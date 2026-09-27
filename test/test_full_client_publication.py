"""Synthetic public packages; no Vercel, model, browser, database or services."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_full_client_dashboard as fixtures
import full_client_publication as publication


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.DashboardTests();self.fixture.setUp()
        self.root=self.fixture.root;self.output=self.root/'packages';self.output.mkdir()
        self.config=self.root/'config';self.config.mkdir();self.path=self.config/'plan.json'
        self.ids=[str(x)*32 for x in range(1,5)]
        self.models=['gpt-6-astra','gpt-5.6-sol','gpt-5.6-terra','gpt-5.6-luna']
        budgets={'total_seconds':90,'operation_seconds':60,'controller_seconds':24,
                 'max_actions':80,'max_api_requests':1,'max_output_tokens':3000,'max_total_tokens':30000}
        fixture={'id':'synthetic','scenario':{'sha256':'a'*64},'baseline':{'sha256':'b'*64},
                 'runtime_manifest':{'sha256':'f'*64},'adapter_fingerprint':'9'*64,'budgets':budgets}
        entries=[]
        for ordinal,(ident,model) in enumerate(zip(self.ids,self.models)):
            spec={'schema_version':1,'model':model,'scenario_fingerprint':'a'*64,'baseline_sha256':'b'*64,'budgets':budgets}
            entries.append({'ordinal':ordinal,'model':model,'attempt_id':ident,'fixture_id':'synthetic',
                            'repetition':1,'spec':spec,'spec_sha256':publication.digest(publication.encoded(spec))})
        self.plan={'schema_version':1,'models':self.models,'repetitions':1,'fixtures':[fixture],'entries':entries,
                   'private_host_path':'/private/never-public','password':'never-public-plan-secret'}
        self.save_plan()

    def tearDown(self):self.fixture.tearDown()

    def save_plan(self):
        raw=publication.encoded(self.plan);self.path.write_bytes(raw);self.plan_sha=publication.digest(raw)

    def attempt(self,index,status='completed',xp=0,no_op=False):
        ident=self.ids[index];entry=self.plan['entries'][index]
        folder,journal,result=self.fixture.attempt(ident,model=entry['model'],status=status,xp=xp)
        journal['request']=copy.deepcopy(entry['spec']);journal['adapter_fingerprint']='9'*64
        journal['events'][-1]['at_ms']+=index
        if no_op:
            self.fixture.execution(result,acknowledged=0,attempts=0)
            self.fixture.save_result(folder,journal,result)
        video=b'SYNTHETIC GAMEPLAY '+ident.encode();video_sha=hashlib.sha256(video).hexdigest()
        (folder/'video.webm').write_bytes(video)
        recording=json.loads((folder/'recording.json').read_text())
        recording.update(sha256=video_sha,interrupted=False,post_render_capture=True)
        refs=journal['receipts']['collect_final']['artifacts']
        refs['recording']=self.fixture.write(folder/'recording.json',recording)
        refs['video']={'path':'video.webm','sha256':video_sha}
        self.fixture.write(folder/'journal.json',journal)
        return folder,journal,result

    def prepare(self,**kwargs):
        return publication.prepare_package(self.path,self.plan_sha,self.fixture.attempts,self.output,**kwargs)

    def snapshot(self,result):return json.loads((Path(result['site'])/'results.json').read_text())

    def test_first_success_publishes_with_all_planned_models_and_no_private_data(self):
        self.attempt(0,xp=0,no_op=True)
        self.fixture.attempt('a'*32)  # A previous attempt must not leak into this cohort.
        result=self.prepare();snapshot=self.snapshot(result)
        self.assertEqual([x['id'] for x in snapshot['attempts']],self.ids)
        self.assertEqual([x['status'] for x in snapshot['attempts']],['completed','not_started','not_started','not_started'])
        self.assertEqual(snapshot['attempts'][0]['persisted_xp'],0)
        self.assertTrue(snapshot['attempts'][0]['no_op'])
        self.assertFalse(result['archive_replacement']);self.assertFalse(result['cohort_complete'])
        self.assertEqual(result['target_path'],'/cohorts/'+self.plan_sha[:16]+'/')
        text=json.dumps(snapshot)
        for forbidden in ('private-password-marker','secret-host','private_account_id','never-public'):
            self.assertNotIn(forbidden,text)
        self.assertEqual([p.name for p in (Path(result['site'])/'recordings').iterdir()],[self.ids[0]+'.webm'])
        self.assertTrue(snapshot['attempts'][0]['recording']['url'].startswith('./recordings/'))

    def test_zero_negative_and_noops_survive_final_curation(self):
        originals=[]
        for index,xp in enumerate((0,-50,100,9000)):
            folder,_,_=self.attempt(index,xp=xp,no_op=index==0)
            originals.append((folder/'journal.json',(folder/'journal.json').read_bytes()))
        self.fixture.attempt('a'*32,xp=999999)
        result=self.prepare(replace_archive=True);snapshot=self.snapshot(result)
        self.assertTrue(result['cohort_complete']);self.assertTrue(result['archive_replacement'])
        self.assertEqual(result['target_path'],'/')
        self.assertEqual([row['persisted_xp'] for row in snapshot['attempts']],[0,-50,100,9000])
        self.assertFalse(snapshot['ranked']);self.assertEqual(len(snapshot['comparisons']),1)
        self.assertEqual(len(snapshot['comparisons'][0]['attempt_ids']),4)
        self.assertEqual(snapshot['featured_run_id'],self.ids[3])
        for path,before in originals:self.assertEqual(path.read_bytes(),before)

    def test_incomplete_failed_uncertain_and_corrupt_outcomes_are_not_omitted(self):
        self.attempt(0,xp=10)
        folder,journal,_=self.attempt(1,status='failed');journal['api_outcome']='uncertain'
        self.fixture.write(folder/'journal.json',journal)
        folder,_,_=self.attempt(2);(folder/'journal.json').write_text('{bad')
        snapshot=self.snapshot(self.prepare())
        self.assertEqual([x['status'] for x in snapshot['attempts']],['completed','failed','unavailable','not_started'])
        self.assertEqual(snapshot['attempts'][1]['api_outcome'],'uncertain')
        self.assertIsNone(snapshot['attempts'][1]['persisted_xp'])
        with self.assertRaisesRegex(ValueError,'four_verified_recordings'):
            self.prepare(replace_archive=True)

    def test_bad_video_does_not_hide_score_or_block_another_success(self):
        bad,_,_=self.attempt(0,xp=0);(bad/'video.webm').write_bytes(b'CORRUPT')
        self.attempt(1,xp=50)
        snapshot=self.snapshot(self.prepare())
        self.assertEqual(snapshot['attempts'][0]['persisted_xp'],0)
        self.assertIsNone(snapshot['attempts'][0]['recording'])
        self.assertEqual(snapshot['attempts'][0]['recording_publication'],'unavailable')
        self.assertIsNotNone(snapshot['attempts'][1]['recording'])

    def test_plan_hash_models_and_exact_frozen_request_are_required(self):
        with self.assertRaisesRegex(ValueError,'hash_mismatch'):
            publication.prepare_package(self.path,'0'*64,self.fixture.attempts,self.output)
        self.plan['models'][1]=self.plan['models'][0];self.save_plan()
        with self.assertRaisesRegex(ValueError,'four_model_plan'):
            self.prepare()

    def test_mismatched_request_or_runtime_cannot_become_a_cohort_score(self):
        folder,journal,_=self.attempt(0)
        journal['request']['budgets']['controller_seconds']=23;self.fixture.write(folder/'journal.json',journal)
        folder,journal,_=self.attempt(1)
        journal['receipts']['collect_final']['artifacts']['runtime_manifest']['sha256']='e'*64
        self.fixture.write(folder/'journal.json',journal)
        rows=self.snapshot(self.prepare())['attempts']
        self.assertEqual([x['status'] for x in rows[:2]],['unavailable','unavailable'])
        self.assertTrue(all(x['persisted_xp'] is None and x['recording'] is None for x in rows[:2]))

    def test_identical_content_reuses_package_and_new_success_changes_digest(self):
        self.attempt(0);first=self.prepare();path=Path(first['site'])/'results.json';stamp=path.stat().st_mtime_ns
        second=self.prepare()
        self.assertEqual(first,second);self.assertEqual(path.stat().st_mtime_ns,stamp)
        self.attempt(1);third=self.prepare();self.assertNotEqual(first['content_sha256'],third['content_sha256'])
        self.assertTrue(Path(first['site']).is_dir())
        self.assertFalse(list(self.output.glob('.cohort-*')))

    def test_existing_package_corruption_or_extra_private_files_refuses_reuse(self):
        self.attempt(0);result=self.prepare();site=Path(result['site'])
        (site/'extra-private.txt').write_text('MUST NOT DEPLOY')
        with self.assertRaisesRegex(ValueError,'unexpected_public_file'):self.prepare()
        (site/'extra-private.txt').unlink();(site/'results.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'package_content_changed'):self.prepare()

    def test_one_deployment_claim_then_reconcile_exact_public_bytes(self):
        self.attempt(0);result=self.prepare();package=Path(result['package']);content=result['content_sha256']
        first=publication.claim_publication(package,content);second=publication.claim_publication(package,content)
        self.assertTrue(first['deployment_allowed']);self.assertFalse(second['deployment_allowed'])
        self.assertEqual(second['publication_state'],'pending_reconciliation')
        self.assertEqual(self.prepare()['publication_state'],'pending_reconciliation')
        url='https://synthetic.vercel.app'+result['target_path']
        with self.assertRaisesRegex(ValueError,'verification_required'):
            publication.record_deployment(package,content,'dpl_SYNTHETIC123',url,'a'*64)
        value=publication.record_deployment(package,content,'dpl_SYNTHETIC123',url,content)
        self.assertEqual(publication.record_deployment(package,content,'dpl_SYNTHETIC123',url,content),value)
        self.assertEqual(self.prepare()['publication_state'],'published')
        self.assertFalse(publication.claim_publication(package,content)['deployment_allowed'])
        with self.assertRaisesRegex(ValueError,'receipt_conflict'):
            publication.record_deployment(package,content,'dpl_DIFFERENT123',url,content)

    def test_unclaimed_deployment_and_private_directory_overlap_are_refused(self):
        result=self.prepare();package=Path(result['package']);content=result['content_sha256']
        with self.assertRaisesRegex(ValueError,'intent_required'):
            publication.record_deployment(package,content,'dpl_SYNTHETIC123','https://synthetic.vercel.app'+result['target_path'],content)
        with self.assertRaisesRegex(ValueError,'outside_publication'):
            publication.prepare_package(self.path,self.plan_sha,self.fixture.attempts,self.root)

    def test_symlink_video_never_copies_an_unrelated_file(self):
        folder,_,_=self.attempt(0);(folder/'video.webm').unlink()
        secret=self.root/'private-data';secret.write_text('MUST STAY PRIVATE')
        (folder/'video.webm').symlink_to(secret)
        row=self.snapshot(self.prepare())['attempts'][0]
        self.assertIsNone(row['recording']);self.assertEqual(row['persisted_xp'],0)
        self.assertEqual(secret.read_text(),'MUST STAY PRIVATE')

    def test_class_profile_is_declared_and_cannot_relabel_legacy_evidence_as_adaptive(self):
        self.attempt(0)
        profile={'protocol_id':'legacy-full-client-v1','class_id':'hero','task_id':'basic_combat'}
        result=self.prepare(research_profile=profile);matrix=self.snapshot(result)['research_matrix']
        self.assertEqual(matrix['columns'][0]['class_label'],'Hero')
        self.assertEqual(matrix['models'][0]['cells'][0]['planned'],1)
        self.assertEqual(matrix['models'][1]['cells'][0]['not_started'],1)
        profile['protocol_id']='full-client-adaptive-pilot-v1'
        with self.assertRaisesRegex(ValueError,'legacy_research_profile_required'):
            self.prepare(research_profile=profile)


if __name__=='__main__':unittest.main()
