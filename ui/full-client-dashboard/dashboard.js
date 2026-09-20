(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const sectionLinks = [...document.querySelectorAll('.site-nav a')];
  function markSection(id) {
    for (const link of sectionLinks) {
      if (link.getAttribute('href') === `#${id}`) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    }
  }
  const navSections = sectionLinks.map(link => document.querySelector(link.getAttribute('href'))).filter(Boolean);
  let sectionFramePending = false;
  function updateCurrentSection() {
    sectionFramePending = false;
    const readingLine = Math.max(document.querySelector('.site-header').getBoundingClientRect().bottom + 24, innerHeight / 2);
    let current = navSections[0];
    for (const section of navSections) {
      if (section.getBoundingClientRect().top <= readingLine) current = section;
    }
    if (scrollY + innerHeight >= document.documentElement.scrollHeight - 4) current = navSections.at(-1);
    if (current) markSection(current.id);
  }
  function scheduleSectionUpdate() {
    if (sectionFramePending) return;
    sectionFramePending = true;
    requestAnimationFrame(updateCurrentSection);
  }
  addEventListener('scroll', scheduleSectionUpdate, { passive: true });
  addEventListener('resize', scheduleSectionUpdate, { passive: true });
  addEventListener('load', scheduleSectionUpdate);
  document.addEventListener('toggle', scheduleSectionUpdate, true);
  scheduleSectionUpdate();
  const node = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
  const number = n => Number.isFinite(n) ? n.toLocaleString('en-US') : '—';
  const xp = n => Number.isFinite(n) ? `${n > 0 ? '+' : ''}${number(n)}` : '—';
  const duration = n => Number.isFinite(n) ? `${(n / 1000).toFixed(1)}s` : '—';
  const model = row => row.returned_model || row.requested_model || 'Script';
  const names = { 'gpt-6-astra':'GPT-6 Astra', 'gpt-5.6-terra':'GPT-5.6 Terra', 'gpt-5.6-sol':'GPT-5.6 Sol', 'gpt-5.6-luna':'GPT-5.6 Luna' };
  const name = row => names[model(row)] || model(row);
  const colors = { 'gpt-6-astra':'#609b8b', 'gpt-5.6-terra':'#a580b7', 'gpt-5.6-sol':'#d2a35b', 'gpt-5.6-luna':'#6f9bc6' };
  const color = row => colors[model(row)] || '#999';
  const status = row => ({completed:'Completed',recovered:'Recovered · invalid',failed:'Failed',interrupted:'Interrupted',running:'In progress',requesting:'Awaiting API'}[row.status] || 'Incomplete');
  let data, recordings = [], selected, filterModel, previewsPlaying = false;
  const player = $('run-video');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  function safeRecording(row) {
    try {
      const u = new URL(row.recording.url, location.href);
      if (u.origin !== location.origin || !['http:', 'https:'].includes(u.protocol) || u.username || u.password || u.search || u.hash
        || !/^\/(?:[A-Za-z0-9_-]+\/){0,3}recordings\/[A-Za-z0-9_./-]+\.(webm|mp4)$/.test(u.pathname)) return null;
      return u.href;
    } catch { return null; }
  }
  function cue(row) {
    const c = row.recording?.playback;
    return c && Number.isFinite(c.start_ms) && c.start_ms >= 0 && c.start_ms < 125000
      && ['program_start','first_acknowledged_input'].includes(c.basis) ? c : null;
  }
  function publication(row) {
    const e = row.publication_evidence;
    if (e?.status === 'passed') return ['Evidence checked','Input checks passed.'];
    if (e?.status === 'blocked') return ['Publication blocked', e.reason_code === 'receipts_incomplete' ? 'Publication blocked: incomplete input receipts.' : 'Publication checks failed.'];
    return ['Not evaluated','Publication evidence not evaluated.'];
  }
  function dot(row) { const d = node('span',null,'model-dot'); d.style.setProperty('--model-color',color(row)); return d; }
  function cell(tr, text, cls) { const c = node('td',text,cls); tr.append(c); return c; }
  /* Copy the column headings onto each cell so the phone stylesheet can stack
     rows into labelled cards instead of scrolling the table sideways. */
  function labelCells(tbody) {
    const heads = [...(tbody.closest('table')?.querySelectorAll('thead th') || [])].map(th => th.textContent.trim());
    for (const tr of tbody.rows) [...tr.cells].forEach((td,i) => { if (heads[i]) td.dataset.label = heads[i]; });
  }
  function watch(row) {
    if (!safeRecording(row)) return node('span','Not recorded','muted small');
    const b = node('button','Watch ↗','watch-button'); b.type = 'button'; b.setAttribute('aria-label',`Watch ${name(row)} attempt ${row.id.slice(0,8)}`);
    b.addEventListener('click', () => openRun(row)); return b;
  }
  function setPreviews(play) {
    previewsPlaying = play;
    for (const v of document.querySelectorAll('.montage video')) { if (play) v.play().catch(() => {}); else v.pause(); }
    $('montage-toggle').textContent = play ? 'Pause previews' : 'Play previews';
    $('montage-toggle').setAttribute('aria-pressed',String(play));
  }
  function renderMontage() {
    const complete = recordings.filter(r => r.status === 'completed');
    // Showcase recorded progress; captions identify each model and outcome.
    const featured = complete.find(r => r.id === data.featured_run_id) || complete[0];
    const picks = featured ? [featured] : [];
    const terra = complete.find(r => model(r) === 'gpt-5.6-terra');
    if (terra && !picks.includes(terra)) picks.push(terra);
    for (const r of complete.filter(r => r.persisted_xp > 0)) if (picks.length < 4 && !picks.includes(r)) picks.push(r);
    for (const r of complete) if (picks.length < 4 && !picks.includes(r)) picks.push(r);
    $('montage').replaceChildren();
    if (!picks.length) { $('montage').append(node('p','No recordings available.','loading')); $('montage-toggle').hidden = true; return; }
    if (picks.length === 1) $('montage').classList.add('single');
    for (const r of picks) {
      const tile = node('button',null,'montage-tile'); tile.type = 'button'; tile.setAttribute('aria-label',`Explore ${name(r)}, ${xp(r.persisted_xp)} saved XP`);
      tile.classList.add('is-loading');
      let previewStart = 0;
      const v = node('video'); v.muted = true; v.playsInline = true; v.preload = 'metadata'; v.tabIndex = -1; v.setAttribute('aria-hidden','true'); v.src = safeRecording(r);
      // Montage excerpts skip opening waits for an immediate view of gameplay.
      // The full player uses only verified cues and retains the entire recording.
      v.addEventListener('loadedmetadata', () => {
        const start = cue(r)?.start_ms / 1000 || (Number.isFinite(r.timing?.api_ms) ? r.timing.api_ms / 1000 + 2 : 0);
        if (start > 0 && start < v.duration) { previewStart = start; v.currentTime = start; }
        else tile.classList.remove('is-loading');
      });
      v.addEventListener('seeked', () => tile.classList.remove('is-loading'), {once:true});
      v.addEventListener('ended', () => { v.currentTime = previewStart; if (previewsPlaying) v.play().catch(() => {}); });
      v.addEventListener('error', () => { tile.classList.remove('is-loading');tile.classList.add('video-unavailable'); });
      const caption = node('span',null,'tile-caption'); caption.append(dot(r),node('span',name(r)),node('span',`${xp(r.persisted_xp)} saved XP`,'tile-score'));
      tile.append(v,caption,node('span','▶','tile-play')); tile.addEventListener('click',() => openRun(r)); $('montage').append(tile);
    }
    if (!reducedMotion.matches) setPreviews(true);
  }
  function planned(group) {
    // Prefer the declared denominator so retained failures stay visible.
    const model = group.sample?.requested_model;
    for (const row of data.research_matrix?.models ?? []) {
      if (row.model !== model) continue;
      const total = (row.cells ?? []).reduce((a, c) => a + (Number(c.planned) || 0), 0);
      if (total) return total;
    }
    return null;
  }
  function renderLeaderboard(rows) {
    const byModel = new Map();
    for (const r of rows) {
      const key = r.requested_model || name(r);
      if (!byModel.has(key)) byModel.set(key, {sample: r, scores: [], attempts: 0});
      const g = byModel.get(key); g.attempts++;
      if (Number.isFinite(r.persisted_xp)) g.scores.push(r.persisted_xp);
    }
    const stats = [...byModel.values()].map(g => {
      const s = [...g.scores].sort((a, b) => a - b), n = s.length;
      const mean = n ? s.reduce((a, b) => a + b, 0) / n : null;
      const median = n ? (n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2) : null;
      return {...g, n, mean, median, best: n ? s[n - 1] : null};
    }).sort((a, b) => (b.mean ?? -Infinity) - (a.mean ?? -Infinity));
    const body = $('leaderboard-rows'); body.replaceChildren();
    stats.forEach((g, i) => {
      const tr = node('tr');
      cell(tr, String(i + 1), 'rank');
      cell(tr).append(dot(g.sample), node('strong', name(g.sample)));
      cell(tr, `${g.n} / ${planned(g) ?? g.attempts}`);
      cell(tr, g.mean === null ? '\u2014' : xp(Math.round(g.mean)), 'score');
      cell(tr, g.median === null ? '\u2014' : xp(Math.round(g.median)));
      cell(tr, g.best === null ? '\u2014' : xp(g.best));
      body.append(tr);
    });
    labelCells(body);
    const scored = stats.reduce((a, g) => a + g.n, 0);
    $('leaderboard-note').textContent =
      `${scored} verified of ${stats.reduce((a, g) => a + (planned(g) ?? g.attempts), 0)} planned attempts \u00b7 ordered by mean saved XP. `
      + 'One fixture and a few repetitions per model: descriptive only, not a ranking claim.';
  }
  function renderComparison() {
    const group = data.comparisons.find(g => g.id === $('comparison-select').value);
    const rows = group ? data.attempts.filter(r => group.attempt_ids.includes(r.id)) : [];
    const max = Math.max(1,...rows.map(r => Number.isFinite(r.persisted_xp) ? Math.abs(r.persisted_xp) : 0));
    const ceiling = Math.max(1000,Math.ceil(max / 1000) * 1000);
    $('xp-chart').replaceChildren(); $('comparison-rows').replaceChildren();
    for (const r of rows) {
      const chart = node('div',null,`chart-row${r.persisted_xp === 0 ? ' zero' : ''}`); chart.style.setProperty('--model-color',color(r));
      const label = node('span',null,'chart-model'); label.append(dot(r),node('span',name(r)));
      const track = node('div',null,'chart-track'), bar = node('div',null,'chart-bar');
      bar.style.width = `${Number.isFinite(r.persisted_xp) ? Math.abs(r.persisted_xp) / ceiling * 100 : 0}%`;
      if (!Number.isFinite(r.persisted_xp)) bar.hidden = true;
      track.append(bar); chart.append(label,track,node('span',xp(r.persisted_xp),'chart-value')); $('xp-chart').append(chart);
      const tr = node('tr'), identity = cell(tr); identity.append(dot(r),node('strong',name(r)),node('small',r.id.slice(0,12)));
      cell(tr,xp(r.persisted_xp),'score');
      const inputs = cell(tr,number(r.acknowledged_actions));
      if (r.no_op) inputs.append(node('small','No input actions'));
      else if (r.action_verification !== 'receipts_rechecked') inputs.append(node('small','Incomplete receipts'));
      cell(tr,duration(r.timing?.controller_ms)); cell(tr,r.alive_at_logout === true ? 'Alive' : r.alive_at_logout === false ? 'Dead' : '—');
      const p = publication(r); cell(tr,p[0],`evidence${r.publication_evidence?.status === 'blocked' ? ' blocked' : ''}`);
      cell(tr).append(watch(r)); $('comparison-rows').append(tr);
    }
    labelCells($('comparison-rows'));
    const axis = node('div',null,'chart-axis'); for (let i=0;i<5;i++) axis.append(node('span',number(ceiling*i/4))); $('xp-chart').append(axis);
    renderLeaderboard(rows);
    $('group-context').textContent = rows.length > 1 ? `${rows.length} attempts · shared frozen inputs; live scenes may differ.` : 'One attempt; no model comparison.';
  }
  function renderModels() {
    $('model-tabs').replaceChildren();
    for (const m of [...new Set(recordings.map(model))]) {
      const row = recordings.find(r => model(r) === m), b = node('button',null,'model-tab'); b.type = 'button';
      b.append(dot(row),node('span',names[m] || m)); b.setAttribute('aria-pressed',String(m === filterModel));
      b.addEventListener('click', () => { filterModel = m; renderModels(); renderRunOptions(); selectRun(recordings.find(r => model(r) === m)); }); $('model-tabs').append(b);
    }
  }
  function renderRunOptions() {
    $('run-select').replaceChildren();
    for (const r of recordings.filter(r => model(r) === filterModel)) {
      const option = node('option',`${r.id.slice(0,8)} · ${xp(r.persisted_xp)} XP · ${status(r)}`); option.value = r.id; $('run-select').append(option);
    }
  }
  function selectRun(row) {
    if (!row) return;
    selected = row; $('run-select').value = row.id; player.pause();
    $('cue-button').disabled = true; $('full-button').disabled = true; player.src = safeRecording(row);
    $('player-status').textContent = 'Loading recording…';
    $('run-model').textContent = name(row); $('run-dot').style.setProperty('--model-color',color(row)); $('run-state').textContent = status(row);
    $('run-outcome').textContent = row.status !== 'completed' ? 'No verified score.' : row.no_op ? 'No inputs or XP gained.' : row.persisted_xp > 0 ? 'XP gain saved after logout.' : 'Inputs executed; no net XP gain.';
    const metrics = [['Saved XP',xp(row.persisted_xp)],['Inputs',number(row.acknowledged_actions)],['API wait',duration(row.timing?.api_ms)],['Play time',duration(row.timing?.controller_ms)]];
    $('run-metrics').replaceChildren(); for (const [label,value] of metrics) { const d=node('div');d.append(node('dt',label),node('dd',value));$('run-metrics').append(d); }
    const p=publication(row); $('run-evidence').textContent = `${p[1]} ${Number.isFinite(row.persisted_xp) ? 'Score verified separately.' : 'Score unverified.'}`;
    $('run-id').textContent = row.id;
    $('run-attribution').textContent = `Requested: ${row.requested_model || 'none'}. Returned: ${row.returned_model || 'not recorded'}. ${row.action_attempts != null ? `${row.action_attempts} attempted inputs; ${number(row.acknowledged_actions)} acknowledged.` : 'Input receipts unavailable.'}`;
    const c=cue(row); $('cue-button').hidden = !c; $('cue-button').textContent = c?.basis === 'first_acknowledged_input' ? 'First input' : 'Program start';
    $('cue-note').textContent = c ? c.basis === 'program_start' ? 'Starts near program start; first-input timing unknown. Full recording includes the model wait.' : 'Starts near first acknowledged input. Full recording includes the model wait.' : 'Full recording; no verified start cue.';
  }
  function openRun(row) {
    filterModel = model(row); renderModels(); renderRunOptions(); selectRun(row); setPreviews(false);
    $('trajectories').scrollIntoView({behavior:reducedMotion.matches ? 'instant' : 'smooth'});
    player.focus({preventScroll:true});
  }
  function renderHistory() {
    $('history-rows').replaceChildren();
    const filter=$('history-filter').value;
    for (const r of data.attempts.filter(r => filter==='all' || (filter==='completed' ? r.status==='completed' : r.status!=='completed'))) {
      const tr=node('tr'), identity=cell(tr); identity.append(node('strong',name(r)),node('small',r.id));
      const state=cell(tr,status(r));if(r.failure_code)state.append(node('small',r.failure_code.replaceAll('_',' ')));
      cell(tr,xp(r.persisted_xp));cell(tr,xp(r.diagnostic_xp));
      const inputs=cell(tr,`${number(r.acknowledged_actions)} acknowledged`); if(r.reported_actions!=null&&r.acknowledged_actions==null)inputs.append(node('small',`${r.reported_actions} reported; unverified`));
      cell(tr,publication(r)[0]);cell(tr).append(watch(r));$('history-rows').append(tr);
    }
    labelCells($('history-rows'));
  }
  player.addEventListener('loadedmetadata', () => { const start=cue(selected)?.start_ms/1000||0;if(start<player.duration)player.currentTime=start;$('player-status').textContent='Ready';$('cue-button').disabled=false;$('full-button').disabled=false; });
  player.addEventListener('playing',()=>{$('player-status').textContent='Playing';setPreviews(false);});
  player.addEventListener('pause',()=>{$('player-status').textContent=player.ended?'Recording finished':'Paused';});
  player.addEventListener('error',()=>{$('player-status').textContent='Recording unavailable. Choose another attempt.';$('cue-button').disabled=true;$('full-button').disabled=true;});
  function playAt(time) { if(player.readyState<1)return;try{player.currentTime=time;player.play().catch(()=>{$('player-status').textContent='Use the video controls to play.';});}catch{$('player-status').textContent='Use the video controls to seek.';} }
  $('cue-button').addEventListener('click',()=>playAt((cue(selected)?.start_ms||0)/1000));
  $('full-button').addEventListener('click',()=>playAt(0));
  $('montage-toggle').addEventListener('click',()=>setPreviews(!previewsPlaying));
  reducedMotion.addEventListener('change',e=>{if(e.matches)setPreviews(false);});
  $('comparison-select').addEventListener('change',renderComparison);
  $('run-select').addEventListener('change',()=>selectRun(recordings.find(r=>r.id===$('run-select').value)));
  $('history-filter').addEventListener('change',renderHistory);
  document.addEventListener('visibilitychange',()=>{if(document.hidden){setPreviews(false);player.pause();}});
  window.addEventListener('pagehide',()=>{setPreviews(false);player.pause();});
  const labDetails = $('lab-details');
  function revealLab() {
    if (location.hash === '#approach') labDetails.open = true;
  }
  document.querySelector('.site-nav a[href="#approach"]').addEventListener('click', () => { labDetails.open = true; });
  addEventListener('hashchange', revealLab);
  revealLab();
  async function init() {
    try {
      const response=await fetch('./results.json',{signal:AbortSignal.timeout(5000)});if(!response.ok)throw Error('unavailable');
      data=await response.json();if(data.schema_version!==1||!Array.isArray(data.attempts)||!Array.isArray(data.comparisons))throw Error('invalid');
      recordings=data.attempts.filter(safeRecording);
      const modelCount = new Set(data.attempts.map(model)).size;
      $('hero-models').textContent = `${modelCount} ${modelCount === 1 ? 'model' : 'models'}`;
      $('hero-recordings').textContent = `${recordings.length} ${recordings.length === 1 ? 'recording' : 'recordings'}`;
      $('hero-attempts').textContent = `${data.attempts.length} ${data.attempts.length === 1 ? 'attempt' : 'attempts'}`;
      $('recording-count').textContent=$('hero-recordings').textContent;$('attempt-count').textContent=`(${data.attempts.length})`;
      const selectedOnly=location.pathname.includes('/latest/');
      if(selectedOnly){$('hero-attempts').textContent='1 selected attempt';$('snapshot-scope').textContent='Selected run · full history under All results';}
      renderMontage();
      data.comparisons.forEach((g,i)=>{const option=node('option',`${g.models.length>1?`${g.models.length} models`:`${i===0?'Latest':'Earlier'} run`} · ${g.id.slice(0,8)}`);option.value=g.id;$('comparison-select').append(option);});
      const comparison=data.comparisons.find(g=>g.models.length>1)||data.comparisons[0];if(comparison)$('comparison-select').value=comparison.id;
      renderComparison();
      const featured=recordings.find(r=>r.id===data.featured_run_id)||recordings.find(r=>r.status==='completed')||recordings[0];
      if(featured){filterModel=model(featured);renderModels();renderRunOptions();selectRun(featured);}else{$('player-status').textContent='No recordings available.';}
      renderHistory();
      $('snapshot-date').textContent=`Updated ${new Date(data.generated_at_ms).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})}`;
    } catch {
      $('load-status').textContent='The result data could not be loaded. Reload this page to try again.';
      $('montage').replaceChildren(node('p','Recordings unavailable','loading'));
      $('montage-toggle').disabled=true;
    }
  }
  /* On a phone every section after the hero starts collapsed, so the headings
     act as the table of contents that the removed nav bar used to provide.
     Wider screens keep everything open; the markup ships open so the page is
     still complete without JavaScript. Only re-apply when the breakpoint is
     actually crossed, otherwise a resize would undo what someone just opened. */
  const phone = matchMedia('(max-width: 560px)');
  function syncCollapsedSections() {
    for (const d of document.querySelectorAll('details.section-collapse')) d.open = !phone.matches;
  }
  phone.addEventListener('change', syncCollapsedSections);
  syncCollapsedSections();

  init();
})();
