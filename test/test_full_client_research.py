"""Research-reporting fixtures only: no fabricated benchmark evidence."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_research import summarize


class ResearchTests(unittest.TestCase):
    def row(self,ident,**changes):
        value={'id':str(ident)*32,'kind':'trial','mode':'api','requested_model':'gpt-6-astra','status':'completed',
               'score_verification':'runner_verified_receipts_rechecked','attribution':'exact','persisted_xp':0,
               'action_verification':'receipts_rechecked','no_op':False,
               'research':{'protocol_id':'legacy-full-client-v1','class_id':'hero','task_id':'basic_combat',
                           'fixture_fingerprint':'a'*64,'planned':True}}
        value.update(changes);return value

    def test_denominators_include_failures_unknowns_and_unstarted_members(self):
        rows=[self.row(1,persisted_xp=100),self.row(2,status='failed'),
              self.row(3,status='unavailable'),self.row(4,status='not_started'),self.row(5,status='running')]
        cell=summarize({'attempts':rows})['models'][0]['cells'][0]
        self.assertEqual({key:cell[key] for key in ('planned','attempted','valid','failed','unknown','in_progress','not_started')},
                         {'planned':5,'attempted':4,'valid':1,'failed':1,'unknown':1,'in_progress':1,'not_started':1})
        self.assertEqual(cell['mean'],100);self.assertEqual(cell['uncertainty'],'not_estimated')

    def test_signed_zero_noop_and_observed_range_are_preserved(self):
        rows=[self.row(1,persisted_xp=-50),self.row(2,persisted_xp=0,no_op=True),self.row(3,persisted_xp=200)]
        cell=summarize({'attempts':rows})['models'][0]['cells'][0]
        self.assertEqual((cell['valid'],cell['mean'],cell['minimum'],cell['maximum'],cell['no_ops']),(3,50,-50,200,1))
        self.assertFalse(cell['ranked'])

    def test_adaptive_last_cycle_cannot_become_a_verified_whole_run_score(self):
        legacy=self.row(1,persisted_xp=100)
        adaptive=self.row(2,persisted_xp=999999)
        adaptive['research']['protocol_id']='full-client-adaptive-pilot-v1'
        result=summarize({'attempts':[legacy,adaptive]})
        self.assertEqual(len(result['columns']),2)
        cells=result['models'][0]['cells'];self.assertEqual([x['valid'] for x in cells],[1,0])
        self.assertIsNone(cells[1]['mean']);self.assertEqual(cells[1]['unknown'],1)
        self.assertEqual(result['research_target']['horizon_ms'],1800000)
        self.assertEqual(result['research_target']['window_ms'],15000)

    def test_classes_and_fixture_versions_do_not_share_score_cells(self):
        hero=self.row(1,persisted_xp=100);bow=self.row(2,persisted_xp=200);newhero=self.row(3,persisted_xp=300)
        bow['research']['class_id']='bowmaster';newhero['research']['fixture_fingerprint']='b'*64
        result=summarize({'attempts':[hero,bow,newhero]})
        self.assertEqual(len(result['columns']),3)
        self.assertEqual([x['mean'] for x in result['models'][0]['cells']],[100,200,300])

    def test_historical_plan_denominator_is_unknown_and_baselines_do_not_score(self):
        row=self.row(1);row.pop('research');row['comparison_group']='a'*64
        cell=summarize({'attempts':[row]})['models'][0]['cells'][0]
        self.assertIsNone(cell['planned']);self.assertEqual(cell['attempted'],1)
        row['kind']='integration'
        self.assertEqual(summarize({'attempts':[row]})['models'][0]['cells'][0]['valid'],0)

    def test_unknown_protocol_and_unfrozen_inputs_never_gain_scores(self):
        row=self.row(1,persisted_xp=100);row['research']['protocol_id']='future-unaccepted'
        cell=summarize({'attempts':[row]})['models'][0]['cells'][0]
        self.assertIsNone(cell['mean']);self.assertEqual(cell['unknown'],1)
        row['research']['protocol_id']='legacy-full-client-v1';row['research']['fixture_fingerprint']='bad'
        self.assertEqual(summarize({'attempts':[row]})['models'][0]['cells'][0]['valid'],0)


if __name__=='__main__':unittest.main()
