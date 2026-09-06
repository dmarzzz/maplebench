import json
import array
import fcntl
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_bridge import FullClientBridge
from full_client_session import AdminServer, SessionCoordinator, validate_guard_descriptors


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='mbs-',dir='/tmp')
        self.root=Path(self.directory.name).resolve()
        self.root.chmod(0o700)
        self.bridge=FullClientBridge(self.root/'runs')
        self.coordinator=SessionCoordinator(self.bridge)

    def tearDown(self):
        self.directory.cleanup()

    def frame(self,page='game',capture='idle',ack=None,client='renderer'):
        observation={'ready':False} if page=='waiting' else {'ready':True,'character':{
            'x':0,'y':0,'hp':100,'maxHp':100,'mp':10,'maxMp':20,'exp':0,'level':180,'mapId':1,'alive':True},'monsters':[]}
        body={'client':client,'page':page,'captureState':capture,'sessionAck':ack,
              'observation':observation,'ageMs':0,'renderAgeMs':0}
        with self.bridge.lock:
            self.coordinator.validate_frame(body)
            self.bridge.frame(body)
            return self.coordinator.frame(body)

    def test_same_tab_wait_connect_disconnect_require_acknowledged_navigation(self):
        self.frame()
        requested=self.coordinator.dispatch({'op':'prepare_wait'})
        self.assertTrue(requested['pinned'])
        self.assertEqual(requested['state'],'transitioning')
        response=self.frame()
        self.assertEqual(response['navigation']['page'],'waiting')
        transition=response['navigation']['id']
        self.assertEqual(self.frame('waiting',ack='wrong')['session']['state'],'transitioning')
        self.assertEqual(self.frame('waiting',ack=transition)['session']['state'],'waiting')
        connecting=self.coordinator.dispatch({'op':'connect'})
        response=self.frame('waiting',ack=transition)
        self.assertEqual(response['navigation']['page'],'game')
        self.assertEqual(response['navigation']['id'],connecting['transitionId'])
        self.assertEqual(self.frame('game',ack=connecting['transitionId'])['session']['state'],'connected')
        self.assertTrue(self.coordinator.dispatch({'op':'status'})['bridge']['fresh'])
        self.assertIsNotNone(self.coordinator.dispatch({'op':'status'})['observation'])
        disconnected=self.coordinator.dispatch({'op':'disconnect'})
        self.assertNotEqual(disconnected['transitionId'],transition)

    def test_navigation_waits_for_capture_upload_and_artifacts(self):
        self.frame(capture='recording')
        self.coordinator.dispatch({'op':'prepare_wait'})
        for capture in ('recording','saving','failed'):
            self.assertIsNone(self.frame(capture=capture)['navigation'])
        self.bridge.run={'id':'a'*32,'status':'completed','evidenceStatus':'saved'}
        self.assertIsNone(self.frame()['navigation'])
        self.bridge.run['failureAcknowledged']=True
        self.assertIsNotNone(self.frame()['navigation'])

    def test_active_run_cannot_be_disconnected_and_owner_cannot_be_replaced(self):
        self.frame()
        self.coordinator.dispatch({'op':'prepare_wait'})
        self.bridge.last_seen-=10
        with self.assertRaisesRegex(ValueError,'pinned'):
            self.frame(client='second-renderer')
        self.assertEqual(self.bridge.client,'renderer')
        self.bridge.run={'status':'running'}
        with self.assertRaisesRegex(ValueError,'active'):
            self.coordinator.dispatch({'op':'disconnect'})

    def test_private_start_requires_connected_session_and_passes_frozen_limits(self):
        request={'op':'start','run_id':'a'*32,'request_id':'a'*32,'model':'gpt-6-astra',
            'duration_seconds':60,'total_token_limit':20000,'docker_image_id':'sha256:'+'b'*64,
            'docker_binding':{'synthetic':'forwarding-only'},
            'readiness_policy':{'synthetic':'forwarding-only'},
            'trial_context':{'scenario_fingerprint':'c'*64,'baseline_sha256':'d'*64}}
        with mock.patch('full_client_session.validate_guard_descriptors'), self.assertRaisesRegex(ValueError,'not_connected'):
            self.coordinator.dispatch(request,(10,11))
        self.frame(); waiting=self.coordinator.dispatch({'op':'prepare_wait'})
        self.frame('waiting',ack=waiting['transitionId'])
        connecting=self.coordinator.dispatch({'op':'connect'})
        self.frame('game',ack=connecting['transitionId'])
        with mock.patch.object(self.bridge,'start',return_value={'id':'a'*32}) as start, \
             mock.patch('full_client_session.validate_guard_descriptors') as validate:
            self.coordinator.dispatch(request,(10,11))
        validate.assert_called_once_with((10,11),None,None)
        self.assertEqual(start.call_args.args,('api','gpt-6-astra',60))
        self.assertEqual(start.call_args.kwargs,{'client':'renderer','run_id':'a'*32,'request_id':'a'*32,
            'total_token_limit':20000,'trial_context':request['trial_context'],'docker_image_id':request['docker_image_id'],
            'docker_binding':request['docker_binding'],'readiness_policy':request['readiness_policy'],'lease_fds':(10,11),'private':True})

    def test_stale_waiting_browser_is_not_ready_for_connect(self):
        self.frame(); requested=self.coordinator.dispatch({'op':'prepare_wait'})
        self.frame('waiting',ack=requested['transitionId'])
        self.coordinator.last_seen-=4
        self.assertFalse(self.coordinator.status()['fresh'])
        with self.assertRaisesRegex(ValueError,'unavailable'):
            self.coordinator.dispatch({'op':'connect'})

    def test_admin_socket_is_private_bounded_and_has_no_eval(self):
        self.frame()
        path=self.root/'admin.sock'
        server=AdminServer(path,self.coordinator)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
            self.assertEqual(path.stat().st_uid,os.geteuid())
            for request,expected in [({'op':'status'},True),({'op':'eval','code':'process.exit()'},False)]:
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                    client.settimeout(2); client.connect(str(path))
                    client.sendall(json.dumps(request).encode()+b'\n')
                    response=json.loads(client.makefile('rb').readline())
                self.assertEqual(response['ok'],expected)
            with self.assertRaisesRegex(ValueError,'owned'):
                AdminServer(path,self.coordinator)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)
        self.assertFalse(path.exists())

    def test_admin_socket_rejects_public_parent_and_preserves_conflicting_files(self):
        self.root.chmod(0o755)
        with self.assertRaisesRegex(ValueError,'0700'):
            AdminServer(self.root/'admin.sock',self.coordinator)
        self.root.chmod(0o700)
        conflict=self.root/'admin.sock'; conflict.write_text('preserve this file')
        with self.assertRaisesRegex(ValueError,'conflict'):
            AdminServer(conflict,self.coordinator)
        self.assertEqual(conflict.read_text(),'preserve this file')

    def test_guard_descriptors_require_matching_distinct_regular_exclusively_locked_files(self):
        paths={role:str(self.root/(role+'.lock')) for role in ('world','queue')}
        with open(paths['world'],'w+') as world, open(paths['queue'],'w+') as queue:
            descriptors=(world.fileno(),queue.fileno())
            # The runtime is Linux; mock only /proc's platform-specific receipt.
            with mock.patch('full_client_session.Path.is_file',return_value=True), \
                 mock.patch('full_client_session.Path.read_text',return_value='lock:\t1: FLOCK  ADVISORY  WRITE 123 00:00:1 0 EOF'):
                validate_guard_descriptors(descriptors,paths,paths)
                for values,request in [((world.fileno(),world.fileno()),paths),
                        (descriptors,paths|{'world':paths['queue']}),((world.fileno(),),paths)]:
                    with self.subTest(values=values,request=request), self.assertRaises(ValueError):
                        validate_guard_descriptors(values,request,paths)
            with mock.patch('full_client_session.Path.is_file',return_value=True), \
                 mock.patch('full_client_session.Path.read_text',return_value='flags: 02'), \
                 self.assertRaisesRegex(ValueError,'not_exclusively_locked'):
                validate_guard_descriptors(descriptors,paths,paths)

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux flock descriptor receipt')
    def test_actual_linux_flock_receipt_survives_sender_close(self):
        paths={role:str(self.root/(role+'.lock')) for role in ('world','queue')}
        originals=[os.open(path,os.O_RDWR|os.O_CREAT,0o600) for path in paths.values()]
        duplicates=[]
        try:
            for descriptor in originals:
                fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
                duplicates.append(os.dup(descriptor))
            for descriptor in originals: os.close(descriptor)
            originals=[]
            validate_guard_descriptors(tuple(duplicates),paths,paths)
            with open(paths['world'],'r+') as contender, self.assertRaises(BlockingIOError):
                fcntl.flock(contender.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        finally:
            for descriptor in originals+duplicates: os.close(descriptor)

    def test_admin_closes_received_descriptors_after_dispatch(self):
        path=self.root/'admin.sock'; received=[]
        def inspect(request,descriptors):
            self.assertEqual(request,{'op':'start'})
            self.assertEqual(len(descriptors),2)
            received.extend(descriptors)
            for descriptor in descriptors:
                self.assertFalse(os.get_inheritable(descriptor)); os.fstat(descriptor)
            return {'accepted':True}
        server=AdminServer(path,self.coordinator)
        worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start()
        try:
            with tempfile.TemporaryFile() as world, tempfile.TemporaryFile() as queue, \
                 mock.patch.object(self.coordinator,'dispatch',side_effect=inspect), \
                 socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.settimeout(2); client.connect(str(path))
                client.sendmsg([b'{"op":"start"}\n'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[world.fileno(),queue.fileno()]))])
                response=json.loads(client.makefile('rb').readline())
                self.assertTrue(response['ok'])
                for descriptor in received:
                    with self.assertRaises(OSError): os.fstat(descriptor)
                os.fstat(world.fileno()); os.fstat(queue.fileno())
        finally:
            server.shutdown(); server.server_close(); worker.join(2)

    def test_cancelled_worker_still_prevents_navigation(self):
        self.frame(); self.coordinator.dispatch({'op':'prepare_wait'})
        self.bridge.run={'status':'failed','workerActive':True,'failureAcknowledged':True}
        self.assertFalse(self.coordinator.status()['artifactsSettled'])
        with self.assertRaisesRegex(ValueError,'active'):
            self.coordinator.dispatch({'op':'disconnect'})


if __name__=='__main__':
    unittest.main()
