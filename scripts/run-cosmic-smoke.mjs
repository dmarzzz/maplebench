import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { HttpMapleTransport, MapleClient } from '../dist/src/sdk.js';
import { peakXpRate, totalXp } from '../dist/src/scoring.js';

const url = process.env.MAPLEBENCH_URL || 'http://127.0.0.1:8790';
const out = process.env.MAPLEBENCH_OUTPUT || 'artifacts/cosmic-smoke';
const duration = Number(process.env.MAPLEBENCH_DURATION_MS || 60000);
if (!Number.isFinite(duration) || duration < 1000 || duration > 600000) throw new Error('Invalid duration');
const health = await (await fetch(url + '/health')).json();
if (health.backend !== 'cosmic-v83') throw new Error('This smoke test requires the real Cosmic backend');
await mkdir(out, { recursive: true });
const client = new MapleClient(new HttpMapleTransport(url));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const snapshots = [];
async function snapshot() {
  const obs = await client.observe();
  snapshots.push(obs);
  const lines = [`player ${obs.character.position.x} ${obs.character.position.y}`];
  for (const m of obs.monsters.filter(m => m.alive)) {
    lines.push(`mob ${m.objectId} ${m.monsterId} ${m.position.x} ${m.position.y} ${Math.max(1, Math.ceil(100 * m.hp / m.maxHp))}`);
  }
  await writeFile(join(out, `state-${String(snapshots.length - 1).padStart(4, '0')}.tsv`), lines.join('\n') + '\n');
  return obs;
}

const initial = await snapshot();
const initialEvents = await client.events(0);
await sleep(2000);
const idle = await snapshot();
const idleEvents = await client.events(0);
const idleXp = totalXp(idleEvents) - totalXp(initialEvents);
if (idleXp !== 0) throw new Error('XP changed without agent actions');
console.log('Idle check passed; character', initial.character.name, 'level', initial.character.level);

let accepted = 0, rejected = 0, lastMove = '', lastMovedAt = 0;
const started = Date.now();
while (Date.now() - started < duration) {
  const obs = await snapshot();
  if (!obs.character.alive) { console.log('Character died'); break; }
  const p = obs.character.position;
  const mobs = obs.monsters.filter(m => m.alive);
  mobs.sort((a, b) => (Math.abs(a.position.x - p.x) + 5 * Math.abs(a.position.y - p.y)) -
                      (Math.abs(b.position.x - p.x) + 5 * Math.abs(b.position.y - p.y)));
  const target = mobs[0];
  if (!target) { await sleep(500); continue; }
  let result;
  if (Math.abs(target.position.x - p.x) > 55 || Math.abs(target.position.y - p.y) > 25) {
    const key = `${target.objectId}:${target.position.x}:${target.position.y}`;
    if (key !== lastMove || Date.now() - lastMovedAt > 4000) {
      result = await client.moveTo(target.position);
      lastMove = key; lastMovedAt = Date.now();
      console.log('move', p, '->', target.position, result.accepted);
    }
  } else {
    result = await client.attack(target.objectId);
    console.log('attack', target.objectId, result.accepted, result.error || '');
  }
  if (result) result.accepted ? accepted++ : rejected++;
  await sleep(500);
}
const final = await snapshot();
const events = await client.events(0);
const score = {
  backend: health.backend, policy: 'nearest-monster-basic-attack',
  durationMs: Date.now() - started, idleXp, accepted, rejected,
  startingLevel: initial.character.level, finalLevel: final.character.level,
  startingExp: initial.character.exp, finalExp: final.character.exp,
  xpGainedThisRun: totalXp(events) - totalXp(idleEvents),
  alive: final.character.alive, ...peakXpRate(events),
};
await writeFile(join(out, 'observations.json'), JSON.stringify(snapshots, null, 2) + '\n');
await writeFile(join(out, 'episode.jsonl'), events.map(e => JSON.stringify(e)).join('\n') + '\n');
await writeFile(join(out, 'score.json'), JSON.stringify(score, null, 2) + '\n');
console.log(JSON.stringify(score, null, 2));
if (score.xpGainedThisRun <= 0) process.exitCode = 2;
