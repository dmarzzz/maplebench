import { appendFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const episodePath = process.env.MAPLEBENCH_EPISODE || join(repoRoot, 'artifacts/live/episode.jsonl');
const port = Number(process.env.MAPLEBENCH_CONTROL_PORT || 8790);

let seq = 0;
let startedAt = Date.now();
let events = [];
let state;

function freshState() {
  return {
    nowMs: 0,
    character: {
      id: 1, name: 'Agent01', level: 15, jobId: 100, exp: 0,
      hp: 420, maxHp: 420, mp: 130, maxMp: 130, mesos: 0,
      mapId: 100000000, position: { x: 0, y: 0 }, alive: true,
    },
    monsters: [
      { objectId: 101, monsterId: 100100, name: 'Training Slime A', hp: 70, maxHp: 70, level: 7, position: { x: 180, y: 0 }, alive: true },
      { objectId: 102, monsterId: 100100, name: 'Training Slime B', hp: 70, maxHp: 70, level: 7, position: { x: 360, y: 0 }, alive: true },
      { objectId: 103, monsterId: 100101, name: 'Training Mushroom', hp: 120, maxHp: 120, level: 12, position: { x: 620, y: -160 }, alive: true },
    ],
    drops: [],
    inventory: [{ itemId: 2000000, quantity: 20, slot: 1 }],
    portals: [{ id: 1, name: 'right', position: { x: 820, y: 0 }, targetMapId: 100000001 }],
  };
}

function nowMs() { return Date.now() - startedAt; }
function snapshot() { return structuredClone({ ...state, nowMs: nowMs() }); }

async function emit(event) {
  const full = { seq: seq++, tMs: nowMs(), ...event };
  events.push(full);
  await appendFile(episodePath, JSON.stringify(full) + '\n');
  return full;
}

async function reset() {
  await mkdir(dirname(episodePath), { recursive: true });
  await writeFile(episodePath, '');
  seq = 0; events = []; startedAt = Date.now(); state = freshState();
  await emit({ kind: 'episode_start', taskId: 'maximize-xp-10m-warrior-v0', seed: 'mock-v0', characterId: 1 });
}

function json(res, status, body) {
  res.writeHead(status, { 'content-type':'application/json; charset=utf-8', 'cache-control':'no-store', 'access-control-allow-origin':'*' });
  res.end(JSON.stringify(body));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.setEncoding('utf8');
    req.on('data', chunk => { body += chunk; if (body.length > 1_000_000) reject(new Error('body too large')); });
    req.on('end', () => resolve(body));
    req.on('error', reject);
  });
}

function targetFor(action) {
  const targetId = Number(action.targetId || 0);
  if (targetId) return state.monsters.find(m => m.objectId === targetId && m.alive);
  const living = state.monsters.filter(m => m.alive);
  living.sort((a,b) => Math.abs(a.position.x-state.character.position.x) - Math.abs(b.position.x-state.character.position.x));
  return living[0];
}

async function respawnIfNeeded() {
  if (state.monsters.some(m => m.alive)) return;
  for (const mob of state.monsters) { mob.hp = mob.maxHp; mob.alive = true; }
  await emit({ kind:'chat', fromCharacterId:0, channel:'map', message:'[mock] monster wave respawned' });
}

async function act(action) {
  const start = nowMs();
  let accepted = true;
  let error;

  if (!action || typeof action.type !== 'string') {
    accepted = false; error = 'invalid action';
  } else if (action.type === 'move_to') {
    if (!action.position || !Number.isFinite(action.position.x) || !Number.isFinite(action.position.y)) { accepted=false; error='invalid position'; }
    else state.character.position = { x: action.position.x, y: action.position.y };
  } else if (action.type === 'basic_attack' || action.type === 'use_skill') {
    const mob = targetFor(action);
    if (!mob) { accepted=false; error='no live target'; }
    else {
      const dist = Math.hypot(mob.position.x-state.character.position.x, mob.position.y-state.character.position.y);
      if (dist > 230) { accepted=false; error='target out of range'; }
      else {
        const damage = action.type === 'use_skill' ? 55 : 38;
        mob.hp = Math.max(0, mob.hp-damage);
        if (mob.hp === 0) {
          mob.alive = false;
          const amount = mob.monsterId === 100101 ? 80 : 42;
          state.character.exp += amount;
          await emit({ kind:'xp_gain', amount, source:'monster', sourceId:mob.monsterId });
          if (state.character.exp >= 290 && state.character.level === 15) {
            state.character.level = 16;
            await emit({ kind:'level_up', fromLevel:15, toLevel:16 });
          }
          await respawnIfNeeded();
        }
      }
    }
  } else if (action.type === 'use_item') {
    const item = state.inventory.find(i => i.itemId === action.itemId && i.quantity > 0);
    if (!item) { accepted=false; error='item unavailable'; }
    else { item.quantity--; state.character.hp = Math.min(state.character.maxHp, state.character.hp + 50); }
  } else if (action.type === 'loot') {
    const index = state.drops.findIndex(d => d.objectId === action.dropId);
    if (index < 0) { accepted=false; error='drop unavailable'; } else state.drops.splice(index, 1);
  } else if (action.type === 'say') {
    await emit({ kind:'chat', fromCharacterId:state.character.id, channel:'map', message:String(action.message || '').slice(0,200) });
  } else if (['enter_portal','allocate_ap','allocate_sp'].includes(action.type)) {
    // Accepted as no-ops in the plumbing mock; real Cosmic owns these semantics.
  } else {
    accepted=false; error='unsupported action';
  }

  await emit({ kind:'action', action, accepted });
  return { accepted, startedAtMs:start, completedAtMs:nowMs(), ...(error ? { error } : {}), observation:snapshot() };
}

await reset();

createServer(async (req, res) => {
  try {
    const url = new URL(req.url || '/', `http://${req.headers.host || '127.0.0.1'}`);
    if (req.method === 'OPTIONS') { res.writeHead(204, { 'access-control-allow-origin':'*', 'access-control-allow-methods':'GET,POST,OPTIONS', 'access-control-allow-headers':'content-type,authorization' }); return res.end(); }
    if (req.method === 'GET' && url.pathname === '/v1/observe') return json(res, 200, snapshot());
    if (req.method === 'GET' && url.pathname === '/v1/events') {
      const since = Math.max(0, Number(url.searchParams.get('since_seq') || 0));
      return json(res, 200, events.filter(e => e.seq >= since));
    }
    if (req.method === 'POST' && url.pathname === '/v1/action') {
      const action = JSON.parse(await readBody(req));
      return json(res, 200, await act(action));
    }
    if (req.method === 'POST' && url.pathname === '/v1/reset') { await reset(); return json(res, 200, { ok:true, observation:snapshot() }); }
    if (req.method === 'GET' && url.pathname === '/health') return json(res, 200, { ok:true, backend:'mock-cosmic', episodePath });
    return json(res, 404, { error:'not found' });
  } catch (error) {
    return json(res, 500, { error:String(error?.message || error) });
  }
}).listen(port, '127.0.0.1', () => {
  console.log(`Mock MapleBench control plane: http://127.0.0.1:${port}`);
  console.log(`Episode log: ${episodePath}`);
});
