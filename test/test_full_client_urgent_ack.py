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
        b=FullClientBridge(folder);b.run.update(id='b'*32,status='running',client='test')
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
            timing={'schema_version':1,'received_at_ms':12345,'keydown_after_ms':1,
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

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_real_poll_inflight_does_not_delay_urgent_ack_and_no_retry(self):
        source=(Path(__file__).resolve().parents[1]/'ui/full-client/controller.js').read_text()
        code=source[source.index('  const commandDeadline = '):source.index('  const startRun=async')]
        fixture=r'''
const assert=require('node:assert/strict');
let activeCommand=null,acknowledgement=null,closed=false,pollAbort,pollTimer,disconnectedAt=null;
let relayConnected=true,captureFailure=null,saving=false,pendingUpload=null,sessionAck=null,releaseAck=null;
const clientId='test',run={id:'b'.repeat(32)},held=new Map(),cancelledRuns=new Set();
const capture={recorderStarted:true,frames:1,autoRunId:run.id,stopping:false};
const document={hidden:false},game={focus(){}},keyNames={LEFT:'ArrowLeft'},skillKeyNames={};
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
 assert.equal(normalBody.ack,null);closed=true;process.exit(0);
})().catch(e=>{console.error(e);process.exit(1);});
'''
        result=subprocess.run([shutil.which('node'),'--max-old-space-size=64','-e',fixture+code+checks],capture_output=True,text=True,timeout=4)
        self.assertEqual(result.returncode,0,result.stderr)
