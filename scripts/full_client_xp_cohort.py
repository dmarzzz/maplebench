"""Bounded publication of explicitly admitted native XP-window cohorts.

This adapter joins an operator-pinned plan to the existing strict XP verifier.
It cannot activate a native runtime, infer acceptance, rerun an API, or deploy.
"""
import hashlib
import os
from pathlib import Path

from full_client_dashboard import Reader, integer, project_attempt
from full_client_gallery import copy_recording, directory
from full_client_publication import digest, encoded, missing_row, require
from full_client_research import CLASSES, TASKS
from full_client_score import same_json
import full_client_xp_publication as xp
import full_client_xp_windows as windows

PROTOCOL = windows.PROTOCOL
EVIDENCE_PROTOCOL = 'native-xp-cohort-evidence-v1'
VERIFIED = xp.VERIFIED


def checked_public(row):
    """Validate a pinned public projection; never infer native evidence from it."""
    if row.get('score_verification') != VERIFIED:
        return False
    native = row.get('native_xp')
    require(isinstance(native, dict) and set(native) == {
        'protocol', 'trial_protocol', 'status', 'verification', 'authoritative_peak_xp_per_minute',
        'persisted_net_xp', 'control_window_net_xp', 'window_ms', 'wall_budget_ms', 'complete_windows',
        'incomplete_tail_ms', 'windows', 'normalization', 'initial_level', 'final_level',
        'native_runtime_acceptance', 'publication_eligible', 'publication_blocker', 'ranked',
        'evidence_sha256', 'recording_review_sha256'}
        and native['protocol'] == xp.PROTOCOL and native['trial_protocol'] == PROTOCOL
        and native['verification'] == VERIFIED and native['status'] == 'verified_native_windows'
        and native['ranked'] is False and native['publication_eligible'] is True
        and native['publication_blocker'] is None and row.get('publication_eligible') is True
        and row.get('status') == 'completed' and row.get('mode') == 'api'
        and row.get('attribution') == 'exact' and row.get('returned_model') == row.get('requested_model')
        and row.get('protocol_id') == PROTOCOL
        and native['window_ms'] == 15000 and native['wall_budget_ms'] == 300000
        and native['complete_windows'] == 20 and native['incomplete_tail_ms'] == 0
        and isinstance(native['windows'], list) and len(native['windows']) == 20,
        'catalog_native_window_contract')
    require(all(isinstance(native[k], str) and xp.SHA.fullmatch(native[k]) for k in
        ('evidence_sha256', 'recording_review_sha256', 'native_runtime_acceptance')),
        'catalog_native_acceptance_hashes')
    norm = native['normalization']
    require(isinstance(norm, dict) and set(norm) == {'server_xp_multiplier', 'simulation_speed_multiplier'},
            'catalog_native_normalization')
    factor = windows.multiplier(norm['server_xp_multiplier']) * windows.multiplier(norm['simulation_speed_multiplier'])
    best = 0; total = 0
    for i, window in enumerate(native['windows']):
        require(isinstance(window, dict) and set(window) == {
            'index', 'start_ms', 'end_ms', 'net_xp', 'normalized_xp_per_minute', 'best_so_far'}
            and type(window['index']) is int and window['index'] == i
            and type(window['start_ms']) is int and window['start_ms'] == i * 15000
            and type(window['end_ms']) is int and window['end_ms'] == (i + 1) * 15000
            and type(window['net_xp']) is int and abs(window['net_xp']) < 2**53,
            'catalog_native_window_row')
        rate = float(window['net_xp'] * 4 / factor)
        best = max(best, rate); total += window['net_xp']
        require(type(window['normalized_xp_per_minute']) in (int, float)
            and window['normalized_xp_per_minute'] == rate and window['best_so_far'] == best,
            'catalog_native_rate_mismatch')
    require(native['authoritative_peak_xp_per_minute'] == row.get('authoritative_peak_xp_per_minute') == best
        and native['control_window_net_xp'] == total
        and type(native['persisted_net_xp']) is int and abs(native['persisted_net_xp']) < 2**53
        and native['persisted_net_xp'] == row.get('persisted_xp')
        and all(type(native[k]) is int and 1 <= native[k] <= 200 for k in ('initial_level', 'final_level'))
        and native['final_level'] >= native['initial_level']
        and isinstance(row.get('adaptive'), dict)
        and row['adaptive'].get('verification') == 'all_cycle_receipts_rechecked',
        'catalog_native_metric_mismatch')
    return True


def checked_inputs(plan, scenario_path, profile, evidence):
    from full_client_adaptive import PROTOCOL as ADAPTIVE, validate_protocol, FULL_HORIZON_POLICY, FINAL_SLOT_POLICY
    fixture = plan['fixtures'][0]
    path = Path(scenario_path)
    scenario = Reader().json(directory(path.parent), path.name, fixture['scenario']['sha256'])
    require(scenario.get('protocol') == ADAPTIVE, 'xp_adaptive_scenario_required')
    protocol = validate_protocol(scenario.get('adaptive_protocol'))
    windows.validate_contract(scenario.get('xp_window_protocol'))
    require(protocol.get('horizon_policy') in (FULL_HORIZON_POLICY, FINAL_SLOT_POLICY)
            and same_json(scenario.get('trial_budgets'), fixture['budgets'])
            and all(e['spec'].get('schema_version') == 3 and e['spec'].get('protocol') == PROTOCOL
                    for e in plan['entries']), 'xp_specs_required')
    require(isinstance(profile, dict) and set(profile) == {'protocol_id', 'class_id', 'task_id'}
            and profile['protocol_id'] == PROTOCOL and profile['class_id'] in CLASSES
            and profile['class_id'] != 'undeclared' and profile['task_id'] in TASKS
            and protocol['profile']['class_name'] == CLASSES[profile['class_id']], 'xp_public_profile_required')
    require(isinstance(evidence, dict) and set(evidence) == {
        'schema_version', 'protocol', 'scorer_sha256', 'native_acceptance', 'attempts'}
        and type(evidence['schema_version']) is int and evidence['schema_version'] == 1
        and evidence['protocol'] == EVIDENCE_PROTOCOL
        and evidence['scorer_sha256'] == hashlib.sha256(Path(windows.__file__).read_bytes()).hexdigest()
        and (evidence['native_acceptance'] is None or isinstance(evidence['native_acceptance'], dict))
        and isinstance(evidence['attempts'], dict)
        and set(evidence['attempts']) <= {e['attempt_id'] for e in plan['entries']}, 'xp_explicit_evidence_required')
    for ident, refs in evidence['attempts'].items():
        require(isinstance(refs, dict) and set(refs) == {'journal', 'backend', 'recording_review'},
                'xp_terminal_pins_required')
        entry = next(e for e in plan['entries'] if e['attempt_id'] == ident)
        xp.validate_context(context(entry, fixture, evidence, refs))
        review = refs['recording_review']
        if review is not None:
            from full_client_native_xp_gate import reference
            reference(review)
    return profile, scenario


def context(entry, fixture, evidence, refs):
    return {'schema_version': 1, 'protocol': xp.PROTOCOL, 'run_id': entry['attempt_id'],
        'request': entry['spec'], 'adapter_fingerprint': fixture['adapter_fingerprint'],
        'runtime_manifest_sha256': fixture['runtime_manifest']['sha256'],
        'scorer_sha256': evidence['scorer_sha256'], 'journal': refs['journal'], 'backend': refs['backend']}


def pending(entry):
    row = missing_row(entry)
    row.update(protocol_id=PROTOCOL, authoritative_peak_xp_per_minute=None,
               native_xp=None, recording_publication='not_ready')
    return row


def project_member(entry, fixture, attempt_root, recordings, scenario, evidence):
    ident = entry['attempt_id']; folder = attempt_root / ident
    row = pending(entry)
    if not os.path.lexists(folder):
        return row
    target = recordings / (ident + '.webm')
    try:
        directory(folder); reader = Reader(); journal = reader.json(folder, 'journal.json')
        require(journal.get('attempt_id') == ident and same_json(journal.get('request'), entry['spec'])
                and journal.get('adapter_fingerprint') == fixture['adapter_fingerprint'], 'xp_cohort_request_mismatch')
        stamp = max([e.get('at_ms') for e in journal.get('events', [])
                     if isinstance(e, dict) and integer(e.get('at_ms')) is not None], default=0)
        row = project_attempt(reader, ident, folder, None, {}, None, stamp, '/recordings/')
        row.update(protocol_id=PROTOCOL, mode='api', returned_model=None, attribution='pending',
            api_usage={}, persisted_xp=None, authoritative_peak_xp_per_minute=None,
            comparison_group=None, score_verification='unverified', recording=None,
            recording_publication='not_ready', publication_eligible=False,
            native_xp=None, adaptive=None, action_verification='unverified', no_op=None)
        if journal.get('status') != 'completed':
            return row
        refs = evidence['attempts'].get(ident)
        if refs is None:
            row['native_xp'] = {'status': 'acceptance_pending', 'publication_blocker': 'terminal_operator_pins_required'}
            return row
        checked = xp.project_attempt(folder, context(entry, fixture, evidence, refs),
            native_acceptance=evidence['native_acceptance'], recording_review=refs['recording_review'])
        if checked['publication_eligible'] is not True:
            # The strict local projection retains valid raw signed metrics, but
            # public scores and media wait for both explicit acceptance gates.
            row['native_xp'] = {'status': 'acceptance_pending',
                                'publication_blocker': checked['publication_blocker']}
            return row
        counters = checked['adaptive']['counters']
        artifact_refs = journal['receipts']['collect_final']['artifacts']
        require(artifact_refs['scenario']['sha256'] == fixture['scenario']['sha256'], 'xp_scenario_mismatch')
        copy_recording(folder, artifact_refs['video'], target, {}, maximum=xp.MAX_VIDEO)
        require(target.stat().st_size == checked['recording']['bytes'], 'xp_video_size_changed')
        recording = {'url': './recordings/' + ident + '.webm', 'sha256': checked['recording']['sha256'], 'reviewed': True}
        if checked['recording']['playback'] is not None:
            recording['playback'] = checked['recording']['playback']
        group = digest(encoded({'protocol': PROTOCOL,
            **{k: fixture[k]['sha256'] for k in ('scenario', 'baseline', 'runtime_manifest')},
            'scorer_sha256': evidence['scorer_sha256'], 'budgets': fixture['budgets']}))
        row.update(status='completed', returned_model=entry['model'], attribution='exact',
            score_verification=VERIFIED, comparison_group=group,
            persisted_xp=checked['persisted_net_xp'],
            authoritative_peak_xp_per_minute=checked['authoritative_peak_xp_per_minute'],
            api_usage={k: counters['actual_' + k] for k in ('input_tokens', 'output_tokens', 'total_tokens')},
            api_response_saved=True, actions=counters['actions'], acknowledged_actions=counters['actions'],
            action_attempts=counters['action_attempts'], sdk_calls=counters['sdk_requests'],
            action_verification='receipts_rechecked', no_op=counters['actions'] == 0,
            adaptive=checked['adaptive'], recording=recording, recording_publication='verified_bytes',
            publication_eligible=True, publication_evidence={'status': 'native_windows_checked', 'reason_code': None},
            native_xp={key: checked[key] for key in ('protocol', 'trial_protocol', 'status', 'verification',
                'authoritative_peak_xp_per_minute', 'persisted_net_xp', 'control_window_net_xp',
                'window_ms', 'wall_budget_ms', 'complete_windows', 'incomplete_tail_ms', 'windows',
                'normalization', 'initial_level', 'final_level', 'native_runtime_acceptance',
                'publication_eligible', 'publication_blocker', 'ranked')})
        # Hash-only provenance; the generic public catalog prohibits arbitrary
        # artifact dictionaries and never copies private review text or paths.
        row['native_xp']['evidence_sha256'] = digest(encoded(checked['provenance']))
        row['native_xp']['recording_review_sha256'] = checked['recording']['visual_review_sha256']
        row['native_xp']['native_runtime_acceptance'] = checked['native_runtime_acceptance']['sha256']
        require(same_json(reader.json(folder, 'journal.json'), journal), 'xp_attempt_changed_during_copy')
        return row
    except (ValueError, OSError, TypeError, KeyError, RecursionError):
        target.unlink(missing_ok=True)
        row.update(status='unavailable', failure_code='native_xp_evidence_unavailable',
            persisted_xp=None, authoritative_peak_xp_per_minute=None, native_xp=None,
            score_verification='unverified', comparison_group=None, recording=None,
            recording_publication='unavailable', publication_eligible=False,
            returned_model=None, attribution='pending', adaptive=None)
        return row
