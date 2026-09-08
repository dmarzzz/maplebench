"""Synthetic cleanup only; root/Linux cases use real admitted child CLIs and flocks."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import full_client_experiment as experiment
import full_client_trial as trial
import full_client_operation_admission as admission
import test_full_client_operation_cli as fixtures
import test_full_client_trial as trial_fixtures


BACKEND = r'''
import json,os,sys
from pathlib import Path
cfg=json.loads(Path(sys.argv[2]).read_bytes());request=json.load(sys.stdin)
ctx=request['context'];op=request['operation'];recovery=ctx.get('recovery') is True
assert op in ('status','restore_baseline','start_server','login','run_controller','cleanup')
assert set(ctx['lock_fds'])=={'world','queue'}
for name,fd in ctx['lock_fds'].items():
    a,b=os.fstat(fd),Path(ctx['lock_paths'][name]).stat()
    assert (a.st_dev,a.st_ino)==(b.st_dev,b.st_ino)
parent=Path('/proc')/str(ctx['guard_parent_pid'])
assert parent.joinpath('cmdline').read_bytes().split(bytes([0]))[1].decode()==cfg['orchestrator']['path']
gate=Path(cfg['gate_path']).stat()
for p in (Path('/proc')/str(os.getpid()),Path('/proc')/str(ctx['guard_pid'])):
    with os.scandir(p/'fd') as entries:
        assert not any((f.stat().st_dev,f.stat().st_ino)==(gate.st_dev,gate.st_ino) for f in entries)
with Path(cfg['test_marker']).open('a') as f:f.write(json.dumps({'operation':op,'recovery':recovery,'new_api_requests':0})+chr(10))
folder=Path(ctx['attempt_dir'])
if op=='status':
    value={k:k!='ownership_conflict' for k in cfg['status_fields']}
    value['ready']=recovery or API_FAILURE
elif op=='run_controller':
    assert not recovery;raise SystemExit(2)
elif op=='cleanup':
    assert recovery
    if CLEANUP_FAILURE:raise SystemExit(2)
    target=folder/'backend-state.json';target.write_text(json.dumps({'attempt_id':ctx['attempt_id'],'clean':True}));target.chmod(0o600)
    value={'attempt_id':ctx['attempt_id'],'clean':True}
else:
    assert not recovery and API_FAILURE;value={'attempt_id':ctx['attempt_id']}
print(json.dumps(value))
'''

RECOVERY_PARENT = r'''
import json,sys
from pathlib import Path
data=json.loads(Path(sys.argv[1]).read_bytes());sys.path.insert(0,data['scripts'])
import full_client_experiment as e
import full_client_operation_admission as a
plan=e.validate_plan(a.gate.read_ref(data['plan'],0,a.gate.Budget()))
subject={'type':'experiment','plan':data['plan'],'experiment_directory':data['directory']}
try:
 with a.admitted(data['authority'],subject,'finite_group',plan['runner']['state_root'],claim_ref=data['claim'],required_sources=(e.__file__,__file__)) as active:
  launch=a.current_launch(active.authority['source_files'],executable_ref=plan['runner']['python'])
  def child(plan,entry,timeout,**kwargs):
   if data['mode']=='descriptor':kwargs['recovery_ref']=dict(kwargs['recovery_ref'],sha256='0'*64)
   if data['mode']=='journal':
    p=Path(plan['runner']['state_root'])/entry['attempt_id']/'journal.json';p.write_bytes(p.read_bytes()+b' ')
   result=e.launch_recovery(plan,entry,timeout,**kwargs)
   if data['mode']=='lost_reply':raise OSError('synthetic lost process reply')
   return result
  value=e.recover_entry(e.Experiment(plan,data['directory']),active,data['plan'],data['attempt_id'],data['journal_sha256'],data['coordinator_sha256'],30,launch,launcher=child)
 print(json.dumps(value))
except Exception as error:print(json.dumps({'status':'blocked','code':str(error)}))
'''


@unittest.skipUnless(sys.platform == "linux" and os.geteuid() == 0, "requires isolated root-owned Linux source")
class GroupRecoveryCLITests(unittest.TestCase):
    def setup_failure(self, *, api_failure=False, cleanup_failure=False, custom_parent=False):
        code=BACKEND.replace('API_FAILURE',str(api_failure)).replace('CLEANUP_FAILURE',str(cleanup_failure))
        with patch.object(fixtures,'BACKEND',code):
            self.f=fixtures.OperationCLITests();self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        if custom_parent:
            self.f.driver.write_text(RECOVERY_PARENT)
            self.f.sources=[fixtures.ref(Path(ref['path'])) for ref in self.f.sources]
        self.authority=self.f.group_authority()
        args=self.args('run',claim=False)
        status,value=self.f.run_cli(experiment.__file__,args)
        self.assertEqual(status,1,value)
        self.assertEqual(value['code'],'submitted_attempt_unresolved')
        self.claim=fixtures.ref(self.f.attempts/'.operations'/fixtures.OPERATION/'claim.json')
        self.journal=self.f.attempts/fixtures.ATTEMPT/'journal.json'
        self.failed=self.journal.read_bytes();self.journal_sha=fixtures.ref(self.journal)['sha256']
        self.coordinator=self.f.directory/'coordinator.json';self.coordinator_raw=self.coordinator.read_bytes()
        self.coordinator_sha=fixtures.ref(self.coordinator)['sha256']

    def args(self,command,*,claim=True):
        args=[command,'--plan',self.f.plan_ref['path'],'--directory',self.f.directory,
              '--operation-authority',self.authority['path'],'--operation-authority-sha256',self.authority['sha256']]
        if claim:args += ['--operation-claim',self.claim['path'],'--operation-claim-sha256',self.claim['sha256']]
        if command=='recover-entry':args += ['--attempt-id',fixtures.ATTEMPT,'--journal-sha256',self.journal_sha,
                 '--coordinator-sha256',self.coordinator_sha,'--timeout-seconds','30']
        return args

    def calls(self):return [json.loads(x) for x in self.f.marker.read_text().splitlines()]

    def test_actual_child_cleanup_preserves_failure_claim_and_has_no_api_replay(self):
        self.setup_failure()
        status,value=self.f.run_cli(experiment.__file__,self.args('recover-entry'))
        self.assertEqual((status,value['status']),(0,'entry_recovered'),value)
        self.assertEqual(self.coordinator.read_bytes(),self.coordinator_raw)
        self.assertEqual((self.f.directory/'recoveries'/(fixtures.ATTEMPT+'.failed-journal.json')).read_bytes(),self.failed)
        saved=json.loads(self.journal.read_bytes());self.assertEqual(saved['status'],'recovered')
        self.assertEqual(saved['events'][:len(json.loads(self.failed)['events'])],json.loads(self.failed)['events'])
        self.assertEqual([x['operation'] for x in self.calls()],['status','status','cleanup','status'])
        self.assertTrue(all(x['new_api_requests']==0 for x in self.calls()))
        self.assertFalse((self.f.attempts/'.operations'/fixtures.OPERATION/'terminal.json').exists())
        count=len(self.calls());again=self.f.run_cli(experiment.__file__,self.args('recover-entry'))
        self.assertEqual(again[0],0,again);self.assertEqual(len(self.calls()),count)
        status,value=self.f.run_cli(experiment.__file__,self.args('seal')+['--journal-sha256',self.coordinator_sha])
        self.assertEqual(status,0,value);self.assertTrue(value['sealed'])
        self.assertTrue((self.f.attempts/'.operations'/fixtures.OPERATION/'terminal.json').exists())

    def test_original_uncertain_provider_reservation_is_preserved(self):
        self.setup_failure(api_failure=True)
        failed=json.loads(self.failed);self.assertEqual(failed['api_outcome'],'uncertain')
        self.assertEqual(failed['charged_usage']['api_requests'],1)
        status,value=self.f.run_cli(experiment.__file__,self.args('recover-entry'));self.assertEqual(status,0,value)
        recovered=json.loads(self.journal.read_bytes())
        self.assertEqual(recovered['api_outcome'],failed['api_outcome'])
        self.assertEqual(recovered['charged_usage'],failed['charged_usage'])
        self.assertEqual(sum(x['operation']=='run_controller' for x in self.calls()),1)

    def test_changed_coordinator_or_failed_journal_refuses_before_child(self):
        self.setup_failure();count=len(self.calls())
        for flag in ('--journal-sha256','--coordinator-sha256'):
            args=self.args('recover-entry');args[args.index(flag)+1]='0'*64
            self.assertEqual(self.f.run_cli(experiment.__file__,args)[0],1)
        self.assertEqual(self.journal.read_bytes(),self.failed);self.assertEqual(len(self.calls()),count)

    def test_failed_cleanup_stays_quarantined_and_never_relaunches(self):
        self.setup_failure(cleanup_failure=True)
        self.assertEqual(self.f.run_cli(experiment.__file__,self.args('recover-entry'))[0],1)
        self.assertEqual(json.loads(self.journal.read_bytes())['status'],'failed');count=len(self.calls())
        status,value=self.f.run_cli(experiment.__file__,self.args('recover-entry'))
        self.assertEqual((status,value['code']),(1,'recovery_outcome_uncertain'))
        self.assertEqual(len(self.calls()),count)

    def custom(self,mode):
        data={'scripts':str(fixtures.SCRIPTS),'plan':self.f.plan_ref,'directory':str(self.f.directory),
              'authority':self.authority,'claim':self.claim,'attempt_id':fixtures.ATTEMPT,
              'journal_sha256':self.journal_sha,'coordinator_sha256':self.coordinator_sha,'mode':mode}
        path=self.f.root/'recovery-parent.json';fixtures.write_json(path,data)
        return self.f.run_cli(self.f.driver,[path])

    def test_lost_launcher_reply_reconciles_saved_child_cleanup(self):
        self.setup_failure(custom_parent=True)
        status,value=self.custom('lost_reply');self.assertEqual(value['status'],'entry_recovered',value)
        count=len(self.calls());self.assertEqual(self.custom('lost_reply')[1]['status'],'entry_recovered')
        self.assertEqual(len(self.calls()),count)

    def test_wrong_descriptor_or_journal_cannot_enter_inherited_recovery(self):
        for mode in ('descriptor','journal'):
            with self.subTest(mode=mode):
                self.setup_failure(custom_parent=True);count=len(self.calls())
                status,value=self.custom(mode);self.assertEqual(value['status'],'blocked',value)
                self.assertEqual(len(self.calls()),count)
                entries=list(self.f.root.glob('.operation-dispatch/*/trial_recover-*.entered.json'))
                self.assertEqual(entries,[])


class RecoveryHashTests(unittest.TestCase):
    def test_expected_failed_journal_hash_is_checked_under_runner_locks(self):
        import tempfile,hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            for name in ('world','queue'):(root/name).touch(mode=0o600)
            adapter=trial_fixtures.FakeAdapter(fail='run_controller')
            runner=trial.TrialRunner(root/'attempts',root/'world',root/'queue',adapter)
            with self.assertRaises(RuntimeError):runner.run(trial_fixtures.spec(),'1'*32)
            path=root/'attempts'/('1'*32)/'journal.json';raw=path.read_bytes();calls=len(adapter.calls)
            with self.assertRaisesRegex(trial.TrialError,'recovery_journal_changed'):
                runner.recover('1'*32,expected_journal_sha256='0'*64)
            self.assertEqual(path.read_bytes(),raw);self.assertEqual(len(adapter.calls),calls)


if __name__=='__main__':unittest.main()
