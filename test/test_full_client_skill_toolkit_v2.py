"""Opt-in kit/recipe tests using synthetic SQL, assets and SDK only."""
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
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import full_client_native as native
from full_client_skill_toolkit import (POLICY_ID,POLICY_V2_ID,NATIVE_PROTOCOL,NATIVE_V2_PROTOCOL,
    toolkit,profile,prompt_reference,fingerprint,validate_toolkit,allowed_keys,sdk_scenario)
from full_client_toolkit_fixture import transform,table,replace,etc_resource_stacks
from full_client_skill_definitions import inspect
from maple_agent import validate_rpc
from test_full_client_skill_toolkit import CLASSES,definitions,sql_fixture
from test_full_client_skill_definitions import nx_bytes,xml_tree


def successor(cls):
    return toolkit(cls,policy_id=POLICY_V2_ID)


def verified_definitions(policy):
    value=definitions(policy)
    if policy['class_id']=='hero':
        value['skills']['1120004']['level_values'].update(x=850)
    if policy['class_id']=='night_lord':
        value['skills']['4111002']['level_values'].update(itemCon=4006001,itemConNo=1,x=80,y=50)
        value['skills']['4121006']['level_values'].update(bulletConsume=200)
        value['items']['4006001']={'info':{'price':1},'nx_xml_scalar_match':True}
    return value


def asset_fixture(root,cls):
    policy=successor(cls);d=verified_definitions(policy);skills={};items={}
    for sid,entry in d['skills'].items():
        skills.setdefault(f'{int(sid)//10000}.img',{'skill':{}})['skill'][sid]={
            'level':{str(entry['level']):entry['level_values']},'req':entry['requirements']}
    for iid,entry in d['items'].items():
        category='Etc' if int(iid)//1000000==4 else 'Consume'
        tree=items.setdefault(category,{}).setdefault(f'{int(iid)//10000:04d}.img',{})
        tree['0'+iid]={'info':entry['info']}
        if 'spec' in entry:tree['0'+iid]['spec']=entry['spec']
    assets=root/'assets';assets.mkdir();wz=root/'wz';(wz/'Skill.wz').mkdir(parents=True)
    (assets/'Skill.nx').write_bytes(nx_bytes(skills));(assets/'Item.nx').write_bytes(nx_bytes(items))
    for stem,tree in skills.items():(wz/'Skill.wz'/f'{stem}.xml').write_bytes(ET.tostring(xml_tree(stem,tree)))
    for category,stems in items.items():
        folder=wz/'Item.wz'/category;folder.mkdir(parents=True)
        for stem,tree in stems.items():(folder/f'{stem}.xml').write_bytes(ET.tostring(xml_tree(stem,tree)))
    return assets,wz


class ToolkitSuccessorTests(unittest.TestCase):
    def test_every_historical_policy_prompt_fixture_contract_and_program_is_byte_stable(self):
        raw=(ROOT/'test/fixtures/skill-toolkit-v1-identities.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'cb9c10524ff115b26767ec4d99d447c269df2066cd21a6677ccb661146f2e390')
        for cls,expected in json.loads(raw)['classes'].items():
            p=toolkit(cls);sql,fixture=transform(sql_fixture(cls),p,definitions(p))
            actual={'toolkit':fingerprint(p),'prompt':hashlib.sha256(prompt_reference(p).encode()).hexdigest(),
                'named_prompt':hashlib.sha256(prompt_reference(p,include_physical_keys=False).encode()).hexdigest(),
                'sql':hashlib.sha256(sql).hexdigest(),'expected_fixture':fingerprint(fixture),'native':{}}
            for name in expected['native']:
                protocol,control=name.split('|');contract=native.contract(cls,'a'*64,protocol=protocol,control=control)
                actual['native'][name]=[fingerprint(contract),hashlib.sha256(native.program(contract).encode()).hexdigest()]
            self.assertEqual(actual,expected,cls)

    def test_successor_is_explicit_canonical_and_ten_skills_with_finite_resources(self):
        for cls in CLASSES:
            p=successor(cls);self.assertEqual(len(p['skills']),10)
            self.assertEqual(validate_toolkit(p,profile(p)),p)
            self.assertNotEqual(fingerprint(p),fingerprint(toolkit(cls)))
            self.assertEqual(p['resources']['etc_items'],[{'item_id':4006001,'quantity':10}] if cls=='night_lord' else [])
            self.assertFalse(p['resources']['runtime_refill'])
            self.assertIn('not a cast, hit, buff or resource consumption',prompt_reference(p))
            self.assertTrue(all(s['live_qualification']=='required' for s in p['skills']))
            contract=native.contract(cls,'a'*64,protocol=NATIVE_V2_PROTOCOL)
            self.assertEqual(native.validate_contract(contract),contract)
            self.assertEqual((contract['wall_seconds'],contract['max_actions'],contract['max_sdk_requests'],contract['capture_max_ms']),
                             (120,128,600,125000))
            for slot in allowed_keys(p):
                rpc={'type':'rpc','id':1,'method':'pressKeys','args':[[slot],1500]}
                self.assertEqual(validate_rpc(rpc,{'adapter':'full-client',**sdk_scenario(contract)})[1]['keys'],[slot])
            for mutate in (lambda v:v.update(id=POLICY_ID),lambda v:v['resources'].update(etc_items=[] if cls=='night_lord' else [{'item_id':4006001,'quantity':10}]),
                           lambda v:v['skills'][0].update(level=1),lambda v:v.update(unreviewed=True)):
                bad=copy.deepcopy(p);mutate(bad)
                with self.assertRaises(ValueError):validate_toolkit(bad)
            for change in ({'wall_seconds':121},{'program':'arbitrary'},{'skill_toolkit':toolkit(cls)}):
                with self.assertRaises(ValueError):native.validate_contract(contract|change)
            with self.assertRaises(ValueError):native.contract(cls,'a'*64,protocol=NATIVE_V2_PROTOCOL,control='idle')
        p=successor('night_lord')
        self.assertEqual([(s['slot'],s['skill_id']) for s in p['skills'][-2:]],[('SKILL_9',4111002),('SKILL_10',4121006)])
        self.assertIn('10 Summoning Rocks (item 4006001)',prompt_reference(p))
        self.assertIn('more than 960 ms',prompt_reference(successor('bowmaster')))
        self.assertIn({'skill_id':1120004,'level':30},successor('hero')['passives'])
        self.assertNotIn({'skill_id':1120004,'level':30},toolkit('hero')['passives'])

    def test_use_and_etc_are_independent_and_account_equipment_remain_unchanged(self):
        for cls in CLASSES:
            original=sql_fixture(cls).decode();cols,rows,_=table(original,'inventoryitems')
            unrelated=copy.deepcopy(rows[1]);unrelated.update(inventoryitemid='12',inventorytype='4',itemid='4000000',quantity='7')
            original=replace(original,'inventoryitems',rows+[unrelated]).encode()
            p=successor(cls);sql,expected=transform(original,p,verified_definitions(p))
            self.assertEqual(table(original.decode(),'accounts')[1],table(sql.decode(),'accounts')[1])
            old_equips=[r for r in table(original.decode(),'inventoryitems')[1] if r['inventorytype']=='-1']
            new_equips=[r for r in table(sql.decode(),'inventoryitems')[1] if r['inventorytype']=='-1']
            self.assertEqual(new_equips,old_equips)
            etc=[r for r in table(sql.decode(),'inventoryitems')[1] if r['inventorytype']=='4']
            self.assertEqual(expected['etc_inventory'],[[1,4006001,10]] if cls=='night_lord' else [])
            self.assertEqual(len(etc),1 if cls=='night_lord' else 0)
            self.assertEqual(expected['use_inventory'][0],[1,2000005,100])
            if cls=='night_lord':
                self.assertEqual(len(expected['use_inventory']),24)
                self.assertEqual(expected['use_inventory'][1:],[[i,2070006,800] for i in range(2,25)])
                self.assertIn([46,1,4111002],expected['keymap']);self.assertIn([47,1,4121006],expected['keymap'])
            legacy,_=transform(original,toolkit(cls),definitions(toolkit(cls)))
            self.assertIn(unrelated,table(legacy.decode(),'inventoryitems')[1])

    def test_wrong_rock_cost_stack_or_scalar_evidence_fails_closed(self):
        p=successor('night_lord')
        for mutate in (lambda d:d['items']['4006001'].update(nx_xml_scalar_match=False),
                       lambda d:d['items']['4006001']['info'].update(slotMax=9),
                       lambda d:d['skills']['4111002']['level_values'].update(itemCon=4006000),
                       lambda d:d['skills']['4111002']['level_values'].update(itemConNo=2),
                       lambda d:d['skills']['4121006']['level_values'].update(bulletConsume=801)):
            d=verified_definitions(p);mutate(d)
            with self.assertRaises(ValueError):transform(sql_fixture('night_lord'),p,d)
        self.assertEqual(etc_resource_stacks(p,verified_definitions(p)),[(4006001,10)])
        hero=successor('hero');d=verified_definitions(hero);d['skills']['1120004']['level_values']['x']=150
        with self.assertRaisesRegex(ValueError,'achilles_definition_not_verified'):transform(sql_fixture('hero'),hero,d)

    def test_real_asset_parser_reads_etc_and_new_skill_requirements_before_sql(self):
        for cls in CLASSES:
            with tempfile.TemporaryDirectory() as directory:
                assets,wz=asset_fixture(Path(directory).resolve(),cls)
                report=inspect(cls,assets,wz,policy_id=POLICY_V2_ID)
                _,expected=transform(sql_fixture(cls),successor(cls),report)
                self.assertEqual(expected['runtime_mutations'],0)
                if cls=='night_lord':
                    self.assertIn('Item.wz/Etc/0400.img.xml',report['source_files'])
                    self.assertEqual(report['items']['4006001']['info'],{'price':1})
                    path=wz/'Item.wz/Etc/0400.img.xml';tree=ET.parse(path)
                    tree.getroot().find('.//int[@name="price"]').set('value','99');tree.write(path)
                    with self.assertRaisesRegex(ValueError,'item_nx_xml_mismatch'):inspect(cls,assets,wz,policy_id=POLICY_V2_ID)

    def test_bridge_runs_only_exact_recipe_without_reading_credentials_or_calling_model(self):
        from test_full_client_native import NativeTests
        harness=NativeTests();harness.setUp()
        try:
            contract=native.contract('night_lord','a'*64,protocol=NATIVE_V2_PROTOCOL)
            with mock.patch('full_client_bridge.threading.Thread'):
                run=harness.bridge.start('script',None,120,**(harness.options|{'native_acceptance':contract}))
            def execute(code,scenario,base,**kwargs):
                self.assertEqual(code,native.program(contract));self.assertEqual(scenario['skill_toolkit'],contract['skill_toolkit'])
                self.assertEqual((kwargs['program_seconds'],kwargs['max_actions'],kwargs['max_requests']),(120,128,600))
                return {'reason':'program_complete','actions':0,'steps':[]}
            with mock.patch.object(harness.bridge,'_wait_for_capture'),mock.patch.object(harness.bridge,'request',return_value=harness.observation),\
                 mock.patch('full_client_bridge.execute_program',side_effect=execute),\
                 mock.patch('full_client_bridge.model_decision',side_effect=AssertionError('model forbidden')),\
                 mock.patch('full_client_bridge.read_private_file',side_effect=AssertionError('credentials forbidden')):
                harness.bridge._run(run)
            result=json.loads((harness.bridge.output/run['id']/'result.json').read_text())
            self.assertEqual(result['controller']['status'],'completed');self.assertEqual(result['model_api_requests'],0)
            self.assertIsNone(result['controller']['model']);self.assertEqual(result['nativeAcceptance'],contract)
        finally:harness.doCleanups()


@unittest.skipUnless(shutil.which('node'),'Node required')
class ToolkitRecipeTests(unittest.TestCase):
    def execute(self,cls,mode='near',latency=10):
        contract=native.contract(cls,'a'*64,protocol=NATIVE_V2_PROTOCOL)
        runner=r"""const calls=[];let elapsed=0,x=0,target=50;
Date.now=()=>elapsed;
const mode=MODE,latency=LATENCY;
const sdk={observe:async()=>{elapsed+=latency;calls.push({method:'observe',at:elapsed});
 return {character:{x,y:0,alive:mode!=='dead'},monsters:mode==='empty'?[]:[{objectId:1,x:mode==='distant'?x+1000:target,y:0}]};},
 pressKeys:async(keys,ms)=>{calls.push({method:'pressKeys',keys,ms,at:elapsed,targetDx:target-x});elapsed+=latency+ms;
 if(keys.length===1&&['LEFT','RIGHT'].includes(keys[0]))x+=(keys[0]==='LEFT'?-1:1)*ms/10;
 else if(mode==='alternating'&&keys.some(k=>k==='ATTACK'||k==='PRIMARY_SKILL'||k==='SKILL_5'||k==='SKILL_6'||k==='SKILL_7'))target=x+(target-x<0?50:-50);
 return {accepted:true};},wait:async ms=>{calls.push({method:'wait',ms,at:elapsed});elapsed+=latency+ms;}};
(async()=>{CODE})().then(()=>console.log(JSON.stringify({calls,elapsed}))).catch(e=>{console.error(e);process.exit(1)});
""".replace('MODE',json.dumps(mode)).replace('LATENCY',str(latency)).replace('CODE',native.program(contract))
        proc=subprocess.run(['node','-e',runner],check=True,capture_output=True,text=True,timeout=10)
        result=json.loads(proc.stdout);inputs=[c for c in result['calls'] if c['method']=='pressKeys']
        self.assertLessEqual(len(inputs),contract['max_actions']);self.assertLessEqual(len(result['calls']),contract['max_sdk_requests'])
        self.assertLess(result['elapsed'],contract['wall_seconds']*1000)
        for i,call in enumerate(result['calls']):
            args=[call['keys'],call['ms']] if call['method']=='pressKeys' else [call['ms']] if call['method']=='wait' else []
            validate_rpc({'type':'rpc','id':i+1,'method':call['method'],'args':args},{'adapter':'full-client',**sdk_scenario(contract)})
        return contract,result,inputs

    def test_every_slot_has_bounded_opportunity_and_effect_observations(self):
        for cls in CLASSES:
            contract,result,inputs=self.execute(cls);keys=[c['keys'] for c in inputs]
            for skill in contract['skill_toolkit']['skills']:self.assertTrue(any(skill['slot'] in k for k in keys),(cls,skill))
            self.assertIn(['ATTACK'],keys);self.assertIn(['HP_POTION'],keys);self.assertIn(['MP_POTION'],keys)
            for i,call in enumerate(result['calls']):
                if call['method']=='pressKeys' and not (len(call['keys'])==1 and call['keys'][0] in ('LEFT','RIGHT')):
                    self.assertEqual(result['calls'][i-1]['method'],'observe')
                    self.assertEqual([c['method'] for c in result['calls'][i+1:i+4]],['observe','wait','observe'])
            if cls=='bowmaster':
                self.assertEqual([c['ms'] for c in inputs if c['keys']==['PRIMARY_SKILL']],[1500])
            if cls=='hero':
                for finisher in ('SKILL_6','SKILL_7'):
                    stop=keys.index([finisher]);prior=keys[:stop]
                    start=prior.index(['SKILL_6'])+1 if finisher=='SKILL_7' else prior.index(['SKILL_5'])+1
                    self.assertEqual(prior[start:].count(['PRIMARY_SKILL']),4)
            if cls=='night_lord':
                self.assertLess(keys.index(['PRIMARY_SKILL']),keys.index(['SKILL_9']))
                self.assertLess(keys.index(['SKILL_9']),keys.index(['SKILL_10']))

    def test_target_motion_requires_new_facing_and_absent_targets_never_become_hits(self):
        for cls in CLASSES:
            contract,result,inputs=self.execute(cls,'alternating')
            attacks={s['slot'] for s in contract['skill_toolkit']['skills'] if s['route'] in ('attack','channel_attack','attack_movement')}|{'ATTACK'}
            for i,call in enumerate(inputs):
                if len(call['keys'])==1 and call['keys'][0] in attacks:
                    self.assertEqual(inputs[i-1]['keys'],['LEFT' if call['targetDx']<0 else 'RIGHT'])
                    self.assertEqual(inputs[i-1]['ms'],30)
            for mode in ('empty','distant'):
                _,_,other=self.execute(cls,mode)
                self.assertFalse(any(len(c['keys'])==1 and c['keys'][0] in attacks for c in other))
            self.assertEqual(self.execute(cls,'dead')[2],[])
            _,_,slow=self.execute(cls,'distant',350)
            self.assertTrue(all(c['at']<112000 for c in slow))

    def test_toolbar_routes_v2_slots_and_hold_without_changing_v1_or_unknown_authority(self):
        source=(ROOT/'ui/full-client/controller.js').read_text()
        a=source.index('const manualSkillBindings =');b=source.index('\n  for (const [text, code, ms]',a)
        c=source.index('const toolkit=run.adaptiveProtocol');d=source.index('    let ok=false;',c)
        prefix="const toolkitKeyNames={PRIMARY_SKILL:'KeyA',SECONDARY_SKILL:'KeyS',BUFF_1:'KeyD',BUFF_2:'KeyF',SKILL_5:'KeyG',SKILL_6:'KeyH',SKILL_7:'KeyZ',SKILL_8:'KeyX',SKILL_9:'KeyC',SKILL_10:'KeyV'};const skillKeyNames={PRIMARY_SKILL:'KeyA',SECONDARY_SKILL:'KeyS',BUFF_1:'KeyD',BUFF_2:'KeyF'};const keyNames={LEFT:'ArrowLeft'};"
        code=prefix+source[a:b]+"\nfunction route(run,command){"+source[c:d]+"return keys;}\n"
        for version in (POLICY_ID,POLICY_V2_ID,'unknown'):
            p=toolkit('bowmaster',policy_id=POLICY_V2_ID if version!=POLICY_ID else POLICY_ID);p['id']=version
            payload={'nativeAcceptance':{'skill_toolkit':p,'profile':{'skill_keys':{s['slot']:s['name'] for s in p['skills']}}}}
            proc=subprocess.run(['node','-e',code+'const run='+json.dumps(payload)+";console.log(JSON.stringify([manualSkillBindings(run),route(run,{keys:['SKILL_9','SKILL_10']})]));"],check=True,capture_output=True,text=True,timeout=10)
            bindings,keys=json.loads(proc.stdout)
            self.assertEqual(len(bindings),10)
            self.assertEqual(bindings[0]['ms'],1500 if version==POLICY_V2_ID else 500)
            self.assertEqual(keys,['KeyC','KeyV'] if version!='unknown' else [None,None])


if __name__=='__main__':unittest.main()
