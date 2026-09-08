"""Deterministic full-horizon receipts; no provider, services or game inputs."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_full_client_adaptive import Harness, MODEL
import full_client_adaptive as adaptive
from full_client_adaptive_evidence import verify_result
from full_client_adaptive_publication import public_cycles
from full_client_score import EvidenceError


class HorizonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.h=Harness(self.temp.name,calls=16)
        self.h.p['horizon_policy']=copy.deepcopy(adaptive.FULL_HORIZON_POLICY)
        self.phases=[]
    def tearDown(self):self.temp.cleanup()
    def sleep(self,seconds):self.h.now+=seconds
    def run_horizon(self,**overrides):
        return self.h.run(sleep=self.sleep,on_phase=lambda **p:self.phases.append(p),**overrides)
    def check(self):return verify_result(self.h.result(),self.h.root,protocol=self.h.p,model=MODEL)
    def resave(self,result):result['adaptiveTrace']=self.h.save('adaptive.json',result['adaptive'])

    def test_last_request_has_full_timeout_and_recording_clock_reaches_horizon(self):
        trace=self.run_horizon()['trace'];checked=self.check()
        self.assertEqual(trace['reason'],'request_window_closed')
        self.assertEqual(len(self.h.api_calls),8);self.assertEqual(len(self.h.programs),8)
        self.assertTrue(all(timeout==50 for _,timeout in self.h.api_calls))
        self.assertEqual(trace['cycles'][-1]['timing']['api_started_ms'],210000)
        self.assertEqual(checked['wall_elapsed_ms'],300000)
        wait=trace['horizon_wait'];self.assertEqual(wait['started_ms'],240000)
        self.assertEqual(wait['ended_ms'],300000);self.assertEqual(wait['counters'],trace['counters'])
        self.assertEqual(self.phases[-1]['phase'],'waiting_for_deadline')
        self.assertTrue(all('monsters' not in sample and 'ready' not in sample for sample in wait['samples']))
        self.assertLess(len(json.dumps(wait)),20000)
        public=public_cycles(self.h.result(),checked)
        self.assertEqual(public['horizon_wait']['observation_count'],len(wait['samples']))
        self.assertNotIn('samples',public['horizon_wait'])

    def test_full_fifty_second_last_response_is_allowed_without_deadline_timeout(self):
        self.h.api_seconds=50
        trace=self.run_horizon()['trace'];self.check()
        self.assertEqual(len(self.h.api_calls),4)
        self.assertEqual(trace['cycles'][-1]['timing']['api_ended_ms'],260000)
        self.assertEqual(trace['horizon_wait']['started_ms'],280000)
        self.assertEqual(trace['timing']['wall_elapsed_ms'],300000)

    def test_each_confirmed_budget_holds_world_without_extra_calls_or_inputs(self):
        for key,value,reason in (('max_api_requests',1,'api_request_limit'),
                                ('max_actions',1,'action_limit'),('max_sdk_requests',1,'sdk_request_limit')):
            with self.subTest(reason=reason):
                self.h=Harness(self.h.root,calls=16)
                self.h.p['horizon_policy']=copy.deepcopy(adaptive.FULL_HORIZON_POLICY)
                self.h.p[key]=value
                trace=self.run_horizon()['trace'];self.check()
                self.assertEqual(trace['reason'],reason);self.assertEqual(trace['timing']['wall_elapsed_ms'],300000)
                self.assertEqual(len(self.h.api_calls),1);self.assertEqual(len(self.h.programs),1)

    def test_token_reservation_after_confirmed_call_holds_without_charging_rejected_request(self):
        self.h.p['max_total_tokens']=13000
        trace=self.run_horizon()['trace'];self.check()
        self.assertEqual(trace['reason'],'token_reservation_limit')
        self.assertEqual(trace['cycles'][-1]['status'],'budget_rejected')
        self.assertEqual(len(self.h.api_calls),1)
        self.assertEqual(trace['counters']['api_requests_started'],trace['counters']['api_responses_confirmed'])
        self.assertEqual(trace['timing']['wall_elapsed_ms'],300000)

    def test_readiness_delay_closes_request_window_before_dispatch(self):
        def phase(**p):
            self.phases.append(p)
            if p['phase']=='requesting' and p['cycle']==7:self.h.now+=16
        value=self.h.run(sleep=self.sleep,on_phase=phase);trace=value['trace'];self.check()
        self.assertEqual(len(self.h.api_calls),7)
        self.assertEqual(trace['cycles'][-1]['status'],'window_closed')
        self.assertEqual(trace['cycles'][-1]['api_outcome'],'not_started')
        self.assertIsNotNone(trace['cycles'][-1]['request'])
        self.assertEqual(trace['counters']['api_requests_started'],7)
        self.assertEqual(trace['reason'],'request_window_closed')
        self.assertEqual(trace['timing']['wall_elapsed_ms'],300000)

    def test_durable_write_delay_never_charges_or_dispatches_a_late_request(self):
        saved=self.h.save;delayed=False
        def save(name,value):
            nonlocal delayed
            ref=saved(name,value)
            if name=='adaptive.json' and len(value['cycles'])==8 and not delayed and 'api_started_ms' in value['cycles'][-1]['timing']:
                self.h.now+=16;delayed=True
            return ref
        trace=self.run_horizon(persist_json=save)['trace'];self.check()
        self.assertEqual(len(self.h.api_calls),7)
        self.assertEqual(trace['counters']['api_requests_started'],7)
        self.assertEqual(trace['cycles'][-1]['api_outcome'],'not_started')
        self.assertNotIn('api_started_ms',trace['cycles'][-1]['timing'])

    def test_model_body_preparation_delay_closes_window_without_a_request_artifact(self):
        original=adaptive.model_decision
        def delayed(*args,**kwargs):
            if len(self.h.api_calls)==7:self.h.now+=16
            return original(*args,**kwargs)
        with patch.object(adaptive,'model_decision',delayed):trace=self.run_horizon()['trace']
        self.check();self.assertEqual(len(self.h.api_calls),7)
        self.assertEqual(trace['cycles'][-1]['status'],'window_closed')
        self.assertIsNone(trace['cycles'][-1]['request'])

    def test_uncertain_request_stays_failed_and_is_never_held_or_retried(self):
        def timeout(*args):
            self.h.api_calls.append(args);self.h.now+=50;raise TimeoutError('private detail')
        trace=self.run_horizon(request_api=timeout)['trace']
        self.assertEqual(trace['status'],'failed');self.assertEqual(trace['reason'],'TimeoutError')
        self.assertEqual(trace['cycles'][0]['api_outcome'],'uncertain')
        self.assertIsNone(trace['horizon_wait']);self.assertEqual(self.h.now,50)
        self.assertEqual(len(self.h.api_calls),1);self.assertNotIn('private detail',json.dumps(trace))

    def test_provider_that_ignores_timeout_is_not_confirmed(self):
        self.h.api_seconds=70;trace=self.run_horizon()['trace']
        self.assertEqual(trace['status'],'failed');self.assertEqual(trace['reason'],'adaptive_request_timeout_overrun')
        self.assertEqual(trace['counters']['api_responses_confirmed'],0)
        self.assertEqual(len(self.h.programs),0);self.assertIsNone(trace['horizon_wait'])

    def test_death_during_passive_wait_is_terminal(self):
        self.h.p['max_api_requests']=1
        def observe(timeout):
            value=self.h.observation()
            if self.h.now>=32:value['character'].update(alive=False,hp=0)
            return value
        trace=self.run_horizon(observe=observe)['trace'];self.check()
        self.assertEqual(trace['reason'],'death');self.assertEqual(self.h.now,32)
        self.assertEqual(len(self.h.api_calls),1);self.assertEqual(len(self.h.programs),1)

    def test_cancel_or_stale_render_during_wait_stops_early(self):
        self.h.p['max_api_requests']=1
        def cancel():
            if self.h.now>=32:raise adaptive.AdaptiveError('cancelled')
        trace=self.run_horizon(cancel_check=cancel)['trace']
        self.assertEqual(trace['status'],'failed');self.assertEqual(trace['reason'],'cancelled')
        self.assertEqual(self.h.now,32)
        self.h=Harness(self.h.root,calls=1);self.h.p['horizon_policy']=copy.deepcopy(adaptive.FULL_HORIZON_POLICY)
        def observe(timeout):
            value=self.h.observation()
            if self.h.now>=31:value['renderAgeMs']=1500
            return value
        trace=self.run_horizon(observe=observe)['trace']
        self.assertEqual(trace['reason'],'adaptive_observation_unavailable');self.assertEqual(self.h.now,31)

    def test_final_observation_is_not_given_a_deadline_shortened_timeout(self):
        self.h.p['max_api_requests']=1;reads=[]
        def observe(timeout):
            reads.append((self.h.now,timeout))
            if self.h.now>=30:
                self.assertEqual(timeout,3);self.assertGreater(300-self.h.now,4)
                self.h.now+=3
            return self.h.observation()
        trace=self.run_horizon(observe=observe)['trace'];self.check()
        self.assertEqual(trace['timing']['wall_elapsed_ms'],300000)
        self.assertLessEqual(reads[-1][0],295)

    def test_wait_evidence_rejects_shortened_clock_changed_counter_stale_or_missing_samples(self):
        self.run_horizon();good=self.h.result()
        for mutate in (
            lambda w:w.update(ended_ms=299000),
            lambda w:w['counters'].update(actions=9),
            lambda w:w['samples'][0].update(renderAgeMs=1500),
            lambda w:w.update(samples=[]),
            lambda w:w['samples'][0].update(monsters=[]),
            lambda w:w.update(started_ms=200000)):
            with self.subTest(mutate=mutate):
                result=copy.deepcopy(good);mutate(result['adaptive']['horizon_wait']);self.resave(result)
                with self.assertRaises(EvidenceError):verify_result(result,self.h.root,protocol=self.h.p,model=MODEL)
        self.resave(good);self.check()

    def test_near_deadline_loop_entry_does_not_start_shortened_observation(self):
        execute=self.h.execute
        def late_cleanup(code,**kwargs):
            value=execute(code,**kwargs);self.h.now=298;return value
        def observe(timeout):
            self.assertLess(self.h.now,298)
            return self.h.observation()
        trace=self.run_horizon(execute=late_cleanup,observe=observe)['trace']
        self.assertEqual(trace['reason'],'request_window_closed')
        self.assertEqual(trace['status'],'completed');self.assertEqual(self.h.now,300)
        self.assertEqual(trace['horizon_wait']['samples'],[])
        # This exercises deadline handling, not valid execution duration evidence.
        with self.assertRaises(EvidenceError):self.check()

    def test_request_timeout_or_cutoff_cannot_be_forged(self):
        self.run_horizon();good=self.h.result()
        for key,value in (('request_timeout_seconds',49),('requested_model','gpt-5.6-sol')):
            result=copy.deepcopy(good);result['adaptive']['cycles'][-1][key]=value;self.resave(result)
            with self.assertRaises(EvidenceError):verify_result(result,self.h.root,protocol=self.h.p,model=MODEL)

    def test_policy_is_exact_opt_in_and_old_prompt_identity_does_not_change(self):
        plain=copy.deepcopy(self.h.p);plain.pop('horizon_policy')
        old=adaptive.prompt(plain);new=adaptive.prompt(self.h.p)
        self.assertTrue(new.startswith(old));self.assertIn('75 seconds',new)
        self.assertNotEqual(hashlib.sha256(old.encode()).digest(),hashlib.sha256(new.encode()).digest())
        for mutate in (lambda p:p['horizon_policy'].update(request_timeout_seconds=49),
                       lambda p:p['horizon_policy'].update(passive_observation_interval_ms=True),
                       lambda p:p.update(horizon_policy=True)):
            p=copy.deepcopy(self.h.p);mutate(p)
            with self.assertRaises(adaptive.AdaptiveError):adaptive.validate_protocol(p)


if __name__=='__main__':unittest.main()
