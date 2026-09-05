"""Accepted-event provenance, WZ timing, and optional replay effect integration."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = """# maplebench-skill-fx-v1 Skill.wz
1121008 effect/1 0 120 1121008_effect_1_0.png 30 23 255 255 0 112.img/skill/1121008/effect/1/0
1121008 effect/1 1 120 1121008_effect_1_1.png 49 81 255 0 0 112.img/skill/1121008/effect/1/1
1111002 effect 0 1000 1111002_effect_0.png 84 131 255 0 0 111.img/skill/1111002/effect/0
"""


@unittest.skipUnless(shutil.which("node"), "Node.js required")
class SkillEffectsTest(unittest.TestCase):
    def helper(self, expression, manifest=MANIFEST):
        source = ("import {parseSkillEffects,skillEffectFrame,effectKey} from "
                  + json.dumps((ROOT / "scripts/replay-skill-effects.mjs").as_uri()) + ";\n"
                  + "const effects=parseSkillEffects(" + json.dumps(manifest) + ");\n"
                  + "console.log(JSON.stringify(" + expression + "));")
        return subprocess.run([shutil.which("node"), "--input-type=module", "-e", source],
                              check=False, capture_output=True, text=True, timeout=10)

    def test_only_accepted_event_types_choose_known_effects(self):
        result = self.helper("[effectKey({kind:'action',accepted:true,skillId:1121008,actionName:'brandish2'})??null,"
                             "effectKey({kind:'combat_attack',skillId:1111003,actionName:'swingTF'})??null,"
                             "effectKey({kind:'combat_attack',skillId:1121008,actionName:'brandish2'})]")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [None, None, "1121008/effect/1"])

    def test_speed_uses_recorded_booster_adjusted_rate_and_wz_alpha(self):
        # Speed 2 => 1.5x. At 120ms the WZ timeline is 180ms: halfway through frame 1.
        result = self.helper("skillEffectFrame(effects,{kind:'combat_attack',skillId:1121008,actionName:'brandish2',speed:2,cooldownMs:9999},120)")
        self.assertEqual(result.returncode, 0, result.stderr)
        frame = json.loads(result.stdout)
        self.assertEqual((frame["index"], frame["alpha"], frame["ox"], frame["oy"]), (1, 128, 49, 81))

    def test_effect_expires_without_looping_and_missing_speed_uses_raw_timing(self):
        result = self.helper("[skillEffectFrame(effects,{kind:'combat_attack',skillId:1121008,actionName:'brandish2'},119)?.index,"
                             "skillEffectFrame(effects,{kind:'combat_attack',skillId:1121008,actionName:'brandish2'},240)??null]")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [0, None])

    def test_bad_archive_provenance_and_frame_paths_fail_closed(self):
        for manifest in [MANIFEST.replace("Skill.wz", "Fake.wz", 1),
                         MANIFEST.replace("1121008_effect_1_0.png", "../private.png"),
                         MANIFEST.replace("112.img/skill/1121008/effect/1/0", "110.img/skill/1121008/effect/1/0")]:
            with self.subTest(manifest=manifest[:80]):
                result = self.helper("effects.size", manifest)
                self.assertNotEqual(result.returncode, 0)

    def test_exporter_drives_native_frames_only_after_combat_event(self):
        with tempfile.TemporaryDirectory(prefix="maplebench-skill-fx-test-") as name:
            root = Path(name)
            run, char, map_dir, fx = [root / p for p in ("run", "char", "map", "fx")]
            for p in (run, char, map_dir, fx): p.mkdir()
            (char / "char.txt").write_text("stand1 0 100\nwalk1 0 100\njump 0 100\nswingO1 0 100\nbrandish2 0 100\n")
            (map_dir / "map.fh").write_text("0 0 2048 1024\n")
            (fx / "effects.txt").write_text(MANIFEST)
            observations = [dict(nowMs=t, combatTrace="combat-v1", character=dict(
                id=4, mapId=100000000, hp=8000, maxHp=8000, position=dict(x=300, y=260)),
                monsters=[]) for t in (0, 1000, 2000)]
            events = [dict(kind="action", tMs=0, accepted=True, action=dict(type="use_skill", skillId=1121008)),
                      dict(kind="combat_attack", tMs=1000, seq=1, characterId=4, mapId=100000000,
                           skillId=1121008, actionName="brandish2", cooldownMs=900, speed=2, facingLeft=False),
                      dict(kind="player_hit", tMs=1100, seq=2, characterId=4, mapId=100000000,
                           position=dict(x=300, y=260), damage=1, knockback=True)]
            (run / "observations.json").write_text(json.dumps(observations))
            (run / "episode.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
            result = subprocess.run([shutil.which("node"), str(ROOT / "scripts/render-cosmic-clip.mjs"), str(run)],
                env=dict(os.environ, MAPLEBENCH_SNAPSHOTS_ONLY="true", MAPLEBENCH_CHARACTER_DIR=str(char),
                         MAPLEBENCH_MAP_DIR=str(map_dir), MAPLEBENCH_SKILL_EFFECT_DIR=str(fx)),
                check=False, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            def effects(frame):
                return [line for line in (run / f"video/frame-{frame:04}.tsv").read_text().splitlines()
                        if line.startswith("effect ")]
            self.assertEqual(effects(0), [])
            self.assertEqual(effects(14), [])
            self.assertEqual(effects(15), ["effect 1121008_effect_1_0.png 300.00 260.00 30 23 1 255 0"])
            self.assertTrue(effects(16))
            self.assertEqual(effects(17), [], "Knockback must stop the canceled attack effect")
            provenance = json.loads((run / "skill-effects.json").read_text())
            self.assertEqual(provenance["archive"], "Skill.wz")
            self.assertEqual(len(provenance["manifestSha256"]), 64)
            overlay_only = subprocess.run([shutil.which("node"), str(ROOT / "scripts/render-cosmic-clip.mjs"), str(run)],
                env=dict(os.environ, MAPLEBENCH_OVERLAY_ONLY="true", MAPLEBENCH_CHARACTER_DIR=str(char),
                         MAPLEBENCH_MAP_DIR=str(map_dir), MAPLEBENCH_SKILL_EFFECT_DIR=str(fx)),
                check=False, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(overlay_only.returncode, 0)
            self.assertIn("Skill effects require a full native render", overlay_only.stderr)
            self.assertEqual(json.loads((run / "skill-effects.json").read_text()), provenance)
