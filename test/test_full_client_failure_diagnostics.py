"""Private failure receipts retain bounded causes without authorizing inputs or scores."""
import hashlib,json,os,re,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_bridge import FullClientBridge,ControlError,CAPTURE_FAILURE_CODES,capture_failure,input_failure

ROOT=Path(__file__).resolve().parents[1]
class FailureDiagnosticsTests(unittest.TestCase):
 def diagnostic(self,**changes):
  return dict(schema_version=1,run_id='a'*32,policy_id='post-render-encoded-frame-v1',code='duplicate_quantized_timestamp',clock_origin='encoder_start',elapsed_ms=50,first_frame_offset_ms=10,last_frame_offset_ms=40,rendered_frames=3,submitted_frames=2,encoded_frames=2)|changes
 def bridge(self,folder):
  b=FullClientBridge(folder);(Path(folder)/('a'*32)).mkdir(mode=0o700)
  b.client='test';b.run.update(id='a'*32,client='test',status='running',nativeAcceptance={'capture_duration_policy':{'id':'post-render-encoded-frame-v1'}})
  return b
 def frame(self,**changes):
  return {'client':'test','ageMs':0,'renderAgeMs':0,'observation':{'ready':True,'character':{'x':0,'y':0,'hp':100,'maxHp':100,'mp':10,'maxMp':20,'exp':10,'level':180,'mapId':1,'alive':True},'monsters':[]}}|changes
 def test_exact_first_capture_receipt_is_durable_and_repeat_is_unchanged(self):
  with tempfile.TemporaryDirectory() as tmp:
   b=self.bridge(tmp);value=self.diagnostic();b.frame(self.frame(captureFailure=value))
   p=Path(tmp)/('a'*32)/'capture-failure.json';before=(p.read_bytes(),p.stat().st_mtime_ns)
   b.frame(self.frame(captureFailure=value));self.assertEqual(before,(p.read_bytes(),p.stat().st_mtime_ns))
   v=json.loads(before[0]);self.assertEqual(v['diagnostic'],value);self.assertEqual(v['source'],'browser_reported_diagnostic_unscored')
   self.assertEqual(p.stat().st_mode&0o777,0o600)
   with self.assertRaisesRegex(ControlError,'capture_failure_changed'):b.frame(self.frame(captureFailure=self.diagnostic(code='capture_frame_gap')))
   self.assertEqual(p.read_bytes(),before[0]);self.assertFalse((Path(tmp)/('a'*32)/'recording.json').exists())
 def test_previous_run_diagnostic_does_not_block_next_run_response(self):
  with tempfile.TemporaryDirectory() as tmp:
   b=self.bridge(tmp);result=b.frame(self.frame(captureFailure=self.diagnostic(run_id='b'*32)))
   self.assertEqual(result['run']['id'],'a'*32);self.assertFalse((Path(tmp)/('a'*32)/'capture-failure.json').exists())
 def test_foreign_owner_or_legacy_capture_cannot_create_encoded_diagnostic(self):
  with tempfile.TemporaryDirectory() as tmp:
   b=self.bridge(tmp)
   with self.assertRaisesRegex(ControlError,'capture_failure_owner_mismatch'):b._capture_failure(self.diagnostic(),'other',123)
   b.run['nativeAcceptance']['capture_duration_policy']['id']='post-render-frame-envelope-v1'
   with self.assertRaisesRegex(ControlError,'capture_failure_owner_mismatch'):b.frame(self.frame(captureFailure=self.diagnostic()))
 def test_arbitrary_messages_extra_fields_and_out_of_bounds_are_rejected(self):
  for change in ({'code':'credential=private'}, {'stack':'private'}, {'elapsed_ms':350001}, {'elapsed_ms':True}, {'encoded_frames':4}, {'last_frame_offset_ms':51}, {'code':[]}):
   with self.subTest(change=change),self.assertRaises(ControlError):capture_failure(self.diagnostic(**change))
 def test_initialization_failure_can_have_no_frame_and_no_encoder_clock(self):
  value=self.diagnostic(clock_origin='capture_request',first_frame_offset_ms=None,last_frame_offset_ms=None,rendered_frames=0,submitted_frames=0,encoded_frames=0,code='webcodecs_unavailable')
  self.assertEqual(capture_failure(value),value)
 def test_first_interrupted_input_keeps_owned_command_and_actual_ack_checks(self):
  with tempfile.TemporaryDirectory() as tmp:
   b=self.bridge(tmp);b.pending={'id':'c'*32,'runId':'a'*32,'sent':True,'sentAt':10.,'deadline':12.,'durationMs':300}
   failure={'code':'interrupted_window_blur','keydown_issued':True,'elapsed_ms':300,'remaining_ms':1700}
   with mock.patch('full_client_bridge.time.monotonic',return_value=10.4):b.frame(self.frame(ack={'id':'c'*32,'ok':False,'failure':failure}))
   p=Path(tmp)/('a'*32)/'input-failure.json';raw=p.read_bytes();v=json.loads(raw)
   self.assertEqual(v['command_id'],'c'*32);self.assertEqual(v['client'],failure);self.assertTrue(v['server']['valid_frame']);self.assertTrue(v['server']['enough_hold_time']);self.assertFalse(b.pending['ack']['ok'])
   with mock.patch('full_client_bridge.time.monotonic',return_value=10.5):b.frame(self.frame(ack={'id':'c'*32,'ok':False,'failure':failure|{'code':'capture_unavailable'}}))
   self.assertEqual(raw,p.read_bytes())
 def test_server_rejection_of_positive_ack_is_distinct_from_client_failure(self):
  with tempfile.TemporaryDirectory() as tmp:
   b=self.bridge(tmp);b.pending={'id':'c'*32,'runId':'a'*32,'sent':True,'sentAt':10.,'deadline':12.,'durationMs':300}
   with mock.patch('full_client_bridge.time.monotonic',return_value=10.1):b.frame(self.frame(ack={'id':'c'*32,'ok':True}))
   value=json.loads((Path(tmp)/('a'*32)/'input-failure.json').read_bytes())
   self.assertIsNone(value['client']);self.assertTrue(value['server']['client_ack_ok']);self.assertFalse(value['server']['enough_hold_time']);self.assertFalse(b.pending['ack']['ok'])
 def test_late_matching_ack_is_diagnostic_only_and_cannot_accept_input(self):
  with tempfile.TemporaryDirectory() as tmp:
   b=self.bridge(tmp);b.pending={'id':'c'*32,'runId':'a'*32,'sent':True,'sentAt':10.,'deadline':12.,'durationMs':300}
   failure={'code':'deadline_after_input','keydown_issued':True,'elapsed_ms':2100,'remaining_ms':-100}
   with mock.patch('full_client_bridge.time.monotonic',return_value=12.1):b.frame(self.frame(ack={'id':'c'*32,'ok':False,'failure':failure}))
   value=json.loads((Path(tmp)/('a'*32)/'input-failure.json').read_bytes())
   self.assertFalse(value['server']['before_deadline']);self.assertNotIn('ack',b.pending)
   self.assertEqual(value['client']['code'],'deadline_after_input')
 def test_unmatched_ack_and_arbitrary_failure_cannot_create_receipt(self):
  with tempfile.TemporaryDirectory() as tmp:
   b=self.bridge(tmp);b.pending={'id':'c'*32,'runId':'a'*32,'sent':True,'sentAt':10.,'deadline':12.,'durationMs':300}
   failure={'code':'capture_unavailable','keydown_issued':False,'elapsed_ms':0,'remaining_ms':1700}
   with mock.patch('full_client_bridge.time.monotonic',return_value=10.4):b.frame(self.frame(ack={'id':'d'*32,'ok':False,'failure':failure}))
   self.assertFalse((Path(tmp)/('a'*32)/'input-failure.json').exists())
   for change in ({'code':'private message'},{'remaining_ms':3001},{'elapsed_ms':True},{'keydown_issued':1},{'stack':'private'}):
    with self.assertRaises(ControlError):input_failure(failure|change)
   with self.assertRaises(ControlError):b.frame(self.frame(ack={'id':'c'*32,'ok':True,'failure':failure}))
 @unittest.skipUnless(shutil.which('node'),'Node required for actual browser diagnostic closure')
 def test_browser_preserves_first_safe_code_and_controller_relay_enum_match(self):
  source=(ROOT/'ui/full-client/controller.js').read_text();start=source.index('  const captureFailureCodes');end=source.index('  async function startRecording(',start)
  codes=json.loads(source[source.index('new Set(',start)+8:source.index(');',start)])
  self.assertEqual(set(codes),CAPTURE_FAILURE_CODES)
  js="""const assert=require('node:assert/strict');let captureFailure=null;const run={id:'a'.repeat(32)};const performance={now:()=>150};
const item={encodedMode:true,autoRunId:'a'.repeat(32),startedAt:0,encodedRecorder:{startedAt:100,firstFrameAt:110,lastFrameAt:140,frames:3,submittedFrames:2,outputFrames:2}};
"""+source[start:end]+"""
retainCaptureFailure(item,'duplicate_quantized_timestamp');const first=JSON.stringify(captureFailure);
assert.equal(captureFailure.elapsed_ms,50);assert.equal(captureFailure.last_frame_offset_ms,40);
retainCaptureFailure(item,'encoder_stop_failed');assert.equal(JSON.stringify(captureFailure),first);
captureFailure=null;run.id='b'.repeat(32);retainCaptureFailure({...item,autoRunId:run.id},'private arbitrary message');
const current=JSON.stringify(captureFailure);retainCaptureFailure(item,'encoder_error');assert.equal(JSON.stringify(captureFailure),current);
assert.equal(captureFailure.code,'encoder_failure_unknown');assert.equal(JSON.stringify(captureFailure).includes('private'),false);
"""
  result=subprocess.run([shutil.which('node'),'--max-old-space-size=64','-e',js],capture_output=True,text=True,timeout=5)
  self.assertEqual(result.returncode,0,result.stderr)
if __name__=='__main__':unittest.main()
