"""Run the real keyboard dispatcher with a minimal browser fixture."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ControllerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node is required for browser timing regressions')
    def test_trial_capture_deadline_and_clock_receive_echo_use_actual_browser_state(self):
        source=(Path(__file__).resolve().parents[1]/'ui/full-client/controller.js').read_text()
        timer=next(line.strip() for line in source.splitlines() if 'item.maxTimer=setTimeout' in line)
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
assert.equal(limit,120000);
let closed=false,pollAbort,acknowledgement=null,sessionAck=null,releaseAck=null,relayConnected=true,disconnectedAt=null;
const clientId='renderer',performance={now:()=>100},observe=()=>({ready:true,capturedAt:Date.now()}),
 Module={MapleBenchRenderedAt:Date.now(),MapleBenchHud:null},renderHeader=()=>{},releaseAll=()=>{};
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

    def run_dispatch(self, checks):
        source=(Path(__file__).resolve().parents[1]/'ui/full-client/controller.js').read_text()
        dispatch=source[source.index('  const commandDeadline = '):source.index('  const poll=async()=>{')]
        fixture="""
const assert=require('node:assert/strict');
let activeCommand=null,acknowledgement=null,clock=100;
const performance={now:()=>clock};
const keyNames={LEFT:'ArrowLeft'}, held=new Map(), cancelledRuns=new Set(['cancelled']);
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
