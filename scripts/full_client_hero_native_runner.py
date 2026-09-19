#!/usr/bin/env python3
"""Root-owned one-shot launcher for native Hero qualification.

The public entrypoint consumes an enrolled standalone-lifecycle operation,
acquires the existing world and queue locks, and starts exactly one guarded
child.  A failed or uncertain launch leaves the operation pending; this command
does not retry gameplay or cleanup under a new identity.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

import full_client_operation_admission as admission
from full_client_hero_native_evidence import VERIFIER_PROTOCOL
from full_client_hero_native_runtime import HeroNativeRuntime, execute_owned
import full_client_hero_native_runtime as hero_runtime
from full_client_runtime import (CosmicRuntime, Host, RuntimeErrorCode, encoded,
                                 private_directory, save_bytes)
from full_client_trial import existing_lock

SHA = re.compile(r'[a-f0-9]{64}\Z')
RUN = re.compile(r'[a-f0-9]{32}\Z')
TIMEOUT_SECONDS = 600
GUARD_EXIT_GRACE_SECONDS = 10
KIND = 'standalone_lifecycle'


class RunnerError(ValueError):
    pass


def need(value, code):
    if not value:
        raise RunnerError(code)


def reference(path, sha256):
    need(isinstance(sha256, str) and SHA.fullmatch(sha256),
         'hero_native_runner_hash_required')
    path = Path(path)
    need(path.is_absolute() and path.resolve(strict=True) == path,
         'hero_native_runner_path_invalid')
    return {'path': str(path), 'sha256': sha256}


def request_value(value, config_ref, config):
    fields = {'schema_version', 'protocol', 'attempt_id', 'timeout_seconds',
              'config_sha256', 'baseline_sha256', 'runtime_manifest_sha256',
              'scenario_sha256'}
    need(isinstance(value, dict) and set(value) == fields
         and value['schema_version'] == 1
         and type(value['schema_version']) is int
         and value['protocol'] == VERIFIER_PROTOCOL
         and isinstance(value['attempt_id'], str) and RUN.fullmatch(value['attempt_id'])
         and value['timeout_seconds'] == TIMEOUT_SECONDS
         and type(value['timeout_seconds']) is int
         and value['config_sha256'] == config_ref['sha256']
         and value['baseline_sha256'] == config['baseline']['sha256']
         and value['runtime_manifest_sha256'] == config['runtime_manifest']['sha256']
         and value['scenario_sha256'] == config['scenario']['sha256'],
         'hero_native_runner_request_invalid')
    return value


def subject(args, config_ref, request_ref, request):
    return {'type': 'hero_native_qualification',
            'attempt_id': request['attempt_id'], 'config': config_ref,
            'request': request_ref,
            'operation_root': str(admission.gate.canonical(args.operation_root)),
            'world_lock': str(admission.gate.canonical(args.world_lock)),
            'queue_lock': str(admission.gate.canonical(args.queue_lock)),
            'timeout_seconds': TIMEOUT_SECONDS}


def _initial_state(run_id, native_ref):
    return {'schema_version': 1, 'attempt_id': run_id,
            'server_instance_id': os.urandom(16).hex(), 'intents': [],
            'events': [], 'session': {}, 'artifacts': {},
            'maintenance_protocol': VERIFIER_PROTOCOL, 'clean': False,
            'publication_eligible': False,
            'native_input_reference': native_ref}


def guarded(config_ref, request_ref, lock_owner_pid, descriptors):
    need(sys.platform.startswith('linux') and os.geteuid() == 0,
         'hero_native_linux_root_required')
    need(type(lock_owner_pid) is int and lock_owner_pid > 1
         and os.getppid() == lock_owner_pid
         and len(descriptors) == 2 and len(set(descriptors)) == 2
         and all(type(fd) is int and fd >= 3 for fd in descriptors),
         'hero_native_guard_invalid')
    config, actual_config_ref = admission.private_ref(
        Path(config_ref['path']), owner_uid=0)
    need(actual_config_ref == config_ref,
         'hero_native_runner_config_changed')
    raw_request, actual_request_ref = admission.private_ref(
        Path(request_ref['path']), owner_uid=0)
    need(actual_request_ref == request_ref,
         'hero_native_runner_request_changed')
    request = request_value(raw_request, config_ref, config)
    run_id = request['attempt_id']
    root = private_directory(config['attempt_root'])
    directory = root / run_id
    need(not os.path.lexists(directory), 'hero_native_attempt_exists')
    directory.mkdir(mode=0o700)
    native_input = {'schema_version': 1, 'protocol': VERIFIER_PROTOCOL,
        'run_id': run_id, 'attempt_root': str(root),
        'config_sha256': hashlib.sha256(encoded(config)).hexdigest()}
    native_ref = save_bytes(directory / 'native-input.json', encoded(native_input))
    native_ref = {'path': str(directory / native_ref['path']),
                  'sha256': native_ref['sha256']}
    runtime = None

    def maintenance_check():
        need(runtime is not None and runtime.host.remaining() > 0,
             'hero_native_maintenance_expired')
        CosmicRuntime.ownership(runtime)

    host = Host()
    host.deadline = time.monotonic() + TIMEOUT_SECONDS
    runtime = HeroNativeRuntime(config, maintenance_check=maintenance_check,
                                host=host)
    runtime.context = {'schema_version': 1, 'attempt_id': run_id,
        'attempt_dir': str(directory), 'maintenance_protocol': VERIFIER_PROTOCOL,
        'lock_owner_pid': lock_owner_pid, 'guard_pid': os.getpid(),
        'guard_parent_pid': lock_owner_pid,
        'lock_paths': {'world': str(Path(config['world_lock'])),
                       'queue': str(Path(config['queue_lock']))},
        'lock_fds': dict(zip(('world', 'queue'), descriptors)),
        'native_input_reference': native_ref}
    runtime.run_id = run_id
    runtime.directory = directory
    runtime.state = _initial_state(run_id, native_ref)
    runtime.persist()
    receipt = execute_owned(runtime)
    need(receipt.get('status') == 'native_skill_qualification_verified'
         and receipt.get('runtime_lifecycle_verified') is True
         and receipt.get('clean') is True and receipt.get('native_restored') is True,
         'hero_native_qualification_failed')
    complete, complete_ref = admission.private_ref(directory / 'complete.json',
                                                   owner_uid=0)
    need(complete == receipt, 'hero_native_complete_receipt_changed')
    return complete_ref


def launch_guard(script, config_ref, request_ref, lock_fds):
    argv = [sys.executable, str(script), '_adapter_guard',
        config_ref['path'], config_ref['sha256'], request_ref['path'],
        request_ref['sha256'], str(os.getpid()),
        ','.join(str(fd) for fd in lock_fds)]
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=output,
                stderr=subprocess.DEVNULL,
                pass_fds=tuple(lock_fds), start_new_session=True,
                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C',
                     'PYTHONDONTWRITEBYTECODE': '1'})
            returncode = process.wait(timeout=TIMEOUT_SECONDS + GUARD_EXIT_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise RunnerError('hero_native_guard_timeout') from None
    need(returncode == 0, 'hero_native_guard_failed')


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == '_adapter_guard':
        try:
            need(len(argv) == 7, 'hero_native_guard_invalid')
            config_ref = reference(argv[1], argv[2])
            request_ref = reference(argv[3], argv[4])
            need(argv[5].isdigit(), 'hero_native_guard_invalid')
            descriptors = [int(value) for value in argv[6].split(',')]
            guarded(config_ref, request_ref, int(argv[5]), descriptors)
            return 0
        except (OSError, ValueError, KeyError, TypeError, RuntimeErrorCode):
            return 1

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--config-sha256', required=True)
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--request-sha256', required=True)
    parser.add_argument('--operation-root', required=True, type=Path)
    parser.add_argument('--world-lock', required=True, type=Path)
    parser.add_argument('--queue-lock', required=True, type=Path)
    admission.add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        need(sys.platform.startswith('linux') and os.geteuid() == 0,
             'hero_native_linux_root_required')
        config_ref = reference(args.config, args.config_sha256)
        config, actual_config_ref = admission.private_ref(args.config, owner_uid=0)
        need(actual_config_ref == config_ref,
             'hero_native_runner_config_changed')
        request_ref = reference(args.request, args.request_sha256)
        request, actual_request_ref = admission.private_ref(args.request, owner_uid=0)
        need(actual_request_ref == request_ref,
             'hero_native_runner_request_changed')
        request_value(request, config_ref, config)
        need(str(admission.gate.canonical(args.world_lock)) == config['world_lock']
             and str(admission.gate.canonical(args.queue_lock)) == config['queue_lock'],
             'hero_native_runner_lock_mismatch')
        authority_ref, claim_ref = admission.argument_refs(
            args, reconcile=args.operation_claim is not None)
        expected = subject(args, config_ref, request_ref, request)
        script = Path(__file__).resolve()
        with admission.admitted(authority_ref, expected, KIND, args.operation_root,
                claim_ref=claim_ref, owner_uid=0,
                required_sources=(script, Path(hero_runtime.__file__).resolve())) as operation:
            if operation.completed:
                print(json.dumps({'status': 'operation_already_completed',
                                  'attempt_id': request['attempt_id'],
                                  'terminal': operation.terminal}, sort_keys=True))
                return 0
            need(claim_ref is None, 'hero_native_recovery_unsupported')
            with ExitStack() as stack:
                lock_fds = [stack.enter_context(existing_lock(path)) for path in
                            (args.world_lock, args.queue_lock)]
                need(len({(os.fstat(fd).st_dev, os.fstat(fd).st_ino)
                          for fd in lock_fds}) == 2,
                     'hero_native_distinct_locks_required')
                launch_guard(script, config_ref, request_ref, lock_fds)
            complete, complete_ref = admission.private_ref(
                Path(config['attempt_root']) / request['attempt_id'] / 'complete.json',
                owner_uid=0)
            need(complete.get('status') == 'native_skill_qualification_verified'
                 and complete.get('runtime_lifecycle_verified') is True
                 and complete.get('clean') is True,
                 'hero_native_qualification_failed')
            terminal = operation.finish([complete_ref])
        print(json.dumps({'status': 'native_skill_qualification_verified',
                          'attempt_id': request['attempt_id'],
                          'complete': complete_ref, 'terminal': terminal}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError,
            admission.gate.GateError, RuntimeErrorCode):
        print(json.dumps({'status': 'blocked',
                          'code': 'hero_native_runner_failed',
                          'publication_eligible': False}, sort_keys=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
