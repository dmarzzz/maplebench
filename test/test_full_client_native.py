"""Offline native recipe/identity checks; no game, API or Docker execution."""
import copy,hashlib,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from full_client_native import PROTOCOL,contract,validate_contract,program,fingerprint
from full_client_bridge import FullClientBridge,ControlError
from full_client_capture import CAPTURE_DURATION_POLICY,capture_receipt,verify_video_duration
from full_client_session import SessionCoordinator,validate_guard_descriptors,AdminServer
from full_client_trial import existing_lock,validate_spec,TrialError
from full_client_publish import validate_manifest,verify_capture_bundle
from full_client_docker_fixture import local_binding
from maple_agent import validate_rpc
import test_full_client_capture as capture_fixtures

class NativeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir='/private/tmp' if sys.platform=='darwin' else '/tmp');self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name).resolve();self.bridge=FullClientBridge(self.root/'runs')
  self.observation={'ready':True,'character':{'x':0,'y':0,'hp':100,'maxHp':100,'mp':100,'maxMp':100,'exp':10,'level':180,'mapId':1,'alive':True},'monsters':[]}
  self.bridge.frame({'client':'test','ageMs':0,'renderAgeMs':0,'observation':self.observation})
  self.fds=[]
  for name in ('world','queue'):
   fd=os.open(self.root/name,os.O_RDWR|os.O_CREAT,0o600);self.fds.append(fd);self.addCleanup(os.close,fd)
  self.config=contract('hero','a'*64)
  self.options={'run_id':'b'*32,'request_id':'b'*32,'native_acceptance':self.config,'lease_fds':self.fds,'private':True,
                'docker_image_id':'sha256:'+'c'*64,'docker_binding':local_binding(self,self.root)}
  self.addCleanup(self.close_leases)
 def close_leases(self):
  for fds in self.bridge.leases.values():
   for fd in fds:os.close(fd)
  self.bridge.leases.clear()
 def start(self,**changes):
  with mock.patch('full_client_bridge.threading.Thread'):
   return self.bridge.start('script',None,30,**(self.options|changes))
 def test_frozen_contract_rejects_unbounded_or_arbitrary_program(self):
  for change in ({'wall_seconds':31},{'max_actions':13},{'code':'arbitrary'},{'profile':{}},{'capture_duration_policy':None}):
   with self.subTest(change=change),self.assertRaises((ValueError,TypeError)):validate_contract(self.config|change)
  self.assertEqual(validate_contract(self.config),self.config);self.assertEqual(len(fingerprint(self.config)),64)
 def test_bowmaster_casts_soul_arrow_before_basic_bow_attack(self):
  code=program(contract('bowmaster','a'*64))
  self.assertLess(code.index("['BUFF_1']"),code.index("['ATTACK']"));self.assertNotIn('BRANDISH',code)
  self.assertLessEqual(code.count('sdk.pressKeys('),12)
 def test_native_sdk_accepts_neutral_keys_but_rejects_hero_labels(self):
  def request(key):return {'type':'rpc','id':1,'method':'pressKeys','args':[[key],100]}
  self.assertEqual(validate_rpc(request('PRIMARY_SKILL'),{'adapter':'full-client','protocol':PROTOCOL})[1]['keys'],['PRIMARY_SKILL'])
  with self.assertRaises(ValueError):validate_rpc(request('BRANDISH'),{'adapter':'full-client','protocol':PROTOCOL})
 def test_native_start_requires_private_locks_and_no_model_contract(self):
  for change in ({'private':False},{'lease_fds':[]},{'trial_context':{'scenario_fingerprint':'d'*64,'baseline_sha256':'a'*64}},
                 {'total_token_limit':1},{'docker_binding':None},{'adaptive_protocol':{}},{'request_id':'c'*32}):
   with self.subTest(change=change),self.assertRaisesRegex(ControlError,'native_acceptance_private_contract_required'):self.start(**change)
  self.assertFalse((self.bridge.output/('b'*32)).exists())
  with self.assertRaisesRegex(ControlError,'native_acceptance_private_contract_required'):
   self.bridge.start('api','gpt-6-astra',30,**self.options)
 def test_native_request_is_claimed_once_and_policy_cannot_change(self):
  first=self.start();second=self.start();self.assertEqual(first['id'],second['id'])
  self.assertEqual(first['mode'],'script');self.assertIsNone(first['model']);self.assertNotIn('adaptiveProtocol',first)
  with self.assertRaisesRegex(ControlError,'run_intent_conflict'):self.start(native_acceptance=contract('bowmaster','a'*64))
 def test_native_worker_never_reads_api_key_or_calls_model(self):
  run=self.start()
  def execute(code,scenario,base,**kwargs):
   self.assertEqual(code,program(self.config));self.assertEqual(scenario['protocol'],PROTOCOL)
   self.assertEqual(kwargs['program_seconds'],30);self.assertEqual(kwargs['max_actions'],12)
   step={'kind':'sdk','method':'pressKeys','args':[['PRIMARY_SKILL'],100],'result':{'accepted':True,'observation':self.observation}}
   kwargs['step_callback'](step);return {'reason':'program_complete','actions':1,'steps':[step]}
  with mock.patch.object(self.bridge,'_wait_for_capture'),mock.patch.object(self.bridge,'request',return_value=self.observation),\
       mock.patch('full_client_bridge.execute_program',side_effect=execute),\
       mock.patch('full_client_bridge.model_decision',side_effect=AssertionError('no model call')),\
       mock.patch('full_client_bridge.read_private_file',side_effect=AssertionError('no credential read')):
   self.bridge._run(run)
  folder=self.bridge.output/run['id'];result=json.loads((folder/'result.json').read_bytes());publication=json.loads((folder/'publication.json').read_bytes())
  self.assertEqual(result['controller']['status'],'completed');self.assertEqual(result['model_api_requests'],0)
  self.assertIsNone(result['api']);self.assertEqual(publication['run_kind'],'native_acceptance')
  self.assertEqual(publication['budgets']['api_requests'],0);self.assertEqual(publication['budgets']['output_tokens'],0)
  self.assertFalse((folder/'api-request.json').exists());self.assertFalse(self.bridge.leases)
  checked=validate_manifest(publication);self.assertFalse(checked['ready'])
  self.assertTrue(any('API controller' in reason for reason in checked['reasons']))
 def test_private_native_dispatch_requires_exact_request_and_fd_validation(self):
  coordinator=SessionCoordinator(self.bridge,{'world':str(self.root/'world'),'queue':str(self.root/'queue')})
  coordinator.owner='test';coordinator.page='game';coordinator.desired='game';coordinator.acknowledged=True;coordinator.last_seen=__import__('time').monotonic()
  req={'op':'start_native','run_id':'b'*32,'request_id':'b'*32,'native_acceptance':self.config,
       'docker_image_id':self.options['docker_image_id'],'docker_binding':self.options['docker_binding'],
       'lock_paths':coordinator.lock_paths}
  with mock.patch('full_client_session.validate_guard_descriptors') as validate,mock.patch.object(self.bridge,'start',return_value={}) as start:
   coordinator.dispatch(req,tuple(self.fds));validate.assert_called_once();self.assertEqual(start.call_args.args,('script',None,30))
  for change in ({'model':'gpt-6-astra'},{'code':'bad'},{'adaptive_protocol':{}}):
   with self.assertRaisesRegex(ControlError,'invalid_native_acceptance_request'):coordinator.dispatch(req|change,tuple(self.fds))
 @unittest.skipUnless(sys.platform=='linux','Linux kernel descriptor proof')
 def test_native_session_real_inherited_locks_are_required(self):
  paths={'world':str(self.root/'world'),'queue':str(self.root/'queue')}
  with self.assertRaisesRegex(ControlError,'not_exclusively_locked'):validate_guard_descriptors(self.fds,paths,paths)
  with existing_lock(self.root/'world') as world,existing_lock(self.root/'queue') as queue:
   validate_guard_descriptors((world,queue),paths,paths)
 @unittest.skipUnless(sys.platform=='linux','Linux private socket inherited lock proof')
 def test_actual_private_socket_start_keeps_inherited_locks_without_starting_api(self):
  import threading,time,socket,array,fcntl
  coordinator=SessionCoordinator(self.bridge,{'world':str(self.root/'world'),'queue':str(self.root/'queue')})
  coordinator.owner='test';coordinator.page='game';coordinator.desired='game';coordinator.acknowledged=True;coordinator.last_seen=time.monotonic()
  req={'op':'start_native','run_id':'b'*32,'request_id':'b'*32,'native_acceptance':self.config,
       'docker_image_id':self.options['docker_image_id'],'docker_binding':self.options['docker_binding'],'lock_paths':coordinator.lock_paths}
  path=self.root/'admin.sock';server=AdminServer(path,coordinator)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with existing_lock(self.root/'world') as world,existing_lock(self.root/'queue') as queue:
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client,mock.patch.object(self.bridge,'_run') as worker:
     client.settimeout(2);client.connect(str(path));client.sendmsg([json.dumps(req).encode()+b'\n'],
       [(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[world,queue]))])
     response=json.loads(client.makefile('rb').readline());self.assertTrue(response['ok']);self.assertEqual(response['result']['mode'],'script')
   # Sender's descriptors have closed; bridge retains the accepted lease until
   # its fixed worker and browser key-release protocol actually settle.
   with self.assertRaises(BlockingIOError):fcntl.flock(self.fds[0],fcntl.LOCK_EX|fcntl.LOCK_NB)
   self.assertEqual(len(self.bridge.leases['b'*32]),2)
   self.assertFalse((self.bridge.output/('b'*32)/'api-request.json').exists())
  finally:server.shutdown();server.server_close();thread.join(2)
 def test_native_protocol_is_rejected_by_model_trial_admission(self):
  with self.assertRaisesRegex(TrialError,'unsupported_protocol'):
   validate_spec({'schema_version':2,'protocol':PROTOCOL,'model':'gpt-6-astra','scenario_fingerprint':'a'*64,
                  'baseline_sha256':'b'*64,'budgets':{}})
 def test_native_capture_policy_is_independent_and_not_accepted_as_api(self):
  fixture=capture_fixtures.CaptureTests();fixture.setUp();owner=fixture.owner|{'protocol':PROTOCOL,'mode':'script','model':None,'nativeAcceptance':self.config}
  raw=fixture.value|{'schema_version':2,'capture_duration_policy':dict(CAPTURE_DURATION_POLICY),'first_frame_offset_ms':2,'last_frame_offset_ms':2498}
  recording=capture_receipt(raw,owner,fixture.anchor,fixture.clock,fixture.terminal)
  probe={'duration_ms':2497,'presentation_span_ms':2496,'presentation_extent_ms':2497,'last_packet_duration_ms':1,'frames':150}
  verify_video_duration(probe,recording,CAPTURE_DURATION_POLICY)
  for changes in ({'mode':'api'},{'model':'gpt-6-astra'},{'adaptiveProtocol':{'capture_duration_policy':CAPTURE_DURATION_POLICY}}):
   with self.assertRaisesRegex(ValueError,'invalid_native_capture_identity'):capture_receipt(raw,owner|changes,fixture.anchor,fixture.clock,fixture.terminal)
 def test_capture_bundle_verifies_native_timeline_without_fake_api_interval(self):
  fixture=capture_fixtures.CaptureTests();fixture.setUp();owner=fixture.owner|{'protocol':PROTOCOL,'mode':'script','model':None,'nativeAcceptance':self.config}
  raw=fixture.value|{'schema_version':2,'capture_duration_policy':dict(CAPTURE_DURATION_POLICY),'first_frame_offset_ms':2,'last_frame_offset_ms':2498}
  refs={}
  def artifact(name,value):
   path=self.root/(name+'.json');data=json.dumps(value).encode();path.write_bytes(data);refs[name]={'path':path.name,'sha256':hashlib.sha256(data).hexdigest()}
  for name,value in (('capture',raw),('capture_ready',fixture.anchor),('capture_clock',fixture.clock),('capture_terminal',fixture.terminal)):artifact(name,value)
  recording=capture_receipt(raw,owner,fixture.anchor,fixture.clock,fixture.terminal)|{'sha256':'d'*64,'capture_sha256':refs['capture']['sha256']}
  artifact('recording',recording)
  result={'protocol':PROTOCOL,'nativeAcceptance':self.config,'model_api_requests':0,'trialContext':None,'api':None,
          'controller':owner|{'returnedModel':None},'timing':{'startedAtMs':20000,'endedAtMs':22000},
          'timeline':{'api_started_ms':None,'program_started_ms':500,'program_ended_ms':1800}}
  manifest={'result':result,'video':recording,'artifacts':refs}
  self.assertFalse(verify_capture_bundle(manifest,self.root)['interrupted'])
  result['controller']['mode']='api'
  with self.assertRaisesRegex(ValueError,'cannot carry a model identity'):verify_capture_bundle(manifest,self.root)

if __name__=='__main__':unittest.main()
