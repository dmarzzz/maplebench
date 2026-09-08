// Opt-in prototype. Never used by the legacy MediaRecorder controller implicitly.
// Explicit post-render snapshots, VP8 outputs, and a finite WebM frame ledger.
export const ENCODED_FRAME_POLICY = Object.freeze({id:'post-render-encoded-frame-v1',
  max_endpoint_gap_ms:250,max_wall_drift_ms:5,timestamp_slack_ms:2,
  max_frame_gap_ms:1000,max_frames:20000});
export const LEDGER_TAG = 'MAPLEBENCH_ENCODER_LEDGER_V1';
export const LIMITS = Object.freeze({maxBytes:95*1024*1024,maxLedgerBytes:8*1024*1024,
  maxPendingFrames:8,maxPendingHashes:16,configurationTimeoutMs:5000,flushTimeoutMs:5000,
  stopTimeoutMs:15000,maxDurationMs:335000});
const utf8 = new TextEncoder();
const need=(ok,code)=>{if(!ok)throw Error(code);};
const integer=(n,min=0,max=Number.MAX_SAFE_INTEGER)=>Number.isSafeInteger(n)&&n>=min&&n<=max;
const hex=bytes=>Array.from(bytes,x=>x.toString(16).padStart(2,'0')).join('');
const hash=async bytes=>hex(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)));
const bounded=async(promise,ms,code)=>{let timer;
  try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(code)),ms);})]);}
  finally{clearTimeout(timer);}};
const id=n=>Uint8Array.from(n.match(/../g),s=>parseInt(s,16));
const concat=parts=>{const out=new Uint8Array(parts.reduce((n,p)=>n+p.length,0));
  let at=0;for(const p of parts){out.set(p,at);at+=p.length;}return out;};
const uint=n=>{need(integer(n),'invalid_ebml_uint');const a=[];do{a.unshift(n%256);n=Math.floor(n/256);}while(n);return Uint8Array.from(a);};
const size=n=>{need(integer(n,0,LIMITS.maxBytes),'invalid_ebml_size');
  for(let width=1;width<=5;width++)if(n<2**(7*width)-1){const a=new Uint8Array(width);
    for(let i=width-1;i>=0;i--){a[i]=n%256;n=Math.floor(n/256);}a[0]|=1<<(8-width);return a;}
  throw Error('ebml_size_overflow');};
const element=(name,...body)=>{const n=body.reduce((total,b)=>total+b.length,0);return concat([id(name),size(n),...body]);};
const unsigned=(name,n)=>element(name,uint(n));
const string=(name,s)=>element(name,utf8.encode(s));
const uint64=n=>{need(integer(n),'invalid_ebml_offset');const raw=new Uint8Array(8);
  for(let i=7;i>=0;i--){raw[i]=n%256;n=Math.floor(n/256);}return raw;};
const float64=(name,n)=>{const raw=new Uint8Array(8);new DataView(raw.buffer).setFloat64(0,n);return element(name,raw);};
const signed=n=>{need(Number.isSafeInteger(n)&&n<0&&n>=-335000,'invalid_reference_timestamp');
  let width=1;while(n<-(2**(8*width-1)))width++;
  let value=2**(8*width)+n;const raw=new Uint8Array(width);
  for(let i=width-1;i>=0;i--){raw[i]=value%256;value=Math.floor(value/256);}return raw;};

/** Small single-video-track VP8 WebM writer. Exact 1ms ticks; no inferred tail. */
export function muxWebM({width,height,frames,ledgerBytes}) {
  need(integer(width,2,4096)&&integer(height,2,4096),'invalid_dimensions');
  need(Array.isArray(frames)&&frames.length>=2&&frames.length<=ENCODED_FRAME_POLICY.max_frames,'invalid_frame_count');
  need(ledgerBytes instanceof Uint8Array&&ledgerBytes.length<=LIMITS.maxLedgerBytes,'ledger_too_large');
  let end=0,previous=0,total=0;
  for(let i=0;i<frames.length;i++){
    const f=frames[i];need(integer(f.timestamp)&&integer(f.duration,1000)&&f.timestamp%1000===0
      &&f.duration%1000===0&&f.timestamp===end&&f.data instanceof Uint8Array
      &&typeof f.key==='boolean'&&(i>0||f.key),'invalid_mux_frame');
    end=f.timestamp+f.duration;total+=f.data.length;
  }
  need(end<=LIMITS.maxDurationMs*1000&&total<=LIMITS.maxBytes,'capture_byte_or_duration_limit');
  const header=element('1a45dfa3',unsigned('4286',1),unsigned('42f7',1),unsigned('42f2',4),
    unsigned('42f3',8),string('4282','webm'),unsigned('4287',4),unsigned('4285',2));
  const info=element('1549a966',unsigned('2ad7b1',1000000),float64('4489',end/1000),
    string('4d80','MapleBench explicit-frame v1'),string('5741','MapleBench explicit-frame v1'));
  const tracks=element('1654ae6b',element('ae',unsigned('d7',1),unsigned('73c5',1),
    unsigned('83',1),unsigned('9c',0),string('86','V_VP8'),element('e0',unsigned('b0',width),unsigned('ba',height))));
  // One Cluster per frame keeps timestamps simple and seek points unambiguous.
  // Delta BlockGroups explicitly reference the preceding frame; every duration is written.
  const tags=element('1254c367',element('7373',element('63c0'),
    element('67c8',string('45a3',LEDGER_TAG),element('4487',ledgerBytes))));
  const seekHead=position=>element('114d9b74',element('4dbb',element('53ab',id('1c53bb6b')),
    element('53ac',uint64(position))));
  const placeholder=seekHead(0); // Fixed-width position keeps cluster offsets stable.
  // Put the bounded ledger before media so metadata-only probes see it too.
  const parts=[placeholder,info,tracks,tags],cues=[];
  let offset=placeholder.length+info.length+tracks.length+tags.length;
  for(const f of frames){
    const at=f.timestamp/1000,block=element('a1',new Uint8Array([0x81,0,0,0]),f.data);
    const group=element('a0',block,unsigned('9b',f.duration/1000),
      ...(f.key?[]:[element('fb',signed(previous-at))]));
    const cluster=element('1f43b675',unsigned('e7',at),group);
    if(f.key)cues.push(element('bb',unsigned('b3',at),element('b7',unsigned('f7',1),unsigned('f1',offset))));
    parts.push(cluster);offset+=cluster.length;previous=at;
  }
  parts[0]=seekHead(offset);parts.push(element('1c53bb6b',...cues));
  const segmentBytes=parts.reduce((n,p)=>n+p.length,0);
  const blob=new Blob([header,id('18538067'),size(segmentBytes),...parts],{type:'video/webm'});
  need(blob.size<=LIMITS.maxBytes,'capture_byte_limit');return blob;
}

export class PostRenderRecorder {
  constructor(canvas,options={},dependencies={}) {
    this.canvas=canvas;this.failure=null;this.stopping=false;this.frames=0;this.submittedFrames=0;this.outputFrames=0;
    this._now=dependencies.now||(()=>performance.now());this._wall=dependencies.wall||(()=>Date.now());
    this._VideoFrame=dependencies.VideoFrame||globalThis.VideoFrame;
    this._VideoEncoder=dependencies.VideoEncoder||globalThis.VideoEncoder;
    this._hash=dependencies.hash||hash;this._onFailure=options.onFailure||(()=>{});
    this._maximum=options.maxDurationMs??LIMITS.maxDurationMs;
    need(integer(this._maximum,1,LIMITS.maxDurationMs),'invalid_capture_limit');
    need(canvas&&integer(canvas.width,2,4096)&&integer(canvas.height,2,4096),'invalid_canvas');
    this._width=canvas.width;this._height=canvas.height;this._pending=null;this._inputs=[];this._outputs=[];
    this._hashes=[];this._hashPending=0;this._bytes=0;this._maxGap=0;this._lastKeyAt=null;
  }
  get failed(){return this.failure!==null;}
  async initialize(){
    need(!this._encoder,'capture_already_initialized');
    need(this._VideoFrame&&this._VideoEncoder&&globalThis.crypto?.subtle,'webcodecs_unavailable');
    const config={codec:'vp8',width:this._width,height:this._height,bitrate:2000000,
      framerate:30,latencyMode:'realtime',hardwareAcceleration:'prefer-software'};
    const support=await bounded(this._VideoEncoder.isConfigSupported(config),LIMITS.configurationTimeoutMs,'encoder_configuration_timeout');
    need(support.supported&&Object.entries(config).every(([k,v])=>support.config[k]===v),'vp8_configuration_unsupported');
    this._encoder=new this._VideoEncoder({output:(chunk,meta)=>this._output(chunk,meta),error:()=>this._fail('encoder_error')});
    this._encoder.configure(config);
    try{await bounded(this._encoder.flush(),LIMITS.configurationTimeoutMs,'encoder_configuration_timeout');this._check();}
    catch(error){this._fail(error.message);throw error;}
    this.startedAt=this._now();this.startedWall=this._wall();this._lastAt=this.startedAt;
    this._timer=setTimeout(()=>this._fail('capture_duration_limit'),this._maximum);
    return this;
  }
  _fail(code){
    if(this.failure)return;this.failure=code;clearTimeout(this._timer);
    this._pending?.frame.close();this._pending=null;
    try{if(this._encoder?.state!=='closed')this._encoder?.close();}catch{}
    this._outputs=[];this._inputs=[];
    try{this._onFailure(code);}catch{}
  }
  _check(){if(this.failure)throw Error(this.failure);}
  /** Must be called synchronously after the caller draws the just-rendered game+HUD. */
  onRendered(){
    this._check();need(!this.stopping&&this._encoder?.state==='configured','capture_not_active');
    try{
      const now=this._now(),wall=this._wall();
      need(Number.isFinite(now)&&now>=this._lastAt&&now-this.startedAt<=this._maximum,'capture_clock_or_duration');
      need(Math.abs(wall-this.startedWall-(now-this.startedAt))<=ENCODED_FRAME_POLICY.max_wall_drift_ms,'capture_wall_clock_drift');
      need(this.frames<ENCODED_FRAME_POLICY.max_frames,'capture_frame_limit');
      need(this.canvas.width===this._width&&this.canvas.height===this._height,'capture_dimensions_changed');
      const gap=now-this._lastAt;
      need(gap<=(this.frames?ENCODED_FRAME_POLICY.max_frame_gap_ms:ENCODED_FRAME_POLICY.max_endpoint_gap_ms),'capture_frame_gap');
      this._maxGap=Math.max(this._maxGap,gap);
      if(!this.frames){this.firstFrameAt=now;this.firstFrameWall=wall;}
      const timestamp=Math.floor(now-this.firstFrameAt)*1000;
      need(!this._pending||timestamp>this._pending.timestamp,'duplicate_quantized_timestamp');
      // Snapshot immediately; no await, RAF, captureStream, or canvas read after the hook.
      const frame=new this._VideoFrame(this.canvas,{timestamp});
      try{if(this._pending)this._submit(timestamp-this._pending.timestamp);}
      catch(error){frame.close();throw error;}
      this._pending={frame,timestamp};this.frames++;this.lastFrameAt=now;this.lastFrameWall=wall;this._lastAt=now;
      return true;
    }catch(error){this._fail(error.message);throw error;}
  }
  _submit(duration){
    const p=this._pending;need(p&&integer(duration,1000)&&duration%1000===0,'invalid_frame_duration');
    need(this._encoder.encodeQueueSize<LIMITS.maxPendingFrames
      &&this.submittedFrames-this.outputFrames<LIMITS.maxPendingFrames
      &&this._hashPending<LIMITS.maxPendingHashes,'encoder_backpressure');
    const key=this._lastKeyAt===null||p.timestamp-this._lastKeyAt>=2000000;
    const timed=new this._VideoFrame(p.frame,{timestamp:p.timestamp,duration});
    this._inputs.push({timestamp:p.timestamp,duration,key});this.submittedFrames++;
    try{this._encoder.encode(timed,{keyFrame:key});if(key)this._lastKeyAt=p.timestamp;}
    finally{timed.close();p.frame.close();this._pending=null;}
  }
  _output(chunk,metadata){
    if(this.failure)return;
    try{
      const index=this.outputFrames,expected=this._inputs[index];
      need(expected&&chunk.timestamp===expected.timestamp&&chunk.duration===expected.duration,'encoder_output_timing_mismatch');
      need(chunk.type==='key'||chunk.type==='delta','encoder_output_type');
      need(!expected.key||chunk.type==='key','encoder_missing_requested_keyframe');
      need(integer(chunk.byteLength,3,LIMITS.maxBytes)&&this._bytes+chunk.byteLength<=LIMITS.maxBytes,'capture_byte_limit');
      need(this._hashPending<LIMITS.maxPendingHashes,'encoder_hash_backpressure');
      const d=metadata?.decoderConfig;
      need(!d||(d.codec==='vp8'&&d.codedWidth===this._width&&d.codedHeight===this._height),'encoder_configuration_changed');
      const data=new Uint8Array(chunk.byteLength);chunk.copyTo(data);
      const key=(data[0]&1)===0;
      need(Boolean(data[0]&16)&&key===(chunk.type==='key'),'vp8_hidden_or_mistyped_frame');
      if(key)need(data.length>=10&&data[3]===0x9d&&data[4]===1&&data[5]===0x2a
        &&((data[6]|data[7]<<8)&0x3fff)===this._width&&((data[8]|data[9]<<8)&0x3fff)===this._height,'vp8_keyframe_dimensions');
      this._outputs.push({timestamp:chunk.timestamp,duration:chunk.duration,key,data});
      this.outputFrames++;this._bytes+=data.length;this._hashPending++;
      this._hashes.push(Promise.resolve(this._hash(data)).then(h=>{need(/^[a-f0-9]{64}$/.test(h),'invalid_encoded_hash');return h;})
        .catch(()=>{this._fail('encoded_hash_failed');return null;}).finally(()=>this._hashPending--));
    }catch(error){this._fail(error.message);}
  }
  /** Freeze the endpoint before awaiting flush. No data is uploadable on failure. */
  stop(){
    if(!this._stopPromise)this._stopPromise=bounded(this._finish(),LIMITS.stopTimeoutMs,'encoder_stop_timeout')
      .catch(error=>{this._fail(error.message);throw error;});
    return this._stopPromise;
  }
  async _finish(){
    this._check();need(!this.stopping,'capture_already_stopping');this.stopping=true;clearTimeout(this._timer);
    const endAt=this._now(),endWall=this._wall();
    try{
      need(this.frames>=2&&endAt>=this.lastFrameAt&&endAt-this.startedAt<=this._maximum,'incomplete_capture');
      need(endAt-this.lastFrameAt<=ENCODED_FRAME_POLICY.max_endpoint_gap_ms,'capture_endpoint_gap');
      need(Math.abs(endWall-this.startedWall-(endAt-this.startedAt))<=ENCODED_FRAME_POLICY.max_wall_drift_ms,'capture_wall_clock_drift');
      this._maxGap=Math.max(this._maxGap,endAt-this.lastFrameAt);
      // Use the identical serialized operands the independent verifier receives.
      // A stop in the same 1ms tick still writes one explicit terminal tick.
      const durationMs=endAt-this.startedAt,firstOffsetMs=this.firstFrameAt-this.startedAt;
      const endTimestamp=Math.max(this._pending.timestamp+1000,Math.ceil(durationMs-firstOffsetMs)*1000);
      const finalDuration=endTimestamp-this._pending.timestamp;
      need(finalDuration<=ENCODED_FRAME_POLICY.max_endpoint_gap_ms*1000,'capture_quantized_endpoint_gap');
      this._submit(finalDuration);
      let timer;
      try{await Promise.race([this._encoder.flush(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('encoder_flush_timeout')),LIMITS.flushTimeoutMs);})]);}
      finally{clearTimeout(timer);}
      this._check();need(this.submittedFrames===this.frames&&this.outputFrames===this.frames,'encoder_frame_count_mismatch');
      const hashes=await Promise.all(this._hashes);this._check();
      this._encoder.close();
      const ledger={schema_version:1,codec:'vp8',timebase_us:1000,
        submitted_timestamps_us:this._inputs.map(f=>f.timestamp),encoded_timestamps_us:this._outputs.map(f=>f.timestamp),
        durations_us:this._inputs.map(f=>f.duration),encoded_sha256:hashes,flushed:true};
      const ledgerBytes=utf8.encode(JSON.stringify(ledger));need(ledgerBytes.length<=LIMITS.maxLedgerBytes,'ledger_too_large');
      const blob=muxWebM({width:this._width,height:this._height,frames:this._outputs,ledgerBytes});
      const encoder_receipt={schema_version:1,codec:'vp8',timebase_us:1000,submitted_frames:this.submittedFrames,
        encoded_frames:this.outputFrames,flushed:true,ledger_sha256:await this._hash(ledgerBytes),ledger_bytes:ledgerBytes.length,
        webm_sha256:await this._hash(await blob.arrayBuffer()),webm_bytes:blob.size};
      this._outputs=[];this._inputs=[];this._hashes=[];
      return {blob,encoder_receipt,measurements:{start_wall_ms:this.startedWall,end_wall_ms:endWall,duration_ms:durationMs,
        first_frame_wall_ms:this.firstFrameWall,last_frame_wall_ms:this.lastFrameWall,
        first_frame_offset_ms:firstOffsetMs,last_frame_offset_ms:this.lastFrameAt-this.startedAt,
        rendered_frames:this.frames,max_frame_gap_ms:this._maxGap}};
    }catch(error){this._fail(error.message);throw error;}
  }
  abort(code='capture_aborted'){this._fail(code);}
}

export async function createPostRenderRecorder(canvas,options={}){
  return new PostRenderRecorder(canvas,options).initialize();
}
