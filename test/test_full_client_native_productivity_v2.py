"""Offline three-minute SDK, capture, and ownership tests; no live experiment."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import full_client_native as native
import full_client_native_xp_inventory as inventory
from full_client_capture import ENCODED_FRAME_POLICY, capture_receipt, verify_video_duration
from full_client_publish import EvidenceError, _measure_video_probe, _probe_video, verify_capture_bundle
from full_client_skill_toolkit import sdk_scenario
from maple_agent import validate_rpc
import test_full_client_native as native_tests
import test_full_client_native_productivity as old_tests
import test_full_client_native_xp_inventory as inventory_tests

V1_PINS={
 'hero|active':['ae272654a9425d51aa2dd07565ad206090c34780a055a444c028872cf201dd8b','ecd43a1d490797ab50c40caf931bf3781bae9964653e221206d780a2fcc6cfeb'],
 'hero|idle':['2455ed341f18e4d148df5c999ccc3d7290fc3dc5556eea7038033955c59a04cd','f2866cf2f287cd3c025b0c82662901439a1b54239ce18cad24f3de1a242e1400'],
 'bowmaster|active':['60662a04daa43015524a89a357025f4269828f286095b0bde16e78b646309f6c','1f989f30d08bf4bdcfecb63c20ae418caa7eeb8490604aca6346bee5459b14ab'],
 'bowmaster|idle':['3ada25be693d6de6c8ee69b384ebbbf8c490f77a042c84b37cb6f6b357c1ce36','f2866cf2f287cd3c025b0c82662901439a1b54239ce18cad24f3de1a242e1400'],
 'ice_lightning_arch_mage|active':['b56e1e2fa711c7d7d25e266c641114ff4f63ebc131b65ed3e54d0d188e8a3485','dd9af4c8ba22411ab8e17ed273ebff52cc76bb40470ea0cf458f16b2f627d1b1'],
 'ice_lightning_arch_mage|idle':['32020e63e69492ec9a3f9e8357f5df56450d6c08100dd91f07aba54a8336f045','f2866cf2f287cd3c025b0c82662901439a1b54239ce18cad24f3de1a242e1400'],
 'night_lord|active':['2ea7e215f25050c0cbd0f823df05930e42c8471db3ff5c0c9d23de4fa271beec','dd9af4c8ba22411ab8e17ed273ebff52cc76bb40470ea0cf458f16b2f627d1b1'],
 'night_lord|idle':['46a0908a5f7eac258bd42a8c865ff1af8ee9d0fcae6844a8c5ac21a06fd4a04b','f2866cf2f287cd3c025b0c82662901439a1b54239ce18cad24f3de1a242e1400'],
}


def capture_fixture(duration_ms=180000):
    fixture=native_tests.encoded_native_fixture()
    count=duration_ms//100
    timestamps=[i*100000 for i in range(count)]
    durations=[100000]*(count-1)+[(duration_ms-2)*1000-timestamps[-1]]
    ledger={'schema_version':1,'codec':'vp8','timebase_us':1000,'flushed':True,
            'submitted_timestamps_us':timestamps,'encoded_timestamps_us':timestamps,
            'durations_us':durations,'encoded_sha256':['d'*64]*count}
    raw=json.dumps(ledger,separators=(',',':'))
    receipt={'schema_version':1,'codec':'vp8','timebase_us':1000,'submitted_frames':count,
             'encoded_frames':count,'flushed':True,'ledger_sha256':hashlib.sha256(raw.encode()).hexdigest(),
             'ledger_bytes':len(raw),'webm_sha256':'d'*64,'webm_bytes':12345}
    fixture.value.update(duration_ms=duration_ms,end_wall_ms=10020+duration_ms,
                         last_frame_wall_ms=10022+timestamps[-1]/1000,
                         last_frame_offset_ms=2+timestamps[-1]/1000,
                         rendered_frames=count,max_frame_gap_ms=100,encoder_receipt=receipt)
    fixture.terminal['serverIssuedAtMs']=20000+duration_ms-100
    fixture.raw_probe={'streams':[{'width':800,'height':720,'nb_read_frames':str(count)}],
        'format':{'tags':{'MAPLEBENCH_ENCODER_LEDGER_V1':raw}},
        'packets':[{'pts_time':str(t/1000000),'duration_time':str(d/1000000),
                    'flags':'__','data_hash':'SHA256:'+'d'*64} for t,d in zip(timestamps,durations)]}
    return fixture


class ProductivityV2Tests(unittest.TestCase):
    class_id='bowmaster'

    def config(self,control='active'):
        return native.contract(self.class_id,'a'*64,protocol=native.PRODUCTIVITY_V2_PROTOCOL,control=control)

    def run_code(self,mode='normal',control='active'):
        return old_tests.ProductivityTests.run_code(self,mode,control)

    def helper(self):
        helper=native_tests.NativeTests();helper.setUp();self.addCleanup(helper.doCleanups)
        return helper

    def test_all_v1_contract_and_program_bytes_stay_exact(self):
        for key,pins in V1_PINS.items():
            cls,control=key.split('|')
            value=native.contract(cls,'a'*64,protocol=native.PRODUCTIVITY_PROTOCOL,control=control)
            self.assertEqual([hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest(),
                              hashlib.sha256(native.program(value).encode()).hexdigest()],pins)

    def test_explicit_caps_cannot_be_mutated_or_misidentified(self):
        value=self.config()
        self.assertEqual(tuple(value[k] for k in ('wall_seconds','max_actions','max_sdk_requests','capture_max_ms')),
                         (180,256,900,185000))
        self.assertEqual(value['capture_duration_policy'],ENCODED_FRAME_POLICY)
        for change in ({'wall_seconds':120},{'wall_seconds':181},{'max_actions':257},
                       {'max_sdk_requests':901},{'capture_max_ms':185001},
                       {'id':native.PRODUCTIVITY_PROTOCOL},{'control':'custom'}):
            with self.subTest(change=change),self.assertRaises(ValueError):native.validate_contract(value|change)
        for key in ('PRIMARY_SKILL','BUFF_1','SKILL_7','HP_POTION'):
            validate_rpc({'type':'rpc','id':1,'method':'pressKeys','args':[[key],100]},
                         {'adapter':'full-client',**sdk_scenario(value)})
        for key in ('D','BRANDISH'):
            with self.assertRaises(ValueError):
                validate_rpc({'type':'rpc','id':1,'method':'pressKeys','args':[[key],100]},
                             {'adapter':'full-client',**sdk_scenario(value)})

    def test_all_four_active_and_idle_programs_target176s_with_safe_tail(self):
        for cls in native.PROFILES:
            self.class_id=cls
            for control in ('active','idle'):
                with self.subTest(cls=cls,control=control):
                    result=self.run_code(control=control)
                    self.assertIsNone(result['error'])
                    self.assertGreaterEqual(result['now'],176000)
                    self.assertLess(result['now'],177000)
                    self.assertLessEqual(result['calls'],900)
                    self.assertLessEqual(len(result['actions']),256)
                    self.assertTrue(all(action['at']<172500 for action in result['actions']))
                    if control=='idle':self.assertEqual(result['actions'],[])
                    else:self.assertGreater(len(result['actions']),0)
        self.class_id='bowmaster'

    def test_targeting_potions_early_death_and_failed_ack_preserve_behavior(self):
        for mode in ('height','cross','empty','dead'):
            self.assertFalse(any(row['keys']==['PRIMARY_SKILL'] for row in self.run_code(mode)['actions']),mode)
        self.assertTrue(any(row['keys']==['HP_POTION'] for row in self.run_code('potion')['actions']))
        old_tests.ProductivityTests.test_negative_ack_aborts_without_input_retry(self)
        self.assertLess(self.run_code('dead')['now'],5000)
        self.assertLess(self.run_code('dead',control='idle')['now'],1000)
        result=self.run_code('normal')
        self.assertTrue(any(row['keys']==['PRIMARY_SKILL'] for row in result['actions']))
        self.assertTrue(all(row['keys']!=['LEFT'] for row in result['actions']))

    def test_private_bridge_dispatches_once_and_worker_has_zero_api(self):
        helper=self.helper();value=self.config();options=helper.options|{'native_acceptance':value}
        with patch('full_client_bridge.threading.Thread'):
            for mode,model,seconds in (('script',None,120),('script',None,181),('api','gpt-6-astra',180)):
                with self.assertRaisesRegex(ValueError,'native_acceptance_private_contract_required'):
                    helper.bridge.start(mode,model,seconds,**options)
            first=helper.bridge.start('script',None,180,**options)
            self.assertEqual(helper.bridge.start('script',None,180,**options)['id'],first['id'])
        def execute(code,scenario,url,**kwargs):
            self.assertEqual(code,native.program(value))
            self.assertEqual({key:scenario[key] for key in sdk_scenario(value)},sdk_scenario(value))
            self.assertEqual((kwargs['program_seconds'],kwargs['max_actions'],kwargs['max_requests']),(180,256,900))
            step={'kind':'sdk','rpcId':1,'method':'pressKeys','args':[['PRIMARY_SKILL'],100],
                  'result':{'accepted':True,'observation':helper.observation}}
            kwargs['step_callback'](step)
            return {'reason':'program_complete','error':None,'actions':1,'actionAttempts':1,'rpcRequests':1,'steps':[step]}
        with patch.object(helper.bridge,'_wait_for_capture'),patch.object(helper.bridge,'request',return_value=helper.observation),\
             patch('full_client_bridge.execute_program',side_effect=execute),\
             patch('full_client_bridge.model_decision',side_effect=AssertionError('no model call')),\
             patch('full_client_bridge.read_private_file',side_effect=AssertionError('no key read')):
            helper.bridge._run(first)
        folder=helper.bridge.output/first['id'];result=json.loads((folder/'result.json').read_bytes())
        self.assertEqual(result['controller']['status'],'completed');self.assertEqual(result['model_api_requests'],0)
        self.assertIsNone(result['score']);self.assertIsNone(result['api']);self.assertFalse(result['publication_eligible'])
        self.assertFalse((folder/'api-request.json').exists());self.assertFalse(helper.bridge.leases)

    def test_inventory_collection_and_restore_do_not_grant_xp_qualification(self):
        helper=inventory_tests.InventoryTests()
        for cls in native.PROFILES:
            _,raw,items=helper.fixture(cls)
            for control in ('active','idle'):
                value=native.contract(cls,hashlib.sha256(raw).hexdigest(),protocol=native.PRODUCTIVITY_V2_PROTOCOL,control=control)
                self.assertEqual(inventory.expected(value,raw,character_id=5,account_id=2),items)
                snapshot=helper.snapshot(value,items,'after_restore',300)
                args=dict(native=value,baseline_sql=raw,identity=helper.identity,runtime_manifest_sha256=helper.runtime_hash)
                self.assertEqual(inventory.verify_restored(snapshot,**args),{'inventory_restored':True,'class_accepted':False})
                with self.assertRaisesRegex(ValueError,'toolkit_owner_required'):
                    inventory.verify_triplet(snapshot,snapshot,snapshot,**args,session={},reset={},final_db={})
        with tempfile.TemporaryDirectory() as directory:
            backend=helper.backend(Path(directory).resolve())
            backend.native=native.contract(backend.native['class_id'],backend.native['baseline_sha256'],protocol=native.PRODUCTIVITY_V2_PROTOCOL,control='idle')
            deadline=backend.host.deadline
            receipt=inventory.collect_owned(backend,'after_logout')
            self.assertEqual(receipt['protocol'],native.PRODUCTIVITY_V2_PROTOCOL)
            backend.disconnect.assert_called_once();self.assertEqual(backend.host.deadline,deadline)

    def test_existing_private_session_forwards_exact180s_and_owned_contract(self):
        from full_client_session import SessionCoordinator
        helper=self.helper();value=self.config()
        coordinator=SessionCoordinator(helper.bridge,{'world':str(helper.root/'world'),'queue':str(helper.root/'queue')})
        coordinator.owner='test';coordinator.page='game';coordinator.desired='game'
        coordinator.acknowledged=True;coordinator.last_seen=time.monotonic()
        request={'op':'start_native','run_id':'b'*32,'request_id':'b'*32,'native_acceptance':value,
                 'docker_image_id':helper.options['docker_image_id'],'docker_binding':helper.options['docker_binding'],
                 'lock_paths':coordinator.lock_paths}
        with patch('full_client_session.validate_guard_descriptors') as validate,\
             patch.object(helper.bridge,'start',return_value={}) as start:
            coordinator.dispatch(request,tuple(helper.fds))
            validate.assert_called_once();self.assertEqual(start.call_args.args,('script',None,180))
            self.assertEqual(start.call_args.kwargs['native_acceptance'],value)
        with self.assertRaisesRegex(ValueError,'invalid_native_acceptance_request'):
            coordinator.dispatch(request|{'model':'gpt-6-astra'},tuple(helper.fds))

    def test_180s_encoded_capture_bundle_and_explicit185s_decoder_boundary(self):
        helper=self.helper();value=self.config('idle');fixture=capture_fixture()
        owner=fixture.owner|{'protocol':value['id'],'mode':'script','model':None,'nativeAcceptance':value}
        refs={}
        def artifact(name,data):
            raw=json.dumps(data).encode();path=helper.root/(name+'.json');path.write_bytes(raw)
            refs[name]={'path':path.name,'sha256':hashlib.sha256(raw).hexdigest()}
        for name,data in (('capture',fixture.value),('capture_ready',fixture.anchor),('capture_clock',fixture.clock),('capture_terminal',fixture.terminal)):
            artifact(name,data)
        recording=capture_receipt(fixture.value,owner,fixture.anchor,fixture.clock,fixture.terminal)|{'sha256':'d'*64,'capture_sha256':refs['capture']['sha256']}
        artifact('recording',recording)
        result={'protocol':value['id'],'nativeAcceptance':value,'model_api_requests':0,'trialContext':None,'api':None,
                'controller':owner|{'returnedModel':None},'timing':{'startedAtMs':20000,'endedAtMs':199500},
                'timeline':{'api_started_ms':None,'api_ended_ms':None,'program_started_ms':100,'program_ended_ms':179500}}
        manifest={'result':result,'video':recording,'artifacts':refs}
        self.assertFalse(verify_capture_bundle(manifest,helper.root)['interrupted'])
        probe=_measure_video_probe(fixture.raw_probe,maximum_ms=185000,duration_policy=ENCODED_FRAME_POLICY)
        probe.update(webm_sha256='d'*64,webm_bytes=12345)
        verify_video_duration(probe,recording,ENCODED_FRAME_POLICY)
        with self.assertRaises(EvidenceError):_measure_video_probe(fixture.raw_probe)
        with self.assertRaises(EvidenceError):_measure_video_probe(capture_fixture(185100).raw_probe,maximum_ms=185000,duration_policy=ENCODED_FRAME_POLICY)
        with self.assertRaises(ValueError):
            capture_receipt(fixture.value|{'duration_ms':185001},owner,fixture.anchor,fixture.clock,fixture.terminal)
        result['controller']['model']='gpt-6-astra'
        with self.assertRaisesRegex(EvidenceError,'cannot carry a model identity'):verify_capture_bundle(manifest,helper.root)

    def test_decoder_policy_refusal_precedes_any_subprocess(self):
        with patch('full_client_publish.subprocess.run',side_effect=AssertionError('must not launch decoder')):
            for maximum,policy in ((185000,None),(185001,ENCODED_FRAME_POLICY)):
                with self.assertRaises(EvidenceError):
                    _probe_video(Path('/missing-video.webm'),'d'*64,maximum_ms=maximum,duration_policy=policy)

    def test_explicit185s_probe_keeps_capped_transport_and_legacy125s_rejection(self):
        import full_client_publish as publication
        fixture=capture_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic-not-a-run.webm'
            payload=b'inert test bytes; the subprocess result below is synthetic'
            path.write_bytes(payload);digest=hashlib.sha256(payload).hexdigest()
            def decoder(command,**kwargs):
                self.assertEqual(command[:7],['ffprobe','-v','error','-threads','1','-err_detect','explode'])
                self.assertEqual(kwargs['timeout'],30)
                self.assertIs(kwargs['preexec_fn'],publication._video_probe_limits)
                self.assertEqual(kwargs['env'],{'PATH':'/usr/bin:/bin','LC_ALL':'C'})
                self.assertEqual(len(kwargs['pass_fds']),1)
                kwargs['stdout'].write(json.dumps(fixture.raw_probe).encode())
                return SimpleNamespace(returncode=0)
            with patch('full_client_publish.subprocess.run',side_effect=decoder):
                probe=_probe_video(path,digest,maximum_ms=185000,duration_policy=ENCODED_FRAME_POLICY)
                self.assertEqual(probe['webm_sha256'],digest)
                self.assertEqual(probe['presentation_extent_ms'],179998)
                with self.assertRaises(EvidenceError):_probe_video(path,digest)

    def test_model_trial_gate_cannot_promote_scripted_successor(self):
        from full_client_trial import TrialError,validate_spec
        with self.assertRaisesRegex(TrialError,'unsupported_protocol'):
            validate_spec({'schema_version':2,'protocol':native.PRODUCTIVITY_V2_PROTOCOL,'model':'gpt-6-astra',
                           'scenario_fingerprint':'a'*64,'baseline_sha256':'b'*64,'budgets':{}})


if __name__=='__main__':unittest.main()
