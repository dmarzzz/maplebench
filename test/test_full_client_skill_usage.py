"""Receipt-backed skill input diagnostics; never inferred successful spell casts."""
import copy
import tempfile
import unittest
from test_full_client_adaptive import Harness, MODEL
from full_client_adaptive_evidence import verify_result
from full_client_adaptive_publication import public_cycles
from full_client_adaptive import final_slot_cohort_protocol, long_horizon_protocol


class SkillUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.h=Harness(self.temp.name,calls=1)
    def execute(self,code,**kw):
        self.h.now+=1
        steps=[]
        for index,keys in enumerate((['LEFT','PRIMARY_SKILL'],['PRIMARY_SKILL'],['ATTACK'])):
            step={'kind':'sdk','rpcId':index+1,'method':'pressKeys','args':[keys,100],
                  'result':{'accepted':True,'observation':self.h.observation()}}
            steps.append(step);kw['step_callback'](step)
        return {'actions':3,'actionAttempts':3,'rpcRequests':3,'steps':steps,'reason':'program_complete','error':None}
    def test_counts_each_acknowledged_skill_input_without_counting_basic_attack(self):
        self.h.run(execute=self.execute);result=self.h.result()
        checked=verify_result(result,self.h.root,protocol=self.h.p,model=MODEL)
        public=public_cycles(result,checked);usage=public['skill_usage'];by_key={r['key']:r for r in usage['skills']}
        self.assertEqual(by_key['PRIMARY_SKILL']['acknowledged_inputs'],2)
        self.assertEqual(by_key['PRIMARY_SKILL']['held_ms'],200)
        self.assertEqual(by_key['SECONDARY_SKILL']['acknowledged_inputs'],0)
        self.assertIsNone(usage['successful_casts']);self.assertFalse(usage['server_effects_verified'])
        self.assertEqual(public['timing_breakdown'],{'basis':'verified_cycle_intervals',
            'model_wait_ms':10000,'program_ms':1000,'observation_only_ms':0})
    def test_new_final_slot_and_passive_time_are_visible_without_changing_score(self):
        self.h.p=final_slot_cohort_protocol(self.h.p['profile']);self.h.p['max_api_requests']=1
        self.h.run(execute=self.execute,sleep=lambda n:setattr(self.h,'now',self.h.now+n))
        result=self.h.result();checked=verify_result(result,self.h.root,protocol=self.h.p,model=MODEL)
        public=public_cycles(result,checked)
        self.assertEqual(public['cycles'][0]['execution_slot']['kind'],'final')
        self.assertEqual(public['timing_breakdown']['observation_only_ms'],289000)
        self.assertIsNone(public['authoritative_peak_xp_per_minute'])
    def test_new_toolkit_slots_keep_declared_levels_and_resource_identity(self):
        from full_client_skill_toolkit import toolkit,profile,fingerprint
        from full_client_catalog import safe_public
        kit=toolkit('hero');self.h.p.update(profile=profile(kit),skill_toolkit=kit)
        def execute(code,**kw):
            self.h.now+=1
            step={'kind':'sdk','rpcId':1,'method':'pressKeys','args':[['SKILL_5'],100],
                  'result':{'accepted':True,'observation':self.h.observation()}}
            kw['step_callback'](step)
            return {'actions':1,'actionAttempts':1,'rpcRequests':1,'steps':[step],
                    'reason':'program_complete','error':None}
        self.h.run(execute=execute);result=self.h.result()
        public=public_cycles(result,verify_result(result,self.h.root,protocol=self.h.p,model=MODEL))
        usage=public['skill_usage'];skills={r['key']:r for r in usage['skills']}
        self.assertEqual(len(skills),10)
        self.assertEqual(skills['SKILL_5']['acknowledged_inputs'],1)
        self.assertEqual(skills['SKILL_5']['name'],'Rush')
        self.assertEqual(skills['SKILL_5']['declared_level'],30)
        self.assertEqual(skills['SKILL_10']['acknowledged_inputs'],0)
        self.assertEqual(usage['toolkit_sha256'],fingerprint(kit))
        self.assertEqual(usage['declared_starting_resources'],kit['resources'])
        self.assertFalse(usage['server_effects_verified']);safe_public(public)
    def test_long_projection_preserves_late_cycles_and_declared_wall(self):
        self.h.p=long_horizon_protocol(self.h.p['profile']);self.h.program_seconds=1000
        self.h.run(sleep=lambda n:setattr(self.h,'now',self.h.now+n))
        result=self.h.result();checked=verify_result(result,self.h.root,protocol=self.h.p,model=MODEL)
        public=public_cycles(result,checked)
        self.assertEqual(public['wall_budget_ms'],1800000)
        self.assertEqual(public['wall_elapsed_ms'],1800000)
        self.assertGreater(public['cycles'][-1]['timing']['program_ended_ms'],300000)
        self.assertEqual(public['timing_breakdown']['observation_only_ms'],5000)


if __name__=='__main__':unittest.main()
