import { HttpMapleTransport, MapleClient } from '../dist/src/sdk.js';

const baseUrl = process.env.MAPLEBENCH_URL || 'http://127.0.0.1:8790';
const client = new MapleClient(new HttpMapleTransport(baseUrl));

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

console.log('demo agent connected:', baseUrl);
for (let step = 0; step < 18; step++) {
  const obs = await client.observe();
  const living = obs.monsters.filter(m => m.alive);
  if (!living.length) { await sleep(150); continue; }
  living.sort((a,b) => Math.hypot(a.position.x-obs.character.position.x, a.position.y-obs.character.position.y) - Math.hypot(b.position.x-obs.character.position.x, b.position.y-obs.character.position.y));
  const target = living[0];
  const dist = Math.hypot(target.position.x-obs.character.position.x, target.position.y-obs.character.position.y);
  if (dist > 190) {
    const result = await client.moveTo({ x:target.position.x, y:target.position.y });
    console.log(step, 'move', target.objectId, result.accepted);
  } else {
    const result = step > 5 ? await client.useSkill(1001005, target.objectId) : await client.attack(target.objectId);
    console.log(step, step > 5 ? 'skill' : 'attack', target.objectId, result.accepted, result.error || '');
  }
  await sleep(350);
}

const events = await client.events(0);
const xp = events.filter(e => e.kind === 'xp_gain').reduce((sum,e) => sum + e.amount, 0);
console.log(`done: ${xp} XP, ${events.length} events`);
