"""Actual serialized evidence bounds; no model, Docker or native world."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_bridge import adaptive_json_bytes,write_adaptive_final,ADAPTIVE_JSON_LIMIT,ControlError

class ArtifactCapTests(unittest.TestCase):
    def test_actual_compact_bytes_include_envelope_and_newline(self):
        value={'text':'x'*(ADAPTIVE_JSON_LIMIT-12)}
        raw=adaptive_json_bytes(value)
        self.assertEqual(len(raw),ADAPTIVE_JSON_LIMIT)
        self.assertEqual(json.loads(raw),value)
        with self.assertRaisesRegex(ControlError,'adaptive_artifact_byte_limit'):
            adaptive_json_bytes({'text':value['text']+'x'})
    def test_oversize_publication_does_not_write_or_replace_either_final(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            old=b'{"status":"failed","original":true}\n'
            (folder/'result.json').write_bytes(old)
            oversized={'result':{'steps':['x'*ADAPTIVE_JSON_LIMIT]}}
            with self.assertRaisesRegex(ControlError,'adaptive_artifact_byte_limit'):
                write_adaptive_final(folder,{'status':'completed'},oversized)
            self.assertEqual((folder/'result.json').read_bytes(),old)
            self.assertFalse((folder/'publication.json').exists())
            self.assertEqual(sorted(p.name for p in folder.iterdir()),['result.json'])
    def test_small_pair_remains_reconstructable(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);result={'status':'completed','steps':[]};publication={'result':result}
            write_adaptive_final(folder,result,publication)
            self.assertEqual(json.loads((folder/'result.json').read_bytes()),result)
            self.assertEqual(json.loads((folder/'publication.json').read_bytes()),publication)

    def test_actual_worker_keeps_last_trace_and_reports_small_failed_terminal(self):
        import full_client_bridge as bridge
        import time,hashlib
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            worker=bridge.FullClientBridge(directory)
            run={'id':'a'*32,'model':'gpt-6-astra','startedAtMs':round(time.time()*1000),
                 'adaptiveProtocol':{},'status':'running','workerActive':True}
            worker.run=dict(run);folder=worker.output/run['id'];folder.mkdir()
            prior={'status':'running','preserved':True}
            def failed_candidate(**kwargs):
                kwargs['persist_json']('adaptive.json',prior)
                kwargs['persist_json']('adaptive.json',{'steps':['x'*ADAPTIVE_JSON_LIMIT]})
                raise AssertionError('oversize must stop before returning completion')
            with patch.object(worker,'_wait_for_capture'),patch.object(worker,'request',return_value={}), \
                 patch.object(bridge,'run_adaptive',side_effect=failed_candidate):
                worker._run_adaptive(run)
            self.assertEqual(json.loads((folder/'adaptive.json').read_bytes()),prior)
            self.assertFalse((folder/'result.json').exists())
            terminal=json.loads((folder/'controller.json').read_bytes())
            self.assertEqual(terminal['status'],'failed')
            self.assertEqual(terminal['reason'],'adaptive_artifact_byte_limit')
            failure=json.loads((folder/'failure.json').read_bytes())
            self.assertEqual(failure['adaptiveTrace']['sha256'],hashlib.sha256((folder/'adaptive.json').read_bytes()).hexdigest())
            self.assertEqual(failure['apiOutcome'],'not_started')
            self.assertFalse(terminal['workerActive'])
