"""Replay the real exporter against explicit combat and interruption boundaries."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class CombatReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='maplebench-combat-test-')
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        run, char, map_dir = root/'run', root/'char', root/'map'
        for p in (run, char, map_dir): p.mkdir()
        (char/'char.txt').write_text('stand1 0 100\nwalk1 0 100\njump 0 100\nswingO1 0 100\nbrandish2 0 100\nbrandish2 1 100\nalert4 0 100\n')
        (map_dir/'map.fh').write_text('0 0 2048 1024\n')
        (run/'mob-animations.json').write_text(json.dumps({'5110301': {'hit1':600,'die1':1000}}))
        def mob(oid):
            return dict(objectId=oid, monsterId=5110301, hp=4400, maxHp=4400,
                        position=dict(x=220,y=167), alive=True, moving=True, facingLeft=True)
        observations=[]
        for i in range(5):
            motion=dict(inAir=i==1, facingLeft=False, moving=False, attackCooldownMs=300 if i==2 else 0)
            character=dict(id=4,mapId=261020300,jobId=112,level=130,hp=7750 if i in (1,2) else 8000,maxHp=8000,
                           position=dict(x=200-i*10,y=150 if i in (1,3) else 167),motion=motion,
                           mp=900,maxMp=1000,combo=dict(active=True,orbs=5,maxOrbs=10))
            observations.append(dict(nowMs=i*1000, character=character,combatTrace='combat-v1',
                                     monsters=[mob(1),mob(2)] if i<2 else [mob(1)] if i==2 else [],
                                     skills=[dict(skillId=1111002,name='Combo Attack',selfBuff=True,active=True,remainingMs=150000)]))
        events=[dict(kind='combat_attack', seq=1, tMs=800, characterId=4,mapId=261020300,skillId=1121008,
                     actionName='brandish2',cooldownMs=900,hitDelayMs=250,facingLeft=False),
                dict(kind='player_hit',tMs=1000,characterId=4,mapId=261020300,source='touch',objectId=1,
                     position=dict(x=190,y=150),damage=250,miss=False,knockback=True,hurtCooldownMs=1400),
                dict(kind='monster_hit',tMs=1100,mapId=261020300,characterId=4,objectId=1,monsterId=5110301,
                     position=dict(x=220,y=167),damageLines=[300,400],hpLoss=700,killed=False),
                dict(kind='combat_attack',seq=3,tMs=1800,characterId=4,mapId=261020300,skillId=1121008,
                     actionName='brandish2',cooldownMs=600,hitDelayMs=250,facingLeft=False),
                dict(kind='xp_gain',tMs=1900,amount=168),
                dict(kind='monster_hit',tMs=1900,mapId=261020300,characterId=4,objectId=1,monsterId=5110301,
                     position=dict(x=220,y=167),damageLines=[1200,1300],hpLoss=2500,killed=False),
                dict(kind='monster_hit',tMs=1900,mapId=261020300,characterId=4,objectId=3,monsterId=5110301,
                     position=dict(x=221,y=167),damageLines=[2000,2100],hpLoss=4100,killed=False),
                dict(kind='monster_hit',tMs=2400,mapId=261020300,characterId=4,objectId=1,monsterId=5110301,
                     position=dict(x=220,y=167),damageLines=[3000,3500],hpLoss=1900,killed=True)]
        events.append(dict(kind='skill_cast',seq=9,tMs=3650,characterId=4,mapId=261020300,
                           skillId=1111002,actionName='alert4',cooldownMs=700,facingLeft=False))
        (run/'observations.json').write_text(json.dumps(observations))
        (run/'episode.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
        subprocess.run([shutil.which('node'),str(ROOT/'scripts/render-cosmic-clip.mjs'),str(run)],
            env=dict(os.environ,MAPLEBENCH_SNAPSHOTS_ONLY='true',MAPLEBENCH_CHARACTER_DIR=str(char),
                     MAPLEBENCH_MAP_DIR=str(map_dir),MAPLEBENCH_MAP_ID='261020300'),
            check=True,capture_output=True,timeout=15)
        cls.out=run/'video'
        cls.ass=(cls.out/'overlay.ass').read_text()

    def frame(self,index):
        return [line.split() for line in (self.out/f'frame-{index:04}.tsv').read_text().splitlines()]

    def test_hit_interrupts_attack_and_recoil_does_not_turn_character(self):
        self.assertEqual(self.frame(12)[0][3], 'brandish2')
        self.assertEqual(self.frame(15)[0][3:6], ['jump','0','1'])
        self.assertIn('KNOCKBACK', self.ass)
        # Grounded at a different height from the initial camera must not become a jump.
        self.assertEqual(self.frame(45)[0][3], 'stand1')

    def test_explicit_buff_uses_its_recorded_pose_and_exposes_resources(self):
        self.assertEqual(self.frame(58)[0][3], 'alert4')
        self.assertTrue('COMBO 5/10' in self.ass, 'Combo count missing from HUD')
        self.assertTrue('MP   900 / 1000' in self.ass, 'MP missing from HUD')

    def test_uses_recorded_cooldown_instead_of_fixed_800ms(self):
        self.assertEqual(self.frame(33)[0][3], 'brandish2')
        self.assertNotEqual(self.frame(36)[0][3], 'brandish2')

    def test_hit_and_death_reactions_follow_confirmed_events_and_wz_duration(self):
        self.assertEqual(next(r for r in self.frame(29) if r[:2]==['mob','1'])[6], 'hit1')
        deaths=[r for r in self.frame(36) if r[0]=='mob']
        self.assertEqual(len(deaths),1)
        self.assertEqual(deaths[0][1], '1')
        self.assertEqual(deaths[0][6], 'die1')
        self.assertFalse(any(r[0]=='mob' for r in self.frame(51)))

    def test_separate_rolls_and_purple_incoming_hit_without_duplicate_hp_delta(self):
        self.assertIn('}3000\n',self.ass)
        self.assertIn('}3500\n',self.ass)
        self.assertNotIn('-1900 HP',self.ass)
        self.assertNotIn('}-250 HP',self.ass)
        self.assertIn(r'\c&HFF80D4&',self.ass)
        self.assertIn('}250\n',self.ass)
        self.assertIn('}+250 HP',self.ass)

    def test_clustered_targets_keep_their_damage_columns_separate(self):
        import re
        rows=[r.split(',',9) for r in self.ass.splitlines() if r.startswith('Dialogue:')]
        labels={}
        for r in rows:
            if r[1]=='0:00:01.93' and r[3]=='Damage':
                value=int(r[9].split('}')[-1])
                labels[value]=int(re.search(r'pos\((\d+),',r[9]).group(1))
        self.assertEqual(labels[1200],labels[1300])
        self.assertEqual(labels[2000],labels[2100])
        self.assertGreaterEqual(labels[2000]-labels[1200],88)

    def test_incoming_hit_clears_intersecting_outgoing_rows(self):
        import re
        incoming=[]; outgoing=[]
        for line in self.ass.splitlines():
            if not line.startswith('Dialogue:'): continue
            r=line.split(',',9)
            if r[1]!='0:00:01.13' or r[3] not in ('PlayerHP','Damage'): continue
            y=int(re.search(r'pos\(\d+,(\d+)\)',r[9]).group(1))
            (incoming if r[3]=='PlayerHP' else outgoing).append(y)
        self.assertTrue(incoming and outgoing)
        self.assertLessEqual(max(incoming),min(outgoing)-35)
