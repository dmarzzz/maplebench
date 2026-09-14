"""Short API skill previews: exact opt-in, real routing, and ordinary lifecycle."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import full_client_skill_preview as preview
from full_client_bridge import FullClientBridge, ControlError, PROMPT
from full_client_skill_toolkit import sdk_scenario
from maple_agent import validate_rpc
from docker_binding_fixture import local_binding


CLASSES = ('hero', 'bowmaster', 'ice_lightning_arch_mage', 'night_lord')


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.p = preview.contract('ice_lightning_arch_mage', 'b' * 64)

    def observation(self):
        return {'ready':True, 'character':{'x':0, 'y':0, 'hp':12000, 'maxHp':12000,
            'mp':16000, 'maxMp':16000, 'exp':0, 'level':180, 'mapId':1, 'alive':True},
            'monsters':[{'objectId':1, 'x':80, 'y':0}]}

    def policy(self):
        return {'schema_version':1, 'expected_map_id':1, 'min_monsters':1,
                'min_samples':3, 'min_span_ms':1000, 'timeout_ms':10000}

    def setup_bridge(self, folder):
        root = Path(folder)
        key = root / 'unused-test-key'
        key.touch(mode=0o600)
        bridge = FullClientBridge(root / 'runs', key)
        bridge.frame({'client':'renderer', 'ageMs':0, 'renderAgeMs':0, 'observation':self.observation()})
        options = {'run_id':'d'*32, 'request_id':'d'*32, 'private':True,
            'total_token_limit':self.p['max_total_tokens'], 'preview_protocol':self.p,
            'trial_context':{'scenario_fingerprint':'a'*64, 'baseline_sha256':'b'*64},
            'docker_image_id':'sha256:'+'c'*64, 'docker_binding':local_binding(self, folder),
            'readiness_policy':self.policy()}
        return bridge, options

    def test_contract_is_exact_and_all_classes_have_named_skill_authority(self):
        for cls in CLASSES:
            protocol = preview.contract(cls, 'b'*64)
            self.assertEqual(preview.validate_protocol(protocol), protocol)
            self.assertEqual(protocol['program_seconds'], 60)
            self.assertEqual(protocol['max_api_requests'], 1)
            self.assertFalse(protocol['publication_eligible'])
            self.assertIsNone(protocol['score'])
            scenario = {'adapter':'full-client', **sdk_scenario(protocol)}
            for skill in protocol['skill_toolkit']['skills']:
                rpc = {'type':'rpc', 'id':1, 'method':'pressKeys', 'args':[[skill['slot']],30]}
                self.assertEqual(validate_rpc(rpc, scenario)[1]['keys'], [skill['slot']])
                self.assertIn(skill['name'], preview.prompt(protocol))
            for mutate in (lambda p:p.update(program_seconds=300), lambda p:p.update(max_api_requests=2),
                           lambda p:p.update(score=1), lambda p:p['skill_toolkit']['skills'].pop(),
                           lambda p:p['profile']['skill_keys'].update(SECONDARY_SKILL='invented')):
                changed = copy.deepcopy(protocol); mutate(changed)
                with self.assertRaisesRegex(ValueError, 'invalid_skill_preview_protocol'):
                    preview.validate_protocol(changed)
        self.assertIn('directional Teleport', preview.prompt(self.p))
        self.assertNotIn('cannot\nteleport', preview.prompt(self.p))
        self.assertIn('top-level await', preview.prompt(self.p))
        self.assertIn('single model response', preview.prompt(self.p))
        self.assertIn('16000/16000', preview.prompt(self.p))
        self.assertIn('100 shared Power Elixirs', preview.prompt(self.p))
        self.assertIn('cannot\nteleport', PROMPT)
        with self.assertRaises(ValueError):
            validate_rpc({'type':'rpc','id':1,'method':'pressKeys','args':[['SKILL_5'],30]},
                         {'adapter':'full-client'})

    def test_private_identity_readiness_and_caps_fail_before_worker_or_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge, options = self.setup_bridge(folder)
            for change in ({'private':False}, {'total_token_limit':32001}, {'trial_context':None},
                           {'readiness_policy':None}, {'duration_seconds':22},
                           {'trial_context':{'scenario_fingerprint':'a'*64,'baseline_sha256':'c'*64}},
                           {'preview_protocol':self.p | {'max_actions':241}}):
                with self.subTest(change=change), mock.patch('full_client_bridge.threading.Thread') as thread:
                    kwargs = {'duration_seconds':60, **options, **change}
                    with self.assertRaises((ControlError, ValueError)):
                        bridge.start('api', 'gpt-6-astra', **kwargs)
                    thread.assert_not_called()
            self.assertFalse((bridge.output / 'requests').exists())

    def test_one_provider_request_uses_preview_prompt_and_emits_unscored_toolkit_receipts(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge, options = self.setup_bridge(folder)
            with tempfile.TemporaryFile() as world, tempfile.TemporaryFile() as queue, \
                    mock.patch('full_client_bridge.threading.Thread'):
                run = bridge.start('api', 'gpt-6-astra', 60,
                    lease_fds=(world.fileno(),queue.fileno()), **options)
            code = "await sdk.pressKeys(['RIGHT','SECONDARY_SKILL'],30); await sdk.pressKeys(['SKILL_5'],100);"
            response = {'id':'synthetic-response', 'model':'gpt-6-astra', 'status':'completed',
                'usage':{'input_tokens':100, 'output_tokens':50, 'total_tokens':150},
                'metadata':{'maplebench_run_id':run['id']}, 'output':[{'type':'message',
                    'content':[{'type':'output_text','text':json.dumps({'note':'test','code':code})}]}]}
            def execute(program, scenario, url, **kwargs):
                self.assertEqual(program, code)
                self.assertEqual(scenario, {'adapter':'full-client', **sdk_scenario(self.p)})
                self.assertEqual((kwargs['program_seconds'], kwargs['max_actions'], kwargs['max_requests']), (60,240,600))
                steps = []
                for keys in (['RIGHT','SECONDARY_SKILL'], ['SKILL_5']):
                    reply = kwargs['request_fn']('/v1/action', {'keys':keys, 'durationMs':30})
                    step = {'kind':'sdk', 'method':'pressKeys', 'args':[keys,30], 'result':reply}
                    kwargs['step_callback'](step); steps.append(step)
                return {'reason':'program_complete', 'actions':2, 'steps':steps, 'error':None}
            def request(url, *args, **kwargs):
                return {'accepted':True,'observation':self.observation()} if url.endswith('/v1/action') else self.observation()
            readiness = {'wait_started_run_ms':0,'qualified_run_ms':0,'policy':self.policy()}
            with mock.patch.object(bridge, 'request', side_effect=request), \
                    mock.patch.object(bridge, '_wait_for_capture'), \
                    mock.patch.object(bridge, '_wait_for_readiness', return_value=(self.observation(),readiness)), \
                    mock.patch.object(bridge, '_readiness_dispatch', return_value={}), \
                    mock.patch('full_client_bridge.bounded_request', return_value=response) as provider, \
                    mock.patch('full_client_bridge.execute_program', side_effect=execute):
                bridge._run(run)
            provider.assert_called_once()
            result = json.loads((bridge.output/run['id']/'result.json').read_text())
            body = json.loads((bridge.output/run['id']/'api-request-body.json').read_text())
            publication = json.loads((bridge.output/run['id']/'publication.json').read_text())
            self.assertEqual(body['instructions'], preview.prompt(self.p))
            self.assertEqual(body['metadata']['maplebench_run_id'], run['id'])
            self.assertEqual(result['source'], preview.SOURCE)
            self.assertEqual(result['protocol'], preview.PROTOCOL)
            self.assertEqual(result['controller']['protocol'], preview.PROTOCOL)
            self.assertEqual(result['previewProtocol'], self.p)
            self.assertEqual(result['controller']['previewProtocol'], self.p)
            self.assertEqual(result['controller']['returnedModel'], 'gpt-6-astra')
            self.assertEqual(result['controller']['status'], 'completed')
            self.assertEqual(result['program']['actions'], 2)
            self.assertEqual(result['model_api_requests'], 1)
            self.assertIn('first_input_acked_ms', result['timeline'])
            self.assertFalse(result['publication_eligible']); self.assertIsNone(result['score'])
            self.assertEqual(publication['run_kind'], 'skill_preview'); self.assertIsNone(publication['score'])
            self.assertEqual(publication['budgets']['run_ms'], 123000)

    def test_runtime_preview_closes_out_real_persistence_bundle_and_cleanup_without_ranking(self):
        from test_full_client_runtime import RuntimeTests
        from full_client_score import SOURCE, verify_trial_bundle
        from full_client_publish import validate_manifest
        harness = RuntimeTests(); harness.setUp()
        try:
            online, events = harness.controller_fixture()
            backend = harness.backend
            arts = backend.state['artifacts']
            arts['baseline'] = backend.artifact('baseline.sql', raw=b'synthetic offline database')
            baseline_sha = arts['baseline']['sha256']
            protocol = preview.contract('ice_lightning_arch_mage', baseline_sha)
            backend.config['baseline'] = {'sha256':baseline_sha}
            backend.scenario.update(preview_protocol=protocol, program_seconds=60,
                id='mage-development', budgets={'actions':240},
                instructions_sha256=hashlib.sha256(preview.prompt(protocol).encode()).hexdigest())
            arts['scenario'] = backend.artifact('scenario.json', backend.scenario)
            scenario_sha = arts['scenario']['sha256']
            backend.config['scenario'] = {'sha256':scenario_sha}
            backend.context['request'].update(schema_version=1, budgets={
                'controller_seconds':62,'max_actions':240,'max_output_tokens':3000,
                'max_total_tokens':32000,'max_api_requests':1},
                scenario_fingerprint=scenario_sha, baseline_sha256=baseline_sha)
            character = {'character_id':10,'account_id':20,'map_id':1,'level':180,'exp':1000,'hp':12000}
            keymap = [[29,5,52],[57,5,53]]
            backend.baseline = {'character':character, 'keymap':keymap}
            backend.state['reset'] = {'run_id':backend.run_id,'baseline_sha256':baseline_sha,
                'world_lock_held':True,'queue_lock_held':True,'server_stopped':True,'verified':True,
                'completed_at_ms':100}
            arts['reset'] = backend.artifact('reset.json',backend.state['reset'])
            backend.state['initial'] = {'schema_version':1,'source':SOURCE,'run_id':backend.run_id,
                'account_logged_in':0,'captured_at_ms':200,'character':character,'keymap':keymap}
            arts['initial_db'] = backend.artifact('initial-db.json',backend.state['initial'])
            backend.state['session']['server_started_at_ms'] = 300
            backend.event('server_started',300); backend.event('login',1000)
            backend.state['invocation_id'] = 'e'*32
            native = Path(backend.state['native_directory']) / 'save.jsonl'
            native.write_text(json.dumps({'schema_version':1,'source':SOURCE,**backend.identity(),
                'kind':'save_committed','committed_at_ms':25000})+'\n')
            harness.host.snapshot.return_value = backend.state['initial'] | {'captured_at_ms':26000,
                'character':character | {'exp':1400}}
            harness.host.command.return_value = b'MapleBench persistence journal initialized\n'
            arts['video'] = backend.artifact('video.webm',raw=b'synthetic placeholder, never published')
            arts['recording'] = backend.artifact('recording.json',{'reviewed':False,'interrupted':None})
            original_metadata = backend.copy_controller_metadata.side_effect
            def metadata():
                original_metadata()
                result = backend.state['result']
                result.update(source=preview.SOURCE, protocol=preview.PROTOCOL, previewProtocol=protocol,
                    model_api_requests=1, publication_eligible=False, score=None,
                    trialContext={'scenario_fingerprint':scenario_sha,'baseline_sha256':baseline_sha})
                result['controller'].update(protocol=preview.PROTOCOL, previewProtocol=protocol)
            backend.copy_controller_metadata.side_effect = metadata
            original_admin = backend.admin
            def admin(*args,**kwargs):
                status = original_admin(*args,**kwargs)
                status['session'].update(pinned=True,captureState='idle')
                return status
            backend.admin = mock.MagicMock(side_effect=admin)
            receipt = backend.run_controller()
            self.assertFalse(online[0]); self.assertLess(events.index('disconnect'), events.index('metadata'))
            self.assertEqual(events.count('start'), 1); self.assertEqual(events.count('disconnect'), 1)
            start = next(call for call in backend.admin.call_args_list if call.args[0]=='start')
            self.assertEqual(start.kwargs['preview_protocol'], protocol)
            self.assertNotIn('adaptive_protocol', start.kwargs)
            self.assertIsNone(backend.trial_protocol())
            self.assertEqual(receipt['api_requests'], 1)
            backend.verify_api_result.assert_called_once_with(preview.prompt(protocol))
            collected = backend.collect_final()
            score = verify_trial_bundle(collected['evidence'],backend.directory,collected['artifacts'])
            self.assertEqual(score['metrics'],{'net_xp':400})
            self.assertTrue(score['artifacts_verified']); self.assertFalse(score['publication_eligible'])
            candidate = json.loads((backend.directory/'publication-candidate.json').read_text())
            self.assertEqual(candidate['run_kind'],'skill_preview')
            self.assertEqual(candidate['previewProtocol'],protocol)
            self.assertIsNone(candidate['score']); self.assertFalse(candidate['publication_eligible'])
            denied = validate_manifest(candidate)
            self.assertFalse(denied['ready'])
            self.assertTrue(any('run_kind' in reason for reason in denied['reasons']))
            denied = validate_manifest(candidate | {'run_kind':'ranked'})
            self.assertFalse(denied['ready'])
            self.assertTrue(any('result.source' in reason for reason in denied['reasons']))
            self.assertEqual(backend.cleanup(),{'clean':True})
            self.assertTrue(backend.state['clean'])
            self.assertEqual(events.count('start'),1); self.assertEqual(events.count('disconnect'),1)
            self.assertGreater(events.index('prepare_wait'),events.index('metadata'))
        finally:
            harness.tearDown()

    def test_runtime_freezes_preview_without_changing_legacy_schema_one(self):
        from test_full_client_runtime import RuntimeTests
        import full_client_runtime as runtime
        harness = RuntimeTests(); harness.setUp()
        try:
            p = self.p
            trial = {'controller_seconds':62,'operation_seconds':180,'max_actions':240,
                     'max_output_tokens':3000,'max_total_tokens':32000,'max_api_requests':1}
            scenario = {'id':'mage-skill-development','program_seconds':60,'reasoning':{'effort':'low'},
                'preview_protocol':p,'instructions_sha256':hashlib.sha256(preview.prompt(p).encode()).hexdigest(),
                'trial_budgets':trial,'settlement_policy':dict(runtime.SETTLEMENT_POLICY),
                'budgets':{'api_requests':1,'output_tokens':3000,'total_tokens':32000,'program_ms':60000,
                           'run_ms':123000,'actions':240,'sdk_requests':600},'readiness_policy':harness.policy()}
            harness.backend.config['baseline'] = {'sha256':'b'*64}
            harness.ref('baseline_snapshot',{'account_logged_in':0,'character':{
                'character_id':10,'account_id':20,'map_id':1,'level':180}})
            harness.ref('runtime_manifest',{'schema_version':2,'docker_binding':harness.binding,
                'working_directory':str(harness.root),'wz_path':str(harness.root/'wz')})
            harness.ref('scenario',scenario); harness.backend.load_pins()
            self.assertEqual(harness.backend.preview_contract(),p)
            self.assertIsNone(harness.backend.trial_protocol())
            for change in ({'protocol':'full-client-adaptive-pilot-v1'}, {'instructions_sha256':'0'*64},
                           {'program_seconds':22}, {'trial_budgets':trial|{'max_total_tokens':33000}}):
                harness.ref('scenario',scenario|change)
                with self.assertRaises(runtime.RuntimeErrorCode):harness.backend.load_pins()
            harness.host.command.assert_not_called(); harness.host.admin.assert_not_called()
        finally:
            harness.tearDown()

    def test_private_session_forwards_exact_preview_with_inherited_guards(self):
        from test_full_client_session import SessionTests
        harness = SessionTests(); harness.setUp()
        try:
            harness.frame(); waiting = harness.coordinator.dispatch({'op':'prepare_wait'})
            harness.frame('waiting',ack=waiting['transitionId'])
            connecting = harness.coordinator.dispatch({'op':'connect'})
            harness.frame('game',ack=connecting['transitionId'])
            request = {'op':'start','run_id':'a'*32,'request_id':'a'*32,'model':'gpt-6-astra',
                'duration_seconds':60,'total_token_limit':32000,'preview_protocol':self.p,
                'trial_context':{'scenario_fingerprint':'c'*64,'baseline_sha256':'b'*64},
                'docker_image_id':'sha256:'+'d'*64,'docker_binding':{'synthetic':'forwarding-only'},
                'readiness_policy':self.policy()}
            with mock.patch.object(harness.bridge,'start',return_value={'id':'a'*32}) as start, \
                    mock.patch('full_client_session.validate_guard_descriptors') as guards:
                harness.coordinator.dispatch(request,(10,11))
            guards.assert_called_once_with((10,11),None,None)
            self.assertEqual(start.call_args.args,('api','gpt-6-astra',60))
            self.assertEqual(start.call_args.kwargs['preview_protocol'],self.p)
            self.assertEqual(start.call_args.kwargs['lease_fds'],(10,11))
            self.assertTrue(start.call_args.kwargs['private'])
            self.assertNotIn('adaptive_protocol',start.call_args.kwargs)
        finally:
            harness.tearDown()

    def test_preview_serving_module_is_frozen_only_for_opted_in_runtime(self):
        from test_full_client_runtime import RuntimeTests
        import full_client_runtime as runtime
        harness = RuntimeTests(); harness.setUp()
        try:
            harness.web_fixture()
            with mock.patch.object(runtime.pwd,'getpwnam',return_value=mock.MagicMock(pw_uid=1234)):
                harness.backend.web_identity({'MainPID':'123','User':'synthetic'})
            harness.backend.scenario = {'preview_protocol':self.p}
            with self.assertRaisesRegex(runtime.RuntimeErrorCode,'serving_sources_not_frozen'):
                harness.backend.web_identity({'MainPID':'123','User':'synthetic'})
            path = Path(harness.backend.config['web_script']).parent/'full_client_skill_preview.py'
            path.write_text('synthetic preview module')
            harness.backend.manifest['extra_files'].append({'path':str(path),'sha256':'1'*64})
            with mock.patch.object(runtime.pwd,'getpwnam',return_value=mock.MagicMock(pw_uid=1234)):
                harness.backend.web_identity({'MainPID':'123','User':'synthetic'})
        finally:
            harness.tearDown()

    @unittest.skipUnless(shutil.which('node'), 'Node is required for the actual key dispatcher')
    def test_actual_browser_routes_teleport_and_extra_spell_slots(self):
        from test_full_client_controller import ControllerTests
        ControllerTests().run_dispatch('run.previewProtocol='+json.dumps(self.p)+r''';
(async()=>{
 run.id='new';capture.autoRunId='new';
 await executeInput({id:'teleport',runId:'new',keys:['RIGHT','SECONDARY_SKILL'],durationMs:30},clock+1000);
 assert.ok(keyCodes.some(x=>x[0]==='KeyS'&&x[1]==='keydown'));
 await executeInput({id:'ice-strike',runId:'new',keys:['SKILL_5'],durationMs:30},clock+1000);
 assert.ok(keyCodes.some(x=>x[0]==='KeyG'&&x[1]==='keydown'));
 delete run.previewProtocol;
 await assert.rejects(executeInput({id:'legacy-forbidden',runId:'new',keys:['SKILL_5'],durationMs:30},clock+1000),/invalid_input_keys/);
 assert.equal(acknowledgement.ok,false);
})().catch(error=>{console.error(error);process.exitCode=1});
''')


if __name__ == '__main__':
    unittest.main()
