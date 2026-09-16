"""Synthetic task bindings only; no fixture, ledger or runtime is qualified."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import full_client_skill_tasks as tasks


def fixture(task_id='platforming-v1',variant=1,control='positive'):
    geometry={'map_id':100000000,'footholds':[
        {'id':1,'x1':-400,'y1':100,'x2':-100,'y2':100},
        {'id':2,'x1':0,'y1':100,'x2':100,'y2':100},
        {'id':3,'x1':150,'y1':80,'x2':450,'y2':80},
        {'id':4,'x1':500,'y1':60,'x2':800,'y2':60},
    ]}
    def region(fid,x1,x2,y):return dict(map_id=100000000,foothold_id=fid,x_min=x1,x_max=x2,y_min=y-1,y_max=y+1)
    initial=dict(map_id=100000000,x=50,y=100,foothold_id=2,facing='right',
                 hp=12000,max_hp=12000,mp=16000,max_mp=16000,power_elixirs=0,active_buffs=[],monster_count=0)
    target=region(3,170,430,80) if variant==1 else region(1,-380,-120,100) if variant==2 else region(4,520,780,60)
    milestones=[region(3,170,430,80)] if variant==3 else []
    teleport=None
    if task_id=='native-teleport-v1':
        teleport=dict(skill_id=2201002,level=20,slot='SECONDARY_SKILL',mp_cost=13,distance_px=150,definitions_sha256='d'*64)
        if control=='insufficient-mp':initial['mp']=0
    elif task_id=='potion-use-v1':
        target=None;milestones=[];initial['mp']=16000*(variant+1)//20
        initial['power_elixirs']=0 if control=='empty-inventory' else 1
    return {'schema_version':1,'id':tasks.BINDING_PROTOCOL,'task_id':task_id,'variant':variant,
            'class_id':tasks.CLASS_ID,'level':180,
            **{k:'b'*64 for k in ('baseline_sha256','equipment_sha256','inventory_sha256','keymap_sha256','native_definitions_sha256')},
            'geometry_sha256':tasks.sha256(geometry),
            'software':{k:('a'*40 if k=='source_commit' else 'a'*64) for k in tasks.SOFTWARE_FIELDS},
            'geometry':geometry,'initial':initial,'target':target,'milestones':milestones,'teleport':teleport}


class SkillTaskContractTests(unittest.TestCase):
    def test_three_native_tasks_and_variants_are_separate_immutable_values(self):
        for task_id in tasks.TASK_IDS:
            for variant in (1,2,3):
                with self.subTest(task_id=task_id,variant=variant):
                    value=tasks.contract(task_id,variant,fixture(task_id,variant))
                    self.assertEqual(tasks.validate_contract(value),value)
                    self.assertEqual(value['limits']['max_api_requests'],0)
                    self.assertEqual(value['limits']['wall_seconds'],120)
                    value['limits']['wall_seconds']=300
                    with self.assertRaises(ValueError):tasks.validate_contract(value)
                    self.assertEqual(tasks.SHORT_LIMITS['wall_seconds'],120)

    def test_null_draft_bindings_and_reserved_tasks_are_not_executable(self):
        with self.assertRaises(ValueError):tasks.contract('platforming-v1',1,None)
        for task_id in tasks.RESERVED_TASK_IDS:
            with self.subTest(task_id=task_id),self.assertRaises(ValueError):tasks.contract(task_id,1,fixture())

    def test_native_control_cannot_claim_qualification(self):
        with self.assertRaises(ValueError):tasks.contract('potion-use-v1',1,fixture('potion-use-v1'),qualification_sha256='c'*64)

    def test_model_admission_and_deadline_reserve_boundaries(self):
        b=fixture('potion-use-v1')
        with self.assertRaises(ValueError):tasks.contract('potion-use-v1',1,b,purpose='model-development')
        value=tasks.contract('potion-use-v1',1,b,purpose='model-development',qualification_sha256='c'*64)
        self.assertFalse(tasks.request_admission(value,14999)['admitted'])
        self.assertEqual(tasks.request_admission(value,15000)['timeout_ms'],5000)
        self.assertEqual(tasks.request_admission(value,120000)['timeout_ms'],30000)
        self.assertEqual(tasks.request_admission(value,14000)['program_limit_ms'],9000)
        self.assertEqual(tasks.request_admission(value,4999)['program_limit_ms'],0)
        self.assertFalse(tasks.input_fits(value,7999));self.assertTrue(tasks.input_fits(value,8000))
        with self.assertRaises(ValueError):tasks.request_admission(value,float('nan'))
        negative=fixture('potion-use-v1',control='empty-inventory')
        with self.assertRaises(ValueError):tasks.contract('potion-use-v1',1,negative,purpose='model-development',control='empty-inventory',qualification_sha256='c'*64)

    def test_restricted_named_keys_and_descriptor_exclude_private_pins(self):
        for task_id,extra in [('platforming-v1',[]),('native-teleport-v1',['SECONDARY_SKILL']),('potion-use-v1',['HP_POTION','MP_POTION'])]:
            value=tasks.contract(task_id,1,fixture(task_id));description=tasks.descriptor(value)
            self.assertEqual(tasks.allowed_keys(value),tasks.MOVEMENT_KEYS+extra)
            encoded=json.dumps(description)
            for forbidden in ('baseline_sha256','source_commit','qualification_sha256','scorer_sha256','account_id'):
                self.assertNotIn(forbidden,encoded)
            scenario=tasks.sdk_scenario(value)
            self.assertEqual(scenario['skill_task'],value)
            self.assertEqual(scenario['protocol'],tasks.PROTOCOL)
            self.assertEqual(description['task_id'],task_id)
        value=tasks.contract('potion-use-v1',1,fixture('potion-use-v1'))
        self.assertTrue(tasks.descriptor(value)['potion']['shared_inventory'])

    def test_geometry_edge_margin_identity_and_hash_tampering_refused(self):
        for mutate in (lambda b:b['target'].update(x_min=151),
                       lambda b:b['target'].update(map_id=100000001),
                       lambda b:b['geometry']['footholds'][2].update(y1=100),
                       lambda b:b['initial'].update(x=200,y=80,foothold_id=3),
                       lambda b:b['software'].update(scorer_sha256=None)):
            b=fixture();mutate(b)
            with self.assertRaises(ValueError):tasks.contract('platforming-v1',1,b)

    def test_task_specific_resource_and_unsupported_skill_mutations_refused(self):
        b=fixture('native-teleport-v1');b['teleport']['skill_id']=4111006
        with self.assertRaises(ValueError):tasks.contract('native-teleport-v1',1,b)
        b=fixture('potion-use-v1');b['initial']['power_elixirs']=2
        with self.assertRaises(ValueError):tasks.contract('potion-use-v1',1,b)
        for variant,mp in ((1,1600),(2,2400),(3,3200)):
            b=fixture('potion-use-v1',variant);v=tasks.contract('potion-use-v1',variant,b)
            self.assertEqual(v['binding']['initial']['mp'],mp)
            b['initial']['mp']+=1
            with self.assertRaises(ValueError):tasks.contract('potion-use-v1',variant,b)

    def test_negative_native_fixture_is_distinct_without_rewriting_positive(self):
        positive=tasks.contract('potion-use-v1',1,fixture('potion-use-v1'))
        negative=tasks.contract('potion-use-v1',1,fixture('potion-use-v1',control='empty-inventory'),control='empty-inventory')
        self.assertNotEqual(positive['binding_sha256'],negative['binding_sha256'])
        self.assertEqual(negative['binding']['initial']['power_elixirs'],0)
        self.assertEqual(positive['binding']['initial']['power_elixirs'],1)


if __name__=='__main__':unittest.main()
