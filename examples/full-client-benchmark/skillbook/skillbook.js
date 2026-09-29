(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const el = (tag, text, cls) => { const n=document.createElement(tag); if(text!=null)n.textContent=text; if(cls)n.className=cls; return n; };
  const names={'gpt-6-astra':'GPT-6 Astra','gpt-5.6-sol':'GPT-5.6 Sol','gpt-5.6-terra':'GPT-5.6 Terra','gpt-5.6-luna':'GPT-5.6 Luna'};
  const colors={'gpt-6-astra':'#609b8b','gpt-5.6-sol':'#d2a35b','gpt-5.6-terra':'#a580b7','gpt-5.6-luna':'#6f9bc6'};
  const classes={hero:{label:'Hero',symbol:'⚔',hint:'Melee'},bowmaster:{label:'Bowmaster',symbol:'➶',hint:'Ranged'},ice_lightning_arch_mage:{label:'Ice / Lightning',symbol:'ϟ',hint:'Magic'}};
  const tasks=[
    {id:'jump',label:'Platforming',symbol:'↗',hint:'Reach a ledge',condition:'Reach a marked platform from a fixed spawn using normal movement. Verify the destination and a stable landing in authoritative position events.',needs:'A qualified map fixture and a complete position / landing trace.'},
    {id:'teleport',label:'Teleport',symbol:'↔',hint:'Mage fixture',condition:'Use native Teleport to cross a specified gap and stop in the target zone. A key acknowledgment alone does not count.',needs:'Native skill execution, position change, and resource-consumption evidence.'},
    {id:'potion',label:'Potion use',symbol:'♧',hint:'Restore MP',condition:'Restore MP from a declared low-MP start using a potion, without dying or receiving outside help.',needs:'A native item-use event or validated inventory and MP deltas; regeneration must be distinguished.'},
    {id:'buff',label:'Buff upkeep',symbol:'✧',hint:'Maintain uptime',condition:'Keep a specified class buff active during a bounded combat task. Score its authoritative active-time fraction.',needs:'A qualified class skill and timestamped buff apply / expire events.'},
    {id:'route',label:'Navigation',symbol:'⌁',hint:'Reach a map',condition:'Traverse a fixed route and arrive at the target map through normal portals. Completion and time are separate from XP.',needs:'Authoritative map transitions, start/end positions, and the fixed task deadline.'},
    {id:'recovery',label:'Recovery',symbol:'↶',hint:'Return to hunt',condition:'After a controlled setback, return to the hunting area and resume productive play within the task budget.',needs:'A frozen setback fixture, respawn / route events, and an authoritative resumed-progress event.'}
  ];
  let data, view='class', selection;
  const fmt = n => Number.isFinite(n) ? `${n>0?'+':''}${n.toLocaleString('en-US',{maximumFractionDigits:0})}` : '—';
  function scoreTier(value,max) { if(!Number.isFinite(value))return 'unknown'; if(value<0)return 'loss'; if(value===0)return 'zero'; const t=max>0?value/max:0; return t>=.9?'high':t>=.5?'mid':'low'; }
  function link(text,href) { const a=el('a',text); const u=new URL(href); if(u.protocol!=='https:'||u.origin!=='https://maplebench.vercel.app')return el('span',text); a.href=u.href; return a; }
  function showCell(model,col,cell,button) {
    selection={model,col};
    document.querySelectorAll('.score-cell').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
    const box=$('cell-inspector');box.replaceChildren();
    box.append(el('p',names[model]||model,'inspector-model'));
    if(view==='skill') {
      box.append(el('h2',col.label),el('p','Proposed task · no model evaluated','inspector-unit'),el('p',col.condition,'inspector-note'),el('p','Evidence needed: '+col.needs,'inspector-note'));
      return;
    }
    box.append(el('h2',classes[col.class_id]?.label||col.class_label),el('p',fmt(cell?.mean),'inspector-score'),el('p','Saved XP over 5 minutes','inspector-unit'));
    const runs=data.attempts.filter(r=>(cell?.attempt_ids||[]).includes(r.id));
    const list=el('dl');
    const fields=[['Verified runs',`${cell?.valid??0} / ${cell?.planned??0}`],['Uncertainty',cell?.uncertainty==='not_estimated'?'Not estimated':'See source data']];
    if(runs.length===1)fields.push(['Acknowledged inputs',String(runs[0].acknowledged_actions??'—')],['Alive at logout',runs[0].alive_at_logout===true?'Yes':runs[0].alive_at_logout===false?'No':'Unknown'],['Model wait',`${(runs[0].api_ms/1000).toFixed(1)}s`]);
    fields.forEach(([k,v])=>list.append(el('dt',k),el('dd',v)));box.append(list);
    box.append(el('p',cell?.mean===0?'No net saved XP. This does not by itself identify which game skill failed.':'A single pilot result; it does not establish a reliable model ranking.','inspector-note'));
    const annotation=data.annotations.find(a=>a.class_id===col.class_id);
    if(annotation)box.append(el('p','This port uses discrete Hurricane attacks; continuous channeling is not implemented.','inspector-note annotation'));
    const links=el('div',null,'inspector-links');
    if(runs[0])links.append(link('Watch recording',runs[0].recording_url),link('Open cohort',runs[0].cohort_url));box.append(links);
  }
  function render() {
    const isSkill=view==='skill'; document.body.classList.toggle('planned',isSkill);
    $('class-view').setAttribute('aria-pressed',String(!isSkill));$('skill-view').setAttribute('aria-pressed',String(isSkill));
    $('matrix-context').textContent=isSkill?'Proposed controlled tests · no scores yet':'Saved XP · 5-minute pilots · 1 run per cell';
    $('matrix-legend').hidden=isSkill;
    $('matrix-caveat').textContent=isSkill?'Empty slots mean not tested. These fixtures need qualification before model trials.':'Pilot observations, not a ranking. Select a square for the evidence.';
    const table=$('matrix'),head=table.querySelector('thead'),body=table.querySelector('tbody');head.replaceChildren();body.replaceChildren();
    table.querySelector('caption').textContent=isSkill?'Proposed model skill tasks, not evaluated':'Saved XP by model and class fixture';
    const cols=isSkill?tasks:data.matrix.columns;
    const hrow=el('tr'),corner=el('th','Model');corner.scope='col';hrow.append(corner);
    cols.forEach(c=>{const meta=isSkill?c:classes[c.class_id];const th=el('th');th.scope='col';const symbol=el('span',meta.symbol,'job-symbol');symbol.setAttribute('aria-hidden','true');th.append(symbol,el('span',meta.label),el('small',meta.hint,'class-hint'));hrow.append(th);});head.append(hrow);
    const buttons=[];
    data.matrix.models.forEach(m=>{
      const row=el('tr'),label=el('th');label.scope='row';const dot=el('span',null,'model-dot');dot.style.setProperty('--model-color',colors[m.model]||'#73846a');label.append(dot,document.createTextNode(names[m.model]||m.model));row.append(label);
      cols.forEach(c=>{
        const cell=isSkill?null:m.cells.find(x=>x.column_id===c.id);
        const max=isSkill?0:Math.max(0,...data.matrix.models.map(x=>x.cells.find(y=>y.column_id===c.id)?.mean).filter(Number.isFinite));
        const b=el('button',isSkill?'—':fmt(cell?.mean),'score-cell '+(isSkill?'unrun':scoreTier(cell?.mean,max)));b.type='button';b.setAttribute('aria-pressed','false');
        const columnName=isSkill?c.label:classes[c.class_id].label;
        b.setAttribute('aria-label',`${names[m.model]||m.model}, ${columnName}: ${isSkill?'not tested':Number.isFinite(cell?.mean)?`${fmt(cell.mean)} saved XP; ${cell.valid} verified run${cell.valid===1?'':'s'}`:'score unavailable'}`);
        b.addEventListener('click',()=>showCell(m.model,c,cell,b));
        const td=el('td');td.append(b);row.append(td);buttons.push({model:m.model,col:c,cell,b});
      });body.append(row);
    });
    const picked=buttons.find(x=>x.model===selection?.model&&x.col.id===selection?.col.id)||buttons[0];if(picked)showCell(picked.model,picked.col,picked.cell,picked.b);
  }
  $('class-view').addEventListener('click',()=>{view='class';render();});$('skill-view').addEventListener('click',()=>{view='skill';render();});
  fetch('./data.json').then(r=>{if(!r.ok)throw Error('unavailable');return r.json();}).then(json=>{data=json;$('snapshot-date').textContent=`Snapshot ${new Date(data.generated_at_ms).toLocaleDateString('en-US',{month:'short',day:'numeric'})}`;render();}).catch(()=>{$('cell-inspector').replaceChildren(el('p','Could not load the pilot snapshot. Reload to try again.'));});
})();
