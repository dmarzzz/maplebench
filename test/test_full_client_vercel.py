"""Mock Vercel/HTTP responses only. No deployment or model requests."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import full_client_vercel as driver
import full_client_publication as publication
import test_full_client_publication as fixtures


class VercelPublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PublicationTests();self.fixture.setUp()
        for i in range(4):self.fixture.attempt(i,xp=i*100)
        prepared=self.fixture.prepare(replace_archive=True)
        self.package=Path(prepared['package']);self.content=prepared['content_sha256']
        self.payload=self.fixture.root/'public-payload';shutil.copytree(prepared['site'],self.payload)
        self.inventory=self.fixture.config/'payload-inventory.json'
        self.save_inventory()
        self.link=self.fixture.config/'project.json'
        self.link_value={'projectId':'prj_SYNTHETIC1234','orgId':'team_SYNTHETIC1234','projectName':'synthetic-maplebench'}
        self.link.write_text(json.dumps(self.link_value));self.link_sha=driver.digest(self.link.read_bytes())
        self.base='https://synthetic-maplebench.vercel.app';self.calls=[];self.fetches=[];self.metadata={}
        self.ident='dpl_SYNTHETIC123456';self.visible=True;self.duplicate=False;self.wrong_alias=False
        self.lose_reply=False;self.bad_content=False;self.bad_range=False

    def tearDown(self):self.fixture.tearDown()

    def save_inventory(self):
        self.files={p.relative_to(self.payload).as_posix():{'bytes':p.stat().st_size,'sha256':driver.digest(p.read_bytes())}
                    for p in self.payload.rglob('*') if p.is_file()}
        self.inventory.write_text(json.dumps({'files':self.files}));self.inventory_sha=driver.digest(self.inventory.read_bytes())

    def cli(self,executable,args,cwd,deadline):
        self.calls.append(list(args));self.assertNotIn('--token',args)
        self.assertEqual(json.loads((Path(cwd)/'.vercel/project.json').read_text()),self.link_value)
        if args[0]=='deploy':
            # A real driver writes both receipts before calling the CLI.
            self.assertTrue((self.package/'publication-intent.json').is_file())
            self.assertTrue((self.package/'vercel-submission.json').is_file())
            self.metadata={args[i+1].split('=',1)[0]:args[i+1].split('=',1)[1]
                           for i,arg in enumerate(args) if arg=='--meta'}
            if self.lose_reply:raise OSError('PRIVATE CLI ERROR MUST NOT BE EXPORTED')
            return {'status':'ok','deployment':{'id':self.ident,'url':'https://synthetic-deployment.vercel.app'}}
        if args[0]=='list':
            row={'id':self.ident,'name':self.link_value['projectName'],'target':'production',
                 'readyState':'READY','url':'synthetic-deployment.vercel.app','meta':copy.deepcopy(self.metadata)}
            return {'deployments':([row,row] if self.duplicate else [row]) if self.visible else [],'pagination':{}}
        self.assertEqual(args[0],'inspect')
        return {'id':self.ident,'name':self.link_value['projectName'],'target':'production','readyState':'READY',
                'aliases':['wrong.vercel.app' if self.wrong_alias else 'synthetic-maplebench.vercel.app']}

    def fetch(self,url,maximum,headers,deadline):
        self.fetches.append((url,headers));name=url[len(self.base)+1:]
        data=(self.payload/name).read_bytes()
        if headers.get('Range'):
            start,end=headers['Range'][6:].split('-');self.assertEqual(start,'0');end=int(end)
            return {'status':200 if self.bad_range else 206,'headers':{'content-range':f'bytes 0-{end}/{len(data)}'},
                    'bytes':end+1,'sha256':driver.digest(data[:end+1])}
        return {'status':200,'headers':{},'bytes':len(data),'sha256':'0'*64 if self.bad_content else driver.digest(data)}

    def publish(self):
        return driver.publish(self.package,self.content,self.payload,self.inventory,self.inventory_sha,
            self.link,self.link_sha,self.base,executable='/usr/bin/true',run_cli=self.cli,fetch=self.fetch)

    def test_url_only_cli_list_resolves_exact_identity_without_resubmission(self):
        original=self.cli
        def current_cli(executable,args,cwd,deadline):
            value=original(executable,args,cwd,deadline)
            if args[0]=='list':
                for row in value['deployments']:del row['id']
            if args[0]=='inspect':value['url']='synthetic-deployment.vercel.app'
            return value
        self.cli=current_cli
        result=self.publish()
        self.assertEqual(result['status'],'published')
        self.assertEqual([c[0] for c in self.calls],['deploy','list','inspect','inspect'])
        self.assertEqual(self.calls[2][1],'synthetic-deployment.vercel.app')
        self.assertEqual(self.calls[3][1],self.ident)
        self.publish()
        self.assertEqual(sum(c[0]=='deploy' for c in self.calls),1)

    def test_url_only_reconciliation_refuses_changed_inspected_url(self):
        original=self.cli
        def changed_cli(executable,args,cwd,deadline):
            value=original(executable,args,cwd,deadline)
            if args[0]=='list':
                for row in value['deployments']:del row['id']
            if args[0]=='inspect':value['url']='different-deployment.vercel.app'
            return value
        self.cli=changed_cli
        self.assertEqual(self.publish()['status'],'uncertain')
        self.assertEqual(self.publish()['status'],'uncertain')
        self.assertEqual(sum(c[0]=='deploy' for c in self.calls),1)
        self.assertFalse(self.fetches)

    def test_one_submission_public_bytes_ranges_and_exact_ids_then_idempotent(self):
        before=json.loads((self.payload/'results.json').read_text())['attempts']
        value=self.publish();self.assertEqual(value['status'],'published')
        self.assertEqual([c[0] for c in self.calls],['deploy','list','inspect'])
        proof=json.loads((self.package/'vercel-public-verification.json').read_text())
        self.assertEqual(len(proof['public_verification']['files']),len(self.files)-1)
        self.assertEqual(len(proof['public_verification']['video_ranges']),4)
        self.assertTrue(proof['public_verification']['anonymous_access']);self.assertEqual(proof['target_latency_ms'],60000)
        self.assertEqual(json.loads((self.payload/'results.json').read_text())['attempts'],before)
        again=self.publish();self.assertEqual(again['status'],'published');self.assertEqual(len(self.calls),3)
        self.assertFalse(again['deployment_allowed'])

    def test_lost_reply_reconciles_existing_metadata_without_resubmission(self):
        self.lose_reply=True
        self.assertEqual(self.publish()['status'],'published')
        self.assertEqual(sum(c[0]=='deploy' for c in self.calls),1)

    def test_uncertain_outcome_can_be_reconciled_later_never_redeployed(self):
        self.lose_reply=True;self.visible=False
        first=self.publish();self.assertEqual(first['status'],'uncertain')
        self.assertEqual(first['reason'],'deployment_outcome_uncertain')
        self.visible=True
        self.assertEqual(self.publish()['status'],'published')
        self.assertEqual(sum(c[0]=='deploy' for c in self.calls),1)

    def test_two_metadata_matches_are_ambiguous_and_never_replayed(self):
        self.duplicate=True
        self.assertEqual(self.publish()['reason'],'deployment_identity_ambiguous')
        self.publish();self.assertEqual(sum(c[0]=='deploy' for c in self.calls),1)
        self.assertEqual(self.fetches,[])

    def test_wrong_public_alias_does_not_claim_success(self):
        self.wrong_alias=True
        self.assertEqual(self.publish()['reason'],'deployment_not_public_ready')
        self.assertFalse((self.package/'publication-complete.json').exists());self.assertEqual(self.fetches,[])

    def test_corrupt_public_bytes_and_missing_ranges_remain_uncertain(self):
        self.bad_content=True
        self.assertEqual(self.publish()['reason'],'public_content_mismatch')
        self.bad_content=False;self.bad_range=True
        self.assertEqual(self.publish()['reason'],'public_video_range_mismatch')
        self.bad_range=False;self.assertEqual(self.publish()['status'],'published')
        self.assertEqual(sum(c[0]=='deploy' for c in self.calls),1)

    def test_lost_completion_write_reuses_durable_public_proof(self):
        with patch.object(driver,'record_deployment',side_effect=OSError('uncertain write')):
            self.assertEqual(self.publish()['status'],'uncertain')
        proof=(self.package/'vercel-public-verification.json').read_bytes()
        self.assertEqual(self.publish()['status'],'published')
        self.assertEqual((self.package/'vercel-public-verification.json').read_bytes(),proof)
        self.assertEqual(sum(c[0]=='deploy' for c in self.calls),1)

    def test_existing_manual_intent_is_not_assumed_to_be_an_unsubmitted_job(self):
        publication.claim_publication(self.package,self.content)
        self.assertEqual(self.publish()['reason'],'existing_intent_requires_reconciliation')
        self.assertEqual(self.calls,[])

    def test_private_extra_files_and_tampered_payload_refuse_before_cli(self):
        secret=self.payload/'private-account.txt';secret.write_text('PRIVATE DATA')
        with self.assertRaisesRegex(ValueError,'unexpected_public_payload_file'):self.publish()
        secret.unlink();(self.payload/'results.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'public_payload_changed'):self.publish()
        self.assertEqual(self.calls,[])

    def test_inventory_cannot_authorize_private_file_names_or_relabel_cohort_ids(self):
        (self.payload/'account-export.json').write_text('{}');self.save_inventory()
        with self.assertRaisesRegex(ValueError,'invalid_public_payload_file'):self.publish()
        (self.payload/'account-export.json').unlink();(self.payload/'results.json').write_text('{}');self.save_inventory()
        with self.assertRaisesRegex(ValueError,'cohort_payload_binding_mismatch'):self.publish()
        self.assertEqual(self.calls,[])

    def test_changed_stage_or_project_link_cannot_be_used_for_reconciliation(self):
        self.visible=False;self.publish()
        marker=json.loads((self.package/'vercel-submission.json').read_text());stage=Path(marker['stage'])
        (stage/'secret.txt').write_text('private')
        with self.assertRaisesRegex(ValueError,'unexpected_staged_file'):self.publish()
        (stage/'secret.txt').unlink();(stage/'.vercel/project.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'staged_project_link_changed'):self.publish()
        self.assertEqual(sum(c[0]=='deploy' for c in self.calls),1)

    def test_project_and_public_origin_are_explicit_and_bounded(self):
        for value in ('http://localhost:8000','https://user:secret@synthetic-maplebench.vercel.app',
                      'https://example.com','https://synthetic-maplebench.vercel.app/private'):
            with self.assertRaises(ValueError):driver.origin(value)
        self.link.write_text(json.dumps(self.link_value|{'orgId':'bad'}));self.link_sha=driver.digest(self.link.read_bytes())
        with self.assertRaisesRegex(ValueError,'invalid_existing_project_link'):self.publish()
        self.assertEqual(self.calls,[])

    def test_cross_origin_redirect_is_refused(self):
        from urllib.request import Request
        request=Request(self.base+'/results.json')
        with self.assertRaisesRegex(ValueError,'public_redirect_refused'):
            driver.SameOriginRedirect().redirect_request(request,None,302,'redirect',{},'https://private.invalid/token')

    def test_completed_receipt_cannot_claim_another_project_or_public_origin(self):
        self.assertEqual(self.publish()['status'],'published')
        self.base='https://another-public-project.vercel.app'
        with self.assertRaisesRegex(ValueError,'publication_binding_changed'):self.publish()
        self.assertEqual(sum(c[0]=='deploy' for c in self.calls),1)

    def test_elapsed_preparation_refuses_before_claim_and_removes_unsubmitted_stage(self):
        with patch.object(driver.time,'monotonic',side_effect=[0,1,301]):
            with self.assertRaisesRegex(ValueError,'publication_deadline'):self.publish()
        self.assertFalse((self.package/'publication-intent.json').exists())
        self.assertEqual(list(self.package.glob('.vercel-payload-*')),[]);self.assertEqual(self.calls,[])

    def test_progress_mount_preserves_root_and_all_four_planned_outcomes(self):
        self.fixture.tearDown();self.fixture=fixtures.PublicationTests();self.fixture.setUp()
        self.fixture.attempt(0,xp=1500);prepared=self.fixture.prepare()
        self.package=Path(prepared['package']);self.content=prepared['content_sha256']
        self.payload=self.fixture.root/'public-payload';self.payload.mkdir()
        (self.payload/'index.html').write_text('SYNTHETIC APPROVED ARCHIVE')
        (self.payload/'results.json').write_text('{"synthetic_archive":true}')
        target=prepared['target_path'].strip('/');shutil.copytree(prepared['site'],self.payload/target)
        self.inventory=self.fixture.config/'payload-inventory.json';self.save_inventory()
        self.link=self.fixture.config/'project.json';self.link.write_text(json.dumps(self.link_value))
        self.link_sha=driver.digest(self.link.read_bytes())
        value=self.publish();self.assertEqual(value['status'],'published')
        self.assertEqual(value['url'],self.base+prepared['target_path'])
        rows=json.loads((self.payload/target/'results.json').read_text())['attempts']
        self.assertEqual(len(rows),4);self.assertEqual(sum(row['status']=='not_started' for row in rows),3)
        self.assertEqual((self.payload/'results.json').read_text(),'{"synthetic_archive":true}')

    def test_metadata_mismatch_and_truncated_listing_never_claim_a_deployment(self):
        original=self.cli
        def changed(executable,args,cwd,deadline):
            value=original(executable,args,cwd,deadline)
            if args[0]=='list':value['deployments'][0]['meta'][driver.META_CONTENT]='0'*64
            return value
        with patch.object(self,'cli',side_effect=changed):
            self.assertEqual(self.publish()['reason'],'deployment_outcome_uncertain')
        def paged(executable,args,cwd,deadline):
            value=original(executable,args,cwd,deadline)
            if args[0]=='list':value['pagination']={'next':12345}
            return value
        with patch.object(self,'cli',side_effect=paged):
            self.assertEqual(self.publish()['reason'],'deployment_reconciliation_incomplete')
        self.assertEqual(sum(c[0]=='deploy' for c in self.calls),1);self.assertEqual(self.fetches,[])

    def test_transferred_package_needs_no_source_host_evidence_paths(self):
        transferred=self.fixture.root/'transferred-package'
        shutil.copytree(self.package,transferred);shutil.rmtree(self.package);self.package=transferred
        shutil.rmtree(self.fixture.fixture.attempts);self.fixture.path.unlink()
        self.assertEqual(self.publish()['status'],'published')
        self.assertEqual(sum(c[0]=='deploy' for c in self.calls),1)

    def test_lost_submission_receipt_write_never_launches_and_requires_reconciliation(self):
        original=driver.write_new
        def lost(path,*args,**kwargs):
            if Path(path).name=='vercel-submission.json':raise OSError('lost durable write')
            return original(path,*args,**kwargs)
        with patch.object(driver,'write_new',side_effect=lost):
            self.assertEqual(self.publish()['reason'],'submission_receipt_unavailable')
        self.assertEqual(self.publish()['reason'],'existing_intent_requires_reconciliation')
        self.assertEqual(self.calls,[])

    def test_cli_cannot_use_ambient_project_override_and_keeps_auth_out_of_arguments(self):
        from unittest.mock import Mock
        def spawn(args,**kwargs):
            self.assertNotIn('--token',args)
            for prefix in ('VERCEL_','NOW_'):
                for name in ('ORG_ID','PROJECT_ID'):self.assertNotIn(prefix+name,kwargs['env'])
            self.assertEqual(kwargs['env']['VERCEL_TOKEN'],'synthetic-local-auth')
            kwargs['stdout'].write(b'{"ok":true}');kwargs['stdout'].flush()
            process=Mock();process.poll.return_value=0;process.returncode=0;return process
        with patch.dict(os.environ,{'VERCEL_ORG_ID':'ambient','VERCEL_PROJECT_ID':'ambient',
                                  'NOW_ORG_ID':'ambient','NOW_PROJECT_ID':'ambient','VERCEL_TOKEN':'synthetic-local-auth'}), \
                patch.object(driver.subprocess,'Popen',side_effect=spawn):
            value=driver.cli(Path('/usr/bin/true'),['list'],self.package,driver.time.monotonic()+10)
        self.assertEqual(value,{'ok':True})


if __name__=='__main__':unittest.main()
