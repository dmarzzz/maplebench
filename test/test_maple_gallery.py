import importlib.util
import json
from functools import partial
from http.server import ThreadingHTTPServer
import http.client
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    'maple_gallery', Path(__file__).parents[1] / 'scripts/maple_gallery.py')
gallery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gallery)
server_spec = importlib.util.spec_from_file_location(
    'gallery_server', Path(__file__).parents[1] / 'scripts/serve-gallery.py')
server_module = importlib.util.module_from_spec(server_spec)
server_spec.loader.exec_module(server_module)


class GalleryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'batch'
        self.attempt = self.root / 'trial one' / 'attempt-1'
        self.attempt.mkdir(parents=True)
        self.batch = {'id': 'batch-01', 'name': 'Warrior smoke test', 'backend': 'cosmic-v83'}
        self.trial = {'id': 'trial-01', 'model': 'requested-model', 'scenario': 'henesys-slimes',
                      'repetition': 1, 'status': 'completed',
                      'attempt_dir': 'trial one/attempt-1'}

    def artifact(self, name, value):
        path = self.attempt / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return path

    def build(self, trials=None, batch=None):
        index = gallery.build_gallery(self.root, self.batch if batch is None else batch,
                                      [self.trial] if trials is None else trials)
        return index.read_text(), json.loads((self.root / 'summary.json').read_text())

    def test_existing_api_artifacts_produce_metrics_and_exact_provider_identity(self):
        self.artifact('score.json', {'reason': 'completed', 'durationMs': 27240,
                                    'xpGainedThisRun': 30, 'finalHp': 500,
                                    'accepted': 8, 'rejected': 2, 'decisions': 2})
        self.artifact('decisions.json', [
            {'response': {'model': 'provider-model-2026-01-01',
                          'usage': {'input_tokens': 100, 'output_tokens': 30, 'total_tokens': 130}}},
            {'response': {'model': 'provider-model-2026-01-01',
                          'usage': {'input_tokens': 200, 'output_tokens': 40, 'total_tokens': 240}}},
        ])
        self.artifact('video/henesys-overlay.mp4', 'fixture bytes; no real gameplay')
        page, summary = self.build()
        trial = summary['trials'][0]
        self.assertEqual(trial['model'], 'requested-model')
        self.assertEqual(trial['provider_models'], ['provider-model-2026-01-01'])
        self.assertEqual(trial['metrics']['duration_sec'], 27.24)
        self.assertEqual(trial['metrics']['xp_gained'], 30)
        self.assertEqual(trial['metrics']['total_tokens'], 370)
        self.assertEqual(trial['video_url'], 'trial%20one/attempt-1/video/henesys-overlay.mp4')
        self.assertIn('trial%20one/attempt-1/score.json', page)
        self.assertNotIn(str(self.root), page)

    def test_text_cannot_break_out_of_embedded_json_or_title(self):
        attack = '</script><script>alert("unsafe")</script><img onerror="alert(1)" src=x>'
        self.trial.update(model=attack, error=attack)
        page, summary = self.build(batch={**self.batch, 'name': attack})
        self.assertNotIn(attack, page)
        self.assertIn('\\u003c/script\\u003e', page)
        self.assertIn('&lt;/script&gt;', page)
        self.assertEqual(summary['trials'][0]['model'], attack)
        embedded = page.split('<script id="batch-data" type="application/json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(embedded), summary)

    def test_traversal_symlinks_urls_and_non_video_files_are_not_linked(self):
        outside = Path(self.temp.name) / 'outside.mp4'
        outside.write_bytes(b'outside')
        (self.attempt / 'escape.mp4').symlink_to(outside)
        for value in ['../outside.mp4', str(outside), 'https://example.invalid/a.mp4',
                      'javascript:alert(1)', 'trial one/attempt-1/escape.mp4']:
            with self.subTest(value=value):
                _, summary = self.build([{**self.trial, 'video_path': value}])
                self.assertIsNone(summary['trials'][0]['video_url'])
        self.artifact('score.json', {})
        _, summary = self.build([{**self.trial, 'video_path': 'trial one/attempt-1/score.json'}])
        self.assertIsNone(summary['trials'][0]['video_url'])
        (self.root / 'escape').symlink_to(outside.parent, target_is_directory=True)
        _, summary = self.build([{**self.trial, 'attempt_dir': 'escape'}])
        self.assertEqual(summary['trials'][0]['artifacts'], {})

    def test_gameplay_outcomes_are_distinct_from_worker_failures(self):
        trials = [{**self.trial, 'id': reason, 'status': 'completed', 'reason': reason}
                  for reason in ['completed', 'time_limit', 'death', 'decision_limit', 'budget_limit', 'action_limit']]
        trials.extend([{**self.trial, 'id': 'infra', 'status': 'infrastructure_error'},
                       {**self.trial, 'id': 'interrupted', 'status': 'interrupted'}])
        _, summary = self.build(trials)
        self.assertEqual(summary['counts'], {
            'completed': 1, 'time_limit': 1, 'death': 1, 'decision_limit': 1,
            'budget_limit': 1, 'action_limit': 1, 'infrastructure_error': 1, 'interrupted': 1})

    def test_mock_and_unknown_runs_cannot_inherit_server_label(self):
        self.artifact('controller.json', {'name': 'Local mock controller'})
        _, summary = self.build()
        self.assertEqual(summary['trials'][0]['provenance'], 'mock')
        (self.attempt / 'controller.json').unlink()
        _, summary = self.build(batch={'id': 'unknown-source'})
        self.assertEqual(summary['trials'][0]['provenance'], 'unverified')
        _, summary = self.build([{**self.trial, 'dry_run': True}])
        self.assertEqual(summary['trials'][0]['provenance'], 'mock')

    def test_missing_and_malformed_artifacts_remain_visible_with_unknown_metrics(self):
        (self.attempt / 'score.json').write_text('{partial')
        _, summary = self.build([{**self.trial, 'status': 'interrupted'}])
        self.assertEqual(summary['trials'][0]['outcome'], 'interrupted')
        self.assertIsNone(summary['trials'][0]['metrics']['hp'])
        self.assertIsNone(summary['trials'][0]['video_url'])

    def test_only_whitelisted_metadata_is_published_and_nonfinite_numbers_are_unknown(self):
        self.trial.update(secret_field='do-not-publish', metrics={'hp': float('nan'),
                          'input_tokens': 42, 'private_configuration': 'do-not-publish'})
        page, summary = self.build(batch={**self.batch, 'runtime_path': str(self.temp.name)})
        self.assertNotIn('do-not-publish', page)
        self.assertNotIn(self.temp.name, page)
        self.assertIsNone(summary['trials'][0]['metrics']['hp'])
        self.assertEqual(summary['trials'][0]['metrics']['input_tokens'], 42)

    def test_atomic_replacement_failure_preserves_previous_output_and_cleans_temporary_file(self):
        target = self.root / 'index.html'
        target.write_text('previous complete page')
        with patch.object(gallery.os, 'replace', side_effect=OSError('test failure')):
            with self.assertRaises(OSError):
                gallery._atomic_write(target, 'new page')
        self.assertEqual(target.read_text(), 'previous complete page')
        self.assertEqual(list(self.root.glob('.index.html-*')), [])

    def test_historical_attempts_use_their_own_evidence_and_outcome(self):
        first = self.root / 'trials/trial-01/attempt-01'
        second = self.root / 'trials/trial-01/attempt-02'
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        (first / 'score.json').write_text(json.dumps({'xpGainedThisRun': 10, 'reason': 'time_limit'}))
        _, summary = self.build([{**self.trial, 'attempt': 2,
            'attempt_dir': 'trials/trial-01/attempt-02', 'metrics': {'xp_gained': 99},
            'attempts': [{'number': 1, 'status': 'completed'}, {'number': 2, 'status': 'completed'}]}])
        self.assertEqual(len(summary['trials']), 2)
        previous, current = summary['trials']
        self.assertEqual(previous['attempt'], 1)
        self.assertEqual(previous['metrics']['xp_gained'], 10)
        self.assertEqual(previous['outcome'], 'time_limit')
        self.assertEqual(current['metrics']['xp_gained'], 99)


class GalleryServerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.attempt = self.root / 'batch-one/trials/trial-one/attempt-01'
        self.attempt.mkdir(parents=True)
        (self.root / 'batch-one/index.html').write_text('<h1>Gallery</h1>')
        (self.root / 'batch-one/summary.json').write_text(json.dumps({'batch': {'name': 'Batch one'}}))
        video = self.attempt / 'video/henesys-overlay.mp4'
        video.parent.mkdir()
        video.write_bytes(b'0123456789')
        runtime = self.root / 'batch-one/_runtime'
        runtime.mkdir()
        (runtime / 'baseline.sql').write_text('PRIVATE DATABASE')
        (self.root / 'queue.sqlite3').write_text('PRIVATE QUEUE')
        (self.root / 'batch-one/manifest.json').write_text('PRIVATE CONFIG')
        (self.root / 'batch-one/queue.json').write_text('PRIVATE QUEUE SNAPSHOT')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(server_module.GalleryHandler, root=self.root))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, method='GET', headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_public_navigation_and_byte_ranges_work(self):
        status, _, body = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn(b'batch-one/index.html', body)
        path = '/batch-one/trials/trial-one/attempt-01/video/henesys-overlay.mp4'
        status, headers, body = self.request(path, headers={'Range': 'bytes=2-5'})
        self.assertEqual((status, body), (206, b'2345'))
        self.assertEqual(headers['Content-Range'], 'bytes 2-5/10')
        self.assertEqual(headers['Content-Length'], '4')
        self.assertEqual(self.request(path, headers={'Range': 'bytes=-3'})[2], b'789')
        self.assertEqual(self.request(path, headers={'Range': 'bytes=7-'})[2], b'789')
        status, headers, body = self.request(path, method='HEAD')
        self.assertEqual((status, body, headers['Content-Length']), (200, b'', '10'))
        self.assertEqual(self.request(path, headers={'Range': 'bytes=20-30'})[0], 416)
        self.assertEqual(self.request(path, headers={'Range': 'bytes=0-1,3-4'})[0], 416)

    def test_private_paths_directory_listing_and_symlink_aliases_are_denied(self):
        (self.attempt / 'score.json').symlink_to(self.root / 'batch-one/_runtime/baseline.sql')
        paths = ['/queue.sqlite3', '/batch-one/manifest.json', '/batch-one/queue.json', '/batch-one/_runtime/baseline.sql', '/batch-one/_source/scripts/maplebench.py',
                 '/batch-one/', '/batch-one/trials/trial-one/attempt-01/',
                 '/batch-one/trials/trial-one/attempt-01/score.json',
                 '/batch-one/%2e%2e/queue.sqlite3', '/batch-one/%255f_runtime/baseline.sql']
        for path in paths:
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(status, 404)
                self.assertNotIn(b'PRIVATE', body)


if __name__ == '__main__':
    unittest.main()
