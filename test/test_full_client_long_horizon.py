import copy,unittest,tempfile
from test_full_client_adaptive import Harness,MODEL
import full_client_adaptive as a
from full_client_adaptive_evidence import verify_result
from full_client_score import EvidenceError
from full_client_capture import validate_duration_policy,LONG_ENCODED_FRAME_POLICY,ENCODED_FRAME_POLICY
class LongHorizonTests(unittest.TestCase):
 def test_full1800_clock_and_final_program_keep_original_deadline(self):
  with tempfile.TemporaryDirectory() as d:
   h=Harness(d);h.p=a.long_horizon_protocol(h.p['profile']);h.program_seconds=1000
   trace=h.run(sleep=lambda n:setattr(h,'now',h.now+n))['trace']
   checked=verify_result(h.result(),h.root,protocol=h.p,model=MODEL)
   self.assertEqual(checked['wall_elapsed_ms'],1800000)
   self.assertEqual(trace['horizon_wait']['started_ms'],1795000)
   self.assertEqual(h.programs[-1][1]['deadline'],1795)
   self.assertLessEqual(len(h.api_calls),72)
 def test_explicit_wall_policy_capture_and_budget_bounds(self):
  good=a.long_horizon_protocol(a.DEFAULT_PROTOCOL['profile'])
  for key,value in [('wall_seconds',1799),('wall_seconds',300),('max_api_requests',73),('max_total_tokens',1440001),('capture_duration_policy',ENCODED_FRAME_POLICY)]:
   with self.subTest(key=key),self.assertRaises(a.AdaptiveError):a.validate_protocol(good|{key:value})
  with self.assertRaises(a.AdaptiveError):a.validate_protocol(a.DEFAULT_PROTOCOL|{'wall_seconds':1800})
  self.assertEqual(a.DEFAULT_PROTOCOL['wall_seconds'],300)
  with self.assertRaises(ValueError):validate_duration_policy(LONG_ENCODED_FRAME_POLICY|{'max_duration_ms':1835001})
 def test_uncertain_call_is_not_replayed(self):
  with tempfile.TemporaryDirectory() as d:
   h=Harness(d);h.p=a.long_horizon_protocol(h.p['profile']);calls=[]
   def fail(*args):calls.append(1);h.now+=50;raise TimeoutError()
   trace=h.run(request_api=fail,sleep=lambda n:setattr(h,'now',h.now+n))['trace']
   self.assertEqual(len(calls),1);self.assertEqual(trace['status'],'failed');self.assertEqual(trace['cycles'][0]['api_outcome'],'uncertain')
 def test_encoded1800_ledger_verifies_only_under_new_policy(self):
  import json,hashlib
  from full_client_capture import verify_video_duration
  count=1801;times=[n*1000000 for n in range(count)];durations=[1000000]*1800+[1000];hashes=['d'*64]*count
  ledger={'schema_version':1,'codec':'vp8','timebase_us':1000,'submitted_timestamps_us':times,
    'encoded_timestamps_us':times,'durations_us':durations,'encoded_sha256':hashes,'flushed':True}
  raw=json.dumps(ledger,separators=(',',':'))
  receipt={'schema_version':1,'codec':'vp8','timebase_us':1000,'submitted_frames':count,'encoded_frames':count,
    'flushed':True,'ledger_sha256':hashlib.sha256(raw.encode()).hexdigest(),'ledger_bytes':len(raw),'webm_sha256':'1'*64,'webm_bytes':100000}
  recording={'capture_duration_policy':LONG_ENCODED_FRAME_POLICY,'duration_ms':1800001,'first_frame_offset_ms':0,
    'last_frame_offset_ms':1800000,'wall_clock_drift_ms':0,'interrupted':False,'post_render_capture':True,'rendered_frames':count,'encoder_receipt':receipt,'sha256':'1'*64}
  probe={'duration_ms':1800001,'presentation_extent_ms':1800001,'presentation_span_ms':1800000,
    'last_packet_duration_ms':1,'frames':count,'packet_timestamps_us':times,'packet_durations_us':durations,
    'packet_sha256':hashes,'encoder_ledger_json':raw,'webm_sha256':'1'*64,'webm_bytes':100000}
  verify_video_duration(probe,recording,LONG_ENCODED_FRAME_POLICY)
  with self.assertRaises(ValueError):verify_video_duration(probe,recording|{'capture_duration_policy':ENCODED_FRAME_POLICY},ENCODED_FRAME_POLICY)
  with self.assertRaises(ValueError):verify_video_duration(probe|{'duration_ms':1800004},recording,LONG_ENCODED_FRAME_POLICY)
 def test_trial_requires_explicit_long_discriminator_and_cleanup_reserve(self):
  from full_client_trial import validate_spec,TrialError
  p=a.long_horizon_protocol(a.DEFAULT_PROTOCOL['profile'])
  spec={'schema_version':2,'protocol':a.PROTOCOL,'horizon_seconds':1800,'model':MODEL,
    'scenario_fingerprint':'a'*64,'baseline_sha256':'b'*64,'budgets':{'total_seconds':2400,
    'operation_seconds':2100,'controller_seconds':1800,'max_actions':14400,'max_api_requests':72,
    'max_output_tokens':216000,'max_total_tokens':1440000}}
  self.assertEqual(validate_spec(spec),spec)
  old=dict(spec);old.pop('horizon_seconds')
  with self.assertRaises(TrialError):validate_spec(old)
  with self.assertRaises(TrialError):validate_spec(spec|{'budgets':spec['budgets']|{'total_seconds':1800}})
 def test_video_probe_long_policy_binding_preserves_legacy_bounds(self):
  from full_client_publish import _measure_video_probe
  probe={'streams':[{'width':32,'height':24,'nb_read_frames':1801}],
    'format':{},'packets':[{'pts_time':str(i),'duration_time':'0.001' if i==1800 else '1', 'flags':'K_'} for i in range(1801)]}
  result=_measure_video_probe(probe,maximum_ms=1835000,duration_policy=LONG_ENCODED_FRAME_POLICY)
  self.assertEqual(result['duration_ms'],1800001)
  for kw in ({},{'maximum_ms':1835000},{'maximum_ms':335000,'duration_policy':LONG_ENCODED_FRAME_POLICY}):
   with self.assertRaises(EvidenceError):_measure_video_probe(probe,**kw)
 def test_upload_limit_comes_from_immutable_owner_even_when_current_run_differs(self):
  from full_client_bridge import FullClientBridge,ControlError
  import json
  with tempfile.TemporaryDirectory() as d:
   b=FullClientBridge(d);old='a'*32;folder=b.output/old;folder.mkdir()
   owner={'client':'owner','adaptiveProtocol':a.long_horizon_protocol(a.DEFAULT_PROTOCOL['profile'])}
   (folder/'request.json').write_text(json.dumps(owner))
   b.run={'id':'b'*32,'adaptiveProtocol':a.DEFAULT_PROTOCOL}
   self.assertEqual(b.recording_upload_limits(old,'owner'),(600*1024*1024,180))
   with self.assertRaises(ControlError):b.recording_upload_limits(old,'foreign')
   owner['adaptiveProtocol']['wall_seconds']=1801
   (folder/'request.json').write_text(json.dumps(owner))
   with self.assertRaises(a.AdaptiveError):b.recording_upload_limits(old,'owner')
   owner['adaptiveProtocol']=a.DEFAULT_PROTOCOL
   (folder/'request.json').write_text(json.dumps(owner))
   b.run={'id':old,'adaptiveProtocol':a.long_horizon_protocol(a.DEFAULT_PROTOCOL['profile'])}
   self.assertEqual(b.recording_upload_limits(old,'owner'),(100*1024*1024,60))
 def test_long_program_budget_passes_actual_sdk_validator_without_docker(self):
  import maple_agent
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   h=Harness(d);h.p=a.long_horizon_protocol(h.p['profile']);budgets=[]
   def execute(code,**kwargs):
    budgets.append(kwargs['max_requests'])
    # Exercise the real executor's public validation, then its expired-deadline
    # path. No process may start; the adaptive harness still accounts normal play.
    checked=maple_agent.execute_program(code,{},'http://127.0.0.1:1',deadline=-1,
      max_actions=kwargs['max_actions'],program_seconds=kwargs['program_seconds'],
      max_requests=kwargs['max_requests'])
    self.assertEqual(checked['reason'],'time_limit')
    return h.execute(code,**kwargs)
   with patch.object(maple_agent.subprocess,'Popen',side_effect=AssertionError('no Docker')):
    h.run(execute=execute,sleep=lambda n:setattr(h,'now',h.now+n))
   self.assertEqual(budgets[0],10000)
   self.assertTrue(all(1<=n<=10000 for n in budgets))
   self.assertEqual(h.p['max_sdk_requests'],60000)
   verify_result(h.result(),h.root,protocol=h.p,model=MODEL)
 def test_runtime_loads_exact_long_scenario_and_rejects_old_settlement(self):
  import hashlib
  from test_full_client_runtime import RuntimeTests
  import full_client_runtime as r
  fixture=RuntimeTests();fixture.setUp()
  try:
   p=a.long_horizon_protocol(a.DEFAULT_PROTOCOL['profile'])
   scenario={'id':'long-fixture','protocol':a.PROTOCOL,'adaptive_protocol':p,'program_seconds':1800,
    'reasoning':{'effort':'low'},'instructions_sha256':hashlib.sha256(a.prompt(p).encode()).hexdigest(),
    'trial_budgets':{'max_api_requests':72,'max_actions':14400,'max_output_tokens':216000,
      'max_total_tokens':1440000,'controller_seconds':1800,'operation_seconds':2100},
    'budgets':{'api_requests':72,'output_tokens':216000,'total_tokens':1440000,'program_ms':1800000,
      'run_ms':1835000,'actions':14400,'sdk_requests':60000},
    'settlement_policy':dict(r.LONG_SETTLEMENT_POLICY),'readiness_policy':fixture.policy()}
   fixture.ref('baseline_snapshot',{'account_logged_in':0,'character':{'character_id':10,'account_id':20,'map_id':1,'level':p['profile']['level']}})
   fixture.ref('runtime_manifest',{'schema_version':2,'docker_binding':fixture.binding,
     'working_directory':str(fixture.root),'wz_path':str(fixture.root/'wz')})
   fixture.ref('scenario',scenario);fixture.backend.load_pins()
   self.assertEqual(fixture.backend.settlement_policy()['upload_after_program_ms'],180000)
   fixture.ref('scenario',scenario|{'settlement_policy':r.SETTLEMENT_POLICY})
   with self.assertRaisesRegex(r.RuntimeErrorCode,'invalid_settlement_policy'):fixture.backend.load_pins()
  finally:fixture.tearDown()
