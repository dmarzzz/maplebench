"""Read-only acceptance of separately pinned native XP and visual evidence.

Caller pins are an explicit operator trust boundary. They establish neither
cryptographic visual proof nor permission to run a game or publish a site.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from full_client_score import (EvidenceError, read_json_artifact, same_json,
                               verified_artifact, read_artifact_bytes)
from full_client_native import validate_contract
from full_client_native_xp_acceptance import PROTOCOL as NATIVE, verify_bundle
from full_client_xp_windows import IDENTITY

PROTOCOL = 'native-xp-runtime-acceptance-v1'
NATIVE_REVIEW = 'native-xp-runtime-visual-review-v1'
MODEL_REVIEW = 'native-xp-model-visual-review-v1'
SHA = re.compile(r'[a-f0-9]{64}\Z')
RUN = re.compile(r'[a-f0-9]{32}\Z')
CLASS_JOBS = {'hero': 112, 'bowmaster': 312, 'ice_lightning_arch_mage': 222, 'night_lord': 412}
ARTIFACTS = frozenset(('baseline', 'baseline_snapshot', 'scenario', 'runtime_manifest',
    'initial_db', 'reset', 'native_result', 'native_program', 'controller', 'capture',
    'capture_ready', 'capture_clock', 'capture_terminal', 'recording', 'video',
    'controller_result', 'coverage', 'final_db', 'native_save', 'xp_ledger', 'native_log',
    'server_log', 'session', 'native_xp_manifest', 'native_xp_result', 'video_probe', 'restored_db'))
TOOLKIT_INVENTORY_ARTIFACTS = frozenset(('inventory_before_login', 'inventory_after_logout', 'inventory_after_restore'))


def require(value, code):
    if not value:
        raise EvidenceError('native_xp_gate: ' + code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                   allow_nan=False).encode()).hexdigest()


def reference(value):
    require(isinstance(value, dict) and set(value) == {'path', 'sha256'}
            and isinstance(value['path'], str) and 0 < len(value['path']) <= 512
            and isinstance(value['sha256'], str) and SHA.fullmatch(value['sha256']),
            'pinned_artifact_required')
    return value


def directory(value):
    require(isinstance(value, (str, Path)), 'canonical_artifact_root_required')
    root = Path(value)
    require(root.is_absolute() and root.resolve() == root and not root.is_symlink()
            and root.is_dir(), 'canonical_artifact_root_required')
    return root


def visual_review(root, ref, *, protocol, binding, duration_ms, after_ms, labels):
    """Attested intervals are bound to exact media; no pixels are inferred here."""
    reference(ref)
    review = read_json_artifact(root, {'review': ref}, 'review')
    require(isinstance(review, dict) and set(review) == {
        'schema_version', 'protocol', 'binding', 'reviewed_at_ms', 'observations'}
        and type(review['schema_version']) is int and review['schema_version'] == 1
        and review['protocol'] == protocol and same_json(review['binding'], binding)
        and type(review['reviewed_at_ms']) is int and review['reviewed_at_ms'] >= after_ms,
        'artifact_bound_visual_review_required')
    observations = review['observations']
    require(isinstance(observations, dict) and set(observations) == set(labels),
            'visual_observations_required')
    for interval in observations.values():
        require(isinstance(interval, dict) and set(interval) == {'start_ms', 'end_ms'}
                and all(type(interval[k]) in (int, float) for k in interval)
                and 0 <= interval['start_ms'] < interval['end_ms'] <= duration_ms,
                'visual_interval_outside_original_recording')
    return review


def verify_native(context, *, model_root, model_context, model_projection):
    """Recompute original native evidence, then bind it to this model fixture."""
    fields = {'schema_version', 'protocol', 'root', 'run_id', 'complete', 'backend',
              'runtime_manifest', 'visual_review'}
    require(isinstance(context, dict) and set(context) == fields
            and type(context['schema_version']) is int and context['schema_version'] == 1
            and context['protocol'] == PROTOCOL and isinstance(context['run_id'], str)
            and RUN.fullmatch(context['run_id']), 'explicit_native_acceptance_required')
    root, model_root = directory(context['root']), directory(model_root)
    ident = context['run_id']
    require(root != model_root and root not in model_root.parents and model_root not in root.parents
            and ident != model_context['run_id'], 'separate_native_identity_required')
    for name in ('complete', 'backend', 'runtime_manifest', 'visual_review'):
        reference(context[name])
    complete = read_json_artifact(root, context, 'complete')
    backend = read_json_artifact(root, context, 'backend')
    runtime = read_json_artifact(root, context, 'runtime_manifest')
    complete_fields = {'schema_version', 'protocol', *IDENTITY, 'status', 'api_calls',
        'model', 'publication_eligible', 'clean', 'native_restored', 'failure', 'result', 'artifacts'}
    require(isinstance(complete, dict) and set(complete) == complete_fields
            and type(complete['schema_version']) is int and complete['schema_version'] == 1
            and complete['protocol'] == NATIVE and complete['run_id'] == ident
            and complete['status'] == 'native_xp_collected_awaiting_visual_review'
            and type(complete['api_calls']) is int and complete['api_calls'] == 0
            and complete['model'] is None and complete['publication_eligible'] is False
            and complete['clean'] is True and complete['native_restored'] is True
            and complete['failure'] is None, 'original_successful_native_closeout_required')
    arts = complete['artifacts']
    require(isinstance(arts, dict) and set(arts) in (ARTIFACTS, ARTIFACTS | TOOLKIT_INVENTORY_ARTIFACTS)
            and all(reference(ref) for ref in arts.values()), 'complete_native_artifacts_required')
    require(backend.get('attempt_id') == ident
            and backend.get('server_instance_id') == complete['server_instance_id']
            and backend.get('maintenance_protocol') == NATIVE and backend.get('clean') is True
            and backend.get('native_restored') is True and backend.get('pending') is None
            and backend.get('publication_eligible') is False
            and backend.get('ordinary_logout', {}).get('confirmed') is True
            and same_json(backend.get('artifacts'), arts)
            and isinstance(backend.get('intents'), list)
            and backend['intents'].count('native_control_submit') == 1
            and backend['intents'].count('native_xp_restore_after') == 1,
            'native_backend_not_clean_and_restored')
    require(arts['runtime_manifest'] == context['runtime_manifest']
            and context['runtime_manifest']['sha256'] == model_context['runtime_manifest_sha256']
            and type(runtime.get('schema_version')) is int and runtime['schema_version'] == 2
            and isinstance(runtime.get('server_jar'), dict)
            and set(runtime['server_jar']) == {'path', 'sha256'}
            and SHA.fullmatch(str(runtime['server_jar']['sha256']))
            and runtime['server_jar']['sha256'] == model_projection['provenance']['native_server_jar_sha256']
            and isinstance(runtime.get('extra_files'), list) and 1 <= len(runtime['extra_files']) <= 4096,
            'exact_frozen_runtime_required')
    # The exact manifest binds the candidate JAR and all frozen source files;
    # no remote host paths, running services, or mutable local JAR are consulted.
    for ref in runtime['extra_files']:
        reference(ref)
    manifest = read_json_artifact(root, arts, 'native_xp_manifest')
    checked = verify_bundle(manifest, root)
    require(checked['run_id'] == ident
            and all(complete[k] == manifest[k] for k in IDENTITY)
            and same_json(checked, complete['result'])
            and same_json(checked, read_json_artifact(root, arts, 'native_xp_result'))
            and checked['status'] == 'native_xp_hook_verified'
            and type(checked['positive_transactions']) is int and checked['positive_transactions'] > 0
            and checked['diagnostic_windows']['complete_windows'] == 20
            and checked['diagnostic_windows']['incomplete_tail_ms'] == 0,
            'positive_complete_native_xp_evidence_required')
    required_mapping = {name: arts['baseline' if name == 'baseline_sql' else name]
                        for name in manifest['artifacts']}
    require(same_json(manifest['artifacts'], required_mapping), 'native_manifest_artifacts_changed')
    scenario = read_json_artifact(root, arts, 'scenario')
    native = validate_contract(scenario['native_contract'])
    require(set(arts) == (ARTIFACTS | TOOLKIT_INVENTORY_ARTIFACTS if 'skill_toolkit' in native else ARTIFACTS),
            'exact_toolkit_inventory_artifacts_required')
    baseline = read_json_artifact(root, arts, 'baseline_snapshot')
    restored = read_json_artifact(root, arts, 'restored_db')
    final = read_json_artifact(root, arts, 'final_db')
    require(manifest['baseline_sha256'] == model_context['request']['baseline_sha256']
            and same_json(native['profile'], model_projection['adaptive']['class_profile'])
            and baseline['character'].get('job') == CLASS_JOBS[native['class_id']]
            and same_json(manifest['normalization'], model_projection['normalization'])
            and manifest['experience_table_sha256'] == model_projection['provenance']['experience_table_sha256'],
            'native_model_fixture_mismatch')
    if 'skill_toolkit' in native:
        from full_client_skill_toolkit import validate_toolkit, fingerprint
        toolkit=validate_toolkit(native['skill_toolkit'],native['profile'])
        require(model_projection['provenance'].get('skill_toolkit_sha256')==fingerprint(toolkit),
                'native_model_toolkit_mismatch')
    else:
        require('skill_toolkit_sha256' not in model_projection['provenance'],'native_model_toolkit_mismatch')
    require(restored.get('schema_version') == 1 and type(restored['schema_version']) is int
            and restored.get('source') == 'cosmic_persisted_character' and restored.get('run_id') == ident
            and type(restored.get('account_logged_in')) is int and restored['account_logged_in'] == 0
            and same_json(restored.get('character'), baseline.get('character'))
            and same_json(restored.get('keymap'), baseline.get('keymap'))
            and type(restored.get('captured_at_ms')) is int
            and restored['captured_at_ms'] >= final['captured_at_ms'], 'actual_restored_baseline_required')
    resource_proof = None
    review_after_ms = restored['captured_at_ms']
    if 'skill_toolkit' in native:
        from full_client_native_xp_inventory import verify_triplet
        snapshots = [read_json_artifact(root, arts, 'inventory_' + phase)
                     for phase in ('before_login', 'after_logout', 'after_restore')]
        try:
            resource_proof = verify_triplet(*snapshots, native=native,
                baseline_sql=read_artifact_bytes(root, arts['baseline'], 'baseline', maximum=64 * 1024**2),
                identity={k: manifest[k] for k in IDENTITY}, runtime_manifest_sha256=context['runtime_manifest']['sha256'],
                session=read_json_artifact(root, arts, 'session'), reset=read_json_artifact(root, arts, 'reset'), final_db=final)
        except (ValueError, KeyError, TypeError):
            raise EvidenceError('native_xp_gate: toolkit_resource_proof_invalid') from None
        require(snapshots[-1]['captured_at_ms'] >= restored['captured_at_ms'], 'inventory_restore_timing_changed')
        review_after_ms = snapshots[-1]['captured_at_ms']
    from full_client_publish import _probe_video, verify_capture_bundle
    from full_client_capture import verify_video_duration
    result = read_json_artifact(root, arts, 'native_result')
    recording = read_json_artifact(root, arts, 'recording')
    require(recording.get('status') == 'completed' and recording.get('interrupted') is False
            and recording.get('post_render_capture') is True
            and recording.get('overlay') == {'controller_id': ident, 'mode': 'script', 'model': None}
            and recording.get('sha256') == arts['video']['sha256'], 'native_script_recording_required')
    video = verified_artifact(root, arts['video'], 'video', maximum=96 * 1024**2)
    probe = _probe_video(video, arts['video']['sha256'])
    require(all(
        type(probe.get(k)) in (int, float) and 0 < probe[k] <= native['capture_max_ms']
        for k in ('duration_ms', 'presentation_span_ms', 'presentation_extent_ms')),
        'native_video_75s_bound' if 'skill_toolkit' in native else 'native_video_45s_bound')
    verify_video_duration(probe, recording, native['capture_duration_policy'])
    verify_capture_bundle({'result': result, 'video': recording, 'artifacts': arts}, root)
    binding = {'run_id': ident, 'model': None, 'complete_sha256': context['complete']['sha256'],
        'backend_sha256': context['backend']['sha256'], 'runtime_manifest_sha256': context['runtime_manifest']['sha256'],
        'native_manifest_sha256': arts['native_xp_manifest']['sha256'], 'video_sha256': arts['video']['sha256'],
        'capture_sha256': arts['capture']['sha256'], 'recording_sha256': arts['recording']['sha256'],
        'class_profile_sha256': digest(native['profile'])}
    labels=('vertical_jump', 'monster_contact', 'native_class_hud', 'script_overlay')
    if 'skill_toolkit' in native:
        binding['skill_toolkit_sha256']=fingerprint(toolkit)
        binding['resource_proof_sha256']=digest(resource_proof)
        binding['inventory_artifact_sha256']={name:arts[name]['sha256'] for name in sorted(TOOLKIT_INVENTORY_ARTIFACTS)}
        labels+=tuple('skill_'+skill['slot'] for skill in toolkit['skills'])
        labels+=('potion_resource_effect',)
    visual_review(root, context['visual_review'], protocol=NATIVE_REVIEW, binding=binding,
        duration_ms=probe['duration_ms'], after_ms=review_after_ms,labels=labels)
    for key, original in (('complete', complete), ('backend', backend), ('runtime_manifest', runtime)):
        require(same_json(original, read_json_artifact(root, context, key)), 'native_acceptance_changed')
    proof = {'protocol': PROTOCOL, 'native_run_id': ident, 'native_manifest_sha256': arts['native_xp_manifest']['sha256'],
        'complete_sha256': context['complete']['sha256'], 'backend_sha256': context['backend']['sha256'],
        'runtime_manifest_sha256': context['runtime_manifest']['sha256'],
        'server_jar_sha256': runtime['server_jar']['sha256'], 'source_inventory_sha256': digest(runtime['extra_files']),
        'video_sha256': arts['video']['sha256'], 'visual_review_sha256': context['visual_review']['sha256'],
        'class_id': native['class_id'], 'baseline_sha256': manifest['baseline_sha256'],
        'experience_table_sha256': manifest['experience_table_sha256'], 'normalization': manifest['normalization']}
    if 'skill_toolkit' in native:
        proof['skill_toolkit_sha256']=fingerprint(toolkit)
        proof['resource_proof_sha256']=digest(resource_proof)
    return {'status': 'native_runtime_evidence_rechecked', 'sha256': digest(proof), **proof,
            'trust_boundary': 'explicit_operator_pins_and_artifact_bound_visual_attestation'}


def verify_model_review(root, reference_value, *, context, projection, native):
    provenance = projection['provenance']
    binding = {'run_id': context['run_id'], 'model': context['request']['model'],
        'video_sha256': projection['recording']['sha256'],
        'xp_manifest_sha256': provenance['artifact_sha256']['xp_manifest'],
        'capture_sha256': provenance['artifact_sha256']['capture'],
        'recording_sha256': provenance['artifact_sha256']['recording'],
        'runtime_manifest_sha256': context['runtime_manifest_sha256'],
        'projection_provenance_sha256': digest(provenance), 'native_acceptance_sha256': native['sha256']}
    journal = read_json_artifact(root, context, 'journal')
    arts = journal['receipts']['collect_final']['artifacts']
    recording = read_json_artifact(root, arts, 'recording')
    capture = read_json_artifact(root, arts, 'capture')
    visual_review(root, reference_value, protocol=MODEL_REVIEW, binding=binding,
        duration_ms=projection['recording']['duration_ms'],
        after_ms=capture['end_wall_ms'] + recording['clock_offset_ms']['upper'],
        labels=('exact_model_overlay', 'recording_matches_actions_and_waits', 'native_hud'))
    return {'status': 'artifact_bound_operator_review', 'sha256': reference_value['sha256']}
