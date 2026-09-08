"""Opt-in XP trial integration, with synthetic files and no native/API actions."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import full_client_runtime as runtime
import full_client_trial as trial
import full_client_xp_windows as windows
import test_full_client_runtime as runtime_tests
import test_full_client_xp_windows as window_tests


def contract(threshold=1000):
    return {'id':windows.PROTOCOL,'window_ms':15000,'wall_seconds':300,
            'experience_table_sha256':hashlib.sha256(json.dumps([threshold]*199,separators=(',',':')).encode()).hexdigest(),
            'normalization':copy.deepcopy(window_tests.NORM)}


class RuntimeWindowTests(unittest.TestCase):
    def setUp(self):
        self.fixture=runtime_tests.RuntimeTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.backend=self.fixture.backend;self.host=self.fixture.host
        self.backend.config['xp_window_protocol']=windows.PROTOCOL
        self.backend.scenario={'protocol':'full-client-adaptive-pilot-v1','xp_window_protocol':contract()}
        self.backend.baseline={'character':{'character_id':10,'account_id':20,'level':1,'exp':900,'map_id':1}}
        self.backend.state['initial']=copy.deepcopy(self.backend.baseline)

    def test_opt_in_requires_both_frozen_scenario_and_private_runtime(self):
        self.assertEqual(self.backend.trial_protocol(),windows.PROTOCOL)
        self.backend.config.pop('xp_window_protocol')
        with self.assertRaisesRegex(runtime.RuntimeErrorCode,'xp_window_opt_in_required'):self.backend.xp_window_contract()
        self.backend.scenario.pop('xp_window_protocol')
        self.assertIsNone(self.backend.xp_window_contract())
        self.assertEqual(self.backend.native_xp_environment(Path('/synthetic')), {})
        self.backend.config['xp_window_protocol']=windows.PROTOCOL
        with self.assertRaisesRegex(runtime.RuntimeErrorCode,'invalid_xp_window_contract'):self.backend.xp_window_contract()

    def test_environment_uses_verified_baseline_and_declared_multipliers(self):
        native=self.fixture.root/'native'
        values=self.backend.native_xp_environment(native)
        self.assertEqual(set(values),set(windows.XP_ENV_NAMES))
        self.assertEqual(values['MAPLEBENCH_XP_BASELINE_EXP'],'900')
        self.assertEqual(values['MAPLEBENCH_XP_JOURNAL'],str(native/'xp.jsonl'))
        self.assertEqual(values['MAPLEBENCH_XP_SIMULATION_DENOMINATOR'],'1')
        self.backend.state['initial']['character']['exp']=899
        with self.assertRaisesRegex(runtime.RuntimeErrorCode,'restored_baseline_mismatch'):self.backend.native_xp_environment(native)

    def test_start_serializes_all_seven_settings_in_owned_dropin(self):
        self.fixture.test_trial_dropin_overrides_inherited_legacy_bot_mode()
        text=Path(self.backend.state['dropin']).read_text()
        for key in windows.XP_ENV_NAMES:
            self.assertIn('Environment="'+key+'=',text)
        stored=json.loads((self.backend.directory/'backend-state.json').read_text())
        self.assertEqual(stored['native_environment']['MAPLEBENCH_XP_BASELINE_LEVEL'],'1')
        self.assertEqual(stored['native_environment']['MAPLEBENCH_XP_SERVER_NUMERATOR'],'1')

    def test_cached_xp_settings_prevent_clean_status_even_without_dropin(self):
        for name in windows.XP_ENV_NAMES:
            unit=self.fixture.offline_unit|{'Environment':name+'=synthetic'}
            self.assertFalse(self.backend.trial_configuration_absent(unit))

    def test_offline_frozen_inventory_requires_native_ledger_class(self):
        jar=self.fixture.root/'synthetic.jar'
        with zipfile.ZipFile(jar,'w') as archive:archive.writestr(runtime.NATIVE_CLASS,b'synthetic')
        self.backend.manifest={'working_directory':str(self.fixture.root),'wz_path':str(self.fixture.root),
            'server_jar':{'path':str(jar),'sha256':hashlib.sha256(jar.read_bytes()).hexdigest()}}
        self.backend.load_pins=MagicMock();self.backend.account_state=MagicMock(return_value=0)
        self.backend.docker_binding=MagicMock(return_value=self.fixture.binding)
        with patch.object(runtime,'verify_manifest'),self.assertRaisesRegex(runtime.RuntimeErrorCode,'native_xp_ledger_class_missing'):
            runtime.CosmicRuntime.frozen(self.backend)
        self.host.admin.assert_not_called()

    def ready_fixture(self):
        self.backend.owned_server=MagicMock(return_value={'MainPID':'123'})
        self.backend.state['invocation_id']='c'*32
        self.backend.config['game_ports']=[8484]
        self.host.listening_ports.return_value={8484}
        self.host.now.return_value=2000
        self.host.command.return_value=(b'MapleBench persistence journal initialized\n'
            b'MapleBench XP ledger initialized\nCosmic is now online after 1 ms\n')
        native=self.fixture.root/'native';native.mkdir();self.backend.state['native_directory']=str(native)
        self.backend.state['server_start_requested_at_ms']=999
        row=json.loads(window_tests.Ledger().bytes());row.update(character_id=10,account_id=20)
        raw=json.dumps(row).encode()+b'\n';(native/'xp.jsonl').write_bytes(raw)
        return native,raw

    def test_readiness_requires_actual_matching_fresh_native_header(self):
        native,raw=self.ready_fixture()
        self.assertTrue(self.backend.server_ready())
        self.assertEqual(self.backend.state['xp_header']['sha256'],hashlib.sha256(raw).hexdigest())
        row=json.loads(raw);row['exp']=899;(native/'xp.jsonl').write_bytes(json.dumps(row).encode()+b'\n')
        with self.assertRaisesRegex(runtime.RuntimeErrorCode,'native_xp_header_invalid'):self.backend.server_ready()
        self.host.admin.assert_not_called()

    def test_missing_marker_header_or_failed_ledger_refuses_before_login(self):
        native,_=self.ready_fixture()
        logs=self.host.command.return_value
        self.host.command.return_value=logs.replace(b'MapleBench XP ledger initialized\n',b'')
        with self.assertRaisesRegex(runtime.RuntimeErrorCode,'native_xp_initialization_missing'):self.backend.server_ready()
        self.host.command.return_value=logs;(native/'xp.jsonl').unlink()
        with self.assertRaisesRegex(runtime.RuntimeErrorCode,'native_xp_header_invalid'):self.backend.server_ready()
        self.host.command.return_value=logs+b'MapleBench XP ledger failed\n'
        with self.assertRaisesRegex(runtime.RuntimeErrorCode,'native_startup_or_save_failed'):self.backend.server_ready()

    def test_unexpected_native_ledger_is_refused_for_legacy_configuration(self):
        self.ready_fixture();self.backend.config.pop('xp_window_protocol');self.backend.scenario.pop('xp_window_protocol')
        with self.assertRaisesRegex(runtime.RuntimeErrorCode,'native_startup_markers_ambiguous'):self.backend.server_ready()

    def test_new_trial_version_reaches_same_single_controller_attempt(self):
        online,events=self.fixture.controller_fixture()
        from full_client_adaptive import DEFAULT_PROTOCOL,prompt
        p=copy.deepcopy(DEFAULT_PROTOCOL)
        self.backend.scenario.update(protocol='full-client-adaptive-pilot-v1',xp_window_protocol=contract(),
            adaptive_protocol=p,program_seconds=300,instructions_sha256=hashlib.sha256(prompt(p).encode()).hexdigest())
        self.backend.context['request'].update(schema_version=3,protocol=windows.PROTOCOL)
        self.backend.verify_adaptive_controller=MagicMock(return_value={'protocol':windows.PROTOCOL,'api_requests':10})
        self.assertEqual(self.backend.run_controller()['protocol'],windows.PROTOCOL)
        self.assertFalse(online[0]);self.assertEqual(events.count('start'),1)
        self.assertLess(events.index('disconnect'),events.index('metadata'))

    def test_old_trial_spec_cannot_start_a_window_run(self):
        self.fixture.controller_fixture()
        from full_client_adaptive import DEFAULT_PROTOCOL,prompt
        p=copy.deepcopy(DEFAULT_PROTOCOL)
        self.backend.scenario.update(protocol='full-client-adaptive-pilot-v1',xp_window_protocol=contract(),
            adaptive_protocol=p,program_seconds=300,instructions_sha256=hashlib.sha256(prompt(p).encode()).hexdigest())
        self.backend.context['request'].update(schema_version=2,protocol='full-client-adaptive-pilot-v1')
        with self.assertRaisesRegex(runtime.RuntimeErrorCode,'bridge_budget_mismatch'):self.backend.run_controller()
        self.host.admin.assert_not_called()


class CollectionWindowTests(unittest.TestCase):
    def setUp(self):
        self.fixture=window_tests.BundleTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.root=self.fixture.root.resolve();self.backend=runtime.CosmicRuntime.__new__(runtime.CosmicRuntime)
        self.backend.host=MagicMock();self.backend.host.now.return_value=1304000
        self.backend.directory=self.root;self.backend.run_id='a'*32
        self.backend.config={'mysql':{'character_id':7,'account_id':9},'xp_window_protocol':windows.PROTOCOL,
            'baseline':{'sha256':self.fixture.manifest['baseline_sha256']},
            'scenario':{'sha256':self.fixture.manifest['scenario_fingerprint']}}
        self.backend.scenario={'protocol':'full-client-adaptive-pilot-v1','xp_window_protocol':contract(1000000000)}
        self.backend.account_state=MagicMock(return_value=0)
        self.backend.persist=MagicMock()
        native=self.root/'native';native.mkdir();self.native=native
        raw=(self.root/self.fixture.arts['xp_ledger']['path']).read_bytes();(native/'xp.jsonl').write_bytes(raw)
        refs=copy.deepcopy(self.fixture.arts)
        for source,target in (('native_save','save'),('baseline_sql','baseline'),('controller_result','result')):
            refs[target]=refs.pop(source)
        self.backend.state={'artifacts':refs,'server_instance_id':'b'*32,'ordinary_logout':{'confirmed':True},
            'native_directory':str(native),'result':self.fixture.result,
            'xp_header':{'sha256':hashlib.sha256(raw.splitlines(keepends=True)[0]).hexdigest()}}

    def test_complete_collection_and_runner_recheck_share_exact_manifest(self):
        evidence,score=self.backend.collect_xp_windows(self.backend.xp_window_contract())
        self.assertEqual(score['complete_windows'],20);self.assertEqual(score['persisted_net_xp'],4500)
        arts=self.backend.state['artifacts']
        self.assertEqual(windows.verify_trial_bundle(evidence,self.root,arts),score)
        self.assertEqual(self.backend.state['xp_window_status']['status'],'verified_native_windows')
        self.assertFalse(score['publication_eligible'])
        bad=copy.deepcopy(evidence);bad['window']['deadline_at_ms']-=1
        with self.assertRaisesRegex(windows.EvidenceError,'window_manifest_receipt_mismatch'):
            windows.verify_trial_bundle(bad,self.root,arts)

    def test_missing_native_file_remains_unknown_without_zero_score(self):
        (self.native/'xp.jsonl').unlink()
        with self.assertRaisesRegex(runtime.RuntimeErrorCode,'xp_window_evidence_incomplete'):
            self.backend.collect_xp_windows(self.backend.xp_window_contract())
        self.assertIsNone(self.backend.state['xp_window_status']['task_score'])
        self.assertEqual(self.backend.state['xp_window_status']['status'],'unknown')
        self.assertNotIn('score',self.backend.state['artifacts'])

    def test_unobserved_header_replacement_is_unknown_even_if_rehashed(self):
        self.backend.state['xp_header']['sha256']='0'*64
        with self.assertRaisesRegex(runtime.RuntimeErrorCode,'xp_window_evidence_incomplete'):
            self.backend.collect_xp_windows(self.backend.xp_window_contract())
        self.assertIsNone(self.backend.state['xp_window_status']['task_score'])

    def test_collection_requires_ordinary_offline_logout(self):
        self.backend.account_state.return_value=2
        with self.assertRaisesRegex(runtime.RuntimeErrorCode,'normal_committed_logout_required'):
            self.backend.collect_xp_windows(self.backend.xp_window_contract())
        self.assertNotIn('xp_manifest',self.backend.state['artifacts'])

    def test_trial_runner_reverifies_window_bytes_and_keeps_new_protocol(self):
        evidence,score=self.backend.collect_xp_windows(self.backend.xp_window_contract())
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);parent=Path(temporary.name).resolve()
        for name in ('world.lock','queue.lock'):(parent/name).touch()
        spec={'schema_version':3,'protocol':windows.PROTOCOL,'model':'gpt-6-astra',
            'scenario_fingerprint':evidence['scenario_fingerprint'],'baseline_sha256':evidence['baseline_sha256'],
            'budgets':{'total_seconds':1200,'operation_seconds':360,'controller_seconds':300,'max_actions':1600,
                'max_api_requests':12,'max_output_tokens':36000,'max_total_tokens':120000}}
        source=self.root;refs=copy.deepcopy(self.backend.state['artifacts']);calls=[]
        class Adapter:
            def perform(inner,operation,context,**kwargs):
                calls.append(operation)
                if operation=='status':return {key:key!='ownership_conflict' for key in trial.STATUS_FIELDS}
                value={'attempt_id':'a'*32}
                if operation=='run_controller':
                    value.update(status='completed',protocol=windows.PROTOCOL,requested_model='gpt-6-astra',returned_model='gpt-6-astra',
                        api_requests=10,output_tokens=100,total_tokens=200,actions=10,controller_ms=300000,recording_complete=True)
                elif operation=='collect_final':
                    shutil.copytree(source,Path(context['attempt_dir']),dirs_exist_ok=True)
                    value.update(evidence=evidence,artifacts=refs)
                elif operation=='cleanup':value['clean']=True
                return value
        legacy=MagicMock(side_effect=AssertionError('legacy verifier must not process XP windows'))
        runner=trial.TrialRunner(parent/'attempts',parent/'world.lock',parent/'queue.lock',Adapter(),verify_bundle=legacy)
        self.assertEqual(runner.run(spec,'a'*32)['status'],'completed')
        self.assertEqual(runner.state['score'],score);self.assertEqual(calls.count('run_controller'),1)
        legacy.assert_not_called()


class SpecWindowTests(unittest.TestCase):
    def test_version_and_protocol_are_not_interchangeable(self):
        spec={'schema_version':3,'protocol':windows.PROTOCOL,'model':'gpt-6-astra',
            'scenario_fingerprint':'1'*64,'baseline_sha256':'2'*64,
            'budgets':{'total_seconds':1200,'operation_seconds':360,'controller_seconds':300,'max_actions':1600,
                'max_api_requests':12,'max_output_tokens':36000,'max_total_tokens':120000}}
        self.assertEqual(trial.validate_spec(spec),spec)
        for version,protocol in ((2,windows.PROTOCOL),(3,'full-client-adaptive-pilot-v1'),(3,None)):
            with self.assertRaises(trial.TrialError):trial.validate_spec(spec|{'schema_version':version,'protocol':protocol})

    def test_window_failure_code_is_safe_but_native_details_are_not_exposed(self):
        self.assertEqual(trial.adapter_failure_code(b'{"error":"xp_window_evidence_incomplete"}'),'xp_window_evidence_incomplete')
        self.assertEqual(trial.adapter_failure_code(b'{"error":"private native path"}'),'adapter_failed')


if __name__=='__main__':unittest.main()
