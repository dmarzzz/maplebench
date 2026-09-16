"""Versioned public reporting of the frozen skill-suite schedule.

This reports sanitized, receipt-backed progress; it neither runs the scorer nor
admits work. Missing reports are explicitly unreported, never submission proof.
Historical XP catalogs and raw runtime evidence are not inputs to this schema.
"""
import argparse
import copy
import csv
from datetime import datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit

PROTOCOL = 'full-client-skill-progress-v1'
DESIGN = 'skill-suite-v1-draft-2026-09-14'
PLAN_FILES = {
    'skill-suite-v1.json': 'fecaef9dab0ccef593783c6d37eb1c851c54ac306862faa5d749b4e0129541d5',
    'skill-suite-v1-schedule.csv': '1cc0ab1837572c824b7d40c1a9a39509b2ee67b20f76de28982ad99691448357',
    'skill-suite-v1-native-checks.csv': 'ff6d4256f03989a7656287cdb2c147217e48230c0dc1de61f4f5dea58178e10b',
}
PHASES = ['native-initial', 'skill-development', 'native-remaining',
          'skill-comparative', 'training-qualification', 'training-long-proposed']
PHASE_LABELS = dict(zip(PHASES, ['Initial native checks', 'Skill development pilot',
    'Remaining native checks', 'Skill comparative cohort', 'Training qualification',
    'Proposed long training cohort']))
TASK_LABELS = {'platforming-v1': 'Platforming', 'native-teleport-v1': 'Native Teleport',
    'potion-use-v1': 'Potion use', 'buff-upkeep-v1': 'Buff upkeep',
    'portal-navigation-v1': 'Portal navigation', 'return-to-hunt-v1': 'Return to hunting',
    'training-hero': 'Hero training', 'training-bowmaster': 'Bowmaster training',
    'training-ice-lightning': 'Ice/Lightning training'}
STATUSES = {'not_started', 'in_progress', 'success', 'gameplay_failure', 'invalid'}
TERMINAL = {'success', 'gameplay_failure', 'invalid'}
ENTRY_FIELDS = {'status', 'execution_manifest_sha256', 'updated_at_utc', 'outcome',
                'reason_code', 'evidence_sha256', 'public_evidence_urls', 'updates'}
UPDATE_FIELDS = {'updated_at_utc', 'previous_status', 'new_status', 'reason_code',
                 'previous_outcome', 'previous_execution_manifest_sha256',
                 'previous_evidence_sha256', 'previous_public_evidence_urls'}
REASONS = set('runtime_and_fixture_bindings native_task_verification '
    'skill_controller_and_observation_contract model_configuration_and_execution_authorization '
    'recording_storage_and_publication execution_manifest_pending source_build_pending '
    'worker_capacity evidence_incomplete protocol_revision_required user_paused '
    'api_outcome_uncertain qualification_failed deadline_insufficient runtime_unavailable '
    'input_ack_uncertain native_event_coverage_invalid provider_error model_mismatch '
    'fixture_mismatch restoration_failed deadline death no_op criterion_not_met task_success '
    'native_check_passed native_check_failed report_correction admitted not_submitted '
    'binding_pending counter_mismatch ledger_incomplete timestamp_invalid '
    'unsupported_configuration freeze_pending pending_actual_evidence '
    'native_position_geometry_physics_coverage native_teleport_causal_link '
    'native_item_ledger_clock_and_closeout qualified_execution_adapter '
    'prior_spend_reconciliation_and_phase_budget'.split())
SHA = re.compile(r'[a-f0-9]{64}\Z')
PUBLIC_PATH = re.compile(r'(?:skill-suite-manifest\.json|skill-suite/(?:' + '|'.join(PHASES)
    + r')/(?:' + '|'.join(TASK_LABELS) + r')\.json)\Z')
MAX_JSON = 4 * 1024**2
MAX_BUNDLE = 16 * 1024**2
PUBLIC_NOTE = ('Reported progress, not a dispatch queue or live worker inventory. '
    'Missing reports do not prove an entry was never submitted. '
    'Native check passes are separate from model success. Historical runs are excluded.')


class ProgressError(ValueError):
    pass


def require(value, code):
    if not value:
        raise ProgressError(code)


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    require(isinstance(raw, bytes) and len(raw) <= MAX_JSON, 'progress_json_limit')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ProgressError('nonfinite_json')))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProgressError('invalid_progress_json') from exc


def load_plan(directory=None):
    """Read the exact original design/schedules; numbering cannot drift on reorder."""
    directory = Path(directory) if directory else Path(__file__).resolve().parents[1] / 'docs/plans'
    values = {}
    for name, sha in PLAN_FILES.items():
        path = directory / name
        require(path.is_file() and not path.is_symlink(), 'plan_file_required')
        raw = path.read_bytes()
        require(len(raw) <= MAX_JSON and digest(raw) == sha, 'frozen_schedule_changed')
        values[name] = raw
    design = decode(values['skill-suite-v1.json'])
    model_rows = list(csv.DictReader(io.StringIO(values['skill-suite-v1-schedule.csv'].decode())))
    native_rows = list(csv.DictReader(io.StringIO(values['skill-suite-v1-native-checks.csv'].decode())))
    initial_tasks = design['phases'][0]['task_ids']
    tasks = {task['id']: task for task in design['tasks']}
    rows, experiments = [], []
    for phase in PHASES:
        native = phase.startswith('native-')
        selected = ([row for row in native_rows if (row['task_id'] in initial_tasks) == (phase == 'native-initial')]
                    if native else [row for row in model_rows if row['phase'] == phase])
        for task in dict.fromkeys(row['task_id'] for row in selected):
            number = len(experiments) + 1
            group = []
            for row in selected:
                if row['task_id'] != task:
                    continue
                item = {'experiment_number': number, 'trial_number': len(rows) + 1,
                    'plan_entry_id': row['plan_entry_id'], 'phase': phase, 'task_id': task,
                    'kind': 'native_control' if native else 'model_trial',
                    'variant': int(row['variant']), 'block': None if native else row['block'],
                    'class_id': tasks[task]['class_id'] if task in tasks else {'training-hero': 'hero', 'training-bowmaster': 'bowmaster',
                        'training-ice-lightning': 'ice_lightning_arch_mage'}[task],
                    'level': tasks[task]['level'] if task in tasks else None,
                    'planned_parameters': (copy.deepcopy(design['short_task_contract' if int(row['wall_seconds']) == 120
                        else 'extended_task_contract']) if not native and phase.startswith('skill-') else None),
                    'repetition': int(row['control'].split('-')[-1] if native else row['repetition']),
                    'model': None if native else row['model'],
                    'admission_slot': None if native else int(row['admission_slot']),
                    'planned_lane': row['worker_lane'], 'wall_seconds': int(row['wall_seconds']),
                    'max_api_requests': 0 if native else int(row['max_api_requests']),
                    'token_ceiling': 0 if native else int(row['token_ceiling']),
                    'control': row['control'] if native else None,
                    'expected_positive': row['expected'] == 'True' if native else None,
                    'design_admission': row['execution_status'], 'design_fixture_binding': row['fixture_binding']}
                rows.append(item); group.append(item['plan_entry_id'])
            experiments.append({'experiment_number': number, 'phase': phase, 'task_id': task,
                'label': TASK_LABELS[task], 'planned': len(group), 'kind': 'native_control' if native else 'model_trial',
                'path': f'skill-suite/{phase}/{task}.json'})
    require(len(rows) == 852 and len({r['plan_entry_id'] for r in rows}) == 852
            and len(experiments) == 21, 'suite_denominator_changed')
    return {'design': design, 'rows': rows, 'experiments': experiments, 'tasks': tasks}


def timestamp(value, nullable=False):
    if value is None and nullable:
        return None
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z', value),
            'actual_utc_timestamp_required')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ProgressError('invalid_utc_timestamp') from exc


def hashes(values, maximum=32):
    require(isinstance(values, list) and len(values) <= maximum
            and all(isinstance(x, str) and SHA.fullmatch(x) for x in values)
            and len(set(values)) == len(values), 'invalid_evidence_hashes')


def public_urls(values, origins):
    require(isinstance(values, list) and len(values) <= 16 and all(isinstance(v, str) for v in values) and len(set(values)) == len(values), 'invalid_public_links')
    for value in values:
        require(isinstance(value, str) and len(value) <= 512, 'invalid_public_link')
        try:
            u = urlsplit(value); port = u.port
        except ValueError as exc:
            raise ProgressError('invalid_public_link') from exc
        require(u.scheme == 'https' and 'https://' + u.netloc in origins and not u.username
                and not u.password and port is None and not u.query and not u.fragment
                and '..' not in u.path and '%' not in u.path and '\\' not in u.path
                and not re.search(r'(?:^|/)[a-f0-9]{32}(?:/|\.|$)', u.path), 'private_or_unapproved_public_link')
        if u.hostname == 'github.com':
            require(re.fullmatch(r'/dmarzzz/maplebench/(?:pull/[1-9][0-9]*|commit/[a-f0-9]{40})', u.path), 'unapproved_repository_link')
        else:
            require(re.fullmatch(r'/skill-suite/evidence/[a-f0-9]{64}\.(?:json|webm)', u.path), 'unapproved_evidence_route')


def number(value, minimum=0, maximum=10**12, integer=False):
    return type(value) in ((int,) if integer else (int, float)) and math.isfinite(value) and minimum <= value <= maximum


def outcome(value, row, status):
    if status in ('not_started', 'in_progress', 'invalid'):
        require(value is None, 'nonterminal_or_invalid_score_forbidden')
        return
    if row['kind'] == 'native_control':
        require(value == ('passed' if status == 'success' else 'failed'), 'native_check_outcome_mismatch')
        return
    require(isinstance(value, dict), 'verified_metric_object_required')
    if row['phase'].startswith('training-'):
        require(set(value) == {'normalized_peak_xp_per_minute', 'net_xp', 'alive'}
                and number(value['normalized_peak_xp_per_minute']) and number(value['net_xp'], -10**12)
                and type(value['alive']) is bool, 'training_metric_shape')
        return
    fields = {'criterion_met', 'completion_ms', 'alive'}
    extra = {'platforming-v1': {'stable_presence_ms'},
             'native-teleport-v1': {'stable_presence_ms', 'accepted_teleports'},
             'potion-use-v1': {'items_consumed', 'mp_fraction'}}.get(row['task_id'], set())
    require(set(value) == fields | extra and type(value['criterion_met']) is bool
            and type(value['alive']) is bool and value['criterion_met'] == (status == 'success'), 'skill_metric_shape')
    if status == 'success':
        require(value['alive'] and number(value['completion_ms'], maximum=row['wall_seconds'] * 1000)
                and value['completion_ms'] < row['wall_seconds'] * 1000, 'success_outside_deadline')
    else:
        require(value['completion_ms'] is None, 'failed_completion_time_forbidden')
    for key in extra:
        require(number(value[key], maximum=1 if key == 'mp_fraction' else 10**9,
                       integer=key in ('accepted_teleports', 'items_consumed')), 'invalid_task_metric')


def _entry(value, row, manifests, origins):
    require(isinstance(value, dict) and set(value) == ENTRY_FIELDS, 'unexpected_progress_entry_fields')
    status = value['status']; require(status in STATUSES, 'invalid_progress_status')
    timestamp(value['updated_at_utc'])
    sha = value['execution_manifest_sha256']
    require((status == 'not_started' and sha is None) or sha in manifests, 'registered_execution_manifest_required')
    require(value['reason_code'] is None or value['reason_code'] in REASONS, 'unapproved_reason_code')
    if status in ('invalid', 'gameplay_failure'):
        require(value['reason_code'] is not None, 'terminal_reason_required')
    hashes(value['evidence_sha256']); public_urls(value['public_evidence_urls'], origins)
    if status in ('success', 'gameplay_failure'):
        require(value['evidence_sha256'], 'verified_outcome_evidence_required')
    outcome(value['outcome'], row, status)
    require(isinstance(value['updates'], list) and len(value['updates']) <= 64, 'progress_history_limit')
    last = None
    previous_new = None
    for event in value['updates']:
        require(isinstance(event, dict) and set(event) == UPDATE_FIELDS, 'invalid_progress_history_fields')
        at = timestamp(event['updated_at_utc'])
        require((last is None or last <= at) and at <= timestamp(value['updated_at_utc']), 'progress_history_time_order')
        require(event['previous_status'] is None or event['previous_status'] in STATUSES, 'invalid_previous_status')
        require(event['new_status'] in STATUSES and event['reason_code'] in REASONS, 'invalid_progress_history_status')
        previous = event['previous_status']
        require(last is None or previous == previous_new, 'progress_history_status_chain')
        previous_new = event['new_status']
        require(event['previous_execution_manifest_sha256'] is None
                or event['previous_execution_manifest_sha256'] in manifests, 'previous_manifest_missing')
        outcome(event['previous_outcome'], row, previous or 'not_started')
        hashes(event['previous_evidence_sha256']); public_urls(event['previous_public_evidence_urls'], origins)
        last = at
    if last is not None:
        require(previous_new == status and last == timestamp(value['updated_at_utc']), 'progress_history_current_mismatch')


def phase_counts(plan, entries):
    counts = {phase: {'planned': sum(row['phase'] == phase for row in plan['rows']),
        'reported_terminal': 0, 'success': 0, 'gameplay_failure': 0, 'invalid': 0, 'in_progress': 0} for phase in PHASES}
    lookup = {row['plan_entry_id']: row for row in plan['rows']}
    for key, entry in entries.items():
        count = counts[lookup[key]['phase']]; status = entry['status']
        if status != 'not_started': count[status] += 1
        count['reported_terminal'] += status in TERMINAL
    return counts


def validate_progress(progress, plan, *, public_origins=('https://maplebench.vercel.app', 'https://github.com')):
    require(isinstance(progress, dict) and set(progress) == {'schema_version', 'design_id', 'status',
        'last_updated_at_utc', 'reporting_note', 'execution_manifests', 'phase_counts', 'entries', 'blockers', 'next_action'},
        'unexpected_progress_fields')
    require(type(progress['schema_version']) is int and progress['schema_version'] == 1
            and progress['design_id'] == DESIGN, 'progress_design_mismatch')
    require(progress['status'] in {'qualification_pending', 'qualification_in_progress', 'execution_in_progress',
            'blocked', 'complete', 'paused'}, 'unapproved_suite_status')
    timestamp(progress['last_updated_at_utc'], nullable=True)
    manifests = progress['execution_manifests']; hashes(manifests, maximum=852)
    entries = progress['entries']; lookup = {row['plan_entry_id']: row for row in plan['rows']}
    require(isinstance(entries, dict) and set(entries) <= set(lookup), 'unknown_plan_entry')
    for key, value in entries.items():
        _entry(value, lookup[key], manifests, public_origins)
        require(progress['last_updated_at_utc'] is not None
                and timestamp(value['updated_at_utc']) <= timestamp(progress['last_updated_at_utc']), 'entry_newer_than_report')
    require(progress['phase_counts'] == phase_counts(plan, entries), 'derived_phase_counts_mismatch')
    require(isinstance(progress['blockers'], list) and len(progress['blockers']) <= 32
            and all(isinstance(x, str) and x in REASONS for x in progress['blockers']), 'unapproved_blocker_code')
    # These human notes stay in the repository report, never the public projection.
    for key in ('reporting_note', 'next_action'):
        require(isinstance(progress[key], str) and len(progress[key]) <= 1000, 'report_note_limit')
    return progress


def upsert_progress(progress, plan, plan_entry_id, entry, *, public_origins=('https://maplebench.vercel.app', 'https://github.com')):
    """Pure update, preserving the prior outcome/evidence in an explicit audit event.

    Reconcile the durable runtime journal before calling. Register real manifest
    hashes first; neither this function nor the Markdown table admits an attempt.
    """
    validate_progress(progress, plan, public_origins=public_origins)
    require(plan_entry_id in {r['plan_entry_id'] for r in plan['rows']}, 'unknown_plan_entry')
    require(isinstance(entry, dict) and set(entry) == ENTRY_FIELDS - {'updates'}, 'unexpected_upsert_fields')
    result = copy.deepcopy(progress); previous = result['entries'].get(plan_entry_id)
    require(entry['reason_code'] in REASONS, 'update_reason_required')
    if previous:
        require(timestamp(entry['updated_at_utc']) >= timestamp(previous['updated_at_utc']), 'report_timestamp_regressed')
    event = {'updated_at_utc': entry['updated_at_utc'], 'previous_status': previous['status'] if previous else None,
        'new_status': entry['status'], 'reason_code': entry['reason_code'],
        'previous_outcome': previous['outcome'] if previous else None,
        'previous_execution_manifest_sha256': previous['execution_manifest_sha256'] if previous else None,
        'previous_evidence_sha256': previous['evidence_sha256'] if previous else [],
        'previous_public_evidence_urls': previous['public_evidence_urls'] if previous else []}
    result['entries'][plan_entry_id] = copy.deepcopy(entry) | {'updates': (previous['updates'] if previous else []) + [event]}
    result['last_updated_at_utc'] = max(filter(None, [result['last_updated_at_utc'], entry['updated_at_utc']]), key=timestamp)
    result['phase_counts'] = phase_counts(plan, result['entries'])
    return validate_progress(result, plan, public_origins=public_origins)


def summarize(rows):
    count = {'planned': len(rows), 'reported': 0, 'not_started': 0, 'unreported': 0,
             'in_progress': 0, 'success': 0, 'gameplay_failure': 0, 'invalid': 0}
    for row in rows:
        count['reported'] += row['reported']
        count[row['status'] if row['reported'] else 'unreported'] += 1
    count['terminal'] = sum(count[k] for k in TERMINAL)
    count['evaluable'] = count['success'] + count['gameplay_failure']
    # Rates are absent at zero coverage, never fabricated zero scores.
    count['success_rate'] = (count['success'] / count['evaluable'] if count['evaluable']
        and all(r['kind'] == 'model_trial' and r['phase'].startswith('skill-') for r in rows) else None)
    count['coverage'] = count['evaluable'] / count['planned'] if count['planned'] else None
    count['final'] = count['terminal'] == count['planned']
    return count


def project(progress, plan=None, *, public_origins=('https://maplebench.vercel.app', 'https://github.com')):
    plan = plan or load_plan(); validate_progress(progress, plan, public_origins=public_origins)
    rows = []
    for planned in plan['rows']:
        entry = progress['entries'].get(planned['plan_entry_id'])
        row = dict(planned, reported=entry is not None, status=entry['status'] if entry else 'not_started',
            configuration_status='execution_manifest_recorded' if entry and entry['execution_manifest_sha256'] else 'unbound',
            execution_manifest_sha256=entry['execution_manifest_sha256'] if entry else None,
            updated_at_utc=entry['updated_at_utc'] if entry else None,
            outcome=copy.deepcopy(entry['outcome']) if entry else None,
            reason_code=entry['reason_code'] if entry else None,
            evidence_sha256=list(entry['evidence_sha256']) if entry else [],
            public_evidence_urls=list(entry['public_evidence_urls']) if entry else [],
            updates=copy.deepcopy(entry['updates']) if entry else [])
        rows.append(row)
    shards = {}
    experiments = []
    for experiment in plan['experiments']:
        entries = [r for r in rows if r['experiment_number'] == experiment['experiment_number']]
        require(len(entries) <= 96, 'task_shard_limit')
        shard = {'schema_version': 1, 'protocol': PROTOCOL, 'design_id': DESIGN,
                 'experiment': experiment, 'summary': summarize(entries), 'entries': entries}
        raw = encoded(shard); shards[experiment['path']] = raw
        cells = [] if experiment['kind'] == 'native_control' else [
            {'model': model, 'summary': summarize([r for r in entries if r['model'] == model])}
            for model in plan['design']['models']]
        experiments.append(experiment | {'summary': summarize(entries), 'model_cells': cells, 'sha256': digest(raw), 'bytes': len(raw)})
    manifests = {'schema_version': 1, 'protocol': PROTOCOL, 'design_id': DESIGN,
        'design_status': plan['design']['status'], 'design_execution_enabled': False,
        'status': progress['status'], 'last_updated_at_utc': progress['last_updated_at_utc'],
        'reporting_note': PUBLIC_NOTE, 'source_sha256': dict(PLAN_FILES),
        'progress_sha256': digest(encoded(progress)), 'execution_manifests': list(progress['execution_manifests']),
        'blockers': list(progress['blockers']), 'planned_entries': 852,
        'reported_entries': len(progress['entries']), 'models': list(plan['design']['models']),
        'phases': [{'id': phase, 'label': PHASE_LABELS[phase],
                    'summary': summarize([r for r in rows if r['phase'] == phase])} for phase in PHASES],
        'experiments': experiments, 'overall_score': None}
    return {'manifest': manifests, 'shards': shards}


def render_markdown(projection):
    """One complete GitHub table; stable numbers match the website and shards."""
    manifest = projection['manifest']
    lines = ['# Skill suite execution progress', '', f'Design: `{DESIGN}`. Reporter: `{PROTOCOL}`.', '',
        PUBLIC_NOTE, '', f'**{manifest["reported_entries"]} reported / 852 planned entries.**', '',
        '| Experiment | Phase / task | Terminal / planned | Positive or passed | Gameplay or check failure | Invalid | In progress |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for e in manifest['experiments']:
        c = e['summary']
        lines.append(f'| E{e["experiment_number"]:03d} | {e["phase"]} / {e["label"]} | {c["terminal"]}/{c["planned"]} | {c["success"]} | {c["gameplay_failure"]} | {c["invalid"]} | {c["in_progress"]} |')
    lines += ['', 'A planned lane is an assignment, not a claim that a worker exists. '
              'A recorded execution-manifest hash is not admission authorization.', '',
              '| Experiment / trial | Plan entry | Variant / repeat | Model or control | Slot / planned lane | Wall / API / tokens | Status | Execution manifest | Outcome |',
              '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for e in manifest['experiments']:
        for r in decode(projection['shards'][e['path']])['entries']:
            status = 'unreported' if not r['reported'] else ('native_check_' + r['outcome'] if r['kind'] == 'native_control' and r['status'] in ('success', 'gameplay_failure') else r['status'])
            result = '—' if r['outcome'] is None else json.dumps(r['outcome'], sort_keys=True)
            sha = f'`{r["execution_manifest_sha256"]}`' if r['execution_manifest_sha256'] else 'Unbound'
            lines.append(f'| E{r["experiment_number"]:03d} / T{r["trial_number"]:04d} | `{r["plan_entry_id"]}` | {r["variant"]} / {r["repetition"]} | {r["model"] or r["control"]} | {r["admission_slot"] or "—"} / {r["planned_lane"]} | {r["wall_seconds"]}s / {r["max_api_requests"]} / {r["token_ceiling"]:,} | {status} | {sha} | {result} |')
    return '\n'.join(lines) + '\n'


def verify_publication(files):
    """Recompute every public field from the frozen schedules and strict entries.

    Hashing alone does not make an arbitrary JSON payload safe. Unknown fields,
    forged summaries, missing entries and substituted settings all fail closed.
    """
    require(isinstance(files, dict) and len(files) == 22 and all(
        isinstance(name, str) and PUBLIC_PATH.fullmatch(name) and isinstance(raw, bytes)
        and 0 < len(raw) <= MAX_JSON for name, raw in files.items())
        and sum(map(len, files.values())) <= MAX_BUNDLE, 'invalid_skill_publication_files')
    require('skill-suite-manifest.json' in files, 'skill_manifest_required')
    manifest = decode(files['skill-suite-manifest.json']); plan = load_plan()
    require(isinstance(manifest, dict) and isinstance(manifest.get('progress_sha256'), str)
            and SHA.fullmatch(manifest['progress_sha256']), 'skill_manifest_required')
    required_paths = {e['path'] for e in plan['experiments']}
    require(set(files) == required_paths | {'skill-suite-manifest.json'}, 'skill_shard_set_mismatch')
    entries = {}
    for path in required_paths:
        shard = decode(files[path])
        require(isinstance(shard, dict) and isinstance(shard.get('entries'), list)
                and len(shard['entries']) <= 96, 'invalid_task_shard')
        for row in shard['entries']:
            require(isinstance(row, dict) and type(row.get('reported')) is bool
                    and isinstance(row.get('plan_entry_id'), str), 'invalid_public_entry')
            if row['reported']:
                key = row['plan_entry_id']
                require(key not in entries and ENTRY_FIELDS <= set(row), 'duplicate_or_invalid_public_entry')
                entries[key] = {field: row[field] for field in ENTRY_FIELDS}
    require({'status', 'last_updated_at_utc', 'execution_manifests', 'blockers'} <= set(manifest), 'skill_manifest_required')
    progress = {'schema_version': 1, 'design_id': DESIGN, 'reporting_note': '', 'next_action': '',
        **{key: manifest[key] for key in ('status', 'last_updated_at_utc', 'execution_manifests', 'blockers')},
        'entries': entries}
    # Unknown plan IDs must fail before deriving phase counts.
    require(set(entries) <= {r['plan_entry_id'] for r in plan['rows']}, 'unknown_plan_entry')
    progress['phase_counts'] = phase_counts(plan, entries)
    expected = project(progress, plan)
    # This opaque hash binds the private/source report including omitted prose;
    # all public data and structure are independently recomputed above.
    expected['manifest']['progress_sha256'] = manifest['progress_sha256']
    require(encoded(expected['manifest']) == files['skill-suite-manifest.json']
            and expected['shards'] == {k: v for k, v in files.items() if k != 'skill-suite-manifest.json'},
            'skill_public_projection_mismatch')
    return manifest


def publication_files(projection):
    files = dict(projection['shards']) | {'skill-suite-manifest.json': encoded(projection['manifest'])}
    verify_publication(files)
    return files


def write_publication(projection, output):
    """Create an immutable JSON-only bundle. No old payload or recording is touched."""
    files = publication_files(projection)
    require(len(files) == 22 and sum(len(raw) for raw in files.values()) <= MAX_BUNDLE, 'skill_publication_limit')
    for path, raw in files.items():
        require(PUBLIC_PATH.fullmatch(path) and len(raw) <= MAX_JSON, 'invalid_skill_publication_file')
    output = Path(output)
    require(not os.path.lexists(output), 'skill_publication_create_only')
    output.mkdir(mode=0o755)
    for path, raw in sorted(files.items()):
        target = output / path; target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    inventory = {name: {'sha256': digest(raw), 'bytes': len(raw)} for name, raw in sorted(files.items())}
    return {'protocol': PROTOCOL, 'files': inventory, 'content_sha256': digest(encoded(inventory)),
            'api_calls': 0, 'runtime_actions': 0, 'deployment_performed': False}


def attach_progress(catalog, projection, output_root):
    """Attach/replace only this versioned report in a fresh immutable catalog.

    Existing result, video and cohort bytes are preserved. Publish UI through the
    existing presentation workflow before calling this function. Old deployment
    intents are never copied or reset. No deployment is performed here.
    """
    from full_client_catalog import copy_file
    from full_client_dashboard import Reader
    from full_client_gallery import directory
    from full_client_publication import verify_package, write_new
    from full_client_trial import publish_attempt
    from full_client_vercel import checked_payload, MAX_PAYLOAD
    additions = publication_files(projection)
    original = directory(Path(catalog['site']))
    primary = verify_package(Path(catalog['primary_package']), catalog['primary_content_sha256'])
    files, _ = checked_payload(original, Path(catalog['inventory']), catalog['inventory_sha256'], primary)
    planned = {**files, **{name: {'sha256': digest(raw), 'bytes': len(raw)} for name, raw in additions.items()}}
    require(len(planned) <= 100 and sum(v['bytes'] for v in planned.values()) <= MAX_PAYLOAD,
            'skill_progress_payload_capacity')
    output_root = directory(Path(output_root))
    require(not output_root.is_relative_to(original) and not original.is_relative_to(output_root), 'skill_output_overlap')
    stage = Path(tempfile.mkdtemp(prefix='.skill-progress-', dir=output_root))
    try:
        site = stage / 'site'; site.mkdir(mode=0o755)
        for name, pin in files.items():
            if name not in additions:
                copy_file(original, name, site / name, pin)
        for name, raw in additions.items():
            (site / name).parent.mkdir(parents=True, exist_ok=True)
            write_new(site / name, raw, 0o644)
        package = stage / 'publication-package'; package.mkdir(mode=0o700)
        shutil.copytree(Path(catalog['primary_package']) / 'site', package / 'site')
        content = {**primary['content'], 'presentation_parent_sha256': catalog['primary_content_sha256'],
                   'skill_progress_payload_sha256': digest(encoded(planned))}
        for field in ('skill_preview_payload_sha256', 'environment_checks_payload_sha256'):
            if field in content:
                content[field] = digest(encoded(planned))
        content_sha = digest(encoded(content))
        bound = {'schema_version': 1, 'content_sha256': content_sha, 'content': content}
        write_new(package / 'package-manifest.json', encoded(bound)); verify_package(package, content_sha)
        inventory_path = Path(catalog['inventory'])
        inventory = Reader().json(inventory_path.parent, inventory_path.name, catalog['inventory_sha256'])
        if 'cohort_manifests' in inventory:
            inventory['cohort_manifests'] = [bound if item['content']['target_path'] == primary['content']['target_path']
                                           else item for item in inventory['cohort_manifests']]
        inventory_raw = encoded({**inventory, 'files': planned})
        write_new(stage / 'payload-inventory.json', inventory_raw)
        checked_payload(site, stage / 'payload-inventory.json', digest(inventory_raw), bound)
        identity = digest(encoded({'parent_inventory_sha256': catalog['inventory_sha256'], 'files': planned}))
        destination = output_root / identity
        require(not os.path.lexists(destination), 'skill_progress_package_exists')
        receipt = {**catalog, 'directory': str(destination), 'site': str(destination / 'site'),
            'inventory': str(destination / 'payload-inventory.json'), 'inventory_sha256': digest(inventory_raw),
            'catalog_sha256': identity, 'primary_package': str(destination / 'publication-package'),
            'primary_content_sha256': content_sha, 'skill_progress_protocol': PROTOCOL,
            'api_requests': 0, 'deployment_performed': False}
        write_new(stage / 'skill-progress-publication.json', encoded(receipt))
        publish_attempt(stage, destination)
        return receipt
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-directory', type=Path)
    parser.add_argument('--progress', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--markdown', type=Path)
    args = parser.parse_args()
    projection = project(decode(args.progress.read_bytes()), load_plan(args.plan_directory))
    receipt = write_publication(projection, args.output)
    if args.markdown:
        with args.markdown.open('x') as stream:
            stream.write(render_markdown(projection))
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
