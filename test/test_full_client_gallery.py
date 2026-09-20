"""Synthetic publication fixtures only; no gameplay, model calls, or services."""
import hashlib
import json
import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_full_client_dashboard as fixtures
from full_client_gallery import export_once


class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.DashboardTests(); self.fixture.setUp()
        self.root=self.fixture.root; self.output=self.root/'gallery'; self.output.mkdir()
        self.a='a'*32; self.b='b'*32; self.cache={}

    def tearDown(self): self.fixture.tearDown()

    def attempt(self,run_id,status='completed',xp=0):
        folder,journal,_=self.fixture.attempt(run_id,status=status,xp=xp)
        raw=b'SYNTHETIC VIDEO BYTES '+run_id.encode()
        digest=hashlib.sha256(raw).hexdigest(); (folder/'video.webm').write_bytes(raw)
        refs=journal['receipts']['collect_final']['artifacts']
        recording=json.loads((folder/'recording.json').read_text())
        recording.update(sha256=digest,interrupted=False,post_render_capture=True)
        refs['recording']=self.fixture.write(folder/'recording.json',recording)
        refs['video']={'path':'video.webm','sha256':digest}
        self.fixture.write(folder/'journal.json',journal)
        return folder,journal

    def export(self,ids=None):
        return export_once(self.fixture.attempts,self.fixture.relay,self.output,ids or [self.a,self.b],
                           prefix='/full-client-benchmark/recordings/',cache=self.cache)

    def test_publishes_first_success_before_next_attempt_exists_and_preserves_zero_xp(self):
        folder,journal=self.attempt(self.a,xp=0)
        result=self.export()
        self.assertEqual(result['recording_uploads']['available'],[self.a])
        row=next(x for x in result['attempts'] if x['id']==self.a)
        self.assertEqual(row['persisted_xp'],0)
        self.assertFalse(row['recording']['reviewed'])
        self.assertFalse(row['ranked'])
        self.assertEqual((self.output/'recordings'/f'{self.a}.webm').read_bytes(),(folder/'video.webm').read_bytes())
        stamp=(self.output/'recordings'/f'{self.a}.webm').stat().st_mtime_ns
        self.attempt(self.b,xp=-50)
        result=self.export()
        self.assertEqual(result['recording_uploads']['available'],[self.a,self.b])
        self.assertEqual((self.output/'recordings'/f'{self.a}.webm').stat().st_mtime_ns,stamp)
        self.assertEqual(json.loads((folder/'journal.json').read_text()),journal)

    def test_no_recording_for_failed_running_or_unselected_attempt(self):
        self.attempt(self.a,status='failed'); self.attempt(self.b,status='running')
        self.attempt('c'*32)
        result=self.export()
        self.assertEqual(result['recording_uploads']['available'],[])
        self.assertEqual(list((self.output/'recordings').iterdir()),[])
        self.assertEqual(len(result['attempts']),3)

    def test_corrupt_video_does_not_hide_score_or_delay_next_success(self):
        folder,_=self.attempt(self.a); (folder/'video.webm').write_bytes(b'CORRUPT')
        self.attempt(self.b)
        result=self.export()
        self.assertEqual(result['recording_uploads'],{'available':[self.b],'unavailable':[self.a]})
        row=next(x for x in result['attempts'] if x['id']==self.a)
        self.assertEqual(row['persisted_xp'],0); self.assertIsNone(row['recording'])
        self.assertFalse((self.output/'recordings'/f'{self.a}.webm').exists())
        self.assertFalse(list((self.output/'recordings').glob('.recording-*')))

    def test_existing_conflict_and_symlinks_are_never_replaced(self):
        self.attempt(self.a); self.attempt(self.b)
        recordings=self.output/'recordings'; recordings.mkdir()
        target=recordings/f'{self.a}.webm'; target.write_bytes(b'PRESERVE')
        other=self.root/'outside'; other.write_bytes(b'PRIVATE')
        (recordings/f'{self.b}.webm').symlink_to(other)
        result=self.export()
        self.assertEqual(set(result['recording_uploads']['unavailable']),{self.a,self.b})
        self.assertEqual(target.read_bytes(),b'PRESERVE'); self.assertEqual(other.read_bytes(),b'PRIVATE')

    def test_cache_does_not_trust_replaced_recording(self):
        self.attempt(self.a); self.export([self.a])
        target=self.output/'recordings'/f'{self.a}.webm'; target.unlink(); target.write_bytes(b'REPLACED')
        result=self.export([self.a]); self.assertEqual(result['recording_uploads']['unavailable'],[self.a])

    def test_public_directory_cannot_contain_private_attempts(self):
        with self.assertRaisesRegex(ValueError,'outside_gallery'):
            export_once(self.fixture.attempts,None,self.root,[self.a])


if __name__=='__main__': unittest.main()
