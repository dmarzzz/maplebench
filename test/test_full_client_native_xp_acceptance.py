"""Synthetic receipts only: no API, native runtime, or database is launched."""
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_native_xp_acceptance import PROTOCOL,verify_bundle
from full_client_xp_windows import PROTOCOL as WINDOWS
from full_client_native import contract,program
from full_client_score import EvidenceError
from test_full_client_xp_windows import Ledger,IDENTITY,NORM

class NativeEnvelopeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.arts={}
  initial={'schema_version':1,'source':'cosmic_persisted_character','run_id':'a'*32,'account_logged_in':0,
   'captured_at_ms':999800,'character':{'character_id':7,'account_id':9,'level':180,'exp':0},'keymap':[[29,5,52]]}
  self.save('initial_db',initial);final=copy.deepcopy(initial);final['captured_at_ms']=1304000;final['character']['exp']=4500;self.save('final_db',final)
  self.save('baseline_snapshot',{'character':initial['character'],'keymap':initial['keymap']});sql=self.save('baseline_sql',b'-- synthetic baseline\n')
  table=hashlib.sha256(json.dumps([1000000000]*199,separators=(',',':')).encode()).hexdigest()
  native=contract('hero',sql['sha256']);scenario={'protocol':PROTOCOL,'native_contract':native,'xp_window_protocol':{'id':WINDOWS,'window_ms':15000,'wall_seconds':300,'normalization':NORM,'experience_table_sha256':table}}
  scenario_ref=self.save('scenario',scenario)
  self.save('controller_result',{'schema_version':1,'protocol':PROTOCOL,'run_id':'a'*32,'model':None,'api_calls':0,
      'started_at_ms':1000000,'ended_at_ms':1020000,'accepted_actions':8,'sdk_requests':30,'program_sha256':hashlib.sha256(program(native).encode()).hexdigest()})
  steps=[{'kind':'sdk','rpcId':i+1,'method':'pressKeys' if i<8 else 'observe',
      'args':[['ATTACK'],100] if i<8 else [],'result':{'accepted':True} if i<8 else {'character':{'alive':True}}} for i in range(30)]
  self.save('native_program',program(native).encode())
  self.save('native_result',{'protocol':native['id'],'nativeAcceptance':native,'api':None,'trialContext':None,
      'source':'client telemetry; unscored integration run','model_api_requests':0,'publication_eligible':False,'score':None,
      'programSha256':hashlib.sha256(program(native).encode()).hexdigest(),
      'controller':{'id':'a'*32,'mode':'script','model':None,'returnedModel':None,'trialContext':None,
        'protocol':native['id'],'nativeAcceptance':native,'status':'completed','reason':'program_complete','workerActive':False,'actions':8},
      'program':{'reason':'program_complete','error':None,'actions':8,'actionAttempts':8,'rpcRequests':30,'steps':steps},
      'timeline':{'status':'completed','program_started_ms':0,'program_ended_ms':20000},
      'timing':{'startedAtMs':1000000,'endedAtMs':1020100,'elapsedMs':20100,'apiLatencyMs':0}})
  self.ledger=Ledger(initial={'level':180,'exp':0},origin=999900,threshold=1000000000);self.ledger.transition(1005000,180,4500);self.ledger.commit(1302000);self.save('xp_ledger',self.ledger.bytes())
  self.save('native_save',(json.dumps({'schema_version':1,'source':'cosmic_persisted_character',**IDENTITY,'kind':'save_committed','committed_at_ms':1302000})+'\n').encode())
  self.save('native_log',b'MapleBench persistence journal initialized\nMapleBench XP ledger initialized\n')
  events=[{'run_id':'a'*32,'server_instance_id':'b'*32,'event':name,'at_ms':at} for name,at in [('server_started',999850),('login',999950),('logged_out',1303000),('collection_completed',1304000)]]
  self.save('server_log',b''.join((json.dumps(r)+'\n').encode() for r in events))
  self.save('reset',{'run_id':'a'*32,'baseline_sha256':sql['sha256'],'world_lock_held':True,'queue_lock_held':True,'server_stopped':True,'verified':True,'completed_at_ms':999700})
  self.save('session',{'run_id':'a'*32,'server_instance_id':'b'*32,'disconnect_kind':'normal','world_lock_held_throughout':True,'queue_lock_held_throughout':True,'server_started_at_ms':999850,'login_at_ms':999950,'controller_started_at_ms':1000000,'controller_ended_at_ms':1300000,'disconnect_requested_at_ms':1301000,'logged_out_at_ms':1303000,
   'save':{'status':'confirmed','run_id':'a'*32,'server_instance_id':'b'*32,'character_id':7,'committed_at_ms':1302000,'log_checked_from_ms':999850,'log_checked_through_ms':1304000,'save_error_count':0,'evidence_sha256':self.arts['native_save']['sha256'],'native_logs_sha256':self.arts['native_log']['sha256'],'logs_sha256':self.arts['server_log']['sha256']}})
  self.rows=[{'sequence':i,'wall_ms':1000000+i*1000,'monotonic_ns':2000000000+i*1000000000,**IDENTITY,'server_owned':True,'account_online':True,'renderer_fresh':True,'controller_idle':i>=20} for i in range(301)]
  self.coverage();self.manifest={'schema_version':1,'protocol':PROTOCOL,**IDENTITY,'window':{'start_at_ms':1000000,'deadline_at_ms':1300000,'window_ms':15000},'normalization':NORM,'artifacts':self.arts,'baseline_sha256':sql['sha256'],'scenario_fingerprint':scenario_ref['sha256'],'experience_table_sha256':table}
 def save(self,name,value):
  raw=value if isinstance(value,bytes) else (json.dumps(value)+'\n').encode();p=self.root/(name+'.bin');p.write_bytes(raw);ref={'path':p.name,'sha256':hashlib.sha256(raw).hexdigest()};self.arts[name]=ref;return ref
 def coverage(self):self.save('coverage',b''.join((json.dumps(r)+'\n').encode() for r in self.rows))
 def edit(self,name,**changes):
  value=json.loads((self.root/self.arts[name]['path']).read_text());value.update(changes);self.save(name,value)
 def test_separate_zero_model_envelope_accepts_native_transaction_only(self):
  result=verify_bundle(self.manifest,self.root);self.assertTrue(result['native_hook_accepted']);self.assertEqual(result['diagnostic_windows']['complete_windows'],20);self.assertFalse(result['publication_eligible']);self.assertIsNone(result['model'])
 def control_timing(self,start_delay,duration):
  origin=self.manifest['window']['start_at_ms'];ended=origin+start_delay+duration
  actual=json.loads((self.root/self.arts['native_result']['path']).read_text())
  actual['timeline'].update(program_started_ms=start_delay,program_ended_ms=start_delay+duration)
  actual['timing'].update(endedAtMs=ended+100,elapsedMs=start_delay+duration+100)
  self.save('native_result',actual)
  self.edit('controller_result',started_at_ms=origin+start_delay,ended_at_ms=ended)
  for row in self.rows:row['controller_idle']=row['sequence']==0 or row['wall_ms']>=ended
  self.coverage()
 def test_delayed_control_keeps_original_300_second_window_and_20_scores(self):
  for start_delay,duration in ((0,30000),(4000,29000),(5000,30000)):
   self.control_timing(start_delay,duration)
   with self.subTest(start_delay=start_delay,duration=duration):
    result=verify_bundle(self.manifest,self.root)
    self.assertTrue(result['native_hook_accepted'])
    self.assertEqual(result['diagnostic_windows']['complete_windows'],20)
    self.assertEqual(self.manifest['window'],{'start_at_ms':1000000,'deadline_at_ms':1300000,'window_ms':15000})
    self.assertFalse(result['publication_eligible'])
 def test_start_or_execution_overrun_is_not_allowed_by_35_second_envelope(self):
  for start_delay,duration in ((5001,29000),(0,30001),(5000,30001)):
   self.control_timing(start_delay,duration)
   with self.subTest(start_delay=start_delay,duration=duration),self.assertRaisesRegex(EvidenceError,'fixed_native_control_window_required'):
    verify_bundle(self.manifest,self.root)
 def test_idle_claim_during_recorded_control_is_refused_but_pre_submission_idle_is_valid(self):
  self.control_timing(4000,29000)
  verify_bundle(self.manifest,self.root)
  self.rows[32]['controller_idle']=True;self.coverage()
  with self.assertRaisesRegex(EvidenceError,'native_control_idle_before_completion'):
   verify_bundle(self.manifest,self.root)
 def test_idle_deadline_uses_actual_start_not_maximum_arming_allowance(self):
  for delay,index in ((0,30),(4000,34),(5000,35)):
   self.control_timing(delay,20000)
   self.rows[index]['controller_idle']=False;self.coverage()
   with self.subTest(delay=delay),self.assertRaisesRegex(EvidenceError,'native_control_exceeded_recipe'):
    verify_bundle(self.manifest,self.root)
 def test_optional_control_cannot_widen_origin_or_change_owner(self):
  from full_client_native_xp_acceptance import verify_coverage
  original=json.loads((self.root/self.arts['controller_result']['path']).read_text())
  raw=(self.root/self.arts['coverage']['path']).read_bytes()
  for change in ({'started_at_ms':1005001},{'ended_at_ms':1030001},{'run_id':'c'*32},{'api_calls':True}):
   with self.subTest(change=change),self.assertRaisesRegex(EvidenceError,'native_coverage_control_mismatch'):
    verify_coverage(raw,IDENTITY,self.manifest['window'],control=original|change)
 def test_capture_45_seconds_and_accounting_300_seconds_remain_fixed(self):
  self.control_timing(5000,30000)
  self.edit('native_result',timing={'startedAtMs':1000000,'endedAtMs':1045001,'elapsedMs':45001,'apiLatencyMs':0})
  with self.assertRaisesRegex(EvidenceError,'fixed_native_control_window_required'):
   verify_bundle(self.manifest,self.root)
  self.control_timing(5000,30000)
  self.manifest['window']['deadline_at_ms']+=1000
  with self.assertRaisesRegex(EvidenceError,'native_control_timing_required'):
   verify_bundle(self.manifest,self.root)
 def test_api_or_duplicate_control_or_unknown_program_refused(self):
  for change in ({'api_calls':1},{'model':'gpt-6-astra'},{'submission_attempts':2},{'program_sha256':'0'*64}):
   original=(self.root/self.arts['controller_result']['path']).read_bytes();self.edit('controller_result',**change)
   with self.subTest(change=change),self.assertRaises(EvidenceError):verify_bundle(self.manifest,self.root)
   self.save('controller_result',original)
 def test_forged_normalized_success_cannot_hide_actual_failed_or_interrupted_result(self):
  original=(self.root/self.arts['native_result']['path']).read_bytes()
  for kind in ('failed','api','context','step','count','program','clock'):
   value=json.loads(original)
   if kind=='failed':value['controller']['status']='failed'
   elif kind=='api':value['api']={'model':'gpt-6-astra'}
   elif kind=='context':value['trialContext']={'baseline_sha256':'0'*64}
   elif kind=='step':value['program']['steps'][0]['result']['accepted']=False
   elif kind=='count':value['program']['rpcRequests']=29
   elif kind=='program':value['programSha256']='0'*64
   else:value['timing']['endedAtMs']+=500
   self.save('native_result',value)
   with self.subTest(kind=kind),self.assertRaises(EvidenceError):verify_bundle(self.manifest,self.root)
  self.save('native_result',original)
  self.save('native_program',b'// forged program')
  with self.assertRaises(EvidenceError):verify_bundle(self.manifest,self.root)
 def test_short_hold_missing_duplicate_or_disconnected_status_refused(self):
  original=copy.deepcopy(self.rows)
  for change in ('short','gap','duplicate','offline','clock'):
   self.rows=copy.deepcopy(original)
   if change=='short':self.rows=self.rows[:-1]
   elif change=='gap':self.rows.pop(50)
   elif change=='duplicate':self.rows[50]=self.rows[49]
   elif change=='offline':self.rows[50]['account_online']=False
   else:self.rows[50]['monotonic_ns']+=100000000
   self.coverage()
   with self.subTest(change=change),self.assertRaises(EvidenceError):verify_bundle(self.manifest,self.root)
 def test_zero_native_transactions_are_insufficient_not_model_zero(self):
  ledger=Ledger(initial={'level':180,'exp':0},origin=999900,threshold=1000000000);ledger.commit(1302000);self.save('xp_ledger',ledger.bytes());value=json.loads((self.root/self.arts['final_db']['path']).read_text());value['character']['exp']=0;self.save('final_db',value)
  result=verify_bundle(self.manifest,self.root);self.assertFalse(result['native_hook_accepted']);self.assertEqual(result['status'],'insufficient_positive_native_transaction')
 def test_no_terminal_ledger_or_corrupt_save_is_unknown(self):
  self.save('xp_ledger',b''.join(self.ledger.rows[:-1]))
  with self.assertRaises(EvidenceError):verify_bundle(self.manifest,self.root)
 def test_old_adaptive_verifier_still_refuses_native_envelope(self):
  from full_client_xp_windows import verify_bundle as adaptive
  with self.assertRaises(EvidenceError):adaptive(self.manifest,self.root)

class PassiveCollectorTests(unittest.TestCase):
 def test_deadline_does_not_move_and_only_read_samples_are_collected(self):
  from full_client_native_xp_acceptance import collect_passive_coverage
  now=[1000000000];writes=[];calls=[]
  def sleep(seconds):now[0]+=int(seconds*1000000000)
  def observe():calls.append(now[0]);return {'sequence':len(calls),'monotonic_ns':now[0]}
  result=collect_passive_coverage({'sequence':0,'monotonic_ns':now[0]},observe,writes.append,monotonic_ns=lambda:now[0],sleep=sleep)
  self.assertEqual(result['samples'],301);self.assertEqual(len(calls),300);self.assertEqual(now[0],301000000000)
 def test_uncertain_persistence_is_not_retried(self):
  from full_client_native_xp_acceptance import collect_passive_coverage
  attempts=[]
  def append(raw):attempts.append(raw);raise OSError('lost reply')
  with self.assertRaises(OSError):collect_passive_coverage({'sequence':0,'monotonic_ns':0},lambda:None,append,monotonic_ns=lambda:0,sleep=lambda _:None)
  self.assertEqual(len(attempts),1)
 def test_missed_clock_deadline_fails_without_rescheduling(self):
  from full_client_native_xp_acceptance import collect_passive_coverage
  calls=[]
  with self.assertRaises(EvidenceError):collect_passive_coverage({'sequence':0,'monotonic_ns':0},lambda:calls.append(1),lambda _:None,monotonic_ns=lambda:2000000000,sleep=lambda _:None)
  self.assertEqual(calls,[])
