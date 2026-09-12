"""Owned zero-API native XP executor library; deliberately no dispatch CLI.

The operator wrapper must verify and hold the existing admission/world/queue/
runner locks and supply its maintenance checker. This library never grants that
authority, activates a JAR, creates an API claim, or resumes native control.
"""
import hashlib
import importlib
import os
import stat
from pathlib import Path
import time

import full_client_native as native
import full_client_native_xp_acceptance as acceptance
import full_client_xp_windows as windows
from full_client_runtime import (CosmicRuntime, RuntimeErrorCode, require, ref_bytes,
    parse_json, encoded, JSON_LIMIT, MAX_SQL, read_artifact_bytes, same_json,
    RUN, private_directory, read_private_json, RUNTIME_ERROR_CODES)

TOTAL_SECONDS = 900
CLEANUP_SECONDS = 180
LOGIN_SECONDS = 60
START_SECONDS = 90
MIN_EXECUTION_SECONDS = 720
WINDOW_COLLECTION_SECONDS = 345
CONTROL_FILES = {'native_result': 'result.json', 'native_program': 'program.js',
    'controller': 'controller.json', 'capture': 'capture.json', 'capture_ready': 'capture-ready.json',
    'capture_clock': 'capture-clock.json', 'capture_terminal': 'capture-terminal.json',
    'recording': 'recording.json'}
CLASS_JOBS = {'hero': 112, 'bowmaster': 312, 'ice_lightning_arch_mage': 222, 'night_lord': 412}
FROZEN_MODULES = ('full_client_native_xp_runtime', 'full_client_native_xp_acceptance',
    'full_client_xp_windows', 'full_client_native', 'full_client_skill_toolkit', 'full_client_runtime', 'full_client_publish',
    'full_client_capture', 'full_client_score', 'full_client_collect', 'full_client_freeze',
    'full_client_docker', 'full_client_readiness', 'full_client_trial')
FAILURE_CODES = frozenset('''native_xp_baseline_mismatch native_xp_candidate_manifest_required
native_xp_executor_sources_not_frozen native_xp_account_not_online native_xp_renderer_or_scene_not_fresh
native_xp_fresh_scene_required native_xp_control_failed_or_identity_changed native_xp_control_exceeded_recipe
native_xp_short_capture_not_saved native_xp_api_evidence_forbidden native_xp_video_changed
native_xp_terminal_evidence_changed native_xp_deferred_collection_requires_offline_coverage
native_xp_window_time_insufficient native_xp_execution_time_insufficient native_xp_preflight_time_insufficient
native_xp_header_invalid native_xp_save_log_failed native_xp_short_video_bound
native_xp_restore_unconfirmed native_xp_initial_restore_not_started native_xp_cleanup_unconfirmed
native_xp_inventory_receipt_failed native_xp_inventory_baseline_mismatch native_xp_inventory_receipt_changed'''.split())


def stopped_capture(status):
    run = status.get('bridge', {}).get('run') or {}
    session = status.get('session', {})
    return (run.get('status') == 'completed' and run.get('workerActive') is False
            and run.get('recordingStatus') == run.get('evidenceStatus') == 'saved'
            and run.get('leaseReleasePending') is not True
            and status.get('bridge', {}).get('browserReleasePending') is not True
            and session.get('captureState') == 'idle' and session.get('artifactsSettled') is True)


def normalized_control(result, identity):
    """Derive the verifier's compact control from original receipts, not claims."""
    timing, timeline, execution = result['timing'], result['timeline'], result['program']
    return {'schema_version': 1, 'protocol': acceptance.PROTOCOL, 'run_id': identity['run_id'],
            'model': None, 'api_calls': 0,
            'started_at_ms': timing['startedAtMs'] + timeline['program_started_ms'],
            'ended_at_ms': timing['startedAtMs'] + timeline['program_ended_ms'],
            'accepted_actions': execution['actions'], 'sdk_requests': execution['rpcRequests'],
            'program_sha256': result['programSha256']}


class NativeXpRuntime(CosmicRuntime):
    def __init__(self, config, *, maintenance_check, host=None, monotonic_ns=time.monotonic_ns,
                 sleep=time.sleep):
        require(callable(maintenance_check), 'native_xp_maintenance_checker_required')
        super().__init__(config, host)
        self.maintenance_check = maintenance_check
        self.monotonic_ns, self.coverage_sleep = monotonic_ns, sleep

    def ownership(self):
        self.maintenance_check()

    def admin(self, op, **values):
        self.ownership()
        require(op in ('status', 'connect', 'disconnect', 'prepare_wait', 'cancel',
                       'release_failed_run'), 'native_xp_model_control_forbidden')
        return super().admin(op, **values)

    def perform(self, *args, **kwargs):
        raise RuntimeErrorCode('native_xp_operator_wrapper_required')

    def run_controller(self):
        raise RuntimeErrorCode('native_xp_model_control_forbidden')

    def write_publication_candidate(self, *args, **kwargs):
        raise RuntimeErrorCode('native_xp_publication_forbidden')

    def load_pins(self):
        require(self.config.get('native_xp_protocol') == acceptance.PROTOCOL,
                'native_xp_explicit_protocol_required')
        self.scenario = parse_json(ref_bytes(self.config['scenario']))
        require(set(self.scenario) == {'protocol', 'native_contract', 'xp_window_protocol'}
                and self.scenario['protocol'] == acceptance.PROTOCOL, 'native_xp_scenario_required')
        self.native = native.validate_contract(self.scenario['native_contract'])
        self.baseline = parse_json(ref_bytes(self.config['baseline_snapshot']))
        self.manifest = parse_json(ref_bytes(self.config['runtime_manifest']))
        require(self.native['baseline_sha256'] == self.config['baseline']['sha256']
                and self.baseline.get('account_logged_in') == 0
                and self.baseline['character']['level'] == self.native['profile']['level']
                and self.baseline['character'].get('job') == CLASS_JOBS[self.native['class_id']]
                and all(self.baseline['character'][k] == self.config['mysql'][k]
                        for k in ('character_id', 'account_id')), 'native_xp_baseline_mismatch')
        candidate = self.config.get('native_xp_candidate_jar')
        require(isinstance(candidate, dict) and set(candidate) == {'path', 'sha256'}
                and all(candidate[k] == self.manifest['server_jar'][k] for k in candidate),
                'native_xp_candidate_manifest_required')
        refs = {ref['path']: ref for ref in self.manifest.get('extra_files', [])}
        for name in FROZEN_MODULES + (('full_client_native_xp_inventory',
                'full_client_toolkit_fixture') if 'skill_toolkit' in self.native else ()):
            path = str(Path(importlib.import_module(name).__file__).resolve())
            require(path in refs, 'native_xp_executor_sources_not_frozen')
            ref_bytes(refs[path])
        self.docker_binding()
        self.xp_window_contract()

    def capture_toolkit_inventory(self, phase):
        if 'skill_toolkit' not in self.native:
            return None
        from full_client_native_xp_inventory import collect_owned, expected, verify_restored
        try:
            value = collect_owned(self, phase)
            baseline_sql = ref_bytes(self.config['baseline'], MAX_SQL)
            if phase == 'before_login':
                wanted = expected(self.native, baseline_sql,
                    character_id=self.config['mysql']['character_id'], account_id=self.config['mysql']['account_id'])
                require(same_json(value['use_inventory'], wanted), 'native_xp_inventory_baseline_mismatch')
            if phase == 'after_restore':
                verify_restored(value, native=self.native, baseline_sql=baseline_sql, identity=self.identity(),
                    runtime_manifest_sha256=self.config['runtime_manifest']['sha256'])
        except RuntimeErrorCode:
            raise
        except (ValueError, TypeError, KeyError):
            raise RuntimeErrorCode('native_xp_inventory_receipt_failed') from None
        key = 'inventory_' + phase
        if key in self.state['artifacts']:
            original = parse_json(read_artifact_bytes(self.directory, self.state['artifacts'][key], key))
            # Reinspection never rewrites an original receipt. A repeated
            # cleanup may only reconfirm the same exact offline inventory.
            fields = lambda row: {k: v for k, v in row.items() if k != 'captured_at_ms'}
            require(same_json(fields(original), fields(value)), 'native_xp_inventory_receipt_changed')
        else:
            self.state['artifacts'][key] = self.artifact(key.replace('_', '-') + '.json', value)
            self.persist()
        return value

    def restore_baseline(self):
        result = super().restore_baseline()
        self.capture_toolkit_inventory('before_login')
        return result

    def xp_window_contract(self):
        require(self.config.get('native_xp_protocol') == acceptance.PROTOCOL
                and self.config.get('xp_window_protocol') == windows.PROTOCOL
                and self.scenario.get('protocol') == acceptance.PROTOCOL,
                'native_xp_explicit_protocol_required')
        contract=windows.validate_contract(self.scenario['xp_window_protocol'])
        require(contract['wall_seconds']==300,'native_xp_explicit_protocol_required')
        return contract

    def service_runtime_seconds(self):
        return TOTAL_SECONDS - 60

    def validate_fresh_owner(self):
        """The outer checker still proves actual held locks and prior clean operations."""
        require(set(self.state) == {'schema_version', 'attempt_id', 'server_instance_id', 'intents',
                'events', 'session', 'artifacts', 'maintenance_protocol', 'clean',
                'publication_eligible', 'native_input_reference'}
                and type(self.state['schema_version']) is int and self.state['schema_version'] == 1
                and self.state['publication_eligible'] is False
                and RUN.fullmatch(self.run_id) is not None
                and RUN.fullmatch(self.state.get('server_instance_id', '')) is not None
                and self.state.get('attempt_id') == self.run_id
                and self.context.get('attempt_id') == self.run_id
                and self.context.get('maintenance_protocol') == acceptance.PROTOCOL
                and 'request' not in self.context, 'native_xp_owner_mismatch')
        root = private_directory(self.config['attempt_root'])
        api_root = private_directory(self.config['api_attempt_root'])
        require(root != api_root and root not in api_root.parents and api_root not in root.parents
                and private_directory(self.directory) == root / self.run_id
                and self.context.get('attempt_dir') == str(self.directory),
                'native_xp_separate_namespace_required')
        require({p.name for p in self.directory.iterdir()} == {'backend-state.json'}
                and same_json(read_private_json(self.directory / 'backend-state.json'), self.state)
                and all(not (Path(self.config[key]) / self.run_id).exists()
                        and not (Path(self.config[key]) / self.run_id).is_symlink()
                        for key in ('relay_output_root', 'native_output_root')),
                'native_xp_existing_attempt_refused')
        reference = self.context.get('native_input_reference')
        require(isinstance(reference, dict) and self.state.get('native_input_reference') == reference,
                'native_xp_input_reference_required')
        frozen = parse_json(ref_bytes(reference))
        require(same_json(frozen, {'schema_version': 1, 'protocol': acceptance.PROTOCOL,
                'run_id': self.run_id, 'attempt_root': str(root), 'api_attempt_root': str(api_root),
                'config_sha256': hashlib.sha256(encoded(self.config)).hexdigest()}),
                'native_xp_input_binding_mismatch')

    def start_server(self):
        end = self.host.deadline
        self.host.deadline = min(end, time.monotonic() + START_SECONDS)
        try:
            return super().start_server()
        finally:
            self.host.deadline = end

    def safe_boundary(self):
        self.ownership()
        self.quiet()
        unit = self.unit('cosmic')
        if not self.stopped(unit):
            self.owned_server()
        else:
            require(self.account_state() == 0, 'native_xp_stopped_account_online')

    def login(self):
        end = self.host.deadline
        self.host.deadline = min(end, time.monotonic() + LOGIN_SECONDS)
        try:
            return super().login()
        finally:
            self.host.deadline = end

    def sample(self, sequence, *, before_submission=False):
        self.safe_boundary()
        self.owned_server()
        self.online_identity()
        require(self.account_state() == 2, 'native_xp_account_not_online')
        status = self.admin('status')
        bridge, session = status.get('bridge', {}), status.get('session', {})
        scene = status.get('observation') or {}
        require(bridge.get('fresh') is True and session.get('state') == 'connected'
                and session.get('fresh') is True and session.get('pinned') is True
                and scene.get('character', {}).get('mapId') == self.baseline['character']['map_id'],
                'native_xp_renderer_or_scene_not_fresh')
        run = bridge.get('run') or {}
        if before_submission:
            require(sequence == 0 and run.get('status', 'idle') in ('idle', 'completed', 'failed')
                    and run.get('workerActive') is not True and session.get('captureState') == 'idle'
                    and session.get('artifactsSettled') is True and scene.get('monsters'),
                    'native_xp_fresh_scene_required')
            idle = True
        else:
            require(run.get('id') == self.run_id and run.get('mode') == 'script'
                    and run.get('model') is None and run.get('protocol') == self.native['id']
                    and run.get('status') in ('requesting', 'running', 'completed'),
                    'native_xp_control_failed_or_identity_changed')
            idle = run.get('status') == 'completed' and run.get('workerActive') is False
        row = {'sequence': sequence, 'wall_ms': self.host.now(), 'monotonic_ns': self.monotonic_ns(),
               **self.identity(), 'server_owned': True, 'account_online': True,
               'renderer_fresh': True, 'controller_idle': idle}
        if not before_submission:
            elapsed = row['wall_ms'] - self.state['window']['start_at_ms']
            control_limit = acceptance.MAX_CONTROL_START_DELAY_MS + self.native['wall_seconds'] * 1000
            require(elapsed < control_limit or idle, 'native_xp_control_exceeded_recipe')
            if stopped_capture(status) and 'short_control_terminal' not in self.state:
                require(elapsed <= self.native['capture_max_ms'], 'native_xp_short_capture_not_saved')
                self.state['short_control_terminal'] = self.control_file_stamps()
                self.persist()
            if 'short_control_terminal' in self.state:
                require(stopped_capture(status), 'native_xp_short_capture_not_saved')
                require(self.control_file_stamps() == self.state['short_control_terminal'],
                        'native_xp_terminal_evidence_changed')
            require(elapsed < self.native['capture_max_ms'] or 'short_control_terminal' in self.state,
                    'native_xp_short_capture_not_saved')
        return row

    def native_window(self):
        """One native submission; all remaining callbacks read status only."""
        require('native_control_submit' not in self.state['intents'], 'native_xp_control_already_submitted')
        require(self.host.remaining() >= WINDOW_COLLECTION_SECONDS, 'native_xp_window_time_insufficient')
        first = self.sample(0, before_submission=True)
        self.state['window'] = {'start_at_ms': first['wall_ms'],
                                'deadline_at_ms': first['wall_ms'] + 300000, 'window_ms': 15000}
        self.state['session'].update(controller_started_at_ms=first['wall_ms'],
                                      controller_ended_at_ms=first['wall_ms'] + 300000)
        self.state['artifacts']['window_origin'] = self.artifact('window-origin.json', first)
        request = {'op': 'start_native', 'run_id': self.run_id, 'request_id': self.run_id,
                   'native_acceptance': self.native, 'docker_image_id': self.manifest['docker_image_id'],
                   'docker_binding': self.docker_binding(), 'lock_paths': self.context['lock_paths']}
        self.state['artifacts']['native_request'] = self.artifact('native-request.json', request)
        self.intent('native_control_submit')
        self.ownership()
        # The intent survives an uncertain reply. No retry path can call this again.
        self.host.admin(self.config['admin_socket'], request, lock_fds=self.lock_fds())
        path = self.directory / 'coverage.jsonl'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            sequence = [0]
            def observe():
                sequence[0] += 1
                return self.sample(sequence[0])
            def append(raw):
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            acceptance.collect_passive_coverage(first, observe, append,
                monotonic_ns=self.monotonic_ns, sleep=self.coverage_sleep)
        raw = self.read_stable(path, 256 * 1024)
        acceptance.verify_coverage(raw, self.identity(), self.state['window'], native_contract=self.native)
        self.state['artifacts']['coverage'] = {'path': path.name, 'sha256': hashlib.sha256(raw).hexdigest()}
        self.state['coverage_verified'] = True
        self.persist()

    def control_file_stamps(self):
        """Bounded metadata-only terminal latch; never read video during coverage."""
        self.ownership()
        source = Path(self.config['relay_output_root']) / self.run_id
        require(source.resolve(strict=True) == source and source.is_dir(),
                'native_xp_terminal_evidence_changed')
        require(not any(os.path.lexists(source / name) for name in
                        ('api-request.json', 'api-response.json', 'adaptive.json', 'cycles')),
                'native_xp_api_evidence_forbidden')
        directory_info = source.lstat()
        stamps = {'directory': [directory_info.st_dev, directory_info.st_ino,
            directory_info.st_mode, directory_info.st_uid, directory_info.st_gid]}
        for name in (*CONTROL_FILES.values(), 'video.webm'):
            info = (source / name).lstat()
            maximum = 96 * 1024 * 1024 if name == 'video.webm' else JSON_LIMIT
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and 0 < info.st_size <= maximum, 'native_xp_terminal_evidence_changed')
            stamps[name] = [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                           info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
        return stamps

    def collect_short_control(self):
        """Transfer and hash original artifacts only after coverage and logout."""
        self.ownership()
        require(self.state.get('coverage_verified') is True and self.account_state() == 0,
                'native_xp_deferred_collection_requires_offline_coverage')
        self.disconnect()  # Read-only verification of the durable ordinary logout receipt.
        terminal = self.state.get('short_control_terminal')
        require(terminal is not None and self.control_file_stamps() == terminal,
                'native_xp_terminal_evidence_changed')
        self.intent('collect_native_control')
        source = Path(self.config['relay_output_root']) / self.run_id
        arts = self.state['artifacts']
        names = CONTROL_FILES
        for key, name in names.items():
            arts[key] = self.artifact('control-' + name, raw=self.read_stable(source / name, JSON_LIMIT))
        result = parse_json(read_artifact_bytes(self.directory, arts['native_result'], 'native_result'))
        program = read_artifact_bytes(self.directory, arts['native_program'], 'native_program')
        normalized = normalized_control(result, self.identity())
        acceptance.verify_control(normalized, self.scenario, self.identity(), self.state['window'],
                                  self.config['baseline']['sha256'], result, program)
        arts['controller_result'] = self.artifact('native-control-result.json', normalized)
        recording = parse_json(read_artifact_bytes(self.directory, arts['recording'], 'recording'))
        raw = self.read_stable(source / 'video.webm', 96 * 1024 * 1024)
        require(hashlib.sha256(raw).hexdigest() == recording['sha256'], 'native_xp_video_changed')
        arts['video'] = self.artifact('native-control.webm', raw=raw)
        require(self.control_file_stamps() == terminal, 'native_xp_terminal_evidence_changed')
        self.persist()

    def collect_final(self):
        self.safe_boundary()
        require(self.state.get('coverage_verified') is True, 'native_xp_full_coverage_required')
        self.disconnect()
        self.collect_short_control()
        self.intent('collect_native_xp')
        arts = self.state['artifacts']
        self.capture_toolkit_inventory('after_logout')
        final = self.host.snapshot(self.config['mysql'], self.run_id)
        self.event('collection_completed', final['captured_at_ms'])
        arts['final_db'] = self.artifact('final-db.json', final)
        for key, filename, maximum in (('native_save', 'save.jsonl', JSON_LIMIT),
                                       ('xp_ledger', 'xp.jsonl', windows.MAX_LEDGER_BYTES)):
            arts[key] = self.artifact('native-' + filename, raw=self.read_stable(
                Path(self.state['native_directory']) / filename, maximum))
        ledger = read_artifact_bytes(self.directory, arts['xp_ledger'], 'xp_ledger',
                                     maximum=windows.MAX_LEDGER_BYTES)
        require(ledger and self.state.get('xp_header', {}).get('sha256') ==
                hashlib.sha256(ledger.splitlines(keepends=True)[0]).hexdigest(),
                'native_xp_header_invalid')
        logs = self.host.command([self.config['journalctl'], '--no-pager', '--output=cat',
                                  '_SYSTEMD_INVOCATION_ID=' + self.state['invocation_id']])
        arts['native_log'] = self.artifact('native-log.txt', raw=logs)
        require(all(marker not in logs for marker in (b'MapleBench XP ledger failed',
                b'MapleBench persistence journal failed', b'Error saving chr')),
                'native_xp_save_log_failed')
        arts['server_log'] = self.artifact('lifecycle.jsonl', raw=b''.join(encoded(row) for row in self.state['events']))
        session = {**self.state['session'], **self.identity(), 'disconnect_kind': 'normal',
                   'world_lock_held_throughout': True, 'queue_lock_held_throughout': True,
                   'save': {'status': 'confirmed', **self.identity(), 'committed_at_ms': self.state['committed_at_ms'],
                       'evidence_sha256': arts['native_save']['sha256'], 'logs_sha256': arts['server_log']['sha256'],
                       'native_logs_sha256': arts['native_log']['sha256'], 'save_error_count': 0,
                       'log_checked_from_ms': self.state['session']['server_started_at_ms'],
                       'log_checked_through_ms': final['captured_at_ms']}}
        arts['session'] = self.artifact('session.json', session)
        contract = self.xp_window_contract()
        names = ('xp_ledger', 'native_save', 'native_log', 'initial_db', 'final_db', 'session', 'scenario',
                 'controller_result', 'baseline_snapshot', 'reset', 'server_log', 'coverage', 'native_result', 'native_program')
        refs = {key: arts[key] for key in names}
        refs['baseline_sql'] = arts['baseline']
        manifest = {'schema_version': 1, 'protocol': acceptance.PROTOCOL, **self.identity(),
                    'window': self.state['window'], 'normalization': contract['normalization'],
                    'experience_table_sha256': contract['experience_table_sha256'], 'artifacts': refs,
                    'baseline_sha256': self.config['baseline']['sha256'],
                    'scenario_fingerprint': self.config['scenario']['sha256']}
        arts['native_xp_manifest'] = self.artifact('native-xp-manifest.json', manifest)
        result = acceptance.verify_bundle(manifest, self.directory)
        self.verify_short_capture()
        arts['native_xp_result'] = self.artifact('native-xp-acceptance.json', result)
        self.persist()
        return result

    def verify_short_capture(self):
        from full_client_publish import _probe_video, verify_capture_bundle
        from full_client_capture import verify_video_duration
        arts = self.state['artifacts']
        recording = parse_json(read_artifact_bytes(self.directory, arts['recording'], 'recording'))
        result = parse_json(read_artifact_bytes(self.directory, arts['native_result'], 'native_result'))
        probe = _probe_video(self.directory / arts['video']['path'], recording['sha256'])
        native.validate_contract(self.native)
        require(all(
                    type(probe.get(key)) in (int, float) and 0 < probe[key] <= self.native['capture_max_ms']
                    for key in ('duration_ms', 'presentation_span_ms', 'presentation_extent_ms')),
                'native_xp_short_video_bound')
        arts['video_probe'] = self.artifact('video-probe.json', probe)
        verify_video_duration(probe, recording, self.native['capture_duration_policy'])
        verify_capture_bundle({'result': result, 'video': recording, 'artifacts': arts}, self.directory)

    def restore_after(self):
        self.state['native_restored'] = False
        self.persist()
        self.safe_boundary()
        require(self.stopped(self.unit('cosmic')) and self.account_state() == 0,
                'native_xp_restore_requires_stopped_offline')
        require('restore_baseline' in self.state['intents'], 'native_xp_initial_restore_not_started')
        if self.state.get('reset', {}).get('verified') is True and 'native_xp_restore_after' not in self.state['intents']:
            self.intent('native_xp_restore_after')
            self.sql(ref_bytes(self.config['baseline'], MAX_SQL))
        # An uncertain initial restore (no reset proof), or a lost final SQL
        # reply, permits inspection only. Neither justifies another SQL write.
        restored = self.host.snapshot(self.config['mysql'], self.run_id)
        require(restored.get('account_logged_in') == 0
                and same_json(restored['character'], self.baseline['character'])
                and same_json(restored['keymap'], self.baseline['keymap']), 'native_xp_restore_unconfirmed')
        if 'restored_db' not in self.state['artifacts']:
            self.state['artifacts']['restored_db'] = self.artifact('restored-db.json', restored)
        self.capture_toolkit_inventory('after_restore')
        self.prepare_cleanup_wait()
        self.state['native_restored'] = True
        self.persist()


def execute_owned(runtime):
    """Run a fresh, outer-wrapper-owned state once; no automatic recovery entry."""
    runtime.ownership()
    runtime.validate_fresh_owner()
    require(runtime.state.get('maintenance_protocol') == acceptance.PROTOCOL
            and runtime.state.get('intents') == [] and runtime.state.get('clean') is False
            and runtime.state.get('events') == [] and runtime.state.get('session') == {}
            and runtime.state.get('artifacts') == {}, 'native_xp_fresh_owned_state_required')
    require(runtime.host.remaining() >= MIN_EXECUTION_SECONDS, 'native_xp_execution_time_insufficient')
    overall = min(runtime.host.deadline, time.monotonic() + TOTAL_SECONDS)
    result, failure, phase = None, None, 'preflight'
    runtime.intent('native_xp_execution')
    try:
        runtime.host.deadline = overall - CLEANUP_SECONDS
        runtime.safe_boundary()
        runtime.frozen()
        require(runtime.host.remaining() >= START_SECONDS + LOGIN_SECONDS + WINDOW_COLLECTION_SECONDS,
                'native_xp_preflight_time_insufficient')
        for phase in ('restore_baseline', 'start_server', 'login', 'native_window',
                      'request_ordinary_disconnect', 'collect_final'):
            runtime.safe_boundary()
            value = getattr(runtime, phase)()
            if phase == 'collect_final':result = value
    except Exception as error:
        failure = {'phase': phase, 'error_type': type(error).__name__, 'status': 'failed_preserved',
                   'reason': str(error) if isinstance(error, RuntimeErrorCode)
                       and str(error) in FAILURE_CODES | RUNTIME_ERROR_CODES else 'native_xp_operation_failed',
                   'api_calls': 0, 'model': None}
        runtime.state['artifacts']['failure'] = runtime.artifact('failure.json', failure)
        runtime.persist()
    finally:
        runtime.host.deadline = overall
    # Failed inventory/authority cannot authorize any cleanup mutation. The
    # separate immutable failure remains for explicit operator reconciliation.
    require('restore_baseline' in runtime.state['intents'], 'native_xp_preflight_unconfirmed')
    runtime.safe_boundary()
    runtime.cleanup()
    runtime.state['clean'] = False
    runtime.persist()
    runtime.restore_after()
    runtime.safe_boundary()
    require(runtime.state.get('native_restored') is True and runtime.stopped(runtime.unit('cosmic'))
            and runtime.account_state() == 0, 'native_xp_cleanup_unconfirmed')
    runtime.state['clean'] = True
    runtime.persist()
    receipt = {'schema_version': 1, 'protocol': acceptance.PROTOCOL, **runtime.identity(),
               'status': 'failed_native_xp_closed' if failure else 'native_xp_collected_awaiting_visual_review',
               'api_calls': 0, 'model': None, 'publication_eligible': False, 'clean': True,
               'native_restored': True, 'failure': failure, 'result': result,
               'artifacts': dict(runtime.state['artifacts'])}
    runtime.artifact('complete.json', receipt)
    return receipt
