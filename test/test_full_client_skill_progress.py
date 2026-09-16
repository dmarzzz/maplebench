"""Synthetic reporting only: no model, game, decoder, deployment or runtime calls."""
import copy
import json
import re
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import full_client_skill_progress as progress


class SkillProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = progress.load_plan()
        cls.initial = progress.decode((Path(__file__).resolve().parents[1] /
            'docs/plans/skill-suite-v1-progress.json').read_bytes())

    def report(self):
        value = copy.deepcopy(self.initial)
        value['execution_manifests'] = ['a' * 64]
        return value

    def entry(self, status, outcome=None, reason='admitted', at='2026-09-14T20:00:00Z'):
        return {'status': status, 'execution_manifest_sha256': 'a' * 64,
            'updated_at_utc': at, 'outcome': outcome, 'reason_code': reason,
            'evidence_sha256': ['b' * 64] if status in progress.TERMINAL else [],
            'public_evidence_urls': [], 'updates': []}

    def insert(self, value, row, entry):
        result = copy.deepcopy(value); result['entries'][row['plan_entry_id']] = entry
        result['phase_counts'] = progress.phase_counts(self.plan, result['entries'])
        result['last_updated_at_utc'] = entry['updated_at_utc']
        return result

    def model_row(self, task='platforming-v1'):
        return next(r for r in self.plan['rows'] if r['phase'] == 'skill-development' and r['task_id'] == task)

    def test_all_original_entries_numbered_once_and_zero_is_not_an_outcome(self):
        result = progress.project(self.initial, self.plan)
        files = progress.publication_files(result)
        self.assertEqual(len(files), 22)
        self.assertEqual(len(result['manifest']['experiments']), 21)
        self.assertEqual(result['manifest']['source_sha256'], progress.PLAN_FILES)
        rows = [row for e in result['manifest']['experiments'] for row in progress.decode(files[e['path']])['entries']]
        self.assertEqual([r['trial_number'] for r in rows], list(range(1, 853)))
        self.assertEqual(len({r['plan_entry_id'] for r in rows}), 852)
        self.assertEqual(sum(r['kind'] == 'native_control' for r in rows), 72)
        self.assertTrue(all(not r['reported'] and r['outcome'] is None and r['configuration_status'] == 'unbound' for r in rows))
        self.assertTrue(all(e['summary']['success_rate'] is None for e in result['manifest']['experiments']))
        self.assertTrue(all(e['planned'] <= 96 for e in result['manifest']['experiments']))
        table = progress.render_markdown(result)
        self.assertEqual(len(re.findall(r'^\| E[0-9]{3} ', table, re.M)), 873)
        self.assertIn('T0852', table); self.assertIn('unreported', table)

    def test_schedule_reordering_cannot_change_numbering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = Path(__file__).resolve().parents[1] / 'docs/plans'
            for name in progress.PLAN_FILES: shutil.copyfile(source / name, root / name)
            path = root / 'skill-suite-v1-native-checks.csv'
            rows = path.read_text().splitlines(); rows[1], rows[2] = rows[2], rows[1]
            path.write_text('\n'.join(rows) + '\n')
            with self.assertRaisesRegex(progress.ProgressError, 'frozen_schedule_changed'): progress.load_plan(root)

    def test_native_negative_pass_is_not_model_success_or_a_rate(self):
        row = next(r for r in self.plan['rows'] if r['control'] == 'negative-1')
        value = self.insert(self.report(), row, self.entry('success', 'passed', 'native_check_passed'))
        projected = progress.project(value, self.plan)
        e = projected['manifest']['experiments'][row['experiment_number'] - 1]
        self.assertEqual(e['summary']['success'], 1)
        self.assertIsNone(e['summary']['success_rate']); self.assertEqual(e['model_cells'], [])
        for experiment in projected['manifest']['experiments']:
            if experiment['kind'] == 'model_trial': self.assertEqual(experiment['summary']['success'], 0)

    def test_valid_failure_invalid_and_positive_have_distinct_denominators(self):
        row = self.model_row(); value = self.report()
        rows = [r for r in self.plan['rows'] if r['experiment_number'] == row['experiment_number']][:3]
        failed = {'criterion_met': False, 'completion_ms': None, 'alive': True, 'stable_presence_ms': 0}
        positive = {'criterion_met': True, 'completion_ms': 2000, 'alive': True, 'stable_presence_ms': 1000}
        for r, entry in zip(rows, [self.entry('gameplay_failure', failed, 'criterion_not_met'),
                self.entry('invalid', None, 'ledger_incomplete'), self.entry('success', positive, 'task_success')]):
            value = self.insert(value, r, entry)
        result = progress.project(value, self.plan); progress.publication_files(result)
        summary = result['manifest']['experiments'][row['experiment_number'] - 1]['summary']
        self.assertEqual((summary['success'], summary['gameplay_failure'], summary['invalid']), (1, 1, 1))
        self.assertEqual(summary['evaluable'], 2); self.assertEqual(summary['success_rate'], .5)
        self.assertFalse(summary['final'])

    def test_upsert_retains_corrected_outcome_evidence_and_status_chain(self):
        row = self.model_row(); value = self.report()
        active = self.entry('in_progress'); active.pop('updates')
        value = progress.upsert_progress(value, self.plan, row['plan_entry_id'], active)
        success = self.entry('success', {'criterion_met': True, 'completion_ms': 2000,
            'alive': True, 'stable_presence_ms': 1000}, 'task_success', '2026-09-14T20:01:00Z'); success.pop('updates')
        value = progress.upsert_progress(value, self.plan, row['plan_entry_id'], success)
        correction = self.entry('invalid', None, 'report_correction', '2026-09-14T20:02:00Z'); correction.pop('updates')
        corrected = progress.upsert_progress(value, self.plan, row['plan_entry_id'], correction)
        history = corrected['entries'][row['plan_entry_id']]['updates']
        self.assertEqual(history[-1]['previous_outcome'], success['outcome'])
        self.assertEqual(history[-1]['previous_evidence_sha256'], ['b' * 64])
        progress.publication_files(progress.project(corrected, self.plan))
        history[-1]['previous_status'] = 'in_progress'
        with self.assertRaisesRegex(progress.ProgressError, 'history_status_chain'): progress.project(corrected, self.plan)

    def test_private_unknown_unregistered_and_false_metric_fields_fail_closed(self):
        row = self.model_row(); base = self.entry('success', {'criterion_met': True, 'completion_ms': 2000,
            'alive': True, 'stable_presence_ms': 1000}, 'task_success')
        cases = [lambda x: x.update(prompt='private'), lambda x: x.update(execution_manifest_sha256='c' * 64),
            lambda x: x['outcome'].update(x=30), lambda x: x['outcome'].update(completion_ms=120000),
            lambda x: x['outcome'].update(completion_ms=True), lambda x: x['outcome'].update(stable_presence_ms=float('nan')),
            lambda x: x.update(evidence_sha256=[]), lambda x: x.update(reason_code='/root/private'),
            lambda x: x.update(public_evidence_urls=['https://maplebench.vercel.app/private/database.sql']),
            lambda x: x.update(public_evidence_urls=['https://github.com/dmarzzz/maplebench/pull/7?secret=1']),
            lambda x: x.update(public_evidence_urls=['http://127.0.0.1/evidence']),
            lambda x: x.update(evidence_sha256=[{}])]
        for mutate in cases:
            entry = copy.deepcopy(base); mutate(entry)
            with self.subTest(entry=entry), self.assertRaises(progress.ProgressError):
                progress.project(self.insert(self.report(), row, entry), self.plan)

    def test_duplicate_json_and_false_summary_are_rejected(self):
        with self.assertRaises(progress.ProgressError): progress.decode(b'{"entries":{},"entries":{}}')
        value = copy.deepcopy(self.initial); value['phase_counts']['native-initial']['success'] = 1
        with self.assertRaisesRegex(progress.ProgressError, 'phase_counts'): progress.project(value, self.plan)

    def test_reconstruction_rejects_changed_settings_hidden_fields_missing_rows_and_forged_summary(self):
        original = progress.publication_files(progress.project(self.initial, self.plan))
        path = self.plan['experiments'][0]['path']
        for mutate in [lambda x: x['entries'][0].update(host='private'),
                       lambda x: x['entries'][0].update(wall_seconds=999),
                       lambda x: x['entries'].pop(), lambda x: x['summary'].update(success=1)]:
            files = dict(original); shard = progress.decode(files[path]); mutate(shard); files[path] = progress.encoded(shard)
            # Even a matching newly forged shard hash cannot bypass semantic validation.
            manifest = progress.decode(files['skill-suite-manifest.json'])
            manifest['experiments'][0].update(sha256=progress.digest(files[path]), bytes=len(files[path]))
            files['skill-suite-manifest.json'] = progress.encoded(manifest)
            with self.assertRaisesRegex(progress.ProgressError, 'projection_mismatch'): progress.verify_publication(files)
        missing = dict(original); missing.pop(path)
        with self.assertRaises(progress.ProgressError): progress.verify_publication(missing)

    def test_writer_is_create_once(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'report'; projection = progress.project(self.initial, self.plan)
            receipt = progress.write_publication(projection, path)
            self.assertEqual(len(receipt['files']), 22); self.assertEqual(receipt['api_calls'], 0)
            before = (path / 'skill-suite-manifest.json').read_bytes()
            with self.assertRaisesRegex(progress.ProgressError, 'create_only'): progress.write_publication(projection, path)
            self.assertEqual((path / 'skill-suite-manifest.json').read_bytes(), before)


class SkillProgressCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = patch.object(tempfile, 'tempdir', str(Path(tempfile.gettempdir()).resolve()))
        self.temp_root.start(); self.addCleanup(self.temp_root.stop)
        import test_full_client_catalog as fixture
        self.f = fixture.CatalogTests(); self.f.setUp()
        self.catalog, _ = self.f.compose([self.f.package(self.f.fixture(), count=1)])
        self.plan = progress.load_plan()
        self.initial = progress.decode((Path(__file__).resolve().parents[1] /
            'docs/plans/skill-suite-v1-progress.json').read_bytes())

    def tearDown(self): self.f.tearDown()

    def test_real_composed_catalog_preserves_every_old_byte_and_new_identity_is_unclaimed(self):
        from full_client_publication import verify_package, publication_state
        from full_client_vercel import checked_payload
        original = Path(self.catalog['site'])
        before = {p.relative_to(original): p.read_bytes() for p in original.rglob('*') if p.is_file()}
        old_package = Path(self.catalog['primary_package'])
        (old_package / 'publication-intent.json').write_bytes(b'old uncertain intent must stay untouched')
        output = self.f.root / 'progress-packages'; output.mkdir()
        result = progress.attach_progress(self.catalog, progress.project(self.initial, self.plan), output)
        for name, raw in before.items():
            self.assertEqual((Path(result['site']) / name).read_bytes(), raw)
            self.assertEqual((original / name).read_bytes(), raw)
        bound = verify_package(Path(result['primary_package']), result['primary_content_sha256'])
        checked_payload(result['site'], result['inventory'], result['inventory_sha256'], bound)
        self.assertEqual(publication_state(Path(result['primary_package']), result['primary_content_sha256']), 'unclaimed')
        self.assertNotEqual(result['primary_content_sha256'], self.catalog['primary_content_sha256'])
        self.assertEqual((old_package / 'publication-intent.json').read_bytes(), b'old uncertain intent must stay untouched')
        # Another root JSON cannot masquerade as a suite file even with a fresh full-payload binding.
        path = Path(result['site']) / 'skill-suite/native-initial/platforming-v1.json'
        path.write_bytes(b'{"private_path":"/root/private"}\n')
        inventory = json.loads(Path(result['inventory']).read_text())
        inventory['files'][path.relative_to(result['site']).as_posix()] = {'sha256': progress.digest(path.read_bytes()), 'bytes': path.stat().st_size}
        Path(result['inventory']).write_bytes(progress.encoded(inventory))
        bound['content']['skill_progress_payload_sha256'] = progress.digest(progress.encoded(inventory['files']))
        with self.assertRaises(ValueError): checked_payload(result['site'], result['inventory'], progress.digest(progress.encoded(inventory)), bound)

    def test_new_json_requires_manifest_binding_and_arbitrary_names_remain_forbidden(self):
        from full_client_vercel import PUBLIC_NAME, checked_payload
        from full_client_publication import verify_package
        self.assertIsNone(PUBLIC_NAME.fullmatch('skill-suite/private.json'))
        self.assertIsNone(PUBLIC_NAME.fullmatch('skill-suite/native-initial/credentials.json'))
        self.assertIsNone(PUBLIC_NAME.fullmatch('secret.json'))
        original = Path(self.catalog['site']); projection = progress.project(self.initial, self.plan)
        inventory = json.loads(Path(self.catalog['inventory']).read_text())
        for name, raw in progress.publication_files(projection).items():
            target = original / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
            inventory['files'][name] = {'sha256': progress.digest(raw), 'bytes': len(raw)}
        path = self.f.root / 'new-inventory.json'; path.write_bytes(progress.encoded(inventory))
        bound = verify_package(Path(self.catalog['primary_package']), self.catalog['primary_content_sha256'])
        with self.assertRaisesRegex(ValueError, 'skill_progress_payload_binding_required'):
            checked_payload(original, path, progress.digest(path.read_bytes()), bound)


if __name__ == '__main__': unittest.main()
