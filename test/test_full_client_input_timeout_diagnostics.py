"""Exercise real pending-command dispatch and timeout paths with a finite clock."""
import json
import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_bridge import ControlError,FullClientBridge


class InputTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.ident='a'*32
        (self.root/self.ident).mkdir(mode=0o700)
        self.b=FullClientBridge(self.root);self.b.run.update(
            id=self.ident,client='renderer',status='running',protocol='full-client-adaptive-pilot-v1')
        self.now=100.0
        self.clock=mock.patch('full_client_bridge.time.monotonic',side_effect=lambda:self.now)
        self.wall=mock.patch('full_client_bridge.time.time',side_effect=lambda:1700000000+self.now)
        self.clock.start();self.wall.start();self.addCleanup(self.clock.stop);self.addCleanup(self.wall.stop)
        self.b.frame(self.frame())
        self.path=self.root/self.ident/'input-timeout.json'

    def frame(self,**changes):
        return {'client':'renderer','ageMs':0,'renderAgeMs':0,
            'observation':{'ready':True,'character':{'x':0,'y':0,'hp':100,'maxHp':100,
                'mp':10,'maxMp':20,'exp':0,'level':180,'mapId':1,'alive':True},'monsters':[]}}|changes

    def timeout(self,events,*,duration=1500):
        actions=iter(events)
        def wait(_seconds):
            # Exhaustion fails synchronously: no background thread can exit
            # before an awaited timeout or its assertions have completed.
            next(actions)()
        original=self.b._input_timeout
        def record(pending,now):
            self.assertIs(self.b.pending,pending);self.assertTrue(self.b.lock._is_owned())
            return original(pending,now)
        with mock.patch.object(self.b.lock,'wait',side_effect=wait), \
             mock.patch.object(self.b,'_input_timeout',side_effect=record):
            with self.assertRaisesRegex(TimeoutError,'did not acknowledge'):
                self.b.request('/v1/action',{'type':'press_keys','keys':['LEFT','PRIMARY_SKILL','JUMP'],
                    'durationMs':duration},timeout=3,run_id=self.ident)
        self.assertIsNone(self.b.pending)
        return json.loads(self.path.read_bytes()) if self.path.exists() else None

    def at(self,now,**body):
        self.now=now
        return self.b.frame(self.frame(**body))

    def expire(self):self.now=103.0

    def test_no_poll_timeout_records_request_origin_and_never_claims_dispatch(self):
        value=self.timeout([self.expire])
        self.assertFalse(value['dispatched']);self.assertIsNone(value['dispatch_elapsed_ms'])
        self.assertIsNone(value['dispatch_poll']);self.assertIsNone(value['matching_ack'])
        self.assertEqual(value['request_budget_ms'],3000);self.assertEqual(value['elapsed_request_ms'],3000)
        self.assertEqual(value['last_poll']['request_elapsed_ms'],0)
        self.assertEqual(value['last_poll']['elapsed_before_timeout_ms'],3000)
        self.assertEqual(value['outcome'],'uncertain');self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        self.assertFalse((self.path.parent/'capture-failure.json').exists())

    def test_fresh_late_poll_without_full_hold_budget_does_not_dispatch(self):
        def poll():self.assertIsNone(self.at(101.2)['command'])
        value=self.timeout([poll,self.expire])
        self.assertFalse(value['dispatched']);self.assertIsNone(value['matching_ack'])
        self.assertEqual(value['last_poll']['request_elapsed_ms'],1200)
        self.assertTrue(value['last_poll']['valid_frame'])

    def test_sent_command_without_ack_keeps_dispatch_and_later_stale_poll_facts(self):
        def send():
            command=self.at(100.2)['command'];self.assertEqual(command['durationMs'],1500)
            self.assertIn(command['remainingMs'],(2799,2800))
        def stale():self.assertIsNone(self.at(102.0,ageMs=1500,renderAgeMs=1600)['command'])
        value=self.timeout([send,stale,self.expire])
        self.assertTrue(value['dispatched']);self.assertEqual(value['dispatch_elapsed_ms'],200)
        self.assertTrue(value['dispatch_poll']['valid_frame']);self.assertFalse(value['last_poll']['valid_frame'])
        self.assertEqual(value['last_poll']['render_age_ms'],1600);self.assertIsNone(value['matching_ack'])
        self.assertEqual(value['dispatch_semantics'],'selected_for_browser_response')

    def test_matching_late_ack_race_is_observed_but_remains_uncertain(self):
        command=[]
        def send():command.append(self.at(100.1)['command']['id'])
        def late():
            self.at(103.1,ack={'id':command[0],'ok':True})
            self.assertNotIn('ack',self.b.pending)
        value=self.timeout([send,late])
        self.assertTrue(value['matching_ack']['ok']);self.assertFalse(value['matching_ack']['before_deadline'])
        self.assertTrue(value['matching_ack']['enough_hold_time']);self.assertEqual(value['remaining_ms'],-100)
        saved=self.path.read_bytes()
        self.at(103.2,ack={'id':command[0],'ok':True})
        self.assertEqual(self.path.read_bytes(),saved)

    def test_foreign_ack_and_extra_private_data_never_enter_receipt(self):
        def send():self.at(100.1)
        def foreign():
            self.at(102,private_debug='DO_NOT_COPY',ack={'id':'b'*32,'ok':False,'private_debug':'DO_NOT_COPY'})
        value=self.timeout([send,foreign,self.expire])
        self.assertIsNone(value['matching_ack']);self.assertNotIn('DO_NOT_COPY',self.path.read_text())
        self.assertEqual(set(value),{'schema_version','source','outcome','dispatch_semantics','run_id','command_id',
            'requested_at_ms','observed_at_ms','keys','duration_ms','dispatched','request_budget_ms','elapsed_request_ms',
            'dispatch_elapsed_ms','remaining_ms','request_poll','dispatch_poll','last_poll','matching_ack'})
        self.assertLess(self.path.stat().st_size,4096)

    def test_oversized_reported_ages_are_unknown_in_bounded_diagnostic(self):
        value=self.timeout([lambda:self.at(101,ageMs=350001,renderAgeMs=350001),self.expire])
        self.assertFalse(value['last_poll']['valid_frame'])
        self.assertIsNone(value['last_poll']['age_ms']);self.assertIsNone(value['last_poll']['render_age_ms'])

    def test_cancelled_request_stays_cancelled_without_timeout_diagnostic(self):
        def cancel(_seconds):self.b.cancel(self.ident)
        with mock.patch.object(self.b.lock,'wait',side_effect=cancel):
            with self.assertRaisesRegex(ControlError,'run_cancelled'):
                self.b.request('/v1/action',{'type':'press_keys','keys':['JUMP'],'durationMs':300},run_id=self.ident)
        self.assertIsNone(self.b.pending);self.assertFalse(self.path.exists())

    def test_existing_diagnostic_is_never_overwritten(self):
        self.timeout([self.expire]);original=(self.path.read_bytes(),self.path.stat().st_mtime_ns)
        self.now=100.;self.b.frame(self.frame())
        self.timeout([self.expire],duration=300)
        self.assertEqual((self.path.read_bytes(),self.path.stat().st_mtime_ns),original)
        self.assertEqual(self.b.run['inputTimeoutDiagnosticStatus'],'existing')

    def test_diagnostic_write_failure_does_not_replace_original_endpoint_timeout(self):
        with mock.patch.object(self.b,'_input_timeout',side_effect=OSError('private write failure')):
            self.assertIsNone(self.timeout([self.expire]))
        self.assertEqual(self.b.run['inputTimeoutDiagnosticStatus'],'write_failed')

    def test_timed_out_old_owner_cannot_create_receipt_for_new_run(self):
        def replace():self.expire();self.b.run['id']='b'*32
        self.assertIsNone(self.timeout([replace]));self.assertFalse(self.path.exists())


if __name__=='__main__':unittest.main()
