"""Toolkit source/SDK/fixture tests; no game, database or paid API is used."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import full_client_adaptive as adaptive
import full_client_native as native
from full_client_skill_toolkit import toolkit,profile,validate_toolkit,allowed_keys,fingerprint,SLOTS,NATIVE_PROTOCOL,sdk_scenario
from full_client_toolkit_fixture import transform,table,learned_skills,resource_stacks
from maple_agent import validate_rpc

CLASSES=('hero','bowmaster','ice_lightning_arch_mage','night_lord')


def definitions(policy):
    skills={str(s['skill_id']):{'level':s['level'],'max_level':s['level'],
        'requirements':{},'level_values':{'mpCon':30},'nx_xml_scalar_match':True}
        for s in policy['skills']+policy['passives']}
    if '2210001' in skills:skills['2210001']['level_values']={'x':200,'y':135}
    if '2221007' in skills:skills['2221007']['level_values']={'mpCon':3500}
    return {'status':'nx_xml_scalars_verified_not_live_qualified','toolkit_sha256':fingerprint(policy),
        'skills':skills,'items':{'2000005':{'info':{'slotMax':100},'spec':{'hpR':100,'mpR':100},'nx_xml_scalar_match':True},
            '2060000':{'info':{'slotMax':2000},'nx_xml_scalar_match':True},
            '2070006':{'info':{'slotMax':800},'nx_xml_scalar_match':True}}}


def sql_fixture(cls):
    p=toolkit(cls);weapon={'hero':1402037,'bowmaster':1452009,'ice_lightning_arch_mage':1382009,'night_lord':1472053}[cls]
    rows={
        'accounts':(['id','loggedin','password'],[[2,0,"'__SYNTHETIC_PRIVATE_FIELD__'"]]),
        'characters':(['id','accountid','job','level','hp','maxhp','mp','maxmp','exp'],[[5,2,p['job'],180,100,12000,100,3000,73250]]),
        'skills':(['id','skillid','characterid','skilllevel','masterlevel','expiration'],[[1,4000000,5,3,0,-1]]),
        'keymap':(['id','characterid','key','type','action'],[[1,5,29,4,52],[2,5,57,4,53],[3,5,46,4,26],[4,5,47,4,27]]),
        'inventoryitems':(['inventoryitemid','type','characterid','accountid','itemid','inventorytype','position','quantity','owner','petid','flag','expiration','giftFrom'],
            [[10,1,5,'NULL',weapon,-1,-11,1,"''",-1,0,-1,"''"],[11,1,5,'NULL',2000006,2,1,51,"''",-1,0,-1,"''"]]),
    }
    sql='-- Synthetic fixture; it is never connected to a database.\n'
    for name,(columns,values) in rows.items():
        sql+='CREATE TABLE `'+name+'` (\n'+',\n'.join('  `'+c+'` int' for c in columns)+'\n) ENGINE=InnoDB;\n'
        sql+='INSERT INTO `'+name+'` VALUES '+','.join('('+','.join(map(str,row))+')' for row in values)+';\n'
    return sql.encode()


class ToolkitTests(unittest.TestCase):
    def test_canonical_profile_and_new_keys_require_exact_opt_in(self):
        for cls,count in zip(CLASSES,(10,10,10,8)):
            p=toolkit(cls);self.assertEqual(len(p['skills']),count)
            protocol=copy.deepcopy(adaptive.DEFAULT_PROTOCOL)
            protocol.update(profile=profile(p),skill_toolkit=p)
            self.assertEqual(adaptive.validate_protocol(protocol),protocol)
            self.assertEqual(sdk_scenario(protocol)['skill_toolkit'],p)
            text=adaptive.prompt(protocol)
            for s in p['skills']:self.assertIn(s['description'],text)
            self.assertIn('same finite Power Elixir',text)
            for slot in SLOTS:
                rpc={'type':'rpc','id':1,'method':'pressKeys','args':[[slot],100]}
                if slot in allowed_keys(p):
                    self.assertEqual(validate_rpc(rpc,{'adapter':'full-client',**sdk_scenario(protocol)})[1]['keys'],[slot])
                else:
                    with self.assertRaises(ValueError):validate_rpc(rpc,{'adapter':'full-client',**sdk_scenario(protocol)})
            altered=copy.deepcopy(p);altered['skills'][0]['key_type']=4
            with self.assertRaises(ValueError):validate_toolkit(altered)
            mismatch=copy.deepcopy(protocol);mismatch['profile']['skill_keys']['PRIMARY_SKILL']='Unknown'
            with self.assertRaisesRegex(ValueError,'invalid_adaptive_skill_toolkit'):adaptive.validate_protocol(mismatch)
        rpc={'type':'rpc','id':1,'method':'pressKeys','args':[['SKILL_5'],100]}
        for old in ({'adapter':'full-client'},{'adapter':'full-client','protocol':adaptive.PROTOCOL}):
            with self.assertRaises(ValueError):validate_rpc(rpc,old)
        for badkeys in (['LEFT','RIGHT'],['UP','DOWN'],['SKILL_5','SKILL_5'],['__proto__']):
            rpc['args'][0]=badkeys
            with self.assertRaises(ValueError):validate_rpc(rpc,{'adapter':'full-client','protocol':adaptive.PROTOCOL,'skill_toolkit':toolkit('hero')})

    def test_slots_do_not_collide_with_directions_actions_or_potions(self):
        self.assertEqual(len({code for code,key in SLOTS.values()}),10)
        self.assertFalse({key for code,key in SLOTS.values()} & {16,17,29,57,85,72,75,77,80})
        self.assertTrue(all(s['key_type']==1 for c in CLASSES for s in toolkit(c)['skills']))
        self.assertIn('empty native movement branch',' '.join(toolkit('night_lord')['unsupported']))

    def test_new_contract_is_bound_and_old_native_proof_cannot_match(self):
        for cls in CLASSES:
            new=native.contract(cls,'a'*64,protocol=NATIVE_PROTOCOL)
            self.assertEqual(native.validate_contract(new),new)
            self.assertEqual(new['profile'],profile(new['skill_toolkit']))
            self.assertEqual((new['wall_seconds'],new['max_actions'],new['max_sdk_requests'],new['capture_max_ms']),(60,32,180,75000))
            old=native.contract(cls,'a'*64,protocol=native.NATIVE_V4_PROTOCOL)
            self.assertNotEqual(new['profile'],old['profile'])
            altered=copy.deepcopy(new);altered['skill_toolkit']['skills'].pop()
            with self.assertRaises(ValueError):native.validate_contract(altered)

    def test_native_bridge_uses_new_exact_caps_and_never_calls_a_model(self):
        from test_full_client_native import NativeTests
        harness=NativeTests();harness.setUp()
        try:
            config=native.contract('hero','a'*64,protocol=NATIVE_PROTOCOL)
            options=harness.options|{'native_acceptance':config}
            with mock.patch('full_client_bridge.threading.Thread'):
                run=harness.bridge.start('script',None,60,**options)
            self.assertEqual((run['actionLimit'],run['sdkRequestLimit'],run['controllerSeconds']),(32,180,60))
            def execute(code,scenario,base,**kwargs):
                self.assertEqual(code,native.program(config));self.assertEqual(scenario['skill_toolkit'],config['skill_toolkit'])
                self.assertEqual((kwargs['program_seconds'],kwargs['max_actions'],kwargs['max_requests']),(60,32,180))
                return {'reason':'program_complete','actions':0,'steps':[]}
            with mock.patch.object(harness.bridge,'_wait_for_capture'),mock.patch.object(harness.bridge,'request',return_value=harness.observation),\
                 mock.patch('full_client_bridge.execute_program',side_effect=execute),\
                 mock.patch('full_client_bridge.model_decision',side_effect=AssertionError('model forbidden')),\
                 mock.patch('full_client_bridge.read_private_file',side_effect=AssertionError('credential read forbidden')):
                harness.bridge._run(run)
            result=json.loads((harness.bridge.output/run['id']/'result.json').read_text())
            self.assertEqual(result['controller']['status'],'completed');self.assertEqual(result['model_api_requests'],0)
        finally:harness.doCleanups()

    def test_extended_sdk_receipt_is_rechecked_under_the_frozen_policy(self):
        from test_full_client_adaptive import Harness,MODEL
        from full_client_adaptive_evidence import verify_result
        with tempfile.TemporaryDirectory() as directory:
            h=Harness(directory,calls=1);p=toolkit('hero');h.p.update(profile=profile(p),skill_toolkit=p)
            h.code="await sdk.pressKeys(['SKILL_5'],100);"
            def execute(code,**kwargs):
                callback=kwargs['step_callback']
                def step(value):
                    value['args']=[['SKILL_5'],100];callback(value)
                return h.execute(code,**(kwargs|{'step_callback':step}))
            h.run(execute=execute)
            checked=verify_result(h.result(),h.root,protocol=h.p,model=MODEL)
            self.assertEqual(checked['counters']['actions'],1)

    def test_capture_bundle_uses_toolkit_native_input_origin_and_sixty_second_contract(self):
        from test_full_client_native import encoded_native_fixture
        from full_client_capture import capture_receipt
        from full_client_publish import verify_capture_bundle
        config=native.contract('hero','a'*64,protocol=NATIVE_PROTOCOL)
        fixture=encoded_native_fixture()
        owner=fixture.owner|{'protocol':NATIVE_PROTOCOL,'mode':'script','model':None,'nativeAcceptance':config}
        raw=fixture.value
        raw.update(end_wall_ms=70520,duration_ms=60500,last_frame_wall_ms=70518,
                   last_frame_offset_ms=60498,rendered_frames=120)
        raw['encoder_receipt'].update(submitted_frames=120,encoded_frames=120)
        fixture.terminal['serverIssuedAtMs']=80000
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);refs={}
            def artifact(name,value):
                data=json.dumps(value).encode();path=root/(name+'.json');path.write_bytes(data)
                refs[name]={'path':path.name,'sha256':hashlib.sha256(data).hexdigest()}
            for name,value in (('capture',raw),('capture_ready',fixture.anchor),
                               ('capture_clock',fixture.clock),('capture_terminal',fixture.terminal)):
                artifact(name,value)
            recording=capture_receipt(raw,owner,fixture.anchor,fixture.clock,fixture.terminal)|{
                'sha256':'d'*64,'capture_sha256':refs['capture']['sha256']}
            artifact('recording',recording)
            result={'protocol':NATIVE_PROTOCOL,'nativeAcceptance':config,'model_api_requests':0,
                'trialContext':None,'api':None,'controller':owner|{'returnedModel':None},
                'timing':{'startedAtMs':20000,'endedAtMs':80000},
                'timeline':{'api_started_ms':None,'api_ended_ms':None,'program_started_ms':500,'program_ended_ms':59800}}
            manifest={'result':result,'video':recording,'artifacts':refs}
            measured=verify_capture_bundle(manifest,root)
            self.assertEqual(measured['duration_ms'],60500);self.assertFalse(measured['interrupted'])
            result['controller']['mode']='api'
            with self.assertRaisesRegex(ValueError,'cannot carry a model identity'):verify_capture_bundle(manifest,root)
            result['controller']['mode']='script'
            result['nativeAcceptance']=native.contract('hero','a'*64,protocol=native.NATIVE_V4_PROTOCOL)
            with self.assertRaisesRegex(ValueError,'cannot carry a model identity'):verify_capture_bundle(manifest,root)

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_native_recipe_executes_every_declared_slot_under_finite_caps(self):
        for cls in CLASSES:
            value=native.contract(cls,'a'*64,protocol=NATIVE_PROTOCOL);code=native.program(value)
            # Execute actual generated code against a finite synthetic SDK; no
            # key acknowledgements are reported as native effects or XP.
            runner="""const calls=[];let elapsed=0;
const sdk={observe:async()=>{calls.push(['observe']);return {character:{x:0,y:0},monsters:[{x:50,y:0}]};},
 pressKeys:async(keys,ms)=>{calls.push(['pressKeys',keys,ms]);elapsed+=ms;},
 wait:async ms=>{calls.push(['wait',ms]);elapsed+=ms;}};
(async()=>{CODE})().then(()=>console.log(JSON.stringify({calls,elapsed}))).catch(e=>{console.error(e);process.exit(1)});
""".replace('CODE',code)
            proc=subprocess.run(['node','-e',runner],check=True,capture_output=True,text=True,timeout=10)
            result=json.loads(proc.stdout);inputs=[c[1] for c in result['calls'] if c[0]=='pressKeys']
            self.assertLessEqual(len(inputs),value['max_actions']);self.assertLessEqual(len(result['calls']),value['max_sdk_requests'])
            self.assertLess(result['elapsed'],value['wall_seconds']*1000)
            for skill in value['skill_toolkit']['skills']:self.assertTrue(any(skill['slot'] in keys for keys in inputs))
            first_attack=next(i for i,keys in enumerate(inputs) if 'PRIMARY_SKILL' in keys)
            for skill in value['skill_toolkit']['skills']:
                if skill['route']=='buff':self.assertLess(inputs.index([skill['slot']]),first_attack)
            self.assertIn(['MP_POTION'],inputs);self.assertIn(['ATTACK'],inputs)

    def test_offline_transform_all_classes_preserves_account_and_weapon(self):
        for cls in CLASSES:
            original=sql_fixture(cls);p=toolkit(cls);new,expected=transform(original,p,definitions(p))
            self.assertEqual(table(new.decode(),'accounts')[1],table(original.decode(),'accounts')[1])
            weapon=lambda raw:[r for r in table(raw.decode(),'inventoryitems')[1] if r['inventorytype']=='-1']
            self.assertEqual(weapon(new),weapon(original))
            self.assertEqual(expected['mp'],16000 if cls=='ice_lightning_arch_mage' else 6000)
            self.assertEqual(expected['hp'],expected['max_hp'])
            self.assertIn([29,5,52],expected['keymap']);self.assertIn([57,5,53],expected['keymap'])
            self.assertIn([16,2,2000005],expected['keymap']);self.assertIn([17,2,2000005],expected['keymap'])
            for skill in p['skills']:self.assertIn([skill['key'],1,skill['skill_id']],expected['keymap'])
            self.assertEqual(expected['use_inventory'][0],[1,2000005,100])
            self.assertLessEqual(len(expected['use_inventory']),24)
            self.assertEqual(expected['runtime_mutations'],0)
            if cls=='night_lord':
                self.assertEqual(sum(r[2] for r in expected['use_inventory'] if r[1]==2070006),18400)
                self.assertFalse({46,47}&{r[0] for r in expected['keymap']})

    def test_prerequisites_and_real_resource_definitions_are_fail_closed(self):
        p=toolkit('night_lord');d=definitions(p)
        d['skills']['4000001']['requirements']={'4000000':3}
        self.assertEqual(learned_skills(p,d)[4000000],3)
        d['skills']['4000001']['requirements']={'4000000':4}
        with self.assertRaisesRegex(ValueError,'skill_definition_not_verified'):learned_skills(p,d)
        for mutate in (
            lambda x:x['items']['2070006']['info'].update(slotMax=799),
            lambda x:x['items']['2000005']['spec'].update(mpR=50),
            lambda x:x.update(toolkit_sha256='0'*64),
            lambda x:x['skills']['4121007'].update(nx_xml_scalar_match=False)):
            d=definitions(p);mutate(d)
            with self.assertRaises(ValueError):transform(sql_fixture('night_lord'),p,d)
        p=toolkit('ice_lightning_arch_mage');d=definitions(p);d['skills']['2221007']['level_values']['mpCon']=16001
        with self.assertRaisesRegex(ValueError,'skill_exceeds_fixture_mp_capacity'):transform(sql_fixture('ice_lightning_arch_mage'),p,d)
        with self.assertRaisesRegex(ValueError,'correct_class_baseline_required'):transform(sql_fixture('hero'),toolkit('bowmaster'),definitions(toolkit('bowmaster')))


if __name__=='__main__':unittest.main()
