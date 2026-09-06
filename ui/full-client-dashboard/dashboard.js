(() => {
  'use strict';
  const $=id=>document.getElementById(id), el=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=String(text);return node;};
  const phases=[['restore_baseline','Restore'],['start_server','Start server'],['login','Login'],['run_controller','Play'],['disconnect','Logout'],['collect_final','Verify XP'],['cleanup','Finish']];
  const labels={running:'In progress',requesting:'Awaiting API',completed:'Completed',failed:'Failed',interrupted:'Interrupted',recovering:'Recovering',recovered:'Recovered; invalid run',unavailable:'Evidence unavailable',idle:'Idle'};
  let snapshot=null,selected=null,closed=false,timer;
  const format=value=>Number.isFinite(value)?value.toLocaleString('en-US'):'—';
  const xp=value=>Number.isFinite(value)?`${value>0?'+':''}${format(value)}`:'—';
  const seconds=value=>Number.isFinite(value)?`${(value/1000).toFixed(1)}s`:'—';
  const alive=value=>value===true?'Alive':value===false?'Dead':'—';
  const badge=status=>{const node=el('span',labels[status]||'Unavailable');node.className='pill';if(Object.hasOwn(labels,status))node.classList.add(status);return node;};
  function publication(row){
    const evidence=row.publication_evidence;
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
  let replayFocus=null,replayRunId=null,replaySection=null;
  const replay=$('replay'),player=$('replay-video');
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
    $('replay-playback-status').textContent='Loading recording…';
    stopReplay();player.src=url.href;
    if(!replay.open)replay.showModal();
    $('replay-close').focus();
    player.play().catch(()=>{if(replay.open&&player.src===url.href)$('replay-playback-status').textContent='Use Play to start the recording.';});
  }
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
  function renderLive(){
    const rows=snapshot.attempts;
    const row=rows.find(item=>['running','recovering','requesting'].includes(item.status))||rows[0];
    if(!row)return;
    $('live-badge').replaceWith(Object.assign(badge(row.status),{id:'live-badge'}));
    $('live-id').textContent=row.id;
    $('live-title').textContent=row.requested_model?`${row.requested_model} attempt`:row.mode==='script'?'Scripted integration attempt':'Full-client attempt';
    const phase=phases.find(([key])=>key===row.phase)?.[1]||'Preparing';
    const failedPhase=phases.find(([key])=>key===row.failure_phase)?.[1]||phase;
    const expectsRenderer=['running','requesting'].includes(row.status)&&['login','run_controller'].includes(row.phase);
    $('live-description').textContent=row.failure_code?`${failedPhase}: ${row.failure_code.replaceAll('_',' ')}.${row.api_response_saved?' The API response was saved; this attempt has no verified persisted score.':''}`
      :row.status==='completed'?'The attempt finished. Its persisted outcome and recording appear below.'
      :`${phase}${expectsRenderer&&row.renderer_fresh===false?' · waiting for fresh renderer state':''}. ${row.kind==='integration'?'Integration run; no persisted benchmark score.':'Persisted XP becomes available after logout and verification.'}`;
    const current=phases.findIndex(([key])=>key===row.phase);$('phases').replaceChildren();
    for(const [index,[key,label]]of phases.entries()){const node=el('li',label),state=row.phase_states?.[key];if(state==='failed'){node.textContent=`${label}: failed`;node.className='phase-failed';}else if(row.status==='completed'||state==='returned')node.className='done';else if(index===current)node.className='current';$('phases').append(node);}
    $('live-model').textContent=row.returned_model||'Awaiting exact attribution';
    $('live-actions').textContent=`${format(row.actions)}${row.action_limit!=null?' / '+format(row.action_limit):''}`;
    $('live-xp').textContent=xp(row.diagnostic_xp);$('live-survival').textContent=alive(row.alive_at_last_observation);
  }
  function renderComparisons(){
    const groups=snapshot.comparisons;
    if(!groups.some(group=>group.id===selected))selected=groups.find(group=>group.ready)?.id||groups[0]?.id;
    $('groups').replaceChildren();
    if(!groups.length)$('groups').append(el('option','No verified starting state'));
    groups.forEach((group,index)=>{const option=el('option',`Group ${index+1}: ${group.models.length} models, ${group.attempt_ids.length} attempts`);option.value=group.id;option.selected=group.id===selected;$('groups').append(option);});
    $('groups').disabled=groups.length<2;
    const group=groups.find(item=>item.id===selected);
    $('comparison-empty').hidden=group?.ready===true;$('comparison-wrap').hidden=group?.ready!==true;$('comparison-rows').replaceChildren();
    for(const row of snapshot.attempts.filter(item=>group?.attempt_ids.includes(item.id))){
      const tr=el('tr');cell(tr,row.requested_model);scoreCell(tr,row);cell(tr,alive(row.alive_at_logout));
      cell(tr,seconds(row.timing.api_ms));cell(tr,seconds(row.timing.controller_ms));publicationCell(tr,row);recording(cell(tr),row);$('comparison-rows').append(tr);
    }
  }
  function renderHistory(){
    $('history').replaceChildren();$('history-empty').hidden=snapshot.attempts.length>0;
    $('count').textContent=`${snapshot.attempts.length} visible attempts${snapshot.truncated?' · recent window':''}`;
    for(const row of snapshot.attempts){
      const tr=el('tr'),identity=cell(tr);identity.append(el('strong',row.requested_model||'No evaluated model'),el('small',row.id));
      if(row.attribution==='mismatch')identity.append(el('small',`Returned ${row.returned_model}; attribution mismatch`));
      const state=cell(tr);state.append(badge(row.status));if(row.failure_code)state.append(el('small',row.failure_code.replaceAll('_',' ')));
      if(row.api_outcome==='uncertain')state.append(el('small',row.api_response_saved?'API receipt saved; runner accounting uncertain':'API outcome uncertain'));
      if(row.kind==='integration')state.append(el('small','Unranked integration'));
      scoreCell(tr,row);cell(tr,xp(row.diagnostic_xp),'numeric');cell(tr,format(row.actions),'numeric');publicationCell(tr,row);recording(cell(tr),row);$('history').append(tr);
    }
    $('scope').textContent=snapshot.truncated?'Comparison scope: displayed attempts only. Older attempts are outside this export.':'Read-only results. No runs are started from this page.';
  }
  function freshness(){if(!snapshot)return;const age=Date.now()-snapshot.generated_at_ms;const stale=age>10000||age< -1000||snapshot.live_status_available===false;$('connection').className=stale?'stale':'';$('connection').textContent=age>10000||age< -1000?'Results feed is stale':snapshot.live_status_available===false?'History updated · live status unavailable':`Updated ${Math.max(0,Math.floor(age/1000))}s ago`;}
  async function refresh(){
    if(closed)return;
    try{
      const response=await fetch('./results.json',{cache:'no-store',signal:AbortSignal.timeout(3000)});
      if(!response.ok)throw Error();const next=await response.json();
      if(next.schema_version!==1||!Array.isArray(next.attempts)||next.attempts.length>100||!Array.isArray(next.comparisons)||!Number.isFinite(next.generated_at_ms))throw Error();
      snapshot=next;renderLive();renderComparisons();renderHistory();freshness();
      if(replay.open){const row=snapshot.attempts.find(item=>item.id===replayRunId);if(row)replayVerification(row);}
    }catch{$('connection').className='stale';$('connection').textContent=snapshot?'Results feed unavailable · showing saved snapshot':'Results feed unavailable';}
    finally{if(!closed)timer=setTimeout(refresh,2000);}
  }
  $('groups').addEventListener('change',()=>{selected=$('groups').value;renderComparisons();});
  window.addEventListener('pagehide',()=>{closed=true;clearTimeout(timer);stopReplay();});
  refresh();
})();
