"""Opt-in controller level changes bound to native synthetic ledger receipts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import full_client_adaptive as adaptive
from full_client_adaptive_evidence import verify_result
from full_client_score import EvidenceError
from full_client_xp_windows import verify_bundle
from test_full_client_adaptive import Harness, MODEL
import test_full_client_xp_windows as fixtures
import test_full_client_xp_runtime as runtime_tests
import test_full_client_xp_experiment as plan_tests


class ProgressionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BundleTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.h=Harness(self.fixture.root,calls=16)
        self.h.p['horizon_policy']=copy.deepcopy(adaptive.FULL_HORIZON_POLICY)
        self.h.p['progression_policy']=copy.deepcopy(adaptive.NATIVE_PROGRESSION_POLICY)
        original=self.h.observation
        def observation():
            value=original()
            if self.h.now>=25:value['character'].update(level=181,exp=0)
            return value
        self.h.observation=observation
    def run_progression(self,level=181):
        def sleep(seconds):self.h.now+=seconds
        original=self.h.observation
        def observation():
            value=original()
            if self.h.now>=25:value['character']['level']=level
            return value
        self.h.observation=observation
        self.h.run(sleep=sleep);result=self.h.result();f=self.fixture
        self.assertEqual(result['adaptive']['status'],'completed')
        f.save('controller_result',result)
        scenario=json.loads((f.root/f.arts['scenario']['path']).read_text())
        scenario['adaptive_protocol']=self.h.p;ref=f.save('scenario',scenario)
        f.manifest['scenario_fingerprint']=ref['sha256']
        final=json.loads((f.root/f.arts['final_db']['path']).read_text())
        final['character'].update(level=level,exp=0);f.save('final_db',final)
        self.ledger=fixtures.Ledger(initial={'level':180,'exp':0},origin=999900,threshold=1000000000)
        self.ledger.transition(1025000,level,0);self.ledger.commit(1302000)
        f.save('xp_ledger',self.ledger.bytes(),True)
        return result

    def test_native_level_up_completes_full_horizon_and_reconciles_real_progression(self):
        result=self.run_progression();score=verify_bundle(self.fixture.manifest,self.fixture.root)
        self.assertEqual(result['adaptive']['timing']['wall_elapsed_ms'],300000)
        self.assertEqual(result['adaptive']['cycles'][0]['observation']['character']['level'],180)
        self.assertEqual(result['adaptive']['cycles'][1]['observation']['character']['level'],181)
        self.assertEqual(score['persisted_net_xp'],1000000000)
        self.assertEqual(score['complete_windows'],20);self.assertEqual(score['task_score'],4000000000)
        self.assertFalse(score['publication_eligible'])

    def test_native_level_cap_is_supported_without_counting_discarded_xp(self):
        self.run_progression(level=200)
        score=verify_bundle(self.fixture.manifest,self.fixture.root)
        self.assertEqual(score['persisted_net_xp'],20000000000)
        self.assertEqual(score['complete_windows'],20)

    def test_death_does_not_extend_a_short_trace_or_create_zero_windows(self):
        self.h.execution_edit=lambda e:e|{'reason':'death'}
        result=self.run_progression()
        self.assertEqual(result['adaptive']['reason'],'death')
        self.assertEqual(result['adaptive']['timing']['wall_elapsed_ms'],30000)
        with self.assertRaises(EvidenceError):verify_bundle(self.fixture.manifest,self.fixture.root)

    def test_progression_cannot_be_approved_by_ordinary_adaptive_verifier(self):
        result=self.run_progression()
        for context in (None,{}, {'verified':True}):
            with self.subTest(context=context),self.assertRaises(EvidenceError):
                verify_result(result,self.h.root,protocol=self.h.p,model=MODEL,native_progression=context)

    def test_late_native_level_change_cannot_explain_earlier_client_levels(self):
        self.run_progression();self.ledger.mutate(1,lambda row:row.update(wall_ms=1100000,elapsed_ns=100100000000))
        self.fixture.save('xp_ledger',self.ledger.bytes(),True)
        with self.assertRaises(EvidenceError):verify_bundle(self.fixture.manifest,self.fixture.root)

    def test_missing_or_unrelated_ledger_cannot_authorize_level_changes(self):
        self.run_progression();self.ledger.mutate(1,lambda row:row.update(account_id=10))
        self.fixture.save('xp_ledger',self.ledger.bytes(),True)
        with self.assertRaises(EvidenceError):verify_bundle(self.fixture.manifest,self.fixture.root)
        self.fixture.save('xp_ledger',b'',True)
        with self.assertRaises(EvidenceError):verify_bundle(self.fixture.manifest,self.fixture.root)

    def test_changed_contract_or_final_native_state_cannot_be_substituted(self):
        self.run_progression();f=self.fixture
        final=json.loads((f.root/f.arts['final_db']['path']).read_text());final['character']['level']=182
        f.save('final_db',final)
        with self.assertRaises(EvidenceError):verify_bundle(f.manifest,f.root)
        final['character']['level']=181;f.save('final_db',final)
        f.manifest['experience_table_sha256']='0'*64
        with self.assertRaises(EvidenceError):verify_bundle(f.manifest,f.root)

    def test_unchanged_pilot_still_stops_on_level_change(self):
        self.h.p.pop('progression_policy')
        value=self.h.run()
        self.assertEqual(value['trace']['reason'],'adaptive_profile_level_mismatch')
        self.assertEqual(len(self.h.api_calls),1)

    def test_initial_level_remains_exact_and_out_of_range_level_is_refused(self):
        self.h.now=25;trace=self.h.run()['trace']
        self.assertEqual(trace['reason'],'adaptive_profile_level_mismatch');self.assertEqual(self.h.api_calls,[])
        self.h.now=0
        original=self.h.observation
        def cap():
            value=original()
            if self.h.now>=25:value['character']['level']=201
            return value
        self.h.observation=cap;trace=self.h.run()['trace']
        self.assertEqual(trace['reason'],'adaptive_profile_level_mismatch');self.assertEqual(len(self.h.api_calls),1)

    def test_policy_changes_prompt_and_cannot_be_enabled_without_full_horizon(self):
        prompt=adaptive.prompt(self.h.p);plain=copy.deepcopy(self.h.p);plain.pop('progression_policy')
        self.assertTrue(prompt.startswith(adaptive.prompt(plain)));self.assertIn('initial level is 180',prompt)
        for mutate in (lambda p:p.pop('horizon_policy'),lambda p:p['progression_policy'].update(maximum_level=255),
                       lambda p:p['progression_policy'].update(xp_window_protocol='legacy-full-client-v1')):
            p=copy.deepcopy(self.h.p);mutate(p)
            with self.assertRaises(adaptive.AdaptiveError):adaptive.validate_protocol(p)


class ProgressionAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.t=plan_tests.WindowExperimentTests();self.t.setUp();self.addCleanup(self.t.doCleanups)
    def update_scenario(self,config,change):
        f=config['fixtures'][0];s=json.loads(Path(f['scenario']['path']).read_text());change(s)
        f['scenario']=self.t.fixture.write('fixture0-scenario.json',s)
        b=json.loads((self.t.fixture.root/'fixture0-backend.json').read_text());b['scenario']=f['scenario']
        self.t.fixture.write('fixture0-backend.json',b)
    def test_finite_plan_rejects_malformed_controller_before_admission(self):
        for mutate in (lambda s:s['adaptive_protocol'].update(wall_seconds=30),
                       lambda s:s['adaptive_protocol'].update(program_seconds=300),
                       lambda s:s.update(adaptive_protocol=[]),
                       lambda s:s['adaptive_protocol'].update(max_api_requests=11)):
            config=self.t.configuration();self.update_scenario(config,mutate)
            with self.subTest(mutate=mutate),self.assertRaises(plan_tests.experiment.ExperimentError):
                plan_tests.experiment.build_plan(config)
    def test_progression_plan_requires_explicit_window_identity(self):
        config=self.t.configuration()
        self.update_scenario(config,lambda s:s['adaptive_protocol'].update(progression_policy=copy.deepcopy(adaptive.NATIVE_PROGRESSION_POLICY)))
        plan=plan_tests.experiment.build_plan(config)
        self.assertTrue(all(e['spec']['schema_version']==3 for e in plan['entries']))
        config['fixtures'][0]['protocol']=adaptive.PROTOCOL
        self.update_scenario(config,lambda s:s.pop('xp_window_protocol'))
        with self.assertRaises(plan_tests.experiment.ExperimentError):plan_tests.experiment.build_plan(config)
    def test_runtime_refuses_progression_with_no_window_contract(self):
        backend=object.__new__(runtime_tests.runtime.CosmicRuntime);backend.config={}
        backend.scenario={'protocol':adaptive.PROTOCOL,'adaptive_protocol':copy.deepcopy(adaptive.DEFAULT_PROTOCOL)}
        backend.scenario['adaptive_protocol']['progression_policy']=copy.deepcopy(adaptive.NATIVE_PROGRESSION_POLICY)
        with self.assertRaisesRegex(runtime_tests.runtime.RuntimeErrorCode,'xp_window_opt_in_required'):
            backend.xp_window_contract()


if __name__=='__main__':unittest.main()
