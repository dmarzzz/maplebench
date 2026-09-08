import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_capture import ENCODED_FRAME_POLICY as POLICY, capture_receipt, verify_video_duration
import test_full_client_capture as legacy

class EncodedCaptureTests(unittest.TestCase):
    def setUp(self):
        legacy.CaptureTests.setUp(self)
        self.owner.update(protocol='full-client-adaptive-pilot-v1',adaptiveProtocol={'capture_duration_policy':dict(POLICY)})
        self.ledger={'schema_version':1,'codec':'vp8','timebase_us':1000,'submitted_timestamps_us':[0,500000,1000000],
            'encoded_timestamps_us':[0,500000,1000000],'durations_us':[500000,500000,10000],
            'encoded_sha256':['d'*64,'e'*64,'f'*64],'flushed':True}
        raw=json.dumps(self.ledger,separators=(',',':'))
        self.encoder={'schema_version':1,'codec':'vp8','timebase_us':1000,'submitted_frames':3,'encoded_frames':3,
            'flushed':True,'ledger_sha256':hashlib.sha256(raw.encode()).hexdigest(),'ledger_bytes':len(raw),
            'webm_sha256':'1'*64,'webm_bytes':12345}
        self.value.update(schema_version=3,capture_duration_policy=dict(POLICY),encoder_receipt=self.encoder,
            duration_ms=1020,end_wall_ms=11040,first_frame_wall_ms=10030,last_frame_wall_ms=11030,
            first_frame_offset_ms=10,last_frame_offset_ms=1010,rendered_frames=3,max_frame_gap_ms=500)
        self.probe={'duration_ms':1010,'presentation_extent_ms':1010,'presentation_span_ms':1000,
            'last_packet_duration_ms':10,'frames':3,'packet_timestamps_us':[0,500000,1000000],
            'packet_durations_us':[500000,500000,10000],'packet_sha256':['d'*64,'e'*64,'f'*64],
            'encoder_ledger_json':raw,'webm_sha256':'1'*64,'webm_bytes':12345}
    def recording(self):
        return capture_receipt(self.value,self.owner,self.anchor,self.clock,self.terminal)|{'sha256':'1'*64}
    def test_exact_stream_ledger_and_clock_pass(self):
        verify_video_duration(self.probe,self.recording(),POLICY)
    def test_missing_duplicate_shifted_dropped_or_corrupt_packet_rejected(self):
        for update in ({'frames':2},{'packet_timestamps_us':[1000,501000,1001000]},
            {'packet_timestamps_us':[0,0,1000000]},{'packet_durations_us':[500000,500000,11000]},
            {'packet_sha256':['d'*64,'a'*64,'f'*64]},{'webm_sha256':'2'*64},{'webm_bytes':12346}):
            with self.subTest(update=update),self.assertRaises(ValueError):verify_video_duration(self.probe|update,self.recording(),POLICY)
    def test_receipt_is_strict_bounded_and_flushed(self):
        for update in ({'flushed':False},{'submitted_frames':True},{'encoded_frames':2},{'ledger_bytes':9000000},
                {'webm_bytes':100000000},{'extra':1}):
            self.value['encoder_receipt']=self.encoder|update
            with self.subTest(update=update),self.assertRaises(ValueError):self.recording()
    def test_ledger_cannot_be_replaced_or_omit_outputs_even_with_new_digest(self):
        for update in ({'encoded_timestamps_us':[0,500000]}, {'submitted_timestamps_us':[1,500000,1000000]},
                {'durations_us':[400000,500000,10000]},{'flushed':False},{'extra':1}):
            raw=json.dumps(self.ledger|update,separators=(',',':'))
            self.value['encoder_receipt']=self.encoder|{'ledger_sha256':hashlib.sha256(raw.encode()).hexdigest(),'ledger_bytes':len(raw)}
            with self.subTest(update=update),self.assertRaises(ValueError):verify_video_duration(self.probe|{'encoder_ledger_json':raw},self.recording(),POLICY)
    def test_original_policy_cannot_accept_new_receipt(self):
        from full_client_capture import CAPTURE_DURATION_POLICY
        with self.assertRaises(ValueError):verify_video_duration(self.probe,self.recording(),CAPTURE_DURATION_POLICY)
        with self.assertRaises(ValueError):verify_video_duration(self.probe,self.recording())
    def test_unmeasured_clock_endpoint_and_schema_rejected(self):
        for update in ({'schema_version':2},{'first_frame_offset_ms':20},{'rendered_frames':4}):
            original=copy.deepcopy(self.value);self.value.update(update)
            with self.subTest(update=update),self.assertRaises(ValueError):self.recording()
            self.value=original

class EncodedProbeTests(unittest.TestCase):
    def test_probe_extracts_exact_tag_hashes_and_frame_times(self):
        from full_client_publish import _measure_video_probe
        probe={'streams':[{'width':800,'height':720,'nb_read_frames':'2'}],
            'format':{'tags':{'MAPLEBENCH_ENCODER_LEDGER_V1':'{}'}},
            'packets':[{'pts_time':'0','duration_time':'0.050','flags':'K_','data_hash':'SHA256:'+'a'*64},
                       {'pts_time':'0.050','duration_time':'0.010','flags':'__','data_hash':'SHA256:'+'b'*64}]}
        measured=_measure_video_probe(probe)
        self.assertEqual(measured['packet_timestamps_us'],[0,50000])
        self.assertEqual(measured['packet_durations_us'],[50000,10000])
        self.assertEqual(measured['packet_sha256'],['a'*64,'b'*64])
        self.assertEqual(measured['encoder_ledger_json'],'{}')
        probe['packets'].reverse()
        with self.assertRaises(ValueError):_measure_video_probe(probe)
        probe['packets'].reverse();probe['packets'][0].pop('data_hash')
        with self.assertRaises(ValueError):_measure_video_probe(probe)
