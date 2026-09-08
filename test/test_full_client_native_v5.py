"""Execute Hero v5 against synthetic moving targets; no actual game or model."""
import hashlib,json,shutil,subprocess,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import full_client_native as native
from maple_agent import validate_rpc
from test_full_client_native_v3 import V3ControlTests

class HeroV5Tests(unittest.TestCase):
 def execute(self,behavior):
  node=shutil.which('node')
  if not node:self.skipTest('Node is required for generated program execution')
  code=native.program(native.contract('hero','a'*64,protocol=native.NATIVE_V5_PROTOCOL))
  harness=r'''
const calls=[];let moves=0,faces=0,time=0,last='',postBuffReads=0,primaryDone=false;
function scene(){
 if(last==='BUFF_2')postBuffReads++;
 let x=80,y=0;
 if(behavior==='far_four')x=moves<4?400:80;
 if(behavior==='unreachable')x=400;
 if(behavior==='left_before_brandish'&&postBuffReads>=4)x=-80;
 if(behavior==='cross_after_face'&&faces>=1)x=-80;
 if(behavior==='drift_before_basic'&&primaryDone)x=-80;
 if(behavior==='depart_after_face'&&faces>=1)x=111;
 if(behavior==='high_after_face'&&faces>=1)y=46;
 if(behavior==='distance_110')x=110;
 if(behavior==='distance_111')x=111;
 if(behavior==='height_45')y=45;
 if(behavior==='height_46')y=46;
 let monsters=[{objectId:1,x,y}];
 if(behavior==='none'||(behavior==='vanish_after_face'&&faces>=1))monsters=[];
 if(behavior==='closest_same_height')monsters=[{objectId:1,x:-10,y:46},{objectId:2,x:95,y:0},{objectId:3,x:60,y:45}];
 return {ready:true,character:{x:0,y:0,hp:100,mp:100,level:180,alive:true},monsters};
}
const sdk={
 async observe(){const result=scene();calls.push({method:'observe',args:[],at:time,result});return result;},
 async wait(ms){calls.push({method:'wait',args:[ms],at:time});time+=ms;},
 async pressKeys(keys,ms){calls.push({method:'pressKeys',args:[keys,ms],at:time});time+=ms;last=keys[0];
  if(['LEFT','RIGHT'].includes(last)){if(ms===30)faces++;else moves++;}
  if(last==='PRIMARY_SKILL')primaryDone=true;
  return {accepted:true};}
};
(async()=>{await new (Object.getPrototypeOf(async function(){}).constructor)('sdk',code)(sdk);
 process.stdout.write(JSON.stringify({calls,time,completed:true,moves,faces}));})().catch(e=>{console.error(e);process.exitCode=1;});
'''
  raw=subprocess.run([node,'-e','const code='+json.dumps(code)+';const behavior='+json.dumps(behavior)+';'+harness],capture_output=True,text=True,timeout=10,check=True)
  data=json.loads(raw.stdout);self.assertTrue(data['completed'])
  for i,call in enumerate(data['calls'],1):validate_rpc({'type':'rpc','id':i,'method':call['method'],'args':call['args']},{'adapter':'full-client','protocol':native.NATIVE_V5_PROTOCOL})
  self.assertLessEqual(sum(c['method']=='pressKeys' for c in data['calls']),12)
  self.assertLessEqual(len(data['calls']),100);self.assertLessEqual(data['time'],30000)
  self.assertLessEqual(data['moves'],4);self.assertLessEqual(data['faces'],2)
  return data

 def attacks(self,data):return [c for c in data['calls'] if c['method']=='pressKeys' and c['args'][0] in (['PRIMARY_SKILL'],['ATTACK'])]

 def test_four_approach_steps_buffs_jump_and_two_fresh_attacks_fit_caps(self):
  data=self.execute('far_four');keys=[c['args'][0] for c in data['calls'] if c['method']=='pressKeys']
  self.assertEqual(len(keys),12);self.assertEqual(data['moves'],4)
  self.assertEqual(keys[:4],[['JUMP'],['SECONDARY_SKILL'],['BUFF_1'],['BUFF_2']])
  self.assertEqual([c['args'] for c in self.attacks(data)],[[['PRIMARY_SKILL'],1200],[['ATTACK'],600]])
  self.assertEqual({c['method'] for c in data['calls']},{'pressKeys','observe','wait'})

 def test_each_attack_has_adjacent_fresh_observation_and_facing_without_wait(self):
  calls=self.execute('far_four')['calls']
  for i,call in enumerate(calls):
   if call['method']=='pressKeys' and call['args'][0] in (['PRIMARY_SKILL'],['ATTACK']):
    self.assertEqual([c['method'] for c in calls[i-3:i]],['observe','pressKeys','observe'])
    self.assertEqual(calls[i-2]['args'][1],30)
    direction=calls[i-2]['args'][0][0];scene=calls[i-1]['result']
    self.assertTrue(any(abs(m['y'])<=45 and abs(m['x'])<=110 and (m['x']<=0 if direction=='LEFT' else m['x']>=0) for m in scene['monsters']))

 def test_brandish_aim_uses_target_that_crossed_after_initial_approach(self):
  calls=self.execute('left_before_brandish')['calls'];i=next(i for i,c in enumerate(calls) if c['args']==[['PRIMARY_SKILL'],1200])
  self.assertEqual(calls[i-2]['args'],[['LEFT'],30])

 def test_basic_attack_reaims_after_brandish_when_target_crosses(self):
  calls=self.execute('drift_before_basic')['calls'];primary=next(i for i,c in enumerate(calls) if c['args']==[['PRIMARY_SKILL'],1200]);basic=next(i for i,c in enumerate(calls) if c['args']==[['ATTACK'],600])
  self.assertLess(primary,basic);self.assertEqual(calls[primary-2]['args'],[['RIGHT'],30]);self.assertEqual(calls[basic-2]['args'],[['LEFT'],30])

 def test_departed_crossed_or_high_post_face_target_skips_brandish(self):
  for behavior in ('cross_after_face','depart_after_face','high_after_face','vanish_after_face'):
   with self.subTest(behavior=behavior):self.assertFalse(any(c['args'][0]==['PRIMARY_SKILL'] for c in self.attacks(self.execute(behavior))))

 def test_no_target_unreachable_or_wrong_height_does_not_attack_or_chase_again(self):
  for behavior in ('none','unreachable','height_46','distance_111'):
   with self.subTest(behavior=behavior):self.assertFalse(self.attacks(self.execute(behavior)))

 def test_position_boundaries_and_nearest_same_height(self):
  for behavior in ('distance_110','height_45','closest_same_height'):
   with self.subTest(behavior=behavior):self.assertEqual(len(self.attacks(self.execute(behavior))),2)

 def test_v5_is_hero_only_and_leaves_default_and_caps_unchanged(self):
  self.assertEqual(native.contract('hero','a'*64)['id'],native.NATIVE_V2_PROTOCOL)
  value=native.contract('hero','a'*64,protocol=native.NATIVE_V5_PROTOCOL)
  self.assertEqual(native.validate_contract(value),value)
  self.assertEqual([value[k] for k in ('wall_seconds','max_actions','max_sdk_requests','capture_max_ms')],[30,12,100,45000])
  for cls in ('bowmaster','ice_lightning_arch_mage'):
   with self.assertRaisesRegex(ValueError,'native_v5_requires_hero'):native.contract(cls,'a'*64,protocol=native.NATIVE_V5_PROTOCOL)

 def test_v5_retains_native_no_api_identity_and_capture_guard(self):
  V3ControlTests.verify_guards(self,native.NATIVE_V5_PROTOCOL)

 def test_v1_and_v4_frozen_program_bytes_stay_unchanged(self):
  # Measured from the parent source before adding v5; v2/v3 fingerprints also
  # have their existing independent regressions in test_full_client_native_v3.
  expected={native.PROTOCOL:{'hero':'01d2efa4d4d5768a17cc52824ce4e91fa2eb82f7378214053c587d5d9e790086','bowmaster':'f9746c8db2fa69028ce7fb89fcf775b75f24e6b53178146b91206a421b6a6124','ice_lightning_arch_mage':'8dc03f0185e3059ad577c68d6b35ea716796b4b59defdd717d5ec447142408f0'},
   native.NATIVE_V4_PROTOCOL:{'hero':'35dce2d10d8ded8af2ab8ec4ce5ef07e2f28fbbc8e554f0bdfa381e01a05df11','bowmaster':'ef1048a8a1f73f6bd357d95ac4ff254296aba7b04155379f5eeb1cdc6be3b65d','ice_lightning_arch_mage':'697daf15459f4011fd8a9c7a859131ed1cca9397a44acc7b759382c707fb3dd0'}}
  for protocol,classes in expected.items():
   for cls,want in classes.items():self.assertEqual(hashlib.sha256(native.program(native.contract(cls,'a'*64,protocol=protocol)).encode()).hexdigest(),want)

if __name__=='__main__':unittest.main()
