import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_capture import capture_receipt, CAPTURE_DURATION_POLICY, verify_video_duration, validate_duration_policy


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

    def test_long_capture_requires_explicit_adaptive_owner_and_retains_hard_cap(self):
        value=self.value|{'duration_ms':310000,'end_wall_ms':320020,'last_frame_wall_ms':320010}
        with self.assertRaises(ValueError):self.receipt(value)
        self.owner['protocol']='full-client-adaptive-pilot-v1'
        self.assertEqual(self.receipt(value)['duration_ms'],310000)
        with self.assertRaises(ValueError):self.receipt(value|{'duration_ms':335001})

    def test_metadata_is_bounded_typed_and_identity_bound(self):
        for changes in ({'run_id':'d'*32},{'client_id':'other'},{'schema_version':True},
                {'duration_ms':float('nan')},{'rendered_frames':True},{'errors':-1},
                {'rendered_frames':100001},{'duration_ms':200000},{'private_string':'reject'},
                {'first_frame_wall_ms':13000},{'hidden':'false'},{'terminal_token':'arbitrary text'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.receipt(self.value|changes)


class FrameEnvelopeTests(unittest.TestCase):
    """Synthetic new-clock offsets model the observed VFR endpoint mismatch.

    The old recording lacks these offsets and cannot be upgraded by this test.
    """
    receipt=CaptureTests.receipt

    def setUp(self):
        CaptureTests.setUp(self)
        self.owner.update(protocol='full-client-adaptive-pilot-v1',
            adaptiveProtocol={'capture_duration_policy':dict(CAPTURE_DURATION_POLICY)})
        self.value.update(schema_version=2,capture_duration_policy=dict(CAPTURE_DURATION_POLICY),
            first_frame_offset_ms=109,last_frame_offset_ms=301994.265,
            start_wall_ms=10020,end_wall_ms=312111,duration_ms=302090.265,
            first_frame_wall_ms=10129,last_frame_wall_ms=312015,
            rendered_frames=2337,max_frame_gap_ms=214.82)
        self.probe={'duration_ms':301973,'presentation_extent_ms':301973,
            'presentation_span_ms':301972,'last_packet_duration_ms':1,'frames':2338}

    def test_frame_envelope_accepts_measured_vfr_endpoints(self):
        recording=self.receipt()
        self.assertFalse(recording['interrupted'])
        verify_video_duration(self.probe,recording,CAPTURE_DURATION_POLICY)
        self.assertGreater(abs(self.probe['duration_ms']-recording['duration_ms']),100)

    def test_old_contract_and_missing_new_offsets_cannot_be_retroaccepted(self):
        with self.assertRaises(ValueError):verify_video_duration(self.probe,self.receipt())
        old={k:v for k,v in self.value.items() if k not in ('capture_duration_policy','first_frame_offset_ms','last_frame_offset_ms')}
        old['schema_version']=1
        with self.assertRaisesRegex(ValueError,'invalid_capture_metadata'):self.receipt(old)
        for key in ('first_frame_offset_ms','last_frame_offset_ms'):
            value=copy.deepcopy(self.value);value.pop(key)
            with self.assertRaises(ValueError):self.receipt(value)

    def test_truncation_extra_frames_and_unmeasured_padding_fail_closed(self):
        recording=self.receipt()
        for changes in ({'presentation_span_ms':301700,'presentation_extent_ms':301701},
                {'presentation_span_ms':302010,'presentation_extent_ms':302011},
                {'frames':2336},{'frames':2339},{'presentation_span_ms':float('nan')},
                {'presentation_extent_ms':302000},{'last_packet_duration_ms':1001},
                {'last_packet_duration_ms':1000,'presentation_extent_ms':302972,'duration_ms':302972}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                verify_video_duration(self.probe|changes,recording,CAPTURE_DURATION_POLICY)

    def test_clock_jumps_or_large_leading_trailing_gap_are_not_duration_slack(self):
        for changes in ({'duration_ms':302080},
                {'first_frame_offset_ms':300,'first_frame_wall_ms':10320,'max_frame_gap_ms':300},
                {'last_frame_offset_ms':301790,'last_frame_wall_ms':311810,'max_frame_gap_ms':301}):
            with self.subTest(changes=changes):
                recording=self.receipt(self.value|changes)
                self.assertTrue(recording['interrupted'])
                with self.assertRaises(ValueError):verify_video_duration(self.probe,recording,CAPTURE_DURATION_POLICY)
        with self.assertRaisesRegex(ValueError,'capture_frame_clock_mismatch'):
            self.receipt(self.value|{'last_frame_offset_ms':301900})

    def test_policy_is_exact_and_binds_browser_metadata_to_frozen_owner(self):
        from full_client_adaptive import DEFAULT_PROTOCOL,validate_protocol
        protocol=copy.deepcopy(DEFAULT_PROTOCOL);protocol['capture_duration_policy']=dict(CAPTURE_DURATION_POLICY)
        self.assertEqual(validate_protocol(protocol),protocol)
        for changes in ({'max_endpoint_gap_ms':1000},{'max_initial_frames':True},{'id':'unfrozen'}, {'extra':1}):
            bad=CAPTURE_DURATION_POLICY|changes
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):validate_duration_policy(bad)
                with self.assertRaises(ValueError):validate_protocol(protocol|{'capture_duration_policy':bad})
                with self.assertRaises(ValueError):self.receipt(self.value|{'capture_duration_policy':bad})



if __name__=='__main__': unittest.main()
