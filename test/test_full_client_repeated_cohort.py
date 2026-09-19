"""Repeated cohort projections from synthetic receipts; no model or native run."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_full_client_adaptive_publication as adaptive_fixture
import full_client_publication as publication
import full_client_catalog as catalog
from full_client_research import operational_reliability


class RepeatedCohortTests(unittest.TestCase):
    def setUp(self):
        self.f=adaptive_fixture.AdaptivePublicationTests();self.f.setUp()
        f=self.f;models=list(f.models);first=copy.deepcopy(f.plan['entries'][0])
        f.ids=[format(i+100,'032x') for i in range(16)]
        f.models=[models[(i%4+i//4)%4] for i in range(16)]
        entries=[]
        for i in range(16):
            entry=copy.deepcopy(first);entry.update(ordinal=i,attempt_id=f.ids[i],model=f.models[i],repetition=i//4+1)
            entry['spec']['model']=f.models[i];entry['spec_sha256']=publication.digest(publication.encoded(entry['spec']))
            entries.append(entry)
        f.plan.update(repetitions=4,models=models,entries=entries);self.save_plan()

    def tearDown(self):self.f.tearDown()

    def save_plan(self):
        f=self.f;f.path.write_bytes(publication.encoded(f.plan));f.plan_sha=publication.digest(f.path.read_bytes())

    def test_all_sixteen_samples_and_clean_groups_are_published_without_ranking(self):
        f=self.f
        for i in range(16):f.attempt(i,(-50,0,100,9000)[i%4])
        value,snapshot=f.prepare()
        self.assertTrue(value['cohort_complete']);self.assertEqual(snapshot['cohort']['planned'],16)
        self.assertEqual(len(snapshot['comparisons'][0]['models']),4)
        for row in snapshot['research_matrix']['models']:
            cell=row['cells'][0]
            self.assertEqual(cell['planned'],4);self.assertEqual(cell['valid'],4)
            self.assertEqual(sorted(cell['samples']),[-50,0,100,9000]);self.assertEqual(cell['median'],50)
            self.assertFalse(cell['ranked'])
        self.assertTrue(snapshot['cohort']['reliability']['gate_passed'])
        self.assertEqual(snapshot['cohort']['reliability']['consecutive_clean_groups'],4)
        validated=catalog.cohort(Path(value['package']),value['content_sha256'])
        self.assertTrue(validated['complete'])

    def test_partial_group_keeps_full_denominator_and_breaks_consecutive_gate(self):
        f=self.f
        for i in range(12):f.attempt(i,0)
        _,snapshot=f.prepare();reliability=snapshot['cohort']['reliability']
        self.assertEqual(snapshot['cohort']['verified'],12)
        self.assertFalse(reliability['gate_passed'])
        self.assertEqual(reliability['groups'][-1]['causes'],{'not_started':4})
        for row in snapshot['research_matrix']['models']:
            self.assertEqual(row['cells'][0]['planned'],4);self.assertEqual(row['cells'][0]['valid'],3)

    def test_order_repetition_duplicates_and_missing_rows_are_rejected(self):
        original=copy.deepcopy(self.f.plan)
        for mutate in (lambda p:p['entries'][4].__setitem__('model',p['models'][0]),
                       lambda p:p['entries'][4].__setitem__('repetition',1),
                       lambda p:p['entries'][4].__setitem__('attempt_id',p['entries'][0]['attempt_id']),
                       lambda p:p['entries'].pop()):
            self.f.plan=copy.deepcopy(original);mutate(self.f.plan);self.save_plan()
            with self.assertRaises(ValueError):publication.selected_plan(self.f.path,self.f.plan_sha)

    def test_two_models_from_each_provider_are_accepted_without_forging_receipts(self):
        f=self.f;names=['gpt-6-astra','gpt-5.6-sol','claude-opus-5','claude-sonnet-5'];f.plan['models']=names
        for i,entry in enumerate(f.plan['entries']):
            entry['model']=names[(i%4+i//4)%4];entry['spec']['model']=entry['model']
            entry['spec_sha256']=publication.digest(publication.encoded(entry['spec']))
        self.save_plan();publication.selected_plan(f.path,f.plan_sha)
        _,snapshot=f.prepare()
        self.assertEqual(snapshot['cohort']['planned'],16);self.assertEqual(snapshot['cohort']['verified'],0)


if __name__=='__main__':unittest.main()
