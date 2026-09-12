"""Synthetic preview artifacts; no API, game server, video decoder or deployment."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import full_client_skill_preview_publication as preview
from full_client_publication import digest, encoded, verify_package, publication_state
from full_client_skill_preview import contract, prompt
from full_client_vercel import PUBLIC_NAME, checked_payload
from maple_agent import SCHEMA
import test_full_client_catalog as catalog_fixture


class SkillPreviewPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.folder = self.root / 'private'; self.folder.mkdir()
        self.run_id = '1' * 32; self.model = 'gpt-6-astra'
        self.protocol = contract('ice_lightning_arch_mage', 'b' * 64)
        self.code = "await sdk.pressKeys(['RIGHT','SECONDARY_SKILL'],300);"
        self.observation = {'source': 'full-client', 'ready': True, 'ageMs': 0, 'renderAgeMs': 0,
            'character': {'alive': True, 'x': 100, 'y': 50}, 'monsters': []}
        controller = {'id': self.run_id, 'mode': 'api', 'status': 'completed',
            'model': self.model, 'returnedModel': self.model, 'protocol': preview.PROTOCOL,
            'previewProtocol': self.protocol, 'sdkRequestLimit': 600, 'actionLimit': 240,
            'programSeconds': 60, 'actions': 1, 'workerActive': False, 'reason': 'program_complete'}
        usage = {'input_tokens': 1000, 'output_tokens': 100, 'total_tokens': 1100}
        self.values = {
            'result': {'controller': controller, 'protocol': preview.PROTOCOL,
                'previewProtocol': self.protocol, 'score': None, 'publication_eligible': False,
                'api': {'model': self.model, 'status': 'completed', 'usage': usage},
                'model_api_requests': 1, 'programSha256': digest(self.code.encode()),
                'initial': self.observation, 'final': self.observation,
                'timing': {'startedAtMs': 70000, 'endedAtMs': 86000, 'elapsedMs': 16000},
                'timeline': {'api_started_ms': 1000, 'api_ended_ms': 14000,
                    'status': 'completed', 'program_started_ms': 15000,
                    'first_input_started_ms': 15100, 'first_input_acked_ms': 15400, 'program_ended_ms': 15500},
                'program': {'actions': 1, 'actionAttempts': 1, 'rpcRequests': 1,
                    'reason': 'program_complete', 'error': None, 'steps': [
                    {'kind': 'sdk', 'rpcId': 1, 'method': 'pressKeys', 'args': [['RIGHT', 'SECONDARY_SKILL'], 300],
                        'result': {'accepted': True, 'observation': self.observation}}]}, 'private_marker': 'must-never-export'},
            'api_request': {'model': self.model, 'instructions': prompt(self.protocol),
                'metadata': {'maplebench_run_id': self.run_id}, 'max_output_tokens': 3000,
                'text': {'format': {'schema': SCHEMA}},
                'reasoning': {'effort': 'low'}, 'input': json.dumps({'observation': self.observation})},
            'api_response': {'model': self.model, 'status': 'completed', 'usage': usage,
                'metadata': {'maplebench_run_id': self.run_id}, 'output': [{'type': 'message',
                    'content': [{'type': 'output_text', 'text': json.dumps({'note': 'synthetic', 'code': self.code})}]}]},
            'recording': {'status': 'completed', 'interrupted': False, 'post_render_capture': True,
                'sha256': digest(b'SYNTHETIC VIDEO'), 'overlay': {'controller_id': self.run_id,
                    'mode': 'api', 'model': self.model}, 'start_ms': 0, 'end_ms': 16000, 'duration_ms': 16000,
                'timing_uncertainty_ms': 10, 'timing_method': 'browser_monotonic_duration_with_measured_clock_offset'},
            'video_probe': {'video_sha256': digest(b'SYNTHETIC VIDEO'), 'duration_ms': 16000},
            'capture': {}, 'capture_ready': {}, 'capture_clock': {}, 'capture_terminal': {}}
        request = self.values['api_request']
        controller.update(totalTokenLimit=32000, apiTokenUpperBound=len(request['instructions'].encode())
            + len(request['input'].encode()) + len(json.dumps(SCHEMA).encode()) + 1024 + 3000)
        self.refs = {}
        for key, value in self.values.items(): self.save(key, value)
        for key, name, raw in [('program', 'program.js', self.code.encode()), ('video', 'video.webm', b'SYNTHETIC VIDEO')]:
            (self.folder / name).write_bytes(raw); self.refs[key] = {'path': name, 'sha256': digest(raw)}
        self.capture = patch.object(preview, 'verify_capture_bundle', return_value={}); self.capture.start()
        self.duration = patch.object(preview, 'verify_video_duration', return_value=None); self.duration.start()
        self.decoder = patch.object(preview, '_probe_video', return_value={'duration_ms': 16000}); self.decoder.start()

    def tearDown(self):
        self.capture.stop(); self.duration.stop(); self.decoder.stop(); self.temp.cleanup()

    def save(self, key, value):
        raw = encoded(value); name = key + '.json'; (self.folder / name).write_bytes(raw)
        self.refs[key] = {'path': name, 'sha256': digest(raw)}

    def row(self): return preview.project_preview(self.folder, self.refs)

    def test_preview_exposes_inputs_without_inventing_cast_or_score_evidence(self):
        row = self.row()
        self.assertEqual(row['actions'], 1); self.assertFalse(row['ranked']); self.assertIsNone(row['score'])
        self.assertEqual(len(row['skills']), 10)
        teleport = next(s for s in row['skills'] if s['name'] == 'Teleport')
        self.assertEqual(teleport['acknowledged_inputs'], 1)
        self.assertEqual(row['skill_evidence'], 'acknowledged_inputs_not_verified_casts')
        self.assertEqual(row['recording']['playback']['start_ms'], 14850)
        raw = json.dumps(row)
        for forbidden in ('must-never-export', 'instructions', self.code, 'api_request', 'private_marker'):
            self.assertNotIn(forbidden, raw)

    def test_wrong_model_saved_program_or_teleport_key_receipt_is_rejected(self):
        original = copy.deepcopy(self.values)
        mutations = [('api_response', lambda v: v.update(model='gpt-5.6-sol')),
            ('api_response', lambda v: v['output'][0]['content'][0].update(text=json.dumps({'code': 'other'}))),
            ('result', lambda v: v['program']['steps'][0]['result'].update(accepted=False)),
            ('result', lambda v: v['program']['steps'][0].update(args=[['UNMAPPED_SKILL'], 300])),
            ('result', lambda v: v['program']['steps'][0].update(method='moveTo', args=[100, 50])),
            ('result', lambda v: v['program']['steps'][0]['result']['observation'].update(ageMs=1500)),
            ('result', lambda v: v['program']['steps'][0].update(rpcId=2)),
            ('result', lambda v: v['program'].update(rpcRequests=2)),
            ('result', lambda v: v['program'].update(actionAttempts=2)),
            ('result', lambda v: v['timeline'].update(api_started_ms=-1)),
            ('result', lambda v: v.update(model_api_requests=2)),
            ('result', lambda v: v.update(publication_eligible=True)),
            ('result', lambda v: v['controller'].update(programSeconds=300)),
            ('recording', lambda v: v['overlay'].update(model='gpt-5.6-sol'))]
        for key, change in mutations:
            with self.subTest(key=key):
                value = copy.deepcopy(original[key]); change(value); self.save(key, value)
                with self.assertRaises(ValueError): self.row()
                self.save(key, original[key])

    def test_video_corruption_symlink_and_missing_input_time_fail(self):
        path = self.folder / 'video.webm'; path.write_bytes(b'changed')
        with self.assertRaises(ValueError): self.row()
        path.unlink(); (self.root / 'unrelated').write_bytes(b'SYNTHETIC VIDEO'); path.symlink_to(self.root / 'unrelated')
        with self.assertRaises((ValueError, OSError)): self.row()
        path.unlink(); path.write_bytes(b'SYNTHETIC VIDEO')
        result = copy.deepcopy(self.values['result']); result['timeline'].pop('first_input_started_ms')
        self.save('result', result)
        with self.assertRaisesRegex(ValueError, 'playback_cue'): self.row()

    def test_saved_probe_cannot_substitute_for_actual_decoder_evidence(self):
        with patch.object(preview, '_probe_video', return_value={'duration_ms': 15000}):
            with self.assertRaisesRegex(ValueError, 'decoder_evidence_changed'): self.row()

    def test_mount_is_tied_to_exact_run_and_cannot_carry_private_files(self):
        self.assertTrue(PUBLIC_NAME.fullmatch('previews/' + self.run_id + '/recordings/' + self.run_id + '.webm'))
        for name in ('previews/' + self.run_id + '/recordings/' + '2' * 32 + '.webm',
            'previews/' + self.run_id + '/result.json', 'previews/../secrets.json'):
            self.assertIsNone(PUBLIC_NAME.fullmatch(name))

    def test_attach_preserves_every_cohort_byte_and_benchmark_summary(self):
        catalog = catalog_fixture.CatalogTests(); catalog.setUp()
        try:
            original, snapshot = catalog.compose([catalog.package(catalog.fixture(), count=4)])
            root = self.root / 'public'; root.mkdir()
            refs_path = self.folder / 'artifacts.json'; refs_path.write_bytes(encoded(self.refs))
            selection = {'folder': str(self.folder), 'artifacts': refs_path.name,
                'artifacts_sha256': digest(refs_path.read_bytes())}
            outcome = preview.attach_previews(original, [selection], root)
            site = Path(outcome['site']); new = json.loads((site / 'results.json').read_text())
            self.assertEqual({k: v for k, v in new.items() if k != 'development_previews'}, snapshot)
            for path in (Path(original['site']) / 'cohorts').rglob('*'):
                if path.is_file(): self.assertEqual(path.read_bytes(), (site / path.relative_to(original['site'])).read_bytes())
            self.assertIn('Short skill previews', (site / 'index.html').read_text())
            self.assertNotIn('must-never-export', (site / 'results.json').read_text())
            self.assertEqual(len(new['development_previews']), 1)
            self.assertNotEqual(outcome['primary_content_sha256'], original['primary_content_sha256'])
            manifest = verify_package(Path(outcome['primary_package']), outcome['primary_content_sha256'])
            self.assertEqual(publication_state(Path(outcome['primary_package']), outcome['primary_content_sha256']), 'unclaimed')
            self.assertEqual(manifest['content']['presentation_parent_sha256'], original['primary_content_sha256'])
            checked_payload(site, Path(outcome['inventory']), outcome['inventory_sha256'], manifest)
            with self.assertRaisesRegex(ValueError, 'skill_preview_payload_binding_mismatch'):
                checked_payload(Path(original['site']), Path(original['inventory']), original['inventory_sha256'], manifest)
        finally: catalog.tearDown()


if __name__ == '__main__': unittest.main()
