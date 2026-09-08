"""Synthetic packages, real catalog/driver validation, mocked external commands.

No model, database, server, SSH connection or Vercel deployment is launched.
"""
import copy
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import full_client_follow_publication as follow
import full_client_catalog as catalog
import full_client_publication as publication
import full_client_vercel as driver
import test_full_client_adaptive_publication as fixtures


class FollowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AdaptivePublicationTests(); self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root.resolve(); self.root.chmod(0o700)
        self.private = self.root/'follow'; self.private.mkdir(mode=0o700)
        self.receipts = self.private/'receipts'; self.receipts.mkdir(mode=0o700)
        self.catalogs = self.private/'catalogs'; self.catalogs.mkdir(mode=0o700)
        self.states = self.private/'states'; self.states.mkdir(mode=0o700)
        self.exports = []; self.cli_calls = []; self.metadata = {}; self.schedule = [(1, False)]
        self.now = 2_000_000.0; self.wall_ms = 1_400_000
        self.bad_observer = False; self.lose_export = False; self.drop_export_receipt = False
        self.lose_deploy = False; self.deployment_visible = True
        self.project = {'projectId': 'prj_SYNTHETIC1234', 'orgId': 'team_SYNTHETIC1234', 'projectName': 'synthetic-follow'}
        self.plan_ref = {'path': str(self.fixture.path.resolve()), 'sha256': self.fixture.plan_sha}
        python = Path(sys.executable).resolve()
        python_ref = {'path': str(python), 'sha256': follow.digest(python.read_bytes())}
        observer = self.write('observer.py', b'# reviewed synthetic observer\n')
        exporter = self.write('exporter.py', b'# reviewed synthetic exporter\n')
        self.export_config = self.write('export-config.json', {'schema_version': 1, 'plan': self.plan_ref,
            'release_root': '/synthetic/immutable-release', 'verification_source': {'path': '/synthetic/verifier', 'commit': 'a'*40},
            'class_id': 'hero', 'attempt_ids': self.fixture.ids})
        self.config = {'schema_version': 1, 'protocol': follow.PROTOCOL,
            'cohort': {'plan': self.plan_ref, 'runtime_manifest_sha256': self.fixture.plan['fixtures'][0]['runtime_manifest']['sha256'],
                      'class_id': 'hero', 'attempts': [{'id': ident, 'model': model} for ident, model in zip(self.fixture.ids, self.fixture.models)]},
            'source': {'path': str(Path(__file__).resolve().parents[1]), 'commit': 'a'*40},
            'observer': {'argv': [str(python), observer['path']], 'dependencies': [python_ref, observer]},
            'exporter': {'command': {'argv': [str(python), exporter['path'], '--config', self.export_config['path'],
                                            '--config-sha256', self.export_config['sha256']],
                                    'dependencies': [python_ref, exporter, self.export_config]},
                         'config': self.export_config, 'receipt_root': str(self.receipts), 'completion_prefix': 'EXPORT_'},
            'catalog': {'cohorts': [], 'previous_cohorts': [], 'archive': None, 'output_root': str(self.catalogs)},
            'publication': {'project_link': self.write('project.json', self.project),
                            'public_origin': 'https://synthetic-follow.vercel.app', 'executable': python_ref},
            'seed': None, 'bounds': {'watch_seconds': 60}}
        self.config_ref = self.write('config.json', self.config)
        self.source_patch = patch.object(follow, 'source_identity'); self.source_patch.start(); self.addCleanup(self.source_patch.stop)
        self.time_patch = patch.object(driver.time, 'time', side_effect=lambda: self.wall_ms/1000)
        self.time_patch.start(); self.addCleanup(self.time_patch.stop)

    def write(self, name, value):
        path = self.private/name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        raw = value if isinstance(value, bytes) else publication.encoded(value)
        path.write_bytes(raw); path.chmod(0o600)
        return follow.reference(path)

    def advance(self, seconds):
        self.now += seconds; self.wall_ms += round(seconds*1000)

    def observation(self, count=1, terminal=False):
        rows = []
        for i, expected in enumerate(self.config['cohort']['attempts']):
            if i < count and not (self.fixture.attempts/expected['id']).exists(): self.fixture.attempt(i, xp=(-50, 0, 100, 200)[i])
            path = self.fixture.attempts/expected['id']/'journal.json'
            status = json.loads(path.read_bytes())['status'] if path.exists() else 'pending'
            rows.append({**expected, 'status': status, 'journal_sha256': follow.digest(path.read_bytes()) if path.exists() else None,
                         'completed_at_ms': 1_350_000+i*1000 if status == 'completed' else None})
        return {'schema_version': 1, 'plan_sha256': self.plan_ref['sha256'],
                'runtime_manifest_sha256': self.config['cohort']['runtime_manifest_sha256'], 'class_id': 'hero',
                'cohort_terminal': terminal, 'attempts': rows}

    def make_export(self, ident, snapshot=False):
        i = self.fixture.ids.index(ident); observed = self.observation(0)
        anchor = observed['attempts'][i]
        prepared, _ = self.fixture.prepare()
        self.advance(2)
        archive = self.write('backups/'+ident+'/evidence.tar', b'SYNTHETIC archive bytes; no database or recording')
        journal_name = 'synthetic/attempts/'+ident+'/journal.json'
        backup = self.write('backups/'+ident+'/receipt.json', {'status': 'verified_private_completed_attempt_backup',
            'plan_sha256': self.plan_ref['sha256'], 'files': {journal_name: {'sha256': anchor['journal_sha256']}},
            'archive_bytes': Path(archive['path']).stat().st_size, 'archive_sha256': archive['sha256']})
        name = ('SNAPSHOT_'+prepared['content_sha256'] if snapshot else 'EXPORT_'+ident)+'.json'
        selected = follow.pinned_json(self.export_config)
        value = {'status': 'completed_model_public_package_verified_not_deployed',
            'export_config_sha256': self.export_config['sha256'], 'verification_source': selected['verification_source'],
            'release_root': selected['release_root'], 'class_id': 'hero', 'model': self.fixture.models[i], 'attempt_id': ident,
            'plan_sha256': self.plan_ref['sha256'], 'journal_sha256': anchor['journal_sha256'],
            'package': prepared['package'], 'content_sha256': prepared['content_sha256'],
            'backup_receipt': backup['path'], 'backup_receipt_sha256': backup['sha256'], 'api_calls': 0, 'deployments': 0}
        path = self.receipts/name
        if not path.exists(): path.write_bytes(follow.encoded(value)); path.chmod(0o600)
        return follow.reference(path)

    def command(self, config, extra, deadline):
        self.assertLessEqual(deadline, self.now+720)
        if config == self.config['observer']:
            count, terminal = self.schedule.pop(0) if len(self.schedule) > 1 else self.schedule[0]
            value = self.observation(count, terminal)
            if self.bad_observer: value['attempts'][0]['id'] = 'e'*32
            return follow.encoded(value)
        self.assertEqual(config, self.config['exporter']['command'])
        self.assertEqual(extra[:1], ['--attempt-id']); self.assertIn(extra[1], self.fixture.ids)
        self.exports.append(extra)
        if self.drop_export_receipt: raise OSError('PRIVATE transport credentials must not escape')
        ref = self.make_export(extra[1], '--snapshot' in extra)
        if self.lose_export: raise OSError('PRIVATE lost transport reply')
        return follow.encoded({'receipt': ref['path'], 'receipt_sha256': ref['sha256']})

    def cli(self, executable, args, stage, deadline):
        self.cli_calls.append(args[0]); self.assertNotIn('--token', args)
        if args[0] == 'deploy':
            self.metadata = {args[i+1].split('=', 1)[0]: args[i+1].split('=', 1)[1] for i, arg in enumerate(args) if arg == '--meta'}
            self.advance(3)
            if self.lose_deploy: raise OSError('PRIVATE provider details')
            return {'ok': True}
        if args[0] == 'list':
            rows = [{'id': 'dpl_SYNTHETIC1234', 'name': self.project['projectName'], 'target': 'production', 'meta': self.metadata}]
            return {'deployments': rows if self.deployment_visible else [], 'pagination': {}}
        return {'id': 'dpl_SYNTHETIC1234', 'name': self.project['projectName'], 'target': 'production',
                'readyState': 'READY', 'aliases': ['synthetic-follow.vercel.app']}

    def publish(self, *args, **kwargs):
        payload = Path(args[2]); base = self.config['publication']['public_origin']
        def fetch(url, maximum, headers, deadline):
            data = (payload/url[len(base)+1:]).read_bytes()
            if headers:
                count = min(16, len(data))
                return {'status': 206, 'headers': {'content-range': f'bytes 0-{count-1}/{len(data)}'},
                        'sha256': follow.digest(data[:count]), 'bytes': count}
            return {'status': 200, 'headers': {}, 'sha256': follow.digest(data), 'bytes': len(data)}
        return driver.publish(*args, **kwargs, run_cli=self.cli, fetch=fetch)

    def runner(self):
        return follow.Follow(self.config, self.config_ref, self.states, run_command=self.command,
            compose=catalog.compose, publish=self.publish, clock=lambda: self.now,
            wall=lambda: self.wall_ms/1000, sleep=self.advance)

    def test_four_completions_keep_exact_ids_signed_scores_and_first_publication_latency(self):
        self.schedule = [(1, False), (2, False), (3, False), (4, True)]
        result = self.runner().run()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(self.cli_calls.count('deploy'), 4)
        self.assertEqual([args[1] for args in self.exports], self.fixture.ids)
        state = follow.pinned_json(follow.reference(Path(result['state'])))
        self.assertEqual(set(state['first_publications']), set(self.fixture.ids))
        first = follow.pinned_json(state['publications'][0])
        self.assertEqual(first['completion_to_public_ms'], {self.fixture.ids[0]: 55000})
        self.assertEqual(first['deployment_latency_ms'], 3000)
        self.assertEqual(first['completion_detection_ms'], {self.fixture.ids[0]: 50000})
        self.assertEqual(first['export_latency_ms'], 2000)
        self.assertEqual(first['completion_target_met'], {self.fixture.ids[0]: True})
        last = follow.pinned_json(state['publications'][-1])
        self.assertEqual(set(last['completion_to_public_ms']), {self.fixture.ids[3]})
        composed = follow.pinned_json(last['catalog'])
        rows = json.loads((Path(composed['site'])/'results.json').read_bytes())['attempts']
        self.assertEqual([row['id'] for row in rows], self.fixture.ids)
        self.assertEqual([row['persisted_xp'] for row in rows], [-50, 0, 100, 200])
        self.assertFalse(any('--snapshot' in args for args in self.exports))

    def test_lost_export_reply_uses_exact_receipt_once(self):
        self.lose_export = True
        result = self.runner().run()
        self.assertEqual(result['status'], 'unfinished')
        self.assertEqual(len(self.exports), 1); self.assertEqual(self.cli_calls.count('deploy'), 1)

    def test_operator_note_survives_each_publication_and_cannot_be_dropped(self):
        note={'plan_sha256':self.plan_ref['sha256'],'text':'This declared port fixture excludes unqualified skills.'}
        self.config['catalog']['annotations']=[note]
        self.config_ref=self.write('annotated-config.json',self.config)
        self.schedule=[(1,False),(2,False),(3,False),(4,True)]
        result=self.runner().run()
        self.assertEqual(result['status'],'complete')
        state=follow.pinned_json(follow.reference(Path(result['state'])))
        for proof_ref in state['publications']:
            proof=follow.pinned_json(proof_ref); composed=follow.pinned_json(proof['catalog'])
            site=Path(composed['site']); snapshot=json.loads((site/'results.json').read_bytes())
            self.assertEqual(snapshot['catalog']['annotations'][0]['text'],note['text'])
            self.assertIn(note['text'],(site/'index.html').read_text())
            request=follow.pinned_json(follow.reference(Path(proof_ref['path']).parent/'catalog-request.json'))
            self.assertEqual(request['annotations'],[note])
            request.pop('annotations')
            with self.assertRaisesRegex(ValueError,'follow_catalog_annotations_changed'):
                follow.checked_composition(composed,request,self.catalogs)

    def test_missing_export_reply_never_blindly_reexports_on_resume(self):
        self.drop_export_receipt = True
        first = self.runner().run(); self.assertEqual(first['reason'], 'follow_export_uncertain')
        self.drop_export_receipt = False
        again = self.runner().run(); self.assertEqual(again['reason'], 'follow_export_uncertain')
        self.assertEqual(len(self.exports), 1); self.assertEqual(self.cli_calls, [])

    def test_deployment_uncertainty_pauses_later_results_and_only_reconciles_same_marker(self):
        self.lose_deploy = True; self.deployment_visible = False
        self.schedule = [(1, False), (2, False)]
        result = self.runner().run(); self.assertEqual(result['reason'], 'follow_deployment_uncertain')
        self.assertEqual(len(self.exports), 1); self.assertEqual(self.cli_calls.count('deploy'), 1)
        self.deployment_visible = True; self.schedule = [(1, False)]
        result = self.runner().run(); self.assertEqual(result['status'], 'unfinished')
        self.assertEqual(len(self.exports), 1); self.assertEqual(self.cli_calls.count('deploy'), 1)

    def test_no_completed_anchor_preserves_failures_without_export_or_deploy(self):
        self.schedule = [(0, False)]
        path = self.fixture.attempts/self.fixture.ids[0]; path.mkdir()
        (path/'journal.json').write_bytes(follow.encoded({'status': 'failed'}))
        result = self.runner().run(); self.assertEqual(result['reason'], 'snapshot_adapter_required')
        state = follow.pinned_json(follow.reference(Path(result['state'])))
        self.assertEqual(state['observed']['attempts'][0]['status'], 'failed')
        self.assertEqual(self.exports, []); self.assertEqual(self.cli_calls, [])

    def test_changed_observer_identity_and_private_errors_do_not_reach_publication(self):
        self.bad_observer = True
        result = self.runner().run(); self.assertEqual(result['reason'], 'follow_observer_attempt_changed')
        self.assertNotIn('PRIVATE', json.dumps(result)); self.assertEqual(self.exports, [])

    def test_deadline_and_poll_count_are_original_across_resume(self):
        self.schedule = [(0, False)]; self.config['bounds']['watch_seconds'] = 10
        result = self.runner().run(); self.assertEqual(result['status'], 'unfinished')
        self.assertEqual(result['observations'], 2)
        result = self.runner().run(); self.assertEqual(result['observations'], 2)
        self.assertEqual(result['status'], 'unfinished'); self.assertEqual(self.exports, [])

    def test_expanded_watch_or_unpinned_shell_commands_are_refused(self):
        follow.checked_config(self.config)
        for seconds in (0, 7201, True):
            bad = copy.deepcopy(self.config); bad['bounds']['watch_seconds'] = seconds
            with self.subTest(seconds=seconds), self.assertRaisesRegex(ValueError, 'finite_deadline'):
                follow.checked_config(bad)
        bad = copy.deepcopy(self.config['observer']); bad['argv'] += ['-c', 'print(1)']
        with self.assertRaisesRegex(ValueError, 'no_shell_or_inline'): follow.checked_command(bad)
        bad = copy.deepcopy(self.config['observer']); bad['dependencies'][1]['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'pinned_bytes_changed'): follow.checked_command(bad)

    def test_orphan_phase_and_changed_original_deadline_refuse_without_external_calls(self):
        runner = self.runner(); runner.load(); (runner.folder/'operation-01').mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, 'orphan_operation'): self.runner().load()
        (runner.folder/'operation-01').rmdir()
        path = runner.folder/'intent.json'; intent = json.loads(path.read_bytes()); intent['monotonic_deadline'] += 1
        path.write_bytes(follow.encoded(intent))
        with self.assertRaisesRegex(ValueError, 'original_deadline_changed'): self.runner().load()
        self.assertEqual(self.exports, []); self.assertEqual(self.cli_calls, [])

    def test_already_published_seed_is_hash_verified_and_never_deployed_again(self):
        previous = self.runner().run()
        state = follow.pinned_json(follow.reference(Path(previous['state'])))
        completed = follow.pinned_json(state['publications'][0])
        exported = next(iter(state['exports'].values()))['receipt']
        value = follow.pinned_json(exported); package = Path(value['package'])
        observed = self.write('seed-observation.json', state['observed'])
        self.config['seed'] = {'observation': observed, 'exports': [exported], 'primary_export': exported,
            'publication': {'complete': follow.reference(package/'publication-complete.json'),
                            'verification': follow.reference(package/'vercel-public-verification.json'),
                            'catalog': completed['catalog']}}
        self.config_ref = self.write('seeded-config.json', self.config)
        before = list(self.cli_calls)
        result = self.runner().run(); self.assertEqual(result['status'], 'unfinished')
        self.assertEqual(self.cli_calls, before); self.assertEqual(len(self.exports), 1)
        seeded = follow.pinned_json(follow.reference(Path(result['state'])))
        for ident, imported in seeded['first_publications'].items():
            self.assertEqual(imported['published_at_ms'], state['first_publications'][ident]['published_at_ms'])
            self.assertEqual(imported['timing_kind'], 'seed_snapshot_upper_bound')
            self.assertNotIn('completion_to_public_ms', imported)
        self.assertEqual(seeded['publications'], [])

    def test_terminal_resume_rechecks_local_proofs_without_observer_or_side_effects(self):
        self.schedule = [(4, True)]
        result = self.runner().run(); self.assertEqual(result['status'], 'complete')
        before = (list(self.exports), list(self.cli_calls), result['observations'])
        runner = self.runner()
        runner.run_command = lambda *args: self.fail('terminal invocation executed a command')
        self.advance(100)
        result = runner.run()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual((self.exports, self.cli_calls, result['observations']), before)

    def test_seed_cannot_suppress_an_outcome_missing_from_public_snapshot(self):
        observed = self.observation()
        prepared, _ = self.fixture.prepare()
        rows = json.loads((Path(prepared['package'])/'site/results.json').read_bytes())['attempts']
        follow.matching_public_outcomes(observed, rows)
        observed['attempts'][1].update(status='failed', journal_sha256='a'*64)
        with self.assertRaisesRegex(ValueError, 'seed_outcomes_changed'):
            follow.matching_public_outcomes(observed, rows)

    def test_several_completed_members_are_all_backed_up_before_one_catalog_publication(self):
        self.schedule = [(4, True)]
        result = self.runner().run(); self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(self.exports), 4); self.assertEqual(self.cli_calls.count('deploy'), 1)
        state = follow.pinned_json(follow.reference(Path(result['state'])))
        self.assertEqual(len(state['exports']), 4)
        self.assertEqual(len(list(Path(result['state']).parent.glob('operation-*/deferred.json'))), 3)

    def fail_second_member_after_first_publication(self):
        original = self.command; calls = [0]
        def run(config, extra, deadline):
            if config == self.config['observer']:
                calls[0] += 1
                if calls[0] == 2:
                    ident = self.fixture.ids[1]; folder = self.fixture.attempts/ident; folder.mkdir()
                    (folder/'journal.json').write_bytes(follow.encoded({'attempt_id': ident, 'status': 'failed',
                        'phase': 'run_controller', 'request': self.fixture.plan['entries'][1]['spec'],
                        'adapter_fingerprint': '9'*64, 'events': [{'kind': 'created', 'at_ms': 900000}],
                        'api_outcome': 'uncertain'}))
            return original(config, extra, deadline)
        self.command = run

    def test_failure_snapshot_uses_completed_anchor_and_preserves_all_four_outcomes(self):
        self.fail_second_member_after_first_publication()
        result = self.runner().run(); self.assertEqual(result['status'], 'unfinished')
        self.assertEqual(self.exports, [['--attempt-id', self.fixture.ids[0]],
            ['--attempt-id', self.fixture.ids[0], '--snapshot']])
        self.assertEqual(self.cli_calls.count('deploy'), 2)
        state = follow.pinned_json(follow.reference(Path(result['state'])))
        done = follow.pinned_json(state['publications'][-1]); composed = follow.pinned_json(done['catalog'])
        rows = json.loads((Path(composed['site'])/'results.json').read_bytes())['attempts']
        self.assertEqual([row['status'] for row in rows], ['completed', 'failed', 'not_started', 'not_started'])
        self.assertEqual(done['completion_to_public_ms'], {})
        self.assertEqual(set(state['first_publications']), {self.fixture.ids[0]})

    def test_lost_snapshot_reply_does_not_search_receipt_directories_or_repeat_export(self):
        self.fail_second_member_after_first_publication()
        original = self.command
        def run(config, extra, deadline):
            self.lose_export = '--snapshot' in extra
            return original(config, extra, deadline)
        self.command = run
        result = self.runner().run(); self.assertEqual(result['reason'], 'follow_export_uncertain')
        self.assertEqual(len(self.exports), 2); self.assertEqual(self.cli_calls.count('deploy'), 1)
        result = self.runner().run(); self.assertEqual(result['reason'], 'follow_export_uncertain')
        self.assertEqual(len(self.exports), 2)

    def test_changed_backup_bytes_refuse_publication_despite_export_success_label(self):
        original = self.make_export
        def exported(ident, snapshot=False):
            ref = original(ident, snapshot)
            (self.private/'backups'/ident/'evidence.tar').write_bytes(b'changed private backup')
            return ref
        self.make_export = exported
        result = self.runner().run(); self.assertEqual(result['reason'], 'follow_backup_archive_changed')
        self.assertEqual(self.cli_calls, [])

    def test_shared_project_lock_prevents_a_second_owner(self):
        path = self.states/('project-'+follow.digest(follow.encoded({key: self.project[key] for key in ('projectId', 'orgId')}))+'.lock')
        fd = os.open(path, os.O_RDWR|os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
            result = follow.follow(self.config_ref['path'], self.config_ref['sha256'], self.states,
                                   run_command=self.command)
            self.assertEqual(result['status'], 'busy'); self.assertEqual(self.exports, [])
        finally: os.close(fd)

    def test_changed_catalog_sources_are_refused_before_driver(self):
        original = catalog.compose
        def composed(request, output):
            value = original(request, output); value['primary_content_sha256'] = '0'*64
            return value
        runner = self.runner(); runner.compose = composed
        result = runner.run(); self.assertEqual(result['reason'], 'follow_catalog_paths_changed')
        self.assertEqual(self.cli_calls, [])

    def test_public_file_proof_cannot_be_replaced_with_bare_success(self):
        original = self.publish
        def publish(*args, **kwargs):
            result = original(*args, **kwargs)
            path = Path(args[0])/'vercel-public-verification.json'; value = json.loads(path.read_bytes())
            value['public_verification']['files'] = []; path.write_bytes(follow.encoded(value))
            return result
        self.publish = publish
        result = self.runner().run(); self.assertEqual(result['reason'], 'follow_publication_file_proofs_changed')
        self.assertEqual(len(follow.pinned_json(follow.reference(Path(result['state'])))['publications']), 0)

    def test_lost_catalog_reply_reuses_same_request_without_export_replay(self):
        calls = []
        def compose(request, output):
            value = catalog.compose(request, output); calls.append(copy.deepcopy(request))
            if len(calls) == 1: raise OSError('lost local composition reply')
            return value
        runner = self.runner(); runner.compose = compose
        result = runner.run(); self.assertEqual(result['status'], 'uncertain')
        runner = self.runner(); runner.compose = compose
        result = runner.run(); self.assertEqual(result['status'], 'unfinished')
        self.assertEqual(calls[0], calls[1]); self.assertEqual(len(self.exports), 1)
        self.assertEqual(self.cli_calls.count('deploy'), 1)

    def test_source_change_during_export_blocks_catalog_and_deployment(self):
        original = self.make_export
        def exported(ident, snapshot=False):
            ref = original(ident, snapshot)
            follow.source_identity.side_effect = ValueError('follow_source_dirty')
            return ref
        self.make_export = exported
        result = self.runner().run(); self.assertEqual(result['reason'], 'follow_source_dirty')
        self.assertEqual(self.cli_calls, [])

    def test_production_cli_adapter_uses_only_fixed_catalog_and_driver_commands(self):
        calls = []
        def process(argv, deadline):
            name = Path(argv[1]).name; calls.append(name)
            values = dict(zip(argv[2::2], argv[3::2]))
            self.assertGreater(deadline, self.now)
            if name == 'full_client_catalog.py':
                request = follow.pinned_json({'path': values['--request'], 'sha256': values['--request-sha256']})
                return follow.encoded(catalog.compose(request, Path(values['--output-root'])))
            self.assertEqual(name, 'full_client_vercel.py')
            value = self.publish(Path(values['--package']), values['--content-sha256'], Path(values['--payload']),
                Path(values['--payload-inventory']), values['--payload-inventory-sha256'], Path(values['--project-link']),
                values['--project-link-sha256'], values['--public-origin'], executable=values['--vercel-executable'],
                timeout_seconds=int(values['--timeout-seconds']))
            return follow.encoded(value)
        runner = self.runner(); runner.compose = runner.publish = None
        with patch.object(follow, 'process_output', side_effect=process): result = runner.run()
        self.assertEqual(result['status'], 'unfinished')
        self.assertEqual(calls, ['full_client_catalog.py', 'full_client_vercel.py'])


class BoundedProcessTests(unittest.TestCase):
    def test_external_stderr_is_discarded_and_timeout_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp).resolve()/'helper.py'
            path.write_text("import sys\nsys.stderr.write('PRIVATE_CREDENTIAL_DETAIL')\nraise SystemExit(1)\n")
            with self.assertRaisesRegex(ValueError, '^follow_command_reply_unavailable$'):
                follow.process_output([str(Path(sys.executable).resolve()), str(path)], time.monotonic()+3)
            path.write_text('import time\ntime.sleep(30)\n')
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, '^follow_command_timeout$'):
                follow.process_output([str(Path(sys.executable).resolve()), str(path)], started+.1)
            self.assertLess(time.monotonic()-started, 3)

    def test_completed_child_output_is_still_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp).resolve()/'helper.py'; path.write_text("import sys\nsys.stdout.write('x'*3000000)\n")
            with self.assertRaisesRegex(ValueError, '^follow_command_output_limit$'):
                follow.process_output([str(Path(sys.executable).resolve()), str(path)], time.monotonic()+3)


if __name__ == '__main__': unittest.main()
