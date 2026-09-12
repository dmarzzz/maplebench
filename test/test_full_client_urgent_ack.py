"""Immediate ACK transport retains the original keyboard acceptance contract."""
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_bridge import FullClientBridge,ControlError

class UrgentAckTests(unittest.TestCase):
    def setup_bridge(self,folder):
        b=FullClientBridge(folder);b.client='test';b.run.update(id='b'*32,status='running',client='test')
        b.pending={'id':'a'*32,'runId':'b'*32,'client':'test','sent':True,'sentAt':100,
                   'durationMs':1500,'deadline':103,'keys':['LEFT']}
        body={'client':'test','ackRunId':'b'*32,'ack':{'id':'a'*32,'ok':True},'ageMs':0,'renderAgeMs':0,
            'observation':{'ready':True,'character':{'x':0,'y':0,'hp':100,'maxHp':100,'mp':10,'maxMp':20,'exp':10,'level':180,'mapId':1,'alive':True},'monsters':[]}}
        return b,body
    def test_accepts_same_hold_and_duplicate_cannot_change_decision(self):
        with tempfile.TemporaryDirectory() as d:
            b,body=self.setup_bridge(d)
            with mock.patch('full_client_bridge.time.monotonic',return_value=101.6):
                self.assertIsNone(b.frame(body,acknowledgement_only=True)['command'])
                self.assertTrue(b.pending['ack']['ok'])
                body['ack']['ok']=False
                b.frame(body,acknowledgement_only=True)
                self.assertTrue(b.pending['ack']['ok'])
    def test_cannot_dispatch_unsent_or_next_command(self):
        with tempfile.TemporaryDirectory() as d:
            b,body=self.setup_bridge(d);b.pending.pop('sent');b.pending['deadline']=104
            with mock.patch('full_client_bridge.time.monotonic',return_value=101):
                self.assertIsNone(b.frame(body,acknowledgement_only=True)['command'])
            self.assertNotIn('sent',b.pending);self.assertNotIn('ack',b.pending)
    def test_stale_early_late_and_foreign_acks_fail_closed(self):
        for case in ('stale','early','late','run','client','id'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as d:
                b,body=self.setup_bridge(d);now=101.6
                if case=='stale':body['renderAgeMs']=1500
                if case=='early':now=101
                if case=='late':now=103
                if case=='run':body['ackRunId']='c'*32
                if case=='client':body['client']='foreign'
                if case=='id':body['ack']['id']='c'*32
                with mock.patch('full_client_bridge.time.monotonic',return_value=now):
                    if case in ('run','client','id'):
                        with self.assertRaises(ControlError):b.frame(body,acknowledgement_only=True)
                    else:b.frame(body,acknowledgement_only=True)
                self.assertFalse(b.pending.get('ack',{}).get('ok',False))
                self.assertEqual(b.pending['deadline'],103)
    def test_optional_timing_is_bounded_and_first_receipt_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            b,body=self.setup_bridge(d)
            timing={'schema_version':1,'handler_started_monotonic_ms':12345,'keydown_after_ms':1,
                    'finished_after_ms':1501,'urgent_post_after_ms':1501}
            body['ack']['timing']=timing
            with mock.patch('full_client_bridge.time.monotonic',return_value=101.6):
                b.frame(body,acknowledgement_only=True)
                original=dict(b.pending['lastMatchingAck'])
                b.frame(body)
            self.assertEqual(b.pending['lastMatchingAck'],original)
            for value in (True,-1,350001,float('nan')):
                body['ack']['timing']=timing | {'finished_after_ms':value}
                with self.assertRaises((ControlError,ValueError)):b.frame(body,acknowledgement_only=True)

    def test_urgent_newer_frame_does_not_regress_active_readiness_on_older_poll(self):
        import copy
        with tempfile.TemporaryDirectory() as d:
            b,body=self.setup_bridge(d)
            policy={'expected_map_id':1,'min_monsters':0,'min_samples':1,'min_span_ms':0}
            b.run.update(readinessPolicy=policy,captureClockAccepted='clock',captureReadyAtMs=1)
            b.capture_clock={'id':'clock','server_sent_ms':0};b.capture_clock_received_ms=0
            b.readiness={'run_id':'b'*32,'client_id':'test','capture_clock_id':'clock','policy':policy,
                'counter':10,'samples':[],'generation':0,'fault':False,'run_started':100}
            body.update(clientSentAtMs=10000,captureClockAck='clock',captureClockReceivedAtMs=0,
                captureState='recording',capture={'runId':'b'*32,'started':True,'renderedFrames':12,'interrupted':False})
            state=copy.deepcopy(b.readiness);observation=copy.deepcopy(b.observation)
            with mock.patch('full_client_bridge.time.monotonic',return_value=101.6),mock.patch('full_client_bridge.time.time',return_value=10):
                b.frame(body,acknowledgement_only=True)
                self.assertEqual(b.readiness,state);self.assertEqual(b.observation,observation)
                older=copy.deepcopy(body);older['ack']=None;older['capture']['renderedFrames']=11
                b.frame(older)
            self.assertFalse(b.readiness['fault']);self.assertEqual(b.readiness['counter'],11)
            self.assertTrue(b.pending['ack']['ok'])
            self.assertEqual(b.pending['ackObservation']['ageMs'],0)

    def test_request_returns_ack_bound_snapshot_despite_older_normal_poll(self):
        import threading,time,copy
        with tempfile.TemporaryDirectory() as d:
            b,body=self.setup_bridge(d);b.pending=None;body['ack']=None
            b.frame(body);result={}
            def request():result.update(b.request('/v1/action',{'type':'press_keys','keys':['LEFT'],'durationMs':30}))
            thread=threading.Thread(target=request);thread.start()
            limit=time.monotonic()+1
            while b.pending is None and time.monotonic()<limit:time.sleep(.001)
            command=b.frame(body)['command'];self.assertIsNotNone(command)
            time.sleep(.035)
            urgent=copy.deepcopy(body);urgent['ack']={'id':command['id'],'ok':True}
            urgent['observation']['character']['x']=42
            with b.lock:
                b.frame(urgent,acknowledgement_only=True)
                b.frame(body) # older normal snapshot arrives before request thread wakes
            thread.join(1);self.assertFalse(thread.is_alive())
            self.assertTrue(result['accepted']);self.assertEqual(result['observation']['character']['x'],42)

    def test_recorded_adaptive_result_with_transport_timing_verifies(self):
        from test_full_client_adaptive import Harness,MODEL,verify_result
        with tempfile.TemporaryDirectory() as d:
            h=Harness(d,calls=1)
            def add_timing(execution):
                execution['steps'][0]['result']['inputTiming']={
                    'receivedAt':101.6,'receivedAtMs':123456,'ok':True,'validFrame':True,
                    'enoughTime':True,'beforeDeadline':True,'transport':'urgent',
                    'clientTiming':{'schema_version':1,'handler_started_monotonic_ms':1000,
                        'keydown_after_ms':1,'finished_after_ms':101,'urgent_post_after_ms':102}}
                return execution
            h.execution_edit=add_timing;h.run()
            result=h.result()
            checked=verify_result(result,h.root,protocol=h.p,model=MODEL)
            self.assertEqual(checked['wall_elapsed_ms'],30000)
            saved=json.loads((h.root/'cycles/000/execution.json').read_text())
            self.assertEqual(saved['steps'][0]['result']['inputTiming']['transport'],'urgent')

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_real_poll_inflight_does_not_delay_urgent_ack_and_no_retry(self):
        source=(Path(__file__).resolve().parents[1]/'ui/full-client/controller.js').read_text()
        mappings=source[source.index('  const keyNames = '):source.index('  const held = ')]
        code=source[source.index('  const commandDeadline = '):source.index('  const startRun=async')]
        fixture=r'''
const assert=require('node:assert/strict');
let activeCommand=null,acknowledgement=null,closed=false,pollAbort,pollTimer,disconnectedAt=null;
let relayConnected=true,captureFailure=null,saving=false,pendingUpload=null,sessionAck=null,releaseAck=null;
const clientId='test',run={id:'b'.repeat(32)},held=new Map(),cancelledRuns=new Set();
const capture={recorderStarted:true,frames:1,autoRunId:run.id,stopping:false};
const document={hidden:false},game={focus(){}};
const observe=()=>({ready:true,capturedAt:Date.now()}),fresh=()=>true;
const Module={get MapleBenchRenderedAt(){return Date.now()},MapleBenchHud:null};
const renderHeader=()=>{},releaseAll=()=>{},key=()=>{},release=code=>{clearTimeout(held.get(code));held.delete(code);};
let normalBody,urgentBody,urgentCount=0;
const fetch=(url,options)=>{
 if(url==='/control/frame'){normalBody=JSON.parse(options.body);return new Promise(()=>{});}
 assert.equal(url,'/control/ack');urgentCount++;urgentBody=JSON.parse(options.body);
 return Promise.reject(Error('lost reply'));
};
'''
        checks=r'''
(async()=>{
 poll();assert.equal(normalBody.ack,null);
 await executeInput({id:'a'.repeat(32),runId:run.id,keys:['LEFT'],durationMs:30},performance.now()+1000);
 await new Promise(r=>setTimeout(r,20));
 assert.equal(urgentCount,1);assert.equal(urgentBody.ack.ok,true);
 assert.equal(urgentBody.ackRunId,run.id);assert.equal(acknowledgement.id,urgentBody.ack.id);
 assert.ok(urgentBody.ack.timing.finished_after_ms>=29);
 assert.equal(normalBody.ack,null);
 const fractional={id:'c'.repeat(32),ok:true,timing:{schema_version:1,handler_started_monotonic_ms:11,
   keydown_after_ms:0,finished_after_ms:1501,urgent_post_after_ms:1501}};
 const realPerformance=globalThis.performance;
 globalThis.performance={now:()=>1511.2};
 await sendUrgentAck(fractional,run.id,10.7);
 assert.equal(fractional.timing.urgent_post_after_ms,1501);
 globalThis.performance=realPerformance;
 closed=true;process.exit(0);
})().catch(e=>{console.error(e);process.exit(1);});
'''
        result=subprocess.run([shutil.which('node'),'--max-old-space-size=64','-e',fixture+mappings+code+checks],capture_output=True,text=True,timeout=4)
        self.assertEqual(result.returncode,0,result.stderr)
