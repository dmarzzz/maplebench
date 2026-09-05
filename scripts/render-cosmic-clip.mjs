import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { promisify } from 'node:util';
import { execFile } from 'node:child_process';

const run = promisify(execFile);
const work = resolve(process.env.MAPLEBENCH_WORK || '..');
const input = resolve(process.argv[2] || 'artifacts/henesys-demo');
const out = join(input, 'video');
const fps = 15;
await mkdir(out, { recursive: true });
const observations = JSON.parse(await readFile(join(input, 'observations.json'), 'utf8'));
const events = (await readFile(join(input, 'episode.jsonl'), 'utf8')).trim().split('\n').filter(Boolean).map(JSON.parse);
const controller = JSON.parse(await readFile(join(input, 'controller.json'), 'utf8').catch(() => JSON.stringify({
  name: 'Nearest-monster scripted baseline', model: 'None (scripted policy)',
})));
const hudText = value => String(value).replace(/[{}\\\r\n]/g, ' ');
if (observations.some(o => o.character.mapId !== 100000000)) throw new Error('This renderer expects Henesys observations');
const start = observations[0].nowMs;
const end = observations.at(-1).nowMs;
const actions = events.filter(e => e.kind === 'action' && e.accepted && e.tMs >= start);
const frames = Math.ceil((end - start) * fps / 1000);
const [offx, offy, mapWidth, mapHeight] = (await readFile(join(work, 'baked/henesys/map.fh'), 'utf8')).split('\n')[0].split(/\s+/).map(Number);
const cameraY = observations[0].character.position.y;
let cameraX = observations[0].character.position.x;
const damage = [];
for (let i = 1; i < observations.length; i++) {
  const before = observations[i - 1], after = observations[i];
  for (const mob of before.monsters.filter(m => m.alive)) {
    const current = after.monsters.find(m => m.objectId === mob.objectId);
    const killed = !current && events.some(e => e.kind === 'xp_gain' && e.tMs > before.nowMs && e.tMs <= after.nowMs);
    const hpLoss = current ? mob.hp - current.hp : killed ? mob.hp : 0;
    if (hpLoss > 0) damage.push({ tMs: after.nowMs, x: mob.position.x, y: mob.position.y, amount: hpLoss });
  }
}
const animations = {};
for (const line of (await readFile(join(work, 'baked/warrior/char.txt'), 'utf8')).trim().split('\n')) {
  const [stance, index, delay] = line.split(/\s+/);
  (animations[stance] ||= []).push({ index: Number(index), delay: Number(delay) });
}
function frameAt(stance, time) {
  const fs = animations[stance];
  let remaining = time % fs.reduce((s, f) => s + f.delay, 0);
  for (const f of fs) { if (remaining < f.delay) return f.index; remaining -= f.delay; }
  return 0;
}
function stamp(ms) {
  return `${Math.floor(ms / 3600000)}:${String(Math.floor(ms / 60000) % 60).padStart(2, '0')}:${(ms / 1000 % 60).toFixed(2).padStart(5, '0')}`;
}
const ass = ['[Script Info]', 'ScriptType: v4.00+', 'PlayResX: 800', 'PlayResY: 600', '[V4+ Styles]',
  'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
  'Style: HUD,DejaVu Sans,19,&H00FFFFFF,&H00FFFFFF,&H00201912,&H90201912,-1,0,0,0,100,100,0,0,3,7,0,7,20,20,16,1',
  'Style: Damage,DejaVu Sans,28,&H0047CAFF,&H00FFFFFF,&H00172954,&H90000000,-1,0,0,0,100,100,0,0,1,2,1,5,0,0,0,1',
  '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text'];
let facing = 1;
for (let i = 0; i < frames; i++) {
  const t = start + i * 1000 / fps;
  let k = observations.findLastIndex(o => o.nowMs <= t);
  k = Math.max(0, k);
  const a = observations[k], b = observations[Math.min(k + 1, observations.length - 1)];
  const alpha = Math.max(0, Math.min(1, (t - a.nowMs) / Math.max(1, b.nowMs - a.nowMs)));
  const p = a.character.position, q = b.character.position;
  const x = p.x + (q.x - p.x) * alpha, y = p.y + (q.y - p.y) * alpha;
  cameraX += (x - cameraX) * (1 - Math.exp(-5 / fps));
  const camx = Math.max(0, Math.min(mapWidth - 1024, Math.round(cameraX) + offx - 512));
  const camy = Math.max(0, Math.min(mapHeight - 768, Math.round(cameraY) + offy - 384));
  const moving = Math.abs(q.x - p.x) > 1;
  if (moving) facing = Math.sign(q.x - p.x);
  const action = actions.findLast(e => e.tMs <= t);
  const attacking = action && ['basic_attack', 'use_skill'].includes(action.action.type) && t - action.tMs < 800;
  if (attacking) {
    const target = a.monsters.find(m => m.objectId === action.action.targetId);
    if (target && target.position.x !== x) facing = Math.sign(target.position.x - x);
  }
  const stance = attacking ? 'swingO1' : y < cameraY - 3 ? 'jump' : moving ? 'walk1' : 'stand1';
  const pose = frameAt(stance, attacking ? t - action.tMs : t - start);
  const lines = [`player ${x.toFixed(2)} ${y.toFixed(2)} ${stance} ${pose} ${facing}`, `camera ${cameraX.toFixed(2)} ${cameraY}`];
  for (const m of a.monsters.filter(m => m.alive)) {
    lines.push(`mob ${m.objectId} ${m.monsterId} ${m.position.x} ${m.position.y} ${Math.max(1, Math.ceil(100 * m.hp / m.maxHp))}`);
  }
  await writeFile(join(out, `frame-${String(i).padStart(4, '0')}.tsv`), lines.join('\n') + '\n');
  const xp = events.filter(e => e.kind === 'xp_gain' && e.tMs >= start && e.tMs <= t).reduce((s, e) => s + e.amount, 0);
  const attackName = action?.action.type === 'use_skill'
    ? ({ 1001004: 'POWER STRIKE', 1001005: 'SLASH BLAST' }[action.action.skillId] || `SKILL ${action.action.skillId}`)
    : 'BASIC ATTACK';
  const label = attacking ? attackName : moving ? (facing > 0 ? 'MOVE RIGHT' : 'MOVE LEFT') : 'OBSERVE';
  const job = ({ 100: 'Warrior', 110: 'Fighter', 111: 'Crusader', 112: 'Hero' })[a.character.jobId] || `Job ${a.character.jobId}`;
  const hud = `MAPLEBENCH  /  HENESYS\\NModel: ${hudText(controller.model)}\\NController: ${hudText(controller.name)}\\NLv ${a.character.level} ${job}   HP ${a.character.hp}/${a.character.maxHp}   XP +${xp}\\N${label}   |   ${((t - start) / 1000).toFixed(1)}s`;
  ass.push(`Dialogue: 0,${stamp(i * 1000 / fps)},${stamp((i + 1) * 1000 / fps)},HUD,,0,0,0,,${hud}`);
  for (const hit of damage.filter(d => t >= d.tMs && t - d.tMs < 850)) {
    const age = t - hit.tMs;
    const dx = Math.round((hit.x + offx - camx) * 800 / 1024);
    const dy = Math.round((hit.y + offy - camy - 68 - age * 0.035) * 600 / 768);
    const alpha = Math.round(Math.max(0, (age - 500) / 350) * 255).toString(16).padStart(2, '0');
    ass.push(`Dialogue: 1,${stamp(i * 1000 / fps)},${stamp((i + 1) * 1000 / fps)},Damage,,0,0,0,,{\\pos(${dx},${dy})\\alpha&H${alpha}&}-${hit.amount} HP`);
  }
}
ass.push(`Dialogue: 0,${stamp(0)},${stamp(frames * 1000 / fps)},HUD,,0,0,0,,{\\an1\\fs14}Cosmic server run / Maplewright replay\\NHenesys test slimes / interpolated movement and attack poses`);
await writeFile(join(out, 'overlay.ass'), ass.join('\n') + '\n');
if (process.env.MAPLEBENCH_OVERLAY_ONLY !== 'true') {
// Warm each monster's asset cache serially: the upstream asset service does not
// serialize concurrent first-time exports and can expose a partially written PNG.
const monsterIds = [...new Set(observations.flatMap(o => o.monsters.map(m => m.monsterId)))];
const assetHost = process.env.MAPLEBENCH_ASSETD || '127.0.0.1:8820';
for (const id of monsterIds) {
  const response = await fetch(`http://${assetHost}/mob/${id}/index.txt`);
  if (!response.ok) throw new Error(`Monster export failed: ${response.status}`);
  await response.text();
}
let next = 0, done = 0;
await Promise.all(Array.from({ length: 4 }, async () => {
  while (next < frames) {
    const i = next++, name = `frame-${String(i).padStart(4, '0')}`;
    await run(join(work, 'maplewright/target/release/client'), [join(work, 'baked/henesys/fg.png'), join(work, 'baked/henesys/map.fh'), join(work, 'baked/henesys'), join(work, 'baked/warrior'), '--benchshot', join(out, name + '.tsv'), join(out, name + '.png')], { maxBuffer: 1024 * 1024 });
    if (++done % 30 === 0) console.log(`Rendered ${done}/${frames}`);
  }
}));
await run('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', String(fps), '-i', join(out, 'frame-%04d.png'), '-c:v', 'libx264', '-threads', '2', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', join(out, 'henesys-first.mp4')]);
console.log('First clip ready:', join(out, 'henesys-first.mp4'));
}
await run('ffmpeg', ['-y', '-loglevel', 'error', '-i', join(out, 'henesys-first.mp4'), '-vf', 'ass=overlay.ass', '-c:v', 'libx264', '-threads', '2', '-preset', 'fast', '-crf', '22', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', join(out, 'henesys-overlay.mp4')], { cwd: out });
console.log('Overlay clip ready:', join(out, 'henesys-overlay.mp4'));
