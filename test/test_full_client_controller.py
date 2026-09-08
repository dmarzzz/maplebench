"""Run the real keyboard dispatcher with a minimal browser fixture."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ControllerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node is required for browser timing regressions')
    def test_capture_offsets_use_post_render_monotonic_clock_and_frozen_policy(self):
        source=(Path(__file__).resolve().parents[1]/'ui/full-client/controller.js').read_text()
        animate=source[source.index('    const animate = () => {'):source.index('    item.onRendered = animate;')]
        metadata=source[source.index('        pendingUpload={runId:'):source.index('        item.chunks=[];')]
        fixture="""
const assert=require('node:assert/strict');
let now=100,wall=1000;const performance={now:()=>now};Date.now=()=>wall;
const item={autoRunId:'trial',startedAt:100,startedWall:1000,recorderStarted:true,frames:0,
 firstFrameAt:null,lastFrameAt:null,firstFrameWall:null,lastFrameWall:null,maxGap:0,chunks:[],
 hidden:false,errors:0,relayLost:false,clockVerified:false,terminalToken:null};
const draw=()=>{},clientId='renderer',capture=item;let pendingUpload;
let durationPolicy={id:'post-render-frame-envelope-v1'};
"""
        checks="""
now=209;wall=1109;animate();now=3399;wall=4299;animate();
const endAt=3500,endWall=4400;
"""+metadata+"""
assert.equal(pendingUpload.metadata.schema_version,2);
assert.equal(pendingUpload.metadata.first_frame_offset_ms,109);
assert.equal(pendingUpload.metadata.last_frame_offset_ms,3299);
assert.equal(pendingUpload.metadata.duration_ms,3400);
assert.equal(pendingUpload.metadata.rendered_frames,2);
durationPolicy=undefined;
"""+metadata+"""
assert.equal(pendingUpload.metadata.schema_version,1);
assert.equal(Object.hasOwn(pendingUpload.metadata,'first_frame_offset_ms'),false);
assert.equal(Object.hasOwn(pendingUpload.metadata,'capture_duration_policy'),false);
"""
        result=subprocess.run([shutil.which('node'),'--max-old-space-size=64','-e',fixture+animate+checks],
                              capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    @unittest.skipUnless(shutil.which('node'),'Node is required for browser timing regressions')
    def test_trial_capture_deadline_and_clock_receive_echo_use_actual_browser_state(self):
        source=(Path(__file__).resolve().parents[1]/'ui/full-client/controller.js').read_text()
        timer='{'+source[source.index('      const captureLimit='):source.index("      notice.textContent='Recording the actual canvas") ]+'}'
        poll=source[source.index('  const poll=async()=>{'):source.index('  const startRun=async')]
        fixture="""
const assert=require('node:assert/strict');
let limit,stopCalls=0;
const run={readinessPolicy:{schema_version:1}}, item={autoRunId:'trial',errors:0};
const stopRecording=()=>{stopCalls++;};
const setTimeout=(fn,ms)=>{limit=ms;return{fn};},clearTimeout=()=>{};
"""
        checks=timer+"""
assert.equal(limit,125000);item.maxTimer.fn();assert.equal(item.errors,1);assert.equal(stopCalls,1);
item.autoRunId=null;
"""+timer+"""
assert.equal(limit,120000);item.autoRunId='demo';delete run.readinessPolicy;
"""+timer+"""
assert.equal(limit,120000);run.adaptiveProtocol={id:'full-client-adaptive-pilot-v1',wall_seconds:300};
"""+timer+"""
assert.equal(limit,335000);delete run.adaptiveProtocol;run.nativeAcceptance={capture_max_ms:45000};
"""+timer+"""
assert.equal(limit,45000);
let closed=false,pollAbort,acknowledgement=null,sessionAck=null,releaseAck=null,relayConnected=true,disconnectedAt=null;
const clientId='renderer',performance={now:()=>100},observe=()=>({ready:true,capturedAt:Date.now()}),
 Module={MapleBenchRenderedAt:Date.now(),MapleBenchHud:null},renderHeader=()=>{},releaseAll=()=>{};
let captureFailure=null;
let capture={clock:{id:'clock',client_received_ms:123456},autoRunId:'trial',recorderStarted:true,frames:17},saving=false,pendingUpload=null;
let sent;
const fetch=async(url,options)=>{sent=JSON.parse(options.body);closed=true;return{ok:false};};
"""+poll+"""
poll().then(()=>{assert.equal(sent.captureClockAck,'clock');assert.equal(sent.captureClockReceivedAtMs,123456);})
 .catch(error=>{console.error(error);process.exitCode=1;});
"""
        result=subprocess.run([shutil.which('node'),'--max-old-space-size=64','-e',fixture+checks],
                              capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    @unittest.skipUnless(shutil.which('node'),'Node is required for the live/captured HUD regression')
    def test_passive_horizon_hud_retains_model_and_displays_actual_wall_clock(self):
        source=(Path(__file__).resolve().parents[1]/'ui/full-client/controller.js').read_text()
        view=source[source.index('  const format = '):source.index('  function renderHeader()')]
        fixture="""
const assert=require('node:assert/strict');
Date.now=()=>251000;
const run={status:'running',mode:'api',model:'gpt-5.6-sol',actions:8,
 adaptivePhase:'waiting_for_deadline',adaptiveStartedAtMs:1000,programStartedAtMs:3000};
const observe=()=>({character:{alive:true,level:180,exp:0,hp:100,maxHp:100,mp:50,maxMp:100}}),fresh=()=>true;
const activeRun=()=>true,relayConnected=true,held=new Map(),physical=new Set(),namesByCode={},skillNamesByCode={};
let baseline={exp:0,level:180},baselineScope='run';
"""
        checks="""
const data=view();assert.equal(data.mode,'OpenAI API · gpt-5.6-sol');
assert.equal(data.state,'Waiting for deadline · game remains live · 8 actions · 250 / 300s');
assert.equal(data.keys,'Keys: none');assert.equal(data.stale,false);
run.status='completed';assert.ok(!view().state.includes('Waiting for deadline'));
run.nativeAcceptance={profile:{class_name:'Bowmaster',skill_keys:{PRIMARY_SKILL:'Hurricane'}}};
held.set('KeyA',1);skillNamesByCode.KeyA='PRIMARY_SKILL';namesByCode.KeyA='Brandish';
assert.equal(view().keys,'Keys: Hurricane');
run.nativeAcceptance.profile={class_name:'Ice/Lightning Arch Mage',skill_keys:{PRIMARY_SKILL:'Chain Lightning'}};
assert.equal(view().keys,'Keys: Chain Lightning');
"""
        result=subprocess.run([shutil.which('node'),'--max-old-space-size=64','-e',fixture+view+checks],
                              capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    def run_dispatch(self, checks):
        source=(Path(__file__).resolve().parents[1]/'ui/full-client/controller.js').read_text()
        dispatch=source[source.index('  const commandDeadline = '):source.index('  const poll=async()=>{')]
        fixture="""
const assert=require('node:assert/strict');
let activeCommand=null,acknowledgement=null,clock=100;
const performance={now:()=>clock};
const skillKeyNames={PRIMARY_SKILL:'KeyA',BUFF_1:'KeyD'},keyNames={LEFT:'ArrowLeft'}, held=new Map(), cancelledRuns=new Set(['cancelled']);
const document={hidden:false},relayConnected=true,run={id:'cancelled'},game={focus(){}};
const capture={recorderStarted:true,frames:1,autoRunId:'cancelled',stopping:false};
const observe=()=>({ready:true}),fresh=()=>true,renderHeader=()=>{};
const events=[],key=(code,type)=>events.push(type),release=code=>{clearTimeout(held.get(code));held.delete(code);key(code,'keyup');};
const releaseAll=()=>{};
"""
        result=subprocess.run([shutil.which('node'),'--max-old-space-size=64','-e',fixture+dispatch+checks],
            capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    @unittest.skipUnless(shutil.which('node'),'Node is required for the browser dispatcher regression')
    def test_first_interrupt_subcode_retains_keydown_without_accepting_input(self):
        self.run_dispatch('''
(async()=>{
 run.id='new';capture.autoRunId='new';
 const promise=executeInput({id:'interrupted',runId:'new',keys:['LEFT'],durationMs:30},clock+1000);
 activeCommand.interrupted=true;activeCommand.failure='interrupted_window_blur';
 await promise;
 assert.equal(acknowledgement.ok,false);assert.equal(acknowledgement.failure.keydown_issued,true);
 assert.equal(acknowledgement.failure.code,'interrupted_window_blur');
 capture.stopping=true;
 await executeInput({id:'stopped',runId:'new',keys:['LEFT'],durationMs:30},clock+1000).catch(()=>{});
 assert.equal(acknowledgement.failure.code,'capture_stopping');assert.equal(acknowledgement.failure.keydown_issued,false);
})().catch(error=>{console.error(error);process.exitCode=1;});
''')

    @unittest.skipUnless(shutil.which('node'),'Node is required for the browser dispatcher regression')
    def test_native_recipe_dispatches_neutral_physical_keys(self):
        self.run_dispatch("""
(async()=>{
 run.id='native';run.nativeAcceptance={id:'scripted-native-acceptance-v2'};capture.autoRunId='native';
 await executeInput({id:'native-buff',runId:'native',keys:['BUFF_1'],durationMs:30},clock+1000);
 assert.equal(acknowledgement.ok,true);assert.equal(events.filter(x=>x==='keydown').length,1);
 await executeInput({id:'native-skill',runId:'native',keys:['PRIMARY_SKILL'],durationMs:30},clock+1000);
 assert.equal(acknowledgement.ok,true);assert.equal(events.filter(x=>x==='keydown').length,2);
})().catch(error=>{console.error(error);process.exitCode=1;});
""")

    @unittest.skipUnless(shutil.which('node'),'Node is required for the browser dispatcher regression')
    def test_cancel_tombstone_rejects_a_late_command_response(self):
        checks="""
(async()=>{
  await executeInput({id:'old-response',runId:'cancelled',keys:['LEFT'],durationMs:30},clock+1000).catch(()=>{});
  assert.equal(events.includes('keydown'),false);
  assert.equal(acknowledgement.ok,false);
  run.id='new-run';capture.autoRunId='new-run';
  await executeInput({id:'new-command',runId:'new-run',keys:['LEFT'],durationMs:30},clock+1000);
  assert.equal(events.filter(x=>x==='keydown').length,1);
  assert.equal(acknowledgement.ok,true);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        self.run_dispatch(checks)

    @unittest.skipUnless(shutil.which('node'),'Node is required for the browser dispatcher regression')
    def test_stale_response_or_elapsed_hold_deadline_never_issues_keydown(self):
        self.run_dispatch("""
(async()=>{
  run.id='new-run';capture.autoRunId='new-run';
  const command={id:'delayed',runId:'new-run',keys:['LEFT'],durationMs:30,remainingMs:1000};
  for(const deadline of [
    commandDeadline(command,0,5000,2100,7100),
    commandDeadline(command,0,5000,100,7100),
    commandDeadline(command,0,5000,100,4999),
    commandDeadline({...command,remainingMs:undefined},0,5000,100,5100),
    commandDeadline({...command,remainingMs:3001},0,5000,100,5100),
    commandDeadline({...command,remainingMs:100},0,5000,100,5100),
    clock+29
  ]) {
    await executeInput(command,deadline).catch(()=>{});
    assert.equal(acknowledgement.ok,false);
    assert.equal(events.includes('keydown'),false);
  }
  const deadline=commandDeadline(command,0,5000,100,5100);
  assert.equal(deadline,1000); // full 100ms trip is conservatively deducted
  clock=980; // UI processing after the response consumed the available hold
  await executeInput(command,deadline).catch(()=>{});
  assert.equal(events.includes('keydown'),false);
  clock=100;
  game.focus=()=>{clock=980;};
  await executeInput(command,deadline).catch(()=>{});
  assert.equal(events.includes('keydown'),false);
  game.focus=()=>{};clock=100;
  await executeInput(command,deadline);
  assert.equal(acknowledgement.ok,true);
  assert.equal(events.filter(x=>x==='keydown').length,1);
  clock=100;
  setTimeout(()=>{clock=1001;},1); // a delayed keyup cannot claim a completed hold
  await executeInput(command,deadline);
  assert.equal(acknowledgement.ok,false);
})().catch(error=>{console.error(error);process.exitCode=1;});
""")


if __name__=='__main__': unittest.main()
