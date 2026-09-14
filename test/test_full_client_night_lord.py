"""Night Lord contract/program tests use synthetic SDK observations, never a game."""
import copy,hashlib,json,sys,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import full_client_native as native
import full_client_adaptive as adaptive
import test_full_client_native as prior
from test_full_client_native_v3 import RecipeTests


class NightLordTests(unittest.TestCase):
 def test_explicit_new_class_does_not_add_historical_recipes(self):
  for protocol in (native.PROTOCOL,native.NATIVE_V2_PROTOCOL,native.NATIVE_V3_PROTOCOL):
   with self.subTest(protocol=protocol),self.assertRaisesRegex(ValueError,'night_lord_requires_native_v4'):
    native.contract('night_lord','a'*64,protocol=protocol)
  value=native.contract('night_lord','a'*64,protocol=native.NATIVE_V4_PROTOCOL)
  self.assertEqual(native.validate_contract(value),value)
  self.assertEqual(value['profile'],{'id':'night-lord-v1','class_name':'Night Lord','level':180,
   'skill_keys':{'PRIMARY_SKILL':'Triple Throw','SECONDARY_SKILL':'Avenger','BUFF_1':'Claw Booster','BUFF_2':'Haste'}})
  self.assertEqual([value[k] for k in ('wall_seconds','max_actions','max_sdk_requests','capture_max_ms')],[30,12,100,45000])
  altered=copy.deepcopy(value);altered['profile']['skill_keys']['BUFF_2']='Shadow Partner'
  with self.assertRaisesRegex(ValueError,'invalid_native_acceptance'):native.validate_contract(altered)

 def test_program_retains_finite_physical_inputs_and_no_hidden_replenishment(self):
  data=RecipeTests.execute(self,'night_lord','far_four',native.NATIVE_V4_PROTOCOL)
  keys=[call['args'][0] for call in data['calls'] if call['method']=='pressKeys']
  self.assertEqual(len(keys),12)
  self.assertEqual(keys.count(['PRIMARY_SKILL']),2)
  self.assertLess(keys.index(['BUFF_1']),keys.index(['PRIMARY_SKILL']))
  self.assertLess(keys.index(['BUFF_2']),keys.index(['PRIMARY_SKILL']))
  self.assertLess(max(i for i,k in enumerate(keys) if k==['PRIMARY_SKILL']),keys.index(['ATTACK']))
  self.assertEqual(keys[-1],['SECONDARY_SKILL'])
  self.assertEqual({call['method'] for call in data['calls']},{'observe','pressKeys','wait'})

 def test_departed_or_unreachable_target_does_not_become_claimed_primary(self):
  for behavior in ('none','out_of_range','cross_after_face','dy_51','distance_301'):
   data=RecipeTests.execute(self,'night_lord',behavior,native.NATIVE_V4_PROTOCOL)
   self.assertFalse(any(c['args']==[['PRIMARY_SKILL'],1200] for c in data['calls']))

 def test_adaptive_preset_binds_four_slots_and_original_model_budgets(self):
  profile=copy.deepcopy(native.PROFILES['night_lord'])
  protocol=adaptive.encoded_capture_cohort_protocol(profile)
  self.assertEqual(protocol['profile'],profile)
  self.assertEqual([protocol[k] for k in ('wall_seconds','program_seconds','max_api_requests','max_total_tokens')],[300,20,12,240000])
  instructions=adaptive.prompt(protocol)
  self.assertIn('Triple Throw',instructions);self.assertIn('Avenger',instructions)
  self.assertNotIn('Shadow Partner',instructions)
  self.assertEqual(adaptive.DEFAULT_PROTOCOL['profile']['class_name'],'Hero')

 def test_existing_private_no_model_and_capture_guards_apply_to_new_class(self):
  names=['test_native_start_requires_private_locks_and_no_model_contract',
   'test_native_worker_never_reads_api_key_or_calls_model',
   'test_native_protocol_is_rejected_by_model_trial_admission',
   'test_native_capture_policy_is_independent_and_not_accepted_as_api',
   'test_capture_bundle_verifies_native_timeline_without_fake_api_interval']
  def make_contract(cls,digest):return native.contract('night_lord',digest,protocol=native.NATIVE_V4_PROTOCOL)
  with mock.patch.object(prior,'contract',side_effect=make_contract),mock.patch.object(prior,'PROTOCOL',native.NATIVE_V4_PROTOCOL):
   result=unittest.TestResult()
   for name in names:prior.NativeTests(name).run(result)
  self.assertEqual(result.testsRun,len(names));self.assertFalse(result.errors,result.errors);self.assertFalse(result.failures,result.failures)


if __name__=='__main__':unittest.main()
