from email.message import Message
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))


class FullClientServerTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.root=Path(self.directory.name)
        (self.root/'web').mkdir()
        (self.root/'web/index.html').write_text('<body></body>')
        self.output=self.root/'output'
        self.account=self.root/'unused-account.json'; self.account.write_text('{}'); self.account.chmod(0o600)
        path=Path(__file__).resolve().parents[1]/'scripts/serve-full-client.py'
        spec=importlib.util.spec_from_file_location('full_client_server_under_test',path)
        self.module=importlib.util.module_from_spec(spec)
        stubs={name:types.ModuleType(name) for name in ('assets_server','websockets','ws_proxy')}
        with mock.patch.dict(os.environ,{'MAPLEBENCH_CLIENT_ROOT':str(self.root),
                'MAPLEBENCH_CLIENT_OUTPUT':str(self.output),'MAPLEBENCH_DEMO_ACCOUNT_FILE':str(self.account),
                'MAPLEBENCH_ADMIN_SOCKET':''}), \
             mock.patch.dict(sys.modules,stubs):
            spec.loader.exec_module(self.module)
        self.logs=mock.patch.object(self.module.Handler,'log_message'); self.logs.start()
        self.server=self.module.BoundedHTTPServer(('127.0.0.1',0),self.module.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.host='127.0.0.1:'+str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)
        self.logs.stop(); self.directory.cleanup()

    def request(self,method,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            connection.request(method,path,body=body,headers=headers or {})
            response=connection.getresponse()
            return response.status,response.read()
        finally:
            connection.close()

    def frame(self):
        return {'client':'test','ageMs':0,'renderAgeMs':0,'observation':{'ready':True,
            'character':{'x':0,'y':0,'hp':100,'maxHp':100,'mp':10,'maxMp':20,'exp':0,'level':180,'mapId':1,'alive':True},
            'monsters':[]}}

    def test_dns_rebinding_and_cross_origin_cannot_read_session_or_control(self):
        for headers in ({'Host':'attacker.example'}, {'Host':'localhost.attacker.example'},
                {'Origin':'https://attacker.example'}, {'Sec-Fetch-Site':'cross-site'},
                {'Host':'user@127.0.0.1'}, {'Host':'127.0.0.1/path'}):
            with self.subTest(headers=headers):
                status,_=self.request('GET','/demo-session',headers=headers)
                self.assertEqual(status,403)
        status,_=self.request('POST','/control/start',b'{}',{
            'Origin':'http://localhost:9999','Content-Type':'application/json'})
        self.assertEqual(status,403)

    def test_controller_loads_encoder_module_from_same_origin(self):
        status,body=self.request('GET','/web/index.html')
        self.assertEqual(status,200)
        self.assertIn(b'<script type="module" src="/full-client-demo.js">',body)
        status,body=self.request('GET','/webcodecs-recorder.js')
        self.assertEqual(status,200)
        self.assertEqual(body,self.module.ENCODER.read_bytes())
        status,body=self.request('GET','/full-client-demo.js')
        self.assertEqual(status,200)
        self.assertIn(b"from './webcodecs-recorder.js'",body)

    def test_status_is_read_only_and_omits_client_identifier(self):
        self.module.BRIDGE.frame(self.frame())
        self.module.BRIDGE.run={'status':'idle','client':'private-owner-id'}
        status,body=self.request('GET','/control/status')
        self.assertEqual(status,200)
        self.assertNotIn(b'private-owner-id',body)
        self.assertNotIn('observation',json.loads(body))
        self.assertTrue(json.loads(body)['fresh'])

    def test_stale_game_url_cannot_reopen_account_after_logout(self):
        session=self.module.SessionCoordinator(self.module.BRIDGE)
        self.module.SESSION=session
        session.owner='renderer'; session.desired='waiting'; session.transition='b'*32
        self.account.write_text('{"password":"test-only-must-stay-private"}')
        for suffix in ('','?transition='+'a'*32,'?transition='+'b'*32):
            status,body=self.request('GET','/web/index.html'+suffix)
            self.assertEqual(status,303)
            self.assertNotIn(b'full-client-demo.js',body)
        status,body=self.request('GET','/demo-session')
        self.assertEqual(status,409)
        self.assertNotIn(b'test-only-must-stay-private',body)
        session.desired='game'; session.transition='c'*32
        self.assertEqual(self.request('GET','/web/index.html?transition='+'a'*32)[0],303)
        self.assertEqual(self.request('GET','/web/index.html?transition='+'c'*32)[0],200)
        self.assertEqual(self.request('GET','/demo-session')[0],200)

    def test_cross_site_top_level_waiting_navigation_is_the_only_exception(self):
        self.module.SESSION=self.module.SessionCoordinator(self.module.BRIDGE)
        navigation={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
        for path in ('/control/wait','/control/wait?transition='+'a'*32):
            status,body=self.request('GET',path,headers=navigation)
            self.assertEqual(status,200)
            self.assertIn(b'<html',body)
        for path in ('/demo-session','/control/status','/web/index.html','/control/start'):
            with self.subTest(path=path):
                self.assertEqual(self.request('GET',path,headers=navigation)[0],403)
        for changes in ({'Sec-Fetch-Dest':'iframe'},{'Sec-Fetch-Dest':'script'},
                {'Sec-Fetch-Mode':'cors'},{'Origin':'http://'+self.host},
                {'Origin':'https://attacker.example'},{'Host':'attacker.example'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.request('GET','/control/wait',headers=navigation|changes)[0],403)
        for path in ('/control/wait','/control/frame','/control/start'):
            with self.subTest(method='POST',path=path):
                self.assertEqual(self.request('POST',path,b'{}',navigation|{'Content-Type':'application/json'})[0],403)

    def test_browser_start_requires_the_existing_renderer_owner(self):
        self.module.BRIDGE.frame(self.frame())
        with mock.patch.object(self.module.BRIDGE,'_run') as worker:
            for client in (None,'other-client'):
                body=json.dumps({'mode':'script','client':client}).encode()
                status,_=self.request('POST','/control/start',body,{
                    'Origin':'http://'+self.host,'Content-Type':'application/json'})
                self.assertEqual(status,409)
            worker.assert_not_called()

    def test_control_rejects_bad_types_and_body_limits(self):
        for body,headers,expected in [(b'{}',{'Content-Type':'text/plain'},415),
                (b'[]',{'Content-Type':'application/json'},409),
                (b'{}',{'Content-Type':'application/json','Content-Length':'invalid'},409),
                (b'{}',{'Content-Type':'application/json','Content-Length':'70001'},413)]:
            with self.subTest(headers=headers):
                status,_=self.request('POST','/control/frame',body,headers)
                self.assertEqual(status,expected)

    def test_failed_or_unknown_upload_does_not_replace_a_saved_recording(self):
        saved=self.output/'full-client-demo.webm'; saved.write_bytes(b'previous recording')
        headers={'Content-Type':'video/webm'}
        for body,extra,expected in [(b'not webm',{},409),
                (b'\x1a\x45\xdf\xa3test',{'X-MapleBench-Run':'a'*32},409),
                (b'anything',{'Content-Length':'invalid'},409),
                (b'anything',{'Content-Length':str(101*1024*1024)},413)]:
            status,_=self.request('POST','/demo-recording',body,headers|extra)
            self.assertEqual(status,expected)
            self.assertEqual(saved.read_bytes(),b'previous recording')
            self.assertEqual(list(self.output.glob('.recording-*.part')),[])

    def test_upload_is_bound_to_old_run_and_retry_is_idempotent(self):
        bridge=self.module.BRIDGE
        bridge.frame(self.frame())
        with mock.patch('full_client_bridge.threading.Thread'):
            run=bridge.start('script',client='test')
        bridge.run={'id':'b'*32,'status':'completed'}
        body=b'\x1a\x45\xdf\xa3bounded test recording'
        headers={'Content-Type':'video/webm','Origin':'http://'+self.host,
                 'X-MapleBench-Run':run['id'],'X-MapleBench-Client':'test'}
        for _ in range(2):
            status,response=self.request('POST','/demo-recording',body,headers)
            self.assertEqual(status,200)
            self.assertEqual(json.loads(response)['runId'],run['id'])
            self.assertEqual(json.loads(response)['sha256'],hashlib.sha256(body).hexdigest())
            self.assertEqual(list(self.output.glob('.recording-*.part')),[])
        self.assertEqual((bridge.output/run['id']/'video.webm').read_bytes(),body)
        status,_=self.request('POST','/demo-recording',body+b'changed',headers)
        self.assertEqual(status,409)
        self.assertEqual((bridge.output/run['id']/'video.webm').read_bytes(),body)

    def test_simultaneous_upload_is_rejected_without_consuming_disk(self):
        self.module.UPLOAD_SLOT.acquire()
        try:
            status,_=self.request('POST','/demo-recording',b'test',{'Content-Type':'video/webm'})
            self.assertEqual(status,429)
            self.assertEqual(list(self.output.glob('.recording-*.part')),[])
        finally:
            self.module.UPLOAD_SLOT.release()

    def test_websocket_rejects_remote_or_missing_origin(self):
        for origin,expected in [('http://127.0.0.1:8843',True),('http://localhost:8840',True),
                ('https://attacker.example',False),('http://localhost.attacker.example',False),('',False)]:
            headers=Message(); headers['Host']='127.0.0.1:8841'; headers['Origin']=origin
            self.assertEqual(self.module.trusted_websocket(types.SimpleNamespace(request_headers=headers)),expected)
            self.assertEqual(self.module.trusted_websocket(types.SimpleNamespace(request=types.SimpleNamespace(headers=headers))),expected)


if __name__=='__main__':
    unittest.main()
