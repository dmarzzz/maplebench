"""Read-only publication of scripted environment checks, outside model results.

Explicit operator-selected artifacts and decoder/clock transports form the trust
boundary. These receipts do not prove full skill qualification or ranked XP.
"""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from full_client_capture import verify_video_duration
from full_client_dashboard import Reader, RUN, SHA, number
from full_client_gallery import copy_recording, directory
from full_client_native import PRODUCTIVITY_V2_PROTOCOL, validate_contract, program
from full_client_native_xp_acceptance import verify_sdk_receipts
from full_client_native_xp_inventory import check_snapshot
from full_client_publication import digest, encoded, require, stable_bytes, stable_fingerprint, verify_package, write_new
from full_client_publish import _probe_video, verify_capture_bundle
from full_client_score import read_artifact_bytes, same_json
from full_client_trial import publish_attempt
from full_client_vercel import checked_payload, MAX_PAYLOAD, PUBLIC_NAME

MAINTENANCE_PROTOCOL = 'native-productivity-development-v2'
MAX_VIDEO = 96 * 1024**2
CLASSES = ('hero', 'bowmaster', 'ice_lightning_arch_mage', 'night_lord')
JOBS = dict(zip(CLASSES, (112, 312, 222, 412)))
BOUND_ARTIFACTS = {'scenario', 'result', 'program', 'initial_db', 'final_db', 'restored_db', 'reset',
    'save', 'native_log', 'capture', 'capture_ready', 'capture_clock', 'capture_terminal', 'recording',
    'video_probe', 'video', 'inventory_before_login', 'inventory_after_logout', 'inventory_after_restore',
    'runtime_manifest', 'baseline_snapshot'}
REQUIRED_ARTIFACTS = BOUND_ARTIFACTS | {'outer_complete', 'executor_complete', 'backend', 'clock', 'clock_qualification'}


def _no_model(value):
    return (type(value.get('api_calls')) is int and value['api_calls'] == 0
        and value.get('model') is None and value.get('publication_eligible') is False
        and value.get('class_accepted') is False and value.get('xp_qualification') is False)


def native_playback_cue(result, recording, native):
    """Map acknowledged input onto verified v2 video, without changing old cues."""
    require(validate_contract(native)['id'] == PRODUCTIVITY_V2_PROTOCOL, 'check_input_cue_protocol')
    timeline = result.get('timeline', {}); maximum = native['capture_max_ms']
    start, end, duration = (recording.get(k) for k in ('start_ms', 'end_ms', 'duration_ms'))
    pstart, pend = (timeline.get(k) for k in ('program_started_ms', 'program_ended_ms'))
    target, ack = (timeline.get(k) for k in ('first_input_started_ms', 'first_input_acked_ms'))
    uncertainty = recording.get('timing_uncertainty_ms')
    require(recording.get('interrupted') is False and recording.get('post_render_capture') is True
        and recording.get('timing_method') == 'browser_monotonic_duration_with_measured_clock_offset'
        and number(start, -maximum, maximum) and number(end, 0, maximum * 2)
        and number(duration, 1, maximum) and number(uncertainty, 0, 100)
        and number(pstart, 0, maximum) and number(pend, pstart, maximum)
        and start <= pstart < pend <= end and abs(end-start-duration) <= 100
        and number(target, pstart, pend) and number(ack, target, pend)
        and 0 <= target-start < duration, 'check_input_cue_required')
    return {'start_ms': round(max(0, target-start-250)), 'basis': 'first_acknowledged_input',
        'timing_uncertainty_ms': uncertainty}


def observation_pause(value, *, source, requested_ms, earliest, latest, settlement=False):
    """Bind v2 status-only pauses without inventing a tight per-pause deadline."""
    fields = {'source', 'requested_ms', 'started_at_ms', 'ended_at_ms', 'status_observations', 'new_inputs', 'api_calls'}
    if settlement: fields.add('diagnostic_saved_xp_includes_ordinary_late_settlement')
    require(isinstance(value, dict) and set(value) == fields and value['source'] == source
        and type(value['requested_ms']) is int and value['requested_ms'] == requested_ms
        and type(value['started_at_ms']) is int and type(value['ended_at_ms']) is int
        and earliest <= value['started_at_ms'] < value['ended_at_ms'] <= latest
        and requested_ms - 2 <= value['ended_at_ms'] - value['started_at_ms'] <= 720000
        and type(value['status_observations']) is int and value['status_observations'] > 0
        and type(value['new_inputs']) is int and value['new_inputs'] == 0
        and type(value['api_calls']) is int and value['api_calls'] == 0
        and (not settlement or value['diagnostic_saved_xp_includes_ordinary_late_settlement'] is True),
        'check_status_only_pause_required')
    return value['ended_at_ms'] - value['started_at_ms']


def project_check(folder, refs, *, source_revision, runtime_manifest_sha256,
                  clock_verifier_sha256, qualify_clock, probe_video=None):
    """Verify a completed active v2 control; never run a controller or model."""
    folder = directory(Path(folder))
    require(isinstance(refs, dict) and set(refs) == REQUIRED_ARTIFACTS, 'check_artifacts_required')
    require(isinstance(source_revision, str) and re.fullmatch('[a-f0-9]{40}', source_revision)
        and all(isinstance(pin, str) and SHA.fullmatch(pin) for pin in
            (runtime_manifest_sha256, clock_verifier_sha256)) and callable(qualify_clock), 'check_trusted_pins_required')
    reader = Reader()
    data = {name: reader.artifact(folder, refs, name) for name in REQUIRED_ARTIFACTS
        - {'program', 'video', 'native_log', 'save'}}
    outer, inner, backend = (data[name] for name in ('outer_complete', 'executor_complete', 'backend'))
    native = validate_contract(data['scenario']); run_id = inner.get('run_id')
    require(native['id'] == PRODUCTIVITY_V2_PROTOCOL and native.get('control') == 'active'
        and native['class_id'] in CLASSES and isinstance(run_id, str) and RUN.fullmatch(run_id), 'check_native_identity')
    require(outer.get('acceptance_id') == run_id and backend.get('attempt_id') == run_id
        and all(value.get('protocol') == MAINTENANCE_PROTOCOL and _no_model(value)
            and value.get('clean') is True and value.get('native_restored') is True for value in (outer, inner))
        and outer.get('status') == 'native_productivity_closed_unscored'
        and inner.get('status') == 'native_productivity_collected_unscored' and inner.get('failure') is None
        and backend.get('maintenance_protocol') == MAINTENANCE_PROTOCOL
        and backend.get('clean') is True and backend.get('native_restored') is True
        and backend.get('publication_eligible') is False and 'run_controller' not in backend.get('intents', []),
        'check_successful_cleanup_required')
    require(outer.get('executor_complete', {}).get('sha256') == refs['executor_complete']['sha256']
        and outer.get('backend_state_ref', {}).get('sha256') == refs['backend']['sha256']
        and same_json(outer.get('artifacts'), inner.get('artifacts'))
        and same_json(inner['artifacts'], backend.get('artifacts')), 'check_completion_graph_changed')
    base = Path(refs['result']['path']).parent
    for name in BOUND_ARTIFACTS:
        original = backend['artifacts'].get(name, {})
        require(original.get('sha256') == refs[name].get('sha256')
            and str(base / original.get('path', '')) == refs[name].get('path'), 'check_artifact_graph_changed')
    require(refs['runtime_manifest']['sha256'] == runtime_manifest_sha256, 'check_runtime_manifest_changed')
    result = data['result']; owner = result.get('controller', {}); execution = result.get('program', {})
    timeline = result.get('timeline', {}); timing = result.get('timing', {})
    raw_program = read_artifact_bytes(folder, refs['program'], 'program', maximum=65536)
    require(raw_program == program(native).encode() and result.get('programSha256') == digest(raw_program)
        and result.get('protocol') == native['id'] and same_json(result.get('nativeAcceptance'), native)
        and result.get('trialContext') is None and result.get('api') is None and result.get('score') is None
        and type(result.get('model_api_requests')) is int and result['model_api_requests'] == 0
        and result.get('publication_eligible') is False and owner.get('id') == run_id
        and owner.get('mode') == 'script' and owner.get('model') is None and owner.get('returnedModel') is None
        and owner.get('protocol') == native['id'] and same_json(owner.get('nativeAcceptance'), native)
        and owner.get('trialContext') is None and owner.get('status') == 'completed'
        and owner.get('workerActive') is False and owner.get('reason') == 'program_complete'
        and execution.get('reason') == 'program_complete' and execution.get('error') is None
        and timeline.get('status') == 'completed', 'check_original_script_required')
    actions = verify_sdk_receipts(execution.get('steps'), native)
    require(1 <= actions <= native['max_actions'] and all(type(v) is int and v == actions for v in
        (execution.get('actions'), execution.get('actionAttempts'), owner.get('actions')))
        and type(execution.get('rpcRequests')) is int and execution['rpcRequests'] == len(execution['steps']),
        'check_input_count_changed')
    start, end = (timeline.get(key) for key in ('program_started_ms', 'program_ended_ms'))
    require(type(start) is int and type(end) is int and 0 <= start < end <= native['capture_max_ms']
        and end - start <= native['wall_seconds'] * 1000 and timing.get('apiLatencyMs') == 0
        and timeline.get('api_started_ms') is None and timeline.get('api_ended_ms') is None
        and number(timing.get('startedAtMs')) and number(timing.get('endedAtMs'))
        and timing['startedAtMs'] + end <= timing['endedAtMs'] + 100, 'check_execution_timing')
    initial, final, restored = (data[name] for name in ('initial_db', 'final_db', 'restored_db'))
    first, last = initial.get('character', {}), final.get('character', {})
    identity = {'run_id': run_id, 'server_instance_id': backend.get('server_instance_id'),
        'character_id': first.get('character_id'), 'account_id': first.get('account_id')}
    require(isinstance(identity['server_instance_id'], str) and RUN.fullmatch(identity['server_instance_id'])
        and all(type(identity[k]) is int and identity[k] > 0 for k in ('character_id', 'account_id'))
        and all(inner.get(k) == v for k, v in identity.items()), 'check_saved_owner_changed')
    for snapshot in (initial, final, restored):
        row = snapshot.get('character', {})
        require(snapshot.get('schema_version') == 1 and snapshot.get('source') == 'cosmic_persisted_character'
            and snapshot.get('run_id') == run_id and snapshot.get('account_logged_in') == 0
            and number(snapshot.get('captured_at_ms')) and all(row.get(k) == first.get(k)
                for k in ('character_id', 'account_id', 'job', 'map_id'))
            and row.get('job') == JOBS[native['class_id']]
            and all(type(row.get(k)) is int and 0 <= row[k] <= 2**31 - 1 for k in ('level', 'exp', 'hp')),
            'check_saved_snapshot_changed')
    require(first['level'] == native['profile']['level'] and first['hp'] > 0
        and same_json(initial, backend.get('initial'))
        and same_json(restored['character'], first) and same_json(restored.get('keymap'), initial.get('keymap'))
        and all(same_json(data['baseline_snapshot'].get(k), initial.get(k)) for k in ('character', 'keymap')),
        'check_baseline_restore_changed')
    reset = data['reset']; session = backend.get('session', {}); logout = backend.get('ordinary_logout', {})
    require(same_json(reset, backend.get('reset')) and reset.get('run_id') == run_id
        and reset.get('baseline_sha256') == native['baseline_sha256']
        and all(reset.get(k) is True for k in ('world_lock_held', 'queue_lock_held', 'server_stopped', 'verified')),
        'check_owned_reset_required')
    stamps = [reset.get('completed_at_ms'), initial['captured_at_ms'], session.get('server_started_at_ms'),
        session.get('login_at_ms'), timing['startedAtMs'] + start, timing['startedAtMs'] + end,
        session.get('disconnect_requested_at_ms'), backend.get('committed_at_ms'),
        session.get('logged_out_at_ms'), final['captured_at_ms'], restored['captured_at_ms']]
    require(all(number(t) for t in stamps) and stamps == sorted(stamps), 'check_save_order_changed')
    require(restored['captured_at_ms'] - reset['completed_at_ms'] <= 720000, 'check_lifecycle_bound')
    warmup_ms = observation_pause(backend.get('native_warmup'),
        source='observation_only_after_ordinary_login_before_capture', requested_ms=3000,
        earliest=session['login_at_ms'], latest=timing['startedAtMs'])
    require(same_json(logout, {'schema_version': 1, 'source': 'cosmic_ordinary_disconnect', **identity,
        'disconnect_requested_at_ms': session['disconnect_requested_at_ms'],
        'logged_out_at_ms': session['logged_out_at_ms'], 'save_committed_at_ms': backend['committed_at_ms']}),
        'check_ordinary_logout_required')
    saves = [json.loads(line) for line in read_artifact_bytes(folder, refs['save'], 'save').splitlines()]
    require(saves and all(row.get('schema_version') == 1 and row.get('source') == 'cosmic_persisted_character'
        and row.get('kind') == 'save_committed' and all(row.get(k) == v for k, v in identity.items())
        and number(row.get('committed_at_ms'), session['server_started_at_ms'], final['captured_at_ms']) for row in saves)
        and sum(session['disconnect_requested_at_ms'] <= row['committed_at_ms'] <= session['logged_out_at_ms']
            for row in saves) == 1 and sum(row['committed_at_ms'] == backend['committed_at_ms'] for row in saves) == 1,
        'check_native_save_commit_required')
    logs = read_artifact_bytes(folder, refs['native_log'], 'native_log')
    require(all(text not in logs for text in (b'MapleBench persistence journal failed', b'Error saving chr')),
        'check_native_save_error')
    for phase in ('before_login', 'after_logout', 'after_restore'):
        check_snapshot(data['inventory_' + phase], native=native, identity=identity, phase=phase,
            runtime_manifest_sha256=runtime_manifest_sha256)
    require(same_json(data['inventory_before_login']['use_inventory'], data['inventory_after_restore']['use_inventory']),
        'check_finite_inventory_restore_changed')
    recording = data['recording']; video = refs['video']
    measured = verify_capture_bundle({'result': result, 'video': recording, 'artifacts': refs}, folder)
    settlement_ms = observation_pause(backend.get('native_settlement'),
        source='observation_only_after_saved_capture_before_ordinary_logout', requested_ms=2000,
        earliest=max(timing['startedAtMs'] + end, timing['startedAtMs'] + measured['end_ms']),
        latest=session['disconnect_requested_at_ms'], settlement=True)
    actual_probe = (probe_video or _probe_video)(folder / video['path'], video['sha256'],
        maximum_ms=native['capture_max_ms'], duration_policy=native['capture_duration_policy'])
    require(same_json(actual_probe, data['video_probe']), 'check_decoder_evidence_changed')
    verify_video_duration(actual_probe, recording, native['capture_duration_policy'])
    video_pin = stable_fingerprint(folder / video['path'], MAX_VIDEO)
    require(video_pin['sha256'] == video['sha256'] == recording.get('sha256'), 'check_video_changed')
    cue = native_playback_cue(result, recording, native)
    require(data['clock'].get('capture_start_wall_ms') == data['capture'].get('start_wall_ms')
        and data['clock'].get('capture_end_wall_ms') == data['capture'].get('end_wall_ms')
        and number(data['clock'].get('capture_start_wall_ms'))
        and number(data['clock'].get('capture_end_wall_ms')), 'check_clock_capture_interval_changed')
    clock = data['clock_qualification']; qualification = qualify_clock(data['clock'], data['capture'])
    expected_clock = {'schema_version': 1, 'run_id': run_id, 'native_protocol': native['id'],
        'source_revision': source_revision, 'runtime_manifest_sha256': runtime_manifest_sha256,
        'capture_sha256': refs['capture']['sha256'], 'video_sha256': video['sha256'],
        'clock_sha256': refs['clock']['sha256'], 'verifier_sha256': clock_verifier_sha256,
        'qualification': qualification}
    require(same_json(clock, expected_clock) and qualification.get('schema_version') == 1
        and qualification.get('status') == 'qualified' and qualification.get('kind') == 'operational_clock_measurement'
        and number(qualification.get('capture_fps'), 30, 1000)
        and abs(qualification['capture_fps'] - measured['rendered_frames'] * 1000 / measured['duration_ms']) < .000001
        and number(qualification.get('simulation_wall_ratio'), .99, 1.01)
        and number(qualification.get('max_pending_ms'), 0) and qualification['max_pending_ms'] < 8
        and type(qualification.get('sample_count')) is int and 3 <= qualification['sample_count'] <= 1000
        and type(qualification.get('api_calls')) is int and qualification['api_calls'] == 0
        and abs(qualification.get('capture_duration_ms', -1) - recording['duration_ms']) <= 100,
        'check_live_clock_qualification_required')
    return {'id': run_id, 'kind': 'scripted_environment_check', 'protocol_id': native['id'],
        'class_id': native['class_id'], 'class_name': native['profile']['class_name'], 'control': 'active',
        'model': None, 'model_api_requests': 0, 'ranked': False, 'score': None, 'comparison_group': None,
        'publication_eligible': False, 'class_accepted': False, 'xp_window_qualified': False,
        'program_budget_seconds': native['wall_seconds'], 'program_elapsed_ms': end - start,
        'actions': actions, 'sdk_calls': len(execution['steps']), 'alive_at_logout': last['hp'] > 0,
        'saved_xp_delta': last['exp'] - first['exp'] if first['level'] == last['level'] else None,
        'initial_level': first['level'], 'final_level': last['level'],
        'saved_xp_evidence': 'ordinary_logout_commit_and_offline_snapshots',
        'saved_xp_scope': 'includes_post_recording_ordinary_settlement',
        'warmup_elapsed_ms': warmup_ms, 'post_recording_settlement_ms': settlement_ms,
        'skill_evidence': 'acknowledged_inputs_not_full_skill_qualification',
        'source_revision': source_revision, 'baseline_sha256': native['baseline_sha256'],
        'runtime_manifest_sha256': runtime_manifest_sha256, 'native_contract_sha256': digest(encoded(native)),
        'clock_evidence': {k: qualification[k] for k in ('capture_fps', 'simulation_wall_ratio', 'max_pending_ms', 'sample_count')},
        'clock_qualification_sha256': refs['clock_qualification']['sha256'],
        'recording': {'url': './checks/' + run_id + '/recordings/' + run_id + '.webm', **video_pin,
            'duration_ms': recording['duration_ms'], 'playback': cue}}


def attach_checks(catalog, selections, output_root, *, qualify_clock, probe_video=None):
    """Attach exactly four distinct classes; preserve all original model bytes."""
    require(isinstance(selections, list) and len(selections) == 4, 'check_four_classes_required')
    original = directory(Path(catalog['site']))
    primary = verify_package(Path(catalog['primary_package']), catalog['primary_content_sha256'])
    files, _ = checked_payload(original, Path(catalog['inventory']), catalog['inventory_sha256'], primary)
    require(b'id="environment-check-grid"' in stable_bytes(original / 'index.html', 4*1024**2)
        and b'function renderEnvironmentChecks(' in stable_bytes(original / 'dashboard.js', 4*1024**2),
        'check_showcase_ui_required')
    sources = []
    for selection in selections:
        require(isinstance(selection, dict) and set(selection) == {'folder', 'artifacts', 'artifacts_sha256',
            'source_revision', 'runtime_manifest_sha256', 'clock_verifier_sha256'}, 'check_selection_schema')
        folder = directory(Path(selection['folder']))
        refs = Reader().json(folder, selection['artifacts'], selection['artifacts_sha256'])
        row = project_check(folder, refs, **{k: selection[k] for k in
            ('source_revision', 'runtime_manifest_sha256', 'clock_verifier_sha256')},
            qualify_clock=qualify_clock, probe_video=probe_video)
        sources.append((folder, refs, row))
    require({row['class_id'] for _, _, row in sources} == set(CLASSES)
        and len({row['id'] for _, _, row in sources}) == 4
        and len({row['source_revision'] for _, _, row in sources}) == 1, 'check_four_distinct_classes_required')
    sources.sort(key=lambda item: CLASSES.index(item[2]['class_id']))
    snapshot = Reader().json(original, 'results.json', files['results.json']['sha256'])
    require('environment_checks' not in snapshot, 'check_existing_selection_immutable')
    snapshot['environment_checks'] = [row for _, _, row in sources]
    manifest = Reader().json(original, 'recording-manifest.json', files['recording-manifest.json']['sha256'])
    require(set(manifest) == {'schema_version', 'entries'} and manifest['schema_version'] == 1,
        'check_recording_manifest')
    manifest['entries'] += [{'path': row['recording']['url'][2:], **{k: row['recording'][k] for k in ('sha256', 'bytes')}}
        for _, _, row in sources]
    root_data = {'results.json': encoded(snapshot), 'recording-manifest.json': encoded(manifest)}
    planned = copy.deepcopy(files)
    for _, _, row in sources:
        name = row['recording']['url'][2:]
        require(name not in planned and PUBLIC_NAME.fullmatch(name), 'check_mount_conflict')
        planned[name] = {k: row['recording'][k] for k in ('sha256', 'bytes')}
    planned.update({name: {'sha256': digest(raw), 'bytes': len(raw)} for name, raw in root_data.items()})
    require(len(planned) <= 100 and sum(item['bytes'] for item in planned.values()) <= MAX_PAYLOAD, 'check_payload_limit')
    output_root = directory(Path(output_root))
    require(not output_root.is_relative_to(original) and not original.is_relative_to(output_root)
        and all(not output_root.is_relative_to(folder) and not folder.is_relative_to(output_root)
            for folder, _, _ in sources), 'check_output_overlap')
    stage = Path(tempfile.mkdtemp(prefix='.environment-checks-', dir=output_root))
    site = stage / 'site'; site.mkdir(mode=0o755)
    try:
        from full_client_catalog import copy_file
        for name, pin in files.items():
            if name not in root_data: copy_file(original, name, site / name, pin)
        for folder, refs, row in sources:
            target = site / row['recording']['url'][2:]; target.parent.mkdir(parents=True)
            copy_recording(folder, refs['video'], target, {}, maximum=MAX_VIDEO)
        for name, raw in root_data.items(): write_new(site / name, raw, 0o644)
        inventory = Reader().json(Path(catalog['inventory']).parent, Path(catalog['inventory']).name, catalog['inventory_sha256'])
        package = stage / 'publication-package'; package.mkdir(mode=0o700)
        shutil.copytree(Path(catalog['primary_package']) / 'site', package / 'site')
        content = {**primary['content'], 'presentation_parent_sha256': catalog['primary_content_sha256'],
            'environment_checks_payload_sha256': digest(encoded(planned))}
        if 'skill_preview_payload_sha256' in content: content['skill_preview_payload_sha256'] = digest(encoded(planned))
        content_sha = digest(encoded(content)); bound = {'schema_version': 1, 'content_sha256': content_sha, 'content': content}
        write_new(package / 'package-manifest.json', encoded(bound)); verify_package(package, content_sha)
        if 'cohort_manifests' in inventory:
            inventory['cohort_manifests'] = [bound if item['content']['target_path'] == primary['content']['target_path'] else item
                for item in inventory['cohort_manifests']]
        raw = encoded({**inventory, 'files': planned}); write_new(stage / 'payload-inventory.json', raw)
        checked_payload(site, stage / 'payload-inventory.json', digest(raw), bound)
        identity = digest(encoded({'parent_inventory_sha256': catalog['inventory_sha256'], 'files': planned}))
        destination = output_root / identity; require(not os.path.lexists(destination), 'check_package_exists')
        receipt = {**catalog, 'directory': str(destination), 'site': str(destination / 'site'),
            'inventory': str(destination / 'payload-inventory.json'), 'inventory_sha256': digest(raw),
            'catalog_sha256': identity, 'environment_check_ids': [row['id'] for _, _, row in sources],
            'primary_package': str(destination / 'publication-package'), 'primary_content_sha256': content_sha,
            'api_requests': 0, 'deployment_performed': False}
        write_new(stage / 'environment-check-publication.json', encoded(receipt)); publish_attempt(stage, destination)
        return receipt
    finally:
        if stage.exists(): shutil.rmtree(stage)
