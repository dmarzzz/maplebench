"""Synthetic executor checks. No services, database, API, or real control inputs."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import full_client_native_xp_runtime as executor
import full_client_runtime as runtime
import full_client_native as native
import full_client_native_xp_acceptance as acceptance
import full_client_xp_windows as windows
import test_full_client_runtime as base_tests
import test_full_client_native_xp_acceptance as envelope_tests
from test_full_client_xp_runtime import contract


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.fixture = base_tests.RuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.backend = self.fixture.backend
        self.backend.__class__ = executor.NativeXpRuntime
        self.host = self.fixture.host
        self.backend.maintenance_check = MagicMock()
        self.backend.ownership = self.backend.__class__.ownership.__get__(self.backend)
        self.backend.context = {'attempt_id': self.backend.run_id,
            'maintenance_protocol': acceptance.PROTOCOL, 'attempt_dir': str(self.backend.directory)}
        self.backend.state.update(maintenance_protocol=acceptance.PROTOCOL, clean=False, publication_eligible=False)
        self.backend.config.update(native_xp_protocol=acceptance.PROTOCOL, xp_window_protocol=windows.PROTOCOL)
        self.backend.native = native.contract('hero', '1' * 64)
        self.backend.scenario = {'protocol': acceptance.PROTOCOL, 'native_contract': self.backend.native,
                                 'xp_window_protocol': contract()}
        self.backend.baseline = {'character': {'character_id': 10, 'account_id': 20,
            'map_id': 1, 'level': 180, 'exp': 0}, 'keymap': [[29, 5, 52]], 'account_logged_in': 0}
        self.backend.config['baseline'] = self.fixture.ref('baseline', b'-- synthetic\n', raw=True)
        self.now = [2_000_000_000]
        self.backend.monotonic_ns = lambda: self.now[0]
        self.backend.coverage_sleep = lambda seconds: self.now.__setitem__(0, self.now[0] + round(seconds * 1e9))
        self.host.deadline = time.monotonic() + 1000
        self.host.remaining.return_value = 1000

    def bind_input(self):
        api = self.fixture.root / 'api'
        api.mkdir(mode=0o700)
        root = self.fixture.root / 'native-attempts'
        root.mkdir(mode=0o700)
        self.backend.directory.rename(root / self.backend.run_id)
        self.backend.directory = root / self.backend.run_id
        self.backend.config.update(attempt_root=str(root), api_attempt_root=str(api))
        self.backend.context['attempt_dir'] = str(self.backend.directory)
        value = {'schema_version': 1, 'protocol': acceptance.PROTOCOL, 'run_id': self.backend.run_id,
            'attempt_root': str(root), 'api_attempt_root': str(api),
            'config_sha256': hashlib.sha256(runtime.encoded(self.backend.config)).hexdigest()}
        path = self.fixture.root / 'native-input.json'
        raw = runtime.encoded(value)
        path.write_bytes(raw)
        ref = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}
        self.backend.context['native_input_reference'] = ref
        self.backend.state['native_input_reference'] = ref
        self.backend.persist()

    def test_fresh_separate_namespace_and_exact_config_are_bound(self):
        self.bind_input()
        self.backend.validate_fresh_owner()
        self.backend.config['services']['web'] = 'other.service'
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'input_binding_mismatch'):
            self.backend.validate_fresh_owner()
        self.host.admin.assert_not_called()

    def test_api_context_or_existing_native_evidence_is_never_reused(self):
        self.bind_input()
        self.backend.context['request'] = {'model': 'gpt-6-astra'}
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'owner_mismatch'):
            self.backend.validate_fresh_owner()
        del self.backend.context['request']
        (self.backend.directory / 'complete.json').write_text('{}')
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'existing_attempt_refused'):
            self.backend.validate_fresh_owner()

    def test_same_or_nested_api_namespace_is_refused(self):
        self.bind_input()
        self.backend.config['api_attempt_root'] = str(self.backend.directory.parent)
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'separate_namespace_required'):
            self.backend.validate_fresh_owner()

    def test_native_cannot_enter_model_dispatch_or_publication(self):
        for method in (lambda: self.backend.admin('start', model='gpt-6-astra'),
                       self.backend.run_controller, self.backend.write_publication_candidate,
                       lambda: self.backend.perform('run_controller', {})):
            with self.assertRaises(runtime.RuntimeErrorCode):
                method()
        self.host.admin.assert_not_called()
        self.assertEqual(self.backend.service_runtime_seconds(), 840)
        legacy = runtime.CosmicRuntime.__new__(runtime.CosmicRuntime)
        legacy.context = {'request': {'budgets': {'total_seconds': 1200}}}
        self.assertEqual(legacy.service_runtime_seconds(), 1320)

    def test_native_xp_opt_in_is_independent_of_adaptive_protocol(self):
        self.assertEqual(self.backend.xp_window_contract(), contract())
        self.backend.config.pop('native_xp_protocol')
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'explicit_protocol_required'):
            self.backend.xp_window_contract()

    def pin_fixture(self):
        self.backend.native = native.contract('hero', self.backend.config['baseline']['sha256'])
        self.backend.scenario['native_contract'] = self.backend.native
        self.backend.baseline['character']['job'] = 112
        self.fixture.ref('scenario', self.backend.scenario)
        self.fixture.ref('baseline_snapshot', self.backend.baseline)
        refs = []
        for name in executor.FROZEN_MODULES:
            path = Path(importlib.import_module(name).__file__).resolve()
            refs.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        candidate = {'path': str(self.fixture.root / 'synthetic-candidate.jar'), 'sha256': 'd' * 64}
        self.backend.config['native_xp_candidate_jar'] = candidate
        manifest = {'server_jar': candidate, 'extra_files': refs}
        self.fixture.ref('runtime_manifest', manifest)
        self.backend.docker_binding = MagicMock(return_value=self.fixture.binding)
        return manifest

    def test_separate_candidate_jar_and_executor_sources_must_be_in_new_manifest(self):
        manifest = self.pin_fixture()
        self.backend.load_pins()
        self.backend.config['native_xp_candidate_jar']['sha256'] = 'e' * 64
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'candidate_manifest_required'):
            self.backend.load_pins()
        self.backend.config['native_xp_candidate_jar']['sha256'] = 'd' * 64
        manifest['extra_files'].pop(0)
        self.fixture.ref('runtime_manifest', manifest)
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'executor_sources_not_frozen'):
            self.backend.load_pins()
        self.host.admin.assert_not_called()

    def test_wrong_baseline_class_is_refused_before_native_start(self):
        self.pin_fixture()
        self.backend.baseline['character']['job'] = 312
        self.fixture.ref('baseline_snapshot', self.backend.baseline)
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'baseline_mismatch'):
            self.backend.load_pins()
        self.host.admin.assert_not_called()

    def test_legacy_native_owner_still_requires_unconditionally_imported_skill_source(self):
        manifest=self.pin_fixture()
        self.assertNotIn('skill_toolkit',self.backend.native)
        manifest['extra_files']=[ref for ref in manifest['extra_files']
                                 if Path(ref['path']).name!='full_client_skill_toolkit.py']
        self.fixture.ref('runtime_manifest',manifest)
        with self.assertRaisesRegex(runtime.RuntimeErrorCode,'executor_sources_not_frozen'):
            self.backend.load_pins()
        self.host.admin.assert_not_called()

    def test_start_and_login_keep_the_cleanup_deadline_reserved(self):
        end = self.host.deadline
        for method, name, maximum in ((self.backend.login, 'login', 60),
                                      (self.backend.start_server, 'start_server', 90)):
            def fail():
                self.assertLessEqual(self.host.deadline, time.monotonic() + maximum)
                raise RuntimeErrorCodeForTest()
            with patch.object(runtime.CosmicRuntime, name, side_effect=fail):
                with self.assertRaises(RuntimeErrorCodeForTest): method()
            self.assertEqual(self.host.deadline, end)

    def row(self, sequence, **kwargs):
        return {'sequence': sequence, 'wall_ms': 1_000_000 + (self.now[0] - 2_000_000_000) // 1_000_000,
            'monotonic_ns': self.now[0], **self.backend.identity(), 'server_owned': True,
            'account_online': True, 'renderer_fresh': True, 'controller_idle': sequence == 0 or sequence >= 20}

    def window_fixture(self):
        self.backend.sample = MagicMock(side_effect=self.row)
        self.backend.manifest = {'docker_image_id': 'sha256:' + 'c' * 64}
        self.backend.docker_binding = MagicMock(return_value=self.fixture.binding)
        self.backend.context['lock_paths'] = {'world': '/synthetic-world', 'queue': '/synthetic-queue'}
        self.backend.lock_fds = MagicMock(return_value=[11, 12])

    def test_single_native_submission_then_301_fixed_owned_samples(self):
        self.window_fixture()
        def submitted(*args, **kwargs):
            durable = json.loads((self.backend.directory / 'backend-state.json').read_text())
            self.assertIn('native_control_submit', durable['intents'])
            self.assertEqual(args[1]['op'], 'start_native')
            self.assertEqual(kwargs['lock_fds'], [11, 12])
        self.host.admin.side_effect = submitted
        self.backend.native_window()
        self.assertEqual(self.host.admin.call_count, 1)
        self.assertEqual(self.backend.sample.call_count, 301)
        self.assertEqual(self.now[0], 302_000_000_000)
        self.assertTrue(self.backend.state['coverage_verified'])
        self.assertEqual(self.backend.state['window']['deadline_at_ms'], 1_300_000)

    def test_uncertain_native_submission_is_durable_and_never_repeated(self):
        self.window_fixture()
        self.host.admin.side_effect = OSError('synthetic lost reply')
        with self.assertRaises(OSError): self.backend.native_window()
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'already_submitted'): self.backend.native_window()
        self.assertEqual(self.host.admin.call_count, 1)
        self.assertNotIn('coverage_verified', self.backend.state)

    def test_sixty_second_toolkit_window_uses_its_exact_native_contract(self):
        from full_client_skill_toolkit import NATIVE_PROTOCOL
        self.window_fixture()
        self.backend.native=native.contract('hero',self.backend.config['baseline']['sha256'],protocol=NATIVE_PROTOCOL)
        def sample(sequence,**kwargs):
            return self.row(sequence)|{'controller_idle':sequence==0 or sequence>=60}
        self.backend.sample.side_effect=sample
        self.backend.native_window()
        self.assertTrue(self.backend.state['coverage_verified'])
        self.assertEqual(self.backend.state['window']['deadline_at_ms'],1300000)
        self.assertEqual(self.host.admin.call_count,1)
        self.assertEqual(self.host.admin.call_args.args[1]['native_acceptance'],self.backend.native)
        ref=self.backend.state['artifacts']['coverage']
        rows=[json.loads(line) for line in (self.backend.directory/ref['path']).read_bytes().splitlines()]
        self.assertFalse(rows[40]['controller_idle']);self.assertTrue(rows[60]['controller_idle'])

    def test_insufficient_window_time_refuses_before_native_intent_or_submission(self):
        self.window_fixture()
        self.host.remaining.return_value = 344.99
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'window_time_insufficient'):
            self.backend.native_window()
        self.host.admin.assert_not_called()
        self.assertEqual(self.backend.state['intents'], [])

    def test_wrapper_preflight_time_does_not_extend_original_deadline(self):
        self.backend.validate_fresh_owner = MagicMock()
        self.backend.safe_boundary = MagicMock()
        self.host.deadline = time.monotonic() + 880
        self.host.remaining.side_effect = [880, 494]
        original = self.host.deadline
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'preflight_unconfirmed'):
            executor.execute_owned(self.backend)
        self.assertEqual(self.host.deadline, original)
        self.assertNotIn('restore_baseline', self.backend.state['intents'])
        failure = json.loads((self.backend.directory / 'failure.json').read_text())
        self.assertEqual(failure['phase'], 'preflight')
        self.assertEqual(failure['reason'], 'native_xp_preflight_time_insufficient')

    def status_fixture(self, *, elapsed=20_000):
        self.backend.safe_boundary = MagicMock()
        self.backend.owned_server = MagicMock()
        self.backend.account_state = MagicMock(return_value=2)
        self.backend.state['window'] = {'start_at_ms': 1_000_000}
        self.host.now.return_value = 1_000_000 + elapsed
        status = {'session': {'state': 'connected', 'fresh': True, 'pinned': True,
                             'artifactsSettled': True, 'captureState': 'idle'},
            'observation': {'character': {'mapId': 1}, 'monsters': [{'id': 1}]},
            'bridge': {'fresh': True, 'browserReleasePending': False,
                'run': {'id': self.backend.run_id, 'mode': 'script', 'model': None,
                    'protocol': self.backend.native['id'], 'status': 'completed', 'workerActive': False,
                    'recordingStatus': 'saved', 'evidenceStatus': 'saved'}}}
        self.host.admin.return_value = status
        folder = Path(self.backend.config['relay_output_root']) / self.backend.run_id
        folder.mkdir(parents=True, exist_ok=True)
        for name in (*executor.CONTROL_FILES.values(), 'video.webm'):
            if not (folder/name).exists(): (folder/name).write_bytes(b'{}')
        return status

    def test_large_video_is_not_copied_or_read_during_terminal_sampling(self):
        self.status_fixture()
        self.backend.collect_short_control = MagicMock(side_effect=AssertionError('heavy copy in sampling'))
        self.backend.read_stable = MagicMock(side_effect=AssertionError('artifact read in sampling'))
        video = Path(self.backend.config['relay_output_root']) / self.backend.run_id / 'video.webm'
        with video.open('wb') as f: f.truncate(96 * 1024 * 1024)
        row = self.backend.sample(20)
        self.assertTrue(row['controller_idle'])
        self.backend.collect_short_control.assert_not_called()
        self.backend.read_stable.assert_not_called()
        self.assertIn('short_control_terminal', self.backend.state)
        self.assertEqual([c.args[1]['op'] for c in self.host.admin.call_args_list], ['status'])

    def test_changed_or_missing_terminal_artifacts_reject_before_deferred_copy(self):
        self.status_fixture()
        self.backend.sample(20)
        self.backend.state['coverage_verified'] = True
        self.backend.account_state.return_value = 0
        self.backend.disconnect = MagicMock()
        self.backend.read_stable = MagicMock(side_effect=AssertionError('copy before pin check'))
        source = Path(self.backend.config['relay_output_root']) / self.backend.run_id
        (source/'result.json').write_bytes(b'{"changed":true}')
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'terminal_evidence_changed'):
            self.backend.collect_short_control()
        (source/'result.json').unlink()
        with self.assertRaises(FileNotFoundError): self.backend.collect_short_control()
        self.backend.read_stable.assert_not_called()

    def test_missing_terminal_file_never_latches_success_and_symlink_is_refused(self):
        self.status_fixture()
        source = Path(self.backend.config['relay_output_root']) / self.backend.run_id
        (source/'result.json').unlink()
        with self.assertRaises(FileNotFoundError): self.backend.sample(20)
        self.assertNotIn('short_control_terminal', self.backend.state)
        (source/'result.json').symlink_to(source/'controller.json')
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'terminal_evidence_changed'):
            self.backend.sample(20)
        self.assertNotIn('short_control_terminal', self.backend.state)

    def test_deferred_copy_requires_verified_coverage_and_offline_account(self):
        self.status_fixture()
        self.backend.sample(20)
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'offline_coverage'):
            self.backend.collect_short_control()
        self.backend.state['coverage_verified'] = True
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'offline_coverage'):
            self.backend.collect_short_control()

    def test_latched_capture_cannot_revert_to_pending_or_change_identity(self):
        status = self.status_fixture()
        self.backend.sample(20)
        status['bridge']['run']['recordingStatus'] = 'pending'
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'short_capture_not_saved'):
            self.backend.sample(21)

    def test_final_collection_orders_logout_before_deferred_artifact_read(self):
        self.backend.safe_boundary = MagicMock()
        self.backend.state['coverage_verified'] = True
        events = []
        self.backend.disconnect = MagicMock(side_effect=lambda: events.append('logout'))
        def stop_after_copy():
            events.append('copy')
            raise RuntimeError('stop_after_order_verified')
        self.backend.collect_short_control = MagicMock(side_effect=stop_after_copy)
        with self.assertRaisesRegex(RuntimeError, 'stop_after_order_verified'):
            self.backend.collect_final()
        self.assertEqual(events, ['logout', 'copy'])

    def test_stale_scene_changed_run_and_control_overrun_are_refused(self):
        for failure in ('stale', 'other_run', 'late'):
            status = self.status_fixture(elapsed=35_000)
            if failure == 'stale': status['bridge']['fresh'] = False
            elif failure == 'other_run': status['bridge']['run']['id'] = 'c' * 32
            else: status['bridge']['run'].update(status='running', workerActive=True)
            with self.subTest(failure=failure), self.assertRaises(runtime.RuntimeErrorCode):
                self.backend.sample(35)
        self.assertNotIn('coverage_verified', self.backend.state)

    def test_native_control_may_use_existing_start_delay_but_must_settle_by_35_seconds(self):
        for elapsed in (30_000, 33_000, 34_999):
            status = self.status_fixture(elapsed=elapsed)
            status['bridge']['run'].update(status='running', workerActive=True)
            row = self.backend.sample(elapsed // 1000)
            self.assertFalse(row['controller_idle'])
        self.status_fixture(elapsed=35_000)
        self.backend.collect_short_control = MagicMock()
        self.assertTrue(self.backend.sample(35)['controller_idle'])

    def test_completed_label_without_inactive_worker_does_not_satisfy_deadline(self):
        status = self.status_fixture(elapsed=35_000)
        status['bridge']['run']['workerActive'] = True
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'native_xp_control_exceeded_recipe'):
            self.backend.sample(35)
        self.assertNotIn('coverage_verified', self.backend.state)

    def test_capture_collection_limit_does_not_move_with_control_start_delay(self):
        status = self.status_fixture(elapsed=45_000)
        status['bridge']['run'].update(recordingStatus='pending', evidenceStatus='pending')
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'native_xp_short_capture_not_saved'):
            self.backend.sample(45)

    def restore_fixture(self, reset=True):
        self.backend.safe_boundary = MagicMock()
        self.backend.account_state = MagicMock(return_value=0)
        self.backend.sql = MagicMock()
        self.backend.prepare_cleanup_wait = MagicMock()
        self.backend.state['intents'] = ['restore_baseline']
        if reset: self.backend.state['reset'] = {'verified': True}
        self.host.snapshot.return_value = copy.deepcopy(self.backend.baseline)

    def test_final_restore_lost_reply_is_only_inspected_not_replayed(self):
        self.restore_fixture()
        self.backend.sql.side_effect = OSError('lost SQL reply')
        with self.assertRaises(OSError): self.backend.restore_after()
        self.backend.restore_after()
        self.assertEqual(self.backend.sql.call_count, 1)
        self.assertTrue(self.backend.state['native_restored'])

    def test_initial_restore_uncertain_never_reissues_sql(self):
        self.restore_fixture(reset=False)
        self.backend.restore_after()
        self.backend.sql.assert_not_called()
        self.host.snapshot.return_value['character']['exp'] = 1
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'restore_unconfirmed'):
            self.backend.restore_after()
        self.backend.sql.assert_not_called()

    def test_restore_without_original_restore_intent_cannot_write(self):
        self.restore_fixture()
        self.backend.state['intents'] = []
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'initial_restore_not_started'):
            self.backend.restore_after()
        self.backend.sql.assert_not_called()

    def test_short_probe_keeps_existing_decoder_cap_then_enforces_45_seconds(self):
        arts = self.backend.state['artifacts']
        arts['recording'] = self.backend.artifact('recording.json', {'sha256': '1' * 64})
        arts['native_result'] = self.backend.artifact('result.json', {})
        arts['video'] = {'path': 'short.webm', 'sha256': '1' * 64}
        probe = {'duration_ms': 25_000, 'presentation_span_ms': 24_999, 'presentation_extent_ms': 25_000}
        with patch('full_client_publish._probe_video', return_value=probe) as measure, \
             patch('full_client_capture.verify_video_duration') as duration, \
             patch('full_client_publish.verify_capture_bundle') as capture:
            self.backend.verify_short_capture()
            measure.assert_called_once_with(self.backend.directory / 'short.webm', '1' * 64)
            duration.assert_called_once()
            capture.assert_called_once()
        probe['presentation_extent_ms'] = 45_001
        with patch('full_client_publish._probe_video', return_value=probe), \
             self.assertRaisesRegex(runtime.RuntimeErrorCode, 'short_video_bound'):
            self.backend.verify_short_capture()

    def test_preflight_failure_preserved_without_cleanup_or_sql(self):
        self.backend.validate_fresh_owner = MagicMock()
        self.backend.safe_boundary = MagicMock()
        self.backend.frozen.side_effect = RuntimeErrorCodeForTest()
        self.backend.cleanup = MagicMock()
        self.backend.restore_after = MagicMock()
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'preflight_unconfirmed'):
            executor.execute_owned(self.backend)
        self.backend.cleanup.assert_not_called()
        self.backend.restore_after.assert_not_called()
        self.assertIn('failure', self.backend.state['artifacts'])
        self.assertFalse(self.backend.state['clean'])
        self.assertFalse((self.backend.directory / 'complete.json').exists())

    def test_completed_flow_keeps_passive_window_before_logout_and_requires_restore(self):
        self.backend.validate_fresh_owner = MagicMock()
        self.backend.safe_boundary = MagicMock()
        order = []
        def phase(name):
            def call():
                order.append(name)
                if name == 'restore_baseline':
                    self.backend.intent('restore_baseline')
                    self.backend.state['reset'] = {'verified': True}
                if name == 'restore_after': self.backend.state['native_restored'] = True
                if name == 'collect_final': return {'native_hook_accepted': False, 'publication_eligible': False}
            return call
        for name in ('restore_baseline', 'start_server', 'login', 'native_window',
                     'request_ordinary_disconnect', 'collect_final', 'cleanup', 'restore_after'):
            setattr(self.backend, name, MagicMock(side_effect=phase(name)))
        result = executor.execute_owned(self.backend)
        self.assertEqual(order, ['restore_baseline', 'start_server', 'login', 'native_window',
            'request_ordinary_disconnect', 'collect_final', 'cleanup', 'restore_after'])
        self.assertEqual(result['api_calls'], 0)
        self.assertIsNone(result['model'])
        self.assertFalse(result['result']['native_hook_accepted'])
        self.assertFalse(result['publication_eligible'])
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'fresh_owned_state_required'):
            executor.execute_owned(self.backend)
        self.assertEqual(order.count('native_window'), 1)

    def failed_flow(self):
        self.backend.validate_fresh_owner = MagicMock()
        self.backend.safe_boundary = MagicMock()
        def restore():
            self.backend.intent('restore_baseline')
            self.backend.state['reset'] = {'verified': True}
        self.backend.restore_baseline = restore
        self.backend.start_server = MagicMock()
        self.backend.login = MagicMock()
        self.backend.native_window = MagicMock(side_effect=runtime.RuntimeErrorCode(
            'native_xp_control_failed_or_identity_changed'))
        self.backend.cleanup = MagicMock()
        def restored(): self.backend.state['native_restored'] = True
        self.backend.restore_after = MagicMock(side_effect=restored)

    def test_failed_control_can_close_cleanly_without_becoming_accepted(self):
        self.failed_flow()
        receipt = executor.execute_owned(self.backend)
        self.assertEqual(receipt['status'], 'failed_native_xp_closed')
        self.assertEqual(receipt['failure']['reason'], 'native_xp_control_failed_or_identity_changed')
        self.assertIsNone(receipt['result'])
        self.assertTrue(receipt['clean'])
        self.assertFalse(receipt['publication_eligible'])
        self.backend.native_window.assert_called_once()

    def test_failed_restore_leaves_unclosed_state_and_no_success_receipt(self):
        self.failed_flow()
        self.backend.restore_after.side_effect = runtime.RuntimeErrorCode('native_xp_restore_unconfirmed')
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'restore_unconfirmed'):
            executor.execute_owned(self.backend)
        self.assertFalse(self.backend.state['clean'])
        self.assertFalse((self.backend.directory / 'complete.json').exists())
        self.assertIn('failure', self.backend.state['artifacts'])


class RuntimeErrorCodeForTest(Exception):
    pass


class IndependentCollectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = envelope_tests.NativeEnvelopeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root.resolve()
        self.backend = executor.NativeXpRuntime.__new__(executor.NativeXpRuntime)
        self.backend.directory = self.root
        self.backend.run_id = 'a' * 32
        self.backend.host = MagicMock()
        self.backend.host.now.return_value = 1_304_000
        self.backend.config = {'mysql': {'character_id': 7, 'account_id': 9},
            'native_xp_protocol': acceptance.PROTOCOL, 'xp_window_protocol': windows.PROTOCOL,
            'baseline': {'sha256': self.fixture.manifest['baseline_sha256']},
            'scenario': {'sha256': self.fixture.manifest['scenario_fingerprint']}, 'journalctl': '/usr/bin/journalctl'}
        self.backend.scenario = self.read('scenario')
        self.backend.native = self.backend.scenario['native_contract']
        self.backend.safe_boundary = MagicMock()
        self.backend.disconnect = MagicMock()
        self.backend.persist = MagicMock()
        self.backend.verify_short_capture = MagicMock()
        self.backend.collect_short_control = MagicMock()
        native_root = self.root / 'native'
        native_root.mkdir()
        for key, name in (('xp_ledger', 'xp.jsonl'), ('native_save', 'save.jsonl')):
            (native_root / name).write_bytes((self.root / self.fixture.arts[key]['path']).read_bytes())
        session = self.read('session')
        arts = copy.deepcopy(self.fixture.arts)
        arts['baseline'] = arts.pop('baseline_sql')
        self.backend.state = {'attempt_id': 'a' * 32, 'server_instance_id': 'b' * 32,
            'session': {k: v for k, v in session.items() if k != 'save'},
            'intents': [], 'artifacts': arts, 'native_directory': str(native_root),
            'events': [json.loads(line) for line in (self.root / arts['server_log']['path']).read_bytes().splitlines()][:-1],
            'committed_at_ms': 1_302_000, 'invocation_id': 'c' * 32, 'coverage_verified': True,
            'xp_header': {'sha256': hashlib.sha256((native_root / 'xp.jsonl').read_bytes().splitlines(keepends=True)[0]).hexdigest()},
            'window': self.fixture.manifest['window']}
        self.backend.host.snapshot.return_value = self.read('final_db')
        self.backend.host.command.return_value = (self.root / arts['native_log']['path']).read_bytes()

    def read(self, key):
        return json.loads((self.root / self.fixture.arts[key]['path']).read_text())

    def test_original_ledger_save_control_and_coverage_recompute_all_20_windows(self):
        result = self.backend.collect_final()
        self.assertEqual(result['diagnostic_windows']['complete_windows'], 20)
        self.assertEqual(result['diagnostic_windows']['persisted_net_xp'], 4500)
        self.assertTrue(result['native_hook_accepted'])
        self.assertFalse(result['publication_eligible'])
        self.backend.verify_short_capture.assert_called_once()
        self.backend.host.admin.assert_not_called()

    def test_replaced_header_cannot_be_accepted_even_if_chain_is_well_formed(self):
        self.backend.state['xp_header']['sha256'] = '0' * 64
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'native_xp_header_invalid'):
            self.backend.collect_final()
        self.assertNotIn('native_xp_result', self.backend.state['artifacts'])

    def test_failed_native_save_log_cannot_produce_confirmed_session(self):
        self.backend.host.command.return_value += b'Error saving chr\n'
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'save_log_failed'):
            self.backend.collect_final()
        self.assertFalse((self.root / 'session.json').exists())

    def test_incomplete_observation_interval_cannot_collect_a_score(self):
        self.backend.state['coverage_verified'] = False
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, 'full_coverage_required'):
            self.backend.collect_final()
        self.backend.host.snapshot.assert_not_called()


if __name__ == '__main__':
    unittest.main()
