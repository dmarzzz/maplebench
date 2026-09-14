"""Run the actual private trace collector; no browser, game or model is used."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SkillTraceTests(unittest.TestCase):
    def test_native_only_bounded_immutable_history_and_input_timing(self):
        node = shutil.which('node')
        self.assertIsNotNone(node)
        source = (ROOT/'ui/full-client/controller.js').read_text()
        factory = source[source.index('function createSkillDiagnosticTrace('):
                         source.index('// Live controls and honest canvas capture')]
        checks = r'''
const assert=require('node:assert/strict');
const native={id:'scripted-native-toolkit-acceptance-v2',class_id:'night_lord',
  skill_toolkit:{id:'full-client-skill-toolkit-v2'}};
const run={id:'a'.repeat(32),mode:'script',model:null,status:'requesting',nativeAcceptance:native};
const state={schemaVersion:1,ready:true,source:'native-client-diagnostic',capturedAt:100,
  receivedBuffs:[{stat:4,skillId:4121006,value:0,receivedDurationMs:120000}],hp:90,mp:80};
const mod={MapleBenchSkillState:state,MapleBenchObservation:{capturedAt:100,
  monsters:[{objectId:7,x:4,y:9}]}};
let time=10;
const d=createSkillDiagnosticTrace(mod,()=>time++);
d.update({...run,mode:'api',model:'gpt-6-astra'});d.sample();
assert.equal(mod.MapleBenchSkillTrace,undefined);
d.update({...run,nativeAcceptance:{...native,id:'scripted-native-toolkit-acceptance-v1'}});
assert.equal(mod.MapleBenchSkillTrace,undefined);
d.update(run);d.sample();const original=mod.MapleBenchSkillTrace;
assert.equal(original.records.length,1);
assert.equal(original.records[0].state.receivedBuffs[0].value,0);
state.receivedBuffs[0].value=42;mod.MapleBenchObservation.monsters[0].x=999;
assert.equal(original.records[0].state.receivedBuffs[0].value,0);
assert.equal(original.records[0].monsters[0].x,4);
const command={runId:run.id,id:'b'.repeat(32),keys:['SKILL_9'],durationMs:300};
d.mark(command,'before_keydown',123.5);time+=300;d.mark(command,'after_release',123.5,true);
assert.equal(original.records[1].handlerStartedMonotonicMs,123.5);
assert.equal(original.records[2].monotonicMs-original.records[1].monotonicMs,301);
assert.equal(original.records[2].ok,true);
d.mark({...command,runId:'c'.repeat(32)},'before_keydown',0);
d.mark({...command,keys:null},'after_release',0);
assert.equal(original.records.length,3);
state.capturedAt=101;d.sample();assert.equal(original.records.length,3);
mod.MapleBenchObservation.capturedAt=101;d.sample();
// Identical wall timestamps may describe distinct simulation updates. Keep
// both with sequence and monotonic time rather than silently deduplicating.
d.sample();assert.equal(original.records.length,5);
d.update({...run,status:'running'});assert.equal(mod.MapleBenchSkillTrace,original);
d.stop('recording_stopped');d.sample();assert.equal(original.records.length,5);
assert.equal(original.closedReason,'recording_stopped');
d.update({...run,id:'d'.repeat(32)});const next=mod.MapleBenchSkillTrace;
assert.notEqual(next,original);assert.equal(next.records.length,0);
for(let i=0;i<8200;i++)d.sample();
assert.equal(next.records.length,8192);assert.equal(next.failure,'diagnostic_limit');
assert.equal(next.records[0].seq,0);assert.equal(next.records[8191].seq,8191);
assert.equal(next.score,null);assert.equal(next.model,null);assert.equal(next.apiCalls,0);
const broken={MapleBenchSkillState:{...state},MapleBenchObservation:{capturedAt:101,monsters:{}}};
const b=createSkillDiagnosticTrace(broken);b.update(run);
assert.doesNotThrow(()=>b.sample());assert.equal(broken.MapleBenchSkillTrace.failure,'diagnostic_serialization');
const big={...mod,MapleBenchSkillState:{...state,receivedBuffs:[],padding:'x'.repeat(13*1024*1024)}};
const bounded=createSkillDiagnosticTrace(big);bounded.update(run);bounded.sample();
assert.equal(big.MapleBenchSkillTrace.records.length,0);
assert.equal(big.MapleBenchSkillTrace.failure,'diagnostic_limit');
assert.equal(mod.MapleBenchObservation.capturedAt,101);
'''
        subprocess.run([node, '-e', factory+checks], check=True, capture_output=True, timeout=15)

    def test_hooks_stay_outside_model_observation_and_wire_ack(self):
        source = (ROOT/'ui/full-client/controller.js').read_text()
        self.assertIn('Module.MapleBenchRecordSkillState=skillDiagnostics.sample', source)
        self.assertIn("skillDiagnostics.mark(command,'before_keydown',item.startedAt)", source)
        self.assertIn("skillDiagnostics.mark(command,'after_release',item.startedAt,ok)", source)
        for start, end in (('  const ackFrame =', '  const sendUrgentAck ='),
                           ('      const response=await fetch(\'/control/frame\'', '      if(!response.ok)')):
            body = source[source.index(start):source.index(end, source.index(start))]
            self.assertNotIn('SkillTrace', body)
            self.assertNotIn('SkillState', body)


if __name__ == '__main__':
    unittest.main()
