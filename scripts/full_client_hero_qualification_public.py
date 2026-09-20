"""Project private Hero native qualification evidence into a public receipt.

The projection recomputes native event qualification from the private ledger
and verifies the frozen fixture/runtime/client/server bindings.  It never
copies identities, paths, raw events, controller output, or recordings into
the public result.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re

from full_client_collect import validate_toolkit_snapshot
from full_client_hero_native_evidence import TASK_ID, VERIFIER_PROTOCOL, verify_events
from full_client_hero_native_runtime import qualification_scenario, verify_control_result
from full_client_hero_toolkit import fingerprint as toolkit_fingerprint
from full_client_native import HERO_TOOLKIT_PROTOCOL, fingerprint, validate_contract
from full_client_score import (EvidenceError, open_verified_artifact, parse_json,
                               read_artifact_bytes, same_json)

SHA = re.compile(r'[0-9a-f]{64}\Z')
EXPECTED_PINS = {'baseline_sha256', 'runtime_manifest_sha256',
    'qualification_scenario_sha256', 'server_jar_sha256', 'client_js_sha256',
    'client_wasm_sha256'}
PUBLIC_FIELDS = {'schema_version', 'protocol', 'task_id', 'status',
    'instrumentation_mode', 'qualification_scope', 'native_protocol', 'native_contract_sha256',
    'qualification_scenario_sha256', 'skill_toolkit', 'baseline_sha256',
    'runtime_manifest_sha256', 'server_jar_sha256', 'client_js_sha256',
    'client_wasm_sha256', 'private_receipt_sha256', 'ledger_sha256',
    'recording_evidence', 'available_skills', 'qualified_skills',
    'runtime_lifecycle_verified', 'baseline_restored', 'unsupported', 'limitations'}
TOOLKIT_FIELDS = {'id', 'sha256'}
RECORDING_FIELDS = {'video_sha256', 'probe_sha256', 'decoded_samples_sha256',
                    'decoded_sample_count', 'visual_review_status'}
LIMITATIONS = [
    'This receipt qualifies native effects for the core ten skills; all 17 controls are available, but the other seven effects remain unqualified.',
    'Stun chance, knockback behavior, Power Stance probability, Power Guard ratio, and Rush displacement are not qualified.',
    'Decoded recording samples are private review aids; this projector does not make a human visual-review claim.',
]


class QualificationProjectionError(ValueError):
    """A fixed public-safe failure code for an invalid private bundle."""


def _require(condition, code):
    if not condition:
        raise QualificationProjectionError(code)


def _digest(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _json_bytes(value):
    try:
        return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                           allow_nan=False) + '\n').encode()
    except (TypeError, ValueError, RecursionError):
        raise QualificationProjectionError('invalid_public_qualification') from None


def _read_json(root, reference, label, maximum=64 * 1024 * 1024):
    try:
        return parse_json(read_artifact_bytes(root, reference, label, maximum))
    except (EvidenceError, TypeError, ValueError, KeyError, UnicodeError):
        raise QualificationProjectionError('invalid_private_qualification') from None


def _reference(value):
    return (isinstance(value, dict) and set(value) == {'path', 'sha256'}
            and isinstance(value['path'], str) and _digest(value['sha256']))


def validate_expected_pins(value):
    _require(isinstance(value, dict) and set(value) == EXPECTED_PINS
             and all(_digest(value[name]) for name in EXPECTED_PINS),
             'invalid_qualification_pins')
    return copy.deepcopy(value)


def validate_public_qualification(value, *, native_contract, expected_pins):
    """Validate the exact public, identity-free qualification shape."""
    pins = validate_expected_pins(expected_pins)
    try:
        native = validate_contract(native_contract)
    except (TypeError, ValueError, KeyError):
        raise QualificationProjectionError('invalid_native_contract') from None
    skills = sorted(native['qualification_skill_ids'])
    available = sorted(skill['skill_id'] for skill in native['skill_toolkit']['skills'])
    _require(isinstance(value, dict) and set(value) == PUBLIC_FIELDS
             and value['schema_version'] == 1
             and type(value['schema_version']) is int
             and value['protocol'] == VERIFIER_PROTOCOL
             and value['task_id'] == TASK_ID
             and value['status'] == 'core_toolkit_effects_qualified'
             and value['instrumentation_mode'] == 'qualification_only'
             and value['qualification_scope'] == 'core10'
             and value['native_protocol'] == HERO_TOOLKIT_PROTOCOL
             and value['native_contract_sha256'] == fingerprint(native)
             and value['qualification_scenario_sha256']
                == pins['qualification_scenario_sha256']
             and value['baseline_sha256'] == pins['baseline_sha256']
             and value['runtime_manifest_sha256'] == pins['runtime_manifest_sha256']
             and value['server_jar_sha256'] == pins['server_jar_sha256']
             and value['client_js_sha256'] == pins['client_js_sha256']
             and value['client_wasm_sha256'] == pins['client_wasm_sha256']
             and _digest(value['private_receipt_sha256'])
             and _digest(value['ledger_sha256'])
             and value['available_skills'] == available
             and all(type(item) is int for item in value['available_skills'])
             and value['qualified_skills'] == skills
             and all(type(item) is int for item in value['qualified_skills'])
             and value['runtime_lifecycle_verified'] is True
             and value['baseline_restored'] is True
             and value['unsupported'] == native['skill_toolkit']['unsupported']
             and value['limitations'] == LIMITATIONS,
             'invalid_public_qualification')
    toolkit = value['skill_toolkit']
    _require(isinstance(toolkit, dict) and set(toolkit) == TOOLKIT_FIELDS
             and toolkit['id'] == native['skill_toolkit']['id']
             and toolkit['sha256'] == toolkit_fingerprint(native['skill_toolkit']),
             'invalid_public_qualification')
    recording = value['recording_evidence']
    _require(isinstance(recording, dict) and set(recording) == RECORDING_FIELDS
             and all(_digest(recording[key]) for key in
                     ('video_sha256', 'probe_sha256', 'decoded_samples_sha256'))
             and recording['decoded_sample_count'] == 3
             and type(recording['decoded_sample_count']) is int
             and recording['visual_review_status']
                == 'not_established_by_projector',
             'invalid_public_qualification')
    return copy.deepcopy(value)


def project_qualification(artifact_root: Path, receipt_ref: dict, *,
                          native_contract: dict, expected_pins: dict):
    """Verify a complete private run and return its sanitized public receipt."""
    root = Path(artifact_root)
    pins = validate_expected_pins(expected_pins)
    _require(_reference(receipt_ref), 'invalid_private_receipt_reference')
    try:
        native = validate_contract(native_contract)
    except (TypeError, ValueError, KeyError):
        raise QualificationProjectionError('invalid_native_contract') from None
    _require(native['id'] == HERO_TOOLKIT_PROTOCOL
             and native['baseline_sha256'] == pins['baseline_sha256'],
             'qualification_binding_mismatch')
    receipt = _read_json(root, receipt_ref, 'private_qualification_receipt')
    receipt_fields = {'schema_version', 'protocol', 'run_id', 'server_instance_id',
        'character_id', 'account_id', 'status', 'api_calls', 'model',
        'publication_eligible', 'clean', 'native_restored',
        'runtime_lifecycle_verified', 'failure', 'result', 'artifacts'}
    _require(isinstance(receipt, dict) and set(receipt) == receipt_fields
             and receipt['schema_version'] == 1
             and type(receipt['schema_version']) is int
             and receipt['protocol'] == VERIFIER_PROTOCOL
             and receipt['status'] == 'native_skill_qualification_verified'
             and receipt['api_calls'] == 0 and type(receipt['api_calls']) is int
             and receipt['model'] is None and receipt['publication_eligible'] is False
             and receipt['clean'] is True and receipt['native_restored'] is True
             and receipt['runtime_lifecycle_verified'] is True
             and receipt['failure'] is None
             and isinstance(receipt['result'], dict)
             and isinstance(receipt['artifacts'], dict)
             and all(_reference(ref) for ref in receipt['artifacts'].values()),
             'invalid_private_qualification')
    result, artifacts = receipt['result'], receipt['artifacts']
    result_fields = {'schema_version', 'protocol', 'run_id', 'server_instance_id',
        'character_id', 'account_id', 'api_calls', 'model', 'status',
        'publication_eligible', 'native_contract_sha256', 'baseline_sha256',
        'runtime_manifest_sha256', 'qualification', 'control', 'artifacts'}
    identity = {key: receipt[key] for key in
                ('run_id', 'server_instance_id', 'character_id', 'account_id')}
    _require(set(result) == result_fields
             and all(result[key] == value for key, value in identity.items())
             and result['schema_version'] == 1 and type(result['schema_version']) is int
             and result['protocol'] == VERIFIER_PROTOCOL
             and result['status'] == 'all_core_skills_qualified'
             and result['api_calls'] == 0 and type(result['api_calls']) is int
             and result['model'] is None and result['publication_eligible'] is False
             and result['native_contract_sha256'] == fingerprint(native)
             and result['baseline_sha256'] == pins['baseline_sha256']
             and result['runtime_manifest_sha256'] == pins['runtime_manifest_sha256']
             and isinstance(result['artifacts'], dict)
             and all(artifacts.get(key) == ref
                     for key, ref in result['artifacts'].items()),
             'qualification_binding_mismatch')

    scenario = _read_json(root, artifacts.get('scenario'), 'scenario')
    expected_scenario = qualification_scenario(pins['baseline_sha256'])
    _require(same_json(scenario, expected_scenario)
             and artifacts['scenario']['sha256']
                == pins['qualification_scenario_sha256']
             and same_json(scenario['native_contract'], native),
             'qualification_scenario_mismatch')
    manifest = _read_json(root, artifacts.get('runtime_manifest'), 'runtime_manifest')
    _require(artifacts['runtime_manifest']['sha256']
                == pins['runtime_manifest_sha256']
             and isinstance(manifest, dict) and manifest.get('schema_version') == 2
             and all(isinstance(manifest.get(key), dict)
                     and manifest[key].get('sha256') == pins[key + '_sha256']
                     for key in ('server_jar', 'client_js', 'client_wasm')),
             'runtime_manifest_binding_mismatch')

    baseline = _read_json(root, artifacts.get('baseline_snapshot'),
                          'baseline_snapshot')
    initial = _read_json(root, artifacts.get('initial_db'), 'initial_db')
    restored = _read_json(root, artifacts.get('restored_db'), 'restored_db')
    try:
        for snapshot in (baseline, initial, restored):
            validate_toolkit_snapshot(snapshot, native['skill_toolkit'])
    except (TypeError, ValueError, KeyError):
        raise QualificationProjectionError('qualification_fixture_mismatch') from None
    comparable = ('character', 'keymap', 'skill_toolkit_id', 'learned_skills')
    _require(all(same_json(initial[key], baseline[key])
                 and same_json(restored[key], baseline[key]) for key in comparable),
             'qualification_fixture_mismatch')
    reset = _read_json(root, artifacts.get('reset'), 'reset')
    _require(reset.get('run_id') == identity['run_id']
             and reset.get('baseline_sha256') == pins['baseline_sha256']
             and all(reset.get(key) is True for key in
                     ('world_lock_held', 'queue_lock_held', 'server_stopped', 'verified')),
             'qualification_lifecycle_mismatch')
    session = _read_json(root, artifacts.get('session'), 'session')
    _require(all(session.get(key) == value for key, value in identity.items())
             and session.get('disconnect_kind') == 'normal'
             and session.get('world_lock_held_throughout') is True
             and session.get('queue_lock_held_throughout') is True
             and session.get('save', {}).get('status') == 'confirmed'
             and session.get('save', {}).get('save_error_count') == 0,
             'qualification_lifecycle_mismatch')

    ledger = read_artifact_bytes(root, artifacts.get('skill_ledger'),
                                 'skill_ledger', 16 * 1024 * 1024)
    context = _read_json(root, artifacts.get('skill_context'), 'skill_context')
    _require(all(context.get(key) == value for key, value in identity.items())
             and context.get('runtime_sha256') == pins['runtime_manifest_sha256']
             and context.get('ledger_sha256') == artifacts['skill_ledger']['sha256'],
             'qualification_ledger_binding_mismatch')
    arm = _read_json(root, artifacts.get('skill_arm'), 'skill_arm')
    seal = _read_json(root, artifacts.get('skill_seal'), 'skill_seal')
    status_fields = {'started', 'sealed', 'failure', 'events', 'bytes',
        'sha256_last_line', 'start_monotonic_ns', 'start_wall_ms', 'duration_ns'}
    lines = ledger.splitlines(keepends=True)
    _require(len(lines) >= 2 and ledger.endswith(b'\n')
             and isinstance(arm, dict) and set(arm) == status_fields
             and isinstance(seal, dict) and set(seal) == status_fields
             and arm['started'] is True and arm['sealed'] is False
             and seal['started'] is True and seal['sealed'] is True
             and arm['failure'] == seal['failure'] == ''
             and arm['events'] == 1 and arm['bytes'] == len(lines[0])
             and seal['events'] == len(lines) and seal['bytes'] == len(ledger)
             and arm['sha256_last_line'] == hashlib.sha256(lines[0]).hexdigest()
             and seal['sha256_last_line'] == hashlib.sha256(lines[-1]).hexdigest()
             and all(arm[key] == seal[key] == context[key] for key in
                     ('start_monotonic_ns', 'start_wall_ms', 'duration_ns')),
             'qualification_ledger_binding_mismatch')
    qualification = verify_events(ledger, native, context)
    stored_qualification = _read_json(root, artifacts.get('skill_qualification'),
                                      'skill_qualification')
    skills = sorted(native['qualification_skill_ids'])
    _require(same_json(qualification, stored_qualification)
             and same_json(qualification, result['qualification'])
             and qualification.get('status') == 'success'
             and qualification.get('reason_code')
                == 'all_core_skills_qualified'
             and qualification.get('qualified_skills') == skills
             and qualification.get('publication_eligible') is False
             and qualification.get('runtime_lifecycle_verified') is False,
             'qualification_recomputation_failed')
    native_result = _read_json(root, artifacts.get('native_result'), 'native_result')
    native_program = read_artifact_bytes(root, artifacts.get('native_program'),
                                         'native_program', 65536)
    verified_control = verify_control_result(native_result, native, identity,
                                             native_program)
    _require(same_json(verified_control, result['control']),
             'qualification_control_mismatch')

    recording = _read_json(root, artifacts.get('recording'), 'recording')
    video_ref = artifacts.get('video')
    _require(_reference(video_ref) and recording.get('status') == 'completed'
             and recording.get('sha256') == video_ref['sha256'],
             'qualification_recording_mismatch')
    with open_verified_artifact(root, video_ref, 'video', 512 * 1024 * 1024):
        pass
    probe = _read_json(root, artifacts.get('video_probe'), 'video_probe')
    samples = _read_json(root, artifacts.get('video_samples'), 'video_samples')
    _require(probe.get('video_sha256') == video_ref['sha256']
             and samples == {'schema_version': 1,
                'source_video_sha256': video_ref['sha256'],
                'decoder': 'ffmpeg-single-frame-png-v1',
                'samples': samples.get('samples'),
                'visual_review_status': 'not_established_by_decoder'}
             and isinstance(samples.get('samples'), list)
             and len(samples['samples']) == 3,
             'qualification_recording_mismatch')
    last_offset = -1
    for sample in samples['samples']:
        _require(isinstance(sample, dict)
                 and set(sample) == {'offset_ms', 'path', 'sha256'}
                 and type(sample['offset_ms']) is int
                 and sample['offset_ms'] > last_offset
                 and _reference({'path': sample['path'], 'sha256': sample['sha256']}),
                 'qualification_recording_mismatch')
        raw = read_artifact_bytes(root, {'path': sample['path'],
            'sha256': sample['sha256']}, 'video_sample', 4 * 1024 * 1024)
        _require(raw.startswith(b'\x89PNG\r\n\x1a\n'),
                 'qualification_recording_mismatch')
        last_offset = sample['offset_ms']

    public = {'schema_version': 1, 'protocol': VERIFIER_PROTOCOL,
        'task_id': TASK_ID, 'status': 'core_toolkit_effects_qualified',
        'instrumentation_mode': 'qualification_only',
        'qualification_scope': 'core10',
        'native_protocol': HERO_TOOLKIT_PROTOCOL,
        'native_contract_sha256': fingerprint(native),
        'qualification_scenario_sha256': pins['qualification_scenario_sha256'],
        'skill_toolkit': {'id': native['skill_toolkit']['id'],
            'sha256': toolkit_fingerprint(native['skill_toolkit'])},
        'baseline_sha256': pins['baseline_sha256'],
        'runtime_manifest_sha256': pins['runtime_manifest_sha256'],
        'server_jar_sha256': pins['server_jar_sha256'],
        'client_js_sha256': pins['client_js_sha256'],
        'client_wasm_sha256': pins['client_wasm_sha256'],
        'private_receipt_sha256': receipt_ref['sha256'],
        'ledger_sha256': artifacts['skill_ledger']['sha256'],
        'recording_evidence': {'video_sha256': video_ref['sha256'],
            'probe_sha256': artifacts['video_probe']['sha256'],
            'decoded_samples_sha256': artifacts['video_samples']['sha256'],
            'decoded_sample_count': 3,
            'visual_review_status': 'not_established_by_projector'},
        'available_skills': sorted(skill['skill_id'] for skill in
                                   native['skill_toolkit']['skills']),
        'qualified_skills': skills,
        'runtime_lifecycle_verified': True,
        'baseline_restored': True,
        'unsupported': copy.deepcopy(native['skill_toolkit']['unsupported']),
        'limitations': copy.deepcopy(LIMITATIONS)}
    return validate_public_qualification(public, native_contract=native,
                                         expected_pins=pins)


def public_bytes(value, *, native_contract, expected_pins):
    """Return the canonical bytes written as ``native-qualification.json``."""
    return _json_bytes(validate_public_qualification(value,
        native_contract=native_contract, expected_pins=expected_pins))
