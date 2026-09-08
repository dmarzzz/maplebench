"""Frozen next-cohort preparation and deterministic reservation tests only."""
import copy
from pathlib import Path
import tempfile
import unittest

import full_client_adaptive as adaptive
from full_client_adaptive_evidence import verify_result
from full_client_capture import CAPTURE_DURATION_POLICY
from test_full_client_adaptive import Harness, MODEL


PROFILES = [adaptive.DEFAULT_PROTOCOL['profile'],
    {'id':'bowmaster-v1','class_name':'Bowmaster','level':180,'skill_keys':{
        'PRIMARY_SKILL':'Hurricane','SECONDARY_SKILL':'Arrow Rain','BUFF_1':'Soul Arrow : Bow','BUFF_2':'Sharp Eyes'}},
    {'id':'ice-lightning-v1','class_name':'Ice/Lightning Arch Mage','level':180,'skill_keys':{
        'PRIMARY_SKILL':'Chain Lightning','SECONDARY_SKILL':'Teleport','BUFF_1':'Magic Guard','BUFF_2':'Spell Booster'}}]


class CaptureCohortTests(unittest.TestCase):
    def test_profiles_share_exact_capture_horizon_and_hard_limits(self):
        for profile in PROFILES:
            with self.subTest(profile=profile['id']):
                p=adaptive.capture_cohort_protocol(profile)
                self.assertEqual(p['id'],'full-client-adaptive-pilot-v1')
                self.assertEqual(p['profile'],profile)
                self.assertEqual(p['capture_duration_policy'],CAPTURE_DURATION_POLICY)
                self.assertEqual(p['horizon_policy'],adaptive.FULL_HORIZON_POLICY)
                self.assertEqual(p['max_total_tokens'],240000)
                self.assertEqual((p['wall_seconds'],p['program_seconds'],p['max_api_requests']),(300,20,12))
                self.assertEqual((p['max_output_tokens'],p['max_actions'],p['max_sdk_requests']),(3000,1600,6000))

    def test_recipe_does_not_mutate_or_reidentify_existing_frozen_runs(self):
        previous=copy.deepcopy(adaptive.DEFAULT_PROTOCOL);profile=copy.deepcopy(PROFILES[1])
        old=copy.deepcopy(previous);old['horizon_policy']=copy.deepcopy(adaptive.FULL_HORIZON_POLICY)
        fresh=adaptive.capture_cohort_protocol(profile)
        self.assertNotEqual(adaptive.digest(fresh),adaptive.digest(old))
        fresh['profile']['skill_keys']['PRIMARY_SKILL']='Changed'
        fresh['horizon_policy']['request_timeout_seconds']=1
        fresh['capture_duration_policy']['max_endpoint_gap_ms']=1000
        self.assertEqual(profile,PROFILES[1]);self.assertEqual(adaptive.DEFAULT_PROTOCOL,previous)
        again=adaptive.capture_cohort_protocol(profile)
        self.assertEqual(again['horizon_policy']['request_timeout_seconds'],50)
        self.assertEqual(again['capture_duration_policy']['max_endpoint_gap_ms'],250)
        self.assertEqual(adaptive.DEFAULT_PROTOCOL['max_total_tokens'],120000)

    def test_larger_reservation_allows_more_confirmed_cycles_without_retries_or_clock_extension(self):
        results=[]
        with tempfile.TemporaryDirectory() as root:
            for limit in (120000,240000):
                folder=Path(root)/str(limit);folder.mkdir();h=Harness(folder)
                h.p=adaptive.capture_cohort_protocol(PROFILES[0]);h.p['max_total_tokens']=limit
                h.code='// '+('x'*8000)+"\nawait sdk.pressKeys(['ATTACK'],100);"
                def sleep(seconds):h.now+=seconds
                trace=h.run(sleep=sleep)['trace']
                checked=verify_result(h.result(),folder,protocol=h.p,model=MODEL)
                self.assertEqual(checked['wall_elapsed_ms'],300000)
                self.assertEqual(trace['counters']['api_requests_started'],len(h.api_calls))
                self.assertEqual(trace['counters']['api_responses_confirmed'],len(h.api_calls))
                self.assertLessEqual(trace['counters']['reserved_tokens'],limit)
                self.assertTrue(all(timeout==50 for _,timeout in h.api_calls))
                self.assertEqual(len(h.programs),len(h.api_calls))
                results.append((len(h.api_calls),trace['reason']))
        self.assertGreater(results[1][0],results[0][0])
        self.assertEqual(results[0][1],'token_reservation_limit')
        self.assertEqual(results[1][1],'request_window_closed')


if __name__=='__main__':unittest.main()
