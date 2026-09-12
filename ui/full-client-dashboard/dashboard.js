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
  const adaptiveRow=row=>['full-client-adaptive-pilot-v1','full-client-xp-windows-v1'].includes(row.research?.protocol_id||row.protocol_id);
  const wallBudget=row=>row.adaptive?.wall_budget_ms===1800000&&row.adaptive?.horizon_policy?.id==='final-program-slot-1800-v1'?1800000:300000;
  const nativeScore=row=>row.score_verification==='native_window_runner_receipts_rechecked'
    &&row.native_xp?.status==='verified_native_windows'&&row.native_xp.publication_eligible===true
    &&row.native_xp.publication_blocker===null?row.native_xp:null;
  const badge=status=>{const node=el('span',labels[status]||'Unavailable');node.className='pill';if(Object.hasOwn(labels,status))node.classList.add(status);return node;};
  function publication(row){
    const evidence=row.publication_evidence;
    if(evidence?.status==='native_windows_checked'&&nativeScore(row))return {label:'Native XP windows checked',detail:'Saved XP, complete windows and recording reviewed',tone:'completed'};
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
    const adaptive=adaptiveRow(row);
    replayCue=cue&&Number.isFinite(cue.start_ms)&&cue.start_ms>=0&&cue.start_ms<(adaptive?wallBudget(row)+35000:125000)
      &&['first_acknowledged_input','program_start'].includes(cue.basis)?cue:null;
    replayStart=replayCue?replayCue.start_ms/1000:0;
    $('replay-agent').hidden=!replayCue;
    $('replay-agent').textContent=replayCue?.basis==='first_acknowledged_input'?'First input':'Program start';
    $('replay-timing').textContent=(Number.isFinite(row.timing?.api_ms)?`${adaptive?'Total model wait across all cycles':'API wait'}: ${seconds(row.timing.api_ms)}. `:'')
      +(row.no_op===true?(row.sdk_calls===0?'The program exited without any SDK calls. ':'No input actions were executed in this run. ')+'Showing the full recording.'
      :replayCue?`Opens near ${replayCue.basis==='first_acknowledged_input'?'the first confirmed input':'program start; first-input timing was not recorded'}. Full recording includes the opening wait.`
      :'Showing the full recording; a verified playback cue is unavailable.');
    if(adaptive)$('replay-timing').textContent+=` The ${wallBudget(row)/60000}-minute wall budget includes every model wait; seeking changes playback only.`;
    const hold=adaptiveHold(row);if(hold)$('replay-timing').textContent+=' '+hold.detail;
    $('replay-playback-status').textContent='Loading recording…';
    stopReplay();player.src=url.href;
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
      final_program_complete:'The final model program finished',
      request_window_closed:'Too little time remained for another complete model cycle'};
    if(!adaptiveRow(row)||info?.verification!=='all_cycle_receipts_rechecked'
        ||!['full-horizon-reserve-v1','final-program-slot-v1','final-program-slot-1800-v1'].includes(info.horizon_policy?.id)||!wait||!Object.hasOwn(labels,wait.reason)
        ||!Number.isFinite(info.wall_elapsed_ms)||info.wall_elapsed_ms<0||info.wall_elapsed_ms>wallBudget(row)
        ||!Number.isFinite(wait.started_ms)||!Number.isFinite(wait.ended_ms)
        ||wait.started_ms<0||wait.started_ms>info.wall_elapsed_ms||wait.ended_ms<wait.started_ms
        ||wait.ended_ms>info.wall_elapsed_ms+5000)return null;
    const duration=wait.ended_ms-wait.started_ms;
    return {brief:`${seconds(duration)} observation only`,
      detail:`${labels[wait.reason]} at ${seconds(wait.started_ms)}. Observation only for ${seconds(duration)} (${seconds(wait.started_ms)}–${seconds(wait.ended_ms)}): no new model requests or input actions; the game and recording continued.`};
  }
  function adaptiveDetails(row){
    if(!adaptiveRow(row))return null;
    const info=row.adaptive,details=el('details');details.className='adaptive-details';
    if(info?.verification!=='all_cycle_receipts_rechecked'){
      details.append(el('summary','Adaptive evidence not yet verified'));return details;
    }
    const hold=adaptiveHold(row);
    details.append(el('summary',`${info.counters.api_responses_confirmed} model responses · ${seconds(info.wall_elapsed_ms)} wall${hold?' · '+hold.brief:''}`));
    if(hold)details.append(el('p',hold.detail));
    details.append(el('p',`${info.full_wall_budget_used?'Full wall budget used':'Ended early'} · ${info.end_reason.replaceAll('_',' ')}. Persisted XP covers the complete run. ${nativeScore(row)?'Authoritative peak-rate evidence appears below.':'Peak-rate scoring is unavailable.'}`));
    const profile=info.class_profile;
    if(profile){
      details.append(el('p',`${profile.class_name}, level ${profile.level}. The model chooses among the skills mapped for this fixture.`));
      const usage=info.skill_usage,skillTable=el('table'),skillHeader=el('tr'),skillBody=el('tbody');
      for(const label of ['Available skill','Control','Confirmed inputs'])skillHeader.append(el('th',label));
      const heading=el('thead');heading.append(skillHeader);skillTable.append(heading,skillBody);
      for(const [key,name] of Object.entries(profile.skill_keys)){
        const recorded=usage?.basis==='acknowledged_skill_inputs'&&Array.isArray(usage.skills)
          ?usage.skills.find(item=>item.key===key&&item.name===name):null;
        const tr=el('tr');cell(tr,name);cell(tr,key);
        cell(tr,Number.isSafeInteger(recorded?.acknowledged_inputs)&&recorded.acknowledged_inputs>=0
          ?format(recorded.acknowledged_inputs):'Not recorded');skillBody.append(tr);
      }
      const wrap=el('div');wrap.className='table-wrap';wrap.append(skillTable);details.append(wrap);
      details.append(el('p','Input counts show acknowledged key presses. Successful casts and server effects need separate evidence. Skills absent from this list were not available through the mapped controls.'));
    }
    const breakdown=info.timing_breakdown;
    if(breakdown?.basis==='verified_cycle_intervals')details.append(el('p',`Model wait: ${seconds(breakdown.model_wait_ms)} · Program execution: ${seconds(breakdown.program_ms)} · Observation only: ${seconds(breakdown.observation_only_ms)}. Programs can include waits; execution time is not continuous key input.`));
    if(['final-program-slot-v1','final-program-slot-1800-v1'].includes(info.horizon_policy?.id))details.append(el('p','The final program can use fresh SDK observations for up to 145 seconds without another model response. Model waiting still counts against the wall-clock budget.'));
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
  function nativeDetails(row){
    const score=nativeScore(row);if(!score)return null;
    const windows=score.windows;
    if(!Array.isArray(windows)||windows.length<1||windows.length>120
        ||!windows.every(w=>Number.isFinite(w.end_ms)&&Number.isFinite(w.best_so_far)&&w.best_so_far>=0))return null;
    const section=el('section');section.className='native-xp-details';
    section.append(el('h3',`${format(score.authoritative_peak_xp_per_minute)} peak normalized XP/min`));
    section.append(el('p',`${score.complete_windows} complete 15-second windows. Control-window net XP: ${xp(score.control_window_net_xp)}. Saved net XP: ${xp(score.persisted_net_xp)}. Level ${score.initial_level} → ${score.final_level}.`));
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox','0 0 640 180');svg.setAttribute('role','img');
    svg.setAttribute('aria-label','Best normalized XP per minute discovered over elapsed time. Exact values are in the table below.');
    const maximum=Math.max(1,...windows.map(w=>w.best_so_far)),end=Math.max(1,...windows.map(w=>w.end_ms));
    const line=document.createElementNS(svg.namespaceURI,'path');let path='M 50 145';
    for(const window of windows){const x=50+window.end_ms/end*570,y=145-window.best_so_far/maximum*115;
      path+=` H ${x} V ${y}`;}
    line.setAttribute('d',path);line.setAttribute('fill','none');line.setAttribute('stroke','currentColor');line.setAttribute('stroke-width','3');svg.append(line);
    for(const [x,y,text] of [[5,30,format(maximum)],[15,145,'0'],[50,170,'0s'],[550,170,seconds(end)]]){
      const label=document.createElementNS(svg.namespaceURI,'text');label.setAttribute('x',x);label.setAttribute('y',y);label.setAttribute('fill','currentColor');label.setAttribute('font-size','12');label.textContent=text;svg.append(label);}
    section.append(svg);
    const details=el('details');details.append(el('summary','Inspect authoritative XP windows'));
    const table=el('table'),heading=el('tr'),head=el('thead'),body=el('tbody');
    for(const label of ['Window','Signed XP','Normalized XP/min','Best so far'])heading.append(el('th',label));head.append(heading);table.append(head,body);
    for(const window of windows){const tr=el('tr');cell(tr,`${seconds(window.start_ms)}–${seconds(window.end_ms)}`);cell(tr,xp(window.net_xp));cell(tr,format(window.normalized_xp_per_minute));cell(tr,format(window.best_so_far));body.append(tr);}
    const wrap=el('div');wrap.className='table-wrap';wrap.append(table);details.append(wrap);section.append(details);
    section.append(el('p','The curve shows the best completed window so far. A brief peak does not establish sustained efficiency. Signed XP losses remain in the window table and saved total.'));
    return section;
  }
  function renderLive(){
    const rows=snapshot.attempts;
    const publicFeatured=snapshot.source==='full_client_public_catalog'&&rows.find(item=>item.id===snapshot.featured_run_id
      &&item.status==='completed'&&item.recording&&['runner_verified_receipts_rechecked','adaptive_runner_verified_receipts_rechecked','native_window_runner_receipts_rechecked'].includes(item.score_verification));
    const row=publicFeatured||rows.find(item=>['running','recovering','requesting'].includes(item.status))
      ||rows.find(item=>item.id===snapshot.featured_run_id)||rows[0];
    if(!row)return;
    const liveBadge=badge(row.status);
    if(row.status==='completed')liveBadge.textContent='Completed · saved result';
    $('live-badge').replaceWith(Object.assign(liveBadge,{id:'live-badge'}));
    $('live-id').textContent=row.id;
    const verifiedFeatured=row.id===snapshot.featured_run_id&&row.status==='completed'&&['runner_verified_receipts_rechecked','adaptive_runner_verified_receipts_rechecked','native_window_runner_receipts_rechecked'].includes(row.score_verification);
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
    const native=nativeDetails(row);if(native)adaptive.append(native);
    const saved=Number.isFinite(row.persisted_xp);
    $('live-xp-label').textContent=saved?'Persisted XP · verified after logout':'Live XP change · diagnostic';
    $('live-xp').textContent=xp(saved?row.persisted_xp:row.diagnostic_xp);$('live-survival').textContent=alive(saved?row.alive_at_logout:row.alive_at_last_observation);
  }
  function renderCatalog(){
    const node=$('catalog-cohorts'),catalog=snapshot.catalog;
    if(!node)return;
    const current=Array.isArray(catalog?.cohorts)?catalog.cohorts:[];
    const previous=catalog?.schema_version===2&&Array.isArray(catalog.previous_cohorts)?catalog.previous_cohorts:[];
    node.replaceChildren();node.hidden=!([1,2].includes(catalog?.schema_version)&&current.length<=4&&previous.length<=4);
    if(node.hidden)return;
    const names={hero:'Hero',bowmaster:'Bowmaster',ice_lightning_arch_mage:'Ice/Lightning Arch Mage',night_lord:'Night Lord'};
    for(const [cohorts,isPrevious] of [[current,false],[previous,true]]){
      if(!cohorts.length)continue;
      const group=el('div');
      group.append(el('p',isPrevious?'Previous pilot cohorts · separate frozen settings; excluded from the current matrix':'Current cohorts'));
      for(const cohort of cohorts){
        if(!/^\.\/cohorts\/[a-f0-9]{16}\/$/.test(cohort.url)||!Number.isInteger(cohort.verified)||cohort.verified<0||cohort.verified>4)continue;
        const link=el('a',`${names[cohort.class_id]||'Declared class'} · ${cohort.verified} / 4 verified`);
        link.href=cohort.url;link.className='pill';group.append(link,document.createTextNode(' '));
      }
      node.append(group);
    }
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
        td.append(el('strong',Number.isFinite(value.mean)?protocol.score_key==='authoritative_peak_xp_per_minute'
          ?`${format(value.mean)} mean peak XP/min`:`${xp(value.mean)} mean net XP`:'No verified score'));
        td.append(el('small',`${value.valid} valid / ${value.attempted} attempted${value.planned==null?' · plan denominator unknown':` / ${value.planned} planned`}`));
        td.append(el('small',`${value.failed} failed · ${value.unknown} unknown · ${value.in_progress} in progress · ${value.not_started} not started`));
        if(value.valid>1)td.append(el('small',`Observed range ${xp(value.minimum)} to ${xp(value.maximum)}; uncertainty not estimated`));
        else if(value.valid===1)td.append(el('small','One sample; uncertainty not estimated'));
        if(value.no_ops)td.append(el('small',`${value.no_ops} verified no-input ${value.no_ops===1?'run':'runs'} retained`));
        for(const id of value.attempt_ids){const row=snapshot.attempts.find(item=>item.id===id);if(row?.recording){const link=el('span');recording(link,row);td.append(link);}}
      }
      body.append(tr);
    }
    container.replaceChildren(table);
  }
  $('research-protocol').addEventListener('change',renderResearch);
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
      for(const label of ['Exact model','Persisted XP','Input actions','At logout','Timing','Publication evidence','Recording'])headRow.append(el('th',label));
      head.append(headRow);table.append(caption,head,body);wrap.append(table);block.append(wrap);
      for(const row of rows){
        const tr=el('tr'),identity=cell(tr,row.requested_model);identity.append(el('small',row.id.slice(0,12)));
        scoreCell(tr,row);inputDetails(cell(tr,null,'input-summary'),row);cell(tr,alive(row.alive_at_logout));
        const timing=cell(tr,`${seconds(row.timing.api_ms)} API`);
        timing.append(el('small',adaptiveRow(row)
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
    for(const row of snapshot.attempts.filter(r=>!$('history-filter')||$('history-filter').value==='all'||($('history-filter').value==='completed'?r.status==='completed':r.status!=='completed'))){
      const tr=el('tr'),identity=cell(tr);identity.append(el('strong',row.requested_model||'No evaluated model'),el('small',row.id));
      if(row.attribution==='mismatch')identity.append(el('small',`Returned ${row.returned_model}; attribution mismatch`));
      const detail=adaptiveDetails(row);if(detail){const native=nativeDetails(row);if(native)detail.append(native);identity.append(detail);}
      const state=cell(tr);state.append(badge(row.status));if(row.no_op===true)state.append(el('small','No input actions'));if(row.failure_code)state.append(el('small',row.failure_code.replaceAll('_',' ')));
      if(row.api_outcome==='uncertain')state.append(el('small',row.api_response_saved?'API receipt saved; runner accounting uncertain':'API outcome uncertain'));
      if(row.kind==='integration')state.append(el('small','Unranked integration'));
      scoreCell(tr,row);cell(tr,xp(row.diagnostic_xp),'numeric');inputDetails(cell(tr,null,'input-summary'),row);publicationCell(tr,row);recording(cell(tr),row);$('history').append(tr);
    }
    $('scope').textContent=snapshot.catalog
      ?`${snapshot.catalog.verified} of ${snapshot.catalog.planned} planned model/class runs have verified results. ${snapshot.catalog.archive_state==='retired'?'A complete four-model cohort replaced the public test recordings.':snapshot.catalog.archive_state==='retained'?'The public test archive remains until one four-model cohort is complete.':''} Saved progress refreshes every 10 seconds. No runs start from this page.`
      :snapshot.cohort
      ?`${snapshot.cohort.verified} of ${snapshot.cohort.planned} planned models have verified results. ${snapshot.cohort.archive_replacement?'This completed cohort replaces the public test archive.':'Cohort progress; the existing public archive is retained.'} No runs start from this page.`
      :snapshot.truncated?'Comparison scope: displayed attempts only. Older attempts are outside this export.':'Read-only results. No runs are started from this page.';
  }
  // Public research presentation; all scores and evidence come from the same snapshot.
  const node=(tag,text,cls)=>{const n=el(tag,text);if(cls)n.className=cls;return n;};
  const number=format,duration=seconds;
  const model=row=>row.returned_model||row.requested_model||'Unattributed';
  const names={'gpt-6-astra':'GPT-6 Astra','gpt-5.6-sol':'GPT-5.6 Sol','gpt-5.6-terra':'GPT-5.6 Terra','gpt-5.6-luna':'GPT-5.6 Luna'};
  const name=row=>names[model(row)]||model(row);
  const colors={'gpt-6-astra':'#609b8b','gpt-5.6-sol':'#d2a35b','gpt-5.6-terra':'#a580b7','gpt-5.6-luna':'#6f9bc6'};
  const color=row=>colors[model(row)]||'#78847b';
  const status=row=>labels[row.status]||'Incomplete';
  let recordings=[],selected,filterModel,previewsPlaying=false,presentationIdentity='',montageIdentity='';
  const runPlayer=$('run-video'),reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
  function safeRecording(row) {
    try {
      const u=new URL(row.recording.url,location.href);
      if(u.origin!==location.origin||!['http:','https:'].includes(u.protocol)||u.username||u.password||u.search||u.hash
        ||!/^\/(?:[A-Za-z0-9_-]+\/){0,3}recordings\/[A-Za-z0-9_./-]+\.(webm|mp4)$/.test(u.pathname))return null;
      return u.href;
    }catch{return null;}
  }
  function cue(row) {
    const c=row?.recording?.playback;
    return c&&Number.isFinite(c.start_ms)&&c.start_ms>=0
      &&c.start_ms<(adaptiveRow(row)?wallBudget(row)+35000:125000)
      &&['program_start','first_acknowledged_input'].includes(c.basis)?c:null;
  }
  function montageRows(group,rows) {
    if(!group||!Array.isArray(group.models)||!Array.isArray(group.attempt_ids))return [];
    const order=['gpt-6-astra','gpt-5.6-sol','gpt-5.6-terra','gpt-5.6-luna'];
    return [...new Set(group.models)].sort((a,b)=>(order.indexOf(a)<0?99:order.indexOf(a))-(order.indexOf(b)<0?99:order.indexOf(b)))
      .map(exact=>({model:exact,row:rows.find(r=>group.attempt_ids.includes(r.id)&&r.requested_model===exact
        &&r.returned_model===exact&&r.attribution!=='mismatch'&&safeRecording(r))||null}));
  }
  function runOutcome(row) {
    if(!Number.isFinite(row.persisted_xp))return 'No verified saved XP score is available for this attempt.';
    const saved=row.persisted_xp===0?'The run ended with zero net saved XP.':row.persisted_xp<0
      ?`${xp(row.persisted_xp)} net XP remained after logout, including losses.`
      :`${xp(row.persisted_xp)} XP remained saved after normal logout.`;
    return saved+(row.no_op===true?' No input actions were executed.':'');
  }
  function groupLabel(group) {
    const row=snapshot.attempts.find(r=>group.attempt_ids.includes(r.id));
    const className=row?.adaptive?.class_profile?.class_name||row?.research?.class_id?.replaceAll('_',' ')||'Undeclared class';
    return `${className} · ${new Set(group.models).size} models · ${adaptiveRow(row||{})?wallBudget(row)/60000+' min':'legacy'}`;
  }
  function dot(row){const d=node('span',null,'model-dot');d.style.setProperty('--model-color',color(row));return d;}
  function watch(row){
    if(!safeRecording(row))return node('span','Not recorded','muted small');
    const b=node('button','Watch ↗','watch-button');b.type='button';b.setAttribute('aria-label',`Watch ${name(row)} attempt ${row.id.slice(0,8)}`);
    b.addEventListener('click',()=>openRun(row));return b;
  }
  function setPreviews(play){
    previewsPlaying=play;
    for(const v of document.querySelectorAll('.montage video')){if(play)v.play().catch(()=>{});else v.pause();}
    $('montage-toggle').textContent=play?'Pause previews':'Play previews';
    $('montage-toggle').setAttribute('aria-pressed',String(play));
  }
  function renderMontage(){
    const group=snapshot.comparisons.find(g=>g.id===$('showcase-select').value),picks=montageRows(group,snapshot.attempts);
    const identity=JSON.stringify([group?.id,picks.map(p=>[p.model,p.row?.id,p.row?.persisted_xp,p.row?.recording])]);
    if(identity===montageIdentity)return;montageIdentity=identity;
    setPreviews(false);$('montage').replaceChildren();$('montage').classList.toggle('single',picks.length===1);
    $('montage-toggle').hidden=!picks.some(p=>p.row);
    $('showcase-class').textContent=group?groupLabel(group):'Awaiting a declared group';
    $('showcase-caption').textContent=group?`${picks.length} models · one frozen class setup`:'No group published';
    document.querySelector('.sample-note').textContent='Independent recorded attempts; previews open at verified playback cues. The full recordings retain every wait. These are unranked pilot observations.';
    if(!picks.length){$('montage').append(node('p','No declared group is available.','loading'));return;}
    for(const {model:exact,row:r}of picks){
      if(!r){const empty=node('div',null,'montage-tile empty-preview');empty.append(node('span',names[exact]||exact),node('small','Recording unavailable'));$('montage').append(empty);continue;}
      const tile=node('button',null,'montage-tile is-loading');tile.type='button';tile.setAttribute('aria-label',`Explore ${name(r)}, ${xp(r.persisted_xp)} saved XP`);
      const v=node('video');v.muted=true;v.playsInline=true;v.preload='metadata';v.tabIndex=-1;v.setAttribute('aria-hidden','true');v.src=safeRecording(r);
      let previewStart=0;
      v.addEventListener('loadedmetadata',()=>{const start=(cue(r)?.start_ms||0)/1000;if(start>0&&start<v.duration){previewStart=start;v.currentTime=start;}else tile.classList.remove('is-loading');});
      v.addEventListener('seeked',()=>tile.classList.remove('is-loading'),{once:true});
      v.addEventListener('loadeddata',()=>{if(!previewStart)tile.classList.remove('is-loading');});
      v.addEventListener('ended',()=>{v.currentTime=previewStart;if(previewsPlaying)v.play().catch(()=>{});});
      v.addEventListener('error',()=>{tile.classList.remove('is-loading');tile.classList.add('video-unavailable');});
      const caption=node('span',null,'tile-caption');caption.append(dot(r),node('span',name(r)),node('span',`${xp(r.persisted_xp)} saved XP`,'tile-score'));
      tile.append(v,caption,node('span','▶','tile-play'));tile.addEventListener('click',()=>openRun(r));$('montage').append(tile);
    }
    if(!reducedMotion.matches&&!document.hidden)setPreviews(true);
  }
  function renderComparison(){
    const group=snapshot.comparisons.find(g=>g.id===$('comparison-select').value);
    const rows=group?snapshot.attempts.filter(r=>group.attempt_ids.includes(r.id)):[];
    const values=rows.map(r=>r.persisted_xp).filter(Number.isFinite),low=Math.min(0,...values),high=Math.max(0,...values);
    const floor=low<0?Math.floor(low/1000)*1000:0,ceiling=Math.max(floor+1000,Math.ceil(high/1000)*1000),span=ceiling-floor;
    $('xp-chart').replaceChildren();$('comparison-rows').replaceChildren();
    for(const r of rows){
      const chart=node('div',null,'chart-row');chart.style.setProperty('--model-color',color(r));
      const label=node('span',null,'chart-model');label.append(dot(r),node('span',name(r)));
      const track=node('div',null,'chart-track'),bar=node('div',null,'chart-bar');
      track.style.setProperty('--zero',`${-floor/span*100}%`);
      if(Number.isFinite(r.persisted_xp)){bar.style.left=`${(Math.min(0,r.persisted_xp)-floor)/span*100}%`;bar.style.width=`${Math.abs(r.persisted_xp)/span*100}%`;bar.classList.toggle('negative',r.persisted_xp<0);bar.classList.toggle('zero',r.persisted_xp===0);}else bar.hidden=true;
      track.append(bar);chart.append(label,track,node('span',xp(r.persisted_xp),'chart-value'));$('xp-chart').append(chart);
      const tr=node('tr'),identity=cell(tr);identity.append(dot(r),node('strong',name(r)),node('small',r.id.slice(0,12)));
      if(r.attribution==='mismatch')identity.append(node('small',`Requested ${r.requested_model}; returned attribution mismatch`));
      scoreCell(tr,r);inputDetails(cell(tr),r);
      const time=cell(tr,adaptiveRow(r)?`${seconds(r.adaptive?.wall_elapsed_ms)} wall`:`${seconds(r.timing?.controller_ms)} program`);
      time.append(node('small',`${seconds(r.timing?.api_ms)} total model wait`));const hold=adaptiveHold(r);if(hold)time.append(node('small',hold.brief));
      cell(tr,alive(r.alive_at_logout));publicationCell(tr,r);cell(tr).append(watch(r));$('comparison-rows').append(tr);
    }
    const axis=node('div',null,'chart-axis');for(let i=0;i<5;i++)axis.append(node('span',number(floor+span*i/4)));$('xp-chart').append(axis);
    $('group-context').textContent=group?`${groupLabel(group)}. ${group.ready?'Matching frozen inputs; live scene equality is unverified.':'A within-group comparison is not yet established.'}`:'No comparison group is available.';
  }
  function renderModels(){
    $('model-tabs').replaceChildren();
    for(const m of [...new Set(recordings.map(model))]){
      const row=recordings.find(r=>model(r)===m),b=node('button',null,'model-tab');b.type='button';b.append(dot(row),node('span',names[m]||m));b.setAttribute('aria-pressed',String(m===filterModel));
      b.addEventListener('click',()=>{filterModel=m;renderModels();renderRunOptions();const group=snapshot.comparisons.find(g=>g.id===$('comparison-select').value);selectRun(recordings.find(r=>model(r)===m&&group?.attempt_ids.includes(r.id))||recordings.find(r=>model(r)===m));});$('model-tabs').append(b);
    }
  }
  function renderRunOptions(){
    $('run-select').replaceChildren();
    for(const r of recordings.filter(r=>model(r)===filterModel)){
      const option=node('option',`${r.adaptive?.class_profile?.class_name||'Undeclared class'} · ${r.id.slice(0,8)} · ${xp(r.persisted_xp)} XP · ${status(r)}`);option.value=r.id;$('run-select').append(option);
    }
  }
  function selectRun(row){
    if(!row)return;
    const changed=selected?.id!==row.id||safeRecording(selected)!==safeRecording(row);
    selected=row;$('run-select').value=row.id;
    if(changed){runPlayer.pause();$('cue-button').disabled=true;$('full-button').disabled=true;runPlayer.src=safeRecording(row);$('player-status').textContent='Loading recording…';}
    $('run-model').textContent=name(row);$('run-dot').style.setProperty('--model-color',color(row));$('run-state').textContent=status(row);$('run-outcome').textContent=runOutcome(row);
    const metrics=[['Saved XP',xp(row.persisted_xp)],['Acknowledged inputs',number(row.acknowledged_actions)],['Total model wait',duration(row.timing?.api_ms)],[adaptiveRow(row)?'Wall budget used':'Program interval',duration(adaptiveRow(row)?row.adaptive?.wall_elapsed_ms:row.timing?.controller_ms)]];
    $('run-metrics').replaceChildren();for(const [label,value]of metrics){const d=node('div');d.append(node('dt',label),node('dd',value));$('run-metrics').append(d);}
    const p=publication(row);$('run-evidence').textContent=`${p.label}. ${p.detail?p.detail+'. ':''}${Number.isFinite(row.persisted_xp)?'Saved XP was verified by the runner.':'Diagnostic XP is not a verified score.'}`;
    $('run-id').textContent=row.id;$('run-attribution').textContent=`Requested: ${row.requested_model||'none'}. Returned: ${row.returned_model||'not recorded'}. ${row.attribution==='mismatch'?'Model attribution mismatch. ':''}${row.action_attempts!=null?`${row.action_attempts} attempted inputs; ${number(row.acknowledged_actions)} acknowledged.`:'Input receipts unavailable.'}`;
    const c=cue(row);$('cue-button').hidden=!c;$('cue-button').textContent=c?.basis==='first_acknowledged_input'?'First input':'Program start';
    $('cue-note').textContent=c?`Playback opens near ${c.basis==='first_acknowledged_input'?'the first acknowledged input':'program start; first-input timing was not recorded'}. Full recording retains the opening wait.`:'Showing the full recording. No verified playback cue is available.';
    if(adaptiveRow(row))$('cue-note').textContent+=` Every model wait counts within the ${wallBudget(row)/60000}-minute wall budget. Seeking changes playback only.`;
    const details=$('selected-evidence');details.replaceChildren();const hold=adaptiveHold(row);if(hold)details.append(node('p',hold.detail,'group-notice'));
    const adaptive=adaptiveDetails(row);if(adaptive)details.append(adaptive);const native=nativeDetails(row);if(native)details.append(native);
  }
  function openRun(row){
    filterModel=model(row);renderModels();renderRunOptions();selectRun(row);setPreviews(false);
    $('trajectories').scrollIntoView({behavior:reducedMotion.matches?'instant':'smooth'});runPlayer.focus({preventScroll:true});
  }
  function playAt(time){if(runPlayer.readyState<1)return;try{runPlayer.currentTime=time;runPlayer.play().catch(()=>{$('player-status').textContent='Use the video controls to play.';});}catch{$('player-status').textContent='Use the video controls to seek.';}}
  function renderRedesign(){
    const {generated_at_ms,...presentation}=snapshot;
    const identity=JSON.stringify(presentation);if(identity===presentationIdentity)return;presentationIdentity=identity;
    recordings=snapshot.attempts.filter(safeRecording);
    $('hero-models').textContent=new Set(snapshot.attempts.map(r=>r.requested_model).filter(Boolean)).size;
    $('hero-recordings').textContent=recordings.length;$('hero-attempts').textContent=snapshot.attempts.length;$('recording-count').textContent=`${recordings.length} recordings`;
    const previous=$('comparison-select').value;
    for(const id of ['comparison-select','showcase-select']){const select=$(id);select.replaceChildren();for(const g of snapshot.comparisons){const option=node('option',groupLabel(g));option.value=g.id;select.append(option);}}
    const group=snapshot.comparisons.find(g=>g.id===previous)||snapshot.comparisons.find(g=>g.attempt_ids.includes(snapshot.featured_run_id))||snapshot.comparisons[0];
    if(group){$('comparison-select').value=group.id;$('showcase-select').value=group.id;}
    renderMontage();renderComparison();
    const featured=recordings.find(r=>r.id===selected?.id)||recordings.find(r=>r.id===snapshot.featured_run_id)||recordings[0];
    if(featured){filterModel=model(featured);renderModels();renderRunOptions();selectRun(featured);}else{$('player-status').textContent='No recordings available.';}
    $('snapshot-date').textContent=`Saved ${new Date(snapshot.generated_at_ms).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})}`;
  }
  runPlayer.addEventListener('loadedmetadata',()=>{const start=(cue(selected)?.start_ms||0)/1000;if(start<runPlayer.duration)runPlayer.currentTime=start;$('player-status').textContent='Ready to play';$('cue-button').disabled=false;$('full-button').disabled=false;});
  runPlayer.addEventListener('playing',()=>{$('player-status').textContent='Playing recorded run';setPreviews(false);});
  runPlayer.addEventListener('pause',()=>{$('player-status').textContent=runPlayer.ended?'Recording finished':'Paused';});
  runPlayer.addEventListener('error',()=>{$('player-status').textContent='Recording unavailable. Choose another attempt.';$('cue-button').disabled=true;$('full-button').disabled=true;});
  $('cue-button').addEventListener('click',()=>playAt((cue(selected)?.start_ms||0)/1000));$('full-button').addEventListener('click',()=>playAt(0));
  $('montage-toggle').addEventListener('click',()=>setPreviews(!previewsPlaying));reducedMotion.addEventListener('change',e=>{if(e.matches)setPreviews(false);});
  for(const id of ['comparison-select','showcase-select'])$(id).addEventListener('change',()=>{$('comparison-select').value=$(id).value;$('showcase-select').value=$(id).value;renderComparison();renderMontage();});
  $('run-select').addEventListener('change',()=>selectRun(recordings.find(r=>r.id===$('run-select').value)));
  $('history-filter').addEventListener('change',renderHistory);
  document.addEventListener('visibilitychange',()=>{if(document.hidden){setPreviews(false);runPlayer.pause();}});
  const architectureTabs = [...document.querySelectorAll('[data-architecture]')];
  function showArchitecture(key, focus = false) {
    for (const tab of architectureTabs) {
      const active = tab.dataset.architecture === key;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      $(tab.getAttribute('aria-controls')).hidden = !active;
      if (active && focus) tab.focus();
    }
  }
  for (const tab of architectureTabs) {
    tab.addEventListener('click', () => showArchitecture(tab.dataset.architecture));
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const index = architectureTabs.indexOf(tab);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? architectureTabs.length - 1
        : (index + (event.key === 'ArrowRight' ? 1 : -1) + architectureTabs.length) % architectureTabs.length;
      showArchitecture(architectureTabs[next].dataset.architecture, true);
    });
  }
  const worldSteps = {
    see: { title: 'Game state, not a video feed.', description: 'The model receives the character’s position, HP, MP, XP, level, map, and nearby monster positions. Journey WASM supplies the client observations; the recordings are for people to inspect.', nodes: ['client','controller'] },
    think: { title: 'Observe, program, adapt.', description: 'The trusted controller sends the task, SDK instructions, and current state to OpenAI. The model returns a JavaScript program. Adaptive pilots repeat this cycle within a fixed wall budget. The game world continues running during inference.', nodes: ['provider','controller'] },
    act: { title: 'A plan becomes actual key presses.', description: 'The generated program runs in a bounded, networkless Node.js container. It calls observe(), pressKeys(), and wait() through the trusted controller. Journey handles movement and combat through the ordinary game connection.', nodes: ['sandbox','controller','client','proxy'] },
    save: { title: 'The score has to survive logout.', description: 'Cosmic saves character state in MySQL after ordinary logout. The runner compares persisted XP with the starting baseline, including penalties. Live client XP remains diagnostic; it is not the final score.', nodes: ['server','database','controller'] }
  };
  function showWorldStep(key) {
    const step = worldSteps[key];
    if (!step) return;
    for (const button of document.querySelectorAll('[data-world-step]')) button.setAttribute('aria-pressed', String(button.dataset.worldStep === key));
    for (const mapNode of document.querySelectorAll('.map-node')) mapNode.classList.toggle('is-highlighted', step.nodes.some(name => mapNode.classList.contains(name)));
    $('world-step-detail').replaceChildren(node('h3',step.title),node('p',step.description));
  }
  for (const button of document.querySelectorAll('[data-world-step]')) button.addEventListener('click', () => showWorldStep(button.dataset.worldStep));
  showWorldStep('see');

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
      snapshot=next;renderRedesign();renderCatalog();renderResearch();renderLive();renderComparisons();renderHistory();freshness();
      if(replay.open){const row=snapshot.attempts.find(item=>item.id===replayRunId);if(row)replayVerification(row);}
    }catch{$('connection').className='stale';$('connection').textContent=snapshot?'Results feed unavailable · showing saved snapshot':'Results feed unavailable';}
    finally{if(!closed&&(snapshot?.live_status_available!==false||[1,2].includes(snapshot?.catalog?.schema_version)))timer=setTimeout(refresh,[1,2].includes(snapshot?.catalog?.schema_version)?10000:2000);}
  }
  window.addEventListener('pagehide',()=>{closed=true;clearTimeout(timer);stopReplay();setPreviews(false);runPlayer.pause();});
  refresh();
})();
