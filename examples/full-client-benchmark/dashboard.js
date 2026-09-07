(() => {
  'use strict';
  const $=id=>document.getElementById(id), el=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=String(text);return node;};
  const phases=[['restore_baseline','Restore'],['start_server','Start server'],['login','Login'],['run_controller','Play'],['disconnect','Logout'],['collect_final','Verify XP'],['cleanup','Finish']];
  const labels={running:'In progress',requesting:'Awaiting API',completed:'Completed',failed:'Failed',interrupted:'Interrupted',recovering:'Recovering',recovered:'Recovered; invalid run',unavailable:'Evidence unavailable',idle:'Idle'};
  let snapshot=null,closed=false,timer;
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
  function playReplay(){
    player.play().catch(()=>{if(replay.open&&!player.error)$('replay-playback-status').textContent='Press Play recording to start.';});
  }
  function openReplay(url,row,trigger){
    replayFocus=trigger;replayRunId=row.id;replaySection=trigger.closest('tbody')?.id;
    $('replay-title').textContent=`${row.returned_model||row.requested_model||'Script / no evaluated model'} · ${row.id.slice(0,12)}`;
    replayVerification(row);
    $('replay-playback-status').textContent='Loading recording…';
    stopReplay();player.src=url.href;
    $('replay-direct').href=url.href;
    if(!replay.open)replay.showModal();
    $('replay-close').focus();
    playReplay();
  }
  $('replay-play').addEventListener('click',()=>{if(player.error)player.load();playReplay();});
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
  player.addEventListener('waiting',()=>{if(replay.open)$('replay-playback-status').textContent='Buffering recording…';});
  player.addEventListener('error',()=>{if(replay.open&&player.getAttribute('src'))$('replay-playback-status').textContent='The player could not load this recording. Try Play recording again or open the video directly.';});
  function recording(cell,row){
    const value=row.recording;
    if(!value){cell.textContent='Not linked';return;}
    try{
      const url=new URL(value.playback_url||value.url,location.href);
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
    if(row.no_op===true)node.append(el('small','No input actions executed'));
    else if(row.action_verification==='receipts_incomplete')node.append(el('small','Action evidence incomplete'));
    else if(row.action_verification!=='receipts_rechecked')node.append(el('small','Action receipts not verified'));
  }
  function renderLive(){
    const rows=snapshot.attempts;
    const row=rows.find(item=>['running','recovering','requesting'].includes(item.status))||rows[0];
    if(!row)return;
    const liveBadge=badge(row.status);
    if(row.status==='completed')liveBadge.textContent='Completed · saved result';
    $('live-badge').replaceWith(Object.assign(liveBadge,{id:'live-badge'}));
    $('live-id').textContent=row.id;
    $('live-title').textContent=row.requested_model?`${row.status==='completed'?'Latest result: ':''}${row.requested_model}${row.status==='completed'?'':' attempt'}`:row.mode==='script'?'Scripted integration attempt':'Full-client attempt';
    const phase=phases.find(([key])=>key===row.phase)?.[1]||'Preparing';
    const failedPhase=phases.find(([key])=>key===row.failure_phase)?.[1]||phase;
    const expectsRenderer=['running','requesting'].includes(row.status)&&['login','run_controller'].includes(row.phase);
    $('live-description').textContent=row.failure_code?`${failedPhase}: ${row.failure_code.replaceAll('_',' ')}.${row.api_response_saved?' The API response was saved; this attempt has no verified persisted score.':''}`
      :row.status==='completed'?'The latest saved run completed. Every group of frozen inputs appears below.'
      :`${phase}${expectsRenderer&&row.renderer_fresh===false?' · waiting for fresh renderer state':''}. ${row.kind==='integration'?'Integration run; no persisted benchmark score.':'Persisted XP becomes available after logout and verification.'}`;
    const current=phases.findIndex(([key])=>key===row.phase);$('phases').replaceChildren();
    for(const [index,[key,label]]of phases.entries()){const node=el('li',label),state=row.phase_states?.[key];if(state==='failed'){node.textContent=`${label}: failed`;node.className='phase-failed';}else if(row.status==='completed'||state==='returned')node.className='done';else if(index===current)node.className='current';$('phases').append(node);}
    $('live-model').textContent=row.returned_model||'Awaiting exact attribution';
    inputDetails($('live-actions'),row);
    const saved=Number.isFinite(row.persisted_xp);
    $('live-xp-label').textContent=saved?'Persisted XP · verified after logout':'Live XP change · diagnostic';
    $('live-xp').textContent=xp(saved?row.persisted_xp:row.diagnostic_xp);$('live-survival').textContent=alive(saved?row.alive_at_logout:row.alive_at_last_observation);
  }
  function renderComparisons(){
    const groups=snapshot.comparisons.map(group=>({group,rows:snapshot.attempts.filter(item=>group.attempt_ids.includes(item.id))}));
    const latest=rows=>Math.max(0,...rows.map(row=>row.created_at_ms||0));
    groups.sort((a,b)=>latest(b.rows)-latest(a.rows));
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
      for(const label of ['Exact model','Persisted XP','Input actions','At logout','API / play time','Publication evidence','Recording'])headRow.append(el('th',label));
      head.append(headRow);table.append(caption,head,body);wrap.append(table);block.append(wrap);
      for(const row of rows){
        const tr=el('tr'),identity=cell(tr,row.requested_model);identity.append(el('small',row.id.slice(0,12)));
        scoreCell(tr,row);inputDetails(cell(tr,null,'input-summary'),row);cell(tr,alive(row.alive_at_logout));
        const timing=cell(tr,`${seconds(row.timing.api_ms)} API`);timing.append(el('small',`${seconds(row.timing.controller_ms)} play`));
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
      const state=cell(tr);state.append(badge(row.status));if(row.no_op===true)state.append(el('small','No input actions'));if(row.failure_code)state.append(el('small',row.failure_code.replaceAll('_',' ')));
      if(row.api_outcome==='uncertain')state.append(el('small',row.api_response_saved?'API receipt saved; runner accounting uncertain':'API outcome uncertain'));
      if(row.kind==='integration')state.append(el('small','Unranked integration'));
      scoreCell(tr,row);cell(tr,xp(row.diagnostic_xp),'numeric');inputDetails(cell(tr,null,'input-summary'),row);publicationCell(tr,row);recording(cell(tr),row);$('history').append(tr);
    }
    $('scope').textContent=snapshot.truncated?'Comparison scope: displayed attempts only. Older attempts are outside this export.':'Read-only results. No runs are started from this page.';
  }
  function freshness(){
    if(!snapshot)return;
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
      const changed=!snapshot||JSON.stringify(next)!==JSON.stringify(snapshot);
      snapshot=next;if(changed){renderLive();renderComparisons();renderHistory();}freshness();
      if(replay.open){const row=snapshot.attempts.find(item=>item.id===replayRunId);if(row)replayVerification(row);}
    }catch{$('connection').className='stale';$('connection').textContent=snapshot?'Results feed unavailable · showing saved snapshot':'Results feed unavailable';}
    finally{if(!closed)timer=setTimeout(refresh,2000);}
  }
  window.addEventListener('pagehide',()=>{closed=true;clearTimeout(timer);stopReplay();});
  refresh();
})();
