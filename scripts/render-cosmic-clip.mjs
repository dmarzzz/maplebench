import { readFile, writeFile, mkdir, readdir, unlink, rename } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { promisify } from 'node:util';
import { execFile } from 'node:child_process';

const run = promisify(execFile);
const work = resolve(process.env.MAPLEBENCH_WORK || '..');
const charDir = resolve(process.env.MAPLEBENCH_CHARACTER_DIR || join(work, 'baked/warrior'));
const mapDir = resolve(process.env.MAPLEBENCH_MAP_DIR || join(work, 'baked/henesys'));
const mapId = Number(process.env.MAPLEBENCH_MAP_ID || 100000000);
const mapName = process.env.MAPLEBENCH_MAP_NAME || 'Henesys';
const fixtureLabel = process.env.MAPLEBENCH_FIXTURE_LABEL || 'Town combat fixture';
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
if (observations.length < 2 || observations.some(o => o.character.mapId !== mapId)) throw new Error('Replay map does not match the selected bake');
const start = observations[0].nowMs;
const end = observations.at(-1).nowMs;
const actions = events.filter(e => e.kind === 'action' && e.accepted && e.tMs >= start);
const frames = Math.ceil((end - start) * fps / 1000);
const [offx, offy, mapWidth, mapHeight] = (await readFile(join(mapDir, 'map.fh'), 'utf8')).split('\n')[0].split(/\s+/).map(Number);
const cameraY = observations[0].character.position.y;
const monsterSimulation = observations.some(o => o.monsterSimulation === 'ground-patrol-v1')
  ? ' / Ground-mob simulation' : '';
let cameraX = observations[0].character.position.x;
const damage = [];
const playerHpChanges = [];
for (let i = 1; i < observations.length; i++) {
  const before = observations[i - 1], after = observations[i];
  // These are observed HP deltas, not damage rolls or source attribution. Skill
  // HP costs and damage/healing within one sample interval can affect the delta.
  const hpDelta = after.character.hp - before.character.hp;
  if (before.character.id === after.character.id && Number.isFinite(hpDelta) && hpDelta !== 0) {
    playerHpChanges.push({ tMs: after.nowMs, characterId: after.character.id, ...after.character.position, delta: hpDelta });
  }
  for (const mob of before.monsters.filter(m => m.alive)) {
    const current = after.monsters.find(m => m.objectId === mob.objectId);
    const killed = !current && events.some(e => e.kind === 'xp_gain' && e.tMs > before.nowMs && e.tMs <= after.nowMs);
    const hpLoss = current ? mob.hp - current.hp : killed ? mob.hp : 0;
    if (hpLoss > 0) {
      const hitPosition = current?.position || mob.position;
      damage.push({ tMs: after.nowMs, x: hitPosition.x, y: hitPosition.y, amount: hpLoss });
    }
  }
}
const animations = {};
for (const line of (await readFile(join(charDir, 'char.txt'), 'utf8')).trim().split('\n')) {
  const [stance, index, delay] = line.split(/\s+/);
  (animations[stance] ||= []).push({ index: Number(index), delay: Number(delay) });
}
const standPose = animations.stand1 ? 'stand1' : 'stand2';
const walkPose = animations.walk1 ? 'walk1' : 'walk2';
// wzchar normalizes stand2/walk2 to stand1/walk1; choose weapon stance explicitly.
const attackPose = process.env.MAPLEBENCH_ATTACK_POSE || (/crusader|hero/i.test(charDir) ? 'swingT1' : 'swingO1');
if (!animations[attackPose]?.length) throw new Error('Selected weapon attack pose is missing');
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
  'Style: PlayerHP,DejaVu Sans,30,&H007070FF,&H00FFFFFF,&H00151030,&H90000000,-1,0,0,0,100,100,0,0,1,2,1,5,0,0,0,1',
  'Style: HealthHUD,DejaVu Sans,16,&H00FFFFFF,&H00FFFFFF,&H00201912,&H90201912,-1,0,0,0,100,100,0,0,1,1,0,7,0,0,0,1',
  '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text'];
let facing = 1;
const mobPoses = new Map();
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
  const selectedAttackPose = action?.action.skillId === 1121008 && animations.brandish1 ? 'brandish1' : attackPose;
  const stance = attacking ? selectedAttackPose : y < cameraY - 3 ? 'jump' : moving ? walkPose : standPose;
  const pose = frameAt(stance, attacking ? t - action.tMs : t - start);
  const lines = [`player ${x.toFixed(2)} ${y.toFixed(2)} ${stance} ${pose} ${facing}`, `camera ${cameraX.toFixed(2)} ${cameraY}`];
  for (const m of a.monsters.filter(m => m.alive)) {
    // Interpolate only an existing monster's two observed positions. A spawn/death
    // boundary has no second position and must never create an invented path.
    const nextMob = b.monsters.find(n => n.objectId === m.objectId && n.monsterId === m.monsterId && n.alive);
    const nextPosition = nextMob?.position || m.position;
    const dx = nextPosition.x - m.position.x, dy = nextPosition.y - m.position.y;
    const mx = m.position.x + dx * alpha, my = m.position.y + dy * alpha;
    const key = `${m.objectId}:${m.monsterId}`;
    const lastPose = mobPoses.get(key);
    const previous = lastPose?.lastFrame === i - 1 ? lastPose : undefined;
    // New traces explicitly distinguish locomotion from knockback or a blocked mob.
    // Older recordings can only infer locomotion/facing from observed displacement.
    const mobMoving = typeof m.moving === 'boolean' ? m.moving : Math.hypot(dx, dy) > 0.5;
    const mobFacing = typeof m.facingLeft === 'boolean' ? (m.facingLeft ? -1 : 1)
      : Math.abs(dx) > 0.5 ? Math.sign(dx) : previous?.facing || -1;
    const mobStance = mobMoving ? 'move' : 'stand';
    const phaseStart = previous?.stance === mobStance ? previous.phaseStart : t;
    mobPoses.set(key, { stance: mobStance, facing: mobFacing, phaseStart, lastFrame: i });
    lines.push(`mob ${m.objectId} ${m.monsterId} ${mx.toFixed(2)} ${my.toFixed(2)} ${Math.max(1, Math.ceil(100 * m.hp / m.maxHp))} ${mobStance} ${mobFacing} ${(t - phaseStart).toFixed(2)}`);
  }
  await writeFile(join(out, `frame-${String(i).padStart(4, '0')}.tsv`), lines.join('\n') + '\n');
  const xp = events.filter(e => e.kind === 'xp_gain' && e.tMs >= start && e.tMs <= t).reduce((s, e) => s + e.amount, 0);
  const attackName = action?.action.type === 'use_skill'
    ? ({ 1001004: 'POWER STRIKE', 1001005: 'SLASH BLAST', 1111008: 'SHOUT', 1121008: 'BRANDISH' }[action.action.skillId] || `SKILL ${action.action.skillId}`)
    : 'BASIC ATTACK';
  const label = attacking ? attackName : moving ? (facing > 0 ? 'MOVE RIGHT' : 'MOVE LEFT') : 'OBSERVE';
  const job = ({ 100: 'Warrior', 110: 'Fighter', 111: 'Crusader', 112: 'Hero' })[a.character.jobId] || `Job ${a.character.jobId}`;
  const hud = `MAPLEBENCH  /  ${hudText(mapName).toUpperCase()}\\NModel: ${hudText(controller.model)}\\NController: ${hudText(controller.name)}\\NLv ${a.character.level} ${job}   HP ${a.character.hp}/${a.character.maxHp}   XP +${xp}\\N${label}   |   ${((t - start) / 1000).toFixed(1)}s`;
  ass.push(`Dialogue: 0,${stamp(i * 1000 / fps)},${stamp((i + 1) * 1000 / fps)},HUD,,0,0,0,,${hud}`);
  const recentHpChange = playerHpChanges.findLast(h => h.characterId === a.character.id && h.tMs <= t && t - h.tMs < 1400);
  const hpColor = recentHpChange?.delta < 0 ? '7070FF' : '8DEA91';
  const hpFraction = Math.max(0, Math.min(1, a.character.hp / Math.max(1, a.character.maxHp)));
  const healthRow = text => ass.push(`Dialogue: 2,${stamp(i * 1000 / fps)},${stamp((i + 1) * 1000 / fps)},HealthHUD,,0,0,0,,${text}`);
  healthRow('{\\pos(552,518)\\p1\\bord0\\c&H201912&\\alpha&H30&}m 0 0 l 228 0 228 72 0 72');
  healthRow(`{\\pos(562,526)}PLAYER HP   ${a.character.hp} / ${a.character.maxHp}`);
  healthRow('{\\pos(562,549)\\p1\\bord0\\c&H5B5050&}m 0 0 l 208 0 208 9 0 9');
  if (hpFraction > 0) healthRow(`{\\pos(562,549)\\p1\\bord0\\c&H${hpColor}&}m 0 0 l ${(208 * hpFraction).toFixed(1)} 0 ${(208 * hpFraction).toFixed(1)} 9 0 9`);
  const hpStatus = recentHpChange
    ? `${recentHpChange.delta < 0 ? 'HP LOSS' : 'HP RESTORED'} ${recentHpChange.delta > 0 ? '+' : ''}${recentHpChange.delta}`
    : 'Recorded server HP';
  healthRow(`{\\pos(562,567)\\fs14\\c&H${recentHpChange ? hpColor : 'FFFFFF'}&}${hpStatus}`);
  for (const hit of damage.filter(d => t >= d.tMs && t - d.tMs < 850)) {
    const age = t - hit.tMs;
    const dx = Math.round((hit.x + offx - camx) * 800 / 1024);
    const dy = Math.round((hit.y + offy - camy - 68 - age * 0.035) * 600 / 768);
    const alpha = Math.round(Math.max(0, (age - 500) / 350) * 255).toString(16).padStart(2, '0');
    ass.push(`Dialogue: 1,${stamp(i * 1000 / fps)},${stamp((i + 1) * 1000 / fps)},Damage,,0,0,0,,{\\pos(${dx},${dy})\\alpha&H${alpha}&}-${hit.amount} HP`);
  }
  for (const change of playerHpChanges.filter(h => h.characterId === a.character.id && t >= h.tMs && t - h.tMs < 1100)) {
    const age = t - change.tMs;
    const px = Math.round((change.x + offx - camx) * 800 / 1024);
    const py = Math.round((change.y + offy - camy - 88 - age * 0.04) * 600 / 768);
    const alpha = Math.round(Math.max(0, (age - 750) / 350) * 255).toString(16).padStart(2, '0');
    const color = change.delta < 0 ? '7070FF' : '8DEA91';
    ass.push(`Dialogue: 3,${stamp(i * 1000 / fps)},${stamp((i + 1) * 1000 / fps)},PlayerHP,,0,0,0,,{\\pos(${px},${py})\\c&H${color}&\\alpha&H${alpha}&}${change.delta > 0 ? '+' : ''}${change.delta} HP`);
  }
}
ass.push(`Dialogue: 0,${stamp(0)},${stamp(frames * 1000 / fps)},HUD,,0,0,0,,{\\an1\\fs14}Cosmic server run / Maplewright replay\\N${hudText(fixtureLabel)}${monsterSimulation}\\NInterpolated movement and presentation poses\\NHP labels: observed changes`);
await writeFile(join(out, 'overlay.ass'), ass.join('\n') + '\n');
if (process.env.MAPLEBENCH_SNAPSHOTS_ONLY === 'true') {
  console.log('Replay snapshots ready:', out);
} else {
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
    await run(process.env.MAPLEBENCH_RENDER_CLIENT || join(work, 'maplewright/target/release/client'), [join(mapDir, 'fg.png'), join(mapDir, 'map.fh'), mapDir, charDir, '--benchshot', join(out, name + '.tsv'), join(out, name + '.png')], { maxBuffer: 1024 * 1024 });
    if (++done % 30 === 0) console.log(`Rendered ${done}/${frames}`);
  }
}));
await run('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', String(fps), '-i', join(out, 'frame-%04d.png'), '-c:v', 'libx264', '-threads', '2', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', join(out, 'henesys-first.tmp.mp4')]);
await rename(join(out,'henesys-first.tmp.mp4'),join(out,'henesys-first.mp4'));
console.log('First clip ready:', join(out, 'henesys-first.mp4'));
}
await run('ffmpeg', ['-y', '-loglevel', 'error', '-i', join(out, 'henesys-first.mp4'), '-vf', 'ass=overlay.ass', '-c:v', 'libx264', '-threads', '2', '-preset', 'fast', '-crf', '22', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', join(out, 'henesys-overlay.tmp.mp4')], { cwd: out });
await rename(join(out,'henesys-overlay.tmp.mp4'),join(out,'henesys-overlay.mp4'));
console.log('Overlay clip ready:', join(out, 'henesys-overlay.mp4'));

if (process.env.MAPLEBENCH_KEEP_FRAMES === 'false') {
  for (const file of await readdir(out)) {
    if (/^frame-\d+\.(png|tsv)$/.test(file)) await unlink(join(out, file));
  }
}
}
