(() => {
  'use strict';
  const $=id=>document.getElementById(id), el=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=String(text);return node;};
  const phases=[['restore_baseline','Restore'],['start_server','Start server'],['login','Login'],['run_controller','Play'],['disconnect','Logout'],['collect_final','Verify XP'],['cleanup','Finish']];
  const labels={not_started:'Not started',running:'In progress',requesting:'Awaiting API',completed:'Completed',failed:'Failed',interrupted:'Interrupted',recovering:'Recovering',recovered:'Recovered; invalid run',unavailable:'Evidence unavailable',idle:'Idle'};
  let snapshot=null,closed=false,timer;
  const format=value=>Number.isFinite(value)?value.toLocaleString('en-US'):'—';
  const xp=value=>Number.isFinite(value)?`${value>0?'+':''}${format(value)}`:'—';
  const seconds=value=>Number.isFinite(value)?`${(value/1000).toFixed(1)}s`:'—';
  const alive=value=>value===true?'Alive':value===false?'Dead':'—';
  const badge=status=>{const node=el('span',labels[status]||'Unavailable');node.className='pill';if(Object.hasOwn(labels,status))node.classList.add(status);return node;};
  function publication(row){
    const evidence=row.publication_evidence;
    if(evidence?.status==='adaptive_checked')return {label:'Adaptive evidence checked',detail:'Every model cycle and original recording checked',tone:'completed'};
    if(evidence?.status==='aggregate_checked')return {label:'Whole-run score checked',detail:'Recording not yet verified',tone:null};
    if(evidence?.status==='passed')return {label:'Evidence checked',detail:null,tone:'completed'};
    if(evidence?.status==='blocked')return {label:'Publication blocked',
      detail:evidence.reason_code==='receipts_incomplete'?'Receipts incomplete':evidence.reason_code==='evidence_unavailable'?'Evidence unavailable':'Check did not pass',tone:'failed'};
    if(evidence?.status==='awaiting_review')return {label:'Awaiting review',detail:null,tone:null};
    return {label:'Not evaluated',detail:null,tone:null};
  }
  function publicationCell(tr,row){
    const status=publication(row),node=cell(tr,null,'publication-status'),pill=el('span',status.label);
    pill.className='pill';if(status.tone)pill.classList.add(status.tone);node.append(pill);
    if(status.detail)node.append(el('small',status.detail));
  }
  let replayFocus=null,replayRunId=null,replaySection=null,replayCue=null,replayStart=0;
  const replay=$('replay'),player=$('replay-video');
  let replayEvents=null;
  const replayControls=new Set(['LEFT','RIGHT','UP','DOWN','JUMP','ATTACK','PRIMARY_SKILL','SECONDARY_SKILL','BUFF_1','BUFF_2','HP_POTION','MP_POTION','SKILL_5','SKILL_6','SKILL_7','SKILL_8','SKILL_9','SKILL_10','SKILL_11','SKILL_12','SKILL_13','SKILL_14','SKILL_15','SKILL_16','SKILL_17']);
  function checkedReplayTimeline(value){
    if(!value||value.schema_version!==1||value.clock!=='recording_media_ms'||value.input_basis!=='relay_request_ack_v1'
        ||!Number.isFinite(value.duration_ms)||value.duration_ms<=0||value.duration_ms>335000
        ||!Number.isFinite(value.timing_uncertainty_ms)||value.timing_uncertainty_ms<0||value.timing_uncertainty_ms>100)return null;
    for(const [field,max,width] of [['api_intervals',64,3],['input_intervals',2400,5]]){
      const rows=value[field];if(rows===null&&field==='input_intervals')continue;
      if(!Array.isArray(rows)||rows.length>max)return null;
      let previous=-1,cycle=-1;
      for(const row of rows){
        if(!Array.isArray(row)||row.length!==width||!row.slice(0,3).every(Number.isInteger)
            ||row[0]<0||row[1]<row[0]||row[1]>value.duration_ms||row[0]<previous||row[2]<cycle||row[2]<0||row[2]>=64)return null;
        if(width===5&&(!Array.isArray(row[3])||row[3].length<1||row[3].length>8
            ||!row[3].every(key=>replayControls.has(key))||new Set(row[3]).size!==row[3].length
            ||!Number.isInteger(row[4])||row[4]<1||row[4]>10000))return null;
        previous=row[1];cycle=row[2];
      }
    }
    return value;
  }
  function replayEventState(value,at){
    const api=value.api_intervals.find(item=>item[0]<=at&&at<item[1]);
    const input=value.input_intervals?.find(item=>item[0]<=at&&at<item[1]);
    return {api,input};
  }
  function updateReplayTimeline(){
    if(!replayEvents)return;
    const at=Math.max(0,Math.min(replayEvents.duration_ms,(player.currentTime||0)*1000));
    const {api,input}=replayEventState(replayEvents,at);
    $('replay-call-state').textContent=api?`Model call ${api[2]+1} · awaiting response`:'Between model calls';
    $('replay-call-state').dataset.waiting=String(Boolean(api));
    $('replay-position').textContent=`${seconds(at)} / ${seconds(replayEvents.duration_ms)}`;
    if(document.activeElement!==$('replay-seek'))$('replay-seek').value=at/1000;
    const keys=$('replay-input-state');keys.replaceChildren();
    if(input){for(const key of input[3]){const cap=el('kbd',key);keys.append(cap);}keys.append(el('span',`${input[4]} ms requested · delivery interval`));}
    else keys.append(el('span',replayEvents.input_intervals===null?'Input timing was not recorded for this attempt.':'No input delivery at this time.'));
    const canvas=$('replay-event-chart'),ctx=canvas.getContext('2d'),width=canvas.width;
    ctx.clearRect(0,0,width,66);ctx.fillStyle='#e9eddf';ctx.fillRect(0,0,width,66);
    for(const [rows,y,color] of [[replayEvents.api_intervals,7,'#997daf'],[replayEvents.input_intervals||[],36,'#c58d43']]){
      ctx.fillStyle=color;for(const row of rows)ctx.fillRect(row[0]/replayEvents.duration_ms*width,y,Math.max(1,(row[1]-row[0])/replayEvents.duration_ms*width),22);
    }
    ctx.fillStyle='#303631';ctx.fillRect(at/replayEvents.duration_ms*(width-2),0,2,66);
  }
  function renderReplayTimeline(row){
    replayEvents=checkedReplayTimeline(row.recording?.timeline);
    $('replay-events').hidden=!replayEvents;if(!replayEvents)return;
    $('replay-seek').max=replayEvents.duration_ms/1000;
    const jumps=$('replay-api-jumps');jumps.replaceChildren();
    for(const item of replayEvents.api_intervals){
      const button=el('button',`Call ${item[2]+1} · ${seconds(item[1]-item[0])}`);button.type='button';
      button.addEventListener('click',()=>playFrom(item[0]/1000));jumps.append(button);
    }
    $('replay-clock-note').textContent=`Violet: model requests. Orange: input request through acknowledgment. Clock alignment uncertainty ≤ ${replayEvents.timing_uncertainty_ms} ms. The key HUD burned into the video shows held browser keys; delivery intervals do not prove a cast or hit.`;
    updateReplayTimeline();
  }
  function stopReplay(){player.pause();player.removeAttribute('src');player.load();}
  function replayVerification(row){
    $('replay-verification').textContent=row.persisted_xp!=null
      ?'Persisted XP verified by the runner. Unranked recording.'
      :row.kind==='integration'?'Unscored integration recording.'
      :['failed','interrupted','recovered'].includes(row.status)?'No verified persisted score. This attempt is invalid for comparison.'
      :'No verified persisted score. Unranked recording.';
    const status=publication(row);
    $('replay-verification').textContent+=` ${status.label}${status.detail?' ('+status.detail.toLowerCase()+')':''}.`;
    if(row.attribution==='mismatch')$('replay-verification').textContent+=` Requested model: ${row.requested_model}.`;
  }
  function openReplay(url,row,trigger){
    replayFocus=trigger;replayRunId=row.id;replaySection=trigger.closest('tbody')?.id;
    $('replay-title').textContent=`${row.returned_model||row.requested_model||'Script / no evaluated model'} · ${row.id.slice(0,12)}`;
    replayVerification(row);
    const cue=row.recording?.playback;
    const adaptive=row.research?.protocol_id==='full-client-adaptive-pilot-v1';
    replayCue=cue&&Number.isFinite(cue.start_ms)&&cue.start_ms>=0&&cue.start_ms<(adaptive?335000:125000)
      &&['first_acknowledged_input','program_start'].includes(cue.basis)?cue:null;
    replayStart=replayCue?replayCue.start_ms/1000:0;
    $('replay-agent').hidden=!replayCue;
    $('replay-agent').textContent=replayCue?.basis==='first_acknowledged_input'?'First input':'Program start';
    $('replay-timing').textContent=(Number.isFinite(row.timing?.api_ms)?`${adaptive?'Total model wait across all cycles':'API wait'}: ${seconds(row.timing.api_ms)}. `:'')
      +(row.no_op===true?(row.sdk_calls===0?'The program exited without any SDK calls. ':'No input actions were executed in this run. ')+'Showing the full recording.'
      :replayCue?`Opens near ${replayCue.basis==='first_acknowledged_input'?'the first confirmed input':'program start; first-input timing was not recorded'}. Full recording includes the opening wait.`
      :'Showing the full recording; a verified playback cue is unavailable.');
    if(adaptive)$('replay-timing').textContent+=' The five-minute wall budget includes every model wait; seeking changes playback only.';
    const hold=adaptiveHold(row);if(hold)$('replay-timing').textContent+=' '+hold.detail;
    $('replay-playback-status').textContent='Loading recording…';
    stopReplay();player.src=url.href;
    if(typeof renderReplayTimeline==='function')renderReplayTimeline(row);
    if(!replay.open)replay.showModal();
    $('replay-close').focus();
  }
  function playFrom(seconds){
    replayStart=seconds;
    if(!replay.open||player.readyState<1)return;
    try{player.currentTime=Number.isFinite(player.duration)&&seconds>=player.duration?0:seconds;}
    catch{$('replay-playback-status').textContent='Seeking is unavailable. Use the video controls.';return;}
    player.play().catch(()=>{if(replay.open)$('replay-playback-status').textContent='Use Play to start the recording.';});
  }
  player.addEventListener('loadedmetadata',()=>playFrom(replayStart));
  player.addEventListener('timeupdate',updateReplayTimeline);
  player.addEventListener('seeked',updateReplayTimeline);
  $('replay-seek').addEventListener('input',event=>{
    if(replayEvents&&player.readyState>=1){player.currentTime=Number(event.target.value);updateReplayTimeline();}
  });
  $('replay-download').addEventListener('click',()=>{
    if(!replayEvents)return;
    const url=URL.createObjectURL(new Blob([JSON.stringify(replayEvents,null,2)+'\n'],{type:'application/json'}));
    const link=el('a');link.href=url;link.download=`maplebench-${replayRunId}-timeline.json`;link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  $('replay-agent').addEventListener('click',()=>{if(replayCue)playFrom(replayCue.start_ms/1000);});
  $('replay-full').addEventListener('click',()=>playFrom(0));
  $('replay-close').addEventListener('click',()=>replay.close());
  replay.addEventListener('close',()=>{
    stopReplay();
    if(closed)return;
    const replacement=[...document.querySelectorAll('button[data-recording-run]')].find(node=>node.dataset.recordingRun===replayRunId&&node.closest('tbody')?.id===replaySection);
    const target=replayFocus?.isConnected?replayFocus:replacement||$('live-title');
    if(target===$('live-title'))target.tabIndex=-1;
    target.focus();replayFocus=null;
  });
  player.addEventListener('playing',()=>{if(replay.open)$('replay-playback-status').textContent='Playing saved recording.';});
  player.addEventListener('ended',()=>{if(replay.open)$('replay-playback-status').textContent='Recording finished.';});
  player.addEventListener('error',()=>{if(replay.open&&player.getAttribute('src'))$('replay-playback-status').textContent='The recording could not be loaded.';});
  function recording(cell,row){
    const value=row.recording;
    if(!value){cell.textContent='Not linked';return;}
    try{
      const url=new URL(value.url,location.href);
      if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.search||url.hash
          ||!/^\/(?:[A-Za-z0-9_-]+\/){0,3}recordings\/[A-Za-z0-9_./-]+\.(webm|mp4)$/.test(url.pathname)
          ||url.origin!==location.origin)throw Error();
      const button=el('button','Watch recording');button.type='button';button.className='watch-recording';button.dataset.recordingRun=row.id;
      button.addEventListener('click',()=>openReplay(url,row,button));cell.append(button);
    }catch{cell.textContent='Not linked';}
  }
  function cell(row,value,className){const node=el('td',value);if(className)node.className=className;row.append(node);return node;}
  function scoreCell(tr,row){const node=cell(tr,xp(row.persisted_xp),'numeric');if(row.persisted_xp<0)node.classList.add('negative');else if(row.persisted_xp>0)node.classList.add('positive');if(row.persisted_xp!=null)node.append(el('small','Runner verified'));else node.append(el('small',row.kind==='integration'?'Unscored integration':['failed','interrupted','recovered'].includes(row.status)?'No verified score':'Awaiting verification'));}
  function inputDetails(node,row){
    if(!Number.isFinite(row.acknowledged_actions)&&Number.isFinite(row.reported_actions)){
      node.replaceChildren(el('span',`${format(row.reported_actions)} reported`),el('small','Action receipts not verified'));return;
    }
    node.replaceChildren(el('span',`${format(row.acknowledged_actions)} acknowledged`));
    if(Number.isFinite(row.action_attempts))node.append(el('small',`${format(row.action_attempts)} attempted`));
    if(row.no_op===true)node.append(el('small',row.sdk_calls===0?'Exited without SDK calls':'No input actions executed'));
    else if(row.action_verification==='receipts_incomplete')node.append(el('small','Action evidence incomplete'));
    else if(row.action_verification!=='receipts_rechecked')node.append(el('small','Action receipts not verified'));
  }
  function adaptiveHold(row){
    const info=row.adaptive,wait=info?.horizon_wait;
    const labels={token_reservation_limit:'Token reservation limit reached',api_request_limit:'Model request limit reached',
      action_limit:'Input action limit reached',sdk_request_limit:'SDK request limit reached',
      request_window_closed:'Too little time remained for another complete model cycle'};
    if(row.research?.protocol_id!=='full-client-adaptive-pilot-v1'||info?.verification!=='all_cycle_receipts_rechecked'
        ||info.horizon_policy?.id!=='full-horizon-reserve-v1'||!wait||!Object.hasOwn(labels,wait.reason)
        ||!Number.isFinite(info.wall_elapsed_ms)||info.wall_elapsed_ms<0||info.wall_elapsed_ms>300000
        ||!Number.isFinite(wait.started_ms)||!Number.isFinite(wait.ended_ms)
        ||wait.started_ms<0||wait.started_ms>info.wall_elapsed_ms||wait.ended_ms<wait.started_ms
        ||wait.ended_ms>info.wall_elapsed_ms+5000)return null;
    const duration=wait.ended_ms-wait.started_ms;
    return {brief:`${seconds(duration)} observation only`,
      detail:`${labels[wait.reason]} at ${seconds(wait.started_ms)}. Observation only for ${seconds(duration)} (${seconds(wait.started_ms)}–${seconds(wait.ended_ms)}): no new model requests or input actions; the game and recording continued.`};
  }
  function adaptiveDetails(row){
    if(row.research?.protocol_id!=='full-client-adaptive-pilot-v1')return null;
    const info=row.adaptive,details=el('details');details.className='adaptive-details';
    if(info?.verification!=='all_cycle_receipts_rechecked'){
      details.append(el('summary','Adaptive evidence not yet verified'));return details;
    }
    const hold=adaptiveHold(row);
    details.append(el('summary',`${info.counters.api_responses_confirmed} model responses · ${seconds(info.wall_elapsed_ms)} wall${hold?' · '+hold.brief:''}`));
    if(hold)details.append(el('p',hold.detail));
    details.append(el('p',`${info.full_wall_budget_used?'Full wall budget used':'Ended early'} · ${info.end_reason.replaceAll('_',' ')}. Persisted XP covers the complete run. Peak-rate scoring is unavailable.`));
    const profile=info.class_profile;
    if(profile)details.append(el('p',`${profile.class_name}, level ${profile.level}. Declared skills: ${Object.values(profile.skill_keys).join(', ')}.`));
    if(info.knowledge_pack)details.append(el('p',`Frozen knowledge: ${info.knowledge_pack.pack_id} · SHA-256 ${info.knowledge_pack.pack_sha256}.`));
    if(Array.isArray(info.skill_toolkit?.unsupported))details.append(el('p',`Fixture limits: ${info.skill_toolkit.unsupported.join(' ')}`));
    const table=el('table'),head=el('tr'),body=el('tbody');
    for(const name of ['Cycle','Exact model returned','Model wait','Program interval','Inputs','Tokens'])head.append(el('th',name));
    const header=el('thead');header.append(head);table.append(header,body);
    for(const cycle of info.cycles){
      const tr=el('tr'),timing=cycle.timing;cell(tr,cycle.index+1);
      const identity=cell(tr,cycle.returned_model||'No response');identity.append(el('small',cycle.status.replaceAll('_',' ')));
      cell(tr,Number.isFinite(timing.api_ended_ms)?seconds(timing.api_ended_ms-timing.api_started_ms):'—');
      cell(tr,Number.isFinite(timing.program_ended_ms)?seconds(timing.program_ended_ms-timing.program_started_ms):'—');
      cell(tr,`${format(cycle.actions)} acknowledged / ${format(cycle.action_attempts)} attempted`);
      cell(tr,format(cycle.usage.total_tokens));body.append(tr);
    }
    const wrap=el('div');wrap.className='table-wrap';wrap.append(table);details.append(wrap);return details;
  }
  function renderLive(){
    const rows=snapshot.attempts;
    const publicFeatured=snapshot.source==='full_client_public_catalog'&&rows.find(item=>item.id===snapshot.featured_run_id
      &&item.status==='completed'&&item.recording&&['runner_verified_receipts_rechecked','adaptive_runner_verified_receipts_rechecked'].includes(item.score_verification));
    const row=publicFeatured||rows.find(item=>['running','recovering','requesting'].includes(item.status))
      ||rows.find(item=>item.id===snapshot.featured_run_id)||rows[0];
    if(!row)return;
    const liveBadge=badge(row.status);
    if(row.status==='completed')liveBadge.textContent='Completed · saved result';
    $('live-badge').replaceWith(Object.assign(liveBadge,{id:'live-badge'}));
    $('live-id').textContent=row.id;
    const verifiedFeatured=row.id===snapshot.featured_run_id&&row.status==='completed'&&['runner_verified_receipts_rechecked','adaptive_runner_verified_receipts_rechecked'].includes(row.score_verification);
    $('live-title').textContent=row.requested_model?`${row.status==='completed'?(verifiedFeatured?'Latest verified result: ':'Latest result: '):''}${row.requested_model}${row.status==='completed'?'':' attempt'}`:row.mode==='script'?'Scripted integration attempt':'Full-client attempt';
    const phase=phases.find(([key])=>key===row.phase)?.[1]||'Preparing';
    const failedPhase=phases.find(([key])=>key===row.failure_phase)?.[1]||phase;
    const expectsRenderer=['running','requesting'].includes(row.status)&&['login','run_controller'].includes(row.phase);
    $('live-description').textContent=row.failure_code?`${failedPhase}: ${row.failure_code.replaceAll('_',' ')}.${row.api_response_saved?' The API response was saved; this attempt has no verified persisted score.':''}`
      :row.status==='not_started'?'This model is planned. No API request has started for this attempt.'
      :verifiedFeatured?'This verified run is featured for sharing. Progress for every planned model remains in the matrix and history below.'
      :row.status==='completed'?'The latest saved run completed. Every group of frozen inputs appears below.'
      :`${phase}${expectsRenderer&&row.renderer_fresh===false?' · waiting for fresh renderer state':''}. ${row.kind==='integration'?'Integration run; no persisted benchmark score.':'Persisted XP becomes available after logout and verification.'}`;
    const current=phases.findIndex(([key])=>key===row.phase);$('phases').replaceChildren();
    for(const [index,[key,label]]of phases.entries()){const node=el('li',label),state=row.phase_states?.[key];if(state==='failed'){node.textContent=`${label}: failed`;node.className='phase-failed';}else if(row.status==='completed'||state==='returned')node.className='done';else if(index===current)node.className='current';$('phases').append(node);}
    $('live-model').textContent=row.returned_model||'Awaiting exact attribution';
    inputDetails($('live-actions'),row);
    const featured=$('featured-recording');featured.replaceChildren();if(row.status==='completed'&&row.recording)recording(featured,row);
    const adaptive=$('adaptive-evidence');adaptive.replaceChildren();
    const hold=adaptiveHold(row);if(hold){const note=el('p',hold.detail);note.className='group-notice';adaptive.append(note);}
    const detail=adaptiveDetails(row);if(detail)adaptive.append(detail);
    const saved=Number.isFinite(row.persisted_xp);
    $('live-xp-label').textContent=saved?'Persisted XP · verified after logout':'Live XP change · diagnostic';
    $('live-xp').textContent=xp(saved?row.persisted_xp:row.diagnostic_xp);$('live-survival').textContent=alive(saved?row.alive_at_logout:row.alive_at_last_observation);
  }
  let previewSignature='';
  function renderOverview(){
    const root=$('gameplay-preview');if(!root)return;
    const rows=snapshot.attempts.filter(row=>row.status==='completed'&&row.recording
      &&['runner_verified_receipts_rechecked','adaptive_runner_verified_receipts_rechecked'].includes(row.score_verification));
    const latest=[...rows].sort((a,b)=>(b.updated_at_ms||0)-(a.updated_at_ms||0)).slice(0,2);
    $('hero-summary').textContent=`${new Set(snapshot.attempts.map(row=>row.requested_model).filter(Boolean)).size} models · ${rows.length} verified recordings · ${snapshot.attempts.length} planned or recorded attempts`;
    const signature=JSON.stringify(latest.map(row=>[row.id,row.recording.url,row.persisted_xp]));
    if(signature===previewSignature)return;previewSignature=signature;
    root.replaceChildren();
    for(const row of latest){
      // Reuse the same URL boundary and click handler as the evidence tables.
      const slot=el('div');recording(slot,row);const button=slot.querySelector('button');if(!button)continue;
      button.className='preview-run';button.replaceChildren();
      button.setAttribute('aria-label',`Watch ${row.requested_model}, ${xp(row.persisted_xp)} saved XP`);
      const video=el('video');video.src=new URL(row.recording.url,location.href).href;video.preload='metadata';video.muted=true;video.playsInline=true;video.setAttribute('aria-hidden','true');
      const cue=row.recording?.playback?.start_ms;
      if(Number.isFinite(cue)&&cue>=0)video.addEventListener('loadedmetadata',()=>{if(cue/1000<video.duration)video.currentTime=cue/1000;},{once:true});
      const identity=el('span');identity.className='preview-identity';identity.append(el('strong',row.requested_model),el('span',`${xp(row.persisted_xp)} saved XP`));
      const play=el('span','▶');play.className='preview-play';play.setAttribute('aria-hidden','true');
      button.append(video,identity,play);root.append(button);
    }
    if(!root.children.length){const empty=el('p','Recorded attempts appear here once their evidence is verified.');empty.className='empty';root.append(empty);}
  }
  function renderNativeQualification(){
    const root=$('native-qualification');if(!root)return;root.replaceChildren();
    const entries=snapshot.native_qualification?[{value:snapshot.native_qualification,url:'./native-qualification.json'}]
      :(snapshot.catalog?.cohorts||[]).filter(c=>c.native_qualification).map(c=>({value:c.native_qualification,url:c.native_qualification_url}));
    for(const {value,url} of entries){
      if(value?.status!=='core_toolkit_effects_qualified'||value.qualification_scope!=='core10'
          ||value.runtime_lifecycle_verified!==true
          ||value.baseline_restored!==true||!Array.isArray(value.qualified_skills)||value.qualified_skills.length!==10
          ||!Array.isArray(value.available_skills)||value.available_skills.length!==17
          ||!/^\.\/(?:cohorts\/[a-f0-9]{16}\/)?native-qualification\.json$/.test(url))continue;
      const detail=el('details');detail.append(el('summary','Hero toolkit · 17 available skills, 10 with native effect checks'));
      detail.append(el('p','A separate zero-model run checked native effects for the core ten skills, and verified the learned skills and bindings for all seventeen controls. The seven additional skills have not had their effects qualified by this run. The character was logged out normally and the baseline restored. Instrumentation was enabled for qualification only. This does not certify skill balance, proc probabilities or model proficiency.'));
      if(Array.isArray(value.unsupported))for(const scope of value.unsupported)detail.append(el('p',scope));
      const link=el('a','Download native qualification evidence');link.href=url;detail.append(link);root.append(detail);
    }
    root.hidden=!root.children.length;
  }
  function renderCatalog(){
    const node=$('catalog-cohorts'),catalog=snapshot.catalog;
    if(!node)return;
    const current=Array.isArray(catalog?.cohorts)?catalog.cohorts:[];
    const previous=catalog?.schema_version===2&&Array.isArray(catalog.previous_cohorts)?catalog.previous_cohorts:[];
    node.replaceChildren();node.hidden=!([1,2].includes(catalog?.schema_version)&&current.length<=3&&previous.length<=3);
    if(node.hidden)return;
    const names={hero:'Hero',bowmaster:'Bowmaster',ice_lightning_arch_mage:'Ice/Lightning Arch Mage'};
    for(const [cohorts,isPrevious] of [[current,false],[previous,true]]){
      if(!cohorts.length)continue;
      const group=el('div');
      group.append(el('p',isPrevious?'Previous pilot cohorts · separate frozen settings; excluded from the current matrix':'Current cohorts'));
      for(const cohort of cohorts){
        const planned=cohort.planned??4;
        if(!/^\.\/cohorts\/[a-f0-9]{16}\/$/.test(cohort.url)||!Number.isInteger(planned)||planned<4||planned>80||planned%4
          ||!Number.isInteger(cohort.verified)||cohort.verified<0||cohort.verified>planned)continue;
        const link=el('a',`${names[cohort.class_id]||'Declared class'} · ${cohort.verified} / ${planned} verified`);
        link.href=cohort.url;link.className='pill';group.append(link,document.createTextNode(' '));
      }
      node.append(group);
    }
  }
  function renderReliability(){
    const section=$('release-reliability'),container=$('reliability-groups');
    if(!section||!container)return;
    const cohorts=snapshot.cohort?[snapshot.cohort]:(snapshot.catalog?.cohorts||[]);
    container.replaceChildren();let count=0;
    for(const cohort of cohorts){
      const value=cohort.reliability;
      if(value?.schema_version!==1||!Array.isArray(value.groups)||value.groups.length>20
          ||value.required_consecutive_clean_groups!==3||!value.groups.every(g=>
            g.planned===4&&[g.attempted,g.verified_scores,g.verified_recordings].every(n=>Number.isInteger(n)&&n>=0&&n<=4)
            &&g.verified_recordings<=g.verified_scores&&g.verified_scores<=g.attempted))continue;
      const group=el('div'),table=el('table'),header=el('tr'),body=el('tbody');
      group.append(el('p',`Cohort ${cohort.id.slice(0,12)} · ${value.consecutive_clean_groups} consecutive clean groups`));
      for(const label of ['Group','Attempted / planned','Verified scores','Verified recordings','Disposition'])header.append(el('th',label));
      const head=el('thead');head.append(header);table.append(head,body);
      for(const item of value.groups){
        const tr=el('tr');cell(tr,item.group);cell(tr,`${item.attempted} / 4`);cell(tr,item.verified_scores);cell(tr,item.verified_recordings);
        cell(tr,item.clean?'Clean':Object.entries(item.causes||{}).map(([cause,n])=>`${n} ${cause.replaceAll('_',' ')}`).join(' · '));body.append(tr);
      }
      const wrap=el('div');wrap.className='table-wrap';wrap.append(table);group.append(wrap);container.append(group);count++;
    }
    section.hidden=count===0;
  }
  function renderResearch(){
    const matrix=snapshot.research_matrix,container=$('research-matrix'),select=$('research-protocol');
    const available=matrix?.schema_version===1&&Array.isArray(matrix.protocols)&&Array.isArray(matrix.columns)&&Array.isArray(matrix.models);
    $('research-empty').hidden=available;container.hidden=!available;select.disabled=!available;
    if(!available)return;
    const selected=select.value;select.replaceChildren();
    for(const protocol of matrix.protocols){const option=el('option',protocol.label);option.value=protocol.id;select.append(option);}
    if(matrix.protocols.some(item=>item.id===selected))select.value=selected;
    else if(snapshot.catalog&&matrix.protocols.some(item=>item.id==='full-client-adaptive-pilot-v1'))select.value='full-client-adaptive-pilot-v1';
    const protocol=matrix.protocols.find(item=>item.id===select.value),columns=matrix.columns.filter(item=>item.protocol_id===select.value);
    $('research-protocol-detail').textContent=protocol?`${protocol.clock}. ${protocol.metric}. ${protocol.status}.`:'';
    const table=el('table'),caption=el('caption',`${protocol?.label||'Protocol'}: model and class/task evidence`),head=el('thead'),heading=el('tr'),body=el('tbody');
    caption.className='visually-hidden';heading.append(el('th','Exact model'));
    for(const column of columns){const th=el('th',column.class_label);th.append(el('small',column.task_label),el('small',column.fixture_fingerprint==='undeclared'?'Fixture undeclared':`Fixture ${column.fixture_fingerprint.slice(0,10)}`));heading.append(th);}
    head.append(heading);table.append(caption,head,body);
    for(const model of matrix.models){
      const tr=el('tr');cell(tr,model.model);
      for(const column of columns){
        const value=model.cells.find(item=>item.column_id===column.id),td=cell(tr,null,'research-cell');
        if(!value||value.attempt_ids.length===0){td.textContent='No declared runs';continue;}
        td.append(el('strong',Number.isFinite(value.mean)?`${xp(value.mean)} mean net XP`:'No verified score'));
        td.append(el('small',`${value.valid} valid / ${value.attempted} attempted${value.planned==null?' · plan denominator unknown':` / ${value.planned} planned`}`));
        td.append(el('small',`${value.failed} failed · ${value.unknown} unknown · ${value.in_progress} in progress · ${value.not_started} not started`));
        if(value.valid>1)td.append(el('small',`Observed range ${xp(value.minimum)} to ${xp(value.maximum)}; uncertainty not estimated`));
        else if(value.valid===1)td.append(el('small','One sample; uncertainty not estimated'));
        if(value.no_ops)td.append(el('small',`${value.no_ops} verified no-input ${value.no_ops===1?'run':'runs'} retained`));
        if(Array.isArray(value.samples)&&value.samples.length<=80&&value.samples.every(Number.isFinite)){
          td.append(el('small',`Samples: ${value.samples.map(xp).join(', ')} XP`));
          if(Number.isFinite(value.median))td.append(el('small',`Median ${xp(value.median)} XP`));
          if(Number.isFinite(value.sample_standard_deviation))td.append(el('small',`Sample SD ${format(Math.round(value.sample_standard_deviation))} XP`));
          if(Number.isFinite(value.eligible_fraction))td.append(el('small',`${(value.eligible_fraction*100).toFixed(0)}% of attempted runs have eligible scores`));
        }
        for(const id of value.attempt_ids){const row=snapshot.attempts.find(item=>item.id===id);if(row?.recording){const link=el('span');recording(link,row);td.append(link);}}
      }
      body.append(tr);
    }
    container.replaceChildren(table);
  }
  $('research-protocol').addEventListener('change',renderResearch);
  function plannedFor(model){
    // Declared denominator, so a model with a retained failure reads 3 / 4.
    const matrix=snapshot.research_matrix;
    for(const row of (matrix&&Array.isArray(matrix.models)?matrix.models:[])){
      if(row.model!==model)continue;
      const total=(Array.isArray(row.cells)?row.cells:[]).reduce((a,c)=>a+(Number(c.planned)||0),0);
      if(total)return total;
    }
    return null;
  }
  function renderLeaderboard(rows){
    const body=$('leaderboard-rows'),note=$('leaderboard-note');
    if(!body)return;
    const byModel=new Map();
    for(const row of rows){
      const key=row.requested_model||'—';
      if(!byModel.has(key))byModel.set(key,{model:key,scores:[],attempts:0});
      const group=byModel.get(key);group.attempts++;
      if(Number.isFinite(row.persisted_xp))group.scores.push(row.persisted_xp);
    }
    const stats=[...byModel.values()].map(group=>{
      const sorted=[...group.scores].sort((a,b)=>a-b),n=sorted.length;
      const mean=n?sorted.reduce((a,b)=>a+b,0)/n:null;
      const median=n?(n%2?sorted[(n-1)/2]:(sorted[n/2-1]+sorted[n/2])/2):null;
      return Object.assign({},group,{n,mean,median,best:n?sorted[n-1]:null});
    }).sort((a,b)=>(b.mean===null?-Infinity:b.mean)-(a.mean===null?-Infinity:a.mean));
    body.replaceChildren();
    stats.forEach((group,index)=>{
      const tr=el('tr');
      cell(tr,String(index+1),'rank');
      cell(tr,group.model,'leader-model');
      cell(tr,`${group.n} / ${plannedFor(group.model)||group.attempts}`);
      cell(tr,group.mean===null?'—':xp(Math.round(group.mean)),'score');
      cell(tr,group.median===null?'—':xp(Math.round(group.median)));
      cell(tr,group.best===null?'—':xp(group.best));
      body.append(tr);
    });
    const scored=stats.reduce((a,g)=>a+g.n,0);
    const planned=stats.reduce((a,g)=>a+(plannedFor(g.model)||g.attempts),0);
    if(note)note.textContent=`${scored} verified of ${planned} planned attempts · ordered by mean saved XP.`
      +' One fixture and a few repetitions per model: descriptive only, not a ranking claim.';
  }
  function renderComparisons(){
    const groups=snapshot.comparisons.map(group=>({group,rows:snapshot.attempts.filter(item=>group.attempt_ids.includes(item.id))}));
    const latest=rows=>Math.max(0,...rows.map(row=>row.created_at_ms||0));
    groups.sort((a,b)=>latest(b.rows)-latest(a.rows));
    const primary=groups.find(item=>item.group.models.length>1)||groups[0];
    if(typeof renderLeaderboard==='function')renderLeaderboard(primary?primary.rows:[]);
    $('comparison-empty').hidden=groups.length>0;$('comparison-groups').replaceChildren();
    for(const [index,{group,rows}] of groups.entries()){
      const block=el('article'),heading=el('div'),title=el('h3',`${index===0?'Latest group':'Earlier group'} · ${group.models.length} ${group.models.length===1?'model':'models'}`);
      block.className='result-group';heading.className='group-heading';heading.append(title,el('span',`${rows.length} ${rows.length===1?'attempt':'attempts'} · ${group.id.slice(0,10)}`));block.append(heading);
      block.append(el('p',group.ready?'Matching baseline, scenario, budgets and runtime. Live scene equality is unverified; no ranking established.':'Separate frozen inputs. Its result is visible here; another model is needed for a within-group comparison.'));
      const noOps=rows.filter(row=>row.no_op===true),incomplete=rows.filter(row=>row.action_verification==='receipts_incomplete');
      if(noOps.length){const note=el('p',`${noOps.map(row=>row.requested_model).join(' and ')} executed no input actions. Their zero XP remains in the results.`);note.className='group-notice';block.append(note);}
      if(incomplete.length){const note=el('p',`${incomplete.map(row=>row.requested_model).join(' and ')} has incomplete action evidence. Persisted XP and publication status are shown separately.`);note.className='group-notice';block.append(note);}
      const wrap=el('div'),table=el('table'),caption=el('caption',`${title.textContent}: persisted outcomes`),head=el('thead'),headRow=el('tr'),body=el('tbody');
      wrap.className='table-wrap';caption.className='visually-hidden';body.id=`comparison-rows-${group.id}`;
      for(const label of ['Exact model','Persisted XP','Input actions','At logout','Timing','Publication evidence','Recording'])headRow.append(el('th',label));
      head.append(headRow);table.append(caption,head,body);wrap.append(table);block.append(wrap);
      for(const row of rows){
        const tr=el('tr'),identity=cell(tr,row.requested_model);identity.append(el('small',row.id.slice(0,12)));
        scoreCell(tr,row);inputDetails(cell(tr,null,'input-summary'),row);cell(tr,alive(row.alive_at_logout));
        const timing=cell(tr,`${seconds(row.timing.api_ms)} API`);
        timing.append(el('small',row.research?.protocol_id==='full-client-adaptive-pilot-v1'
          ?`${seconds(row.adaptive?.wall_elapsed_ms)} wall`:`${seconds(row.timing.controller_ms)} play`));
        const hold=adaptiveHold(row);if(hold)timing.append(el('small',hold.brief),el('small',hold.detail));
        publicationCell(tr,row);recording(cell(tr),row);body.append(tr);
      }
      $('comparison-groups').append(block);
    }
  }
  function renderHistory(){
    $('history').replaceChildren();$('history-empty').hidden=snapshot.attempts.length>0;
    $('count').textContent=`${snapshot.attempts.length} visible attempts${snapshot.truncated?' · recent window':''}`;
    for(const row of snapshot.attempts){
      const tr=el('tr'),identity=cell(tr);identity.append(el('strong',row.requested_model||'No evaluated model'),el('small',row.id));
      if(row.attribution==='mismatch')identity.append(el('small',`Returned ${row.returned_model}; attribution mismatch`));
      const detail=adaptiveDetails(row);if(detail)identity.append(detail);
      const state=cell(tr);state.append(badge(row.status));if(row.no_op===true)state.append(el('small','No input actions'));if(row.failure_code)state.append(el('small',row.failure_code.replaceAll('_',' ')));
      if(row.api_outcome==='uncertain')state.append(el('small',row.api_response_saved?'API receipt saved; runner accounting uncertain':'API outcome uncertain'));
      if(row.kind==='integration')state.append(el('small','Unranked integration'));
      scoreCell(tr,row);cell(tr,xp(row.diagnostic_xp),'numeric');inputDetails(cell(tr,null,'input-summary'),row);publicationCell(tr,row);recording(cell(tr),row);$('history').append(tr);
    }
    $('scope').textContent=snapshot.catalog
      ?`${snapshot.catalog.verified} of ${snapshot.catalog.planned} planned model/class runs have verified results. ${snapshot.catalog.archive_state==='retired'?'A complete four-model cohort replaced the public test recordings.':snapshot.catalog.archive_state==='retained'?'The public test archive remains until one four-model cohort is complete.':''} Saved progress refreshes every 10 seconds. No runs start from this page.`
      :snapshot.cohort
      ?`${snapshot.cohort.verified} of ${snapshot.cohort.planned} planned attempts have verified results. ${snapshot.cohort.archive_replacement?'This completed cohort replaces the public test archive.':'Cohort progress; the existing public archive is retained.'} No runs start from this page.`
      :snapshot.truncated?'Comparison scope: displayed attempts only. Older attempts are outside this export.':'Read-only results. No runs are started from this page.';
  }
  function freshness(){
    if(!snapshot)return;
    if(snapshot.source==='full_client_public_catalog'){
      $('connection').className='';
      $('connection').textContent=`Published results · refreshes every 10s · Snapshot ${new Date(snapshot.generated_at_ms).toLocaleString()}`;
      return;
    }
    if(snapshot.cohort&&snapshot.generated_at_ms===0){$('connection').textContent='Four-model cohort · awaiting the first attempt';return;}
    const age=Date.now()-snapshot.generated_at_ms,active=snapshot.attempts.some(row=>['running','requesting','recovering'].includes(row.status));
    const stale=age>10000||age< -1000||snapshot.live_status_available===false;
    $('connection').className=active&&stale?'stale':'';
    $('connection').textContent=active&&stale?'Live updates stale · showing saved snapshot':stale
      ?`Saved results · ${new Date(snapshot.generated_at_ms).toLocaleString()}`:`Snapshot updated ${Math.max(0,Math.floor(age/1000))}s ago`;
  }
  async function refresh(){
    if(closed)return;
    try{
      const response=await fetch('./results.json',{cache:'no-store',signal:AbortSignal.timeout(3000)});
      if(!response.ok)throw Error();const next=await response.json();
      if(next.schema_version!==1||!Array.isArray(next.attempts)||next.attempts.length>100||!Array.isArray(next.comparisons)||!Number.isFinite(next.generated_at_ms))throw Error();
      snapshot=next;renderCatalog();renderReliability();renderResearch();renderLive();renderOverview();renderNativeQualification();renderComparisons();renderHistory();freshness();
      if(replay.open){const row=snapshot.attempts.find(item=>item.id===replayRunId);if(row)replayVerification(row);}
    }catch{$('connection').className='stale';$('connection').textContent=snapshot?'Results feed unavailable · showing saved snapshot':'Results feed unavailable';}
    finally{if(!closed&&(snapshot?.live_status_available!==false||[1,2].includes(snapshot?.catalog?.schema_version)))timer=setTimeout(refresh,[1,2].includes(snapshot?.catalog?.schema_version)?10000:2000);}
  }
  window.addEventListener('pagehide',()=>{closed=true;clearTimeout(timer);stopReplay();});
  refresh();
})();
