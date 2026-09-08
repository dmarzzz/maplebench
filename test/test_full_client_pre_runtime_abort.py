import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import full_client_pre_runtime_abort as abort
import full_client_operation_gate as gate

class AbortTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.root.chmod(0o700)
        self.attempts=self.root/'attempts';self.attempts.mkdir(mode=0o700)
        self.ids=['1'*32,'2'*32,'3'*32,'4'*32];self.op='a'*32
        self.gate=gate.initialize_registry(self.attempts,owner_uid=__import__('os').geteuid())
        self.folder=self.attempts/'.pre-runtime-aborts'/self.op;self.folder.mkdir(parents=True,mode=0o700);self.folder.parent.chmod(0o700)
        a=self.attempts/self.ids[0];a.mkdir(mode=0o700)
        shapes=[('attempt_created',None,None),('operation_pending','status',None),('recovery_required',None,'invalid_limit_timeout_seconds'),('recovery_started',None,None),('operation_pending','status',None),('operation_returned','status',None),('operation_pending','cleanup',None),('recovery_required',None,'orchestrator_identity_mismatch')]
        events=[]
        for i,(kind,operation,code) in enumerate(shapes):
            e={'sequence':i,'kind':kind,'at_ms':i}
            if operation:e['operation']=operation
            if code:e.update(code=code,phase='status' if i==2 else 'cleanup')
            if i==3:e['interrupted_phase']='status'
            events.append(e)
        self.journal={'schema_version':1,'attempt_id':self.ids[0],'status':'failed','api_outcome':'not_started','charged_usage':{'api_requests':0,'total_tokens':0},'publication_eligible':False,'phase':'cleanup','phase_status':'pending','failure_code':'orchestrator_identity_mismatch','events':events,'receipts':{'status':dict(account_offline=True,controller_idle=True,ownership_conflict=False,queue_idle=True,ready=True,server_stopped=True)},'request':{},'adapter_fingerprint':'f'*64}
        journal=self.write(a/'journal.json',self.journal)
        snapshot=self.write(self.root/'snapshot.json',{})
        runtime=self.write(self.root/'runtime.json',{'baseline':{},'baseline_snapshot':snapshot,'runtime_manifest':{}})
        adapter=self.write(self.root/'adapter.json',{'argv':['python','script','--config',runtime['path']]})
        plan=self.write(self.root/'plan.json',{'runner':{'state_root':str(self.attempts)},'entries':[{'attempt_id':i,'fixture_id':'fixture','spec':{}} for i in self.ids],'fixtures':[{'id':'fixture','adapter_config':adapter,'adapter_fingerprint':'f'*64,'baseline':{},'runtime_manifest':{}}]})
        source=[self.write(self.root/('source'+str(i)+'.json'),{}) for i in range(3)]
        authority=self.write(self.root/'authority.json',{'schema_version':1,'operation_id':self.op,'kind':'finite_group','gate':self.gate,'subject':{'plan':plan,'experiment_directory':str(self.root)},'source_files':source})
        claimdir=self.attempts/'.operations'/self.op;claimdir.mkdir(mode=0o700)
        claim=self.write(claimdir/'claim.json',{'schema_version':1,'operation_id':self.op,'kind':'finite_group','authority':authority,'created_at_ms':0,'owner':{'pid':123,'uid':__import__('os').geteuid()}})
        coord=self.write(self.root/'coordinator.json',{'status':'stopped','plan_sha256':plan['sha256'],'submissions':[{'attempt_id':self.ids[0],'returncode':1}],'settled':{}})
        configuration=self.write(self.root/'config.json',{'schema_version':1,'original_source':str(self.root),'authority':authority,'claim':claim,'journal':journal,'coordinator':coord,'attempt_ids':self.ids,'runtime':runtime,'snapshot':snapshot,'implementation':source[0],'group_unit':'maplebench-test.service','group_invocation':'b'*32})
        self.proof={'schema_version':1,'kind':abort.KIND,'outcome':'aborted_before_runtime_no_score','authority':authority,'claim':claim,'plan':plan,'coordinator':coord,'configuration':configuration,'journal':journal,'retired_attempt_ids':self.ids,'observations':{'ready':True,'account_offline':True,'baseline_snapshot':snapshot,'browser_transition':'c'*32,'services_stopped':True,'api_calls':0,'observed_at_ms':1,'processes_absent':True,'artifacts_absent':True,'group_unit':'maplebench-test.service','group_invocation':'b'*32,'group_cgroup_empty':True},'api_calls':0}
    def write(self,path,value):return abort.create(path,value)
    def seal(self):
        proof=self.write(self.folder/'proof.json',self.proof)
        rdir=self.root/'.operation-receipts'/self.op;rdir.mkdir(parents=True,mode=0o700)
        receipt=self.write(rdir/'terminal-receipt.json',{'schema_version':1,'operation_id':self.op,'claim_sha256':self.proof['claim']['sha256'],'status':'completed','quiescent':True,'evidence':[proof]})
        terminal=self.write(self.attempts/'.operations'/self.op/'terminal.json',{'schema_version':1,'operation_id':self.op,'claim_sha256':self.proof['claim']['sha256'],'completed_at_ms':1,'receipt':receipt})
        self.write(self.folder/'certificate.json',{'proof':proof,'terminal':terminal})
    def test_exact_certificate_withdraws_all_ids_preserves_journal(self):
        before=Path(self.proof['journal']['path']).read_bytes();self.seal()
        self.assertEqual(abort.certified(self.attempts),(set(self.ids),{self.ids[0]}))
        self.assertEqual(Path(self.proof['journal']['path']).read_bytes(),before)
    def test_arbitrary_cleanup_or_provider_usage_is_not_untouched(self):
        for mutation in ('api','operation','code','receipts'):
            j=copy.deepcopy(self.journal)
            if mutation=='api':j['charged_usage']['api_requests']=1
            if mutation=='operation':j['events'][4]['operation']='restore_baseline'
            if mutation=='code':j['events'][7]['code']='operation_timeout'
            if mutation=='receipts':j['receipts']['cleanup']={'clean':True}
            with self.subTest(mutation=mutation),self.assertRaises(abort.AbortError):abort.untouched(j)
    def test_partial_certificate_and_changed_journal_fail_closed(self):
        with self.assertRaises(FileNotFoundError):abort.certified(self.attempts)
        self.seal();Path(self.proof['journal']['path']).write_text('{}')
        with self.assertRaises(abort.AbortError):abort.certified(self.attempts)
    def test_future_artifact_and_changed_gate_refuse(self):
        self.seal();(self.attempts/self.ids[1]).mkdir()
        with self.assertRaises(abort.AbortError):abort.certified(self.attempts)
        (self.attempts/self.ids[1]).rmdir();Path(self.gate['path']).write_text('changed')
        with self.assertRaises(abort.AbortError):abort.certified(self.attempts)
    def test_copied_terminal_cannot_grant_exemption(self):
        self.seal();c=self.folder/'certificate.json';v=json.loads(c.read_text());old=abort.read(v['terminal']);v['terminal']=self.write(self.root/'copied-terminal.json',old);c.write_bytes(abort.encoded(v))
        with self.assertRaises(abort.AbortError):abort.certified(self.attempts)
    def test_runner_scan_accepts_only_certified_failure_and_rejects_all_retired_ids(self):
        import full_client_trial as trial
        self.seal();runner=trial.TrialRunner(self.attempts,self.root/'world',self.root/'queue',None)
        with patch.object(runner,'_load',return_value=self.journal):
            runner._require_no_unrecovered('5'*32)
            for ident in self.ids:
                with self.subTest(ident=ident),self.assertRaisesRegex(trial.TrialError,'attempt_permanently_retired'):
                    runner._require_no_unrecovered(ident)
    def test_boolean_ready_alone_cannot_certify_quiescence(self):
        self.proof['observations']={'ready':True}
        with self.assertRaisesRegex(abort.AbortError,'abort_observation_schema'):abort.validate_proof(self.proof,self.attempts)
    def test_changed_runtime_reference_or_implementation_refuses(self):
        path=Path(abort.read(self.proof['configuration'])['runtime']['path']);path.write_text('{}')
        with self.assertRaises(abort.AbortError):abort.validate_proof(self.proof,self.attempts)
    def test_private_json_rejects_public_mode_duplicate_and_nonfinite(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}'):
            p=self.root/'bad.json';p.write_bytes(raw);p.chmod(0o600)
            with self.assertRaises(abort.AbortError):abort.pin(p)
        p.write_bytes(b'{}');p.chmod(0o644)
        with self.assertRaises(abort.AbortError):abort.pin(p)
    def test_oversized_or_symlink_pin_refuses(self):
        p=self.root/'big';p.write_bytes(b'x'*(abort.MAX_BYTES+1))
        with self.assertRaises(abort.AbortError):abort.pin(p)
        q=self.root/'link';q.symlink_to(p)
        with self.assertRaises(abort.AbortError):abort.pin(q)

class AbortWriterTests(unittest.TestCase):
    def setUp(self):
        import test_full_client_experiment as fixtures
        import full_client_experiment as experiment
        import full_client_operation_admission as admission
        self.experiment=experiment;self.admission=admission
        self.fixture=fixtures.ExperimentTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root;self.plan=self.fixture.plan(models=experiment.MODELS[:4]);self.attempts=self.fixture.attempts
        self.ids=[e['attempt_id'] for e in self.plan['entries']];self.op='d'*32
        self.plan_ref=abort.create(self.root/'plan.json',self.plan)
        self.directory=self.root/'experiment'
        coordinator=experiment.Experiment(self.plan,self.directory,launcher=lambda *a,**kw:1)
        with self.assertRaises(experiment.ExperimentError):coordinator.run()
        template=AbortTests();template.setUp();self.addCleanup(template.doCleanups)
        journal=copy.deepcopy(template.journal);journal.update(attempt_id=self.ids[0],request=self.plan['entries'][0]['spec'],adapter_fingerprint=self.plan['fixtures'][0]['adapter_fingerprint'])
        d=self.attempts/self.ids[0];d.mkdir(mode=0o700);self.journal=abort.create(d/'journal.json',journal)
        self.original_journal=Path(self.journal['path']).read_bytes();self.original_coordinator=(self.directory/'coordinator.json').read_bytes()
        pin=gate.initialize_registry(self.attempts,owner_uid=__import__('os').geteuid())
        scripts=Path(abort.__file__).parent
        sources=[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in scripts.glob('full_client_*.py') if p.name!='full_client_pre_runtime_abort.py']
        authority={'schema_version':1,'operation_id':self.op,'kind':'finite_group','gate':pin,'subject':{'type':'experiment','plan':self.plan_ref,'experiment_directory':str(self.directory)},'source_files':sources}
        self.authority=abort.create(self.root/'authority.json',authority)
        with gate.OperationGate(self.attempts,pin,owner_uid=__import__('os').geteuid()).locked() as lease:
            self.claim=lease.begin(self.op,'finite_group',self.authority)
        adapter=abort.read(self.plan['fixtures'][0]['adapter_config']);runtime=abort.pin(Path(adapter['argv'][-1]));snapshot=abort.read(runtime)['baseline_snapshot']
        implementation={'path':str(Path(abort.__file__).resolve()),'sha256':hashlib.sha256(Path(abort.__file__).read_bytes()).hexdigest()}
        self.config={'schema_version':1,'authority':self.authority,'claim':self.claim,'coordinator':abort.pin(self.directory/'coordinator.json'),'journal':self.journal,'runtime':runtime,'snapshot':snapshot,'original_source':str(scripts),'attempt_ids':self.ids,'implementation':implementation,'group_unit':'maplebench-test.service','group_invocation':'e'*32}
        self.config_ref=abort.create(self.root/'abort-config.json',self.config)
        self.observation={'ready':True,'account_offline':True,'baseline_snapshot':snapshot,'browser_transition':'f'*32,'services_stopped':True,'api_calls':0,'observed_at_ms':__import__('time').time_ns()//1000000,'processes_absent':True,'artifacts_absent':True,'group_unit':'maplebench-test.service','group_invocation':'e'*32,'group_cgroup_empty':True}
    def test_actual_writer_admission_locks_finish_and_repeat_are_nonreplaying(self):
        with patch.object(abort,'observe',return_value=self.observation) as observed:
            self.assertEqual(abort.execute(self.config_ref)['status'],'aborted_before_runtime_no_score')
            self.assertEqual(observed.call_count,2)
            self.assertEqual(abort.execute(self.config_ref)['status'],'already_aborted')
            self.assertEqual(observed.call_count,2)
        self.assertEqual(Path(self.journal['path']).read_bytes(),self.original_journal)
        self.assertEqual((self.directory/'coordinator.json').read_bytes(),self.original_coordinator)
        self.assertEqual(abort.certified(self.attempts),(set(self.ids),{self.ids[0]}))
    def test_failed_native_observation_keeps_original_claim_pending(self):
        with patch.object(abort,'observe',side_effect=abort.AbortError('abort_browser_busy')):
            with self.assertRaisesRegex(abort.AbortError,'abort_browser_busy'):abort.execute(self.config_ref)
        authority=abort.read(self.authority)
        with gate.OperationGate(self.attempts,authority['gate'],owner_uid=__import__('os').geteuid()).locked() as lease:
            self.assertEqual(lease.reconcile(self.claim)['status'],'pending')
        self.assertFalse((self.attempts/'.pre-runtime-aborts'/self.op/'proof.json').exists())
        self.assertEqual(Path(self.journal['path']).read_bytes(),self.original_journal)
    def test_lost_terminal_reply_reconciles_real_marker_without_observation(self):
        original=self.admission.Admission.finish
        def lost(instance,evidence):original(instance,evidence);raise OSError('lost reply')
        with patch.object(abort,'observe',return_value=self.observation),patch.object(self.admission.Admission,'finish',lost):
            with self.assertRaises(OSError):abort.execute(self.config_ref)
        with patch.object(abort,'observe',side_effect=AssertionError('must not observe terminal operation')):
            self.assertEqual(abort.execute(self.config_ref)['status'],'already_aborted')
        self.assertEqual(abort.certified(self.attempts)[0],set(self.ids))

if __name__=='__main__':unittest.main()
