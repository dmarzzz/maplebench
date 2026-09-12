"""Synthetic native ledger through package/catalog; no live review or deployment.

Only video decoding and the separate visual-acceptance boundary are mocked.
Native ledger, save, cycle and package hashes are independently recomputed.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))

import full_client_catalog as catalog
import full_client_publication as package
import full_client_xp_cohort as cohort
from full_client_research import summarize
import test_full_client_xp_publication as fixtures


class NativeCohortTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.NativePublicationTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.attempts = self.root / 'attempts'; self.attempts.mkdir()
        self.output = self.root / 'output'; self.output.mkdir()
        self.config = self.root / 'config'; self.config.mkdir()
        self.ids = [c * 32 for c in 'abcd']
        self.models = ['gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna']
        self.fixture = {'id': 'synthetic-native',
            **{k: {'sha256': self.f.refs[k]['sha256']} for k in ('scenario', 'baseline', 'runtime_manifest')},
            'adapter_fingerprint': self.f.context['adapter_fingerprint'], 'budgets': self.f.context['request']['budgets']}
        self.plan = {'schema_version': 1, 'repetitions': 1, 'models': self.models,
                     'fixtures': [self.fixture], 'entries': []}
        for i, (ident, model) in enumerate(zip(self.ids, self.models)):
            spec = self.f.context['request'] | {'model': model}
            self.plan['entries'].append({'ordinal': i, 'attempt_id': ident, 'model': model, 'repetition': 1,
                'fixture_id': self.fixture['id'], 'spec': spec, 'spec_sha256': package.digest(package.encoded(spec))})
        self.scenario = self.config / 'scenario.json'
        self.scenario.write_bytes((self.f.root / self.f.refs['scenario']['path']).read_bytes())
        self.path = self.config / 'plan.json'; self.path.write_bytes(package.encoded(self.plan))
        self.sha = package.digest(self.path.read_bytes())
        self.profile = {'protocol_id': cohort.PROTOCOL, 'class_id': 'hero', 'task_id': 'sustained_hunting'}
        self.evidence = {'schema_version': 1, 'protocol': cohort.EVIDENCE_PROTOCOL,
            'scorer_sha256': self.f.context['scorer_sha256'], 'native_acceptance': None,
            'attempts': {self.ids[0]: {k: self.f.context[k] for k in ('journal', 'backend')} | {'recording_review': None}}}
        self.copy_attempt()

    def copy_attempt(self):
        target = self.attempts / self.ids[0]
        if target.exists(): shutil.rmtree(target)
        shutil.copytree(self.f.root, target, ignore=shutil.ignore_patterns("docker.sock"))
        self.evidence['attempts'][self.ids[0]].update({k: self.f.context[k] for k in ('journal', 'backend')})

    @staticmethod
    def synthetic_acceptance(row, *_):
        # Gate acceptance is explicitly synthetic here; the original gate has
        # separate native ledger/capture/review tests and is never disabled live.
        row['native_runtime_acceptance'] = {'sha256': '6' * 64}
        row['recording'].update(visual_review='artifact_bound_operator_review', visual_review_sha256='7' * 64)
        row.update(publication_eligible=True, publication_blocker=None)
        return row

    def prepare(self, accepted=True, **kwargs):
        with patch('full_client_publish._probe_video', return_value=self.f.probe):
            if accepted:
                with patch('full_client_xp_publication._acceptance', side_effect=self.synthetic_acceptance):
                    result = package.prepare_package(self.path, self.sha, self.attempts, self.output,
                        adaptive_scenario=self.scenario, research_profile=self.profile, xp_evidence=self.evidence, **kwargs)
            else:
                result = package.prepare_package(self.path, self.sha, self.attempts, self.output,
                    adaptive_scenario=self.scenario, research_profile=self.profile, xp_evidence=self.evidence, **kwargs)
        self.snapshot = json.loads((Path(result['site']) / 'results.json').read_bytes())
        return result

    def test_native_ledger_to_verified_package_and_catalog(self):
        result = self.prepare(); row = self.snapshot['attempts'][0]
        self.assertEqual(row['persisted_xp'], 4500)
        self.assertEqual(row['authoritative_peak_xp_per_minute'], 18000)
        self.assertEqual(len(row['native_xp']['windows']), 20)
        self.assertTrue(row['publication_eligible']); self.assertFalse(row['ranked'])
        self.assertEqual(self.snapshot['cohort']['verified'], 1)
        self.assertEqual(len(self.snapshot['attempts']), 4)
        self.assertFalse(self.snapshot['cohort']['complete'])
        checked = catalog.cohort(result['package'], result['content_sha256'])
        self.assertEqual(checked['class_id'], 'hero')
        cells = self.snapshot['research_matrix']['models']
        self.assertEqual(cells[0]['cells'][0]['mean'], 18000)
        self.assertEqual(cells[1]['cells'][0]['not_started'], 1)
        copied = Path(result['site']) / 'recordings' / (self.ids[0] + '.webm')
        self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(), self.f.refs['video']['sha256'])
        self.assertEqual(result['api_requests'], 0); self.assertFalse(result['deployment_performed'])

    def test_missing_acceptance_keeps_public_scores_and_media_pending(self):
        result = self.prepare(accepted=False); row = self.snapshot['attempts'][0]
        self.assertEqual(row['status'], 'completed')
        self.assertIsNone(row['persisted_xp']); self.assertIsNone(row['authoritative_peak_xp_per_minute'])
        self.assertFalse(row['publication_eligible']); self.assertIsNone(row['recording'])
        self.assertEqual(row['native_xp']['publication_blocker'], 'new_native_runtime_and_baseline_acceptance_required')
        self.assertEqual(self.snapshot['research_matrix']['models'][0]['cells'][0]['unknown'], 1)
        catalog.cohort(result['package'], result['content_sha256'])

    def test_missing_terminal_pins_are_not_derived_from_candidate_output(self):
        self.evidence['attempts'] = {}
        with patch('full_client_xp_publication.project_attempt') as strict:
            self.prepare()
            strict.assert_not_called()
        self.assertEqual(self.snapshot['attempts'][0]['native_xp']['publication_blocker'], 'terminal_operator_pins_required')

    def test_failed_and_unsubmitted_outcomes_are_retained(self):
        self.f.journal.update(status='failed', api_outcome='uncertain')
        self.f.repin(); self.copy_attempt(); self.prepare()
        self.assertEqual(self.snapshot['attempts'][0]['status'], 'failed')
        self.assertEqual([m['cells'][0]['failed'] for m in self.snapshot['research_matrix']['models']], [1, 0, 0, 0])
        self.assertEqual([m['cells'][0]['not_started'] for m in self.snapshot['research_matrix']['models']], [0, 1, 1, 1])

    def test_original_ledger_corruption_remains_unknown_not_zero(self):
        (self.attempts / self.ids[0] / self.f.refs['xp_ledger']['path']).write_bytes(b'changed')
        self.prepare()
        row = self.snapshot['attempts'][0]
        self.assertIsNone(row['authoritative_peak_xp_per_minute']); self.assertIsNone(row['recording'])
        self.assertEqual(self.snapshot['cohort']['verified'], 0)

    def test_partial_cohort_cannot_retire_archive(self):
        with self.assertRaisesRegex(ValueError, 'four_verified_recordings'):
            self.prepare(replace_archive=True)

    def test_same_accepted_evidence_is_idempotent(self):
        self.assertEqual(self.prepare()['content_sha256'], self.prepare()['content_sha256'])

    def test_private_evidence_is_not_in_public_projection(self):
        self.prepare(); raw = json.dumps(self.snapshot)
        for value in (str(self.root), str(self.f.root), 'account_id', 'character_id',
                      'backend-state.json', 'native_save', 'SYNTHETIC NONDECODABLE', 'instructions'):
            self.assertNotIn(value, raw)

    def test_explicit_context_and_scorer_pins_cannot_be_extended_or_replaced(self):
        original = copy.deepcopy(self.evidence)
        for mutation in (lambda e: e.update(accepted=True), lambda e: e.update(scorer_sha256='1' * 64),
                         lambda e: e['attempts'].update({'f' * 32: e['attempts'][self.ids[0]]}),
                         lambda e: e['attempts'][self.ids[0]]['journal'].update(sha256='1' * 64)):
            self.evidence = copy.deepcopy(original); mutation(self.evidence)
            try: self.prepare()
            except ValueError: pass
            else: self.assertEqual(self.snapshot['cohort']['verified'], 0)

    def test_native_windows_cannot_enter_legacy_or_adaptive_publisher(self):
        for scenario in (None, self.scenario):
            with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                package.prepare_package(self.path, self.sha, self.attempts, self.output,
                    research_profile=self.profile, adaptive_scenario=scenario)

    def test_catalog_rejects_tampered_rate_denominator_and_review(self):
        self.prepare(); original = self.snapshot['attempts'][0]
        for change in (lambda r: r['native_xp']['windows'][0].update(net_xp=9000),
                       lambda r: r['native_xp']['normalization']['server_xp_multiplier'].update(numerator=2),
                       lambda r: r['native_xp'].update(recording_review_sha256='yes'),
                       lambda r: r.update(authoritative_peak_xp_per_minute=4500),
                       lambda r: r['native_xp'].update(complete_windows=19)):
            row = copy.deepcopy(original); change(row)
            with self.assertRaises(ValueError): catalog.verified(row)


if __name__ == '__main__': unittest.main()
