from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_bridge import FullClientBridge
from maple_agent import validate_rpc

class FullClientTests(unittest.TestCase):
    def message(self,keys,duration):
        return {'type':'rpc','id':1,'method':'pressKeys','args':[keys,duration]}

    def test_keyboard_is_opt_in_and_bounded(self):
        with self.assertRaises(ValueError): validate_rpc(self.message(['LEFT'],100),{})
        for keys,ms in [(['LEFT','RIGHT'],100),(['ADMIN'],100),(['LEFT'],1501),(['JUMP'],True),(['LEFT','LEFT'],30)]:
            with self.assertRaises(ValueError): validate_rpc(self.message(keys,ms),{'adapter':'full-client'})
        _,action=validate_rpc(self.message(['RIGHT','JUMP'],250),{'adapter':'full-client'})
        self.assertEqual(action['type'],'press_keys')

    def test_input_requires_fresh_state_and_ack(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            with self.assertRaises(ValueError): bridge.request('/v1/observe')
            frame={'client':'test','ageMs':0,'renderAgeMs':0,'observation':{'ready':True,'character':{'x':0}}}
            bridge.frame(frame)
            result=[]
            action={'type':'press_keys','keys':['LEFT'],'durationMs':100}
            worker=threading.Thread(target=lambda:result.append(bridge.request('/v1/action',action,timeout=1)))
            worker.start()
            end=time.monotonic()+0.5
            command=None
            while time.monotonic()<end and command is None:
                command=bridge.frame(frame)['command']
                time.sleep(0.001)
            self.assertIsNotNone(command)
            self.assertIsNone(bridge.frame(frame)['command'])
            self.assertEqual(result,[])
            bridge.frame(frame|{'ack':{'id':command['id'],'ok':True}})
            worker.join(1)
            self.assertTrue(result[0]['accepted'])
            self.assertIsNone(bridge.pending)
            bridge.frame(frame|{'renderAgeMs':2000})
            with self.assertRaises(ValueError): bridge.request('/v1/observe')

    def test_expired_commands_are_not_delivered_later(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            frame={'client':'test','ageMs':0,'renderAgeMs':0,'observation':{'ready':True}}
            bridge.frame(frame)
            with self.assertRaises(TimeoutError):
                bridge.request('/v1/action',{'type':'press_keys','keys':['LEFT'],'durationMs':100},timeout=0.02)
            self.assertIsNone(bridge.frame(frame)['command'])

if __name__=='__main__': unittest.main()
