import test from 'node:test';
import assert from 'node:assert/strict';
import {PostRenderRecorder,muxWebM,LIMITS} from '../ui/full-client/webcodecs-recorder.js';

function harness(behavior={}){
  let time=1000,wallDelta=0;const calls=[],instances=[];
  class Frame{constructor(source,init){Object.assign(this,init);this.source=source;this.closed=false;}
    close(){assert.equal(this.closed,false);this.closed=true;calls.push('frame-close');}}
  class Encoder{
    static async isConfigSupported(config){if(behavior.hangConfig)return new Promise(()=>{});
      return {supported:!behavior.unsupported,config:{...config,...behavior.supportOverride}};}
    constructor(callbacks){this.callbacks=callbacks;this.state='unconfigured';this.encodeQueueSize=0;this.inputs=[];instances.push(this);}
    configure(config){this.config={...config};this.state='configured';calls.push('configure');}
    encode(frame,options){this.inputs.push({...frame,...options});calls.push('encode');}
    async flush(){calls.push('flush');if(!this.inputs.length)return;
      if(behavior.hangFlush)return new Promise(()=>{});
      for(const [i,input] of this.inputs.entries()){
        if(behavior.drop&&i===0)continue;
        const data=new Uint8Array([input.keyFrame?16:17,0,0,0x9d,1,0x2a,32,0,24,0]);
        const chunk={timestamp:input.timestamp+(behavior.timestamp?1000:0),duration:input.duration,
          type:input.keyFrame?'key':'delta',byteLength:data.length,copyTo:target=>target.set(data)};
        if(behavior.hidden)data[0]&=~16;
        this.callbacks.output(chunk);if(behavior.duplicate)this.callbacks.output(chunk);
      }
    }
    close(){this.state='closed';calls.push('close');}
  }
  const canvas={width:32,height:24};
  const recorder=new PostRenderRecorder(canvas,{maxDurationMs:10000},{VideoFrame:Frame,VideoEncoder:Encoder,
    now:()=>time,wall:()=>100000+time+wallDelta,...(behavior.hash?{hash:behavior.hash}:{})});
  return {recorder,canvas,calls,instances,set:n=>time=n,drift:n=>wallDelta=n};
}
async function two(h){await h.recorder.initialize();h.set(1010);assert.equal(h.recorder.onRendered(),true);
  h.set(1044.2);h.recorder.onRendered();h.set(1050.1);}

test('explicit snapshots flush before final WebM and stop is idempotent',async()=>{
  const h=harness();await two(h);const a=h.recorder.stop(),b=h.recorder.stop();assert.equal(a,b);
  const result=await a;assert.equal(result.encoder_receipt.encoded_frames,2);
  assert.equal(result.encoder_receipt.submitted_frames,2);assert.equal(result.encoder_receipt.flushed,true);
  assert.match(result.encoder_receipt.webm_sha256,/^[a-f0-9]{64}$/);
  assert.equal(result.blob.size,result.encoder_receipt.webm_bytes);
  assert.equal(result.measurements.first_frame_offset_ms,10);
  assert.equal(result.measurements.last_frame_offset_ms,44.200000000000045);
  assert.equal(h.calls.at(-1),'close');assert.ok(h.calls.indexOf('flush')<h.calls.lastIndexOf('close'));
});
test('each snapshot is retained until next timestamp gives its duration',async()=>{
  const h=harness();await h.recorder.initialize();h.set(1010);h.recorder.onRendered();
  assert.equal(h.recorder.submittedFrames,0);h.set(1044);h.recorder.onRendered();
  assert.equal(h.instances[0].inputs[0].duration,34000);h.set(1044);await h.recorder.stop();
  assert.equal(h.instances[0].inputs[1].duration,1000);
});
test('terminal rounding uses the exact serialized clock operands',async()=>{
  const h=harness();h.set(0.1);await h.recorder.initialize();h.set(0.2);h.recorder.onRendered();
  h.set(2.2);h.recorder.onRendered();h.set(4.2);const result=await h.recorder.stop();
  const m=result.measurements;
  assert.equal(Math.ceil(4.2-0.2),4);
  assert.equal(Math.ceil(m.duration_ms-m.first_frame_offset_ms),5);
  assert.equal(h.instances[0].inputs[1].duration,3000);
  // The same cancellation occurs in the concrete long-running browser clocks.
  const started=221325.76518336454,first=221485.7757564947,stop=515664.7757564947;
  assert.equal(Math.ceil(stop-first),294179);
  assert.equal(Math.ceil((stop-started)-(first-started)),294180);
});
test('quantized terminal tail must fit 250ms even when raw tail fits',async()=>{
  const a=harness();await a.recorder.initialize();a.set(1010);a.recorder.onRendered();
  a.set(1044.9);a.recorder.onRendered();a.set(1294.8);
  await assert.rejects(a.recorder.stop(),/capture_quantized_endpoint_gap/);
  assert.equal(a.recorder.failed,true);
  const b=harness();await b.recorder.initialize();b.set(1010);b.recorder.onRendered();
  b.set(1044.9);b.recorder.onRendered();b.set(1294.0);await b.recorder.stop();
  assert.equal(b.instances[0].inputs[1].duration,250000);
});
for(const [name,behavior,code] of [['missing output',{drop:true},'encoder_output_timing_mismatch'],
  ['duplicate output',{duplicate:true},'encoder_output_timing_mismatch'],
  ['changed timestamp',{timestamp:true},'encoder_output_timing_mismatch'],
  ['invisible VP8 output',{hidden:true},'vp8_hidden_or_mistyped_frame']]){
  test(name+' fails closed',async()=>{const h=harness(behavior);await two(h);
    await assert.rejects(h.recorder.stop(),new RegExp(code));assert.equal(h.recorder.failed,true);});
}
test('backpressure fails instead of dropping or waiting inside the post-render hook',async()=>{
  const h=harness();await h.recorder.initialize();
  for(let i=0;i<=LIMITS.maxPendingFrames;i++){h.set(1010+i*10);h.recorder.onRendered();}
  h.set(1200);assert.throws(()=>h.recorder.onRendered(),/encoder_backpressure/);
  await assert.rejects(h.recorder.stop(),/encoder_backpressure/);
});
test('encoder pending queue is bounded independently of output counters',async()=>{
  const h=harness();await h.recorder.initialize();h.set(1010);h.recorder.onRendered();
  h.instances[0].encodeQueueSize=LIMITS.maxPendingFrames;h.set(1020);
  assert.throws(()=>h.recorder.onRendered(),/encoder_backpressure/);
});
test('same quantized millisecond is refused, never silently coalesced',async()=>{
  const h=harness();await h.recorder.initialize();h.set(1010);h.recorder.onRendered();h.set(1010.1);
  assert.throws(()=>h.recorder.onRendered(),/duplicate_quantized_timestamp/);
});
test('canvas resize is refused',async()=>{const h=harness();await h.recorder.initialize();h.canvas.width++;
  assert.throws(()=>h.recorder.onRendered(),/capture_dimensions_changed/);});
test('wall clock drift is refused',async()=>{const h=harness();await h.recorder.initialize();h.drift(6);
  assert.throws(()=>h.recorder.onRendered(),/capture_wall_clock_drift/);});
test('long lead, internal and tail gaps are refused',async()=>{
  const a=harness();await a.recorder.initialize();a.set(1251);assert.throws(()=>a.recorder.onRendered(),/capture_frame_gap/);
  const b=harness();await b.recorder.initialize();b.set(1010);b.recorder.onRendered();b.set(2011);
  assert.throws(()=>b.recorder.onRendered(),/capture_frame_gap/);
  const c=harness();await two(c);c.set(1295);await assert.rejects(c.recorder.stop(),/capture_endpoint_gap/);
});
test('unsupported configuration cannot fall back to MediaRecorder',async()=>{
  const h=harness({unsupported:true});await assert.rejects(h.recorder.initialize(),/vp8_configuration_unsupported/);
  assert.equal(h.instances.length,0);
});
test('every submitted frame requires quality mode without changing capture budgets',async()=>{
  const h=harness();await two(h);await h.recorder.stop();
  assert.deepEqual(h.instances[0].config,{codec:'vp8',width:32,height:24,bitrate:2000000,
    framerate:30,latencyMode:'quality',hardwareAcceleration:'prefer-software'});
  assert.equal(LIMITS.maxPendingFrames,8);
});
test('support that changes or omits quality mode is refused before encoding',async()=>{
  for(const latencyMode of ['realtime',undefined]) {
    const h=harness({supportOverride:{latencyMode}});
    await assert.rejects(h.recorder.initialize(),/vp8_configuration_unsupported/);
    assert.equal(h.instances.length,0);assert.equal(h.recorder.submittedFrames,0);
  }
});
test('failed chunk hash invalidates completed encoding',async()=>{
  const h=harness({hash:async()=>{throw Error('bad digest');}});await two(h);
  await assert.rejects(h.recorder.stop(),/encoded_hash_failed/);
});
test('configuration timeout is bounded',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});const h=harness({hangConfig:true});
  const checked=assert.rejects(h.recorder.initialize(),/encoder_configuration_timeout/);
  t.mock.timers.tick(LIMITS.configurationTimeoutMs+1);await checked;
});
test('flush timeout closes the encoder and never produces an upload',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});const h=harness({hangFlush:true});await two(h);
  const checked=assert.rejects(h.recorder.stop(),/encoder_flush_timeout/);
  t.mock.timers.tick(LIMITS.flushTimeoutMs+1);await checked;
  assert.equal(h.instances[0].state,'closed');
});
test('entire stop is bounded even when encoded hashing stalls',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});const h=harness({hash:()=>new Promise(()=>{})});await two(h);
  const checked=assert.rejects(h.recorder.stop(),/encoder_stop_timeout/);
  // Settle the encoder flush first, then leave only asynchronous hashes pending.
  for(let i=0;i<8;i++)await Promise.resolve();
  t.mock.timers.tick(LIMITS.stopTimeoutMs+1);await checked;
  assert.equal(h.instances[0].state,'closed');
});
test('muxer refuses gaps, nonzero origin, nonintegral ticks and missing first key',()=>{
  const first={timestamp:0,duration:1000,key:true,data:new Uint8Array([16,0,0])};
  for(const frames of [[{...first,timestamp:1000},first],[first,{...first,timestamp:2000}],
    [{...first,duration:1500},first],[{...first,key:false},{...first,timestamp:1000}]])
    assert.throws(()=>muxWebM({width:32,height:24,frames,ledgerBytes:new Uint8Array()}),/invalid_mux_frame/);
});
