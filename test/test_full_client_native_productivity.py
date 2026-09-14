"""Fake-clock/SDK control tests; no model, game, database or native wrapper."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from full_client_native import PRODUCTIVITY_PROTOCOL, contract, program, validate_contract
from full_client_skill_toolkit import sdk_scenario
from maple_agent import validate_rpc
import test_full_client_native_xp_inventory as inventory_tests
import full_client_native_xp_inventory as inventory

class ProductivityTests(unittest.TestCase):
 def config(self,control='active'):
  return contract('bowmaster','a'*64,protocol=PRODUCTIVITY_PROTOCOL,control=control)
 def test_exact_opt_in_caps_and_sdk(self):
  c=self.config();self.assertEqual((c['wall_seconds'],c['max_actions'],c['max_sdk_requests'],c['capture_max_ms']),(120,128,600,125000))
  for field in ('wall_seconds','max_actions','max_sdk_requests','capture_max_ms'):
   bad=copy.deepcopy(c);bad[field]+=1
   with self.assertRaises(ValueError):validate_contract(bad)
  for key in ('PRIMARY_SKILL','BUFF_1','SKILL_7','HP_POTION'):
   validate_rpc({'type':'rpc','id':1,'method':'pressKeys','args':[[key],100]}, {'adapter':'full-client',**sdk_scenario(c)})
  with self.assertRaises(ValueError):validate_rpc({'type':'rpc','id':1,'method':'pressKeys','args':[['D'],100]}, {'adapter':'full-client',**sdk_scenario(c)})
  with self.assertRaises(ValueError):contract('hero','a'*64,control='idle')
 def run_code(self,mode='normal',control='active'):
  node=shutil.which('node')
  if not node:self.skipTest('Node required for real JS fake-clock execution')
  code=program(self.config(control))
  harness=r'''
let now=0,calls=0,observes=0,actions=[],waits=[];Date.now=()=>now;
const mode=MODE;
const sdk={wait:async(ms)=>{calls++;waits.push(ms);now+=ms;},
 pressKeys:async(keys,ms)=>{calls++;actions.push({keys,at:now});now+=ms;return {accepted:mode!=='reject'};},
 observe:async()=>{calls++;observes++;now+=10;
 const turned=actions.some(x=>['LEFT','RIGHT'].includes(x.keys[0]));
 let monsters=[{objectId:7,x:200,y:0},{objectId:8,x:turned?-1:230,y:0}];
 if(mode==='height'&&turned)monsters=[{objectId:7,x:200,y:100}];
 if(mode==='cross'&&turned){const last=actions.filter(x=>['LEFT','RIGHT'].includes(x.keys[0])).slice(-1)[0];monsters=[{objectId:7,x:last.keys[0]==='RIGHT'?-200:200,y:0}];}
 if(mode==='empty')monsters=[];
 if(mode==='dead')return {character:{alive:false},monsters:[]};
 const needsPotion=mode==='potion'&&!actions.some(x=>x.keys[0]==='HP_POTION');
 return {character:{alive:true,x:0,y:0,hp:needsPotion?10:100,maxHp:100,mp:100,maxMp:100},monsters};}};
(async()=>{let error=null;try{await (async()=>{CODE})();}catch(e){error=e.message;}
console.log(JSON.stringify({now,calls,actions,waits,observes,error}));})();
'''.replace('MODE',json.dumps(mode)).replace('CODE',code)
  p=subprocess.run([node,'-e',harness],check=True,capture_output=True,text=True,timeout=5)
  return json.loads(p.stdout)
 def test_active_sticky_target_and_hard_caps(self):
  x=self.run_code();self.assertIsNone(x['error']);self.assertLessEqual(x['now'],120000);self.assertLessEqual(x['calls'],600);self.assertLessEqual(len(x['actions']),128)
  self.assertTrue(any(a['keys']==['PRIMARY_SKILL'] for a in x['actions']))
  # Target8 becomes closer after turning, but target7 remains selected:
  # facing stays RIGHT instead of chasing new nearest-target positions.
  self.assertTrue(all(a['keys']!=['LEFT'] for a in x['actions']))
  self.assertGreater(x['observes'],len([a for a in x['actions'] if a['keys']==['PRIMARY_SKILL']]))
 def test_idle_no_actions_and_equal_observation_horizon(self):
  x=self.run_code(control='idle');self.assertEqual(x['actions'],[]);self.assertGreater(x['now'],110000);self.assertLessEqual(x['now'],120000);self.assertLessEqual(x['calls'],600)
 def test_potion_and_reobservation_gates(self):
  x=self.run_code('potion');self.assertTrue(any(a['keys']==['HP_POTION'] for a in x['actions']))
  for mode in ('height','cross','empty','dead'):
   x=self.run_code(mode);self.assertFalse(any(a['keys']==['PRIMARY_SKILL'] for a in x['actions']),mode)
 def test_negative_ack_aborts_without_input_retry(self):
  x=self.run_code('reject');self.assertEqual(x['error'],'control_input_not_accepted');self.assertEqual(len(x['actions']),1)
 def test_inventory_identity_cleanup_not_class_qualification(self):
  helper=inventory_tests.InventoryTests();_,raw,items=helper.fixture('bowmaster')
  for control in ('active','idle'):
   native=contract('bowmaster',hashlib.sha256(raw).hexdigest(),protocol=PRODUCTIVITY_PROTOCOL,control=control)
   self.assertEqual(inventory.expected(native,raw,character_id=5,account_id=2),items)
   value=helper.snapshot(native,items,'after_restore',300)
   self.assertEqual(value['protocol'],PRODUCTIVITY_PROTOCOL);self.assertEqual(value['native_acceptance_id'],helper.identity['run_id']);self.assertIsNone(value['model']);self.assertEqual(value['api_calls'],0)
   args=dict(native=native,baseline_sql=raw,identity=helper.identity,runtime_manifest_sha256=helper.runtime_hash)
   self.assertEqual(inventory.verify_restored(value,**args),{'inventory_restored':True,'class_accepted':False})
   with self.assertRaisesRegex(ValueError,'toolkit_owner_required'):
    inventory.verify_triplet(value,value,value,**args,session={},reset={},final_db={})
 def test_bridge_private_120s_admission_and_no_model(self):
  import test_full_client_native as native_tests
  from unittest.mock import patch
  from full_client_bridge import ControlError
  h=native_tests.NativeTests();h.setUp();self.addCleanup(h.doCleanups)
  options=h.options|{'native_acceptance':self.config()}
  with patch('full_client_bridge.threading.Thread'):
   for duration in (60,119,121):
    with self.assertRaisesRegex(ControlError,'native_acceptance_private_contract_required'):
     h.bridge.start('script',None,duration,**options)
   with self.assertRaisesRegex(ControlError,'native_acceptance_private_contract_required'):
    h.bridge.start('api','gpt-6-astra',120,**options)
   value=h.bridge.start('script',None,120,**options)
  self.assertIsNone(value['model']);self.assertEqual(value['programSeconds'],120)
  self.assertEqual(value['nativeAcceptance']['max_sdk_requests'],600)
 def test_owned_inventory_collection_preserves_productivity_id(self):
  import tempfile
  helper=inventory_tests.InventoryTests()
  with tempfile.TemporaryDirectory() as d:
   backend=helper.backend(Path(d).resolve())
   backend.native=contract(backend.native['class_id'],backend.native['baseline_sha256'],protocol=PRODUCTIVITY_PROTOCOL,control='idle')
   deadline=backend.host.deadline
   value=inventory.collect_owned(backend,'after_logout')
   self.assertEqual(value['protocol'],PRODUCTIVITY_PROTOCOL)
   self.assertEqual(value['native_acceptance_id'],backend.run_id)
   self.assertEqual(backend.host.deadline,deadline)
   backend.disconnect.assert_called_once();self.assertEqual(backend.safe_boundary.call_count,3)
 def test_encoded_publication_keeps_script_identity_and_rejects_api(self):
  import test_full_client_native as native_tests
  from unittest.mock import patch
  h=native_tests.NativeTests();h.setUp();self.addCleanup(h.doCleanups);h.config=self.config('idle')
  with patch.object(native_tests,'PROTOCOL',PRODUCTIVITY_PROTOCOL):
   h.test_capture_bundle_verifies_native_timeline_without_fake_api_interval()
 def test_model_trial_admission_rejects_productivity(self):
  from full_client_trial import validate_spec,TrialError
  with self.assertRaisesRegex(TrialError,'unsupported_protocol'):
   validate_spec({'schema_version':2,'protocol':PRODUCTIVITY_PROTOCOL,'model':'gpt-6-astra','scenario_fingerprint':'a'*64,'baseline_sha256':'b'*64,'budgets':{}})

 def test_all_historical_contract_and_program_bytes(self):
  pins={'scripted-native-acceptance-v1|hero': ['51501e8d323dbaffcfd551f78186199bfb1da386be2b95aea909487771ef7909', '01d2efa4d4d5768a17cc52824ce4e91fa2eb82f7378214053c587d5d9e790086'], 'scripted-native-acceptance-v1|bowmaster': ['a68f240ab716b33ae0849c32034a8d7e5245b854e0e247bd846dd9df62331763', 'f9746c8db2fa69028ce7fb89fcf775b75f24e6b53178146b91206a421b6a6124'], 'scripted-native-acceptance-v1|ice_lightning_arch_mage': ['d15ffe28e773e77e5d77dfc830817703c4ea7a2e35beaf8c31994be1f043053d', '8dc03f0185e3059ad577c68d6b35ea716796b4b59defdd717d5ec447142408f0'], 'scripted-native-acceptance-v2|hero': ['d5de06edbb276baa600e255102372735bd3dbf9822935fde20aa095a6ec62878', '35dce2d10d8ded8af2ab8ec4ce5ef07e2f28fbbc8e554f0bdfa381e01a05df11'], 'scripted-native-acceptance-v2|bowmaster': ['e1efe469383f3d947958ef97efd2ff6622ad1bb008c5b37768a2626a83afd212', 'e605d3b65e1caa0554e55c9aef5d9a026ae17538bcd79aed8115dbb0d70aa01b'], 'scripted-native-acceptance-v2|ice_lightning_arch_mage': ['163930fd925e3af4931f634a69ba6e8ad86c2a1e5548cc9fd02ce30136856651', '38a26e497857b9852e02cb3cc90faefd6770e713654d2c76e6e7ab4073f45158'], 'scripted-native-acceptance-v3|hero': ['1a7366035135043f7bb94ee50ea3906110ec272552e74ad8085cae06ac547409', '35dce2d10d8ded8af2ab8ec4ce5ef07e2f28fbbc8e554f0bdfa381e01a05df11'], 'scripted-native-acceptance-v3|bowmaster': ['f5545451e7adcc5348e5f2f845ab71f2af9153b65a412794813b516967876fdc', '7cdc0f151a2eb35782b0788358af208699b2cc9d256c71e9795514afed9c858d'], 'scripted-native-acceptance-v3|ice_lightning_arch_mage': ['6613d8001739b1173ddbfeff3199b35d6c5bd5eee01bee1d669922208db1e497', 'b8127a06cda14bb1ab815b35d8f057df9c55c7c97232376c6df733c0338dba74'], 'scripted-native-acceptance-v4|hero': ['580edb765e3ed1458715e354e0b2377ebcee57d74a42d4d368fbd40e817533db', '35dce2d10d8ded8af2ab8ec4ce5ef07e2f28fbbc8e554f0bdfa381e01a05df11'], 'scripted-native-acceptance-v4|bowmaster': ['04b48ae72705a1a6c99e967e35c117dc7687516818a696b1e35fb65fa1427ca8', 'ef1048a8a1f73f6bd357d95ac4ff254296aba7b04155379f5eeb1cdc6be3b65d'], 'scripted-native-acceptance-v4|ice_lightning_arch_mage': ['f9365a44fd97e971c9c93964ec470a70c08b7301303ffd815f2826f4bb345044', '697daf15459f4011fd8a9c7a859131ed1cca9397a44acc7b759382c707fb3dd0'], 'scripted-native-acceptance-v4|night_lord': ['7b17ef7db7af2e6586084f690b90a478c3b6ca257c1b554ed742b69d52645e14', 'ef1048a8a1f73f6bd357d95ac4ff254296aba7b04155379f5eeb1cdc6be3b65d'], 'scripted-native-toolkit-acceptance-v1|hero': ['2692a2a946fed60b040cb405d013f5435dfbadba909c620a9e3441ccf41d1e0b', '968604896c75bfbd3b25f9a0076e937a9324552d7653b2c08517e15a37702909'], 'scripted-native-toolkit-acceptance-v1|bowmaster': ['e953833c250e0b4a3839a02495b0ae4842ed0e377266cf09f6654b56d78fa30a', 'bbab3eaf4d4bac5af0eefb03760c46f49782dd0e4361bfa2ac32b558cdd630b2'], 'scripted-native-toolkit-acceptance-v1|ice_lightning_arch_mage': ['8b3567dce5e7c90c38eae4fa83cbc651435cd61178e76aac2e0e0d9ce2519d01', 'b54e4cacd433551043d1f6594f5de2580737e307eea57a2cb5c24ff24b68851c'], 'scripted-native-toolkit-acceptance-v1|night_lord': ['67c7de87ccee3a95179d5814c287195e1d56e097ecddde86149659bcdcff77f5', '3d47c6e13675afd85016ffee80c84b0b91c0a7562027bdbde09cc1c4e1e7c153']}
  for key,expected in pins.items():
   proto,cls=key.split("|");c=contract(cls,"a"*64,protocol=proto)
   self.assertEqual([hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest(),hashlib.sha256(program(c).encode()).hexdigest()],expected)
