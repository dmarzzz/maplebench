import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_capture import capture_receipt


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.owner={'id':'a'*32,'client':'renderer','startedAtMs':20000}
        self.clock={'id':'b'*32,'client_sent_ms':10000,'server_received_ms':20010,'server_sent_ms':20012}
        self.anchor={'runId':'a'*32,'serverReceivedAtMs':20030,'renderedFrames':1}
        self.terminal={'id':'c'*32,'serverIssuedAtMs':22000}
        self.value={'schema_version':1,'run_id':'a'*32,'client_id':'renderer',
            'start_wall_ms':10020,'end_wall_ms':12520,'duration_ms':2500,
            'first_frame_wall_ms':10022,'last_frame_wall_ms':12518,'rendered_frames':150,
            'max_frame_gap_ms':18,'hidden':False,'errors':0,'relay_lost':False,'interrupted':False,
            'clock':self.clock|{'client_received_ms':10020},'terminal_token':'c'*32}

    def receipt(self,value=None):
        return capture_receipt(self.value if value is None else value,self.owner,self.anchor,self.clock,self.terminal)

    def test_measured_offset_interval_and_duration_are_explicit_and_unreviewed(self):
        receipt=self.receipt()
        self.assertEqual(receipt['clock_offset_ms'],{'lower':9992,'upper':10010})
        self.assertEqual(receipt['timing_uncertainty_ms'],9)
        self.assertEqual(receipt['start_ms'],21); self.assertEqual(receipt['end_ms'],2521)
        self.assertEqual(receipt['duration_ms'],2500)
        self.assertFalse(receipt['interrupted']); self.assertNotIn('reviewed',receipt)
        self.assertEqual(receipt['capture_ready_at_ms'],20030)
        self.assertEqual(receipt['terminal_observed_after_ms'],22000)

    def test_clock_receipt_cannot_be_forged_or_accepted_with_negative_uncertainty(self):
        for changes in ({'id':'d'*32},{'server_sent_ms':20013},{'client_received_ms':10001}):
            value=copy.deepcopy(self.value); value['clock'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.receipt(value)

    def test_hidden_gaps_errors_disconnect_and_clock_jump_are_interrupted(self):
        for changes in ({'hidden':True},{'errors':1},{'relay_lost':True},{'max_frame_gap_ms':1500},
                {'duration_ms':2000},{'terminal_token':None}):
            with self.subTest(changes=changes):
                self.assertTrue(self.receipt(self.value|changes)['interrupted'])

    def test_failed_capture_can_be_saved_without_fabricated_timing(self):
        value=self.value|{'clock':None,'rendered_frames':0,'first_frame_wall_ms':None,'last_frame_wall_ms':None}
        receipt=self.receipt(value)
        self.assertTrue(receipt['interrupted']); self.assertIsNone(receipt['start_ms'])
        self.assertEqual(receipt['timing_method'],'unavailable')

    def test_metadata_is_bounded_typed_and_identity_bound(self):
        for changes in ({'run_id':'d'*32},{'client_id':'other'},{'schema_version':True},
                {'duration_ms':float('nan')},{'rendered_frames':True},{'errors':-1},
                {'rendered_frames':100001},{'duration_ms':200000},{'private_string':'reject'},
                {'first_frame_wall_ms':13000},{'hidden':'false'},{'terminal_token':'arbitrary text'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.receipt(self.value|changes)


if __name__=='__main__': unittest.main()
