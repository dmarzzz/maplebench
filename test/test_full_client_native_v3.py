"""Execute the frozen native recipe against observed-position fixtures, never a game."""
import hashlib,json,shutil,subprocess,sys,unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import full_client_native as native
import test_full_client_native as prior
from maple_agent import validate_rpc


class RecipeTests(unittest.TestCase):
 def execute(self,class_id='ice_lightning_arch_mage',behavior='near',protocol=None):
  node=shutil.which('node')
  if not node:self.skipTest('Node is required to execute the generated program')
  protocol=protocol or native.NATIVE_V3_PROTOCOL
  code=native.program(native.contract(class_id,'a'*64,protocol=protocol))
  harness=r'''
const calls=[];let movements=0,afterMovement=0,time=0;
function observation(){
 let x=80;
 if(behavior.startsWith('distance_'))x=Number(behavior.slice(9));
 if(behavior==='far_four')x=movements<4?400:80;
 if(behavior==='cross_before_face'&&movements>=1&&afterMovement>=1)x=-80;
 if(behavior==='cross_before_face'&&movements>=2)x=-80;
 if(behavior==='cross_after_face'&&movements>=2)x=-80;
 if(behavior==='out_of_range'&&movements>=1&&afterMovement>=1)x=400;
 afterMovement++;
 return {ready:true,character:{x:0,y:0,hp:100,mp:100,level:180,alive:true},
  monsters:behavior==='none'?[]:[{objectId:1,x,y:behavior==='dy_48'?48:behavior==='dy_51'?51:0}]};
}
const sdk={
 async observe(){calls.push({method:'observe',args:[],at:time});return observation();},
 async wait(ms){calls.push({method:'wait',args:[ms],at:time});time+=ms;},
 async pressKeys(keys,ms){calls.push({method:'pressKeys',args:[keys,ms],at:time});time+=ms;
  if(keys.length===1&&['LEFT','RIGHT'].includes(keys[0])){movements++;afterMovement=0;}
  return {accepted:true};}
};
(async()=>{await new (Object.getPrototypeOf(async function(){}).constructor)('sdk',code)(sdk);
 process.stdout.write(JSON.stringify({calls,time,completed:true}));})().catch(e=>{console.error(e);process.exitCode=1;});
'''
  result=subprocess.run([node,'-e','const code='+json.dumps(code)+';const behavior='+json.dumps(behavior)+';'+harness],capture_output=True,text=True,timeout=10,check=True)
  data=json.loads(result.stdout);self.assertTrue(data['completed'])
  for index,call in enumerate(data['calls'],1):
   validate_rpc({'type':'rpc','id':index,'method':call['method'],'args':call['args']},
                {'adapter':'full-client','protocol':protocol})
  self.assertLessEqual(len(data['calls']),100)
  self.assertLessEqual(sum(c['method']=='pressKeys' for c in data['calls']),12)
  self.assertLessEqual(data['time'],30000)
  return data

 def test_full_four_step_path_stays_within_original_caps(self):
  for cls in ('bowmaster','ice_lightning_arch_mage'):
   with self.subTest(cls=cls):
    d=self.execute(cls,'far_four');keys=[c['args'][0] for c in d['calls'] if c['method']=='pressKeys']
    self.assertEqual(len(keys),12)
    self.assertEqual(keys.count(['PRIMARY_SKILL']),2)
    self.assertLess(keys.index(['BUFF_1']),keys.index(['PRIMARY_SKILL']))
    self.assertLess(keys.index(['PRIMARY_SKILL']),keys.index(['ATTACK']))
    self.assertLess(max(i for i,k in enumerate(keys) if k==['PRIMARY_SKILL']),keys.index(['ATTACK']))

 def test_fresh_aim_faces_target_that_crossed_after_approach(self):
  calls=self.execute(behavior='cross_before_face')['calls']
  first=next(i for i,c in enumerate(calls) if c['args']==[['PRIMARY_SKILL'],1200])
  self.assertEqual(calls[first-2]['args'],[['LEFT'],30])
  self.assertEqual(calls[first-1]['method'],'observe')
  self.assertNotIn('wait',[c['method'] for c in calls[first-2:first]])
  self.assertEqual(next(c for c in calls if c['method']=='pressKeys' and 'SECONDARY_SKILL' in c['args'][0])['args'],[['LEFT','SECONDARY_SKILL'],300])

 def test_no_target_or_departed_target_does_not_trigger_primary(self):
  for behavior in ('none','out_of_range','cross_after_face','dy_51'):
   with self.subTest(behavior=behavior):
    calls=self.execute(behavior=behavior)['calls']
    self.assertFalse(any(c['method']=='pressKeys' and c['args'][0]==['PRIMARY_SKILL'] for c in calls))

 def test_native_default_vertical_extent_keeps_observed_48_pixel_target(self):
  calls=self.execute(behavior='dy_48')['calls']
  self.assertEqual(sum(c['method']=='pressKeys' and c['args'][0]==['PRIMARY_SKILL'] for c in calls),2)

 def test_teleport_has_direction_and_adjacent_observations(self):
  calls=self.execute()['calls'];i=next(i for i,c in enumerate(calls) if c['method']=='pressKeys' and 'SECONDARY_SKILL' in c['args'][0])
  self.assertEqual(calls[i]['args'],[['RIGHT','SECONDARY_SKILL'],300])
  self.assertEqual(calls[i-1]['method'],'observe')
  self.assertEqual(calls[i+1]['method'],'wait');self.assertEqual(calls[i+2]['method'],'observe')
  bow=self.execute('bowmaster')['calls']
  self.assertIn([['SECONDARY_SKILL'],600],[c['args'] for c in bow])

 def test_explicit_opt_in_preserves_hero_and_v2_hashes(self):
  # Expected values below are frozen before this revision, not derived from it.
  expected=V2_HASHES
  for cls,(code_hash,contract_hash) in expected.items():
   v2=native.contract(cls,'a'*64)
   self.assertEqual(v2['id'],native.NATIVE_V2_PROTOCOL)
   self.assertEqual(hashlib.sha256(native.program(v2).encode()).hexdigest(),code_hash)
   self.assertEqual(native.fingerprint(v2),contract_hash)
   v3=native.contract(cls,'a'*64,protocol=native.NATIVE_V3_PROTOCOL)
   self.assertEqual({k:v3[k] for k in ('wall_seconds','max_actions','max_sdk_requests','capture_max_ms')},
                    {'wall_seconds':30,'max_actions':12,'max_sdk_requests':100,'capture_max_ms':45000})
   if cls=='hero':self.assertEqual(native.program(v3),native.program(v2))


class V3ControlTests(unittest.TestCase):
 def test_existing_native_guards_and_capture_verifier_apply_to_v3(self):
  self.verify_guards(native.NATIVE_V3_PROTOCOL)

 def test_existing_native_guards_and_capture_verifier_apply_to_v4(self):
  self.verify_guards(native.NATIVE_V4_PROTOCOL)

 def verify_guards(self,protocol):
  # Run actual existing bridge/socket/capture tests with the explicit V3 contract.
  names=['test_native_start_requires_private_locks_and_no_model_contract',
   'test_native_worker_never_reads_api_key_or_calls_model',
   'test_native_protocol_is_rejected_by_model_trial_admission',
   'test_native_capture_policy_is_independent_and_not_accepted_as_api',
   'test_capture_bundle_verifies_native_timeline_without_fake_api_interval']
  def contract(cls,digest):return native.contract(cls,digest,protocol=protocol)
  with mock.patch.object(prior,'contract',side_effect=contract),mock.patch.object(prior,'PROTOCOL',protocol):
   result=unittest.TestResult()
   for name in names:prior.NativeTests(name).run(result)
  self.assertEqual(result.testsRun,len(names));self.assertFalse(result.errors,result.errors);self.assertFalse(result.failures,result.failures)

class V4RangeTests(unittest.TestCase):
 def test_actual_150_pixel_target_and_boundary_receive_primary_but_301_does_not(self):
  for cls in ('bowmaster','ice_lightning_arch_mage'):
   for distance,expected in ((150,2),(300,2),(301,0)):
    with self.subTest(cls=cls,distance=distance):
     data=RecipeTests.execute(self,cls,'distance_'+str(distance),native.NATIVE_V4_PROTOCOL)
     self.assertEqual(sum(c['method']=='pressKeys' and c['args'][0]==['PRIMARY_SKILL'] for c in data['calls']),expected)
  prior_result=RecipeTests.execute(self,behavior='distance_150')
  self.assertFalse(any(c['args']==[['PRIMARY_SKILL'],1200] for c in prior_result['calls']))

 def test_v4_retains_worst_case_action_sdk_and_time_caps(self):
  for cls in ('bowmaster','ice_lightning_arch_mage'):
   data=RecipeTests.execute(self,cls,'far_four',native.NATIVE_V4_PROTOCOL)
   self.assertEqual(sum(c['method']=='pressKeys' for c in data['calls']),12)

 def test_v3_bytes_unchanged_and_v4_only_changes_header_and_horizontal_limit(self):
  expected={
   'hero':('35dce2d10d8ded8af2ab8ec4ce5ef07e2f28fbbc8e554f0bdfa381e01a05df11','6839cdd56919ed4aa9dd3e679f84645be10664a970317f78e1c3f53b1ea19e7c'),
   'bowmaster':('7cdc0f151a2eb35782b0788358af208699b2cc9d256c71e9795514afed9c858d','bf23b1475890e800c3dfb69a9ca72058cabd50c74beeb1c458fe9b26ce638cc7'),
   'ice_lightning_arch_mage':('b8127a06cda14bb1ab815b35d8f057df9c55c7c97232376c6df733c0338dba74','0b79a9788b0adb6d8076d894e41a4076b7d152c09901446b52bbc3400fbb9af9')}
  for cls,(program_hash,contract_hash) in expected.items():
   v3=native.contract(cls,'a'*64,protocol=native.NATIVE_V3_PROTOCOL)
   v4=native.contract(cls,'a'*64,protocol=native.NATIVE_V4_PROTOCOL)
   before,after=native.program(v3),native.program(v4)
   self.assertEqual(hashlib.sha256(before.encode()).hexdigest(),program_hash)
   self.assertEqual(native.fingerprint(v3),contract_hash)
   self.assertEqual(v4|{'id':v3['id']},v3)
   self.assertEqual(native.contract(cls,'a'*64)['id'],native.NATIVE_V2_PROTOCOL)
   self.assertEqual(after,before if cls=='hero' else before.replace('acceptance v3;','acceptance v4;').replace('<=110','<=300'))


V2_HASHES = {
 'hero':('35dce2d10d8ded8af2ab8ec4ce5ef07e2f28fbbc8e554f0bdfa381e01a05df11','ea9d5789767a7fdb8d193a76ea7f9ab3714e309e6fe35bf12c319b8d2af25add'),
 'bowmaster':('e605d3b65e1caa0554e55c9aef5d9a026ae17538bcd79aed8115dbb0d70aa01b','ae657b8e3f16a765b5088455c92a45b936cb66d8ff1c10b0061dcbe107eef5aa'),
 'ice_lightning_arch_mage':('38a26e497857b9852e02cb3cc90faefd6770e713654d2c76e6e7ab4073f45158','bdc80a1dd8e5ff34e073dd9e7f3cf903c658dcd086d5a1cbc6b1a9e57086bf95'),
}

if __name__=='__main__':unittest.main()
