import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(dirname(fileURLToPath(import.meta.url))), 'upstream/maplewright/crates/client/src');
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
