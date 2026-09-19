"""Offline tests for the identity-free native Hero qualification projector."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import full_client_hero_qualification_public as public
from full_client_hero_native_evidence import TASK_ID, VERIFIER_PROTOCOL
from full_client_hero_native_runtime import qualification_scenario
from full_client_hero_toolkit import expected_keymap, expected_skills
from full_client_native import HERO_TOOLKIT_PROTOCOL, contract, fingerprint


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


class PublicHeroQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.baseline_sha = 'a' * 64
        self.native = contract('hero', self.baseline_sha,
                               protocol=HERO_TOOLKIT_PROTOCOL)
        self.refs = {}

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, name, value=None, raw=None):
        data = raw if raw is not None else encoded(value)
        (self.root / name).write_bytes(data)
        ref = {'path': name, 'sha256': hashlib.sha256(data).hexdigest()}
        self.refs[name] = ref
        return ref

    def snapshot(self, captured):
        keymap = expected_keymap(self.native['skill_toolkit']) + [
            [29, 5, 52], [57, 5, 53]]
        keymap.sort()
        return {'schema_version': 1, 'source': 'cosmic_persisted_character',
            'run_id': 'b' * 32, 'captured_at_ms': captured,
            'account_logged_in': 0,
            'character': {'character_id': 5, 'account_id': 2, 'job': 112,
                'level': 180, 'map_id': 240040511, 'exp': 0, 'hp': 30000},
            'keymap': keymap,
            'skill_toolkit_id': self.native['skill_toolkit']['id'],
            'learned_skills': expected_skills(self.native['skill_toolkit'])}

    def bundle(self):
        scenario_ref = self.write('scenario.json',
                                  qualification_scenario(self.baseline_sha))
        binary_pins = {'server_jar_sha256': 'c' * 64,
            'client_js_sha256': 'd' * 64, 'client_wasm_sha256': 'e' * 64}
        runtime_ref = self.write('runtime-manifest.json', {'schema_version': 2,
            'server_jar': {'path': '/private/server.jar',
                           'sha256': binary_pins['server_jar_sha256']},
            'client_js': {'path': '/private/JourneyClient.js',
                          'sha256': binary_pins['client_js_sha256']},
            'client_wasm': {'path': '/private/JourneyClient.wasm',
                            'sha256': binary_pins['client_wasm_sha256']}})
        pins = {'baseline_sha256': self.baseline_sha,
            'runtime_manifest_sha256': runtime_ref['sha256'],
            'qualification_scenario_sha256': scenario_ref['sha256'],
            **binary_pins}
        baseline_ref = self.write('baseline-snapshot.json', self.snapshot(1))
        initial_ref = self.write('initial-db.json', self.snapshot(2))
        restored_ref = self.write('restored-db.json', self.snapshot(3))
        identity = {'run_id': 'b' * 32, 'server_instance_id': 'f' * 32,
                    'character_id': 5, 'account_id': 2}
        reset_ref = self.write('reset.json', {'run_id': identity['run_id'],
            'baseline_sha256': self.baseline_sha, 'world_lock_held': True,
            'queue_lock_held': True, 'server_stopped': True, 'verified': True,
            'completed_at_ms': 1})
        session_ref = self.write('session.json', {**identity,
            'disconnect_kind': 'normal', 'world_lock_held_throughout': True,
            'queue_lock_held_throughout': True,
            'save': {'status': 'confirmed', 'save_error_count': 0}})
        ledger = b'{"private":"header"}\n{"private":"terminal"}\n'
        ledger_ref = self.write('native-skill.jsonl', raw=ledger)
        context = {**identity, 'runtime_sha256': runtime_ref['sha256'],
            'ledger_sha256': ledger_ref['sha256'], 'start_monotonic_ns': 1,
            'start_wall_ms': 1, 'duration_ns': 120000000000}
        context_ref = self.write('skill-context.json', context)
        status = {'started': True, 'sealed': False, 'failure': '', 'events': 1,
            'bytes': len(ledger.splitlines(keepends=True)[0]),
            'sha256_last_line': hashlib.sha256(
                ledger.splitlines(keepends=True)[0]).hexdigest(),
            'start_monotonic_ns': 1, 'start_wall_ms': 1,
            'duration_ns': 120000000000}
        arm_ref = self.write('skill-arm.json', status)
        seal_ref = self.write('skill-seal.json', status | {'sealed': True,
            'events': 2, 'bytes': len(ledger),
            'sha256_last_line': hashlib.sha256(
                ledger.splitlines(keepends=True)[-1]).hexdigest()})
        skills = sorted(self.native['qualification_skill_ids'])
        qualification = {'schema_version': 1, 'protocol': VERIFIER_PROTOCOL,
            'native_protocol': HERO_TOOLKIT_PROTOCOL, 'task_id': TASK_ID,
            'status': 'success', 'reason_code': 'all_core_skills_qualified',
            'qualified_skills': skills,
            'evidence': {'contract_sha256': fingerprint(self.native),
                         'ledger_sha256': ledger_ref['sha256'],
                         'skill_event_ids': {}},
            'publication_eligible': False, 'runtime_lifecycle_verified': False}
        qualification_ref = self.write('hero-skill-qualification.json', qualification)
        native_result_ref = self.write('result.json', {'private': True})
        native_program_ref = self.write('program.js', raw=b'private program\n')
        recording_ref = self.write('recording.json', {'status': 'completed',
            'sha256': hashlib.sha256(b'private video').hexdigest()})
        video_ref = self.write('video.webm', raw=b'private video')
        probe_ref = self.write('video-probe.json',
            {'video_sha256': video_ref['sha256'], 'duration_ms': 120000})
        png = b'\x89PNG\r\n\x1a\nprivate'
        samples = []
        for index, offset in enumerate((12000, 60000, 108000), 1):
            ref = self.write(f'video-sample-{index}.png', raw=png + bytes([index]))
            samples.append({'offset_ms': offset, **ref})
        samples_ref = self.write('video-samples.json', {'schema_version': 1,
            'source_video_sha256': video_ref['sha256'],
            'decoder': 'ffmpeg-single-frame-png-v1', 'samples': samples,
            'visual_review_status': 'not_established_by_decoder'})
        artifacts = {'scenario': scenario_ref, 'runtime_manifest': runtime_ref,
            'baseline_snapshot': baseline_ref, 'initial_db': initial_ref,
            'restored_db': restored_ref, 'reset': reset_ref, 'session': session_ref,
            'skill_ledger': ledger_ref, 'skill_context': context_ref,
            'skill_arm': arm_ref, 'skill_seal': seal_ref,
            'skill_qualification': qualification_ref,
            'native_result': native_result_ref, 'native_program': native_program_ref,
            'recording': recording_ref, 'video': video_ref,
            'video_probe': probe_ref, 'video_samples': samples_ref}
        control = {'actions': 10, 'sdk_requests': 10,
            'program_started_at_ms': 1, 'program_ended_at_ms': 2,
            'program_sha256': '9' * 64}
        result = {'schema_version': 1, 'protocol': VERIFIER_PROTOCOL, **identity,
            'api_calls': 0, 'model': None,
            'status': 'all_core_skills_qualified',
            'publication_eligible': False,
            'native_contract_sha256': fingerprint(self.native),
            'baseline_sha256': self.baseline_sha,
            'runtime_manifest_sha256': runtime_ref['sha256'],
            'qualification': qualification, 'control': control, 'artifacts': {}}
        receipt = {'schema_version': 1, 'protocol': VERIFIER_PROTOCOL, **identity,
            'status': 'native_skill_qualification_verified', 'api_calls': 0,
            'model': None, 'publication_eligible': False, 'clean': True,
            'native_restored': True, 'runtime_lifecycle_verified': True,
            'failure': None, 'result': result, 'artifacts': artifacts}
        receipt_ref = self.write('complete.json', receipt)
        return pins, receipt_ref, qualification, control

    def test_projects_exact_public_shape_after_recomputing_private_evidence(self):
        pins, receipt, qualification, control = self.bundle()
        with mock.patch.object(public, 'verify_events', return_value=qualification) as verify, \
                mock.patch.object(public, 'verify_control_result', return_value=control):
            value = public.project_qualification(self.root, receipt,
                native_contract=self.native, expected_pins=pins)
        self.assertEqual(value['instrumentation_mode'], 'qualification_only')
        self.assertEqual(value['qualification_scope'], 'core10')
        self.assertEqual(len(value['qualified_skills']), 10)
        self.assertEqual(len(value['available_skills']), 17)
        self.assertEqual(value['recording_evidence']['decoded_sample_count'], 3)
        self.assertNotIn('run_id', value)
        self.assertNotIn('character_id', value)
        verify.assert_called_once()
        self.assertEqual(verify.call_args.args[0],
                         b'{"private":"header"}\n{"private":"terminal"}\n')
        self.assertEqual(public.public_bytes(value,
            native_contract=self.native, expected_pins=pins), encoded(value))

    def test_rejects_recomputed_qualification_disagreement(self):
        pins, receipt, qualification, control = self.bundle()
        changed = copy.deepcopy(qualification)
        changed['qualified_skills'] = changed['qualified_skills'][:-1]
        with mock.patch.object(public, 'verify_events', return_value=changed), \
                mock.patch.object(public, 'verify_control_result', return_value=control), \
                self.assertRaisesRegex(public.QualificationProjectionError,
                                       'qualification_recomputation_failed'):
            public.project_qualification(self.root, receipt,
                native_contract=self.native, expected_pins=pins)

    def test_rejects_wrong_binary_pin_and_public_claim_expansion(self):
        pins, receipt, qualification, control = self.bundle()
        wrong = pins | {'server_jar_sha256': '0' * 64}
        with mock.patch.object(public, 'verify_events', return_value=qualification), \
                mock.patch.object(public, 'verify_control_result', return_value=control), \
                self.assertRaisesRegex(public.QualificationProjectionError,
                                       'runtime_manifest_binding_mismatch'):
            public.project_qualification(self.root, receipt,
                native_contract=self.native, expected_pins=wrong)
        with mock.patch.object(public, 'verify_events', return_value=qualification), \
                mock.patch.object(public, 'verify_control_result', return_value=control):
            value = public.project_qualification(self.root, receipt,
                native_contract=self.native, expected_pins=pins)
        value['recording_evidence']['visual_review_status'] = 'passed'
        with self.assertRaisesRegex(public.QualificationProjectionError,
                                   'invalid_public_qualification'):
            public.validate_public_qualification(value,
                native_contract=self.native, expected_pins=pins)


if __name__ == '__main__':
    unittest.main()
