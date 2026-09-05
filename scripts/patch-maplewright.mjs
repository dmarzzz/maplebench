import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(dirname(fileURLToPath(import.meta.url))), 'upstream/maplewright/crates/client/src');
const exporterPath = join(root, '../../wz/src/bin/wzskillfx.rs');
writeFileSync(exporterPath, readFileSync(new URL('./wzskillfx.rs', import.meta.url), 'utf8'));
function insert(file, anchor, code, marker) {
  const path = join(root, file);
  const text = readFileSync(path, 'utf8');
  if (text.includes(marker)) return;
  if (text.split(anchor).length !== 2) throw new Error(`Unexpected Maplewright source: ${file}`);
  writeFileSync(path, text.replace(anchor, code + anchor));
}

insert('lib.rs', '    pub fn framebuffer(&self) -> &[u32] {', `    /// Position a replay camera from an authoritative Cosmic observation. No simulation step.
    pub fn set_authoritative_position(&mut self, x: f64, y: f64) {
        self.b.x = x;
        self.b.y = y;
        let (cx, cy) = cam(x.round() as i32 + self.offx, y.round() as i32 + self.offy, self.fw, self.fh);
        self.camfx = cx as f64;
        self.camfy = cy as f64;
    }

`, 'pub fn set_authoritative_position');

insert('lib.rs', '    pub fn framebuffer(&self) -> &[u32] {', `    /// Set a presentation pose for an observed move or accepted attack in a replay.
    pub fn set_replay_pose(&mut self, stance: &str, frame: usize, facing: f64) {
        if self.chr.contains_key(stance) { self.stance = stance.to_string(); }
        self.frame = frame;
        self.facing = facing;
    }

`, 'pub fn set_replay_pose');

insert('lib.rs', '    pub fn framebuffer(&self) -> &[u32] {', `    /// Keep replay camera motion independent of the character's jump/knockback arc.
    pub fn set_replay_camera(&mut self, x: f64, y: f64) {
        let (cx, cy) = cam(x.round() as i32 + self.offx, y.round() as i32 + self.offy, self.fw, self.fh);
        self.camfx = cx as f64;
        self.camfy = cy as f64;
    }

`, 'pub fn set_replay_camera');

insert('lib.rs', '    pub fn framebuffer(&self) -> &[u32] {', `    /// Present an observed monster pose at an explicit animation phase. Does not move it.
    pub fn set_replay_mob_pose(&mut self, oid: i32, stance: &str, facing: f64, phase_ms: f64) {
        let Some(mob) = self.mobs.iter_mut().find(|m| m.oid == oid) else { return };
        let Some(set) = self.mob_art.get(&mob.mob_id) else { return };
        let chosen = [stance, "stand", "move", "fly"].into_iter()
            .find(|name| set.get(*name).is_some_and(|frames| !frames.is_empty()));
        let Some(chosen) = chosen else { return };
        let frames = &set[chosen];
        let total: f64 = frames.iter().map(|f| f.delay.max(1) as f64).sum();
        let mut remaining = if phase_ms.is_finite() { phase_ms.max(0.0) % total } else { 0.0 };
        let mut selected = 0;
        for (index, frame) in frames.iter().enumerate() {
            selected = index;
            if remaining < frame.delay.max(1) as f64 { break; }
            remaining -= frame.delay.max(1) as f64;
        }
        mob.stance = chosen.to_string();
        mob.facing = if facing < 0.0 { -1.0 } else { 1.0 };
        mob.frame = selected;
        mob.frame_ms = remaining;
    }

`, 'pub fn set_replay_mob_pose');

insert('lib.rs', '    pub fn framebuffer(&self) -> &[u32] {', `    /// Composite one original WZ effect frame over a completed authoritative replay.
    /// Origin and alpha are read from Skill.wz; this method never simulates combat.
    pub fn draw_replay_effect(&mut self, rgba: &[u8], w: i32, h: i32,
        x: f64, y: f64, ox: i32, oy: i32, flip: bool, alpha: u32, additive: bool) {
        let sx = (x + self.offx as f64).round() as i32 - self.camfx.round() as i32;
        let sy = (y + self.offy as f64).round() as i32 - self.camfy.round() as i32;
        let tlx = sx - if flip { w - ox } else { ox };
        let tly = sy - oy;
        for row in 0..h {
            let py = tly + row;
            if py < 0 || py >= VH as i32 { continue; }
            for col in 0..w {
                let px = tlx + col;
                if px < 0 || px >= VW as i32 { continue; }
                let src_x = if flip { w - 1 - col } else { col };
                let si = ((row * w + src_x) * 4) as usize;
                let a = (rgba[si + 3] as u32 * alpha.min(255) + 127) / 255;
                if a == 0 { continue; }
                let idx = py as usize * VW + px as usize;
                if additive {
                    let dst = self.fb[idx];
                    let channel = |shift: u32, value: u8| {
                        (((dst >> shift) & 255) + (value as u32 * a + 127) / 255).min(255)
                    };
                    self.fb[idx] = (channel(16, rgba[si]) << 16)
                        | (channel(8, rgba[si + 1]) << 8) | channel(0, rgba[si + 2]);
                } else {
                    blend(&mut self.fb, idx, rgba[si], rgba[si + 1], rgba[si + 2], a);
                }
            }
        }
    }

`, 'pub fn draw_replay_effect');

insert('main.rs', '    // ---- headless screenshot ----', `    // MapleBench replay: TSV snapshots contain only server-observed positions and HP.
    if let Some(i) = args.iter().position(|a| a == "--benchshot") {
        let snapshot = fs::read_to_string(&args[i + 1]).expect("read snapshot");
        let assetd = std::env::var("MAPLEBENCH_ASSETD").unwrap_or_else(|_| "127.0.0.1:8820".into());
        for line in snapshot.lines() {
            let c: Vec<&str> = line.split_whitespace().collect();
            if c.first() == Some(&"player") {
                game.set_authoritative_position(c[1].parse().unwrap(), c[2].parse().unwrap());
            } else if c.first() == Some(&"mob") {
                let oid: i32 = c[1].parse().unwrap();
                game.upsert_mob(oid, c[2].parse().unwrap(), c[3].parse().unwrap(), c[4].parse().unwrap(), 0);
                game.set_mob_hp(oid, c[5].parse().unwrap());
            }
        }
        for id in game.missing_mob_art() {
            let frames = fetch_mob(&assetd, id).expect("load monster art");
            game.add_mob_sprites(id, frames);
        }
        game.render();
        save_shot(&game.fb, &args[i + 2]);
        println!("server-state replay -> {}", args[i + 2]);
        return;
    }

`, 'server-state replay ->');

const mainPath = join(root, 'main.rs');
let main = readFileSync(mainPath, 'utf8');
if (!main.includes('game.set_replay_pose(c[3]')) {
  const anchor = '                game.set_authoritative_position(c[1].parse().unwrap(), c[2].parse().unwrap());';
  if (main.split(anchor).length !== 2) throw new Error('Unexpected snapshot renderer source');
  main = main.replace(anchor, anchor + '\n                if c.len() >= 6 { game.set_replay_pose(c[3], c[4].parse().unwrap(), c[5].parse().unwrap()); }');
  writeFileSync(mainPath, main);
}
if (!main.includes('game.set_replay_camera(c[1]')) {
  const anchor = '            } else if c.first() == Some(&"mob") {';
  if (main.split(anchor).length !== 2) throw new Error('Unexpected snapshot renderer source');
  main = main.replace(anchor, '            } else if c.first() == Some(&"camera") {\n                game.set_replay_camera(c[1].parse().unwrap(), c[2].parse().unwrap());\n' + anchor);
  writeFileSync(mainPath, main);
}
if (!main.includes('game.set_replay_mob_pose(c[1]')) {
  const anchor = '        game.render();\n        save_shot(&game.fb, &args[i + 2]);';
  if (main.split(anchor).length !== 2) throw new Error('Unexpected monster replay renderer source');
  main = main.replace(anchor, `        // Select each monster's WZ animation frame after its sprite set is loaded.
        for line in snapshot.lines() {
            let c: Vec<&str> = line.split_whitespace().collect();
            if c.first() == Some(&"mob") && c.len() >= 9 {
                game.set_replay_mob_pose(c[1].parse().unwrap(), c[6], c[7].parse().unwrap(), c[8].parse().unwrap());
            }
        }
` + anchor);
  writeFileSync(mainPath, main);
}
if (!main.includes('game.draw_replay_effect(')) {
  const anchor = '        save_shot(&game.fb, &args[i + 2]);';
  if (main.split(anchor).length !== 2) throw new Error('Unexpected skill-effect replay source');
  main = main.replace(anchor, `        // Effects are exported offline. Only frame basenames from the verified manifest
        // enter the TSV; there is no access to Skill.wz or the control API here.
        for line in snapshot.lines() {
            let c: Vec<&str> = line.split_whitespace().collect();
            if c.first() != Some(&"effect") { continue; }
            assert_eq!(c.len(), 9, "malformed skill-effect snapshot");
            assert!(c[1].ends_with(".png") && c[1].chars().all(|v| v.is_ascii_alphanumeric() || v == '_' || v == '.'), "invalid effect basename");
            assert!(!c[1].contains(".."), "invalid effect basename");
            let dir = std::env::var("MAPLEBENCH_SKILL_EFFECT_DIR").expect("effect bake missing");
            let bytes = fs::read(format!("{}/{}", dir, c[1])).expect("read effect frame");
            let (w, h, rgba) = decode_png(&bytes);
            game.draw_replay_effect(&rgba, w, h, c[2].parse().unwrap(), c[3].parse().unwrap(),
                c[4].parse().unwrap(), c[5].parse().unwrap(), c[6] == "1", c[7].parse().unwrap(), c[8] == "1");
        }
` + anchor);
  writeFileSync(mainPath, main);
}
const charPath = join(root, '../../wz/src/bin/wzchar.rs');
let chr = readFileSync(charPath, 'utf8');
if (!chr.includes('"swingO1", "swingO2"')) {
  const old = 'let stances = [look.stand(), look.walk(), "jump", "prone", "alert"];';
  if (!chr.includes(old)) throw new Error('Unexpected character exporter source');
  chr = chr.replace(old, 'let stances = [look.stand(), look.walk(), "jump", "prone", "alert", "swingO1", "swingO2", "swingO3", "stabO1", "stabO2"];');
  writeFileSync(charPath, chr);
}
if (!chr.includes('"swingT1", "swingT2"')) {
  const old = '"swingO1", "swingO2", "swingO3", "stabO1", "stabO2"';
  if (!chr.includes(old)) throw new Error('Unexpected character exporter source');
  chr = chr.replace(old, old + ', "swingT1", "swingT2", "swingT3", "stabT1", "stabT2"');
  writeFileSync(charPath, chr);
}
console.log('Maplewright authoritative-snapshot renderer installed.');
if (!chr.includes('"brandish1", "brandish2"')) {
  const old = '"swingT1", "swingT2", "swingT3", "stabT1", "stabT2"';
  if (!chr.includes(old)) throw new Error('Unexpected character exporter source for Brandish');
  chr = chr.replace(old, old + ', "brandish1", "brandish2"');
  writeFileSync(charPath, chr);
}

// Skill actions such as Brandish are WZ frame references, not body canvases.
const dollPath = join(root, '../../wz/src/paperdoll.rs');
let doll = readFileSync(dollPath, 'utf8');
if (!doll.includes('// MapleBench: resolve a WZ action-frame reference')) {
  const anchor = '        let body_img = self.image(&[&body_file])?.clone();';
  if (doll.split(anchor).length !== 2) throw new Error('Unexpected paper-doll action source');
  doll = doll.replace(anchor, anchor + `
        // MapleBench: resolve a WZ action-frame reference (Brandish's swing/stab sequence).
        // Only direct canvas destinations are supported, so malformed cycles cannot recurse.
        if let Some(node) = nav(&body_img, &[stance, &fkey]) {
            if let Some(WzValue::Str(action)) = child(node, "action") {
                let target_frame = child(node, "frame").and_then(int_of)?;
                let target_key = target_frame.to_string();
                canvas_at(&body_img, &[action.as_str(), &target_key, "body"])?;
                let delay = child(node, "delay").and_then(int_of).unwrap_or(120).saturating_abs().max(1);
                let mut rendered = self.render(look, action, target_frame)?;
                rendered.delay = delay;
                return Some(rendered);
            }
        }
`);
  writeFileSync(dollPath, doll);
}

if (!chr.includes('"alert2", "alert4"')) {
  const old = '"brandish1", "brandish2"';
  if (!chr.includes(old)) throw new Error('Unexpected character exporter source for buff actions');
  chr = chr.replace(old, old + ', "alert2", "alert4", "swingOF", "stabOF", "swingTF", "stabTF"');
  writeFileSync(charPath, chr);
}
if (!chr.includes('"alert3"')) {
  const old = '"alert2", "alert4"';
  if (!chr.includes(old)) throw new Error('Unexpected character exporter source for Maple Warrior');
  chr = chr.replace(old, old + ', "alert3"');
  writeFileSync(charPath, chr);
}

// A rear-facing swing must use the matching head layer. Otherwise the front head
// and face cover the WZ backCap/backHair layers and make the character look bald.
if (!doll.includes('fn maplebench_head_view')) {
  const headAnchor = '        let head_c = canvas_at(&head_img, &["front", "head"]).cloned();';
  const faceAnchor = '        if let Some(fimg) = &face_img {';
  const helperAnchor = 'fn alt_stance(s: &str) -> &\'static str {';
  if ([headAnchor, faceAnchor, helperAnchor].some(anchor => doll.split(anchor).length !== 2)) {
    throw new Error('Unexpected paper-doll front/back head source');
  }
  doll = doll.replace(headAnchor, `        let head_view = maplebench_head_view(resolve(&body_img, &[stance, &fkey]));
        let head_c = canvas_at(&head_img, &[head_view, "head"]).cloned();`);
  doll = doll.replace(faceAnchor, '        if let Some(fimg) = face_img.as_ref().filter(|_| head_view == "front") {');
  doll = doll.replace(helperAnchor, `// MapleBench: WZ face=0 denotes a view of the character's back, not a missing face.
// Brandish2 frame 3 delegates to swingTF/0, which explicitly carries this flag.
fn maplebench_head_view(body_frame: Option<&WzValue>) -> &'static str {
    if body_frame.and_then(|node| child(node, "face")).and_then(int_of) == Some(0) {
        "back"
    } else {
        "front"
    }
}

#[cfg(test)]
mod maplebench_head_tests {
    use super::*;

    #[test]
    fn rear_swing_uses_back_head_and_omits_front_face() {
        let frame = WzValue::Sub(vec![("face".into(), WzValue::Short(0))]);
        assert_eq!(maplebench_head_view(Some(&frame)), "back");
        let integer_flag = WzValue::Sub(vec![("face".into(), WzValue::Int(0))]);
        assert_eq!(maplebench_head_view(Some(&integer_flag)), "back");
    }

    #[test]
    fn front_and_unspecified_frames_keep_front_head() {
        let frame = WzValue::Sub(vec![("face".into(), WzValue::Short(1))]);
        assert_eq!(maplebench_head_view(Some(&frame)), "front");
        assert_eq!(maplebench_head_view(Some(&WzValue::Sub(vec![]))), "front");
        assert_eq!(maplebench_head_view(None), "front");
    }
}

` + helperAnchor);
  writeFileSync(dollPath, doll);
}
