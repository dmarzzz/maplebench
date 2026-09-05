"""Exercise the actual snapshot exporter without WZ files or a native renderer."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def mob(oid, x, y=167, **extra):
    return {"objectId": oid, "monsterId": 5110301, "position": {"x": x, "y": y},
            "hp": 100, "maxHp": 100, "alive": True, **extra}


@unittest.skipUnless(shutil.which("node"), "Node.js is required for the replay exporter")
class ReplayMonsterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="maplebench-replay-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        run = root / "run"
        map_dir, char_dir = root / "map", root / "character"
        for p in (run, map_dir, char_dir):
            p.mkdir()
        (map_dir / "map.fh").write_text("0 0 2048 1024\n")
        (char_dir / "char.txt").write_text("stand1 0 100\nwalk1 0 100\njump 0 100\nswingO1 0 100\n")
        c = {"mapId": 261020300, "position": {"x": 0, "y": 167}, "level": 130,
             "jobId": 112, "hp": 8000, "maxHp": 8000}
        observations = [
            {"nowMs": 0, "character": c, "monsterSimulation": "ground-patrol-v1", "monsters": [
                mob(1, 100, facingLeft=False, moving=True, movementMode="patrol"),
                mob(2, 200, facingLeft=True, moving=False, movementMode="idle"),
                mob(4, -50),
            ]},
            {"nowMs": 1000, "character": c, "monsterSimulation": "ground-patrol-v1", "monsters": [
                mob(1, 200, 267, facingLeft=True, moving=False, movementMode="blocked"),
                mob(3, 500, facingLeft=False, moving=True, movementMode="chase"),
                mob(4, 0),
            ]},
            {"nowMs": 2000, "character": c, "monsterSimulation": "ground-patrol-v1", "monsters": [
                mob(1, 200, 267, facingLeft=True, moving=False, movementMode="blocked"),
                mob(3, 600, facingLeft=False, moving=True, movementMode="chase"),
                mob(4, 0),
            ]},
        ]
        (run / "observations.json").write_text(json.dumps(observations))
        (run / "episode.jsonl").write_text('{"kind":"episode_start","tMs":0}\n')
        env = dict(os.environ, MAPLEBENCH_SNAPSHOTS_ONLY="true", MAPLEBENCH_MAP_DIR=str(map_dir),
                   MAPLEBENCH_CHARACTER_DIR=str(char_dir), MAPLEBENCH_MAP_ID="261020300")
        subprocess.run([shutil.which("node"), str(ROOT / "scripts/render-cosmic-clip.mjs"), str(run)],
                       check=True, env=env, capture_output=True, text=True, timeout=15)
        cls.out = run / "video"

    def frame(self, number):
        rows = [line.split() for line in (self.out / f"frame-{number:04d}.tsv").read_text().splitlines()]
        return {int(row[1]): row for row in rows if row[0] == "mob"}

    def test_interpolates_both_observed_coordinates_and_keeps_facing(self):
        m = self.frame(6)[1]  # 400 ms between observations at 0 and 1000.
        self.assertAlmostEqual(float(m[3]), 140)
        self.assertAlmostEqual(float(m[4]), 207)
        self.assertEqual(m[6:8], ["move", "1"])
        self.assertAlmostEqual(float(m[8]), 400)

    def test_does_not_extrapolate_a_missing_or_new_monster(self):
        before = self.frame(6)
        self.assertNotIn(3, before)
        self.assertEqual(float(before[2][3]), 200)
        self.assertEqual(before[2][6:8], ["stand", "-1"])
        after = self.frame(15)
        self.assertNotIn(2, after)
        self.assertEqual(float(after[3][3]), 500)
        self.assertEqual(float(after[3][8]), 0)

    def test_authoritative_stop_resets_pose_phase_and_updates_facing(self):
        at_stop = self.frame(15)[1]
        self.assertEqual(at_stop[6:8], ["stand", "-1"])
        self.assertEqual(float(at_stop[8]), 0)
        later = self.frame(21)[1]
        self.assertEqual(float(later[3]), 200)
        self.assertEqual(float(later[8]), 400)

    def test_legacy_trace_infers_only_observed_motion_and_remembers_facing(self):
        moving = self.frame(6)[4]
        self.assertEqual(float(moving[3]), -30)
        self.assertEqual(moving[6:8], ["move", "1"])
        stopped = self.frame(15)[4]
        self.assertEqual(stopped[6:8], ["stand", "1"])

    def test_overlay_identifies_benchmark_monster_simulation(self):
        self.assertIn("Ground-mob simulation", (self.out / "overlay.ass").read_text())

    def test_native_patch_installs_pose_after_art_loading_and_is_repeatable(self):
        with tempfile.TemporaryDirectory(prefix="maplebench-native-patch-test-") as name:
            root = Path(name)
            script = root / "scripts/patch-maplewright.mjs"
            script.parent.mkdir()
            shutil.copyfile(ROOT / "scripts/patch-maplewright.mjs", script)
            src = root / "upstream/maplewright/crates/client/src"
            src.mkdir(parents=True)
            lib = src / "lib.rs"
            main = src / "main.rs"
            lib.write_text("impl Game {\n    pub fn framebuffer(&self) -> &[u32] {\n    }\n}\n")
            main.write_text("fn main() {\n    // ---- headless screenshot ----\n}\n")
            character = root / "upstream/maplewright/crates/wz/src/bin/wzchar.rs"
            character.parent.mkdir(parents=True)
            character.write_text('let stances = [look.stand(), look.walk(), "jump", "prone", "alert"];\n')
            doll = root / "upstream/maplewright/crates/wz/src/paperdoll.rs"
            doll.write_text('        let body_img = self.image(&[&body_file])?.clone();\n')
            cmd = [shutil.which("node"), str(script)]
            subprocess.run(cmd, check=True, capture_output=True, timeout=10)
            expected = {p: p.read_text() for p in (lib, main, character, doll)}
            self.assertLess(expected[main].index("game.add_mob_sprites"),
                            expected[main].index("game.set_replay_mob_pose"))
            self.assertEqual(expected[main].count("game.set_replay_mob_pose"), 1)
            subprocess.run(cmd, check=True, capture_output=True, timeout=10)
            self.assertEqual(expected, {p: p.read_text() for p in expected})


@unittest.skipUnless(shutil.which("node"), "Node.js is required for the replay exporter")
class ReplayPlayerHpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="maplebench-hp-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        run, map_dir, char_dir = root / "run", root / "map", root / "character"
        for p in (run, map_dir, char_dir):
            p.mkdir()
        (map_dir / "map.fh").write_text("0 0 2048 1024\n")
        (char_dir / "char.txt").write_text("stand1 0 100\nwalk1 0 100\njump 0 100\nswingO1 0 100\n")
        c = {"id": 1, "mapId": 261020300, "position": {"x": 200, "y": 167},
             "level": 130, "jobId": 112, "hp": 8000, "maxHp": 8000}
        # Include enemy damage, recovery, a skill HP cost, and a new character.
        characters = [c, dict(c, hp=7500), dict(c, hp=7800), dict(c, hp=7784),
                      dict(c, id=2, hp=500), dict(c, id=2, hp=500)]
        observations = [{"nowMs": i * 1000, "character": character,
                         "monsters": [mob(1, 210, hp=100 if i == 0 else 50)]}
                        for i, character in enumerate(characters)]
        (run / "observations.json").write_text(json.dumps(observations))
        (run / "episode.jsonl").write_text(json.dumps({"kind": "action", "tMs": 2990,
            "accepted": True, "action": {"type": "use_skill", "skillId": 1001005}}) + "\n")
        env = dict(os.environ, MAPLEBENCH_SNAPSHOTS_ONLY="true", MAPLEBENCH_MAP_DIR=str(map_dir),
                   MAPLEBENCH_CHARACTER_DIR=str(char_dir), MAPLEBENCH_MAP_ID="261020300")
        subprocess.run([shutil.which("node"), str(ROOT / "scripts/render-cosmic-clip.mjs"), str(run)],
                       check=True, env=env, capture_output=True, text=True, timeout=15)
        cls.ass = (run / "video/overlay.ass").read_text()
        cls.rows = [line.split(",", 9) for line in cls.ass.splitlines() if line.startswith("Dialogue:")]

    def test_player_hp_loss_is_visible_at_observation_time_and_distinct_from_monster_damage(self):
        hits = [r for r in self.rows if r[3] == "PlayerHP" and r[9].endswith("-500 HP")]
        self.assertTrue(hits)
        self.assertEqual(hits[0][1], "0:00:01.00")
        self.assertIn(r"\c&H7070FF&", hits[0][9])
        self.assertTrue(any(r[3] == "Damage" and r[9].endswith("-50 HP") for r in self.rows))
        self.assertIn("HP LOSS -500", self.ass)

    def test_recovery_is_green_and_does_not_become_damage(self):
        restored = [r for r in self.rows if r[3] == "PlayerHP" and r[9].endswith("+300 HP")]
        self.assertTrue(restored)
        self.assertEqual(restored[0][1], "0:00:02.00")
        self.assertIn(r"\c&H8DEA91&", restored[0][9])
        self.assertNotIn("-300 HP", self.ass)
        self.assertIn("HP RESTORED +300", self.ass)

    def test_hud_keeps_hp_discrete_and_does_not_invent_an_attacker_for_skill_costs(self):
        before = [r[9] for r in self.rows if r[1] == "0:00:00.93" and "PLAYER HP" in r[9]]
        after = [r[9] for r in self.rows if r[1] == "0:00:01.00" and "PLAYER HP" in r[9]]
        self.assertEqual(len(before), 1)
        self.assertEqual(len(after), 1)
        self.assertIn("8000 / 8000", before[0])
        self.assertIn("7500 / 8000", after[0])
        self.assertIn("HP LOSS -16", self.ass)
        self.assertNotIn("MONSTER HIT", self.ass)
        self.assertIn("HP labels: observed changes", self.ass)

    def test_character_switch_does_not_generate_a_false_hp_loss(self):
        self.assertNotIn("-7284 HP", self.ass)
        self.assertNotIn("HP LOSS -7284", self.ass)
        at_switch = [r for r in self.rows if r[1] == "0:00:04.00"]
        self.assertFalse(any(r[3] == "PlayerHP" for r in at_switch))
        self.assertFalse(any("HP LOSS" in r[9] for r in at_switch))


if __name__ == "__main__":
    unittest.main()
