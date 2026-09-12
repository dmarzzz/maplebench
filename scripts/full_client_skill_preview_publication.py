"""Publish short skill demonstrations beside, and outside, benchmark cohorts.

Only explicitly pinned private artifacts are projected. Original recordings and
cohort bytes remain intact. Skill input counts are not claims of successful casts.
"""
import copy
from html import escape
import json
import os
from pathlib import Path
import shutil
import tempfile

from full_client_capture import verify_video_duration
from full_client_dashboard import Reader, RUN, model, number, playback_cue
from full_client_gallery import copy_recording, directory
from full_client_publication import (digest, encoded, require, stable_bytes, verify_package, write_new)
from full_client_publish import verify_capture_bundle, _probe_video
from full_client_score import same_json, read_artifact_bytes
from full_client_skill_toolkit import sdk_scenario, validate_toolkit
from full_client_trial import publish_attempt
from full_client_vercel import checked_payload, MAX_PAYLOAD, PUBLIC_NAME
from maple_agent import validate_rpc

PROTOCOL = 'full-client-skill-preview-v1'
MAX_VIDEO = 96 * 1024**2
REQUIRED_ARTIFACTS = {'result', 'api_request', 'api_response', 'program', 'recording',
    'capture', 'capture_ready', 'capture_clock', 'capture_terminal', 'video_probe', 'video'}


def project_preview(folder, refs, *, probe_video=None):
    """Recheck API identity, actual input receipts, capture, and original bytes."""
    folder = directory(folder)
    require(isinstance(refs, dict) and REQUIRED_ARTIFACTS <= set(refs), 'preview_artifacts_required')
    reader = Reader()
    result = reader.artifact(folder, refs, 'result')
    controller = result.get('controller', {})
    run_id = controller.get('id')
    require(isinstance(run_id, str) and RUN.fullmatch(run_id), 'preview_run_identity')
    from full_client_skill_preview import validate_protocol
    protocol = validate_protocol(result.get('previewProtocol'))
    toolkit = validate_toolkit(protocol['skill_toolkit'], protocol['profile'])
    requested = model(controller.get('model'))
    api = result.get('api', {})
    request = reader.artifact(folder, refs, 'api_request')
    response = reader.artifact(folder, refs, 'api_response')
    require(result.get('protocol') == PROTOCOL and controller.get('protocol') == PROTOCOL
        and same_json(controller.get('previewProtocol'), protocol)
        and result.get('score') is None and result.get('publication_eligible') is False
        and type(result.get('model_api_requests')) is int and result['model_api_requests'] == 1
        and controller.get('mode') == 'api' and controller.get('status') == 'completed'
        and controller.get('workerActive') is False
        and requested is not None and all(value == requested for value in
            (controller.get('returnedModel'), api.get('model'), request.get('model'), response.get('model')))
        and api.get('status') == response.get('status') == 'completed'
        and request.get('metadata', {}).get('maplebench_run_id') == run_id
        and response.get('metadata', {}).get('maplebench_run_id') == run_id,
        'preview_model_or_protocol_mismatch')
    program = read_artifact_bytes(folder, refs['program'], 'program').decode('utf-8')
    text = ''.join(content.get('text', '') for item in response.get('output', []) if item.get('type') == 'message'
        for content in item.get('content', []) if content.get('type') == 'output_text')
    choice = json.loads(text)
    require(isinstance(choice, dict) and choice.get('code') == program
        and result.get('programSha256') == digest(program.encode()), 'preview_program_mismatch')
    from full_client_skill_preview import prompt
    require(request.get('instructions') == prompt(protocol)
        and request.get('max_output_tokens') == 3000 and request.get('reasoning') == {'effort': 'low'}
        and json.loads(request.get('input', 'null')) == {'observation': result.get('initial')},
        'preview_prompt_mismatch')
    token_bound = (len(request['instructions'].encode()) + len(request['input'].encode())
        + len(json.dumps(request.get('text', {}).get('format', {}).get('schema')).encode())
        + 1024 + request['max_output_tokens'])
    require(type(controller.get('apiTokenUpperBound')) is int and controller['apiTokenUpperBound'] == token_bound
        and controller.get('totalTokenLimit') == protocol['max_total_tokens']
        and token_bound <= protocol['max_total_tokens'], 'preview_token_reservation_mismatch')
    execution = result.get('program', {})
    timeline = result.get('timeline', {}); timing = result.get('timing', {})
    reason = execution.get('reason')
    require(reason in ('program_complete', 'time_limit', 'action_limit', 'death')
        and controller.get('reason') == reason and timeline.get('status') == 'completed',
        'preview_terminal_mismatch')
    stamps = [timeline.get(key) for key in ('api_started_ms', 'api_ended_ms', 'program_started_ms', 'program_ended_ms')]
    require(all(type(t) is int for t in stamps) and stamps == sorted(stamps)
        and 0 <= stamps[0] < stamps[1] <= stamps[2] < stamps[3] <= protocol['run_seconds'] * 1000
        and stamps[1] - stamps[0] <= protocol['api_timeout_seconds'] * 1000 + 100
        and stamps[3] - stamps[2] <= (protocol['program_seconds'] + 2) * 1000 + 100
        and number(timing.get('elapsedMs'), stamps[-1], protocol['run_seconds'] * 1000)
        and number(timing.get('startedAtMs')) and number(timing.get('endedAtMs'))
        and abs(timing['endedAtMs'] - timing['startedAtMs'] - timing['elapsedMs']) <= 100,
        'preview_timing_bounds')
    usage = response.get('usage', {})
    require(same_json(api.get('usage'), usage) and all(type(usage.get(key)) is int and usage[key] >= 0
        for key in ('input_tokens', 'output_tokens', 'total_tokens'))
        and usage['total_tokens'] == usage['input_tokens'] + usage['output_tokens']
        and usage['output_tokens'] <= protocol['max_output_tokens']
        and usage['total_tokens'] <= protocol['max_total_tokens'], 'preview_usage_bounds')
    steps = execution.get('steps')
    limit = controller.get('sdkRequestLimit')
    require(type(limit) is int and limit == 600 and controller.get('actionLimit') == 240
        and controller.get('programSeconds') == 60 and isinstance(steps, list)
        and 1 <= len(steps) <= limit and execution.get('error') is None,
        'preview_execution_incomplete')
    counts = {skill['slot']: 0 for skill in toolkit['skills']}
    actions = 0
    for index, step in enumerate(steps):
        require(isinstance(step, dict) and step.get('kind') == 'sdk'
            and step.get('method') in ('observe', 'wait', 'pressKeys')
            and type(step.get('rpcId')) is int and step['rpcId'] == index + 1, 'preview_execution_incomplete')
        method, _ = validate_rpc({'type': 'rpc', 'id': step['rpcId'],
            'method': step.get('method'), 'args': step.get('args')},
            {'adapter': 'full-client', **sdk_scenario(protocol)})
        if method == 'pressKeys':
            require(step.get('result', {}).get('accepted') is True
                and step['result'].get('error') is None, 'preview_input_incomplete')
            actions += 1
            for key in step['args'][0]:
                if key in counts: counts[key] += 1
        receipt = step.get('result', {})
        if method in ('observe', 'pressKeys'):
            obs = receipt if method == 'observe' else receipt.get('observation', {})
            require(obs.get('source') == 'full-client' and obs.get('ready') is True
                and all(number(obs.get(key), 0, 1499.999) for key in ('ageMs', 'renderAgeMs')),
                'preview_stale_observation')
        if method == 'wait':
            waited = receipt.get('waitedMs'); requested_wait = step['args'][0]
            require(number(waited, 0, requested_wait + 100)
                and (waited >= requested_wait - 100 or index == len(steps) - 1 and reason == 'time_limit'),
                'preview_wait_receipt')
    require(actions > 0 and all(type(value) is int and value == actions for value in
        (execution.get('actions'), execution.get('actionAttempts'), controller.get('actions')))
        and type(controller.get('actionLimit')) is int and actions <= controller['actionLimit'],
        'preview_action_count_mismatch')
    # A deadline/action cap can reserve one final RPC without sending it. Keep
    # that explicit instead of inventing a receipt or rejecting a clean cutoff.
    rpc_count = execution.get('rpcRequests')
    require(type(rpc_count) is int and (rpc_count == len(steps) or
        (rpc_count == len(steps) + 1 and reason in ('time_limit', 'action_limit')))
        and (reason != 'action_limit' or actions == 240)
        and (reason != 'time_limit' or stamps[3] - stamps[2] >= 60000)
        and (reason != 'death' or result.get('final', {}).get('character', {}).get('alive') is False),
        'preview_counter_or_terminal_mismatch')
    recording = reader.artifact(folder, refs, 'recording')
    video = refs['video']
    require(recording.get('status') == 'completed' and recording.get('interrupted') is False
        and recording.get('post_render_capture') is True and recording.get('sha256') == video.get('sha256')
        and recording.get('overlay') == {'controller_id': run_id, 'mode': 'api', 'model': requested},
        'preview_recording_identity')
    probe = reader.artifact(folder, refs, 'video_probe')
    require(probe.get('video_sha256') == video['sha256'], 'preview_probe_identity')
    verify_capture_bundle({'result': result, 'video': recording, 'artifacts': refs}, folder)
    # Hosts unable to enforce the decoder's memory cap may explicitly supply a
    # trusted Linux decoder transport. It must decode these exact bytes anew;
    # loading the saved probe is not an independent decoder implementation.
    actual_probe = (probe_video or _probe_video)(folder / video['path'], video['sha256'])
    require(same_json({key: value for key, value in probe.items() if key != 'video_sha256'}, actual_probe),
        'preview_decoder_evidence_changed')
    verify_video_duration(actual_probe, recording, recording.get('capture_duration_policy'))
    # Hash via the verified reader; do not trust a saved byte count or a filename.
    from full_client_score import open_verified_artifact
    with open_verified_artifact(folder, video, 'video', maximum=MAX_VIDEO) as stream:
        size = os.fstat(stream.fileno()).st_size
    cue = playback_cue(result, recording, {'actions': actions, 'action_verification': 'receipts_rechecked'})
    require(cue is not None and cue['basis'] == 'first_acknowledged_input', 'preview_playback_cue_required')
    end = result.get('timing', {}).get('endedAtMs')
    require(number(end), 'preview_timing_missing')
    alive = result.get('final', {}).get('character', {}).get('alive')
    require(type(alive) is bool, 'preview_final_observation_missing')
    return {'id': run_id, 'protocol_id': PROTOCOL, 'kind': 'skill_development_preview',
        'class_id': toolkit['class_id'], 'class_name': protocol['profile']['class_name'],
        'requested_model': requested, 'returned_model': requested, 'attribution': 'exact',
        'ranked': False, 'score': None, 'comparison_group': None, 'publication_eligible': False,
        'updated_at_ms': end, 'actions': actions, 'alive_at_last_observation': alive,
        'program_budget_seconds': 60, 'sdk_calls': len(steps),
        'planning_ms': stamps[1] - stamps[0], 'program_elapsed_ms': stamps[3] - stamps[2],
        'sdk_unexecuted_requests': rpc_count - len(steps),
        'skills': [{'name': s['name'], 'key': s['slot'], 'role': s['route'],
                    'acknowledged_inputs': counts[s['slot']]} for s in toolkit['skills']],
        'skill_evidence': 'acknowledged_inputs_not_verified_casts',
        'recording': {'url': './recordings/' + run_id + '.webm', 'sha256': video['sha256'],
            'bytes': size, 'playback': cue, 'duration_ms': recording['duration_ms']}}


def preview_panel(rows):
    cards = []
    for row in rows:
        recording = row['recording']
        url = escape(recording['url'], quote=True)
        cue = recording['playback']['start_ms'] / 1000
        items = ''.join('<tr><td>' + escape(s['name']) + '</td><td>' + escape(s['key'])
            + '</td><td>' + str(s['acknowledged_inputs']) + '</td></tr>' for s in row['skills'])
        cards.append('<article class="skill-preview-card"><h3>' + escape(row['class_name'])
            + ' · ' + escape(row['requested_model']) + '</h3><video controls playsinline preload="metadata" src="'
            + url + '#t=' + format(cue, '.3f') + '" aria-label="Short ' + escape(row['class_name'], quote=True)
            + ' skill preview"></video><p>60-second program budget · ' + str(row['actions'])
            + ' acknowledged inputs · ' + ('Alive' if row['alive_at_last_observation'] else 'Dead')
            + ' at last observation</p><p>' + format(row['program_elapsed_ms'] / 1000, '.1f')
            + 's of program execution after ' + format(row['planning_ms'] / 1000, '.1f')
            + 's of model planning.</p><p><a href="' + url + '">Full original recording, including planning</a></p>'
            + '<details><summary>Available skills and model inputs</summary><table><thead><tr>'
            + '<th scope="col">Skill</th><th scope="col">SDK key</th><th scope="col">Inputs</th>'
            + '</tr></thead><tbody>' + items + '</tbody></table></details><p class="skill-preview-id">Run '
            + row['id'] + '</p></article>')
    return ('<!-- skill-previews:start --><section id="skill-previews" class="section" aria-labelledby="skill-previews-title">'
        '<h2 id="skill-previews-title">Short skill previews</h2><p>Recent model experiments with expanded class controls. '
        'Playback opens at the first acknowledged input. These development clips are outside the benchmark comparisons.</p>'
        '<p>Input counts show what the model requested. They do not prove successful casts or damage.</p>'
        '<div class="skill-preview-grid">' + ''.join(cards) + '</div></section><!-- skill-previews:end -->')


def attach_previews(catalog, selections, output_root, *, probe_video=None):
    """Add 1–4 pinned previews to a verified catalog without changing its cohorts."""
    require(isinstance(selections, list) and 1 <= len(selections) <= 4, 'preview_selection_limit')
    original = directory(Path(catalog['site']))
    primary = verify_package(Path(catalog['primary_package']), catalog['primary_content_sha256'])
    files, _ = checked_payload(original, Path(catalog['inventory']), catalog['inventory_sha256'], primary)
    rows = []; sources = []
    for selection in selections:
        require(isinstance(selection, dict) and set(selection) == {'folder', 'artifacts', 'artifacts_sha256'},
            'preview_selection_schema')
        folder = directory(Path(selection['folder']))
        refs = Reader().json(folder, selection['artifacts'], selection['artifacts_sha256'])
        row = project_preview(folder, refs, probe_video=probe_video)
        require(row['id'] not in {r['id'] for r in rows}, 'preview_duplicate_run')
        row['recording']['url'] = './previews/' + row['id'] + '/recordings/' + row['id'] + '.webm'
        rows.append(row); sources.append((folder, refs, row))
    rows.sort(key=lambda row: (-row['updated_at_ms'], row['id']))
    snapshot = Reader().json(original, 'results.json', files['results.json']['sha256'])
    require('development_previews' not in snapshot, 'preview_existing_selection_required')
    snapshot['development_previews'] = rows
    html = stable_bytes(original / 'index.html', 4 * 1024**2).decode('utf-8')
    require('<!-- skill-previews:start -->' not in html and html.count('<main>') == 1, 'preview_html_anchor')
    html = html.replace('<main>', '<main>\n' + preview_panel(rows), 1)
    style = (stable_bytes(original / 'style.css', 4 * 1024**2) + b'\n'
        b'.skill-preview-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,400px),1fr));gap:24px}'
        b'.skill-preview-card{background:#fff;border:1px solid #d6d1c8;border-radius:16px;padding:20px;min-width:0}'
        b'.skill-preview-card video{display:block;width:100%;aspect-ratio:4/3;background:#17252e;border-radius:8px}'
        b'.skill-preview-card table{width:100%;text-align:left}.skill-preview-card td,.skill-preview-card th{padding:7px}'
        b'.skill-preview-id{font-size:12px;overflow-wrap:anywhere}.skill-preview-card summary{cursor:pointer}\n')
    root_data = {'index.html': html.encode(), 'style.css': style, 'results.json': encoded(snapshot)}
    planned = copy.deepcopy(files)
    for _, refs, row in sources:
        name = row['recording']['url'][2:]
        require(name not in planned and PUBLIC_NAME.fullmatch(name), 'preview_mount_conflict')
        planned[name] = {key: row['recording'][key] for key in ('sha256', 'bytes')}
    manifest = Reader().json(original, 'recording-manifest.json', files['recording-manifest.json']['sha256'])
    require(set(manifest) == {'schema_version', 'entries'} and manifest['schema_version'] == 1,
        'preview_recording_manifest')
    manifest['entries'] += [{'path': row['recording']['url'][2:], **{key: row['recording'][key]
        for key in ('sha256', 'bytes')}} for row in rows]
    root_data['recording-manifest.json'] = encoded(manifest)
    planned.update({name: {'sha256': digest(raw), 'bytes': len(raw)} for name, raw in root_data.items()})
    require(len(planned) <= 100 and sum(v['bytes'] for v in planned.values()) <= MAX_PAYLOAD,
        'preview_payload_limit')
    output_root = directory(Path(output_root))
    require(not output_root.is_relative_to(original) and not original.is_relative_to(output_root)
        and all(not output_root.is_relative_to(folder) and not folder.is_relative_to(output_root)
            for folder, _, _ in sources), 'preview_output_overlap')
    stage = Path(tempfile.mkdtemp(prefix='.skill-previews-', dir=output_root))
    site = stage / 'site'; site.mkdir(mode=0o755)
    try:
        from full_client_catalog import copy_file
        for name, expected in files.items():
            if name not in root_data: copy_file(original, name, site / name, expected)
        for folder, refs, row in sources:
            target = site / row['recording']['url'][2:]
            target.parent.mkdir(parents=True)
            copy_recording(folder, refs['video'], target, {}, maximum=MAX_VIDEO)
        for name, raw in root_data.items(): write_new(site / name, raw, 0o644)
        old_inventory = Reader().json(Path(catalog['inventory']).parent, Path(catalog['inventory']).name,
            catalog['inventory_sha256'])
        # A new payload gets a new immutable publication identity. Copy only
        # verified cohort bytes and its manifest, never the old deployment
        # intents. The bound payload hash prevents reusing this identity for
        # other root content; existing uncertain/published intents stay intact.
        publication_package = stage / 'publication-package'; publication_package.mkdir(mode=0o700)
        shutil.copytree(Path(catalog['primary_package']) / 'site', publication_package / 'site')
        bound_content = {**primary['content'], 'presentation_parent_sha256': catalog['primary_content_sha256'],
            'skill_preview_payload_sha256': digest(encoded(planned))}
        bound_sha = digest(encoded(bound_content))
        bound_manifest = {'schema_version': 1, 'content_sha256': bound_sha, 'content': bound_content}
        write_new(publication_package / 'package-manifest.json', encoded(bound_manifest))
        verify_package(publication_package, bound_sha)
        if 'cohort_manifests' in old_inventory:
            old_inventory['cohort_manifests'] = [bound_manifest if item['content']['target_path'] ==
                primary['content']['target_path'] else item for item in old_inventory['cohort_manifests']]
        inventory = encoded({**old_inventory, 'files': planned})
        write_new(stage / 'payload-inventory.json', inventory)
        checked_payload(site, stage / 'payload-inventory.json', digest(inventory), bound_manifest)
        identity = digest(encoded({'parent_inventory_sha256': catalog['inventory_sha256'], 'files': planned}))
        destination = output_root / identity
        require(not os.path.lexists(destination), 'preview_package_exists')
        receipt = {**catalog, 'directory': str(destination), 'site': str(destination / 'site'),
            'inventory': str(destination / 'payload-inventory.json'), 'inventory_sha256': digest(inventory),
            'catalog_sha256': identity, 'preview_run_ids': [r['id'] for r in rows],
            'primary_package': str(destination / 'publication-package'), 'primary_content_sha256': bound_sha,
            'api_requests': 0, 'deployment_performed': False}
        write_new(stage / 'skill-preview-publication.json', encoded(receipt))
        publish_attempt(stage, destination)
        return receipt
    finally:
        if stage.exists(): shutil.rmtree(stage)
