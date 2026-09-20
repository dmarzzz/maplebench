"""Offline coordinator tests; no game, API, Docker, database, or host changes."""
import copy
import hashlib
import sys
import time
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from full_client_hero_native_evidence import VERIFIER_PROTOCOL
from full_client_hero_native_runtime import (HeroNativeRuntime, _status,
    decode_recording_samples, execute_owned, qualification_scenario,
    verify_control_result)
from full_client_native import HERO_TOOLKIT_PROTOCOL, contract, program
from full_client_runtime import RuntimeErrorCode


def observation():
    return {'ready': True, 'ageMs': 1, 'renderAgeMs': 1,
            'character': {'alive': True}, 'monsters': []}


def control_result(native):
    steps = []
    selected = set(native['qualification_skill_ids'])
    for index, skill in enumerate((skill for skill in native['skill_toolkit']['skills']
                                   if skill['skill_id'] in selected), 1):
        steps.append({'kind': 'sdk', 'rpcId': index, 'method': 'pressKeys',
            'args': [[skill['slot']], 100],
            'result': {'accepted': True, 'observation': observation()}})
    owner = {'id': 'b' * 32, 'mode': 'script', 'model': None,
        'returnedModel': None, 'protocol': HERO_TOOLKIT_PROTOCOL,
        'nativeAcceptance': copy.deepcopy(native), 'status': 'completed',
        'reason': 'program_complete', 'workerActive': False,
        'actions': len(steps)}
    return {'protocol': HERO_TOOLKIT_PROTOCOL,
        'nativeAcceptance': copy.deepcopy(native), 'api': None,
        'trialContext': None,
        'source': 'client telemetry; unscored integration run',
        'model_api_requests': 0, 'publication_eligible': False, 'score': None,
        'programSha256': hashlib.sha256(program(native).encode()).hexdigest(),
        'controller': owner,
        'program': {'reason': 'program_complete', 'error': None,
            'steps': steps, 'actions': len(steps),
            'actionAttempts': len(steps), 'rpcRequests': len(steps)},
        'timeline': {'status': 'completed', 'program_started_ms': 100,
                     'program_ended_ms': 50100},
        'timing': {'startedAtMs': 1000000, 'endedAtMs': 1050100,
                   'elapsedMs': 50100, 'apiLatencyMs': 0}}


class TinyHost:
    def __init__(self):
        self.deadline = time.monotonic() + 1000
        self.admin_calls = []

    def remaining(self):
        return self.deadline - time.monotonic()

    def now(self):
        return 2000000000000

    def sleep(self):
        return None

    def admin(self, path, request, *, lock_fds=()):
        self.admin_calls.append((path, request, tuple(lock_fds)))
        return {'accepted': True}


class HeroNativeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.native = contract('hero', 'a' * 64,
            protocol=HERO_TOOLKIT_PROTOCOL)

    def test_control_result_accepts_all_ten_only_through_frozen_toolkit(self):
        actual = control_result(self.native)
        checked = verify_control_result(actual, self.native,
            {'run_id': 'b' * 32}, program(self.native).encode())
        self.assertEqual(checked['actions'], 10)
        self.assertEqual(checked['sdk_requests'], 10)
        changed = copy.deepcopy(actual)
        changed['program']['steps'][4]['args'][0] = ['DELETE']
        with self.assertRaisesRegex(RuntimeErrorCode,
                                    'hero_native_sdk_receipt_invalid'):
            verify_control_result(changed, self.native,
                {'run_id': 'b' * 32}, program(self.native).encode())

    def test_scenario_builder_binds_expanded_contract_and_baseline(self):
        value = qualification_scenario('a' * 64)
        self.assertEqual(value['protocol'], VERIFIER_PROTOCOL)
        self.assertEqual(value['native_contract'], self.native)

    def test_status_schema_is_exact_and_terminal_state_is_bounded(self):
        initial = {'started': False, 'sealed': False, 'failure': '',
            'events': 0, 'bytes': 0, 'sha256_last_line': '0' * 64,
            'start_monotonic_ns': 0, 'start_wall_ms': 0,
            'duration_ns': 120000000000}
        self.assertEqual(_status(initial), initial)
        terminal = initial | {'started': True, 'sealed': True, 'events': 2,
            'bytes': 100, 'sha256_last_line': 'a' * 64,
            'start_monotonic_ns': 1, 'start_wall_ms': 2}
        self.assertEqual(_status(terminal), terminal)
        for change in ({'duration_ns': 1}, {'extra': 1}, {'sealed': True}):
            with self.subTest(change=change), self.assertRaises(RuntimeErrorCode):
                _status(initial | change)

    def test_recording_samples_decode_three_private_pngs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            video = root / 'video.webm'
            video.write_bytes(b'video')
            def decode(argv, **kwargs):
                Path(argv[-1]).write_bytes(b'\x89PNG\r\n\x1a\nframe')
                return mock.Mock(returncode=0)
            with mock.patch('full_client_hero_native_runtime.shutil.which',
                            return_value='/usr/bin/ffmpeg'), \
                    mock.patch('full_client_hero_native_runtime.subprocess.run',
                               side_effect=decode) as called:
                value = decode_recording_samples(video, 'a' * 64, 120000, root)
            self.assertEqual([row['offset_ms'] for row in value['samples']],
                             [12000, 60000, 108000])
            self.assertEqual(value['visual_review_status'],
                             'not_established_by_decoder')
            self.assertEqual(called.call_count, 3)

    def test_lost_arm_reply_is_reconciled_once_without_reissuing_post(self):
        runtime = HeroNativeRuntime.__new__(HeroNativeRuntime)
        runtime.host = TinyHost()
        runtime.state = {'intents': [], 'artifacts': {}}
        runtime.persist = lambda: None
        runtime.intent = lambda value: runtime.state['intents'].append(value)
        runtime.artifact = lambda name, value: {'path': name, 'sha256': 'a' * 64}
        calls = []
        def request(method, suffix):
            calls.append((method, suffix))
            raise RuntimeErrorCode('hero_native_control_unavailable')
        runtime._control_request = request
        armed = {'started': True, 'sealed': False, 'failure': '',
            'events': 1, 'bytes': 10, 'sha256_last_line': 'a' * 64,
            'start_monotonic_ns': 1, 'start_wall_ms': runtime.host.now(),
            'duration_ns': 120000000000}
        runtime.skill_status = lambda: armed
        self.assertEqual(HeroNativeRuntime._transition(runtime, 'arm'), armed)
        self.assertEqual(calls, [('POST', 'arm')])
        self.assertEqual(runtime.state['intents'], ['skill_arm'])

    def test_native_window_seals_at_first_terminal_before_waiting_for_upload(self):
        runtime = HeroNativeRuntime.__new__(HeroNativeRuntime)
        runtime.host = TinyHost()
        runtime.native = self.native
        runtime.run_id = 'b' * 32
        runtime.manifest = {'docker_image_id': 'sha256:' + 'c' * 64}
        runtime.config = {'admin_socket': '/private/admin.sock'}
        runtime.context = {'lock_paths': {'world': '/w', 'queue': '/q'}}
        runtime.state = {'session': {'login_at_ms': 1}, 'intents': [],
                         'artifacts': {}}
        runtime.account_state = lambda: 2
        runtime.owned_server = lambda: None
        runtime.ownership = lambda: None
        runtime.quiet = lambda: None
        runtime.lock_fds = lambda: [3, 4]
        runtime.docker_binding = lambda: {'schema_version': 1}
        runtime.persist = lambda: None
        runtime.intent = lambda value: runtime.state['intents'].append(value)
        runtime.artifact = lambda name, value: {'path': name, 'sha256': 'a' * 64}
        runtime.identity = lambda: {'run_id': runtime.run_id,
            'server_instance_id': 'c' * 32, 'character_id': 5, 'account_id': 2}
        transitions = []
        arm = {'started': True, 'sealed': False, 'failure': '',
            'events': 1, 'bytes': 10, 'sha256_last_line': 'a' * 64,
            'start_monotonic_ns': 1, 'start_wall_ms': runtime.host.now(),
            'duration_ns': 120000000000}
        seal = arm | {'sealed': True, 'events': 2, 'bytes': 20,
                      'sha256_last_line': 'b' * 64}
        def transition(value):
            transitions.append(value)
            result = arm if value == 'arm' else seal
            runtime.state['skill_' + value + '_status'] = result
            return result
        runtime._transition = transition
        run = {'id': runtime.run_id, 'protocol': HERO_TOOLKIT_PROTOCOL,
               'nativeAcceptance': self.native, 'status': 'completed',
               'workerActive': True, 'evidenceStatus': 'saved',
               'recordingStatus': 'pending'}
        statuses = iter([
            {'bridge': {'run': run}, 'session': {'artifactsSettled': False}},
            {'bridge': {'run': run | {'workerActive': False,
                'recordingStatus': 'saved'}},
             'session': {'artifactsSettled': True}},
        ])
        runtime.admin = lambda op, **values: next(statuses)
        disconnected, collected = [], []
        runtime.request_ordinary_disconnect = lambda: disconnected.append(True)
        runtime.collect_controller_metadata = lambda: collected.append(True)
        result = HeroNativeRuntime.native_window(runtime)
        self.assertEqual(transitions, ['arm', 'seal'])
        self.assertEqual((disconnected, collected), ([True], [True]))
        self.assertEqual(result['api_calls'], 0)
        self.assertEqual(len(runtime.host.admin_calls), 1)

    def test_owned_executor_restores_after_success_and_failure(self):
        class Fake:
            def __init__(self, fail=False):
                self.host = TinyHost()
                self.fail = fail
                self.run_id = 'b' * 32
                self.state = {'schema_version': 1, 'attempt_id': self.run_id,
                    'server_instance_id': 'c' * 32, 'intents': [], 'events': [],
                    'session': {}, 'artifacts': {},
                    'maintenance_protocol': VERIFIER_PROTOCOL, 'clean': False,
                    'publication_eligible': False,
                    'native_input_reference': {'path': '/x', 'sha256': 'a' * 64}}
                self.token_factory = lambda: 'd' * 64
                self.phases = []
            def ownership(self): pass
            def validate_fresh_owner(self): pass
            def persist(self): pass
            def intent(self, value): self.state['intents'].append(value)
            def safe_boundary(self): pass
            def frozen(self): self.phases.append('frozen')
            def restore_baseline(self):
                self.state['intents'].append('restore_baseline')
                self.phases.append('restore_baseline')
            def start_server(self): self.phases.append('start_server')
            def login(self): self.phases.append('login')
            def native_window(self):
                self.phases.append('native_window')
                if self.fail: raise RuntimeErrorCode('hero_native_controller_failed')
            def collect_final(self):
                self.phases.append('collect_final')
                return {'accepted': True}
            def cleanup(self): self.phases.append('cleanup')
            def restore_after(self):
                self.phases.append('restore_after')
                self.state['native_restored'] = True
            def unit(self, name): return {'ActiveState': 'inactive', 'MainPID': '0'}
            def stopped(self, unit): return True
            def account_state(self): return 0
            def identity(self): return {'run_id': self.run_id,
                'server_instance_id': 'c' * 32, 'character_id': 5, 'account_id': 2}
            def artifact(self, name, value):
                return {'path': name, 'sha256': 'e' * 64}
        for failure in (False, True):
            with self.subTest(failure=failure):
                runtime = Fake(failure)
                receipt = execute_owned(runtime)
                self.assertEqual(runtime.phases[-2:], ['cleanup', 'restore_after'])
                self.assertTrue(receipt['clean'])
                self.assertTrue(receipt['native_restored'])
                self.assertEqual(receipt['failure'] is not None, failure)


if __name__ == '__main__':
    unittest.main()
