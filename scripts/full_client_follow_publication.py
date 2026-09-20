#!/usr/bin/env python3
"""Finite publication follow-up. Trusted operator commands; no game control.

The observer and exporter are explicitly reviewed, hash-pinned local programs.
Their configuration may contain private transport details; none are embedded here.
An interrupted export is reconciled only from its exact durable receipt. The
existing catalog and Vercel driver retain all package and submission authority.
"""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time

import full_client_catalog as catalog
import full_client_vercel as vercel
from full_client_dashboard import Reader, write_snapshot
from full_client_publication import (digest, encoded, require, stable_bytes,
    stable_fingerprint, verify_package, publication_state, write_new)
from full_client_score import parse_json

PROTOCOL = 'finite-publication-follow-v1'
MODELS = ('gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna')
ID = re.compile(r'[a-f0-9]{32}\Z')
SHA = re.compile(r'[a-f0-9]{64}\Z')
TERMINAL = {'completed', 'failed', 'interrupted', 'recovered', 'withdrawn', 'unknown'}
STATUSES = TERMINAL | {'pending', 'running', 'recovering'}
POLL_SECONDS = 5
MAX_PUBLICATIONS = 9
MAX_OUTPUT = 2 * 1024**2
MAX_JSON = 4 * 1024**2


def private_directory(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path, 'follow_canonical_directory_required')
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700, 'follow_private_directory_required')
    return path


def reference(path):
    path = Path(path)
    return {'path': str(path), 'sha256': digest(stable_bytes(path, MAX_JSON))}


def pinned(ref, *, maximum=MAX_JSON, private=True):
    require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}
            and isinstance(ref['path'], str) and isinstance(ref['sha256'], str)
            and SHA.fullmatch(ref['sha256']), 'follow_reference_required')
    path = Path(ref['path']); raw = stable_bytes(path, maximum)
    info = path.lstat()
    require(info.st_uid in (0, os.geteuid()) and not info.st_mode & (0o077 if private else 0o022)
            and digest(raw) == ref['sha256'], 'follow_pinned_bytes_changed')
    if private: private_directory(path.parent)
    return raw


def pinned_json(ref):
    value = parse_json(pinned(ref))
    require(isinstance(value, dict), 'follow_json_object_required')
    return value


def save(path, value):
    raw = encoded(value); require(len(raw) <= MAX_JSON, 'follow_receipt_size_limit')
    write_new(path, raw)
    return reference(path)


def save_once(path, value):
    if path.exists(): require(pinned_json(reference(path)) == value, 'follow_existing_receipt_changed')
    else: save(path, value)
    return reference(path)


def checked_command(value):
    require(isinstance(value, dict) and set(value) == {'argv', 'dependencies'}, 'follow_command_required')
    argv, deps = value['argv'], value['dependencies']
    require(isinstance(argv, list) and 1 <= len(argv) <= 32
            and all(isinstance(arg, str) and 0 < len(arg) <= 4096 and '\0' not in arg for arg in argv)
            and sum(map(len, argv)) <= 32768 and Path(argv[0]).is_absolute()
            and Path(argv[0]).name not in ('sh', 'bash', 'dash', 'zsh', 'fish', 'ksh')
            and not any(arg in ('-c', '-e', '--eval') for arg in argv), 'follow_no_shell_or_inline_program')
    require(isinstance(deps, list) and 1 <= len(deps) <= 16
            and len({row['path'] for row in deps}) == len(deps)
            and argv[0] in {row['path'] for row in deps}, 'follow_command_dependencies_required')
    for ref in deps: pinned(ref, maximum=32 * 1024**2, private=False)
    require(os.access(argv[0], os.X_OK), 'follow_command_not_executable')
    # All absolute file arguments must be included in the reviewed dependency set.
    declared = {row['path'] for row in deps}
    require(all(not Path(arg).is_absolute() or arg in declared for arg in argv),
            'follow_unpinned_command_argument')
    return argv


def command(value, extra, deadline):
    """Bound process group and output. Raw stdout/stderr never enter status logs."""
    argv = checked_command(value)
    return process_output([*argv, *extra], deadline)


def process_output(argv, deadline):
    """Only pinned external roles or fixed source-owned catalog/driver argv enter."""
    require(time.monotonic() < deadline, 'follow_deadline')
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
            stdout=out, stderr=err, shell=False, start_new_session=True)
        try:
            while process.poll() is None:
                require(time.monotonic() < deadline, 'follow_command_timeout')
                require(os.fstat(out.fileno()).st_size <= MAX_OUTPUT
                        and os.fstat(err.fileno()).st_size <= MAX_OUTPUT, 'follow_command_output_limit')
                time.sleep(min(.05, max(0, deadline-time.monotonic())))
            require(process.returncode == 0, 'follow_command_reply_unavailable')
            require(os.fstat(out.fileno()).st_size <= MAX_OUTPUT
                    and os.fstat(err.fileno()).st_size <= MAX_OUTPUT, 'follow_command_output_limit')
            out.seek(0); return out.read(MAX_OUTPUT+1)
        finally:
            if process.poll() is None:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait(timeout=5)


def source_identity(value):
    require(isinstance(value, dict) and set(value) == {'path', 'commit'}
            and isinstance(value['commit'], str) and re.fullmatch('[a-f0-9]{40}', value['commit']),
            'follow_source_required')
    root = Path(value['path'])
    require(root.resolve(strict=True) == root and Path(__file__).resolve().parents[1] == root,
            'follow_source_root_changed')
    require(subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], timeout=10,
            stderr=subprocess.DEVNULL, text=True).strip() == value['commit'], 'follow_source_commit_changed')
    require(not subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no'],
            timeout=10, stderr=subprocess.DEVNULL), 'follow_source_dirty')


def checked_config(value):
    require(isinstance(value, dict) and set(value) == {'schema_version', 'protocol', 'cohort', 'source',
            'observer', 'exporter', 'catalog', 'publication', 'seed', 'bounds'}
            and type(value['schema_version']) is int and value['schema_version'] == 1
            and value['protocol'] == PROTOCOL, 'follow_config_schema')
    group = value['cohort']
    require(isinstance(group, dict) and set(group) == {'plan', 'runtime_manifest_sha256', 'class_id', 'attempts'}
            and group['class_id'] in catalog.CLASSES and isinstance(group['plan'], dict)
            and set(group['plan']) == {'path', 'sha256'} and Path(group['plan']['path']).is_absolute()
            and SHA.fullmatch(group['plan']['sha256']) and SHA.fullmatch(group['runtime_manifest_sha256']),
            'follow_cohort_pins_required')
    entries = group['attempts']
    require(isinstance(entries, list) and len(entries) == 4
            and all(isinstance(row, dict) and set(row) == {'id', 'model'} and ID.fullmatch(row['id']) for row in entries)
            and len({row['id'] for row in entries}) == 4
            and tuple(row['model'] for row in entries) == MODELS, 'follow_exact_four_models_required')
    bounds = value['bounds']
    require(isinstance(bounds, dict) and set(bounds) <= {'watch_seconds'}
            and type(bounds.get('watch_seconds', 3600)) is int
            and 5 <= bounds.get('watch_seconds', 3600) <= 7200, 'follow_finite_deadline_required')
    checked_command(value['observer'])
    exporter = value['exporter']
    require(isinstance(exporter, dict) and set(exporter) == {'command', 'config', 'receipt_root', 'completion_prefix'},
            'follow_exporter_contract_required')
    argv = checked_command(exporter['command']); exported = pinned_json(exporter['config'])
    private_directory(exporter['receipt_root'])
    require(re.fullmatch('[A-Za-z0-9_-]{1,64}', exporter['completion_prefix'])
            and exported.get('plan') == group['plan'] and exported.get('class_id') == group['class_id']
            and exported.get('attempt_ids') == [row['id'] for row in entries]
            and '--attempt-id' not in argv and '--snapshot' not in argv
            and argv[-4:] == ['--config', exporter['config']['path'], '--config-sha256', exporter['config']['sha256']]
            and exporter['config'] in exporter['command']['dependencies'], 'follow_export_config_changed')
    base = value['catalog']
    require(isinstance(base, dict) and set(base)-{'annotations'} == {'cohorts', 'previous_cohorts', 'archive', 'output_root'}
            and isinstance(base['cohorts'], list) and len(base['cohorts']) <= 3
            and isinstance(base['previous_cohorts'], list) and len(base['previous_cohorts']) <= 3,
            'follow_catalog_base_required')
    require(isinstance(base.get('annotations', []), list) and len(base.get('annotations', [])) <= 6
            and all(isinstance(note, dict) and set(note) == {'plan_sha256', 'text'}
                    and isinstance(note['plan_sha256'], str) and SHA.fullmatch(note['plan_sha256'])
                    and isinstance(note['text'], str) and 1 <= len(note['text']) <= 400
                    for note in base.get('annotations', [])), 'follow_catalog_annotations_required')
    private_directory(base['output_root'])
    pub = value['publication']
    require(isinstance(pub, dict) and set(pub) == {'project_link', 'public_origin', 'executable'},
            'follow_publication_binding_required')
    vercel.project_link(pub['project_link']['path'], pub['project_link']['sha256'])
    vercel.origin(pub['public_origin']); pinned(pub['executable'], maximum=32*1024**2, private=False)
    require(os.access(pub['executable']['path'], os.X_OK), 'follow_vercel_executable_required')
    return value


def checked_observation(value, config):
    group = config['cohort']
    require(isinstance(value, dict) and set(value) == {'schema_version', 'plan_sha256',
            'runtime_manifest_sha256', 'class_id', 'cohort_terminal', 'attempts'}
            and type(value['schema_version']) is int and value['schema_version'] == 1
            and value['plan_sha256'] == group['plan']['sha256']
            and value['runtime_manifest_sha256'] == group['runtime_manifest_sha256']
            and value['class_id'] == group['class_id'] and type(value['cohort_terminal']) is bool
            and isinstance(value['attempts'], list) and len(value['attempts']) == 4,
            'follow_observer_binding_changed')
    for row, expected in zip(value['attempts'], group['attempts']):
        require(isinstance(row, dict) and set(row) == {'id', 'model', 'status', 'journal_sha256', 'completed_at_ms'}
                and all(row[key] == expected[key] for key in ('id', 'model')) and row['status'] in STATUSES,
                'follow_observer_attempt_changed')
        require(row['journal_sha256'] is None and row['status'] in ('pending', 'withdrawn')
                or isinstance(row['journal_sha256'], str) and SHA.fullmatch(row['journal_sha256']),
                'follow_observer_journal_required')
        require((type(row['completed_at_ms']) is int and row['completed_at_ms'] > 0) if row['status'] == 'completed'
                else row['completed_at_ms'] is None, 'follow_completion_clock_required')
    require(not value['cohort_terminal'] or all(row['status'] in TERMINAL for row in value['attempts']),
            'follow_false_terminal_cohort')
    return value


def signature(observation):
    return digest(encoded([{'id': row['id'], 'status': row['status'] if row['status'] in TERMINAL else 'pending',
                           'journal_sha256': row['journal_sha256'] if row['status'] in TERMINAL else None}
                          for row in observation['attempts']]))


def matching_public_outcomes(observed, rows):
    aliases = {'pending': {'not_started'}, 'withdrawn': {'not_started'},
               'unknown': {'unavailable'}, 'running': {'running', 'requesting'}}
    require(len(rows) == len(observed['attempts']) and all(
        actual['id'] == wanted['id'] and actual['requested_model'] == wanted['model']
        and actual['status'] in aliases.get(wanted['status'], {wanted['status']})
        for actual, wanted in zip(rows, observed['attempts'])), 'follow_seed_outcomes_changed')


def exported_receipt(ref, config, anchor):
    exporter = config['exporter']; path = Path(ref['path'])
    require(path.parent == Path(exporter['receipt_root']), 'follow_export_receipt_outside_root')
    receipt = pinned_json(ref); group = config['cohort']; selected = pinned_json(exporter['config'])
    require(receipt.get('status') == 'completed_model_public_package_verified_not_deployed'
            and receipt.get('export_config_sha256') == exporter['config']['sha256']
            and receipt.get('verification_source') == selected['verification_source']
            and receipt.get('release_root') == selected['release_root']
            and receipt.get('class_id') == group['class_id'] and receipt.get('plan_sha256') == group['plan']['sha256']
            and receipt.get('attempt_id') == anchor['id'] and receipt.get('model') == anchor['model']
            and receipt.get('journal_sha256') == anchor['journal_sha256']
            and type(receipt.get('api_calls')) is int and receipt['api_calls'] == 0
            and type(receipt.get('deployments')) is int and receipt['deployments'] == 0,
            'follow_export_receipt_changed')
    package = catalog.cohort(receipt['package'], receipt['content_sha256'])
    require(package['manifest']['content']['plan_sha256'] == group['plan']['sha256']
            and package['class_id'] == group['class_id']
            and [row['id'] for row in package['snapshot']['attempts']] == [row['id'] for row in group['attempts']],
            'follow_export_package_changed')
    row = next(row for row in package['snapshot']['attempts'] if row['id'] == anchor['id'])
    require(catalog.verified(row) and row['recording_publication'] == 'verified_bytes',
            'follow_anchor_not_verified')
    backup_ref = {'path': receipt['backup_receipt'], 'sha256': receipt['backup_receipt_sha256']}
    backup = pinned_json(backup_ref)
    journals = [value for name, value in backup.get('files', {}).items()
                if Path(name).parts[-3:] == ('attempts', anchor['id'], 'journal.json')]
    require(backup.get('status') == 'verified_private_completed_attempt_backup'
            and backup.get('plan_sha256') == group['plan']['sha256'] and len(journals) == 1
            and journals[0]['sha256'] == anchor['journal_sha256'], 'follow_backup_receipt_changed')
    archive = Path(backup_ref['path']).parent/'evidence.tar'
    require(stable_fingerprint(archive, 194*1024**2) == {'bytes': backup['archive_bytes'],
            'sha256': backup['archive_sha256']}, 'follow_backup_archive_changed')
    return receipt, package


def publication_proof(package, content, config, composed):
    package = Path(package); manifest = verify_package(package, content)
    require(publication_state(package, content) == 'published', 'follow_publication_not_verified')
    done = Reader().json(package, 'publication-complete.json')
    proof = Reader().json(package, 'vercel-public-verification.json')
    pub = config['publication']; link = vercel.project_link(pub['project_link']['path'], pub['project_link']['sha256'])
    require(proof.get('content_sha256') == content and proof.get('project') == link
            and proof.get('public_origin') == vercel.origin(pub['public_origin'])
            and proof.get('deployment_id') == done.get('deployment_id')
            and done.get('url') == pub['public_origin'].rstrip('/')+manifest['content']['target_path']
            and type(proof.get('published_at_ms')) is int and type(proof.get('validated_at_ms')) is int
            and type(proof.get('latency_ms')) is int and proof['published_at_ms']-proof['validated_at_ms'] == proof['latency_ms'] >= 0
            and proof.get('target_latency_ms') == 60000 and type(proof.get('model_api_requests')) is int
            and proof['model_api_requests'] == 0
            and proof.get('public_verification', {}).get('anonymous_access') is True,
            'follow_publication_proof_changed')
    files, payload_sha = vercel.checked_payload(Path(composed['site']), Path(composed['inventory']),
        composed['inventory_sha256'], manifest)
    expected = [{'path': name, **value} for name, value in files.items()
                if Path(name).name not in ('vercel.json', 'README.md')]
    ranges = [{'path': name, 'status': 206, 'bytes': min(16, value['bytes']), 'total_bytes': value['bytes']}
              for name, value in files.items() if name.endswith('.webm')]
    checked = proof['public_verification']
    require(proof.get('payload_sha256') == payload_sha
            and checked.get('files') == expected and checked.get('video_ranges') == ranges,
            'follow_publication_file_proofs_changed')
    return proof


def checked_composition(value, request, output_root):
    require(isinstance(value, dict) and isinstance(value.get('catalog_sha256'), str)
            and SHA.fullmatch(value['catalog_sha256']), 'follow_catalog_reply_required')
    directory = Path(output_root)/value['catalog_sha256']
    primary = next(row for row in request['cohorts'] if row['content_sha256'] == request['primary_content_sha256'])
    require(value.get('directory') == str(directory) and value.get('site') == str(directory/'site')
            and value.get('inventory') == str(directory/'payload-inventory.json')
            and value.get('primary_package') == primary['package']
            and value.get('primary_content_sha256') == primary['content_sha256'], 'follow_catalog_paths_changed')
    manifest = Reader().json(private_directory(directory), 'catalog-manifest.json')
    content = manifest.get('content')
    require(isinstance(content, dict) and manifest.get('content_sha256') == value['catalog_sha256']
            and digest(encoded(content)) == value['catalog_sha256'] and content.get('schema_version') == 2
            and sorted(content.get('source_content_sha256', [])) == sorted(row['content_sha256'] for row in request['cohorts'])
            and content.get('previous_content_sha256') == [row['content_sha256'] for row in request['previous_cohorts']]
            and content.get('archive_inventory_sha256') == (request['archive']['inventory_sha256'] if request['archive'] else None),
            'follow_catalog_sources_changed')
    inventory = Reader().json(directory, 'payload-inventory.json', value['inventory_sha256'])
    require(inventory.get('files') == content.get('files'), 'follow_catalog_inventory_changed')
    notes = [{'plan_sha256': row['plan_sha256'], 'text': row['text']} for row in content.get('annotations', [])]
    require(sorted(notes, key=lambda row: row['plan_sha256']) ==
            sorted(request.get('annotations', []), key=lambda row: row['plan_sha256']),
            'follow_catalog_annotations_changed')
    return value


class Follow:
    def __init__(self, config, config_ref, root, *, run_command=command, compose=None,
                 publish=None, clock=time.monotonic, wall=time.time, sleep=time.sleep, ownership=lambda: None):
        self.config, self.config_ref, self.root = config, config_ref, private_directory(root)
        self.run_command, self.compose, self.publish = run_command, compose, publish
        self.clock, self.wall, self.sleep = clock, wall, sleep
        self.ownership = ownership
        self.folder = self.root/config_ref['sha256']; self.state = None

    def now(self): return round(self.wall()*1000)

    def store(self): write_snapshot(self.folder/'state.json', self.state)

    def bounded(self, seconds): return min(self.deadline, self.clock()+seconds)

    def stop(self, status, reason):
        self.state.update(status=status, reason=reason); self.store()
        return {'status': status, 'reason': reason, 'state': str(self.folder/'state.json'),
                'observations': self.state['polls'], 'publications': len(self.state['publications']),
                'model_api_requests': 0}

    def load(self):
        duration = self.config['bounds'].get('watch_seconds', 3600)
        if not self.folder.exists():
            self.folder.mkdir(mode=0o700)
            started, monotonic = self.now(), self.clock()
            intent = {'schema_version': 1, 'config': self.config_ref, 'started_at_ms': started,
                      'deadline_at_ms': started+duration*1000, 'monotonic_started': monotonic,
                      'monotonic_deadline': monotonic+duration}
            save(self.folder/'intent.json', intent)
            self.state = {'schema_version': 1, 'config': self.config_ref, 'status': 'watching', 'reason': None,
                'polls': 0, 'observed': None, 'exports': {}, 'last_signature': None, 'publications': [],
                'current': None, 'operations': [], 'latest_export': None, 'seed_imported': False, 'first_publications': {}}
            self.store()
        else:
            private_directory(self.folder)
            intent = pinned_json(reference(self.folder/'intent.json'))
            self.state = pinned_json(reference(self.folder/'state.json'))
            require(intent.get('config') == self.state.get('config') == self.config_ref
                    and type(self.state.get('polls')) is int and 0 <= self.state['polls'] <= duration//POLL_SECONDS+1
                    and isinstance(self.state.get('operations'), list) and len(self.state['operations']) <= MAX_PUBLICATIONS
                    and self.state['operations'] == ['operation-'+str(i+1).zfill(2) for i in range(len(self.state['operations']))]
                    and isinstance(self.state.get('publications'), list) and len(self.state['publications']) <= MAX_PUBLICATIONS
                    and isinstance(self.state.get('exports'), dict)
                    and set(self.state['exports']) <= {row['id'] for row in self.config['cohort']['attempts']}
                    and isinstance(self.state.get('first_publications'), dict)
                    and set(self.state['first_publications']) <= set(self.state['exports'])
                    and type(self.state.get('seed_imported')) is bool,
                    'follow_resume_state_changed')
            current = self.state.get('current')
            require(current is None or isinstance(current, dict) and set(current) == {'name', 'intent'}
                    and current['name'] in self.state['operations'], 'follow_current_operation_changed')
        require(intent['monotonic_started'] <= self.clock() and intent['started_at_ms'] <= self.now(),
                'follow_clock_or_boot_changed')
        require(0 < intent['monotonic_deadline']-intent['monotonic_started'] <= duration
                and 0 < intent['deadline_at_ms']-intent['started_at_ms'] <= duration*1000, 'follow_original_deadline_changed')
        self.deadline = min(intent['monotonic_deadline'], self.clock()+max(0, (intent['deadline_at_ms']-self.now())/1000))
        actual = {p.name for p in self.folder.iterdir() if p.name.startswith('operation-')}
        require(actual == set(self.state['operations']), 'follow_orphan_operation_requires_review')
        if not self.state['seed_imported']:
            self.import_seed(); self.state['seed_imported'] = True; self.store()

    def import_seed(self):
        seed = self.config['seed']
        if seed is None: return
        require(isinstance(seed, dict) and set(seed) == {'observation', 'exports', 'primary_export', 'publication'}, 'follow_seed_schema')
        observed = checked_observation(pinned_json(seed['observation']), self.config)
        require(isinstance(seed['exports'], list) and 1 <= len(seed['exports']) <= 4, 'follow_seed_exports_required')
        for ref in seed['exports']:
            value = pinned_json(ref); anchor = next((r for r in observed['attempts'] if r['id'] == value.get('attempt_id')), None)
            require(anchor is not None and anchor['status'] == 'completed', 'follow_seed_anchor_changed')
            exported_receipt(ref, self.config, anchor)
            require(anchor['id'] not in self.state['exports'], 'follow_seed_duplicate_attempt')
            self.state['exports'][anchor['id']] = {'receipt': ref, 'observation': anchor}
        require(seed['primary_export'] in seed['exports'], 'follow_seed_primary_required')
        primary = pinned_json(seed['primary_export'])
        saved = seed['publication']
        require(isinstance(saved, dict) and set(saved) == {'complete', 'verification', 'catalog'}, 'follow_seed_publication_required')
        for key, name in (('complete', 'publication-complete.json'), ('verification', 'vercel-public-verification.json')):
            require(saved[key]['path'] == str(Path(primary['package'])/name), 'follow_seed_publication_path_changed')
            pinned_json(saved[key])
        composed = pinned_json(saved['catalog'])
        require(composed.get('primary_package') == primary['package']
                and composed.get('primary_content_sha256') == primary['content_sha256'], 'follow_seed_catalog_changed')
        base = self.config['catalog']
        request = {'schema_version': 2, 'cohorts': [*base['cohorts'],
            {'package': primary['package'], 'content_sha256': primary['content_sha256']}],
            'previous_cohorts': base['previous_cohorts'], 'archive': base['archive'],
            'primary_content_sha256': primary['content_sha256']}
        if base.get('annotations'): request['annotations'] = base['annotations']
        checked_composition(composed, request, base['output_root'])
        proof = publication_proof(primary['package'], primary['content_sha256'], self.config, composed)
        public = catalog.cohort(primary['package'], primary['content_sha256'])['snapshot']['attempts']
        matching_public_outcomes(observed, public)
        published_ids = {row['id'] for row in public if row['status'] == 'completed'}
        require(published_ids == set(self.state['exports']), 'follow_seed_export_set_changed')
        for row in observed['attempts']:
            if row['status'] == 'completed':
                require(row['id'] in published_ids and row['completed_at_ms'] <= proof['published_at_ms'],
                        'follow_seed_completion_time_changed')
                self.state['first_publications'][row['id']] = {'published_at_ms': proof['published_at_ms'],
                    'completion_to_known_public_ms': proof['published_at_ms']-row['completed_at_ms'],
                    'timing_kind': 'seed_snapshot_upper_bound',
                    'verification': saved['verification']}
        self.state.update(observed=observed, last_signature=signature(observed), latest_export=seed['primary_export'])
        self.store()

    def observe(self):
        raw = self.run_command(self.config['observer'], [], self.bounded(15))
        require(isinstance(raw, bytes) and len(raw) <= MAX_OUTPUT, 'follow_observer_output_limit')
        observed = checked_observation(parse_json(raw), self.config)
        for key, prior in self.state['exports'].items():
            row = next(r for r in observed['attempts'] if r['id'] == key)
            require(row == prior['observation'], 'follow_completed_journal_changed')
        self.state['polls'] += 1; self.state['observed'] = observed
        self.state['last_poll_monotonic'] = self.clock(); self.store()
        return observed

    def begin(self, observed, anchor, snapshot):
        require(len(self.state['operations']) < MAX_PUBLICATIONS, 'follow_publication_limit')
        name = 'operation-'+str(len(self.state['operations'])+1).zfill(2)
        folder = self.folder/name; folder.mkdir(mode=0o700)
        intent = {'schema_version': 1, 'config': self.config_ref, 'observation': observed,
                  'anchor': anchor, 'snapshot': snapshot, 'observed_at_ms': self.now(),
                  'signature': signature(observed)}
        ref = save(folder/'intent.json', intent)
        self.state['operations'].append(name); self.state['current'] = {'name': name, 'intent': ref}
        self.store()

    def export(self, folder, intent):
        self.ownership()
        path = folder/'export.json'
        if path.exists():
            saved = pinned_json(reference(path)); exported_receipt(saved['receipt'], self.config, intent['anchor'])
            return saved
        started = folder/'export-started.json'; exporter = self.config['exporter']; anchor = intent['anchor']
        expected = Path(exporter['receipt_root'])/(exporter['completion_prefix']+anchor['id']+'.json')
        if started.exists():
            previous = pinned_json(reference(started))
            require(previous.get('config') == self.config_ref and previous.get('intent') == reference(folder/'intent.json')
                    and previous.get('expected_receipt') == (None if intent['snapshot'] else str(expected)),
                    'follow_export_intent_changed')
            require(not intent['snapshot'] and expected.exists(), 'follow_export_uncertain')
            ref = reference(expected)  # Exact known completion receipt, never a directory search.
        else:
            save(started, {'config': self.config_ref, 'intent': reference(folder/'intent.json'),
                          'at_ms': self.now(), 'expected_receipt': None if intent['snapshot'] else str(expected)})
            extra = ['--attempt-id', anchor['id']]+(['--snapshot'] if intent['snapshot'] else [])
            try:
                raw = self.run_command(exporter['command'], extra, self.bounded(720))
                require(isinstance(raw, bytes) and len(raw) <= MAX_OUTPUT, 'follow_export_output_limit')
                lines = raw.splitlines(); require(lines, 'follow_export_reply_missing')
                result = parse_json(lines[-1])
                require(isinstance(result, dict) and set(result) == {'receipt', 'receipt_sha256'}, 'follow_export_reply_missing')
                ref = {'path': result['receipt'], 'sha256': result['receipt_sha256']}
            except (ValueError, OSError, subprocess.SubprocessError):
                require(not intent['snapshot'] and expected.exists(), 'follow_export_uncertain')
                ref = reference(expected)
        value, _ = exported_receipt(ref, self.config, anchor)
        if not intent['snapshot']: require(ref['path'] == str(expected), 'follow_completion_receipt_path_changed')
        return_value = {'receipt': ref, 'content_sha256': value['content_sha256'], 'completed_at_ms': self.now()}
        save(path, return_value); return return_value

    def operate(self):
        current = self.state['current']; folder = private_directory(self.folder/current['name'])
        intent = pinned_json(current['intent'])
        require(current['intent']['path'] == str(folder/'intent.json') and intent['config'] == self.config_ref,
                'follow_operation_intent_changed')
        checked_observation(intent['observation'], self.config)
        self.state['status'] = 'exporting'; self.store()
        exported = self.export(folder, intent); ref = exported['receipt']
        value, package = exported_receipt(ref, self.config, intent['anchor'])
        if not intent['snapshot']:
            self.state['exports'][intent['anchor']['id']] = {'receipt': ref, 'observation': intent['anchor']}
        self.state['latest_export'] = ref; self.store()
        completed = {r['id'] for r in package['snapshot']['attempts'] if r['status'] == 'completed'}
        if not completed <= set(self.state['exports']):
            save_once(folder/'deferred.json', {'reason': 'completed_member_backup_required', 'content_sha256': value['content_sha256']})
            self.state['current'] = None; self.store(); return
        for key in completed:
            prior = self.state['exports'][key]; exported_receipt(prior['receipt'], self.config, prior['observation'])
        request_path = folder/'catalog-request.json'
        base = self.config['catalog']
        request = {'schema_version': 2, 'cohorts': [*base['cohorts'], {'package': value['package'], 'content_sha256': value['content_sha256']}],
                   'previous_cohorts': base['previous_cohorts'], 'archive': base['archive'],
                   'primary_content_sha256': value['content_sha256']}
        if base.get('annotations'): request['annotations'] = base['annotations']
        if request_path.exists(): require(pinned_json(reference(request_path)) == request, 'follow_catalog_request_changed')
        else: save(request_path, request)
        composed_path = folder/'catalog.json'
        self.state['status'] = 'composing'; self.store()
        source_identity(self.config['source'])
        if composed_path.exists(): composed = pinned_json(reference(composed_path))
        else:
            if self.compose is None:
                raw = process_output([str(Path(sys.executable).resolve()),
                    str(Path(__file__).resolve().with_name('full_client_catalog.py')),
                    '--request', str(request_path), '--request-sha256', reference(request_path)['sha256'],
                    '--output-root', base['output_root']], self.bounded(120))
                composed = parse_json(raw)
            else: composed = self.compose(request, Path(base['output_root']))
            save(composed_path, composed)
        checked_composition(composed, request, base['output_root'])
        pub = self.config['publication']
        marker = folder/'publication-started.json'
        if not marker.exists(): save(marker, {'intent': current['intent'], 'catalog': reference(composed_path), 'at_ms': self.now()})
        else:
            previous = pinned_json(reference(marker))
            require(previous.get('intent') == current['intent'] and previous.get('catalog') == reference(composed_path),
                    'follow_publication_intent_changed')
        require(self.clock() < self.deadline, 'follow_deadline')
        self.ownership()
        source_identity(self.config['source'])
        pinned(pub['executable'], maximum=32*1024**2, private=False)
        self.state['status'] = 'publishing'; self.store()
        timeout = max(1, min(300, math.floor(self.deadline-self.clock())))
        if self.publish is None:
            raw = process_output([str(Path(sys.executable).resolve()),
                str(Path(__file__).resolve().with_name('full_client_vercel.py')),
                '--package', composed['primary_package'], '--content-sha256', composed['primary_content_sha256'],
                '--payload', composed['site'], '--payload-inventory', composed['inventory'],
                '--payload-inventory-sha256', composed['inventory_sha256'],
                '--project-link', pub['project_link']['path'], '--project-link-sha256', pub['project_link']['sha256'],
                '--public-origin', pub['public_origin'], '--vercel-executable', pub['executable']['path'],
                '--timeout-seconds', str(timeout)], self.bounded(timeout))
            result = parse_json(raw)
        else:
            result = self.publish(Path(composed['primary_package']), composed['primary_content_sha256'], Path(composed['site']),
                Path(composed['inventory']), composed['inventory_sha256'], Path(pub['project_link']['path']),
                pub['project_link']['sha256'], pub['public_origin'], executable=pub['executable']['path'], timeout_seconds=timeout)
        require(result.get('status') == 'published', 'follow_deployment_uncertain')
        proof = publication_proof(composed['primary_package'], composed['primary_content_sha256'], self.config, composed)
        self.ownership()
        source_identity(self.config['source'])
        times = {key: self.state['exports'][key]['observation']['completed_at_ms'] for key in completed
                 if key not in self.state['first_publications']}
        require(all(at <= proof['published_at_ms'] for at in times.values()), 'follow_publication_clock_changed')
        receipt = {'schema_version': 1, 'status': 'published', 'intent': current['intent'],
            'export': reference(folder/'export.json'), 'catalog': reference(composed_path),
            'verification': reference(Path(composed['primary_package'])/'vercel-public-verification.json'),
            'deployment_id': proof['deployment_id'], 'content_sha256': composed['primary_content_sha256'],
            'published_at_ms': proof['published_at_ms'], 'deployment_latency_ms': proof['latency_ms'],
            'completion_to_public_ms': {key: proof['published_at_ms']-at for key, at in times.items()},
            'completion_target_met': {key: 0 <= proof['published_at_ms']-at <= 60000 for key, at in times.items()},
            'completion_detection_ms': {key: intent['observed_at_ms']-at for key, at in times.items()},
            'export_latency_ms': exported['completed_at_ms']-pinned_json(reference(folder/'export-started.json'))['at_ms'],
            'catalog_and_checks_ms': pinned_json(reference(marker))['at_ms']-exported['completed_at_ms'],
            'observed_to_public_ms': proof['published_at_ms']-intent['observed_at_ms'], 'target_ms': 60000,
            'model_api_requests': 0}
        done = folder/'complete.json'
        if done.exists(): require(pinned_json(reference(done)) == receipt, 'follow_publication_receipt_changed')
        else: save(done, receipt)
        for key, at in times.items():
            self.state['first_publications'][key] = {'published_at_ms': proof['published_at_ms'],
                'completion_to_public_ms': proof['published_at_ms']-at, 'verification': receipt['verification']}
        self.state['publications'].append(reference(done)); self.state['last_signature'] = intent['signature']
        self.state['current'] = None; self.store()

    def run(self):
        self.load(); maximum = self.config['bounds'].get('watch_seconds', 3600)//POLL_SECONDS+1
        try:
            if self.state['status'] == 'complete':
                # A completed finite invocation never resumes observation or side effects.
                observed = checked_observation(self.state['observed'], self.config)
                require(self.state['current'] is None and observed['cohort_terminal']
                        and signature(observed) == self.state['last_signature'], 'follow_terminal_state_changed')
                for prior in self.state['exports'].values():
                    exported_receipt(prior['receipt'], self.config, prior['observation'])
                latest = pinned_json(self.state['latest_export'])
                publication = (pinned_json(self.state['publications'][-1]) if self.state['publications']
                               else self.config['seed']['publication'])
                composed = pinned_json(publication['catalog'])
                publication_proof(latest['package'], latest['content_sha256'], self.config, composed)
                return self.stop('complete', 'cohort_outcomes_published')
            while self.clock() < self.deadline:
                self.ownership()
                source_identity(self.config['source'])
                if self.state['current'] is not None:
                    self.operate(); continue
                if self.state['polls'] >= maximum: break
                last = self.state.get('last_poll_monotonic')
                if last is not None and self.clock()-last < POLL_SECONDS:
                    self.sleep(min(POLL_SECONDS-(self.clock()-last), max(0, self.deadline-self.clock())))
                    continue
                self.state['status'] = 'watching'; self.store()
                observed = self.observe(); rows = observed['attempts']
                unexported = [r for r in rows if r['status'] == 'completed' and r['id'] not in self.state['exports']]
                if unexported:
                    self.begin(observed, unexported[0], False); continue
                changed = signature(observed) != self.state['last_signature']
                if changed and any(row['status'] in TERMINAL for row in rows):
                    anchors = [r for r in rows if r['status'] == 'completed' and r['id'] in self.state['exports']]
                    if not anchors: return self.stop('blocked', 'snapshot_adapter_required')
                    self.begin(observed, max(anchors, key=lambda r: r['completed_at_ms']), True); continue
                if observed['cohort_terminal'] and not changed: return self.stop('complete', 'cohort_outcomes_published')
                self.sleep(min(POLL_SECONDS, max(0, self.deadline-self.clock())))
            return self.stop('unfinished', 'finite_watch_deadline')
        except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
            code = str(error)
            reason = code if re.fullmatch('follow_[a-z_]{1,90}|snapshot_adapter_required', code) else 'follow_step_unavailable'
            return self.stop('uncertain' if self.state['current'] else 'blocked', reason)


def follow(config_path, config_sha256, state_root, **kwargs):
    ref = {'path': str(config_path), 'sha256': config_sha256}; config = checked_config(pinned_json(ref))
    source_identity(config['source']); root = private_directory(state_root)
    link = vercel.project_link(config['publication']['project_link']['path'], config['publication']['project_link']['sha256'])
    lock_path = root/('project-'+digest(encoded({key: link[key] for key in ('projectId', 'orgId')}))+'.lock')
    fd = os.open(lock_path, os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0o600)
    try:
        def ownership():
            held, current = os.fstat(fd), lock_path.lstat()
            require(stat.S_ISREG(held.st_mode) and held.st_nlink == 1 and held.st_uid == os.geteuid()
                    and stat.S_IMODE(held.st_mode) == 0o600
                    and all(getattr(held, key) == getattr(current, key) for key in ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_uid')),
                    'follow_project_lock_changed')
        ownership()
        try: fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return {'status': 'busy', 'reason': 'publication_owner_active', 'model_api_requests': 0}
        return Follow(config, ref, root, ownership=ownership, **kwargs).run()
    finally: os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True); parser.add_argument('--config-sha256', required=True)
    parser.add_argument('--state-root', type=Path, required=True); args = parser.parse_args(argv)
    try: result = follow(args.config, args.config_sha256, args.state_root)
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        result = {'status': 'blocked', 'reason': 'follow_inputs_or_state_unavailable', 'model_api_requests': 0}
    print(json.dumps(result, sort_keys=True)); return 0 if result['status'] == 'complete' else 2


if __name__ == '__main__': raise SystemExit(main())
