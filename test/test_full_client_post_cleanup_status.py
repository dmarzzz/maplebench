"""Synthetic read-only status reconciliation; no services, DB, browser or API."""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import full_client_post_cleanup_status as reconcile
import full_client_operation_gate as gate
import full_client_operation_admission as admission
import full_client_experiment as experiment
import full_client_trial as trial
import full_client_pre_runtime_abort as files
from test_full_client_trial import spec


def write(path,value):
    path.write_bytes(reconcile.encoded(value));path.chmod(0o600)
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.root.chmod(0o700)
        self.attempts=self.root/'attempts';self.attempts.mkdir(mode=0o700)
        self.ident='a'*32;self.transition='b'*32
        folder=self.attempts/self.ident;folder.mkdir(mode=0o700)
        self.group=self.root/'group';self.group.mkdir(mode=0o700)
        self.area=self.group/'recoveries';self.area.mkdir(mode=0o700)
        self.world=self.root/'world';self.queue=self.root/'queue'
        for p in (self.world,self.queue):p.touch(mode=0o600)
        self.original={'schema_version':1,'attempt_id':self.ident,'status':'failed','phase':'collect_final',
            'phase_status':'pending','failure_code':'recording_duration_mismatch','pending':None,
            'publication_eligible':False,'api_outcome':'uncertain','charged_usage':{'api_requests':12,'total_tokens':120000},
            'request':spec(),'adapter_fingerprint':'f'*64,
            'events':[{'sequence':0,'kind':'attempt_created','at_ms':1},
                      {'sequence':1,'kind':'recovery_required','phase':'collect_final','code':'recording_duration_mismatch','at_ms':2}],
            'receipts':{'run_controller':{'preserved':'synthetic'}}}
        self.current=copy.deepcopy(self.original)
        self.current.update(phase='status',phase_status='returned',failure_code='runtime_not_idle')
        shapes=[('recovery_started',None,None),('operation_pending','status',None),('operation_returned','status',None),
            ('operation_pending','cleanup',None),('operation_returned','cleanup',None),('operation_pending','status',None),
            ('operation_returned','status',None),('recovery_required',None,'runtime_not_idle')]
        for kind,op,code in shapes:
            i=len(self.current['events']);e={'sequence':i,'at_ms':i+1,'kind':kind}
            if op:e['operation']=op
            if code:e.update(code=code,phase='status')
            self.current['events'].append(e)
        self.status={k:k!='ownership_conflict' for k in trial.STATUS_FIELDS}
        self.current['receipts'].update(status=self.status|{'ready':False},cleanup={'attempt_id':self.ident,'clean':True})
        self.backend={'attempt_id':self.ident,'clean':True,'pending':None,'dropin':'/synthetic/trial.conf','dropin_sha256':'c'*64,
            'configuration_cleanup':{'path':'/synthetic/trial.conf','sha256':'c'*64,'phase':'verified'}}
        journal=write(folder/'journal.json',self.current);backend=write(folder/'backend-state.json',self.backend)
        original=write(self.area/(self.ident+'.failed-journal.json'),self.original)
        coord=write(self.group/'coordinator.json',{'submissions':[{'attempt_id':self.ident}],'settled':{}})
        runtime=write(self.root/'runtime.json',{'world_lock':str(self.world),'queue_lock':str(self.queue),
            'attempt_root':str(self.attempts),'orchestrator':{'path':'/synthetic/trial.py','sha256':'d'*64}})
        adapter=write(self.root/'adapter.json',{'argv':['/synthetic/python','/synthetic/source/full_client_runtime.py',
            '--config',runtime['path']]})
        self.plan={'runner':{'state_root':str(self.attempts),'world_lock':str(self.world),'queue_lock':str(self.queue),
                'python':{'path':'/synthetic/python','sha256':'e'*64},'trial_script':{'path':'/synthetic/trial.py','sha256':'d'*64}},
            'entries':[{'ordinal':0,'attempt_id':self.ident,'spec':self.current['request'],'fixture_id':'synthetic'},
                       {'ordinal':1,'attempt_id':'c'*32,'spec':self.current['request'],'fixture_id':'synthetic'}],
            'fixtures':[{'id':'synthetic','adapter_fingerprint':'f'*64}]}
        plan=write(self.root/'plan.json',self.plan)
        self.authority={'subject':{'plan':plan}};authority=write(self.root/'authority.json',self.authority)
        self.gate_pin=gate.initialize_registry(self.attempts,owner_uid=os.geteuid())
        self.gate=gate.OperationGate(self.attempts,self.gate_pin,owner_uid=os.geteuid())
        with self.gate.locked() as lease:claim=lease.begin('d'*32,'finite_group',authority)
        self.descriptor={'failure':original,'coordinator':coord,'adapter_config':adapter}
        recovery=write(self.area/(self.ident+'.json'),self.descriptor)
        self.config={'authority':authority,'claim':claim,'coordinator':coord,'journal':journal,'backend':backend,
            'runtime':runtime,'recovery':recovery,'original_source':'/synthetic/source','waiting_transition':self.transition,
            'timeout_seconds':30}
        implementation=Path(reconcile.__file__).resolve()
        self.config['implementation']={'path':str(implementation),'sha256':hashlib.sha256(implementation.read_bytes()).hexdigest()}
        self.config_ref=write(self.root/'config.json',self.config)
        self.coordinator=SimpleNamespace(plan=self.plan,directory=self.group)
        def load():
            self.coordinator.state=reconcile.read(self.config['coordinator'])
            self.coordinator.state_sha=self.config['coordinator']['sha256']
        self.coordinator.load=load
        self.adapter=SimpleNamespace(fingerprint='f'*64)
        self.runner=trial.TrialRunner(self.attempts,self.world,self.queue,self.adapter)
        self.admission=SimpleNamespace(recovery_descriptor=lambda *a,**k:self.descriptor,
            private_ref=admission.private_ref,trial_terminal=admission.trial_terminal)
        self.modules=(self.admission,experiment,trial,None,files);self.calls=0

    def observe(self,*args,**kwargs):
        self.calls+=1
        # All real gate/coordinator/world/queue/runner locks must already be held.
        for p in [Path(self.gate_pin['path']),self.group/'.experiment.lock',self.world,self.queue,self.attempts/'.runner.lock']:
            with p.open('r+b') as f:
                with self.assertRaises(BlockingIOError):fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.assertEqual(kwargs['attempt_id'],self.ident)
        return {'status':copy.deepcopy(self.status),'waiting_transition':self.transition,
                'observed_at_ms':round(time.time()*1000),'inventory_revalidated':False}

    def run_reconcile(self):
        with self.gate.locked() as lease:
            lease.reconcile(self.config['claim'])
            operation=SimpleNamespace(lease=lease,claim=self.config['claim'],completed=False,uid=os.geteuid(),authority=self.authority)
            with experiment.Experiment.locked(self.coordinator),self.runner._locks():
                return reconcile.reconcile_locked(self.config_ref,self.config,operation,self.coordinator,self.runner,
                                                  self.modules,observe=self.observe)

    def test_success_preserves_failure_accounting_and_uses_original_terminal_validator(self):
        preserved={key:Path(self.config[key]['path']).read_bytes() for key in ('backend','coordinator','recovery','claim')}
        result=self.run_reconcile();self.assertEqual(result['status'],'recovered_unscored');self.assertEqual(self.calls,1)
        saved=json.loads(Path(self.config['journal']['path']).read_bytes())
        self.assertEqual(saved['events'][:-1],self.current['events'])
        self.assertEqual(saved['events'][-1]['kind'],'post_cleanup_status_reconciled')
        self.assertEqual(saved['failure_code'],'runtime_not_idle')
        for key in ('request','api_outcome','charged_usage','publication_eligible'):
            self.assertEqual(saved[key],self.original[key])
        for key,raw in preserved.items():self.assertEqual(Path(self.config[key]['path']).read_bytes(),raw)
        self.assertEqual((self.area/(self.ident+'.status-failed-journal.json')).read_bytes(),reconcile.encoded(self.current))
        self.assertFalse((self.attempts/'.operations'/('d'*32)/'terminal.json').exists())
        self.assertEqual(self.run_reconcile(),result);self.assertEqual(self.calls,1)
        self.assertEqual(trial.TrialRunner._load(self.runner,self.ident),saved)
        self.assertTrue(experiment.inspect_attempt(self.plan,self.plan['entries'][0])['terminal_clean'])

    def test_not_ready_cannot_change_journal_or_manufacture_terminal_state(self):
        before=Path(self.config['journal']['path']).read_bytes();self.status['ready']=False
        with self.assertRaisesRegex(trial.TrialError,'runtime_not_idle'):self.run_reconcile()
        self.assertEqual(Path(self.config['journal']['path']).read_bytes(),before)
        self.assertFalse((self.area/(self.ident+'.status-proof.json')).exists())

    def test_accounting_cleanup_receipt_history_and_backend_changes_are_refused(self):
        mutations=[lambda c,b:c['charged_usage'].update(total_tokens=0),lambda c,b:c.update(api_outcome='confirmed'),
            lambda c,b:c['receipts']['cleanup'].update(clean=False),lambda c,b:c['events'][-4].update(operation='start_server'),
            lambda c,b:c.update(phase_status='pending'),lambda c,b:b.update(clean=False),
            lambda c,b:b['configuration_cleanup'].update(phase='reload_pending')]
        for change in mutations:
            c=copy.deepcopy(self.current);b=copy.deepcopy(self.backend);change(c,b)
            with self.subTest(change=change),self.assertRaises(ValueError):
                reconcile.validate_failed_cleanup(c,self.original,b,trial.STATUS_FIELDS)

    def test_hash_change_during_observation_refuses_journal_write(self):
        original=self.observe
        def changed(*a,**kw):
            value=original(*a,**kw);Path(self.config['backend']['path']).write_bytes(b'{}');return value
        self.observe=changed
        with self.assertRaisesRegex(ValueError,'status_reference_changed'):self.run_reconcile()
        self.assertEqual(Path(self.config['journal']['path']).read_bytes(),reconcile.encoded(self.current))

    def test_missing_runner_locks_refuses_before_status_read(self):
        with self.gate.locked() as lease:
            lease.reconcile(self.config['claim'])
            operation=SimpleNamespace(lease=lease,claim=self.config['claim'],completed=False,uid=os.geteuid(),authority=self.authority)
            with self.assertRaisesRegex(ValueError,'status_runner_locks_required'):
                reconcile.reconcile_locked(self.config_ref,self.config,operation,self.coordinator,self.runner,self.modules,observe=self.observe)
        self.assertEqual(self.calls,0)

    def test_source_bootstrap_rejects_unpinned_preloaded_modules_before_entry(self):
        source=Path(trial.__file__).resolve().parent
        names=('full_client_operation_admission','full_client_experiment','full_client_trial','full_client_runtime','full_client_pre_runtime_abort')
        refs=[{'path':str(source/(name+'.py')),'sha256':hashlib.sha256((source/(name+'.py')).read_bytes()).hexdigest()} for name in names]
        authority=write(self.root/'bootstrap-authority.json',{'source_files':refs})
        implementation=Path(reconcile.__file__).resolve()
        config=self.config|{'schema_version':1,'kind':reconcile.KIND,'authority':authority,'original_source':str(source),
            'implementation':{'path':str(implementation),'sha256':hashlib.sha256(implementation.read_bytes()).hexdigest()}}
        ref=write(self.root/'bootstrap-config.json',config)
        with self.assertRaisesRegex(ValueError,'status_modules_already_loaded'):reconcile.execute(ref)
        self.assertEqual(self.calls,0)

    def test_private_reference_rejects_symlink_hardlink_permissions_and_duplicate_keys(self):
        p=self.root/'private.json';ref=write(p,{'value':1})
        link=self.root/'linked.json';link.symlink_to(p)
        with self.assertRaisesRegex(ValueError,'status_noncanonical_path'):reconcile.read(ref|{'path':str(link)})
        link.unlink();os.link(p,link)
        with self.assertRaisesRegex(ValueError,'status_unprotected_file'):reconcile.read(ref)
        link.unlink();p.chmod(0o644)
        with self.assertRaisesRegex(ValueError,'status_unprotected_file'):reconcile.read(ref)
        p.chmod(0o600);p.write_bytes(b'{"value":1,"value":2}')
        ref['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'status_duplicate_json_key'):reconcile.read(ref)

    def test_lost_journal_write_reply_reconciles_saved_bytes_without_second_observation(self):
        atomic=trial.atomic_json
        def lost(*args,**kwargs):atomic(*args,**kwargs);raise OSError('lost reply')
        with patch.object(trial,'atomic_json',side_effect=lost),self.assertRaises(OSError):self.run_reconcile()
        self.assertEqual(self.calls,1);result=self.run_reconcile();self.assertEqual(result['status'],'recovered_unscored')
        self.assertEqual(self.calls,1)

    def test_unwritten_journal_after_proof_requires_new_read_only_observation(self):
        with patch.object(trial,'atomic_json',side_effect=OSError('before write')),self.assertRaises(OSError):self.run_reconcile()
        self.assertEqual(self.calls,1);self.run_reconcile();self.assertEqual(self.calls,2)

    def test_tampered_proof_observation_is_rejected_before_lost_reply_branch(self):
        with patch.object(trial,'atomic_json',side_effect=OSError('before write')),self.assertRaises(OSError):self.run_reconcile()
        path=self.area/(self.ident+'.status-proof.json');original=json.loads(path.read_bytes())
        for mutate in [lambda p:p['observation'].update(waiting_transition='e'*32),
                       lambda p:p['observation']['status'].update(ready=False),
                       lambda p:p['observation'].update(observed_at_ms=True),
                       lambda p:p['observation'].update(observed_at_ms=0),
                       lambda p:p['observation'].update(extra='bad'),lambda p:p.update(extra=True),
                       lambda p:p.update(api_calls=True)]:
            value=copy.deepcopy(original);mutate(value);ref=write(path,value)
            # Even a journal forged to agree with the changed proof is refused.
            proposed=reconcile.commit_reconciliation(self.runner,self.current,ref,value['observation'])
            write(Path(self.config['journal']['path']),proposed)
            with self.subTest(mutate=mutate),self.assertRaises((ValueError,trial.TrialError)):self.run_reconcile()
            self.assertEqual(self.calls,1)
        write(path,original)


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.run={'id':'a'*32,'status':'failed','workerActive':False,'leaseReleasePending':False}
        self.session={'transitionId':'b'*32,'state':'waiting','fresh':True,'pinned':True,'artifactsSettled':True,'captureState':'idle'}
        self.bridge={'run':self.run,'browserReleasePending':False,'quarantinedRuns':[]}
        self.stopped=True;self.offline=True;self.config_absent=True;self.queue=0;self.calls=[]
        self.backend=SimpleNamespace(host=SimpleNamespace(queue_count=lambda path:self.queue),
            load_pins=lambda:self.calls.append('pins'),online_identity=lambda:self.calls.append('identity'),
            unit=lambda role:role,stopped=lambda role:self.stopped,account_state=lambda:0 if self.offline else 2,
            trial_configuration_absent=lambda unit:self.config_absent,
            admin=lambda op:self.calls.append(op) or {'session':self.session,'bridge':self.bridge})
        self.runtime=SimpleNamespace(CosmicRuntime=lambda config:self.backend)
    def observe(self):
        return reconcile.observed_status(self.runtime,{'queue_database':'synthetic'},'b'*32,time.monotonic()+30,attempt_id='a'*32)
    def test_read_only_operational_predicate_does_not_claim_inventory_revalidation(self):
        value=self.observe();self.assertTrue(value['status']['ready']);self.assertFalse(value['inventory_revalidated'])
        self.assertEqual(self.calls,['pins','identity','status'])
    def test_live_services_account_queue_dropin_or_leases_cannot_be_ready(self):
        for field,value in [('stopped',False),('offline',False),('config_absent',False),('queue',1)]:
            setattr(self,field,value);self.assertFalse(self.observe()['status']['ready']);self.setUp()
        for field,value in [('workerActive',True),('leaseReleasePending',True),('id','e'*32)]:
            self.run[field]=value;self.assertFalse(self.observe()['status']['ready']);self.setUp()
    def test_wrong_stale_unsettled_or_capturing_transition_is_refused(self):
        for field,value in [('transitionId','e'*32),('fresh',False),('pinned',False),('artifactsSettled',False),('captureState','recording')]:
            self.session[field]=value
            with self.assertRaisesRegex(ValueError,'status_waiting_transition_unverified'):self.observe()
            self.setUp()


if __name__=='__main__':unittest.main()
