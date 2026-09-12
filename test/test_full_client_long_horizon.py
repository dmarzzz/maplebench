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
