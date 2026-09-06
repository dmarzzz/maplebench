"""Run the real keyboard dispatcher with a minimal browser fixture."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ControllerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node is required for the browser dispatcher regression')
    def test_cancel_tombstone_rejects_a_late_command_response(self):
        source=(Path(__file__).resolve().parents[1]/'ui/full-client/controller.js').read_text()
        dispatch=source[source.index('  const executeInput = async command => {'):source.index('  const poll=async()=>{')]
        fixture="""
const assert=require('node:assert/strict');
let activeCommand=null,acknowledgement=null;
const keyNames={LEFT:'ArrowLeft'}, held=new Map(), cancelledRuns=new Set(['cancelled']);
const document={hidden:false},relayConnected=true,run={id:'cancelled'},game={focus(){}};
const capture={recorderStarted:true,frames:1,autoRunId:'cancelled',stopping:false};
const observe=()=>({ready:true}),fresh=()=>true,renderHeader=()=>{};
const events=[],key=(code,type)=>events.push(type),release=code=>{clearTimeout(held.get(code));held.delete(code);key(code,'keyup');};
const releaseAll=()=>{};
"""
        checks="""
(async()=>{
  await executeInput({id:'old-response',runId:'cancelled',keys:['LEFT'],durationMs:30}).catch(()=>{});
  assert.equal(events.includes('keydown'),false);
  assert.equal(acknowledgement.ok,false);
  run.id='new-run';capture.autoRunId='new-run';
  await executeInput({id:'new-command',runId:'new-run',keys:['LEFT'],durationMs:30});
  assert.equal(events.filter(x=>x==='keydown').length,1);
  assert.equal(acknowledgement.ok,true);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result=subprocess.run([shutil.which('node'),'--max-old-space-size=64','-e',fixture+dispatch+checks],
            capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__': unittest.main()
