"""Public fixture binding checks; mocked native verifier, no game or API calls."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

import test_full_client_hero_qualification_public as native_fixture
import full_client_hero_qualification_public as projection
import full_client_publication as publication


class NativePublicationBindingTests(unittest.TestCase):
    def setUp(self):
        self.fixture=native_fixture.PublicHeroQualificationTests();self.fixture.setUp()
        pins,receipt,qualified,control=self.fixture.bundle()
        with patch.object(projection,'verify_events',return_value=qualified), \
                patch.object(projection,'verify_control_result',return_value=control):
            self.value=projection.project_qualification(self.fixture.root,receipt,
                native_contract=self.fixture.native,expected_pins=pins)
        self.site=self.fixture.root/'public';self.site.mkdir()
        raw=publication.encoded(self.value)
        (self.site/'native-qualification.json').write_bytes(raw)
        self.binding={'path':'native-qualification.json','sha256':publication.digest(raw),
            'baseline_sha256':pins['baseline_sha256'],
            'runtime_manifest_sha256':pins['runtime_manifest_sha256'],
            'scenario_sha256':'f'*64,'budgets':{'controller_seconds':300}}
        fingerprint=publication.digest(publication.encoded({
            'scenario':self.binding['scenario_sha256'],'baseline':pins['baseline_sha256'],
            'runtime_manifest':pins['runtime_manifest_sha256'],'budgets':self.binding['budgets']}))
        self.snapshot={'native_qualification':self.value,'attempts':[{'research':{
            'class_id':'hero','fixture_fingerprint':fingerprint}}]}
        self.save_snapshot()
        self.content={'protocol':publication.ADAPTIVE_PROTOCOL,'native_qualification':self.binding,
            'files':{'native-qualification.json':{'sha256':self.binding['sha256'],'bytes':len(raw)}}}

    def tearDown(self):self.fixture.tearDown()
    def save_snapshot(self):
        (self.site/'results.json').write_bytes(publication.encoded(self.snapshot))

    def test_valid_native_check_is_bound_to_identical_scored_fixture(self):
        value=publication.verify_qualification_binding(self.site,self.content)
        self.assertEqual(value['status'],'core_toolkit_effects_qualified')
        self.assertEqual(len(value['available_skills']),17)
        self.assertEqual(len(value['qualified_skills']),10)

    def test_fixture_mismatch_and_non_dict_claim_are_refused(self):
        original=copy.deepcopy(self.snapshot)
        self.snapshot['attempts'][0]['research']['fixture_fingerprint']='0'*64;self.save_snapshot()
        with self.assertRaisesRegex(ValueError,'native_qualification_fixture_mismatch'):
            publication.verify_qualification_binding(self.site,self.content)
        self.snapshot=original;self.snapshot['native_qualification']='untrusted';self.save_snapshot()
        with self.assertRaisesRegex(ValueError,'native_qualification_file_mismatch'):
            publication.verify_qualification_binding(self.site,self.content)

    def test_detached_qualification_file_or_snapshot_is_refused(self):
        content=copy.deepcopy(self.content);del content['native_qualification']
        with self.assertRaisesRegex(ValueError,'native_qualification_binding_missing'):
            publication.verify_qualification_binding(self.site,content)
        del self.snapshot['native_qualification'];self.save_snapshot()
        with self.assertRaisesRegex(ValueError,'native_qualification_binding_missing'):
            publication.verify_qualification_binding(self.site,self.content)
