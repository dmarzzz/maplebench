"""Inert publication fixtures; video probing is mocked, no native/model acceptance."""
import copy
import json
import unittest
from pathlib import Path

import test_full_client_adaptive_publication as fixtures
from full_client_native import PROFILES, NATIVE_V4_PROTOCOL
from full_client_trial import TrialError
from full_client_publication import digest, encoded, selected_plan

RUNTIME = '966bfe38b2661be8b38a8743ac28e74d036d7e4d'


class NightLordProjectionTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.AdaptivePublicationTests('runTest')
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        case = self.case
        case.scenario['adaptive_protocol']['profile'] = copy.deepcopy(PROFILES['night_lord'])
        case.profile.update(class_id='night_lord', task_id='basic_combat')
        case.plan['runner'] = {'trial_script': {
            'path': '/opt/maplebench/releases/' + RUNTIME + '/scripts/full_client_trial.py',
            'sha256': '4' * 64}}
        case.enable_capture_policy()

    def test_four_model_projection_preserves_runtime_plan_and_signed_receipts(self):
        case = self.case
        for index, xp in enumerate((0, -25, 100, 500)):
            case.attempt(index, xp=xp)
        original_plan = case.path.read_bytes()
        original_journals = {p: p.read_bytes() for p in case.attempts.glob('*/journal.json')}
        selected = selected_plan(case.path, case.plan_sha)
        value, snapshot = case.prepare()
        self.assertEqual(selected['runner']['trial_script']['path'], case.plan['runner']['trial_script']['path'])
        self.assertEqual(value['target_path'], '/cohorts/' + case.plan_sha[:16] + '/')
        self.assertEqual([r['persisted_xp'] for r in snapshot['attempts']], [0, -25, 100, 500])
        self.assertEqual([r['requested_model'] for r in snapshot['attempts']], case.models)
        self.assertTrue(all(r['research']['class_id'] == 'night_lord' for r in snapshot['attempts']))
        self.assertTrue(all(r['score_verification'] == fixtures.projection.VERIFIED for r in snapshot['attempts']))
        self.assertEqual(case.path.read_bytes(), original_plan)
        self.assertEqual({p: p.read_bytes() for p in original_journals}, original_journals)
        self.assertFalse((case.attempts / '.operations').exists())
        self.assertEqual(value['api_requests'], 0)
        self.assertFalse(value['deployment_performed'])

    def test_native_script_identity_is_never_a_model_publication(self):
        case = self.case
        for entry in case.plan['entries']:
            entry['spec']['protocol'] = NATIVE_V4_PROTOCOL
            entry['spec_sha256'] = digest(encoded(entry['spec']))
        case.path.write_bytes(encoded(case.plan))
        with self.assertRaisesRegex(TrialError, 'unsupported_protocol'):
            selected_plan(case.path, digest(case.path.read_bytes()))

    def test_mislabeled_night_lord_profile_refuses(self):
        case = self.case
        case.profile['class_id'] = 'hero'
        with self.assertRaisesRegex(ValueError, 'adaptive_public_class_mismatch'):
            case.prepare()

    def test_unsubmitted_models_remain_in_the_denominator(self):
        case = self.case
        case.attempt(0, xp=0)
        _, snapshot = case.prepare()
        self.assertEqual([r['status'] for r in snapshot['attempts']],
                         ['completed', 'not_started', 'not_started', 'not_started'])
        self.assertEqual(len(snapshot['attempts']), 4)
        self.assertEqual(snapshot['attempts'][0]['persisted_xp'], 0)
        self.assertTrue(all(r['persisted_xp'] is None for r in snapshot['attempts'][1:]))


if __name__ == '__main__':
    unittest.main()
