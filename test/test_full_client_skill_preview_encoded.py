"""Synthetic encoded preview contracts; no API, browser, decoder or live world."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import full_client_skill_preview as preview
from full_client_bridge import FullClientBridge
from full_client_capture import ENCODED_FRAME_POLICY, capture_receipt, verify_video_duration
from full_client_publish import verify_capture_bundle
import test_full_client_capture as legacy
import test_full_client_native as native_fixture
import test_full_client_runtime as runtime_fixture


class PreviewEncodedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.protocol = preview.contract('ice_lightning_arch_mage', 'b' * 64)
        self.fixture = native_fixture.encoded_native_fixture()
        self.raw_video = b'SYNTHETIC ONLY: independent decoder is mocked'
        self.sha = hashlib.sha256(self.raw_video).hexdigest()
        self.fixture.value['encoder_receipt'].update(webm_sha256=self.sha, webm_bytes=len(self.raw_video))
        self.fixture.probe.update(webm_sha256=self.sha, webm_bytes=len(self.raw_video))
        self.owner = self.fixture.owner | {'protocol': preview.PROTOCOL, 'mode': 'api',
            'model': 'gpt-6-astra', 'previewProtocol': self.protocol}
        self.bridge = FullClientBridge(self.root / 'relay')
        self.bridge.run = copy.deepcopy(self.owner)
        self.folder = self.bridge.output / self.owner['id']
        self.folder.mkdir(parents=True)
        for name, value in (('request', self.owner), ('capture-ready', self.fixture.anchor),
                            ('capture-clock', self.fixture.clock), ('capture-terminal', self.fixture.terminal)):
            (self.folder / (name + '.json')).write_text(json.dumps(value))

    def attach(self, capture=None):
        temporary = self.root / 'upload.tmp'
        temporary.write_bytes(self.raw_video)
        return self.bridge.attach_recording(self.owner['id'], temporary, self.sha,
            client=self.owner['client'], capture=self.fixture.value if capture is None else capture)

    def result(self):
        return {'protocol': preview.PROTOCOL, 'previewProtocol': self.protocol,
            'controller': self.owner, 'timing': {'startedAtMs': 20000, 'endedAtMs': 22000},
            'timeline': {'api_started_ms': 200, 'program_started_ms': 500, 'program_ended_ms': 1800}}

    def manifest(self, recording):
        refs = {}
        for name, filename in (('capture', 'capture.json'), ('capture_ready', 'capture-ready.json'),
            ('capture_clock', 'capture-clock.json'), ('capture_terminal', 'capture-terminal.json'),
            ('recording', 'recording.json')):
            refs[name] = {'path': filename, 'sha256': hashlib.sha256((self.folder / filename).read_bytes()).hexdigest()}
        return {'result': self.result(), 'video': recording, 'artifacts': refs}

    def test_original_four_contract_and_prompt_hashes_are_unchanged(self):
        hashes = {
            'hero': ('e585c8d2ba21a30aa02ed114fae854846df723aad13f4cc5520076ae6718bd5c',
                     '52b2137e459f562b331dce86299d57dca27808806848d31d8e1345f15c180b11'),
            'bowmaster': ('f0d2716867ff88643b60e693bd553080cfc73dc1d1634bb7efef77e4ed64d2a6',
                          '7f91dafcb2f2424a2c9acdfeb6dde9c5b2853fa444a1371bfff2bea6f4400acc'),
            'ice_lightning_arch_mage': ('1826d375e4e970163fd7155b3db2934c423ae22cd6d0189e9aff8e1a2f416c56',
                                       'acd078ece25c3fed2821a17dc52b6cf65c6bb0cf35646184bc418a60f2e67c2a'),
            'night_lord': ('400283e413761beb30849ec8109b66553fcbaf7eb5f68accfc746e989f941a42',
                           '8e36f0142e7a64ff810f31d77fed11bbfc677452f3086877bb15dd3b06857286')}
        for cls, (contract_sha, prompt_sha) in hashes.items():
            with self.subTest(cls=cls):
                old = preview.contract(cls, 'b' * 64, protocol=preview.LEGACY_PROTOCOL)
                self.assertEqual(preview.fingerprint(old), contract_sha)
                self.assertEqual(hashlib.sha256(preview.prompt(old).encode()).hexdigest(), prompt_sha)
                self.assertNotIn('capture_duration_policy', old)
                new = preview.contract(cls, 'b' * 64)
                self.assertEqual(new['capture_duration_policy'], ENCODED_FRAME_POLICY)
                self.assertEqual(new['capture_max_ms'], 125000)
                self.assertIn('2500ms after each buff and 1500ms after each attack', preview.prompt(new))

    def test_policy_cannot_be_added_to_v1_removed_from_v2_or_changed(self):
        for changes in ({'id': preview.LEGACY_PROTOCOL}, {'capture_max_ms': 335000},
                        {'capture_duration_policy': None}, {'capture_duration_policy': {}},
                        {'capture_duration_policy': ENCODED_FRAME_POLICY | {'max_endpoint_gap_ms': 300}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                preview.validate_protocol(self.protocol | changes)
        missing = dict(self.protocol); missing.pop('capture_duration_policy')
        with self.assertRaises(ValueError): preview.validate_protocol(missing)
        missing = dict(self.protocol); missing.pop('capture_max_ms')
        with self.assertRaises(ValueError): preview.validate_protocol(missing)

    def test_actual_bridge_upload_and_shared_bundle_recompute_encoded_policy(self):
        recording = self.attach()
        self.assertFalse(recording['interrupted'])
        self.assertEqual(recording['capture_duration_policy'], ENCODED_FRAME_POLICY)
        self.assertEqual(recording['overlay'], {'controller_id': self.owner['id'],
                                              'mode': 'api', 'model': 'gpt-6-astra'})
        verify_video_duration(self.fixture.probe, recording, self.protocol['capture_duration_policy'])
        measured = verify_capture_bundle(self.manifest(recording), self.folder)
        self.assertEqual(measured['encoder_receipt'], self.fixture.value['encoder_receipt'])

    def test_preview_owner_and_controller_contract_cannot_be_downgraded_or_mixed(self):
        raw = self.fixture.value
        for update in ({'previewProtocol': None}, {'protocol': preview.LEGACY_PROTOCOL},
                       {'model': None}, {'mode': 'script'},
                       {'adaptiveProtocol': {'capture_duration_policy': ENCODED_FRAME_POLICY}}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                capture_receipt(raw, self.owner | update, self.fixture.anchor, self.fixture.clock, self.fixture.terminal)
        manifest = self.manifest(self.attach())
        for key, value in (('protocol', preview.LEGACY_PROTOCOL), ('previewProtocol', None), ('mode', 'script')):
            forged = copy.deepcopy(manifest); forged['result']['controller'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): verify_capture_bundle(forged, self.folder)

    def test_v2_rejects_legacy_metadata_before_attaching_video(self):
        old = legacy.CaptureTests(); old.setUp()
        with self.assertRaisesRegex(ValueError, 'invalid_capture_metadata'): self.attach(old.value)
        self.assertFalse((self.folder / 'video.webm').exists())
        self.assertFalse((self.folder / 'recording.json').exists())

    def test_v1_still_accepts_original_capture_and_keeps_100ms_tolerance(self):
        old = legacy.CaptureTests(); old.setUp()
        old_protocol = preview.contract('ice_lightning_arch_mage', 'b' * 64, protocol=preview.LEGACY_PROTOCOL)
        owner = self.owner | {'protocol': preview.LEGACY_PROTOCOL, 'previewProtocol': old_protocol}
        recording = capture_receipt(old.value, owner, old.anchor, old.clock, old.terminal)
        verify_video_duration({'duration_ms': 2400}, recording, old_protocol.get('capture_duration_policy'))
        with self.assertRaisesRegex(ValueError, 'recording_duration_mismatch'):
            verify_video_duration({'duration_ms': 2371.55}, recording)
        with self.assertRaises(ValueError):
            capture_receipt(self.fixture.value, owner, old.anchor, old.clock, old.terminal)

    def test_preview_capture_cannot_borrow_the_335_second_adaptive_limit(self):
        value = self.fixture.value | {'duration_ms': 125001, 'end_wall_ms': 135021}
        with self.assertRaisesRegex(ValueError, 'invalid_capture_measurement'): self.attach(value)

    def test_copy_after_logout_runs_real_duration_and_bundle_verifiers(self):
        self._copy_run()

    def test_changed_decoded_packet_is_rejected_during_runtime_collection(self):
        with self.assertRaisesRegex(ValueError, 'recording_duration_mismatch'):
            self._copy_run(corrupt=True)

    def test_missing_decoded_ledger_is_rejected_during_runtime_collection(self):
        with self.assertRaisesRegex(ValueError, 'recording_duration_mismatch'):
            self._copy_run(missing=True)

    def _copy_run(self, corrupt=False, missing=False):
        recording = self.attach()
        manifest = self.manifest(recording)
        harness = runtime_fixture.RuntimeTests(); harness.setUp()
        try:
            backend = harness.backend
            backend.config.update(relay_output_root=str(self.bridge.output), baseline={'sha256': 'b' * 64})
            backend.scenario = {'preview_protocol': self.protocol}
            backend.state.update(ordinary_logout={'synthetic': True}, result=manifest['result'])
            for name, ref in manifest['artifacts'].items():
                backend.state['artifacts'][name] = backend.artifact(ref['path'], raw=(self.folder / ref['path']).read_bytes())
            probe = copy.deepcopy(self.fixture.probe)
            if corrupt: probe['packet_sha256'][0] = '0' * 64
            if missing: probe.pop('encoder_ledger_json')
            with mock.patch('full_client_publish._probe_video', return_value=probe) as decoder:
                backend.copy_run()
            self.assertEqual(decoder.call_args.kwargs, {})  # Existing bounded 125-second decoder.
            saved = json.loads((backend.directory / 'video-probe.json').read_text())
            self.assertEqual(saved['video_sha256'], self.sha)
            self.assertEqual(saved['encoder_ledger_json'], self.fixture.probe['encoder_ledger_json'])
        finally:
            harness.tearDown()

    def test_capture_failure_diagnostic_uses_current_preview_policy_owner(self):
        diagnostic = {'schema_version': 1, 'run_id': self.owner['id'], 'policy_id': ENCODED_FRAME_POLICY['id'],
            'code': 'encoder_backpressure', 'clock_origin': 'encoder_start', 'elapsed_ms': 100,
            'first_frame_offset_ms': 0, 'last_frame_offset_ms': 100,
            'rendered_frames': 2, 'submitted_frames': 2, 'encoded_frames': 0}
        self.bridge._capture_failure(diagnostic, self.owner['client'], 20100)
        saved = (self.folder / 'capture-failure.json').read_bytes()
        self.bridge._capture_failure(diagnostic, self.owner['client'], 20101)
        self.assertEqual((self.folder / 'capture-failure.json').read_bytes(), saved)
        with self.assertRaises(ValueError): self.bridge._capture_failure(diagnostic, 'foreign-renderer', 20102)


if __name__ == '__main__': unittest.main()
