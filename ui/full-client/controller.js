// Live controls and honest canvas capture for the unscored full-client adapter.
(() => {
  fetch('/demo-session').then(r => { if (!r.ok) throw Error(); return r.json(); })
    .then(session => { Module.MapleBenchSession = session; }).catch(() => {});
  const game = document.getElementById('canvas');
  if (!game) return;
  const style = document.createElement('style');
  style.textContent = `
    #maplebench-shell{position:fixed;inset:0;z-index:10;display:flex;flex-direction:column;background:#0c1320;color:#edf4ff;font:12px system-ui,sans-serif;text-align:left}
    #maplebench-shell *{box-sizing:border-box}
    #maplebench-shell header{flex:none;padding:8px 12px;border-bottom:1px solid #2b3c55;display:grid;gap:3px}
    #maplebench-shell .mb-title{display:flex;justify-content:space-between;gap:8px;color:#91b7e5;font-size:11px;letter-spacing:.04em}
    #maplebench-shell .mb-controller{font-weight:650;font-size:14px;overflow-wrap:anywhere}
    #maplebench-shell .mb-status{color:#b4c6dd;font-size:11px;overflow-wrap:anywhere}
    #maplebench-shell .mb-telemetry{display:flex;flex-wrap:wrap;column-gap:14px;row-gap:2px;font-variant-numeric:tabular-nums}
    #maplebench-shell .mb-note{color:#93a9c3;font-size:10px}
    #maplebench-shell .mb-stage{flex:1;min-height:0;min-width:0;display:flex;align-items:center;justify-content:center;overflow:hidden;background:#03070e}
    #maplebench-shell canvas{display:block!important;position:static!important;margin:0!important;border:0!important;flex:none;max-width:none!important;max-height:none!important;width:var(--mb-canvas-width)!important;height:var(--mb-canvas-height)!important}
    #maplebench-shell footer{flex:none;background:#121d2d;border-top:1px solid #2b3c55;padding:6px 10px;max-height:45%;overflow:auto}
    #maplebench-shell .mb-tools{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
    #maplebench-shell details{flex:1;min-width:150px}
    #maplebench-shell summary{cursor:pointer;padding:5px 0;color:#c3d9f5;font-weight:600}
    #maplebench-shell .mb-controls{display:flex;flex-wrap:wrap;gap:5px;padding:5px 0}
    #maplebench-shell button{border:1px solid #405673;border-radius:5px;background:#20334d;color:#eef5ff;padding:5px 8px;font:inherit;cursor:pointer;white-space:nowrap}
    #maplebench-shell button:hover:not(:disabled){background:#304969}
    #maplebench-shell button:disabled{opacity:.45;cursor:default}
    #maplebench-shell button:focus-visible,#maplebench-shell summary:focus-visible{outline:2px solid #9bcdff;outline-offset:2px}
    #maplebench-shell .mb-notice{color:#b7cce6;font-size:11px;margin-top:3px;overflow-wrap:anywhere}
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
  element('span', '', title, 'MAPLEBENCH · JOURNEY + COSMIC');
  const captureStatus = element('span', '', title, 'LIVE');
  const controller = element('div', 'mb-controller', header);
  const status = element('div', 'mb-status', header);
  const telemetry = element('div', 'mb-telemetry', header);
  const hpText = element('span', '', telemetry), mpText = element('span', '', telemetry);
  const xpText = element('span', '', telemetry), keysText = element('span', '', telemetry);
  element('div', 'mb-note', header, 'Client telemetry · unranked · no server score');
  const stage = element('div', 'mb-stage', shell); stage.appendChild(game);
  const footer = element('footer', '', shell);
  const tools = element('div', 'mb-tools', footer);
  const details = element('details', '', tools);
  element('summary', '', details, 'Controls & models');
  const manualGroup = element('div', 'mb-controls', details);
  const modelGroup = element('div', 'mb-controls', details);
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
  const namesByCode = Object.fromEntries(Object.entries(keyNames).map(([name, code]) => [code, name]));
  const codes = {ArrowLeft:37,ArrowRight:39,ArrowUp:38,ArrowDown:40,ControlLeft:17,Space:32,KeyA:65,KeyS:83,KeyD:68,KeyF:70,KeyQ:81,KeyW:87};
  const held = new Map(), physical = new Set(), manualButtons = [], runButtons = [];
  let run = {status:'idle',mode:'manual',model:null}, baseline = null, baselineScope = 'session';
  let starting = false, relayConnected = false, disconnectedAt = null, closed = false;
  let acknowledgement = null, activeCommand = null, lastRunId = null, recordedRunId = null;
  let capture = null, saving = false, pollTimer, pollAbort;
  const activeRun = () => ['requesting','running'].includes(run.status);
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
  const releaseAll = interrupted => {
    if (interrupted && activeCommand) activeCommand.interrupted = true;
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
  button('Release keys', () => releaseAll(true), manualGroup);
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
  window.addEventListener('blur', () => { releaseAll(true); renderHeader(); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { releaseAll(true); if (capture?.autoRunId) stopRecording(); }
  });

  const format = value => Number.isFinite(value) ? value.toLocaleString('en-US') : '—';
  const view = () => {
    const observation = observe(), available = fresh(observation), character = observation.character || {};
    if (!baseline && available) setBaseline(activeRun() ? 'run' : 'session');
    const model = run.mode === 'api' ? (run.model || 'model unavailable') : null;
    const mode = activeRun() ? (run.mode === 'api' ? `OpenAI API · ${model}` : 'Scripted SDK · no evaluated model')
      : 'Manual controls · no active model';
    let state = !relayConnected ? 'Relay disconnected · inputs released'
      : !available ? 'Waiting for fresh client state'
      : run.status === 'requesting' ? (run.mode === 'api' ? 'Awaiting API program · game remains live' : 'Preparing SDK program')
      : run.status === 'running' ? 'Program running'
      : run.id ? `Last ${model || 'scripted SDK'} run: ${run.status}${run.actions != null ? ` · ${run.actions} actions` : ''}${run.reason ? ` · ${run.reason}` : ''}`
      : 'Ready · manual input';
    if (available && character.alive === false) state += ' · CHARACTER DEAD';
    const delta = available && baseline && character.level === baseline.level
      && Number.isFinite(character.exp) && Number.isFinite(baseline.exp) ? character.exp - baseline.exp : null;
    const xp = delta === null ? (available && baseline && character.level !== baseline.level ? 'XP Δ unavailable (level changed)' : 'XP Δ —')
      : `XP Δ ${delta >= 0 ? '+' : ''}${format(delta)} (${baselineScope})`;
    const keys = [...new Set([...held.keys(),...physical])].map(code => namesByCode[code] || code).join(' + ') || 'none';
    return {mode,state,hp:`HP ${available ? format(character.hp)+' / '+format(character.maxHp) : '—'}`,
      mp:`MP ${available ? format(character.mp)+' / '+format(character.maxMp) : '—'}`,xp,keys:`Keys: ${keys}`,
      stale:!available, alive:character.alive, level:character.level};
  };
  function renderHeader() {
    const data = view(); controller.textContent = data.mode; status.textContent = data.state;
    hpText.textContent = data.hp; mpText.textContent = data.mp; xpText.textContent = data.xp; keysText.textContent = data.keys;
    hpText.style.color = data.alive === false ? '#ffa0a0' : '#a7e8bb';
    captureStatus.textContent = capture ? `● REC ${((performance.now()-capture.startedAt)/1000).toFixed(1)}s` : saving ? 'SAVING' : 'LIVE';
    manualButtons.forEach(node => { node.disabled = busy(); });
    runButtons.forEach(node => { node.disabled = busy() || !relayConnected || !fresh(observe()) || saving || Boolean(capture?.autoRunId) || Boolean(capture?.stopping); });
    recordButton.disabled = Boolean(capture) || saving; stopButton.disabled = !capture || capture.stopping;
  }
  const fitText = (ctx, text, x, y, width) => {
    let value = String(text);
    while (value.length && ctx.measureText(value).width > width) value = value.slice(0,-1);
    ctx.fillText(value === text ? value : value.slice(0,-1)+'…', x,y);
  };
  function startRecording(autoRunId = null) {
    if (capture) { if (autoRunId) capture.autoRunId = autoRunId; return; }
    if (saving || closed) return;
    const output = document.createElement('canvas'), headerHeight = 104;
    output.width = game.width; output.height = game.height + headerHeight;
    const ctx = output.getContext('2d');
    const item = {autoRunId,startedAt:performance.now(),chunks:[],stopping:false,animation:null,stream:null,recorder:null,finishTimer:null};
    const draw = () => {
      const data = view();
      ctx.fillStyle='#101b2b';ctx.fillRect(0,0,output.width,headerHeight);
      ctx.font='bold 15px sans-serif';ctx.fillStyle='#fff';
      fitText(ctx,`MAPLEBENCH  |  ${data.mode}`,12,20,output.width-24);
      ctx.font='12px sans-serif';ctx.fillStyle='#c1d8f3';
      fitText(ctx,data.state,12,39,output.width-24);
      ctx.fillStyle='#e5f1ff';ctx.font='bold 13px sans-serif';
      fitText(ctx,`${data.hp}   ${data.mp}   ${data.xp}`,12,59,output.width-24);
      ctx.font='12px sans-serif';ctx.fillStyle='#c1d8f3';
      fitText(ctx,`${data.keys}   |   Capture ${((performance.now()-item.startedAt)/1000).toFixed(1)}s`,12,78,output.width-24);
      ctx.font='11px sans-serif';ctx.fillStyle='#98b2d0';
      fitText(ctx,'Actual Journey + Cosmic client canvas · client telemetry only · unranked / no server score',12,96,output.width-24);
      ctx.drawImage(game,0,headerHeight,output.width,game.height);
    };
    item.draw = draw;
    // Capture while the client's just-drawn WebGL buffer is valid. A separate
    // browser RAF can read an older/discarded compositor frame.
    const animate = () => { if (!item.stopping) draw(); };
    item.onRendered = animate;
    try {
      const mimeType = ['video/webm;codecs=vp8','video/webm'].find(type => MediaRecorder.isTypeSupported(type));
      if (!mimeType) throw Error('WebM capture is unavailable');
      draw(); item.stream=output.captureStream(30);
      item.recorder=new MediaRecorder(item.stream,{mimeType,videoBitsPerSecond:5000000});
      item.recorder.ondataavailable=event=>{ if(event.data.size) item.chunks.push(event.data); };
      item.recorder.onstop=async()=>{
        cancelAnimationFrame(item.animation); clearTimeout(item.finishTimer);
        item.stream.getTracks().forEach(track=>track.stop());
        if (capture === item) capture=null;
        saving=true; renderHeader();
        try {
          const response=await fetch('/demo-recording',{method:'POST',headers:item.autoRunId?{'X-MapleBench-Run':item.autoRunId}:{},body:new Blob(item.chunks,{type:'video/webm'}),signal:AbortSignal.timeout(30000)});
          if (!response.ok) throw Error();
          notice.textContent='Saved full-client-demo.webm on the runner.';
        } catch { notice.textContent='Recording could not be saved on the runner.'; }
        finally { saving=false; renderHeader(); }
      };
      item.recorder.onerror=()=>{ notice.textContent='Recording failed; capture stopped.'; stopRecording(); };
      capture=item; item.recorder.start(1000); animate();
      notice.textContent='Recording the actual canvas and controller/telemetry header.'; renderHeader();
    } catch {
      cancelAnimationFrame(item.animation); item.stream?.getTracks().forEach(track=>track.stop());
      if(capture===item) capture=null;
      notice.textContent='This browser could not start WebM recording.'; renderHeader();
    }
  }
  Module.MapleBenchOnRendered = () => {
    if (!capture || capture.stopping) return;
    try { capture.onRendered(); } catch { notice.textContent='Frame capture failed'; stopRecording(); }
  };
  function stopRecording() {
    const item=capture;
    if(!item||item.stopping) return;
    item.stopping=true; clearTimeout(item.finishTimer); cancelAnimationFrame(item.animation);
    if(item.recorder.state!=='inactive') item.recorder.stop();
    else { item.stream.getTracks().forEach(track=>track.stop()); capture=null; }
    renderHeader();
  }
  const recordButton = button('Record',()=>startRecording(),tools);
  const stopButton = button('Stop & save',stopRecording,tools);

  const clientId=crypto.randomUUID();
  const updateRun = next => {
    run=next;
    if(run.id && lastRunId!==run.id && activeRun()) { lastRunId=run.id; setBaseline('run'); details.open=false; }
    if(activeRun() && run.id && recordedRunId!==run.id && !saving) {
      recordedRunId=run.id; startRecording(run.id);
    }
    if(['completed','failed'].includes(run.status) && capture?.autoRunId===run.id && !capture.finishTimer) {
      capture.finishTimer=setTimeout(stopRecording,600);
    }
    renderHeader();
  };
  const executeInput = async command => {
    if(activeCommand) return;
    const item={interrupted:false}; activeCommand=item;
    const keys=Array.isArray(command.keys)?command.keys.map(name=>keyNames[name]):[];
    let ok=false;
    try {
      if(!keys.length||keys.length>3||new Set(keys).size!==keys.length||keys.some(code=>!code)
        ||!Number.isInteger(command.durationMs)||command.durationMs<30||command.durationMs>1500) throw Error('Invalid input');
      releaseAll(false); game.focus();
      for(const code of keys) { key(code,'keydown'); held.set(code,setTimeout(()=>release(code),command.durationMs)); }
      renderHeader();
      await new Promise(resolve=>setTimeout(resolve,command.durationMs));
      ok=!item.interrupted;
    } finally {
      keys.filter(Boolean).forEach(release);
      acknowledgement={id:command.id,ok}; activeCommand=null; renderHeader();
    }
  };
  const poll=async()=>{
    if(closed) return;
    pollAbort=new AbortController(); const timeout=setTimeout(()=>pollAbort.abort(),2000);
    try {
      const observation=observe(), ack=acknowledgement;
      const response=await fetch('/control/frame',{method:'POST',headers:{'Content-Type':'application/json'},signal:pollAbort.signal,
        body:JSON.stringify({client:clientId,observation,ageMs:Date.now()-(observation.capturedAt||0),renderAgeMs:Date.now()-(Module.MapleBenchRenderedAt||0),renderedHud:Module.MapleBenchHud||null,ack})});
      if(!response.ok) throw Error('Relay unavailable');
      const state=await response.json();
      if(acknowledgement===ack) acknowledgement=null;
      relayConnected=true; disconnectedAt=null; updateRun(state.run);
      if(state.command) executeInput(state.command).catch(()=>{});
    } catch {
      relayConnected=false; disconnectedAt ??= Date.now(); releaseAll(true);
      if(capture?.autoRunId && Date.now()-disconnectedAt>3000) stopRecording();
      renderHeader();
    } finally { clearTimeout(timeout); if(!closed) pollTimer=setTimeout(poll,100); }
  };
  const startRun=async(mode,model=null)=>{
    // Let the previous run's terminal frame finish and upload before a new run
    // can inherit its capture or be stopped by its pending completion timer.
    if(busy() || saving || capture?.autoRunId || capture?.stopping) return;
    starting=true; releaseAll(true); renderHeader();
    try {
      const response=await fetch('/control/start',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({mode,model}),signal:AbortSignal.timeout(5000)});
      if(!response.ok) throw Error();
      updateRun(await response.json()); notice.textContent='';
    } catch { notice.textContent='Start was not confirmed; checking the relay for the current run.'; }
    finally { starting=false; renderHeader(); }
  };
  button('Run SDK script',()=>startRun('script'),modelGroup,runButtons);
  for(const [name,model] of [['Astra','gpt-6-astra'],['Sol','gpt-5.6-sol'],['Terra','gpt-5.6-terra'],['Luna','gpt-5.6-luna']])
    button(name+' API',()=>startRun('api',model),modelGroup,runButtons);
  window.addEventListener('pagehide',()=>{ closed=true;clearTimeout(pollTimer);pollAbort?.abort();releaseAll(true);stopRecording(); });
  resize(); renderHeader(); poll();
})();
