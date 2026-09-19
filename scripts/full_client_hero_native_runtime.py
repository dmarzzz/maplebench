"""Owned zero-API executor for the Hero-180 native skill qualification.

This module is a library for the existing root maintenance wrapper.  It does
not acquire locks, start itself, publish a model result, or retry gameplay.
The wrapper supplies an already-owned fresh state, inherited world/queue lock
descriptions, and a finite host deadline.  Original controller, recording,
database, save-journal, and native skill-ledger bytes remain private.
"""
from __future__ import annotations

import hashlib
import http.client
import importlib
import math
import os
from pathlib import Path
import resource
import secrets
import shutil
import subprocess
import time
import zipfile

from full_client_capture import verify_video_duration
from full_client_hero_native_evidence import (MAX_BYTES as MAX_SKILL_LEDGER,
    TASK_ID, VERIFIER_PROTOCOL, verify_events)
from full_client_hero_toolkit import sdk_scenario
from full_client_native import (HERO_TOOLKIT_PROTOCOL, contract as native_contract,
    fingerprint, program, validate_contract)
from full_client_runtime import (CosmicRuntime, JSON_LIMIT, MAX_SQL,
    RuntimeErrorCode, absolute, encoded, open_verified_artifact, parse_json,
    private_directory, read_artifact_bytes, ref_bytes, require, same_json)

TOTAL_SECONDS = 600
CLEANUP_SECONDS = 180
MIN_EXECUTION_SECONDS = 420
START_SECONDS = 90
LOGIN_SECONDS = 60
CONTROL_RESPONSE_MAX = 4096
VIDEO_SAMPLE_BYTES = 4 * 1024 * 1024
SKILL_CLASSES = (
    'server/bots/MapleBenchSkillLedger.class',
    'server/bots/MapleBenchSkillControlServer.class',
    'server/bots/MapleBenchSkillHooks.class',
)
SKILL_ENV_NAMES = (
    'MAPLEBENCH_SKILL_JOURNAL', 'MAPLEBENCH_SKILL_TASK_ID',
    'MAPLEBENCH_SKILL_BINDING_SHA256', 'MAPLEBENCH_SKILL_RUNTIME_SHA256',
    'MAPLEBENCH_SKILL_DURATION_MS', 'MAPLEBENCH_SKILL_CONTROL_TOKEN',
    'MAPLEBENCH_SKILL_CONTROL_PORT', 'MAPLEBENCH_SKILL_WORLD_ID',
    'MAPLEBENCH_SKILL_CHANNEL_ID',
)
FROZEN_MODULES = (
    'full_client_hero_native_runtime', 'full_client_hero_native_evidence',
    'full_client_hero_toolkit', 'full_client_native', 'full_client_runtime',
    'full_client_collect', 'full_client_freeze', 'full_client_docker',
    'full_client_capture', 'full_client_score', 'full_client_publish',
    'maple_agent',
)
CONTROL_FILES = {
    'native_result': 'result.json', 'native_program': 'program.js',
    'controller': 'controller.json', 'capture': 'capture.json',
    'capture_ready': 'capture-ready.json', 'capture_clock': 'capture-clock.json',
    'capture_terminal': 'capture-terminal.json', 'recording': 'recording.json',
}
FAILURE_CODES = frozenset('''hero_native_protocol_required hero_native_scenario_required
hero_native_fixture_mismatch hero_native_baseline_mismatch hero_native_control_config_invalid
hero_native_sources_not_frozen hero_native_classes_missing hero_native_environment_still_loaded
hero_native_control_unavailable hero_native_control_response_invalid hero_native_control_state_invalid
hero_native_control_transition_failed hero_native_arm_deadline hero_native_seal_deadline
hero_native_controller_failed hero_native_controller_identity_mismatch hero_native_program_mismatch
hero_native_sdk_receipt_invalid hero_native_capture_invalid hero_native_ledger_invalid
hero_native_log_invalid hero_native_restore_unconfirmed hero_native_preflight_unconfirmed
hero_native_cleanup_unconfirmed hero_native_operation_failed'''.split())


def decode_recording_samples(video_path, video_sha256, duration_ms, output_directory,
                             *, timeout_seconds=30):
    """Decode three private PNGs so recording review is based on real frames."""
    require(isinstance(video_path, Path) and video_path.is_absolute()
            and isinstance(output_directory, Path) and output_directory.is_absolute()
            and output_directory.resolve() == output_directory
            and isinstance(video_sha256, str) and len(video_sha256) == 64
            and all(c in '0123456789abcdef' for c in video_sha256)
            and type(duration_ms) in (int, float) and math.isfinite(duration_ms)
            and 1000 <= duration_ms <= 125000
            and _integer(timeout_seconds, 1, 60),
            'hero_native_capture_invalid')
    ffmpeg = shutil.which('ffmpeg', path='/usr/sbin:/usr/bin:/sbin:/bin')
    require(ffmpeg is not None, 'hero_native_capture_invalid')
    offsets = sorted({max(0, min(duration_ms - 100,
        int(duration_ms * fraction))) for fraction in (.1, .5, .9)})
    require(len(offsets) == 3, 'hero_native_capture_invalid')

    def limits():
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        resource.setrlimit(resource.RLIMIT_FSIZE,
                           (VIDEO_SAMPLE_BYTES, VIDEO_SAMPLE_BYTES))

    samples = []
    for index, offset in enumerate(offsets, 1):
        path = output_directory / ('video-sample-%d.png' % index)
        require(not path.exists() and not path.is_symlink(),
                'hero_native_capture_invalid')
        try:
            result = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-n',
                '-ss', '%.3f' % (offset / 1000), '-i', str(video_path),
                '-map', '0:v:0', '-frames:v', '1', '-threads', '1',
                '-f', 'image2', str(path)], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=timeout_seconds, check=False, preexec_fn=limits,
                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeErrorCode('hero_native_capture_invalid') from None
        require(result.returncode == 0 and path.is_file() and not path.is_symlink(),
                'hero_native_capture_invalid')
        raw = path.read_bytes()
        require(8 < len(raw) <= VIDEO_SAMPLE_BYTES
                and raw.startswith(b'\x89PNG\r\n\x1a\n'),
                'hero_native_capture_invalid')
        samples.append({'offset_ms': offset, 'path': path.name,
                        'sha256': hashlib.sha256(raw).hexdigest()})
    return {'schema_version': 1, 'source_video_sha256': video_sha256,
            'decoder': 'ffmpeg-single-frame-png-v1', 'samples': samples,
            'visual_review_status': 'not_established_by_decoder'}


def qualification_scenario(baseline_sha256):
    """Return the exact small JSON object the operator freezes as `scenario`."""
    return {'schema_version': 1, 'protocol': VERIFIER_PROTOCOL,
            'native_contract': native_contract('hero', baseline_sha256,
                                               protocol=HERO_TOOLKIT_PROTOCOL)}


def _integer(value, low=0, high=2**53 - 1):
    return type(value) is int and low <= value <= high


def _status(value):
    fields = {'started', 'sealed', 'failure', 'events', 'bytes',
              'sha256_last_line', 'start_monotonic_ns', 'start_wall_ms',
              'duration_ns'}
    require(isinstance(value, dict) and set(value) == fields
            and type(value['started']) is bool and type(value['sealed']) is bool
            and isinstance(value['failure'], str) and len(value['failure']) <= 128
            and _integer(value['events'], 0, 100000)
            and _integer(value['bytes'], 0, MAX_SKILL_LEDGER)
            and isinstance(value['sha256_last_line'], str)
            and len(value['sha256_last_line']) == 64
            and all(c in '0123456789abcdef' for c in value['sha256_last_line'])
            and _integer(value['start_monotonic_ns'], 0, 2**63 - 1)
            and _integer(value['start_wall_ms'], 0)
            and value['duration_ns'] == 120000000000,
            'hero_native_control_state_invalid')
    require(not value['sealed'] or value['started'],
            'hero_native_control_state_invalid')
    if not value['started']:
        require(not value['sealed'] and value['events'] == value['bytes'] == 0
                and value['start_monotonic_ns'] == value['start_wall_ms'] == 0
                and value['sha256_last_line'] == '0' * 64,
                'hero_native_control_state_invalid')
    else:
        require(value['events'] >= 1 and value['bytes'] > 0
                and value['start_monotonic_ns'] > 0 and value['start_wall_ms'] > 0,
                'hero_native_control_state_invalid')
    return value


def _observation(value):
    require(isinstance(value, dict) and value.get('ready') is True
            and isinstance(value.get('character'), dict)
            and all(type(value.get(key)) in (int, float)
                    and math.isfinite(value[key]) and 0 <= value[key] < 1500
                    for key in ('ageMs', 'renderAgeMs')),
            'hero_native_sdk_receipt_invalid')


def verify_control_result(actual, native, identity, program_raw):
    """Recheck the finite no-model controller result and its original SDK steps."""
    from maple_agent import validate_rpc

    native = validate_contract(native)
    expected = program(native).encode()
    require(program_raw == expected and isinstance(actual, dict)
            and actual.get('protocol') == HERO_TOOLKIT_PROTOCOL
            and same_json(actual.get('nativeAcceptance'), native)
            and actual.get('source') == 'client telemetry; unscored integration run'
            and actual.get('api') is None and actual.get('trialContext') is None
            and actual.get('model_api_requests') == 0
            and type(actual.get('model_api_requests')) is int
            and actual.get('publication_eligible') is False
            and actual.get('score') is None
            and actual.get('programSha256') == hashlib.sha256(expected).hexdigest(),
            'hero_native_program_mismatch')
    owner, execution = actual.get('controller', {}), actual.get('program', {})
    timing, timeline = actual.get('timing', {}), actual.get('timeline', {})
    require(owner.get('id') == identity['run_id'] and owner.get('mode') == 'script'
            and owner.get('model') is None and owner.get('returnedModel') is None
            and owner.get('protocol') == HERO_TOOLKIT_PROTOCOL
            and same_json(owner.get('nativeAcceptance'), native),
            'hero_native_controller_identity_mismatch')
    require(owner.get('status') == 'completed'
            and owner.get('reason') == 'program_complete'
            and owner.get('workerActive') is False
            and execution.get('reason') == 'program_complete'
            and execution.get('error') is None
            and timeline.get('status') == 'completed',
            'hero_native_controller_failed')
    steps = execution.get('steps')
    require(isinstance(steps, list) and 1 <= len(steps) <= native['max_sdk_requests'],
            'hero_native_sdk_receipt_invalid')
    rpc_ids, actions = [], 0
    scenario = {'adapter': 'full-client'} | sdk_scenario(native)
    for step in steps:
        require(isinstance(step, dict) and step.get('kind') == 'sdk'
                and step.get('method') in ('observe', 'pressKeys', 'wait'),
                'hero_native_sdk_receipt_invalid')
        try:
            method, argument = validate_rpc({'type': 'rpc', 'id': step.get('rpcId'),
                'method': step['method'], 'args': step.get('args')}, scenario)
        except (ValueError, TypeError, KeyError):
            raise RuntimeErrorCode('hero_native_sdk_receipt_invalid') from None
        rpc_ids.append(step['rpcId'])
        receipt = step.get('result')
        require(isinstance(receipt, dict) and receipt.get('error') in (None, ''),
                'hero_native_sdk_receipt_invalid')
        if method == 'pressKeys':
            require(receipt.get('accepted') is True,
                    'hero_native_sdk_receipt_invalid')
            _observation(receipt.get('observation'))
            actions += 1
        elif method == 'observe':
            _observation(receipt)
        else:
            require(type(receipt.get('waitedMs')) is int
                    and receipt['waitedMs'] == argument,
                    'hero_native_sdk_receipt_invalid')
    require(rpc_ids == sorted(rpc_ids) and len(set(rpc_ids)) == len(rpc_ids)
            and 1 <= actions <= native['max_actions']
            and execution.get('actions') == owner.get('actions') == actions
            and type(execution.get('actions')) is int
            and execution.get('actionAttempts') == actions
            and execution.get('rpcRequests') == len(steps)
            and all(_integer(timing.get(key)) for key in
                    ('startedAtMs', 'endedAtMs', 'elapsedMs', 'apiLatencyMs'))
            and timing['apiLatencyMs'] == 0
            and abs(timing['endedAtMs'] - timing['startedAtMs']
                    - timing['elapsedMs']) <= 25
            and _integer(timeline.get('program_started_ms'))
            and _integer(timeline.get('program_ended_ms'))
            and 0 < timeline['program_ended_ms'] - timeline['program_started_ms']
                    <= native['wall_seconds'] * 1000,
            'hero_native_sdk_receipt_invalid')
    return {'actions': actions, 'sdk_requests': len(steps),
            'program_started_at_ms': timing['startedAtMs'] + timeline['program_started_ms'],
            'program_ended_at_ms': timing['startedAtMs'] + timeline['program_ended_ms'],
            'program_sha256': hashlib.sha256(expected).hexdigest()}


class HeroNativeRuntime(CosmicRuntime):
    """One fresh native skill window under an already-owned maintenance lock."""

    def __init__(self, config, *, maintenance_check, host=None,
                 token_factory=lambda: secrets.token_hex(32)):
        require(callable(maintenance_check) and callable(token_factory),
                'hero_native_control_config_invalid')
        super().__init__(config, host)
        self.maintenance_check = maintenance_check
        self.token_factory = token_factory

    def ownership(self):
        self.maintenance_check()

    def admin(self, op, **values):
        self.ownership()
        require(op in ('status', 'connect', 'disconnect', 'prepare_wait', 'cancel',
                       'release_failed_run', 'start_native'),
                'hero_native_controller_identity_mismatch')
        if op == 'start_native':
            return self.host.admin(self.config['admin_socket'], {'op': op, **values},
                                   lock_fds=self.lock_fds())
        return super().admin(op, **values)

    def perform(self, *args, **kwargs):
        raise RuntimeErrorCode('hero_native_operator_wrapper_required')

    def write_publication_candidate(self, *args, **kwargs):
        raise RuntimeErrorCode('hero_native_publication_forbidden')

    def xp_window_contract(self):
        require(self.config.get('xp_window_protocol') is None,
                'hero_native_protocol_required')
        return None

    def trial_protocol(self):
        return VERIFIER_PROTOCOL

    def service_runtime_seconds(self):
        return 300

    def _control_config(self):
        value = self.config.get('hero_skill_control')
        require(isinstance(value, dict)
                and set(value) == {'port', 'world_id', 'channel_id'}
                and _integer(value['port'], 1024, 65535)
                and _integer(value['world_id'], 0, 255)
                and _integer(value['channel_id'], 1, 255),
                'hero_native_control_config_invalid')
        return value

    def load_pins(self):
        require(self.config.get('hero_native_protocol') == VERIFIER_PROTOCOL,
                'hero_native_protocol_required')
        self.scenario = parse_json(ref_bytes(self.config['scenario']))
        require(isinstance(self.scenario, dict)
                and set(self.scenario) == {'schema_version', 'protocol', 'native_contract'}
                and self.scenario['schema_version'] == 1
                and type(self.scenario['schema_version']) is int
                and self.scenario['protocol'] == VERIFIER_PROTOCOL,
                'hero_native_scenario_required')
        try:
            self.native = validate_contract(self.scenario['native_contract'])
        except (ValueError, TypeError, KeyError):
            raise RuntimeErrorCode('hero_native_scenario_required') from None
        require(self.native['id'] == HERO_TOOLKIT_PROTOCOL
                and self.native['baseline_sha256'] == self.config['baseline']['sha256'],
                'hero_native_fixture_mismatch')
        self.baseline = parse_json(ref_bytes(self.config['baseline_snapshot']))
        try:
            from full_client_collect import validate_toolkit_snapshot
            validate_toolkit_snapshot(self.baseline, self.native['skill_toolkit'])
        except (ValueError, TypeError, KeyError):
            raise RuntimeErrorCode('hero_native_baseline_mismatch') from None
        db = self.config['mysql']
        require(self.baseline.get('account_logged_in') == 0
                and all(self.baseline.get('character', {}).get(key) == db[key]
                        for key in ('character_id', 'account_id'))
                and self.baseline['character'].get('job') == 112
                and self.baseline['character'].get('level') == 180
                and self.baseline['character'].get('map_id') == 240040511,
                'hero_native_baseline_mismatch')
        self.manifest = parse_json(ref_bytes(self.config['runtime_manifest']))
        self.docker_binding()
        self._control_config()
        refs = {ref['path']: ref for ref in self.manifest.get('extra_files', [])}
        for name in FROZEN_MODULES:
            path = str(Path(importlib.import_module(name).__file__).resolve())
            require(path in refs, 'hero_native_sources_not_frozen')
            ref_bytes(refs[path])

    def snapshot(self):
        value = self.host.snapshot(self.config['mysql'], self.run_id,
                                   skill_toolkit=self.native['skill_toolkit'])
        try:
            from full_client_collect import validate_toolkit_snapshot
            validate_toolkit_snapshot(value, self.native['skill_toolkit'])
        except (ValueError, TypeError, KeyError):
            raise RuntimeErrorCode('hero_native_baseline_mismatch') from None
        return value

    def web_identity(self, unit, *, verify_bytes=True):
        super().web_identity(unit, verify_bytes=verify_bytes)
        extras = {ref['path']: ref for ref in self.manifest.get('extra_files', [])}
        paths = [Path(importlib.import_module(name).__file__).resolve()
                 for name in ('full_client_hero_native_runtime',
                              'full_client_hero_native_evidence')]
        require(all(extras.get(str(path), {}).get('sha256') for path in paths),
                'hero_native_sources_not_frozen')
        if verify_bytes:
            for path in paths:
                ref_bytes(extras[str(path)])
        started = self.host.process_started_ms(int(unit.get('MainPID', '0')))
        require(all(max(path.stat().st_mtime_ns, path.stat().st_ctime_ns) / 1_000_000
                    <= started for path in paths),
                'hero_native_sources_not_frozen')

    def frozen(self):
        super().frozen()
        jar = self.manifest['server_jar']
        path = absolute(jar['path'])
        with open_verified_artifact(path.parent,
                {'path': path.name, 'sha256': jar['sha256']}, 'server_jar',
                maximum=512 * 1024 * 1024) as stream:
            with zipfile.ZipFile(stream) as archive:
                names = set(archive.namelist())
        require(set(SKILL_CLASSES) <= names, 'hero_native_classes_missing')

    def native_xp_environment(self, native_directory):
        require(isinstance(self.state.get('skill_control_token'), str)
                and len(self.state['skill_control_token']) == 64
                and all(c in '0123456789abcdef'
                        for c in self.state['skill_control_token']),
                'hero_native_control_config_invalid')
        control = self._control_config()
        values = (str(native_directory / 'skill.jsonl'), TASK_ID,
                  fingerprint(self.native), self.config['runtime_manifest']['sha256'],
                  '120000', self.state['skill_control_token'], str(control['port']),
                  str(control['world_id']), str(control['channel_id']))
        return dict(zip(SKILL_ENV_NAMES, values))

    def trial_configuration_absent(self, unit):
        if not super().trial_configuration_absent(unit):
            return False
        try:
            environment = __import__('shlex').split(unit.get('Environment', ''))
        except ValueError:
            return False
        return not any(item.split('=', 1)[0] in SKILL_ENV_NAMES for item in environment)

    def start_server(self):
        before = self.unit('cosmic')
        require(not any(name in before.get('Environment', '')
                        for name in SKILL_ENV_NAMES),
                'hero_native_environment_still_loaded')
        return super().start_server()

    def _control_request(self, method, suffix):
        self.ownership()
        self.owned_server()
        control = self._control_config()
        connection = http.client.HTTPConnection('127.0.0.1', control['port'],
            timeout=min(5, self.host.remaining()))
        headers = {'Authorization': 'Bearer ' + self.state['skill_control_token'],
                   'X-MapleBench-Run': self.run_id}
        try:
            connection.request(method, '/v1/skill-ledger/' + suffix,
                               body=b'' if method == 'POST' else None,
                               headers=headers)
            response = connection.getresponse()
            raw = response.read(CONTROL_RESPONSE_MAX + 1)
            status = response.status
        except (OSError, TimeoutError, http.client.HTTPException):
            raise RuntimeErrorCode('hero_native_control_unavailable') from None
        finally:
            connection.close()
        require(status == 200 and 0 < len(raw) <= CONTROL_RESPONSE_MAX,
                'hero_native_control_transition_failed')
        try:
            return _status(parse_json(raw))
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise RuntimeErrorCode('hero_native_control_response_invalid') from None

    def skill_status(self):
        return self._control_request('GET', 'status')

    def server_ready(self):
        if not super().server_ready():
            return False
        try:
            value = self.skill_status()
        except RuntimeErrorCode as error:
            if str(error) == 'hero_native_control_unavailable':
                return False
            raise
        require(not value['started'] and not value['sealed']
                and value['failure'] == '',
                'hero_native_control_state_invalid')
        return True

    def _transition(self, operation):
        require(operation in ('arm', 'seal'),
                'hero_native_control_transition_failed')
        key = 'skill_' + operation
        require(key not in self.state['intents'], 'operation_already_attempted')
        self.intent(key)
        try:
            value = self._control_request('POST', operation)
        except RuntimeErrorCode as error:
            # A lost POST reply is reconciled once through the read-only status
            # endpoint.  The transition itself is never reissued.
            if str(error) not in ('hero_native_control_unavailable',
                                  'hero_native_control_transition_failed'):
                raise
            value = self.skill_status()
        if operation == 'arm':
            require(value['started'] and not value['sealed']
                    and value['failure'] == '' and value['events'] == 1,
                    'hero_native_control_transition_failed')
            require(abs(self.host.now() - value['start_wall_ms']) <= 5000,
                    'hero_native_arm_deadline')
        else:
            require(value['started'] and value['sealed']
                    and value['failure'] == '' and value['events'] >= 2,
                    'hero_native_control_transition_failed')
            require(self.host.now() - value['start_wall_ms'] <= 125000,
                    'hero_native_seal_deadline')
        self.state[key + '_status'] = value
        self.state['artifacts'][key] = self.artifact(
            'skill-' + operation + '.json', value)
        self.persist()
        return value

    def safe_boundary(self):
        self.ownership()
        self.quiet()
        unit = self.unit('cosmic')
        if not self.stopped(unit):
            self.owned_server()
        else:
            require(self.account_state() == 0,
                    'hero_native_baseline_mismatch')

    def login(self):
        deadline = self.host.deadline
        self.host.deadline = min(deadline, time.monotonic() + LOGIN_SECONDS)
        try:
            return super().login()
        finally:
            self.host.deadline = deadline

    def native_window(self):
        self.owned_server()
        require(self.state['session'].get('login_at_ms')
                and self.account_state() == 2,
                'ordinary_login_required')
        arm = self._transition('arm')
        self.state['session']['skill_window_started_at_ms'] = arm['start_wall_ms']
        self.intent('native_control_submit')
        request = {'op': 'start_native', 'run_id': self.run_id,
            'request_id': self.run_id, 'native_acceptance': self.native,
            'docker_image_id': self.manifest['docker_image_id'],
            'docker_binding': self.docker_binding(),
            'lock_paths': self.context['lock_paths']}
        self.state['artifacts']['native_request'] = self.artifact(
            'native-request.json', request)
        self.persist()
        try:
            self.host.admin(self.config['admin_socket'], request,
                            lock_fds=self.lock_fds())
        except Exception:
            # start_native is a create-once request.  A lost response may be
            # reconciled from status, but it is never submitted twice.
            observed = self.admin('status')
            run = observed.get('bridge', {}).get('run') or {}
            require(run.get('id') == self.run_id,
                    'hero_native_controller_identity_mismatch')
        sealed = False
        terminal_seen = None
        while True:
            self.ownership()
            self.quiet()
            self.owned_server()
            observed = self.admin('status')
            run = observed.get('bridge', {}).get('run') or {}
            require(run.get('id') == self.run_id
                    and run.get('protocol') == HERO_TOOLKIT_PROTOCOL
                    and same_json(run.get('nativeAcceptance'), self.native),
                    'hero_native_controller_identity_mismatch')
            if run.get('status') in ('failed', 'timed_out', 'cancelled'):
                if not sealed:
                    self._transition('seal')
                raise RuntimeErrorCode('hero_native_controller_failed')
            if run.get('status') == 'completed' and not sealed:
                self._transition('seal')
                sealed = True
                terminal_seen = self.host.now()
            complete = (sealed and run.get('status') == 'completed'
                and run.get('workerActive') is False
                and run.get('evidenceStatus') == 'saved'
                and run.get('recordingStatus') == 'saved'
                and observed.get('session', {}).get('artifactsSettled') is True)
            if complete:
                self.state['upload_status'] = {'schema_version': 1,
                    'source': 'full_client_hero_native_runtime_status',
                    **self.identity(), 'observed_at_ms': self.host.now(),
                    'status': observed}
                self.state['session']['controller_terminal_seen_at_ms'] = terminal_seen
                self.state['session']['upload_observed_at_ms'] = \
                    self.state['upload_status']['observed_at_ms']
                self.persist()
                break
            self.host.sleep()
        self.request_ordinary_disconnect()
        self.collect_controller_metadata()
        return {'status': 'completed', 'api_calls': 0, 'model': None,
                'skill_window': self.state['skill_seal_status']}

    def collect_controller_metadata(self):
        require(self.account_state() == 0 and self.state.get('ordinary_logout'),
                'normal_committed_logout_required')
        source = absolute(self.config['relay_output_root']) / self.run_id
        require(source.resolve() == source and source.is_dir(),
                'run_artifacts_missing')
        arts = self.state['artifacts']
        for key, filename in CONTROL_FILES.items():
            arts[key] = self.artifact('control-' + filename,
                raw=self.read_stable(source / filename, JSON_LIMIT))
        actual = parse_json(read_artifact_bytes(self.directory,
            arts['native_result'], 'native_result'))
        raw = read_artifact_bytes(self.directory, arts['native_program'],
                                  'native_program', maximum=65536)
        checked = verify_control_result(actual, self.native, self.identity(), raw)
        self.state['result'] = actual
        self.state['control_verified'] = checked
        self.state['session'].update(controller_started_at_ms=checked['program_started_at_ms'],
            controller_ended_at_ms=checked['program_ended_at_ms'])
        self.persist()

    def collect_final(self):
        self.owned_server()
        require(self.account_state() == 0 and self.state.get('ordinary_logout')
                and self.state.get('control_verified')
                and self.state.get('skill_seal_status', {}).get('sealed') is True,
                'normal_committed_logout_required')
        self.intent('collect_final')
        self.disconnect()
        arts = self.state['artifacts']
        final = self.snapshot()
        self.event('collection_completed', final['captured_at_ms'])
        arts['final_db'] = self.artifact('final-db.json', final)
        ledger = self.read_stable(Path(self.state['native_directory']) / 'skill.jsonl',
                                  MAX_SKILL_LEDGER)
        lines = ledger.splitlines(keepends=True)
        arm, seal = self.state['skill_arm_status'], self.state['skill_seal_status']
        require(ledger.endswith(b'\n') and len(ledger) == seal['bytes']
                and len(lines) == seal['events']
                and hashlib.sha256(lines[0]).hexdigest() == arm['sha256_last_line']
                and hashlib.sha256(lines[-1]).hexdigest() == seal['sha256_last_line'],
                'hero_native_ledger_invalid')
        arts['skill_ledger'] = self.artifact('native-skill.jsonl', raw=ledger)
        expected = {**self.identity(),
            'runtime_sha256': self.config['runtime_manifest']['sha256'],
            'ledger_sha256': hashlib.sha256(ledger).hexdigest(),
            'start_monotonic_ns': self.state['skill_arm_status']['start_monotonic_ns'],
            'start_wall_ms': self.state['skill_arm_status']['start_wall_ms'],
            'duration_ns': 120000000000}
        arts['skill_context'] = self.artifact('skill-context.json', expected)
        try:
            qualification = verify_events(ledger, self.native, expected)
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise RuntimeErrorCode('hero_native_ledger_invalid') from None
        required = sorted(self.native['qualification_skill_ids'])
        require(qualification.get('status') == 'success'
                and qualification.get('reason_code') == 'all_core_skills_qualified'
                and qualification.get('qualified_skills') == required
                and qualification.get('publication_eligible') is False
                and qualification.get('runtime_lifecycle_verified') is False,
                'hero_native_ledger_invalid')
        arts['skill_qualification'] = self.artifact(
            'hero-skill-qualification.json', qualification)
        arts['native_save'] = self.artifact('native-save.jsonl', raw=self.read_stable(
            Path(self.state['native_directory']) / 'save.jsonl', JSON_LIMIT))
        logs = self.host.command([self.config['journalctl'], '--no-pager', '--output=cat',
            '_SYSTEMD_INVOCATION_ID=' + self.state['invocation_id']])
        arts['native_log'] = self.artifact('native-log.txt', raw=logs)
        require(logs.count(b'MapleBench persistence journal initialized') == 1
                and all(marker not in logs for marker in
                    (b'MapleBench persistence journal failed',
                     b'MapleBench XP ledger failed', b'Error saving chr')),
                'hero_native_log_invalid')
        arts['server_log'] = self.artifact('lifecycle.jsonl',
            raw=b''.join(encoded(row) for row in self.state['events']))
        session = {**self.state['session'], **self.identity(),
            'disconnect_kind': 'normal', 'world_lock_held_throughout': True,
            'queue_lock_held_throughout': True,
            'save': {'status': 'confirmed', **self.identity(),
                'committed_at_ms': self.state['committed_at_ms'],
                'evidence_sha256': arts['native_save']['sha256'],
                'logs_sha256': arts['server_log']['sha256'],
                'native_logs_sha256': arts['native_log']['sha256'],
                'save_error_count': 0,
                'log_checked_from_ms': self.state['session']['server_started_at_ms'],
                'log_checked_through_ms': final['captured_at_ms']}}
        arts['session'] = self.artifact('session.json', session)
        self.collect_recording()
        result = {'schema_version': 1, 'protocol': VERIFIER_PROTOCOL,
            **self.identity(), 'api_calls': 0, 'model': None,
            'status': 'all_core_skills_qualified',
            'publication_eligible': False,
            'native_contract_sha256': fingerprint(self.native),
            'baseline_sha256': self.config['baseline']['sha256'],
            'runtime_manifest_sha256': self.config['runtime_manifest']['sha256'],
            'qualification': qualification,
            'control': self.state['control_verified'],
            'artifacts': {key: arts[key] for key in
                ('skill_ledger', 'skill_qualification', 'native_result',
                 'native_program', 'recording', 'video', 'video_probe',
                 'video_samples',
                 'skill_arm', 'skill_seal', 'skill_context',
                 'initial_db', 'final_db', 'native_save', 'native_log',
                 'server_log', 'session', 'scenario', 'baseline_snapshot',
                 'baseline', 'runtime_manifest', 'reset')}}
        arts['hero_native_result'] = self.artifact(
            'hero-native-qualification.json', result)
        self.persist()
        return result

    def collect_recording(self):
        from full_client_publish import _probe_video, verify_capture_bundle

        arts = self.state['artifacts']
        recording = parse_json(read_artifact_bytes(self.directory,
            arts['recording'], 'recording'))
        require(recording.get('status') == 'completed'
                and recording.get('overlay') == {'controller_id': self.run_id,
                    'mode': 'script', 'model': None}
                and recording.get('capture_sha256') == arts['capture']['sha256'],
                'hero_native_capture_invalid')
        source = absolute(self.config['relay_output_root']) / self.run_id
        with open_verified_artifact(source,
                {'path': 'video.webm', 'sha256': recording.get('sha256')},
                'video', maximum=512 * 1024 * 1024) as stream:
            destination = self.directory / 'video.webm'
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as output:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
        arts['video'] = {'path': 'video.webm', 'sha256': recording['sha256']}
        try:
            probe = _probe_video(self.directory / 'video.webm', recording['sha256'],
                                 maximum_ms=self.native['capture_max_ms']) \
                    | {'video_sha256': recording['sha256']}
            verify_video_duration(probe, recording,
                                  self.native['capture_duration_policy'])
            arts['video_probe'] = self.artifact('video-probe.json', probe)
            samples = decode_recording_samples(self.directory / 'video.webm',
                recording['sha256'], probe['duration_ms'], self.directory,
                timeout_seconds=min(30, max(1, int(self.host.remaining()))))
            arts['video_samples'] = self.artifact('video-samples.json', samples)
            verify_capture_bundle({'result': self.state['result'],
                'video': recording, 'artifacts': arts}, self.directory)
        except (ValueError, TypeError, KeyError, OSError):
            raise RuntimeErrorCode('hero_native_capture_invalid') from None

    def validate_fresh_owner(self):
        require(set(self.state) == {'schema_version', 'attempt_id',
                'server_instance_id', 'intents', 'events', 'session', 'artifacts',
                'maintenance_protocol', 'clean', 'publication_eligible',
                'native_input_reference'}
                and self.state['schema_version'] == 1
                and type(self.state['schema_version']) is int
                and self.state['maintenance_protocol'] == VERIFIER_PROTOCOL
                and self.state['publication_eligible'] is False
                and self.state['clean'] is False
                and self.context.get('maintenance_protocol') == VERIFIER_PROTOCOL
                and self.context.get('attempt_id') == self.run_id,
                'hero_native_fresh_owned_state_required')
        root = private_directory(self.config['attempt_root'])
        require(private_directory(self.directory) == root / self.run_id
                and self.context.get('attempt_dir') == str(self.directory),
                'hero_native_fresh_owned_state_required')
        reference = self.context.get('native_input_reference')
        require(isinstance(reference, dict)
                and same_json(self.state.get('native_input_reference'), reference),
                'hero_native_input_reference_required')
        frozen = parse_json(ref_bytes(reference))
        require(same_json(frozen, {'schema_version': 1,
                'protocol': VERIFIER_PROTOCOL, 'run_id': self.run_id,
                'attempt_root': str(root),
                'config_sha256': hashlib.sha256(encoded(self.config)).hexdigest()}),
                'hero_native_input_binding_mismatch')

    def restore_after(self):
        self.state['native_restored'] = False
        self.persist()
        self.safe_boundary()
        require(self.stopped(self.unit('cosmic')) and self.account_state() == 0
                and 'restore_baseline' in self.state['intents'],
                'hero_native_preflight_unconfirmed')
        if self.state.get('reset', {}).get('verified') is True \
                and 'hero_native_restore_after' not in self.state['intents']:
            self.intent('hero_native_restore_after')
            self.sql(ref_bytes(self.config['baseline'], MAX_SQL))
        restored = self.snapshot()
        require(restored.get('account_logged_in') == 0
                and same_json(restored['character'], self.baseline['character'])
                and same_json(restored['keymap'], self.baseline['keymap'])
                and restored.get('skill_toolkit_id') == self.baseline.get('skill_toolkit_id')
                and same_json(restored.get('learned_skills'),
                              self.baseline.get('learned_skills')),
                'hero_native_restore_unconfirmed')
        self.state['artifacts']['restored_db'] = self.artifact(
            'restored-db.json', restored)
        self.prepare_cleanup_wait()
        self.state['native_restored'] = True
        self.persist()


def execute_owned(runtime):
    """Execute one fresh qualification and always close/restore owned state."""
    runtime.ownership()
    runtime.validate_fresh_owner()
    require(runtime.state['intents'] == [] and runtime.state['events'] == []
            and runtime.state['session'] == {} and runtime.state['artifacts'] == {},
            'hero_native_fresh_owned_state_required')
    require(runtime.host.remaining() >= MIN_EXECUTION_SECONDS,
            'hero_native_execution_time_insufficient')
    token = runtime.token_factory()
    require(isinstance(token, str) and len(token) == 64
            and all(c in '0123456789abcdef' for c in token),
            'hero_native_control_config_invalid')
    runtime.state['skill_control_token'] = token
    runtime.persist()
    overall = min(runtime.host.deadline, time.monotonic() + TOTAL_SECONDS)
    result, failure, phase = None, None, 'preflight'
    runtime.intent('hero_native_execution')
    try:
        runtime.host.deadline = overall - CLEANUP_SECONDS
        runtime.safe_boundary()
        runtime.frozen()
        require(runtime.host.remaining() >= START_SECONDS + LOGIN_SECONDS + 150,
                'hero_native_preflight_time_insufficient')
        for phase in ('restore_baseline', 'start_server', 'login',
                      'native_window', 'collect_final'):
            runtime.safe_boundary()
            value = getattr(runtime, phase)()
            if phase == 'collect_final':
                result = value
    except Exception as error:
        failure = {'phase': phase, 'error_type': type(error).__name__,
            'status': 'failed_preserved',
            'reason': str(error) if isinstance(error, RuntimeErrorCode)
                and str(error) in FAILURE_CODES else 'hero_native_operation_failed',
            'api_calls': 0, 'model': None}
        runtime.state['artifacts']['failure'] = runtime.artifact(
            'failure.json', failure)
        runtime.persist()
    finally:
        runtime.host.deadline = overall
    require('restore_baseline' in runtime.state['intents'],
            'hero_native_preflight_unconfirmed')
    runtime.safe_boundary()
    runtime.cleanup()
    runtime.state['clean'] = False
    runtime.persist()
    runtime.restore_after()
    runtime.safe_boundary()
    require(runtime.state.get('native_restored') is True
            and runtime.stopped(runtime.unit('cosmic'))
            and runtime.account_state() == 0,
            'hero_native_cleanup_unconfirmed')
    runtime.state['clean'] = True
    runtime.persist()
    receipt = {'schema_version': 1, 'protocol': VERIFIER_PROTOCOL,
        **runtime.identity(),
        'status': 'failed_native_skill_qualification_closed' if failure
            else 'native_skill_qualification_verified',
        'api_calls': 0, 'model': None, 'publication_eligible': False,
        'clean': True, 'native_restored': True,
        'runtime_lifecycle_verified': failure is None, 'failure': failure,
        'result': result, 'artifacts': dict(runtime.state['artifacts'])}
    runtime.artifact('complete.json', receipt)
    return receipt
