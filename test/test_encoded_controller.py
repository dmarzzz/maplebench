"""Exercise the opt-in controller's real recording lifecycle with bounded fakes."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node required')
class EncodedControllerTests(unittest.TestCase):
    def run_lifecycle(self, checks):
        source=(Path(__file__).resolve().parents[1]/'ui/full-client/controller.js').read_text()
        start=source[source.index('  const captureFailureCodes ='):source.index('  Module.MapleBenchOnRendered =')]
        stop=source[source.index('  async function stopRecording()'):source.index('  const recordButton =')]
        fixture="""
const assert=require('node:assert/strict');
let capture=null,captureFailure=null,saving=false,pendingUpload=null,closed=false,uploads=0,created=0;
let failStart=false,failStop=false,finish;
const failureCallbacks=[];
const policy={id:'post-render-encoded-frame-v1'};
const run={id:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',nativeAcceptance:{capture_duration_policy:policy,capture_max_ms:45000}};
const ctx=new Proxy({measureText:()=>({width:0})},{get:(o,k)=>k in o?o[k]:()=>{}});
const document={hidden:false,createElement:()=>({getContext:()=>ctx})};
const game={width:800,height:600},performance={now:()=>100},clientId='client';Date.now=()=>1000;
const notice={},renderHeader=()=>{},setTimeout=()=>1,clearTimeout=()=>{},cancelAnimationFrame=()=>{};
const ink={},leafPath='',Path2D=function(){},fitText=()=>{};
const view=()=>({mode:'Native',state:'Running',hp:'HP',mp:'MP',xp:'XP',keys:'Keys',hpFraction:1,mpFraction:1,alive:true});
const relayConnected=true;
const MediaRecorder={isTypeSupported:()=>{throw Error('Unexpected legacy fallback');}};
const measurements={start_wall_ms:1000,end_wall_ms:1200,duration_ms:200,
 first_frame_wall_ms:1010,last_frame_wall_ms:1190,first_frame_offset_ms:10,last_frame_offset_ms:190,
 rendered_frames:2,max_frame_gap_ms:180};
const receipt={schema_version:1,codec:'vp8',flushed:true};
const createPostRenderRecorder=async(canvas,options)=>{
 failureCallbacks.push(options.onFailure);
 created++;assert.equal(options.maxDurationMs,45000);if(failStart)throw Error('Unsupported');
 const r={startedAt:100,startedWall:1000,frames:0,onRendered(){this.frames++;return true;},
 stop(){if(failStop)return Promise.reject(Error('Flush failed'));
 return new Promise(resolve=>{finish=()=>resolve({blob:new Blob(['clip']),encoder_receipt:receipt,measurements});});}};
 return r;
};
const uploadRecording=async()=>{uploads++;assert.equal(pendingUpload.metadata.schema_version,3);};
"""
        result=subprocess.run([shutil.which('node'),'--max-old-space-size=64','-e',fixture+start+stop+
                               '(async()=>{'+checks+'})().catch(e=>{console.error(e);process.exitCode=1;});'],
                              capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_flush_precedes_upload_and_original_policy_is_retained(self):
        self.run_lifecycle("""
await startRecording('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');assert.equal(created,1);assert.equal(capture.frames,0);
capture.onRendered();capture.onRendered();assert.equal(capture.frames,2);
capture.clockVerified=true;capture.clock={id:'clock'};capture.terminalToken='terminal';
const ending=stopRecording();assert.equal(capture.stopping,true);assert.equal(uploads,0);
await startRecording('another');assert.equal(created,1);
run.nativeAcceptance.capture_duration_policy={id:'changed'};finish();await ending;
assert.equal(capture,null);assert.equal(uploads,1);
assert.equal(pendingUpload.metadata.capture_duration_policy,policy);
assert.equal(pendingUpload.metadata.encoder_receipt,receipt);
assert.equal(pendingUpload.metadata.first_frame_offset_ms,10);
assert.equal(pendingUpload.metadata.terminal_token,'terminal');
assert.equal(pendingUpload.metadata.interrupted,false);
""")

    def test_unsupported_encoder_has_no_fallback_or_upload(self):
        self.run_lifecycle("""
failStart=true;await startRecording('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');assert.equal(capture,null);
assert.equal(uploads,0);assert.match(notice.textContent,/could not start/);
assert.equal(captureFailure.code,'encoder_failure_unknown');
""")

    def test_failed_flush_cannot_upload_an_accepted_recording(self):
        self.run_lifecycle("""
await startRecording('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');capture.onRendered();failStop=true;await stopRecording();
assert.equal(capture,null);assert.equal(uploads,0);assert.equal(pendingUpload,null);
assert.match(notice.textContent,/no accepted recording/);
assert.equal(captureFailure.code,'encoder_failure_unknown');
""")

    def test_late_failure_from_old_recorder_cannot_stop_replacement(self):
        self.run_lifecycle("""
await startRecording('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');const oldCapture=capture;
failStop=true;await stopRecording();assert.equal(capture,null);
failStop=false;await startRecording('replacement');const replacement=capture;
const previousNotice=notice.textContent;
failureCallbacks[0]();
assert.equal(capture,replacement);assert.equal(replacement.stopping,false);
assert.equal(replacement.errors,0);assert.equal(oldCapture.errors,0);
assert.equal(notice.textContent,previousNotice);assert.equal(uploads,0);
replacement.onRendered();replacement.onRendered();
const ending=stopRecording();finish();await ending;assert.equal(uploads,1);
""")


class EncodedPlaybackCueTests(unittest.TestCase):
    def test_cue_accounts_for_first_post_render_origin(self):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
        from full_client_adaptive_publication import playback_cue
        result={'timeline':{'program_started_ms':1000,'program_ended_ms':5000,
                            'first_input_started_ms':1500,'first_input_acked_ms':1600}}
        recording={'start_ms':0,'end_ms':6000,'duration_ms':6000,'timing_uncertainty_ms':5,
                   'timing_method':'browser_monotonic_duration_with_measured_clock_offset'}
        self.assertEqual(playback_cue(result,recording,1)['start_ms'],1250)
        recording.update(capture_duration_policy={'id':'post-render-encoded-frame-v1'},first_frame_offset_ms=100)
        self.assertEqual(playback_cue(result,recording,1)['start_ms'],1150)
        self.assertIsNone(playback_cue(result,recording,0))
        recording['first_frame_offset_ms']=2000
        self.assertIsNone(playback_cue(result,recording,1))
