import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('combat_metrics', Path(__file__).parents[1]/'scripts/combat_metrics.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def observation(t, hp=1000, combo=0, active=False, remaining=0):
    return {'nowMs':t,'combatTrace':'combat-v1','mechanicsVersion':'hero-control-v2',
            'character':{'id':4,'hp':hp,'maxHp':1000,'combo':{'orbs':combo}},
            'skills':[{'skillId':1111002,'selfBuff':True,'active':active,'remainingMs':remaining}]}


class CombatMetricsTest(unittest.TestCase):
    def test_counts_actual_kills_and_applied_damage_not_xp_or_overkill(self):
        events=[{'kind':'combat_attack','seq':1,'tMs':100,'skillId':1121008},
                {'kind':'monster_hit','tMs':100,'mapId':1,'objectId':9,'attackId':1,
                 'damage':3000,'damageLines':[1400,1600],'hpBefore':1000,'hpLoss':1000,'killed':True},
                {'kind':'xp_gain','tMs':200,'amount':9999},
                {'kind':'monster_hit','tMs':1100,'mapId':1,'objectId':10,'killed':True,'hpLoss':1000}]
        score=m.summarize_combat([observation(0),observation(1000)],events)
        self.assertEqual(score['monstersKilled'],1)
        self.assertEqual(score['damageDealt'],1000)
        self.assertEqual(score['damageRolled'],3000)
        self.assertEqual(score['overkillDamage'],2000)
        self.assertEqual(score['averageTargetsPerAttack'],1)

    def test_time_weights_buffs_and_excludes_recording_gaps(self):
        obs=[observation(0,combo=4,active=True,remaining=600),observation(1000),
             observation(5000,combo=10,active=True,remaining=2000),observation(6000,hp=700)]
        score=m.summarize_combat(obs,[])
        self.assertAlmostEqual(score['buffUptimePercent']['1111002'],80)
        self.assertEqual(score['observationCoveragePercent'],33.33)
        self.assertEqual(score['minimumHpPercent'],70)
        self.assertEqual(score['maximumComboOrbs'],10)

    def test_misses_resisted_knockback_and_rejected_potions_stay_distinct(self):
        events=[{'kind':'player_hit','tMs':100,'damage':0,'miss':True,'knockback':False},
                {'kind':'player_hit','tMs':200,'damage':200,'miss':False,'knockback':False},
                {'kind':'player_hit','tMs':300,'damage':250,'miss':False,'knockback':True},
                {'kind':'action','tMs':500,'accepted':True,'action':{'type':'use_item','itemId':2001001}},
                {'kind':'action','tMs':600,'accepted':False,'action':{'type':'use_item','itemId':2001001}}]
        s=m.summarize_combat([observation(0),observation(1000)],events)
        self.assertEqual((s['incomingHits'],s['incomingMisses'],s['knockbacks']),(2,1,1))
        self.assertEqual(s['incomingDamage'],450)
        self.assertEqual(s['potionsUsed'],{'2001001':1})

    def test_legacy_recordings_do_not_claim_zero_combat(self):
        self.assertEqual(m.summarize_combat([{'nowMs':0,'character':{}}],[]),{'combatMetricsAvailable':False})
        old=observation(0); del old['skills']; del old['character']['combo']
        s=m.summarize_combat([old],[])
        self.assertIsNone(s['maximumComboOrbs']); self.assertIsNone(s['buffUptimePercent'])
