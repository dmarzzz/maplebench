"""Read-only, unranked projection of explicitly pinned native XP-window trials.

This adapter never upgrades a pilot net-XP score, authorizes deployment, or copies
private evidence. Optional acceptance requires original separately pinned native
evidence and an artifact-bound operator visual review. All public values are
rebuilt from the native ledger, ordinary save, adaptive cycles and original
capture; absent or inconsistent evidence stays unknown.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from full_client_adaptive import PROTOCOL as ADAPTIVE, FULL_HORIZON_POLICY
from full_client_adaptive_evidence import verify_result
from full_client_adaptive_publication import public_cycles, playback_cue
from full_client_score import (EvidenceError, read_artifact_bytes,
                               read_json_artifact, same_json, verified_artifact)
from full_client_trial import STATUS_FIELDS, validate_spec
import full_client_xp_windows as windows
import full_client_capture as capture_contract

PROTOCOL = 'full-client-native-xp-publication-v1'
VERIFIED = 'native_window_runner_receipts_rechecked'
MAX_VIDEO = 96 * 1024**2
BLOCKER = 'new_native_runtime_and_baseline_acceptance_required'
SHA = re.compile(r'[a-f0-9]{64}\Z')
RUN = re.compile(r'[a-f0-9]{32}\Z')


def require(value, code):
    if not value:
        raise EvidenceError('xp_publication: ' + code)


def validate_context(context):
    """Pins come from the accepted finite plan and terminal attempt receipt."""
    fields = {'schema_version', 'protocol', 'run_id', 'request', 'adapter_fingerprint',
              'runtime_manifest_sha256', 'scorer_sha256', 'journal', 'backend'}
    require(isinstance(context, dict) and set(context) == fields
            and type(context['schema_version']) is int and context['schema_version'] == 1
            and context['protocol'] == PROTOCOL and isinstance(context['run_id'], str)
            and RUN.fullmatch(context['run_id']), 'explicit_native_context_required')
    for key in ('adapter_fingerprint', 'runtime_manifest_sha256', 'scorer_sha256'):
        require(isinstance(context[key], str) and SHA.fullmatch(context[key]), 'invalid_context_pin')
    for key, filename in (('journal', 'journal.json'), ('backend', 'backend-state.json')):
        ref = context[key]
        require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}
                and ref['path'] == filename and isinstance(ref['sha256'], str)
                and SHA.fullmatch(ref['sha256']), 'invalid_context_artifact')
    request = validate_spec(context['request'])
    require(request.get('schema_version') == 3 and request.get('protocol') == windows.PROTOCOL,
            'native_window_trial_required')
    return context


def _verify_attempt(root, context):
    """Return only public-safe values after every enclosing receipt is checked.

    A complete projection is still unranked and publication-ineligible until the
    separate native-runtime/baseline acceptance milestone is actually satisfied.
    Capture policy is selected only from the frozen adaptive scenario, never
    inferred from decoded duration or supplied by a mutable publication option.
    """
    validate_context(context)
    root = Path(root)
    require(root.is_absolute() and root.resolve() == root and not root.is_symlink(), 'canonical_attempt_root_required')
    scorer_hash = hashlib.sha256(Path(windows.__file__).read_bytes()).hexdigest()
    require(scorer_hash == context['scorer_sha256'], 'frozen_scorer_mismatch')
    journal = read_json_artifact(root, context, 'journal')
    backend = read_json_artifact(root, context, 'backend')
    request, ident = context['request'], context['run_id']
    require(journal.get('attempt_id') == backend.get('attempt_id') == ident
            and same_json(journal.get('request'), request)
            and journal.get('adapter_fingerprint') == context['adapter_fingerprint']
            and journal.get('status') == 'completed' and journal.get('api_outcome') == 'confirmed'
            and journal.get('phase') == 'status' and journal.get('phase_status') == 'returned'
            and journal.get('pending') is None and backend.get('pending') is None
            and backend.get('clean') is True and backend.get('ordinary_logout', {}).get('confirmed') is True,
            'completed_native_attempt_required')
    events = journal.get('events')
    require(isinstance(events, list) and 1 <= len(events) <= 10000
            and all(isinstance(e, dict) and type(e.get('sequence')) is int and e['sequence'] == i
                    for i, e in enumerate(events))
            and any(e.get('kind') == 'evidence_verified' for e in events), 'runner_verification_required')
    receipts = journal['receipts']
    require(receipts.get('cleanup') == {'attempt_id': ident, 'clean': True}
            and isinstance(receipts.get('status'), dict)
            and all(receipts['status'].get(k) is (k != 'ownership_conflict') for k in STATUS_FIELDS),
            'terminal_cleanup_required')
    refs = receipts['collect_final']['artifacts']
    manifest = read_json_artifact(root, refs, 'xp_manifest')
    score = windows.verify_trial_bundle(manifest, root, refs)
    require(same_json(score, journal.get('score')) and same_json(score, read_json_artifact(root, refs, 'score'))
            and score['run_id'] == ident and score['complete_windows'] == 20 and score['incomplete_tail_ms'] == 0
            and score['scenario_fingerprint'] == request['scenario_fingerprint']
            and score['baseline_sha256'] == request['baseline_sha256'], 'native_score_receipts_mismatch')
    scenario = read_json_artifact(root, refs, 'scenario')
    result = read_json_artifact(root, refs, 'result')
    runtime = read_json_artifact(root, refs, 'runtime_manifest')
    protocol = scenario['adaptive_protocol']
    require(same_json(protocol.get('horizon_policy'), FULL_HORIZON_POLICY)
            and same_json(scenario.get('trial_budgets'), request['budgets'])
            and refs['runtime_manifest']['sha256'] == context['runtime_manifest_sha256']
            and runtime.get('schema_version') == 2 and type(runtime['schema_version']) is int
            and isinstance(runtime.get('server_jar'), dict)
            and isinstance(runtime['server_jar'].get('sha256'), str)
            and SHA.fullmatch(runtime['server_jar']['sha256']), 'frozen_native_fixture_required')
    limits = request['budgets']
    require(limits['controller_seconds'] == protocol['wall_seconds'] == 300
            and limits['max_actions'] == protocol['max_actions']
            and limits['max_api_requests'] == protocol['max_api_requests']
            and limits['max_total_tokens'] == protocol['max_total_tokens']
            and limits['max_output_tokens'] == protocol['max_api_requests'] * protocol['max_output_tokens'],
            'frozen_controller_budgets_mismatch')
    trial_context = {key: request[key] for key in ('scenario_fingerprint', 'baseline_sha256')}
    controller = result['controller']
    require(result.get('protocol') == scenario.get('protocol') == ADAPTIVE
            and controller.get('id') == ident and controller.get('model') == request['model']
            and controller.get('mode') == 'api' and controller.get('status') == 'completed'
            and same_json(result.get('trialContext'), trial_context)
            and same_json(controller.get('trialContext'), trial_context)
            and scenario.get('instructions_sha256') == result['adaptive']['instructions']['sha256'],
            'exact_controller_attribution_required')
    initial = read_json_artifact(root, refs, 'initial_db')
    final = read_json_artifact(root, refs, 'final_db')
    session = read_json_artifact(root, refs, 'session')
    raw = read_artifact_bytes(root, refs['xp_ledger'], 'xp_ledger', maximum=windows.MAX_LEDGER_BYTES)
    require(backend.get('xp_header', {}).get('sha256') == hashlib.sha256(raw.splitlines(keepends=True)[0]).hexdigest(),
            'native_startup_header_mismatch')
    native = None
    if protocol.get('progression_policy'):
        native = {'contract': scenario['xp_window_protocol'],
                  'identity': {key: manifest[key] for key in windows.IDENTITY},
                  'initial': {key: initial['character'][key] for key in ('level', 'exp')},
                  'final': {key: final['character'][key] for key in ('level', 'exp')},
                  'window': manifest['window'], 'committed_at_ms': session['save']['committed_at_ms'],
                  'ledger': refs['xp_ledger']}
    checked = verify_result(result, root, protocol=protocol, model=request['model'], native_progression=native)
    counters = checked['counters']
    require(same_json(journal.get('charged_usage'), {'api_requests': counters['api_responses_confirmed'],
            'total_tokens': counters['actual_total_tokens']}), 'confirmed_usage_mismatch')
    from full_client_publish import (_verify_docker_execution, _verify_readiness_policy,
                                    _verify_settlement_policy, verify_capture_bundle, _probe_video)
    enclosing = {'result': result, 'artifacts': refs, 'budgets': scenario.get('budgets'), 'timeline': result['timeline']}
    evidence = {'run_id': ident, 'baseline': read_json_artifact(root, refs, 'baseline_snapshot'), 'session': session}
    _verify_docker_execution(enclosing, root)
    _verify_readiness_policy(enclosing, root, evidence, scenario)
    recording = read_json_artifact(root, refs, 'recording')
    require(recording.get('status') == 'completed' and recording.get('interrupted') is False
            and recording.get('overlay') == {'controller_id': ident, 'mode': 'api', 'model': request['model']}
            and recording.get('sha256') == refs['video']['sha256']
            and Path(refs['video']['path']).suffix == '.webm', 'original_capture_required')
    measured = verify_capture_bundle(enclosing | {'video': recording}, root)
    _verify_settlement_policy(enclosing | {'video': recording}, root, evidence, scenario)
    video_path = verified_artifact(root, refs['video'], 'video', maximum=MAX_VIDEO)
    probe = _probe_video(video_path, refs['video']['sha256'], maximum_ms=335000)
    capture_contract.verify_video_duration(probe, recording, protocol.get('capture_duration_policy'))
    capture = read_json_artifact(root, refs, 'capture')
    require(capture['first_frame_wall_ms'] + measured['clock_offset_ms']['upper'] <= manifest['window']['start_at_ms'] + 100
            and capture['last_frame_wall_ms'] + measured['clock_offset_ms']['lower'] >= manifest['window']['deadline_at_ms'] - 100,
            'full_native_window_capture_required')
    # Re-read pins after the bounded decoder; no racing closeout or video swap is accepted.
    require(same_json(journal, read_json_artifact(root, context, 'journal'))
            and same_json(backend, read_json_artifact(root, context, 'backend')), 'attempt_changed_during_projection')
    adaptive = public_cycles(result, checked)
    # This nested pilot field stays unknown: only the separate native window metric carries a peak.
    start = manifest['window']['start_at_ms']
    rows = [{'index': w['index'], 'start_ms': w['start_at_ms'] - start, 'end_ms': w['end_at_ms'] - start,
             'net_xp': w['net_xp'], 'normalized_xp_per_minute': w['normalized_xp_per_minute'],
             'best_so_far': w['best_so_far']} for w in score['windows']]
    return {'schema_version': 1, 'protocol': PROTOCOL, 'trial_protocol': windows.PROTOCOL,
            'run_id': ident, 'requested_model': request['model'], 'returned_model': request['model'],
            'status': 'verified_native_windows', 'verification': VERIFIED,
            'authoritative_peak_xp_per_minute': score['peak_normalized_xp_per_minute'],
            'persisted_net_xp': score['persisted_net_xp'], 'control_window_net_xp': score['control_window_net_xp'],
            'window_ms': windows.WINDOW_MS, 'wall_budget_ms': 300000, 'complete_windows': 20,
            'incomplete_tail_ms': 0, 'windows': rows, 'normalization': score['normalization'],
            'initial_level': initial['character']['level'], 'final_level': final['character']['level'],
            'adaptive': adaptive,
            'recording': {'sha256': refs['video']['sha256'], 'bytes': video_path.stat().st_size,
                          'duration_ms': probe['duration_ms'], 'width': probe['width'], 'height': probe['height'],
                          'frames': probe['frames'], 'visual_review': 'not_assessed',
                          'playback': playback_cue(result, recording, counters['actions'])},
            'provenance': {'source': windows.SOURCE, 'trust_boundary': 'trusted_native_runtime_and_collector',
                'scorer_sha256': scorer_hash, 'publication_adapter_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'experience_table_sha256': score['experience_table_sha256'],
                'native_server_jar_sha256': runtime['server_jar']['sha256'],
                'capture_duration_policy': protocol.get('capture_duration_policy'),
                'capture_verifier_sha256': hashlib.sha256(Path(capture_contract.__file__).read_bytes()).hexdigest(),
                'journal_sha256': context['journal']['sha256'], 'backend_sha256': context['backend']['sha256'],
                'artifact_sha256': {name: refs[name]['sha256'] for name in
                    ('xp_manifest', 'xp_ledger', 'save', 'native_log', 'initial_db', 'final_db', 'session',
                     'scenario', 'baseline', 'runtime_manifest', 'result', 'capture', 'recording', 'video')}},
            'ranked': False, 'publication_eligible': False, 'publication_blocker': BLOCKER}


def _acceptance(row, root, context, native_acceptance, recording_review):
    if native_acceptance is None:
        require(recording_review is None, 'native_acceptance_required_before_model_review')
        return row
    from full_client_native_xp_gate import verify_native, verify_model_review
    native = verify_native(native_acceptance, model_root=root, model_context=context,
                           model_projection=row)
    row['native_runtime_acceptance'] = native
    row['publication_blocker'] = 'model_recording_visual_review_required'
    if recording_review is not None:
        review = verify_model_review(root, recording_review, context=context, projection=row, native=native)
        row['recording']['visual_review'] = review['status']
        row['recording']['visual_review_sha256'] = review['sha256']
        row['publication_blocker'] = None
        row['publication_eligible'] = True
    return row


def verify_attempt(root, context, *, native_acceptance=None, recording_review=None):
    """Strict evidence verification; optional acceptance never authorizes deployment."""
    row = _verify_attempt(root, context)
    return _acceptance(row, root, context, native_acceptance, recording_review)


def project_attempt(root, context, *, native_acceptance=None, recording_review=None):
    """A malformed caller context is an error; unavailable evidence is unknown."""
    validate_context(context)
    try:
        row = _verify_attempt(root, context)
    except (ValueError, OSError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
        return {'schema_version': 1, 'protocol': PROTOCOL, 'trial_protocol': windows.PROTOCOL,
                'run_id': context['run_id'], 'requested_model': context['request']['model'], 'returned_model': None,
                'status': 'unknown', 'verification': 'unverified', 'reason': 'missing_or_inconsistent_native_window_evidence',
                'authoritative_peak_xp_per_minute': None, 'persisted_net_xp': None, 'control_window_net_xp': None,
                'complete_windows': None, 'windows': [], 'recording': None, 'adaptive': None,
                'ranked': False, 'publication_eligible': False, 'publication_blocker': BLOCKER}
    try:
        return _acceptance(row, root, context, native_acceptance, recording_review)
    except (ValueError, OSError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
        # A review failure cannot erase an independently verified signed metric.
        # It only closes publication; unknown evidence is never manufactured zero.
        row['publication_eligible'] = False
        row['publication_blocker'] = ('model_recording_visual_review_unverified'
            if row.get('native_runtime_acceptance') else 'native_runtime_acceptance_unverified')
        return row
