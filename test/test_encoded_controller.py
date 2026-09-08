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
        hook=source[source.index('  Module.MapleBenchOnRendered ='):source.index('  async function stopRecording()')]
        stop=source[source.index('  async function stopRecording()'):source.index('  const recordButton =')]
        fixture="""
const assert=require('node:assert/strict');
let capture=null,captureFailure=null,saving=false,pendingUpload=null,closed=false,uploads=0,created=0;
let failStart=false,failStop=false,finish,now=100,wall=1000,stopCalls=0,uploadWait=null;
const aborts=[],stopClocks=[],timers=new Map();let nextTimer=1;
const failureCallbacks=[];
const policy={id:'post-render-encoded-frame-v1'};
const run={id:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',nativeAcceptance:{capture_duration_policy:policy,capture_max_ms:45000}};
const ctx=new Proxy({measureText:()=>({width:0})},{get:(o,k)=>k in o?o[k]:()=>{}});
const document={hidden:false,createElement:()=>({getContext:()=>ctx})};
const game={width:800,height:600},performance={now:()=>now},clientId='client';Date.now=()=>wall;
const notice={},Module={},renderHeader=()=>{},cancelAnimationFrame=()=>{};
const setTimeout=(fn,ms)=>{const id=nextTimer++;timers.set(id,{fn,ms,at:now+ms});return id;};
const clearTimeout=id=>timers.delete(id);
const advance=async ms=>{now+=ms;wall+=ms;for(const [id,timer] of [...timers])if(timer.at<=now&&timers.has(id)){timers.delete(id);timer.fn();}
 for(let i=0;i<12;i++)await Promise.resolve();};
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
 const r={frames:0,failed:false,onRendered(){if(!this.frames){this.startedAt=this.firstFrameAt=now;this.startedWall=this.firstFrameWall=wall;}this.frames++;return true;},
 abort(code){this.failed=true;this.failure=code;aborts.push(code);},
 stop(){stopCalls++;stopClocks.push(now);if(this.failed)return Promise.reject(Error(this.failure));
 if(!this.frames){this.abort('incomplete_capture');return Promise.reject(Error('incomplete_capture'));}
 if(failStop)return Promise.reject(Error('Flush failed'));
 const ended={...measurements,duration_ms:now-this.startedAt,first_frame_offset_ms:0,rendered_frames:this.frames};
 return new Promise(resolve=>{finish=()=>resolve({blob:new Blob(['clip']),encoder_receipt:receipt,measurements:ended});});}};
 return r;
};
const uploadRecording=async()=>{uploads++;assert.equal(pendingUpload.metadata.schema_version,3);if(uploadWait)await uploadWait;};
"""
        result=subprocess.run([shutil.which('node'),'--max-old-space-size=64','-e',fixture+start+hook+stop+
                               '(async()=>{'+checks+'})().then(()=>console.log("LIFECYCLE_CHECKS_COMPLETE"))'
                               '.catch(e=>{console.error(e);process.exitCode=1;});'],
                              capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'LIFECYCLE_CHECKS_COMPLETE',
                         'Lifecycle assertions did not finish; a fake-timer promise may be pending.')

    def test_flush_precedes_upload_and_original_policy_is_retained(self):
        self.run_lifecycle("""
await startRecording('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');assert.equal(created,1);assert.equal(capture.frames,0);
Module.MapleBenchOnRendered();Module.MapleBenchOnRendered();assert.equal(capture.frames,2);
capture.clockVerified=true;capture.clock={id:'clock'};capture.terminalToken='terminal';
const ending=stopRecording();assert.equal(capture.stopping,true);assert.equal(uploads,0);
assert.equal(capture.finalFrameRequested,true);assert.equal(stopCalls,0);
await startRecording('another');assert.equal(created,1);
run.nativeAcceptance.capture_duration_policy={id:'changed'};await advance(100);Module.MapleBenchOnRendered();
assert.equal(stopCalls,1);assert.equal(stopClocks[0],200);assert.equal(capture.frames,3);
Module.MapleBenchOnRendered();assert.equal(capture.frames,3);finish();await ending;
assert.equal(capture,null);assert.equal(uploads,1);
assert.equal(pendingUpload.metadata.capture_duration_policy,policy);
assert.equal(pendingUpload.metadata.encoder_receipt,receipt);
assert.equal(pendingUpload.metadata.first_frame_offset_ms,0);
assert.equal(pendingUpload.metadata.terminal_token,'terminal');
assert.equal(pendingUpload.metadata.interrupted,false);
""")

    def test_unsupported_encoder_has_no_fallback_or_upload(self):
        self.run_lifecycle("""
failStart=true;await startRecording('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');assert.equal(capture,null);
assert.equal(uploads,0);assert.match(notice.textContent,/could not start/);
assert.equal(captureFailure.code,'encoder_failure_unknown');
""")

    def test_armed_controller_waits_for_actual_frame_origin_and_keeps_diagnostic_clock_honest(self):
        self.run_lifecycle("""
await startRecording(run.id);assert.equal(capture.recorderStarted,true);assert.equal(capture.frames,0);
assert.equal(capture.startedAt,100);assert.equal(capture.encodedRecorder.startedAt,undefined);
retainCaptureFailure(capture,'capture_first_frame_timeout');assert.equal(captureFailure.clock_origin,'capture_request');
captureFailure=null;now=401;wall=1301;capture.onRendered();
assert.equal(capture.frames,1);assert.equal(capture.startedAt,401);assert.equal(capture.startedWall,1301);
assert.equal(capture.firstFrameAt,401);assert.equal(capture.firstFrameWall,1301);
retainCaptureFailure(capture,'encoder_error');assert.equal(captureFailure.clock_origin,'encoder_start');
assert.equal(captureFailure.first_frame_offset_ms,0);
failStop=true;const ending=stopRecording();Module.MapleBenchOnRendered();await ending;
""")

    def test_failed_flush_cannot_upload_an_accepted_recording(self):
        self.run_lifecycle("""
await startRecording('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');Module.MapleBenchOnRendered();failStop=true;
const ending=stopRecording();Module.MapleBenchOnRendered();await ending;
assert.equal(capture,null);assert.equal(uploads,0);assert.equal(pendingUpload,null);
assert.match(notice.textContent,/no accepted recording/);
assert.equal(captureFailure.code,'encoder_failure_unknown');
""")

    def test_late_failure_from_old_recorder_cannot_stop_replacement(self):
        self.run_lifecycle("""
await startRecording('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');const oldCapture=capture;
failStop=true;await stopRecording();assert.equal(capture,null);
failStop=false;run.id='b'.repeat(32);await startRecording(run.id);const replacement=capture;
const previousNotice=notice.textContent;
failureCallbacks[0]();
assert.equal(capture,replacement);assert.equal(replacement.stopping,false);
assert.equal(replacement.errors,0);assert.equal(oldCapture.errors,0);
assert.equal(notice.textContent,previousNotice);assert.equal(uploads,0);
Module.MapleBenchOnRendered();Module.MapleBenchOnRendered();
const ending=stopRecording();Module.MapleBenchOnRendered();finish();await ending;assert.equal(uploads,1);
""")

    def test_stop_before_first_frame_closes_without_waiting_for_a_hook(self):
        self.run_lifecycle("""
await startRecording(run.id);await stopRecording();
assert.equal(capture,null);assert.equal(stopCalls,1);assert.equal(uploads,0);
assert.equal(captureFailure.code,'incomplete_capture');assert.equal(timers.size,0);
""")

    def test_unresponsive_renderer_times_out_without_fallback_or_upload(self):
        self.run_lifecycle("""
await startRecording(run.id);Module.MapleBenchOnRendered();const item=capture;
const ending=stopRecording();await stopRecording();assert.equal(item.finalFrameRequested,true);
await advance(1000);await ending;
assert.equal(stopCalls,0);assert.equal(uploads,0);assert.equal(capture,null);
assert.equal(captureFailure.code,'capture_final_frame_timeout');assert.equal(timers.size,0);
assert.equal(item.finalFrameRequested,false);assert.deepEqual(aborts,['capture_final_frame_timeout']);
""")

    def test_wait_and_encoder_finish_share_one_fifteen_second_deadline(self):
        self.run_lifecycle("""
await startRecording(run.id);Module.MapleBenchOnRendered();const ending=stopRecording();
await advance(900);Module.MapleBenchOnRendered();assert.equal(stopCalls,1);
await advance(14100);await ending;
assert.equal(captureFailure.code,'encoder_stop_timeout');assert.equal(uploads,0);assert.equal(capture,null);
finish();await advance(1);assert.equal(uploads,0);assert.equal(timers.size,0);
""")

    def test_request_deadline_survives_stop_even_when_timer_dispatch_is_delayed(self):
        self.run_lifecycle("""
await startRecording(run.id);now=400;wall=1300;Module.MapleBenchOnRendered();
now=45099;wall=45999;const ending=stopRecording();assert.equal(capture.captureDeadlineAt,45100);
assert.ok(timers.has(capture.maxTimer));
now=45101;wall=46001;Module.MapleBenchOnRendered();await ending;
assert.equal(captureFailure.code,'capture_duration_limit');assert.equal(uploads,0);assert.equal(stopCalls,0);
assert.equal(timers.size,0);
""")

    def test_slow_upload_cannot_fire_an_already_finished_capture_timeout(self):
        self.run_lifecycle("""
let releaseUpload;uploadWait=new Promise(resolve=>{releaseUpload=resolve;});
await startRecording(run.id);Module.MapleBenchOnRendered();const ending=stopRecording();
Module.MapleBenchOnRendered();finish();await advance(1);assert.equal(uploads,1);
await advance(20000);assert.equal(captureFailure,null);assert.equal(timers.size,0);assert.equal(aborts.length,0);
releaseUpload();await ending;
""")

    def test_owner_change_cannot_finish_or_upload_the_old_capture(self):
        self.run_lifecycle("""
await startRecording(run.id);Module.MapleBenchOnRendered();const old=capture;const ending=stopRecording();
capture={autoRunId:'b'.repeat(32),stopping:false,errors:0};run.id=capture.autoRunId;
const replacement=capture;notice.textContent='new owner';old.onRendered();await ending;
assert.equal(capture,replacement);assert.equal(notice.textContent,'new owner');assert.equal(replacement.errors,0);
assert.equal(captureFailure,null);assert.equal(uploads,0);assert.equal(stopCalls,0);
assert.deepEqual(aborts,['capture_owner_changed']);assert.equal(timers.size,0);
""")

    def test_interruption_aborts_an_existing_final_hook_wait_immediately(self):
        self.run_lifecycle("""
await startRecording(run.id);Module.MapleBenchOnRendered();const ending=stopRecording();
capture.hidden=true;await stopRecording();await ending;
assert.equal(capture,null);assert.equal(captureFailure.code,'capture_interrupted');
assert.equal(uploads,0);assert.equal(stopCalls,0);assert.equal(timers.size,0);
""")

    def test_changed_run_cannot_label_the_same_capture_objects_final_frame(self):
        self.run_lifecycle("""
await startRecording(run.id);Module.MapleBenchOnRendered();const item=capture;const ending=stopRecording();
run.id='b'.repeat(32);Module.MapleBenchOnRendered();await ending;
assert.equal(item.frames,1);assert.equal(stopCalls,0);assert.equal(uploads,0);
assert.equal(captureFailure,null);assert.deepEqual(aborts,['capture_owner_changed']);assert.equal(timers.size,0);
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
