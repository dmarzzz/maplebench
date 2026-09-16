"""Synthetic controller-clock tests; no model, game, or native qualification."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import full_client_skill_controller as controller
import full_client_skill_tasks as tasks
from maple_agent import validate_rpc
from test_full_client_skill_tasks import fixture


class Harness:
    def __init__(self):
        self.now = 0.0
        self.calls, self.programs, self.reservations = [], [], []
        self.api_seconds, self.execution_seconds = 10, 10
        self.response_edit = lambda response: response
        self.save_delay = lambda name: 0
        self.artifacts = {}
        self.contract = tasks.contract('potion-use-v1', 1, fixture('potion-use-v1'),
            purpose='model-development', qualification_sha256='c'*64)
        self.code = "await sdk.pressKeys(['MP_POTION'],100);"

    def observe(self, timeout=3):
        return {'ready': True, 'ageMs': 0, 'renderAgeMs': 0,
                'character': {'alive': True, 'level': 180, 'hp': 12000, 'mp': 1600}}

    def persist(self, name, raw):
        self.now += self.save_delay(name)
        self.artifacts[name] = raw
        import hashlib
        return {'path': name, 'sha256': hashlib.sha256(raw).hexdigest()}

    def save(self, name, value):
        return self.persist(name, controller.encoded(value))

    def reserve(self, **kw):
        self.reservations.append(kw)
        return {'reservation_id': 'synthetic-'+str(len(self.reservations)), 'reserved_microdollars': 1000000}

    def provider(self, url, body, timeout):
        self.calls.append((copy.deepcopy(body), timeout, self.now))
        self.now += self.api_seconds
        value = {'id': 'resp_synthetic_'+str(len(self.calls)), 'status': 'completed',
            'model': body['model'], 'metadata': body['metadata'],
            'usage': {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120},
            'output': [{'type': 'message', 'content': [{'type': 'output_text',
                'text': json.dumps({'note': 'synthetic', 'code': self.code})}]}]}
        return self.response_edit(value)

    def execute(self, code, **kw):
        self.programs.append((code, kw, self.now))
        self.now += min(kw['program_seconds'], self.execution_seconds)
        step = {'kind': 'sdk', 'method': 'pressKeys', 'args': [['MP_POTION'], 100],
                'result': {'accepted': True}}
        kw['step_callback'](step)
        return {'reason': 'program_complete', 'error': None, 'actions': 1,
                'actionAttempts': 1, 'rpcRequests': 1, 'steps': [step]}

    def sleep(self, delay):
        self.now += delay

    def run(self, **overrides):
        args = dict(run_id='a'*32, plan_entry_id='synthetic-potion-v1-r1',
            execution_manifest_sha256='b'*64, model='gpt-6-astra',
            controller_protocol=controller.protocol('potion-use-v1'), task_contract=self.contract,
            initial=self.observe(), observe=self.observe, request_api=self.provider,
            execute=self.execute, persist_json=self.save, persist_bytes=self.persist,
            cancel_check=lambda: None, reserve_request=self.reserve, verified_terminal=lambda: None,
            clock=lambda: self.now, wall_clock=lambda: 1000+self.now, sleep=self.sleep)
        args.update(overrides)
        return controller.run_skill_task(**args)


class SkillControllerTests(unittest.TestCase):
    def test_fixed_protocol_and_admission_boundaries(self):
        p = controller.protocol('potion-use-v1')
        self.assertFalse(controller.offer(p, 14.999)['admitted'])
        self.assertEqual(controller.offer(p, 15)['request_timeout_seconds'], 5)
        self.assertEqual(controller.offer(p, 39)['request_timeout_seconds'], 29)
        self.assertEqual(controller.offer(p, 120)['request_timeout_seconds'], 30)
        for task in controller.EXTENDED_TASKS:
            extended = controller.protocol(task)
            self.assertEqual(extended['max_api_requests'], 12)
            self.assertEqual(controller.offer(extended, 60)['request_timeout_seconds'], 50)
        p['max_api_requests'] = 5
        with self.assertRaises(ValueError): controller.validate_protocol(p)

    def test_clock_counts_inference_then_passively_finishes_full_horizon(self):
        h = Harness(); value = h.run(); t = value['trace']
        self.assertEqual(t['reason'], 'api_request_limit')
        self.assertEqual(t['timing']['wall_elapsed_ms'], 120000)
        self.assertEqual(len(h.calls), 4)
        self.assertEqual(len(h.programs), 4)
        self.assertTrue(all(code == h.code for code, _, _ in h.programs))
        self.assertEqual(h.calls[0][0]['reasoning'], {'effort': 'low'})
        self.assertEqual(h.calls[0][0]['service_tier'], 'default')
        self.assertEqual(t['counters']['actual_total_tokens'], 480)
        self.assertEqual(len(h.reservations), 4)

    def test_long_preparation_is_excluded_but_provider_clock_is_not(self):
        h = Harness()
        h.save_delay = lambda name: 20 if name == 'skill-task-prompt.txt' else 0
        trace = h.run()['trace']
        self.assertEqual(trace['timing']['wall_started_at_ms'], 1020000)
        self.assertEqual(h.now, 140)
        self.assertEqual(trace['timing']['wall_elapsed_ms'], 120000)

    def test_fourth_request_can_use_smaller_legal_timeout(self):
        h = Harness(); h.api_seconds = 25
        # 3*(25+10)=105, so request four has5seconds inference,10reserved.
        def provider(url, body, timeout):
            original = h.api_seconds
            h.api_seconds = min(original, timeout)
            try: return h.provider(url, body, timeout)
            finally: h.api_seconds = original
        trace = h.run(request_api=provider)['trace']
        self.assertEqual([x[1] for x in h.calls], [30, 30, 30, 5])
        self.assertEqual(h.programs[-1][1]['program_seconds'], 5)
        self.assertEqual(trace['timing']['wall_elapsed_ms'], 120000)
        self.assertTrue(all(start+kw['program_seconds'] <= 115 for _,kw,start in h.programs))

    def test_late_provider_is_not_executed_or_retried(self):
        h = Harness(); h.api_seconds = 31
        trace = h.run()['trace']
        self.assertEqual(trace['reason'], 'skill_provider_timeout_overrun')
        self.assertEqual(h.programs, [])
        self.assertEqual(len(h.calls), 1)

    def test_uncertain_provider_keeps_reservation_and_never_replays(self):
        h = Harness()
        def failed(*args):
            h.calls.append(args)
            raise TimeoutError('private provider text must stay private')
        trace = h.run(request_api=failed)['trace']
        self.assertEqual(trace['status'], 'failed')
        self.assertEqual(trace['cycles'][0]['api_outcome'], 'uncertain')
        self.assertEqual(len(h.reservations), 1)
        self.assertEqual(len(h.calls), 1)
        self.assertEqual(h.programs, [])
        self.assertNotIn('private provider text', json.dumps(trace))

    def test_exact_returned_model_and_usage_required(self):
        for mutation, reason in [
            (lambda r: r.update(model='gpt-5.6-sol'), 'skill_api_model_mismatch'),
            (lambda r: r.update(usage=None), 'skill_api_usage_invalid'),
            (lambda r: r.update(metadata={}), 'skill_api_identity_mismatch')]:
            with self.subTest(reason=reason):
                h = Harness()
                def edit(response): mutation(response); return response
                h.response_edit = edit
                trace = h.run()['trace']
                self.assertEqual(trace['reason'], reason)
                self.assertEqual(h.programs, [])

    def test_early_success_requires_bound_immutable_verifier_receipt(self):
        h = Harness()
        def terminal():
            if not h.programs: return None
            return {'run_id':'a'*32, 'plan_entry_id':'synthetic-potion-v1-r1',
                'execution_manifest_sha256':'b'*64, 'status':'success',
                'evidence_sha256':'d'*64, 'completion_ms':15000}
        trace = h.run(verified_terminal=terminal)['trace']
        self.assertEqual(trace['reason'], 'verified_early_success')
        self.assertEqual(len(h.calls), 1)
        self.assertEqual(trace['timing']['wall_elapsed_ms'], 20000)
        h = Harness()
        trace = h.run(verified_terminal=lambda: {'success':True})['trace']
        self.assertEqual(trace['reason'], 'invalid_skill_terminal_verifier')
        self.assertEqual(h.programs, [])

    def test_last_two_programs_and_five_receipts_only(self):
        h = Harness(); h.run()
        recent = json.loads(h.calls[-1][0]['input'])['recent_programs']
        self.assertEqual(len(recent), 2)
        self.assertTrue(all(x['code'] == h.code and len(x['recent_receipts']) <= 5 for x in recent))

    def test_native_control_contract_cannot_dispatch_model(self):
        h = Harness()
        h.contract = tasks.contract('potion-use-v1', 1, fixture('potion-use-v1'))
        with self.assertRaises(ValueError): h.run()
        self.assertEqual(h.calls, [])

    def test_actual_schedule_model_ids_are_valid(self):
        import csv
        path = Path(__file__).resolve().parents[1]/'docs/plans/skill-suite-v1-schedule.csv'
        with path.open() as stream:
            rows = [r for r in csv.DictReader(stream) if r['phase']=='skill-development' and r['task_id']=='potion-use-v1'][:4]
        self.assertEqual(len(rows), 4)
        for row in rows:
            h = Harness()
            result = h.run(plan_entry_id=row['plan_entry_id'], model=row['model'])
            self.assertEqual(result['trace']['counters']['api_requests_started'], 4)
            self.assertEqual(h.calls[0][0]['metadata']['maplebench_plan_entry_id'], row['plan_entry_id'])

    def test_restricted_skill_sdk_rejects_other_actions_and_raw_keys(self):
        for task, key in [('platforming-v1','JUMP'), ('native-teleport-v1','SECONDARY_SKILL'),
                          ('potion-use-v1','MP_POTION')]:
            contract = tasks.contract(task, 1, fixture(task))
            scenario = tasks.sdk_scenario(contract)
            def rpc(method, args): return {'type':'rpc','id':1,'method':method,'args':args}
            self.assertEqual(validate_rpc(rpc('pressKeys', [[key], 100]), scenario)[0], 'pressKeys')
            for method, args in [('pressKeys',[['ATTACK'],100]), ('pressKeys',[['D'],100]),
                                 ('moveTo',[0,0]), ('useItem',[2000005]), ('useSkill',[2201002])]:
                with self.subTest(task=task, method=method, args=args), self.assertRaises(ValueError):
                    validate_rpc(rpc(method,args), scenario)
        scenario['protocol'] = 'full-client-adaptive-pilot-v1'
        with self.assertRaises(ValueError): validate_rpc(rpc('observe',[]), scenario)


if __name__ == '__main__': unittest.main()
