import { createPostRenderRecorder } from './webcodecs-recorder.js';
// Live controls and honest canvas capture for the unscored full-client adapter.
(() => {
  fetch('/demo-session').then(r => { if (!r.ok) throw Error(); return r.json(); })
    .then(session => { Module.MapleBenchSession = session; }).catch(() => {});
  const game = document.getElementById('canvas');
  if (!game) return;
  const ink = {base:'#10120f',panel:'#191d17',line:'#38432e',text:'#eef3dc',muted:'#a8b29b',
    green:'#c3f45b',violet:'#b59af4',orange:'#ff9956',danger:'#ff776b'};
  const leafPath = 'M12 1 15 7 20 5 18 11 23 13 15 18 13 17 13 23 11 23 11 17 9 18 1 13 6 11 4 5 9 7Z';
  const style = document.createElement('style');
  style.textContent = `
    #maplebench-shell{--mb-signal:${ink.green};position:fixed;inset:0;z-index:10;display:flex;flex-direction:column;background:${ink.base};color:${ink.text};font:12px system-ui,sans-serif;text-align:left;color-scheme:dark}
    #maplebench-shell *{box-sizing:border-box}
    #maplebench-shell header{flex:none;position:relative;padding:8px 12px 7px;border-top:3px solid #66528b;border-bottom:1px solid ${ink.line};display:grid;gap:4px;background:linear-gradient(105deg,#22202c 0%,${ink.base} 65%)}
    #maplebench-shell header::after{content:'';position:absolute;bottom:-1px;left:0;width:72px;height:2px;background:var(--mb-signal)}
    #maplebench-shell .mb-title{display:flex;align-items:center;justify-content:space-between;gap:8px;min-width:0}
    #maplebench-shell .mb-brand{display:flex;align-items:center;gap:7px;min-width:0}
    #maplebench-shell .mb-leaf{width:20px;height:22px;flex:none;fill:${ink.orange}}
    #maplebench-shell .mb-wordmark{font:900 20px/1 'Arial Narrow',Impact,sans-serif;letter-spacing:-.04em}
    #maplebench-shell .mb-wordmark b{color:${ink.green};font-weight:inherit}
    #maplebench-shell .mb-engine{font:9px/1.2 ui-monospace,monospace;letter-spacing:.06em;color:${ink.muted};border-left:1px solid #5e5074;padding-left:9px;margin-left:3px}
    #maplebench-shell .mb-capture{flex:none;min-width:55px;text-align:center;font:700 10px/1.2 ui-monospace,monospace;letter-spacing:.06em;color:${ink.green};border:1px solid ${ink.line};padding:4px 7px;clip-path:polygon(0 0,calc(100% - 5px) 0,100% 5px,100% 100%,0 100%)}
    #maplebench-shell .mb-capture[data-recording=true]{color:${ink.orange};border-color:#965830;background:#2e2118}
    #maplebench-shell .mb-controller{border-left:3px solid var(--mb-signal);padding-left:7px;font-weight:750;font-size:15px;line-height:1.2;overflow-wrap:anywhere}
    #maplebench-shell .mb-status{color:${ink.muted};font-size:10px;line-height:1.3;overflow-wrap:anywhere}
    #maplebench-shell[data-alert=true]{--mb-signal:${ink.orange}}
    #maplebench-shell[data-alert=true] .mb-status{color:${ink.orange}}
    #maplebench-shell .mb-telemetry{display:grid;grid-template-columns:1fr 1fr;gap:12px;font:11px/1.3 ui-monospace,monospace;font-variant-numeric:tabular-nums}
    #maplebench-shell .mb-vital{min-width:0;color:${ink.green}}
    #maplebench-shell .mb-vital-mp{color:${ink.violet}}
    #maplebench-shell .mb-meter{height:4px;margin-top:3px;background:#30372a;overflow:hidden}
    #maplebench-shell .mb-meter-fill{width:0;height:100%;background:repeating-linear-gradient(90deg,currentColor 0 8px,transparent 8px 10px)}
    #maplebench-shell .mb-readout{display:flex;flex-wrap:wrap;justify-content:space-between;gap:2px 12px;font:10px/1.3 ui-monospace,monospace;color:#d2dbc3}
    #maplebench-shell .mb-note{color:${ink.muted};font-size:9px;line-height:1.2;letter-spacing:.04em}
    #maplebench-shell .mb-note strong{font-weight:700;color:${ink.orange}}
    #maplebench-shell .mb-stage{flex:1;min-height:0;min-width:0;display:flex;align-items:center;justify-content:center;overflow:hidden;background:#070906;border-inline:1px solid #262d21}
    #maplebench-shell canvas{display:block!important;position:static!important;margin:0!important;border:0!important;flex:none;max-width:none!important;max-height:none!important;width:var(--mb-canvas-width)!important;height:var(--mb-canvas-height)!important}
    #maplebench-shell footer{flex:none;background:${ink.panel};border-top:1px solid ${ink.line};border-left:3px solid #66528b;padding:6px 10px;max-height:45%;overflow:auto}
    #maplebench-shell .mb-tools{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
    #maplebench-shell details{flex:1;min-width:150px}
    #maplebench-shell details[open]{flex-basis:100%}
    #maplebench-shell .mb-tools:has(details[open]){justify-content:flex-end}
    #maplebench-shell summary{cursor:pointer;padding:5px 0;color:${ink.green};font-size:11px;font-weight:650}
    #maplebench-shell summary::marker{color:${ink.orange}}
    #maplebench-shell .mb-controls{display:flex;flex-wrap:wrap;gap:5px;padding:5px 0}
    #maplebench-shell .mb-models{border-top:1px solid ${ink.line};margin-top:4px;padding-top:8px}
    #maplebench-shell button{border:1px solid #515c44;border-radius:0;background:#252c20;color:${ink.text};padding:6px 8px;font:600 11px/1.2 system-ui,sans-serif;cursor:pointer;white-space:nowrap}
    #maplebench-shell .mb-models button{border-color:#6f5c94;background:#292333;color:#e0d4ff}
    #maplebench-shell button.mb-record{border-color:#946037;color:${ink.orange};background:#30251c}
    #maplebench-shell button:hover:not(:disabled){border-color:${ink.green};background:#354129;color:${ink.text}}
    #maplebench-shell button:disabled{opacity:.4;cursor:default}
    #maplebench-shell button:focus-visible,#maplebench-shell summary:focus-visible{outline:2px solid ${ink.green};outline-offset:2px}
    #maplebench-shell .mb-notice{color:${ink.muted};font-size:10px;margin-top:4px;overflow-wrap:anywhere}
    #maplebench-shell .mb-notice:empty{display:none}
    @media(max-width:480px){#maplebench-shell .mb-engine{display:none}}
    @media(max-width:340px){#maplebench-shell header{padding-inline:8px}#maplebench-shell .mb-telemetry{font-size:10px;gap:8px}#maplebench-shell .mb-controller{font-size:13px}}
  `;
  document.head.appendChild(style);
  const element = (tag, className, parent, text = '') => {
    const node = document.createElement(tag); node.className = className; node.textContent = text;
    parent.appendChild(node); return node;
  };
  const shell = element('section', '', document.body); shell.id = 'maplebench-shell';
  shell.setAttribute('aria-label', 'MapleBench full-client controls');
  const header = element('header', '', shell);
  const title = element('div', 'mb-title', header);
  const brand = element('div', 'mb-brand', title);
  const leaf = document.createElementNS('http://www.w3.org/2000/svg','svg');
  leaf.setAttribute('class','mb-leaf'); leaf.setAttribute('viewBox','0 0 24 24'); leaf.setAttribute('aria-hidden','true');
  const leafShape = document.createElementNS('http://www.w3.org/2000/svg','path');
  leafShape.setAttribute('d',leafPath); leaf.appendChild(leafShape); brand.appendChild(leaf);
  const wordmark = element('span', 'mb-wordmark', brand, 'MAPLE');
  element('b', '', wordmark, 'BENCH');
  element('span', 'mb-engine', brand, 'JOURNEY × COSMIC');
  const captureStatus = element('span', 'mb-capture', title, 'WAITING');
  const controller = element('div', 'mb-controller', header);
  const status = element('div', 'mb-status', header);
  const telemetry = element('div', 'mb-telemetry', header);
  const hpVital = element('div', 'mb-vital', telemetry), mpVital = element('div', 'mb-vital mb-vital-mp', telemetry);
  const hpText = element('span', '', hpVital), mpText = element('span', '', mpVital);
  const hpFill = element('div','mb-meter-fill',element('div','mb-meter',hpVital));
  const mpFill = element('div','mb-meter-fill',element('div','mb-meter',mpVital));
  hpFill.parentNode.setAttribute('aria-hidden','true'); mpFill.parentNode.setAttribute('aria-hidden','true');
  const readout = element('div','mb-readout',header);
  const xpText = element('span', '', readout), keysText = element('span', '', readout);
  const note = element('div', 'mb-note', header);
  element('strong','',note,'UNRANKED'); element('span','',note,' / Client telemetry · no server score');
  const stage = element('div', 'mb-stage', shell); stage.appendChild(game);
  const footer = element('footer', '', shell);
  const tools = element('div', 'mb-tools', footer);
  const details = element('details', '', tools);
  element('summary', '', details, 'Controls & models');
  const manualGroup = element('div', 'mb-controls', details);
  const modelGroup = element('div', 'mb-controls mb-models', details);
  element('div', 'mb-notice', details, 'Start a 22-second model run or the 60-second Astra demo. Each makes one API request and stops automatically.');
  const notice = element('div', 'mb-notice', footer); notice.setAttribute('role', 'status');
  const resize = () => {
    const scale = Math.min(stage.clientWidth / game.width, stage.clientHeight / game.height);
    if (Number.isFinite(scale) && scale > 0) {
      // The upstream resize handler replaces the canvas's inline style. Keep the
      // fitted dimensions on its parent so stylesheet !important rules win.
      stage.style.setProperty('--mb-canvas-width', `${Math.floor(game.width * scale)}px`);
      stage.style.setProperty('--mb-canvas-height', `${Math.floor(game.height * scale)}px`);
    }
  };
  new ResizeObserver(resize).observe(stage);
  new MutationObserver(resize).observe(game, {attributes:true, attributeFilter:['width','height']});

  const keyNames = {LEFT:'ArrowLeft',RIGHT:'ArrowRight',UP:'ArrowUp',DOWN:'ArrowDown',JUMP:'Space',
    ATTACK:'ControlLeft',BRANDISH:'KeyA',COMBO:'KeyS',BOOSTER:'KeyD',MAPLE_WARRIOR:'KeyF',HP_POTION:'KeyQ',MP_POTION:'KeyW'};
  const skillKeyNames={PRIMARY_SKILL:'KeyA',SECONDARY_SKILL:'KeyS',BUFF_1:'KeyD',BUFF_2:'KeyF'};
  const skillNamesByCode=Object.fromEntries(Object.entries(skillKeyNames).map(([name,code])=>[code,name]));
  const namesByCode = Object.fromEntries(Object.entries(keyNames).map(([name, code]) => [code, name]));
  const codes = {ArrowLeft:37,ArrowRight:39,ArrowUp:38,ArrowDown:40,ControlLeft:17,Space:32,KeyA:65,KeyS:83,KeyD:68,KeyF:70,KeyQ:81,KeyW:87};
  const held = new Map(), physical = new Set(), manualButtons = [], runButtons = [];
  const cancelledRuns = new Set();
  let run = {status:'idle',mode:'manual',model:null}, baseline = null, baselineScope = 'session';
  let starting = false, relayConnected = false, disconnectedAt = null, closed = false;
  let acknowledgement = null, activeCommand = null, lastRunId = null, recordedRunId = null, releaseAck = null;
  let captureFailure = null;
  let capture = null, saving = false, pendingUpload = null, pollTimer, pollAbort;
  const activeRun = () => ['requesting','running'].includes(run.status) || run.workerActive === true || run.leaseReleasePending === true;
  const busy = () => starting || activeRun() || Boolean(activeCommand);
  const observe = () => Module.MapleBenchObservation || {ready:false};
  const fresh = observation => observation.ready && Number.isFinite(observation.capturedAt)
    && Date.now() - observation.capturedAt >= 0 && Date.now() - observation.capturedAt < 1500
    && Number.isFinite(Module.MapleBenchRenderedAt) && Date.now()-Module.MapleBenchRenderedAt < 1500;
  const setBaseline = scope => {
    const observation = observe(); baselineScope = scope;
    baseline = fresh(observation) ? {exp:observation.character.exp,level:observation.character.level} : null;
  };
  const key = (code, type) => window.dispatchEvent(new KeyboardEvent(type, {
    key:code.startsWith('Key') ? code.slice(3).toLowerCase() : code === 'Space' ? ' ' : code === 'ControlLeft' ? 'Control' : code,
    code,keyCode:codes[code],which:codes[code],bubbles:true,cancelable:true
  }));
  const release = code => { clearTimeout(held.get(code)); held.delete(code); key(code,'keyup'); };
  const releaseAll = (interrupted,reason='interrupted_unknown') => {
    if (interrupted && activeCommand) { activeCommand.interrupted = true; activeCommand.failure ??= reason; }
    [...new Set([...held.keys(), ...physical])].forEach(release); physical.clear();
  };
  const manualMode = () => { if (baselineScope !== 'session') setBaseline('session'); };
  const hold = (code, ms=180) => {
    if (busy()) return;
    manualMode(); game.focus(); release(code); key(code,'keydown');
    held.set(code,setTimeout(() => release(code),ms)); renderHeader();
  };
  const button = (text, action, parent, collection) => {
    const node = element('button', '', parent, text); node.type = 'button';
    node.addEventListener('click', action); collection?.push(node); return node;
  };
  for (const [text, code, ms] of [['← 1s','ArrowLeft',1000],['→ 1s','ArrowRight',1000],['Jump','Space',180],
    ['Brandish','KeyA',500],['Combo','KeyS',180],['Booster','KeyD',180],['Maple Warrior','KeyF',180],
    ['HP potion','KeyQ',180],['MP potion','KeyW',180]]) button(text, () => hold(code,ms), manualGroup,manualButtons);
  button('Release keys', () => releaseAll(true,'interrupted_operator'), manualGroup);
  for (const type of ['keydown','keyup']) window.addEventListener(type, event => {
    if (!event.isTrusted || !namesByCode[event.code]) return;
    // Preserve keyboard activation of toolbar controls without forwarding their
    // Space/arrows to the game's window-level keyboard listener.
    if (event.target !== game && /^(BUTTON|SUMMARY|INPUT|SELECT|TEXTAREA)$/.test(event.target?.tagName)) {
      event.stopImmediatePropagation(); return;
    }
    if (busy()) { event.preventDefault(); event.stopImmediatePropagation(); return; }
    manualMode();
    if (type === 'keydown') physical.add(event.code); else physical.delete(event.code);
    renderHeader();
  }, true);
  window.addEventListener('blur', () => { releaseAll(true,'interrupted_window_blur'); renderHeader(); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { releaseAll(true,'interrupted_hidden'); if(capture) capture.hidden=true; if (capture?.autoRunId) stopRecording(); }
  });

  const format = value => Number.isFinite(value) ? value.toLocaleString('en-US') : '—';
  const fraction = (value, max) => Number.isFinite(value) && Number.isFinite(max) && max > 0
    ? Math.min(1,Math.max(0,value/max)) : 0;
  const view = () => {
    const observation = observe(), available = fresh(observation), character = observation.character || {};
    if (!baseline && available) setBaseline(activeRun() ? 'run' : 'session');
    const model = run.mode === 'api' ? (run.model || 'model unavailable') : null;
    const mode = activeRun() ? (run.mode === 'api' ? `OpenAI API · ${model}` : run.nativeAcceptance ? `Native acceptance · ${run.nativeAcceptance.profile.class_name} · no model` : 'Scripted SDK · no evaluated model')
      : held.size || physical.size ? 'Manual controls · no active model' : 'Idle · no active model';
    let state = !relayConnected ? 'Relay disconnected · inputs released'
      : !available ? 'Waiting for fresh client state'
      : run.status === 'running' && run.adaptivePhase === 'waiting_for_deadline' ? `Waiting for deadline · game remains live · ${run.actions || 0} actions${run.adaptiveStartedAtMs ? ` · ${Math.max(0, Math.floor((Date.now()-run.adaptiveStartedAtMs)/1000))} / 300s` : ''}`
      : run.status === 'requesting' ? (run.adaptiveProtocol ? `Planning cycle ${(run.cycleNumber || 0)+1} · game remains live` : run.mode === 'api' ? 'Awaiting API program · game remains live' : 'Preparing SDK program')
      : run.status === 'running' ? `Program running · ${run.actions || 0} actions${run.programStartedAtMs ? ` · ${Math.max(0, Math.floor((Date.now()-run.programStartedAtMs)/1000))} / ${run.programSeconds || 22}s` : ''}`
      : run.id ? `Last ${model || 'scripted SDK'} run: ${run.status}${run.actions != null ? ` · ${run.actions} actions` : ''}${run.reason ? ` · ${run.reason}` : ''}`
      : 'Ready · open Controls & models to start one short run';
    if (available && character.alive === false) state += ' · CHARACTER DEAD';
    const delta = available && baseline && character.level === baseline.level
      && Number.isFinite(character.exp) && Number.isFinite(baseline.exp) ? character.exp - baseline.exp : null;
    const xp = delta === null ? (available && baseline && character.level !== baseline.level ? 'XP Δ unavailable (level changed)' : 'XP Δ —')
      : `XP Δ ${delta >= 0 ? '+' : ''}${format(delta)} (${baselineScope})`;
    const skillProfile = run.adaptiveProtocol?.profile || run.nativeAcceptance?.profile;
    const keys = [...new Set([...held.keys(),...physical])].map(code => {const key=(skillProfile?skillNamesByCode[code]:null)||namesByCode[code]||code; return skillProfile?.skill_keys?.[key]||key;}).join(' + ') || 'none';
    return {mode,state,hp:`HP ${available ? format(character.hp)+' / '+format(character.maxHp) : '—'}`,
      mp:`MP ${available ? format(character.mp)+' / '+format(character.maxMp) : '—'}`,xp,keys:`Keys: ${keys}`,
      hpFraction:available ? fraction(character.hp,character.maxHp) : 0,
      mpFraction:available ? fraction(character.mp,character.maxMp) : 0,
      stale:!available, alive:character.alive, level:character.level};
  };
  function renderHeader() {
    const data = view(); controller.textContent = data.mode; status.textContent = data.state;
    hpText.textContent = data.hp; mpText.textContent = data.mp; xpText.textContent = data.xp; keysText.textContent = data.keys;
    shell.dataset.alert = String(data.stale || !relayConnected || data.alive === false);
    hpVital.style.color = data.alive === false ? ink.danger : ink.green;
    hpFill.style.width = `${data.hpFraction*100}%`; mpFill.style.width = `${data.mpFraction*100}%`;
    captureStatus.dataset.recording = String(Boolean(capture) || saving);
    captureStatus.textContent = capture ? `● REC ${((performance.now()-capture.startedAt)/1000).toFixed(1)}s`
      : saving ? 'SAVING' : !relayConnected || data.stale ? 'WAITING'
      : activeRun() ? 'RUNNING' : held.size || physical.size ? 'MANUAL' : 'IDLE';
    manualButtons.forEach(node => { node.disabled = busy(); });
    runButtons.forEach(node => { node.disabled = busy() || !relayConnected || !fresh(observe()) || saving || Boolean(pendingUpload) || Boolean(capture); });
    recordButton.disabled = Boolean(capture) || saving || Boolean(pendingUpload); stopButton.disabled = !capture || capture.stopping;
    retryButton.disabled = !pendingUpload || saving;
  }
  async function uploadRecording() {
    if (!pendingUpload || saving) return;
    const item = pendingUpload;
    saving = true; renderHeader();
    try {
      const response = await fetch('/demo-recording', {method:'POST',
        headers:{'Content-Type':'video/webm','X-MapleBench-Client':clientId,
          ...(item.runId ? {'X-MapleBench-Run':item.runId,'X-MapleBench-Capture':btoa(JSON.stringify(item.metadata))} : {})},
        body:item.blob, signal:AbortSignal.timeout(65000)});
      if (!response.ok) throw Error('Upload rejected');
      const receipt = await response.json();
      if (receipt.status !== 'saved' || receipt.runId !== item.runId) throw Error('Upload receipt mismatch');
      pendingUpload = null;
      notice.textContent = item.runId ? `Saved recording for run ${item.runId}.` : 'Saved full-client-demo.webm on the runner.';
    } catch { notice.textContent = 'Recording upload failed. Use Retry save before starting another run.'; }
    finally { saving = false; renderHeader(); }
  }
  const fitText = (ctx, text, x, y, width) => {
    let value = String(text);
    while (value.length && ctx.measureText(value).width > width) value = value.slice(0,-1);
    ctx.fillText(value === text ? value : value.slice(0,-1)+'…', x,y);
  };
  const captureFailureCodes = new Set(["capture_clock_or_duration","capture_wall_clock_drift","capture_frame_limit","capture_dimensions_changed","capture_snapshot_failed","capture_first_frame_timeout","capture_final_frame_timeout","capture_owner_changed","capture_interrupted","capture_frame_gap","duplicate_quantized_timestamp","invalid_frame_duration","encoder_backpressure","encoder_output_timing_mismatch","encoder_output_type","encoder_missing_requested_keyframe","capture_byte_limit","encoder_hash_backpressure","encoder_configuration_changed","vp8_hidden_or_mistyped_frame","vp8_keyframe_dimensions","encoded_hash_failed","encoder_stop_timeout","capture_already_stopping","incomplete_capture","capture_endpoint_gap","capture_quantized_endpoint_gap","encoder_flush_timeout","encoder_frame_count_mismatch","ledger_too_large","encoder_error","capture_duration_limit","encoder_configuration_timeout","vp8_configuration_unsupported","webcodecs_unavailable","invalid_canvas","invalid_capture_limit","capture_not_active","capture_already_initialized","render_hook_failed","encoder_initialization_failed","encoder_stop_failed","encoder_failure_unknown"]);
  const retainCaptureFailure = (item, code) => {
    if(!item?.encodedMode || item.autoRunId!==run.id || !/^[a-f0-9]{32}$/.test(item.autoRunId) || captureFailure?.run_id===item.autoRunId) return;
    const recorder=item.encodedRecorder, start=recorder?.startedAt ?? item.startedAt;
    const offset=at=>Number.isFinite(at)&&Number.isFinite(start)?Math.max(0,Math.min(350000,Math.round(at-start))):null;
    const count=value=>Number.isSafeInteger(value)&&value>=0&&value<=(item.durationPolicy?.max_frames||20000)?value:0;
    captureFailure={schema_version:1,run_id:item.autoRunId,policy_id:item.durationPolicy?.id||'post-render-encoded-frame-v1',
      code:captureFailureCodes.has(code)?code:'encoder_failure_unknown',
      clock_origin:Number.isFinite(recorder?.startedAt)?'encoder_start':'capture_request',elapsed_ms:offset(performance.now()) ?? 0,
      first_frame_offset_ms:offset(recorder?.firstFrameAt),last_frame_offset_ms:offset(recorder?.lastFrameAt),
      rendered_frames:count(recorder?.frames),submitted_frames:count(recorder?.submittedFrames),encoded_frames:count(recorder?.outputFrames)};
  };
  async function startRecording(autoRunId = null) {
    if (capture) return;
    if (saving || pendingUpload || closed) return;
    const output = document.createElement('canvas'), headerHeight = 120;
    output.width = game.width; output.height = game.height + headerHeight;
    const ctx = output.getContext('2d');
    const durationPolicy=run.nativeAcceptance?.capture_duration_policy || run.adaptiveProtocol?.capture_duration_policy;
    const item = {autoRunId,startedAt:performance.now(),startedWall:Date.now(),recorderStarted:false,
      frames:0,firstFrameWall:null,lastFrameWall:null,firstFrameAt:null,lastFrameAt:null,maxGap:0,hidden:document.hidden,
      errors:0,relayLost:false,clock:null,clockVerified:false,terminalToken:null,
      chunks:[],bytes:0,stopping:false,animation:null,stream:null,recorder:null,finishTimer:null,maxTimer:null};
    const draw = () => {
      const data = view();
      const width=output.width, alert=data.stale || !relayConnected || data.alive===false;
      const signal=alert ? ink.orange : ink.green;
      ctx.fillStyle=ink.base;ctx.fillRect(0,0,width,headerHeight);
      ctx.fillStyle='#24202e';ctx.beginPath();ctx.moveTo(0,0);ctx.lineTo(286,0);ctx.lineTo(262,29);ctx.lineTo(0,29);ctx.fill();
      ctx.fillStyle='#66528b';ctx.fillRect(0,0,width,3);
      ctx.save();ctx.translate(12,7);ctx.scale(.8,.8);ctx.fillStyle=ink.orange;ctx.fill(new Path2D(leafPath));ctx.restore();
      ctx.font='900 20px "Arial Narrow",Impact,sans-serif';ctx.fillStyle=ink.text;
      ctx.fillText('MAPLE',39,24);const brandWidth=ctx.measureText('MAPLE').width;
      ctx.fillStyle=ink.green;ctx.fillText('BENCH',39+brandWidth,24);
      ctx.font='10px monospace';ctx.fillStyle=ink.muted;ctx.fillText('JOURNEY × COSMIC',283,21);
      ctx.fillStyle=ink.orange;ctx.font='bold 10px monospace';ctx.fillText('UNRANKED',width-186,21);
      ctx.strokeStyle='#946037';ctx.strokeRect(width-116,8,104,19);
      ctx.fillText(item.encodedMode&&!item.frames?'● ARMING':`● REC ${((performance.now()-item.startedAt)/1000).toFixed(1)}s`,width-108,21);
      ctx.fillStyle=signal;ctx.fillRect(0,34,4,17);
      ctx.font='bold 17px sans-serif';ctx.fillStyle=ink.text;fitText(ctx,data.mode,12,47,width-24);
      ctx.font='11px sans-serif';ctx.fillStyle=alert ? ink.orange : ink.muted;fitText(ctx,data.state,12,63,width-24);
      const vitalWidth=Math.floor((width-36)*.3), mpX=24+vitalWidth, readoutX=mpX+vitalWidth+12;
      const meter=(label,value,x,color)=>{
        ctx.fillStyle=color;ctx.font='bold 12px monospace';fitText(ctx,label,x,82,vitalWidth);
        ctx.fillStyle='#30372a';ctx.fillRect(x,88,vitalWidth,4);
        ctx.fillStyle=color;
        for(let offset=0;offset<vitalWidth*value;offset+=10) ctx.fillRect(x+offset,88,Math.min(8,vitalWidth*value-offset),4);
      };
      meter(data.hp,data.hpFraction,12,data.alive===false ? ink.danger : ink.green);
      meter(data.mp,data.mpFraction,mpX,ink.violet);
      ctx.fillStyle=ink.text;ctx.font='11px monospace';fitText(ctx,data.xp,readoutX,81,width-readoutX-12);
      ctx.fillStyle=ink.muted;fitText(ctx,data.keys,readoutX,97,width-readoutX-12);
      ctx.font='10px sans-serif';ctx.fillStyle=ink.muted;
      fitText(ctx,'ACTUAL CLIENT CANVAS / Client telemetry · no server score',12,110,width-24);
      ctx.fillStyle=ink.line;ctx.fillRect(0,headerHeight-1,width,1);
      ctx.fillStyle=signal;ctx.fillRect(0,headerHeight-2,72,2);
      ctx.drawImage(game,0,headerHeight,output.width,game.height);
    };
    item.draw = draw;
    // Capture while the client's just-drawn WebGL buffer is valid. A separate
    // browser RAF can read an older/discarded compositor frame.
    const animate = () => {
      if(capture!==item||(item.encodedMode&&item.autoRunId!==run.id)) { item.failFinalFrame?.(Error('capture_owner_changed')); return; }
      if(item.stopping && !item.finalFrameRequested) return;
      draw();
      if(item.recorderStarted) {
        if(item.encodedRecorder) {
          item.encodedRecorder.onRendered();
          item.startedAt=item.encodedRecorder.startedAt;item.startedWall=item.encodedRecorder.startedWall;
          item.firstFrameAt=item.encodedRecorder.firstFrameAt;item.firstFrameWall=item.encodedRecorder.firstFrameWall;
          if(!item.frames) notice.textContent='Recording verified post-render frames.';
        }
        const now=performance.now(),wall=Date.now();
        item.maxGap=Math.max(item.maxGap,now-(item.lastFrameAt ?? item.startedAt));
        item.firstFrameWall ??= wall; item.lastFrameWall=wall; item.firstFrameAt ??= now; item.lastFrameAt=now; item.frames=item.encodedRecorder?item.encodedRecorder.frames:item.frames+1;
      }
      // The final real hook supplies its pixels before the endpoint is sampled.
      // finishOnFrame calls recorder.stop() synchronously, before this stack yields.
      if(item.finalFrameRequested) item.finishOnFrame();
    };
    item.onRendered = animate;
    const encoded = ['post-render-encoded-frame-v1','post-render-encoded-frame-1800-v1'].includes(durationPolicy?.id);
    if(encoded) {
      item.encodedMode=true;item.durationPolicy=durationPolicy;capture=item;
      const encodedLimit=run.nativeAcceptance?run.nativeAcceptance.capture_max_ms:run.adaptiveProtocol?.wall_seconds===1800&&durationPolicy?.id==='post-render-encoded-frame-1800-v1'?1835000:335000;
      item.captureDeadlineAt=item.startedAt+encodedLimit;
      item.maxTimer=setTimeout(()=>{retainCaptureFailure(item,'capture_duration_limit');item.errors++;stopRecording();},encodedLimit);
      try {
        item.encoderPromise=createPostRenderRecorder(output,{policy:durationPolicy,maxDurationMs:encodedLimit,onFailure:code=>{
          retainCaptureFailure(item,code);
          item.failFinalFrame?.(Error(code));
          if(capture!==item) return;
          item.errors++; notice.textContent='Encoded frame capture failed; this recording cannot be accepted.';
          stopRecording();
        }});
        item.encodedRecorder=await item.encoderPromise;
        if(item.stopping || closed) return;
        item.recorderStarted=true;
        notice.textContent='Recorder ready; waiting for the first post-render frame.';renderHeader();
      } catch (error) {
        retainCaptureFailure(item,error?.message || 'encoder_initialization_failed');
        item.errors++;clearTimeout(item.maxTimer);
        if(capture===item) capture=null;
        notice.textContent='This browser could not start the required encoded-frame recording.';renderHeader();
      }
      return;
    }
    try {
      const mimeType = ['video/webm;codecs=vp8','video/webm'].find(type => MediaRecorder.isTypeSupported(type));
      if (!mimeType) throw Error('WebM capture is unavailable');
      draw(); item.stream=output.captureStream(30);
      item.recorder=new MediaRecorder(item.stream,{mimeType,videoBitsPerSecond:run.adaptiveProtocol||run.nativeAcceptance?2000000:5000000});
      item.recorder.onstart=()=>{item.recorderStarted=true;item.startedAt=performance.now();item.startedWall=Date.now();};
      item.recorder.ondataavailable=event=>{
        if(event.data.size) { item.chunks.push(event.data); item.bytes+=event.data.size; }
        if(item.bytes>96*1024*1024 && !item.stopping) { item.errors++; stopRecording(); }
      };
      item.recorder.onstop=async()=>{
        cancelAnimationFrame(item.animation); clearTimeout(item.finishTimer); clearTimeout(item.maxTimer);
        item.stream.getTracks().forEach(track=>track.stop());
        if (capture === item) capture=null;
        const endAt=item.stoppedAt ?? performance.now(),endWall=item.stoppedWall ?? Date.now();
        item.maxGap=Math.max(item.maxGap,endAt-(item.lastFrameAt ?? item.startedAt));
        pendingUpload={runId:item.autoRunId,blob:new Blob(item.chunks,{type:'video/webm'}),metadata:{
          schema_version:1,run_id:item.autoRunId,client_id:clientId,start_wall_ms:item.startedWall,end_wall_ms:endWall,
          duration_ms:Math.max(1,endAt-item.startedAt),first_frame_wall_ms:item.firstFrameWall,last_frame_wall_ms:item.lastFrameWall,
          rendered_frames:item.frames,max_frame_gap_ms:item.maxGap,hidden:item.hidden,errors:item.errors,relay_lost:item.relayLost,
          interrupted:item.hidden||item.errors>0||item.relayLost||item.frames===0||item.maxGap>1000,
          clock:item.clockVerified?item.clock:null,terminal_token:item.terminalToken}};
        if(durationPolicy)Object.assign(pendingUpload.metadata,{schema_version:2,capture_duration_policy:durationPolicy,
          first_frame_offset_ms:item.firstFrameAt===null?null:item.firstFrameAt-item.startedAt,
          last_frame_offset_ms:item.lastFrameAt===null?null:item.lastFrameAt-item.startedAt});
        item.chunks=[];
        await uploadRecording();
      };
      item.recorder.onerror=()=>{ item.errors++; notice.textContent='Recording failed; capture stopped.'; stopRecording(); };
      capture=item; item.recorder.start(1000);
      const captureLimit=run.nativeAcceptance?run.nativeAcceptance.capture_max_ms:run.adaptiveProtocol?.id==='full-client-adaptive-pilot-v1'&&run.adaptiveProtocol.wall_seconds===300
        ?335000:item.autoRunId&&run.readinessPolicy?125000:120000;
      item.maxTimer=setTimeout(()=>{item.errors++;stopRecording();},captureLimit);
      notice.textContent='Recording the actual canvas and controller/telemetry header.'; renderHeader();
    } catch {
      cancelAnimationFrame(item.animation); item.stream?.getTracks().forEach(track=>track.stop());
      if(capture===item) capture=null;
      notice.textContent='This browser could not start WebM recording.'; renderHeader();
    }
  }
  Module.MapleBenchOnRendered = () => {
    if (!capture || (capture.stopping && !capture.finalFrameRequested)) return;
    const item=capture;
    try { item.onRendered(); } catch (error) { retainCaptureFailure(item,error?.message || 'render_hook_failed'); item.failFinalFrame?.(Error('render_hook_failed')); item.errors++; notice.textContent='Frame capture failed'; stopRecording(); }
  };
  async function stopRecording() {
    const item=capture;
    if(!item) return;
    if(item.stopping) {
      if(item.encodedMode&&(closed||item.hidden||item.errors>0||item.relayLost)) {
        item.failFinalFrame?.(Error('capture_interrupted'));
        item.encodedRecorder?.abort('capture_interrupted');
      }
      return;
    }
    item.stoppedAt=performance.now();item.stoppedWall=Date.now();
    item.stopping=true; clearTimeout(item.finishTimer); cancelAnimationFrame(item.animation);
    if(item.encodedMode) {
      let stopTimer;
      try {
        // The 15s bound includes configuration settlement, the final-hook wait,
        // encoder flush and hashing. A late factory cannot leak its encoder.
        const timeout=new Promise((_,reject)=>{stopTimer=setTimeout(()=>{
          item.stopExpired=true;
          item.failFinalFrame?.(Error('encoder_stop_timeout'));
          item.encodedRecorder?.abort('encoder_stop_timeout');
          reject(Error('encoder_stop_timeout'));
        },15000);});
        const finish=(async()=>{
          const recorder=item.encodedRecorder || await item.encoderPromise;
          if(item.stopExpired){recorder.abort('encoder_stop_timeout');throw Error('encoder_stop_timeout');}
          if(capture!==item||item.autoRunId!==run.id){recorder.abort('capture_owner_changed');throw Error('capture_owner_changed');}
          if(closed||item.hidden||item.errors>0||item.relayLost)recorder.abort('capture_interrupted');
          if(recorder.failed || !recorder.frames) return recorder.stop();
          return new Promise((resolve,reject)=>{
            const clear=()=>{
              clearTimeout(item.finalFrameTimer);item.finalFrameRequested=false;
              item.finishOnFrame=null;item.failFinalFrame=null;
            };
            item.failFinalFrame=error=>{clear();recorder.abort(error.message);reject(error);};
            item.finishOnFrame=()=>{
              if(capture!==item||item.autoRunId!==run.id){item.failFinalFrame(Error('capture_owner_changed'));return;}
              if(performance.now()>item.captureDeadlineAt){item.failFinalFrame(Error('capture_duration_limit'));return;}
              clear();
              try{const ending=recorder.stop();clearTimeout(item.maxTimer);resolve(ending);}
              catch(error){recorder.abort('encoder_stop_failed');reject(error);}
            };
            item.finalFrameRequested=true;
            item.finalFrameTimer=setTimeout(()=>item.failFinalFrame?.(Error('capture_final_frame_timeout')),1000);
          });
        })();
        const finished=await Promise.race([finish,timeout]);
        clearTimeout(stopTimer);stopTimer=null;
        if(capture!==item||item.autoRunId!==run.id)throw Error('capture_owner_changed');
        if(item.encodedRecorder.startedAt+finished.measurements.duration_ms>item.captureDeadlineAt)throw Error('capture_duration_limit');
        pendingUpload={runId:item.autoRunId,blob:finished.blob,metadata:{
          schema_version:3,run_id:item.autoRunId,client_id:clientId,...finished.measurements,
          capture_duration_policy:item.durationPolicy,
          encoder_receipt:finished.encoder_receipt,
          hidden:item.hidden,errors:item.errors,relay_lost:item.relayLost,
          interrupted:item.hidden||item.errors>0||item.relayLost||finished.measurements.rendered_frames===0||finished.measurements.max_frame_gap_ms>1000,
          clock:item.clockVerified?item.clock:null,terminal_token:item.terminalToken}};
        if(capture===item) capture=null;
        await uploadRecording();
      } catch (error) {
        retainCaptureFailure(item,error?.message || 'encoder_stop_failed');
        if(capture===item) {
          capture=null;notice.textContent='Encoded recording did not finish verification; the run has no accepted recording.';
        }
      } finally { clearTimeout(stopTimer);clearTimeout(item.maxTimer);clearTimeout(item.finalFrameTimer);item.finalFrameRequested=false;item.finishOnFrame=null;item.failFinalFrame=null; }
      renderHeader();return;
    }
    clearTimeout(item.maxTimer);
    if(item.recorder.state!=='inactive') item.recorder.stop();
    else { item.stream.getTracks().forEach(track=>track.stop()); capture=null; }
    renderHeader();
  }
  const recordButton = button('Record',()=>startRecording(),tools);
  recordButton.classList.add('mb-record');
  const stopButton = button('Stop & save',stopRecording,tools);
  const retryButton = button('Retry save',uploadRecording,tools);

  const storageKey='maplebench.full-client.tab';
  let clientId=sessionStorage.getItem(storageKey);
  if(!clientId || !/^[A-Za-z0-9_-]{1,64}$/.test(clientId)) {
    clientId=crypto.randomUUID(); sessionStorage.setItem(storageKey,clientId);
  }
  const sessionAck=new URLSearchParams(location.search).get('transition');
  const updateRun = next => {
    if(captureFailure && captureFailure.run_id!==next.id) captureFailure=null;
    run=next;
    if(run.id && lastRunId!==run.id && activeRun()) { lastRunId=run.id; setBaseline('run'); details.open=false; }
    if(activeRun() && run.id && recordedRunId!==run.id && !saving) {
      recordedRunId=run.id; startRecording(run.id);
    }
    if(run.captureTerminal && capture?.autoRunId===run.id) capture.terminalToken=run.captureTerminal.id;
    if(['completed','failed'].includes(run.status) && !run.workerActive && capture?.autoRunId===run.id && !capture.finishTimer) {
      capture.finishTimer=setTimeout(stopRecording,600);
    }
    renderHeader();
  };
  const commandDeadline = (command, sentAt, sentWall, receivedAt, receivedWall) => {
    const elapsed=receivedAt-sentAt, wallElapsed=receivedWall-sentWall;
    if(!Number.isInteger(command.remainingMs) || command.remainingMs<30 || command.remainingMs>3000
      || !Number.isFinite(elapsed) || !Number.isFinite(wallElapsed)
      || elapsed<0 || wallElapsed<0 || Math.max(elapsed,wallElapsed)>2000
      || Math.abs(elapsed-wallElapsed)>250) return NaN;
    // Subtract the entire trip conservatively; server and laptop clocks need
    // not agree. Recheck this local deadline immediately before keydown.
    return receivedAt+command.remainingMs-Math.max(elapsed,wallElapsed);
  };
  const ackFrame = (ack, runId) => {
    const observation=observe(),clientSentAtMs=Date.now();
    return {client:clientId,observation,ageMs:Date.now()-(observation.capturedAt||0),renderAgeMs:Date.now()-(Module.MapleBenchRenderedAt||0),renderedHud:Module.MapleBenchHud||null,ack,
          page:'game',sessionAck,releaseAck,clientSentAtMs,captureClockAck:capture?.clock?.id,
          captureClockReceivedAtMs:capture?.clock?.client_received_ms,
          capture:capture?{runId:capture.autoRunId,started:capture.recorderStarted,renderedFrames:capture.frames,
            interrupted:capture.hidden||capture.errors>0||capture.relayLost||capture.stopping}:null,
          captureState:saving?'saving':pendingUpload?'failed':capture?'recording':'idle',captureFailure};
  };
  const sendUrgentAck = async (ack, runId, startedAt) => {
    const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),2000);
    try {
      // One attempt only. The normal poll retains the same ACK on any reply.
      const body={...ackFrame(ack,runId),ackRunId:runId};
      ack.timing.urgent_post_after_ms=Math.round(performance.now()-startedAt);
      await fetch('/control/ack',{method:'POST',headers:{'Content-Type':'application/json'},
        signal:abort.signal,body:JSON.stringify(body)});
    } catch {} finally {clearTimeout(timer);}
  };
  const executeInput = async (command, deadline) => {
    if(activeCommand) return;
    const item={interrupted:false,failure:null,keydown:false,startedAt:performance.now()}; activeCommand=item;
    const keys=Array.isArray(command.keys)?command.keys.map(name=>(run.adaptiveProtocol||run.nativeAcceptance)?(skillKeyNames[name]||keyNames[name]):keyNames[name]):[];
    let ok=false;
    const reject=code=>{item.failure ??= code;throw Error(code);};
    try {
      if(document.hidden) reject('hidden_before_input');
      if(!fresh(observe())) reject('stale_before_input');
      if(!relayConnected) reject('relay_before_input');
      if(cancelledRuns.has(command.runId)) reject('cancelled_before_input');
      if(!capture?.recorderStarted || !capture.frames || capture.autoRunId!==command.runId) reject('capture_unavailable');
      if(capture.stopping) reject('capture_stopping');
      if(command.runId && command.runId!==run.id) reject('run_mismatch');
      if(!keys.length||keys.length>3||new Set(keys).size!==keys.length||keys.some(code=>!code)) reject('invalid_input_keys');
      if(!Number.isInteger(command.durationMs)||command.durationMs<30||command.durationMs>1500) reject('invalid_input_duration');
      if(!Number.isFinite(deadline)) reject('invalid_input_deadline');
      if(performance.now()+command.durationMs>deadline) reject('deadline_before_input');
      releaseAll(false); game.focus();
      if(performance.now()+command.durationMs>deadline) reject('deadline_before_keydown');
      item.keydown=true; item.keydownAt=performance.now();
      for(const code of keys) { key(code,'keydown'); held.set(code,setTimeout(()=>release(code),command.durationMs)); }
      renderHeader();
      await new Promise(resolve=>setTimeout(resolve,command.durationMs));
      ok=!item.interrupted && performance.now()<=deadline;
      if(!ok) item.failure ??= item.interrupted?'interrupted_unknown':'deadline_after_input';
    } finally {
      keys.filter(Boolean).forEach(release);
      acknowledgement={id:command.id,ok};
      if(!ok) {
        const elapsed=Math.round(performance.now()-item.startedAt),remaining=Math.round(deadline-performance.now());
        acknowledgement.failure={code:item.failure||'input_failure_unknown',keydown_issued:item.keydown,
          elapsed_ms:Number.isSafeInteger(elapsed)&&elapsed>=0&&elapsed<=350000?elapsed:null,
          remaining_ms:Number.isSafeInteger(remaining)&&remaining>=-350000&&remaining<=3000?remaining:null};
      }
      const done=performance.now();
      acknowledgement.timing={schema_version:1,handler_started_monotonic_ms:Math.round(item.startedAt),
        keydown_after_ms:item.keydown?Math.round(item.keydownAt-item.startedAt):null,
        finished_after_ms:Math.round(done-item.startedAt),urgent_post_after_ms:Math.round(done-item.startedAt)};
      activeCommand=null; renderHeader();
      sendUrgentAck(acknowledgement,command.runId,item.startedAt).catch(()=>{});
    }
  };
  const poll=async()=>{
    if(closed) return;
    pollAbort=new AbortController(); const timeout=setTimeout(()=>pollAbort.abort(),2000);
    try {
      const observation=observe(), ack=acknowledgement, clientSentAtMs=Date.now(), clientSentAt=performance.now();
      const response=await fetch('/control/frame',{method:'POST',headers:{'Content-Type':'application/json'},signal:pollAbort.signal,
        body:JSON.stringify({client:clientId,observation,ageMs:Date.now()-(observation.capturedAt||0),renderAgeMs:Date.now()-(Module.MapleBenchRenderedAt||0),renderedHud:Module.MapleBenchHud||null,ack,
          page:'game',sessionAck,releaseAck,clientSentAtMs,captureClockAck:capture?.clock?.id,
          captureClockReceivedAtMs:capture?.clock?.client_received_ms,
          capture:capture?{runId:capture.autoRunId,started:capture.recorderStarted,renderedFrames:capture.frames,
            interrupted:capture.hidden||capture.errors>0||capture.relayLost||capture.stopping}:null,
          captureState:saving?'saving':pendingUpload?'failed':capture?'recording':'idle',captureFailure})});
      if(!response.ok) throw Error('Relay unavailable');
      const state=await response.json(),clientReceivedAtMs=Date.now(),clientReceivedAt=performance.now();
      if(acknowledgement===ack) acknowledgement=null;
      relayConnected=true; disconnectedAt=null; updateRun(state.run);
      if(capture?.autoRunId===run.id && !run.captureClockAccepted && state.clock?.client_sent_ms===clientSentAtMs) {
        capture.clock={...state.clock,client_received_ms:clientReceivedAtMs};
      }
      if(capture?.clock && run.captureClockAccepted===capture.clock.id) capture.clockVerified=true;
      if(state.releaseKeys?.runId) { cancelledRuns.add(state.releaseKeys.runId); releaseAll(true,'interrupted_cancelled'); releaseAck=state.releaseKeys.runId; }
      if(document.hidden || !fresh(observe())) releaseAll(true,document.hidden?'interrupted_hidden':'interrupted_stale_observation');
      if(state.command && !state.releaseKeys) executeInput(state.command,
        commandDeadline(state.command,clientSentAt,clientSentAtMs,clientReceivedAt,clientReceivedAtMs)).catch(()=>{});
      if(state.session?.desiredPage==='waiting' && !busy() && capture) stopRecording();
      const navigation=state.navigation;
      if(navigation && navigation.page==='waiting' && /^[a-f0-9]{32}$/.test(navigation.id)
          && navigation.url==='/control/wait?transition='+navigation.id
          && !busy() && !capture && !saving && !pendingUpload) {
        closed=true; releaseAll(true,'interrupted_navigation'); location.assign(navigation.url);
      }
    } catch {
      relayConnected=false; disconnectedAt ??= Date.now(); releaseAll(true,'interrupted_relay');
      if(capture) capture.relayLost=true;
      if(capture?.autoRunId && Date.now()-disconnectedAt>3000) stopRecording();
      renderHeader();
    } finally { clearTimeout(timeout); if(!closed) pollTimer=setTimeout(poll,100); }
  };
  const startRun=async(mode,model=null,durationSeconds=22)=>{
    // Let the previous run's terminal frame finish and upload before a new run
    // can inherit its capture or be stopped by its pending completion timer.
    if(busy() || saving || pendingUpload || capture) return;
    starting=true; releaseAll(true); renderHeader();
    try {
      const response=await fetch('/control/start',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({mode,model,durationSeconds,client:clientId}),signal:AbortSignal.timeout(5000)});
      if(!response.ok) throw Error();
      updateRun(await response.json()); notice.textContent='';
    } catch { notice.textContent='Start was not confirmed; checking the relay for the current run.'; }
    finally { starting=false; renderHeader(); }
  };
  button('Run SDK script',()=>startRun('script'),modelGroup,runButtons);
  for(const [name,model] of [['Astra','gpt-6-astra'],['Sol','gpt-5.6-sol'],['Terra','gpt-5.6-terra'],['Luna','gpt-5.6-luna']])
    button(name+' API',()=>startRun('api',model),modelGroup,runButtons);
  button('Astra · 60s demo',()=>startRun('api','gpt-6-astra',60),modelGroup,runButtons);
  window.addEventListener('pagehide',()=>{ closed=true;clearTimeout(pollTimer);pollAbort?.abort();releaseAll(true,'interrupted_page_hide');stopRecording(); });
  resize(); renderHeader(); poll();
})();
