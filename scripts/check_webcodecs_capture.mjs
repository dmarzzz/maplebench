/** Synthetic browser-only check. No game, relay, native service or model API. */
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {fileURLToPath} from 'node:url';
const run=promisify(execFile),root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const bounded=async(promise,ms)=>{let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{
  timer=setTimeout(()=>reject(Error('synthetic_browser_timeout')),ms);})]);}finally{clearTimeout(timer);}};
const output=process.argv[2],playwrightPath=process.env.PLAYWRIGHT_MODULE_PATH,chrome=process.env.CHROME_EXECUTABLE;
if(!output||!path.isAbsolute(output)||!playwrightPath||!chrome)throw Error('absolute output, PLAYWRIGHT_MODULE_PATH and CHROME_EXECUTABLE required');
await fs.mkdir(output,{mode:0o700});
const moduleBytes=await fs.readFile(path.join(root,'ui/full-client/webcodecs-recorder.js'));
const server=http.createServer((request,response)=>{
  if(request.url==='/recorder.js'){response.setHeader('content-type','text/javascript');response.end(moduleBytes);}
  else if(request.url==='/'){response.setHeader('content-type','text/html');response.end('<canvas width="800" height="720"></canvas>');}
  else{response.statusCode=404;response.end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const {chromium}=await import(playwrightPath);let browser;
try{
  browser=await chromium.launch({executablePath:chrome,headless:true,timeout:15000,args:['--disable-background-networking']});
  const page=await browser.newPage();await page.goto(`http://127.0.0.1:${server.address().port}/`,{timeout:5000});
  const result=await bounded(page.evaluate(async()=>{
    const {createPostRenderRecorder}=await import('/recorder.js');
    const canvas=document.querySelector('canvas'),ctx=canvas.getContext('2d');
    const r=await createPostRenderRecorder(canvas,{maxDurationMs:10000});
    for(let i=0;i<40;i++){
      ctx.fillStyle=i%2?'#11172b':'#192a41';ctx.fillRect(0,0,800,720);
      ctx.fillStyle='#63e4b3';ctx.fillRect(i*15,260,80,130);
      ctx.fillStyle='white';ctx.font='32px monospace';ctx.fillText(`SYNTHETIC ENCODER CHECK ${i}`,24,60);
      r.onRendered();await new Promise(resolve=>setTimeout(resolve,i%3===0?75:40));
    }
    const final=await r.stop();const bytes=new Uint8Array(await final.blob.arrayBuffer());
    let raw='';for(let at=0;at<bytes.length;at+=8192)raw+=String.fromCharCode(...bytes.subarray(at,at+8192));
    return {base64:btoa(raw),encoder_receipt:final.encoder_receipt,measurements:final.measurements,
      browser:navigator.userAgent,secure:isSecureContext};
  }),15000);
  const video=Buffer.from(result.base64,'base64');delete result.base64;
  if(video.length>16*1024*1024)throw Error('synthetic_fixture_too_large');
  await fs.writeFile(path.join(output,'synthetic.webm'),video,{mode:0o600,flag:'wx'});
  const probe=await run('ffprobe',['-v','error','-select_streams','v:0','-count_frames','-show_packets',
    '-show_data_hash','sha256','-show_entries','packet=pts_time,duration_time,data_hash:stream=codec_name,width,height,nb_read_frames:format=duration:format_tags',
    '-of','json',path.join(output,'synthetic.webm')],{timeout:15000,maxBuffer:12*1024*1024});
  const parsed=JSON.parse(probe.stdout),ledgerText=parsed.format.tags.MAPLEBENCH_ENCODER_LEDGER_V1;
  const ledger=JSON.parse(ledgerText),packets=parsed.packets,receipt=result.encoder_receipt;
  const sha=raw=>crypto.createHash('sha256').update(raw).digest('hex');
  if(sha(video)!==receipt.webm_sha256||video.length!==receipt.webm_bytes
    ||sha(ledgerText)!==receipt.ledger_sha256||Buffer.byteLength(ledgerText)!==receipt.ledger_bytes)throw Error('exact_file_or_ledger_hash_mismatch');
  if(packets.length!==40||Number(parsed.streams[0].nb_read_frames)!==40)throw Error('encoded_or_decoded_count_mismatch');
  for(let i=0;i<packets.length;i++){
    const p=packets[i];
    if(Math.round(Number(p.pts_time)*1e6)!==ledger.submitted_timestamps_us[i]
      ||ledger.encoded_timestamps_us[i]!==ledger.submitted_timestamps_us[i]
      ||Math.round(Number(p.duration_time)*1e6)!==ledger.durations_us[i]
      ||p.data_hash.toLowerCase()!=='sha256:'+ledger.encoded_sha256[i])throw Error('packet_timing_or_payload_hash_mismatch');
  }
  const end=ledger.encoded_timestamps_us.at(-1)+ledger.durations_us.at(-1);
  if(Math.round(Number(parsed.format.duration)*1e6)!==end)throw Error('duration_extent_mismatch');
  result.status='synthetic_encoder_packet_decode_verified';result.decoded_frames=40;
  result.module_sha256=sha(moduleBytes);result.api_calls=0;result.game_actions=0;
  await fs.writeFile(path.join(output,'ffprobe.json'),probe.stdout,{mode:0o600,flag:'wx'});
  await fs.writeFile(path.join(output,'receipt.json'),JSON.stringify(result,null,2)+'\n',{mode:0o600,flag:'wx'});
  console.log(JSON.stringify({status:result.status,frames:40,bytes:video.length,module_sha256:result.module_sha256,
    receipt:path.join(output,'receipt.json')}));
}finally{await browser?.close();await new Promise(resolve=>server.close(resolve));}
