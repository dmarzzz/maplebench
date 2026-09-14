"""Next-policy scheduling/receipts only; no game, provider or remote containers."""
import copy,json,tempfile,unittest
from test_full_client_adaptive import Harness,MODEL
import full_client_adaptive as a
from full_client_adaptive_evidence import verify_result
from full_client_score import EvidenceError
class FinalSlotTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.h=Harness(self.tmp.name,calls=12)
  self.h.p=a.final_slot_cohort_protocol(self.h.p['profile']);self.h.program_seconds=1000
 def run_policy(self,**kw):return self.h.run(sleep=lambda n:setattr(self.h,'now',self.h.now+n),**kw)['trace']
 def verify(self):return verify_result(self.h.result(),self.h.root,protocol=self.h.p,model=MODEL)
 def test_final_executes_to_settlement_and_verifies(self):
  t=self.run_policy();self.verify();self.assertEqual(t['reason'],'final_program_complete');self.assertEqual(t['horizon_wait']['started_ms'],295000)
  self.assertEqual([c['execution_slot']['kind'] for c in t['cycles']],['ordinary']*5+['final'])
  self.assertEqual(self.h.programs[-1][1]['program_seconds'],135);self.assertEqual(self.h.programs[-1][1]['deadline'],295)
  self.assertEqual(t['timing']['wall_elapsed_ms'],300000)
 def test_slow_full_timeout_still_preserves_absolute_deadline(self):
  self.h.api_seconds=50;t=self.run_policy();self.verify();self.assertEqual(t['horizon_wait']['started_ms'],295000);self.assertTrue(all(x[1]==50 for x in self.h.api_calls));self.assertLessEqual(t['counters']['api_requests_started'],12)
 def test_last_request_is_final_even_with_time_remaining(self):
  self.h.p['max_api_requests']=1;t=self.run_policy();self.verify();self.assertEqual(len(self.h.api_calls),1);self.assertEqual(self.h.programs[0][1]['program_seconds'],145)
 def test_early_return_is_not_replayed(self):
  self.h.p['max_api_requests']=1;self.h.program_seconds=1;t=self.run_policy();self.verify();self.assertEqual(len(self.h.programs),1);self.assertEqual(t['horizon_wait']['started_ms'],11000)
 def test_no_retry_uncertain_request(self):
  def fail(*args):self.h.api_calls.append(args);self.h.now+=50;raise TimeoutError()
  t=self.run_policy(request_api=fail);self.assertEqual(t['status'],'failed');self.assertEqual(t['counters']['api_requests_started'],1);self.assertEqual(t['cycles'][0]['api_outcome'],'uncertain');self.assertEqual(len(self.h.api_calls),1)
 def test_action_budget_stops_before_new_request(self):
  self.h.p['max_actions']=1;t=self.run_policy();self.verify();self.assertEqual(t['reason'],'action_limit');self.assertEqual(len(self.h.api_calls),1)
 def test_policy_bounds_and_legacy_defaults_unchanged(self):
  self.assertNotIn('horizon_policy',a.DEFAULT_PROTOCOL)
  p=copy.deepcopy(self.h.p);p['horizon_policy']['final_program_max_seconds']=146
  with self.assertRaises(a.AdaptiveError):a.validate_protocol(p)
  p=copy.deepcopy(self.h.p);p['program_seconds']=21
  with self.assertRaises(a.AdaptiveError):a.validate_protocol(p)
 def test_slot_thresholds(self):
  self.assertEqual(a.final_slot_offer(150,12)['kind'],'final');self.assertEqual(a.final_slot_offer(150.001,12)['kind'],'ordinary');self.assertEqual(a.final_slot_offer(75,12)['admission_seconds'],75)
 def test_forged_final_budget_rejected(self):
  self.run_policy();r=self.h.result();r['adaptive']['cycles'][-1]['execution_budget']['program_seconds']=146;r['adaptiveTrace']=self.h.save('adaptive.json',r['adaptive'])
  with self.assertRaises(EvidenceError):verify_result(r,self.h.root,protocol=self.h.p,model=MODEL)
 def test_old_policy_cannot_accept_new_trace(self):
  self.run_policy();r=self.h.result();old=copy.deepcopy(self.h.p);old['horizon_policy']=a.FULL_HORIZON_POLICY
  with self.assertRaises(EvidenceError):verify_result(r,self.h.root,protocol=old,model=MODEL)
if __name__=='__main__':unittest.main()

class FinalSlotFaultTests(unittest.TestCase):
 setUp=FinalSlotTests.setUp
 run_policy=FinalSlotTests.run_policy
 def test_slow_persistence_closes_unsent_window_without_charge(self):
  self.h.p['max_api_requests']=1
  def persist(name,value):
   if name.endswith('api-request.json'):self.h.now=226
   return self.h.save(name,value)
  t=self.run_policy(persist_json=persist);self.assertEqual(t['reason'],'request_window_closed');self.assertEqual(len(self.h.api_calls),0);self.assertEqual(t['counters']['api_requests_started'],0);self.assertEqual(t['timing']['wall_elapsed_ms'],300000)
 def test_cancellation_during_final_never_reissues(self):
  self.h.p['max_api_requests']=1
  def execute(*args,**kwargs):raise a.AdaptiveError('cancelled')
  t=self.run_policy(execute=execute);self.assertEqual(t['status'],'failed');self.assertEqual(t['reason'],'cancelled');self.assertEqual(len(self.h.api_calls),1)
 def test_reservation_cap_prevents_even_first_call(self):
  self.h.p['max_total_tokens']=1024;t=self.run_policy();self.assertEqual(t['reason'],'token_reservation_limit');self.assertEqual(len(self.h.api_calls),0);self.assertEqual(t['counters']['reserved_tokens'],0)
 def test_invalid_final_program_consumes_slot_without_replay(self):
  self.h.p['max_api_requests']=1
  def edit(r):r['output'][0]['content'][0]['text']='not json';return r
  self.h.response_edit=edit;t=self.run_policy();self.assertEqual(t['reason'],'final_program_complete');self.assertEqual(len(self.h.api_calls),1);self.assertEqual(len(self.h.programs),0)
