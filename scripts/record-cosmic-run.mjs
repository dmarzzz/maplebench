// Read-only recorder: actions are chosen and submitted separately by the operator.
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { HttpMapleTransport, MapleClient } from '../dist/src/sdk.js';
import { totalXp } from '../dist/src/scoring.js';

const url = process.env.MAPLEBENCH_URL || 'http://127.0.0.1:8790';
const out = process.env.MAPLEBENCH_OUTPUT || 'artifacts/operator-run';
const duration = Number(process.env.MAPLEBENCH_DURATION_MS || 90000);
if (!Number.isFinite(duration) || duration < 1000 || duration > 600000) throw new Error('Invalid duration');
const health = await (await fetch(url + '/health')).json();
if (health.backend !== 'cosmic-v83') throw new Error('Requires the real Cosmic backend');
await mkdir(out, { recursive: true });
const controller = {
  name: process.env.MAPLEBENCH_CONTROLLER || 'External operator',
  model: process.env.MAPLEBENCH_MODEL || 'Unspecified',
  mode: 'external-actions; recorder performs no actions',
};
await writeFile(join(out, 'controller.json'), JSON.stringify(controller, null, 2) + '\n');
const client = new MapleClient(new HttpMapleTransport(url));
const snapshots = [], started = Date.now();
const initialEvents = await client.events(0);
console.log('Recording observations without issuing actions');
while (Date.now() - started < duration) {
  const observation = await client.observe();
  snapshots.push(observation);
  // End once all initially spawned monsters have died, retaining a brief final hold.
  if (snapshots[0].monsters.length && !observation.monsters.some(m => m.alive)) {
    await new Promise(r => setTimeout(r, 1200));
    snapshots.push(await client.observe());
    break;
  }
  await new Promise(r => setTimeout(r, 100));
}
const events = await client.events(0);
const score = {
  backend: health.backend, controller,
  durationMs: Date.now() - started,
  xpGainedThisRun: totalXp(events) - totalXp(initialEvents),
  finalExp: snapshots.at(-1).character.exp,
  alive: snapshots.at(-1).character.alive,
};
await writeFile(join(out, 'observations.json'), JSON.stringify(snapshots, null, 2) + '\n');
await writeFile(join(out, 'episode.jsonl'), events.map(e => JSON.stringify(e)).join('\n') + '\n');
await writeFile(join(out, 'score.json'), JSON.stringify(score, null, 2) + '\n');
console.log(JSON.stringify(score, null, 2));
