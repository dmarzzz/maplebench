"""Synthetic baseline contract/execution tests; no API or native qualification."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import full_client_adaptive as adaptive
import full_client_baseline as baseline
from full_client_adaptive_evidence import verify_result
from full_client_skill_toolkit import sdk_scenario, toolkit
from maple_agent import validate_rpc
from test_full_client_adaptive import Harness, MODEL


class BaselineTests(unittest.TestCase):
    def make(self):
        return baseline.protocol(toolkit('ice_lightning_arch_mage'))

    def test_explicit_toolkit_and_unchanged_outer_envelope(self):
        with self.assertRaises(TypeError):baseline.protocol()
        p = self.make()
        old = adaptive.encoded_capture_cohort_protocol(adaptive.DEFAULT_PROTOCOL['profile'])
        old['profile'] = copy.deepcopy(p['profile'])
        old['skill_toolkit'] = toolkit('ice_lightning_arch_mage')
        self.assertEqual({k: v for k, v in p.items() if k != 'baseline_policy'}, old)
        self.assertEqual(p['baseline_policy']['id'], baseline.POLICY_ID)
        self.assertNotEqual(adaptive.digest(p), adaptive.digest(old))
        self.assertEqual(adaptive.prompt(p), baseline.prompt(p))

    def test_policy_rejects_mixed_horizons_budgets_history_and_reflection(self):
        edits = [
            lambda p: p.update(wall_seconds=120),
            lambda p: p.update(wall_seconds=1800),
            lambda p: p.update(program_seconds=30),
            lambda p: p.update(max_api_requests=16),
            lambda p: p.update(max_total_tokens=120000),
            lambda p: p.update(horizon_policy=adaptive.FINAL_SLOT_POLICY),
            lambda p: p.update(progression_policy=adaptive.NATIVE_PROGRESSION_POLICY),
            lambda p: p.pop('skill_toolkit'),
            lambda p: p['baseline_policy'].update(id='full-client-adaptive-baseline-v2'),
            lambda p: p['baseline_policy'].update(explicit_reflection=True),
            lambda p: p['baseline_policy'].update(candidate_search=True),
            lambda p: p['baseline_policy'].update(cross_run_memory=True),
            lambda p: p['baseline_policy'].update(recent_programs=3),
            lambda p: p['baseline_policy'].update(recent_sdk_receipts_per_program=6),
            lambda p: p['baseline_policy'].update(schema_version=True),
            lambda p: p['baseline_policy'].update(accepted=True),
            lambda p: p['capture_duration_policy'].update(max_wall_drift_ms=100),
        ]
        for edit in edits:
            with self.subTest(edit=edit):
                p = self.make(); edit(p)
                with self.assertRaises(ValueError):adaptive.validate_protocol(p)
                with self.assertRaises(ValueError):baseline.prompt(p)

    def test_toolkit_profile_or_skill_mutation_cannot_keep_identity(self):
        for field, replacement in [('level', 1), ('skill_id', 1234567), ('slot', 'D')]:
            p = self.make(); p['skill_toolkit']['skills'][0][field] = replacement
            with self.assertRaises(ValueError):adaptive.validate_protocol(p)
        p = self.make(); p['profile']['skill_keys']['PRIMARY_SKILL'] = 'Brandish'
        with self.assertRaises(ValueError):adaptive.validate_protocol(p)
        self.assertNotEqual(baseline.fingerprint(self.make()),
                            baseline.fingerprint(baseline.protocol(toolkit('hero'))))

    def test_named_controls_are_accepted_but_physical_aliases_are_not(self):
        p = self.make(); scenario = {'adapter':'full-client', **sdk_scenario(p)}
        for skill in p['skill_toolkit']['skills']:
            validate_rpc({'type':'rpc', 'id':1, 'method':'pressKeys',
                          'args':[[skill['slot']], 100]}, scenario)
        for key in ('D', 'KeyD', '2201002', 'Teleport', 'BRANDISH'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_rpc({'type':'rpc', 'id':1, 'method':'pressKeys',
                              'args':[[key], 100]}, scenario)
        prompt = adaptive.prompt(p)
        self.assertIn('maximize verified signed native net XP', prompt)
        self.assertNotIn('physical key', prompt)
        self.assertNotIn('press A, S, D and F', prompt)
        for code in ('KeyA', 'KeyD', 'KeyZ'):self.assertNotIn(code, prompt)

    def test_baseline_and_existing_prompt_bytes_are_frozen(self):
        p = self.make()
        self.assertEqual(hashlib.sha256(adaptive.prompt(p).encode()).hexdigest(),
                         '7bec13690f88f015f3a2a3e5af405f2779149717d6a305297464281e97212183')
        profile = adaptive.DEFAULT_PROTOCOL['profile']
        cases = [
            (adaptive.DEFAULT_PROTOCOL, '849bd390ac42e6580a179e0bede00c72cb631e5274d94b80a2b88006d8663efb'),
            (adaptive.encoded_capture_cohort_protocol(profile), '97b455b6346204bffeb735c44166933ddd6938ef670bdf1428e45b94abfa1889'),
            (adaptive.final_slot_cohort_protocol(profile), '99041e348b4285981be91202d1dc18e4805080cef4a5d1c482a828cb90ccebb3'),
            (adaptive.long_horizon_protocol(profile), 'd971b837d6eb3f4c1bdb7d312b77843216246a718dde924525862644557e1c84'),
        ]
        for protocol, expected in cases:
            self.assertEqual(hashlib.sha256(adaptive.prompt(protocol).encode()).hexdigest(), expected)

    def test_returned_copies_cannot_mutate_future_policy(self):
        original = copy.deepcopy(adaptive.DEFAULT_PROTOCOL)
        kit = toolkit('ice_lightning_arch_mage'); before = copy.deepcopy(kit)
        p = baseline.protocol(kit); p['baseline_policy']['cross_run_memory'] = True
        p['skill_toolkit']['resources']['potion']['quantity'] = 9999
        policy = baseline.policy(); policy['explicit_reflection'] = True
        self.assertEqual(kit, before)
        self.assertEqual(adaptive.DEFAULT_PROTOCOL, original)
        self.assertFalse(self.make()['baseline_policy']['cross_run_memory'])
        self.assertFalse(baseline.policy()['explicit_reflection'])

    def test_actual_controller_requests_use_baseline_prompt_and_normal_feedback(self):
        with tempfile.TemporaryDirectory() as folder:
            h = Harness(folder); h.p = self.make()
            h.code = "await sdk.pressKeys(['ATTACK'],100); for(let i=0;i<7;i++) await sdk.observe();"
            original_execute = h.execute
            def execute(code, **kwargs):
                result = original_execute(code, **kwargs)
                for rpc_id in range(2, 9):
                    step = {'kind':'sdk', 'rpcId':rpc_id, 'method':'observe',
                            'args':[], 'result':h.observation()}
                    result['steps'].append(step); kwargs['step_callback'](step)
                result['rpcRequests'] = 8
                return result
            h.execute = execute
            value = h.run(sleep=lambda seconds: setattr(h, 'now', h.now + seconds))
            trace = value['trace']
            self.assertEqual(trace['status'], 'completed')
            self.assertEqual(trace['reason'], 'request_window_closed')
            self.assertEqual(trace['timing']['wall_elapsed_ms'], 300000)
            self.assertGreater(len(h.api_calls), 2)
            self.assertEqual(len(h.api_calls), len(h.programs))
            self.assertEqual(trace['counters']['api_requests_started'], len(h.api_calls))
            for index, (body, timeout) in enumerate(h.api_calls):
                self.assertEqual(timeout, 50)
                self.assertEqual(body['instructions'], baseline.prompt(h.p))
                self.assertEqual(body['reasoning'], {'effort':'low'})
                state = json.loads(body['input'])
                self.assertEqual(set(state), {'observation', 'recent_programs',
                    'remaining_seconds', 'remaining_actions', 'remaining_sdk_requests', 'cycle_index'})
                self.assertLessEqual(len(state['recent_programs']), 2)
                if index:
                    self.assertNotEqual(state['observation'], json.loads(h.api_calls[index-1][0]['input'])['observation'])
                    for recent in state['recent_programs']:
                        self.assertEqual(set(recent), {'note','code','execution','recent_receipts'})
                        self.assertEqual(recent['code'], h.code)
                        self.assertEqual(len(recent['recent_receipts']), 5)
                        self.assertEqual([s['rpcId'] for s in recent['recent_receipts']], [4,5,6,7,8])
                else:self.assertEqual(state['recent_programs'], [])
            self.assertTrue(all(code == h.code and args['program_seconds'] == 20 for code, args in h.programs))
            self.assertGreater(trace['horizon_wait']['ended_ms'] - trace['horizon_wait']['started_ms'], 0)
            checked = verify_result(h.result(), h.root, protocol=h.p, model=MODEL)
            self.assertEqual(checked['wall_elapsed_ms'], 300000)
            self.assertIsNone(checked['authoritative_peak_xp_per_minute'])
            relabeled = copy.deepcopy(h.p); relabeled.pop('baseline_policy')
            with self.assertRaises(ValueError):
                verify_result(h.result(), h.root, protocol=relabeled, model=MODEL)

    def test_uncertain_provider_is_not_reflected_repaired_or_replayed(self):
        with tempfile.TemporaryDirectory() as folder:
            h = Harness(folder); h.p = self.make()
            def fail(*args):h.api_calls.append(args); raise TimeoutError('private detail')
            trace = h.run(request_api=fail)['trace']
            self.assertEqual(trace['status'], 'failed')
            self.assertEqual(trace['cycles'][0]['api_outcome'], 'uncertain')
            self.assertEqual(len(h.api_calls), 1)
            self.assertEqual(h.programs, [])
            self.assertNotIn('private detail', json.dumps(trace))

    def test_independent_runs_start_with_empty_agent_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('first', 'second'):
                out = Path(folder) / name; out.mkdir()
                h = Harness(out); h.p = self.make()
                h.run(sleep=lambda seconds: setattr(h, 'now', h.now + seconds))
                self.assertEqual(json.loads(h.api_calls[0][0]['input'])['recent_programs'], [])

    def test_v1_level_change_stops_before_another_model_request(self):
        with tempfile.TemporaryDirectory() as folder:
            h = Harness(folder); h.p = self.make()
            original_observe = h.observation
            def observe():
                value = original_observe()
                if h.programs:value['character']['level'] = 181
                return value
            h.observation = observe
            trace = h.run()['trace']
            self.assertEqual(trace['status'], 'failed')
            self.assertEqual(trace['reason'], 'adaptive_profile_level_mismatch')
            self.assertEqual(len(h.api_calls), 1)
            self.assertEqual(len(h.programs), 1)


if __name__ == '__main__':unittest.main()
