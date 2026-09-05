// A narrow presentation layer over accepted server events and exported Skill.wz art.
// Unknown effects remain absent; action requests alone never create an animation.
const castSkills = new Set([1111002, 1101004, 1101006, 1121002, 1121000]);
export function parseSkillEffects(text) {
  if (!text.startsWith('# maplebench-skill-fx-v1 Skill.wz\n')) throw new Error('Unrecognized skill effect provenance');
  const effects = new Map();
  for (const line of text.split('\n').filter(line => line && !line.startsWith('#'))) {
    const [skill, path, index, delay, file, ox, oy, a0, a1, blend, source, ...extra] = line.split(/\s+/);
    const numbers = [skill, index, delay, ox, oy, a0, a1, blend].map(Number);
    if (extra.length || numbers.some(n => !Number.isSafeInteger(n)) || Number(delay) <= 0
        || !/^[0-9]+_effect(?:_[01])?_[0-9]+\.png$/.test(file)
        || ![0, 1].includes(Number(blend)) || [a0, a1].some(a => Number(a) < 0 || Number(a) > 255)
        || !['effect', 'effect/0', 'effect/1'].includes(path)
        || source !== `${Math.floor(Number(skill) / 10000)}.img/skill/${skill}/${path}/${index}`) {
      throw new Error('Invalid Skill.wz effect manifest row');
    }
    const key = `${skill}/${path}`;
    const frames = effects.get(key) || [];
    if (Number(index) !== frames.length) throw new Error('Skill effect frames are not contiguous');
    frames.push({index: Number(index), delay: Number(delay), file, ox: Number(ox), oy: Number(oy),
      a0: Number(a0), a1: Number(a1), blend: Number(blend), source});
    effects.set(key, frames);
  }
  return effects;
}

export function effectKey(event) {
  if (event.kind === 'combat_attack' && event.skillId === 1121008) {
    if (event.actionName === 'brandish1') return '1121008/effect/0';
    if (event.actionName === 'brandish2') return '1121008/effect/1';
  }
  if (event.kind === 'skill_cast' && castSkills.has(event.skillId)) return `${event.skillId}/effect`;
  return undefined;
}

export function skillEffectFrame(effects, event, elapsedMs) {
  const key = effectKey(event), frames = effects.get(key);
  if (!frames || !Number.isFinite(elapsedMs) || elapsedMs < 0) return undefined;
  // Same rate conversion as Cosmic BotAttackTiming. The event records effective
  // speed, including Booster; never stretch an entire effect to the attack cooldown.
  const recordedSpeed = Number.isInteger(event.speed) ? (event.speed <= 0 ? 4 : event.speed) : undefined;
  const factor = recordedSpeed === undefined ? 1 : 1.7 - recordedSpeed / 10;
  const speed = factor > 0 ? factor : 1;
  let remaining = elapsedMs * speed;
  for (const frame of frames) {
    if (remaining < frame.delay) return {...frame, key, alpha: Math.round(frame.a0 + (frame.a1 - frame.a0) * remaining / frame.delay)};
    remaining -= frame.delay;
  }
  return undefined; // One shot: never loop an expired cast.
}
