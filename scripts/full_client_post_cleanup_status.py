"""Explicit status-only reconciliation after a proven successful cleanup.

This operator is separately pinned. It loads the original authority's modules,
never enters a recovery child, and cannot dispatch cleanup, game or API actions.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time

KIND='full-client-post-cleanup-status-v1'
FIELDS={'schema_version','kind','authority','claim','recovery','coordinator','journal','backend',
        'runtime','original_source','implementation','waiting_transition','timeout_seconds'}
MAX_BYTES=4*1024*1024

class StatusReconcileError(ValueError):pass

def need(value,code):
    if not value:raise StatusReconcileError(code)

def encoded(value):return (json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()

def read_reference(ref, *, private=True):
    need(isinstance(ref,dict) and set(ref)=={'path','sha256'} and isinstance(ref['sha256'],str)
         and re.fullmatch('[a-f0-9]{64}',ref['sha256']),'status_invalid_reference')
    path=Path(ref['path']);need(path.is_absolute() and path.resolve(strict=True)==path,'status_noncanonical_path')
    mask=0o077 if private else 0o022
    parent=path.parent.stat();need(parent.st_uid==os.geteuid() and not parent.st_mode&mask,'status_unprotected_parent')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        before=os.fstat(f.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_uid==os.geteuid() and before.st_nlink==1
             and not before.st_mode&mask and 0<before.st_size<=MAX_BYTES,'status_unprotected_file')
        raw=f.read(MAX_BYTES+1);after=os.fstat(f.fileno())
    stamp=lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    need(stamp(before)==stamp(after)==stamp(path.stat()) and hashlib.sha256(raw).hexdigest()==ref['sha256'],
         'status_reference_changed')
    return raw

def read(ref):
    def pairs(items):
        result={}
        for k,v in items:need(k not in result,'status_duplicate_json_key');result[k]=v
        return result
    def constant(_):raise StatusReconcileError('status_nonfinite_json')
    return json.loads(read_reference(ref),object_pairs_hook=pairs,parse_constant=constant)

def validate_failed_cleanup(current, original, backend, status_fields):
    """Only the exact completed-cleanup/final-readiness failure is eligible."""
    ident=current.get('attempt_id')
    need(current.get('status')=='failed' and current.get('phase')=='status'
         and current.get('phase_status')=='returned' and current.get('failure_code')=='runtime_not_idle'
         and current.get('pending') is None and current.get('publication_eligible') is False,
         'status_not_post_cleanup_failure')
    need(original.get('status') in ('failed','interrupted') and original.get('publication_eligible') is False,
         'status_original_failure_required')
    mutable={'status','phase','phase_status','failure_code','receipts','events'}
    need({k:v for k,v in current.items() if k not in mutable}=={k:v for k,v in original.items() if k not in mutable},
         'status_original_accounting_changed')
    old=original.get('events');events=current.get('events')
    suffix=[('recovery_started',None,None),('operation_pending','status',None),
        ('operation_returned','status',None),('operation_pending','cleanup',None),
        ('operation_returned','cleanup',None),('operation_pending','status',None),
        ('operation_returned','status',None),('recovery_required',None,'runtime_not_idle')]
    need(isinstance(old,list) and old and isinstance(events,list) and len(events)==len(old)+len(suffix)
         and events[:len(old)]==old and len(events)<=10000,'status_recovery_history_changed')
    need(all(type(e.get('sequence')) is int and e['sequence']==i for i,e in enumerate(events)),
         'status_invalid_event_sequence')
    need(all((e.get('kind'),e.get('operation'),e.get('code'))==s for e,s in zip(events[len(old):],suffix))
         and events[-1].get('phase')=='status','status_cleanup_return_not_proven')
    receipts=current.get('receipts',{});previous=original.get('receipts',{})
    expected={k:k!='ownership_conflict' for k in status_fields};expected['ready']=False
    need(receipts.get('status')==expected and all(type(v) is bool for v in receipts['status'].values())
         and receipts.get('cleanup')=={'attempt_id':ident,'clean':True}
         and receipts['cleanup']['clean'] is True
         and {k:v for k,v in receipts.items() if k not in ('status','cleanup')}
          =={k:v for k,v in previous.items() if k not in ('status','cleanup')},'status_cleanup_receipts_changed')
    need(backend.get('attempt_id')==ident and backend.get('clean') is True and backend.get('pending') is None,
         'status_backend_not_clean')
    if backend.get('dropin'):
        checkpoint=backend.get('configuration_cleanup',{})
        need(checkpoint=={'path':backend['dropin'],'sha256':backend.get('dropin_sha256'),'phase':'verified'},
             'status_configuration_removal_unverified')


def observed_status(runtime, runtime_config, transition, deadline, *, attempt_id):
    """Explicit operational cleanup status, not a claim of a current inventory.

    The original recovery status CLI requires a trial/guard ancestry. This new
    operator already owns the original locks and uses only original read helpers;
    it never impersonates that ancestry or patches a frozen runtime method.
    """
    backend=runtime.CosmicRuntime(runtime_config)
    backend.host.deadline=deadline
    backend.context={'schema_version':1,'recovery':False};backend.state=None
    backend.load_pins();backend.online_identity()
    world,worker,cosmic=(backend.unit(role) for role in ('world','worker','cosmic'))
    queue=backend.stopped(world) and backend.stopped(worker) and backend.host.queue_count(runtime_config['queue_database'])==0
    stopped=backend.stopped(cosmic);offline=backend.account_state()==0
    configuration_absent=backend.trial_configuration_absent(cosmic)
    admin=backend.admin('status');session=admin.get('session',{});bridge=admin.get('bridge',{})
    run=bridge.get('run') or {}
    idle=(run.get('id') in (None,attempt_id)
          and (run.get('id') is None and run.get('status')=='idle'
               or run.get('id')==attempt_id and run.get('status') in ('completed','failed','timed_out','cancelled'))
          and run.get('workerActive') is False and run.get('leaseReleasePending') is False
          and bridge.get('browserReleasePending') is False and bridge.get('quarantinedRuns')==[])
    need(session.get('transitionId')==transition and session.get('state')=='waiting'
         and all(session.get(k) is True for k in ('fresh','pinned','artifactsSettled'))
         and session.get('captureState')=='idle' and bridge.get('browserReleasePending') is False,
         'status_waiting_transition_unverified')
    status={'ready':queue and stopped and offline and idle and configuration_absent,
            'queue_idle':queue,'server_stopped':stopped,'account_offline':offline,
            'controller_idle':idle,'ownership_conflict':not stopped}
    return {'status':status,'waiting_transition':transition,'observed_at_ms':round(time.time()*1000),
            'inventory_revalidated':False}


def validate_proof(proof, config_ref, config, before_ref, current, runner):
    need(isinstance(proof,dict) and set(proof)=={'schema_version','kind','configuration','before','backend',
            'recovery','observation','api_calls','cleanup_calls'} and type(proof['schema_version']) is int
         and proof['schema_version']==1 and proof['kind']==KIND and proof['configuration']==config_ref
         and proof['before']==before_ref and proof['backend']==config['backend'] and proof['recovery']==config['recovery']
         and type(proof['api_calls']) is int and proof['api_calls']==0
         and type(proof['cleanup_calls']) is int and proof['cleanup_calls']==0,'status_proof_changed')
    o=proof['observation']
    need(isinstance(o,dict) and set(o)=={'status','waiting_transition','observed_at_ms','inventory_revalidated'}
         and o['waiting_transition']==config['waiting_transition'] and o['inventory_revalidated'] is False
         and type(o['observed_at_ms']) is int and current['events'][-1]['at_ms']<=o['observed_at_ms']<=round(time.time()*1000)
         and isinstance(o['status'],dict),'status_proof_observation_invalid')
    checked=runner._status(o['status'],require_idle=True)
    need(checked==o['status'],'status_proof_observation_invalid')


def commit_reconciliation(runner, current, proof_ref, observation):
    """Preserve failure history and usage; append an explicit unscored event."""
    value=copy.deepcopy(current)
    value['status']='recovered';value['receipts']['status']=copy.deepcopy(observation['status'])
    value['events'].append({'sequence':len(value['events']),'kind':'post_cleanup_status_reconciled',
        'at_ms':observation['observed_at_ms'],'protocol':KIND,'proof':copy.deepcopy(proof_ref),
        'outcome':'invalid_no_retry','new_api_requests':0,'cleanup_repeated':False})
    return value


def reconcile_locked(config_ref, config, operation, coordinator, runner, modules, *, observe=observed_status):
    """Caller owns original operation/coordinator/world/queue/runner locks."""
    admission,experiment,trial,runtime,files=modules
    operation.lease._check();need(operation.lease._active==config['claim'],'status_original_claim_required')
    need(runner.locked is True and len(runner.lock_fds)==2,'status_runner_locks_required')
    read_reference(config['implementation'],private=False)
    coordinator.load();need(coordinator.state_sha==config['coordinator']['sha256'],'status_coordinator_changed')
    plan=coordinator.plan;ident=Path(config['journal']['path']).parent.name
    need(coordinator.state['submissions'] and coordinator.state['submissions'][-1]['attempt_id']==ident
         and ident not in coordinator.state['settled'] and 'closure' not in coordinator.state,'status_not_current_submission')
    entry=plan['entries'][len(coordinator.state['submissions'])-1]
    descriptor=admission.recovery_descriptor(config['recovery'],operation.authority['subject']['plan'],plan,entry,
        coordinator.directory,config['claim'],owner_uid=operation.uid,current=False)
    need(descriptor['coordinator']==config['coordinator'],'status_recovery_coordinator_mismatch')
    original=read(descriptor['failure']);backend=read(config['backend'])
    area=coordinator.directory/'recoveries'
    before_path=area/(ident+'.status-failed-journal.json')
    proof_path=area/(ident+'.status-proof.json')
    complete_path=area/(ident+'.status-complete.json')
    journal_path=runner.root/ident/'journal.json'
    need(config['journal']['path']==str(journal_path) and config['backend']['path']==str(journal_path.parent/'backend-state.json'),
         'status_artifact_namespace')
    need(not operation.completed,'status_operation_already_completed')
    # Save the exact failed post-cleanup bytes before any read of current runtime.
    if before_path.exists():
        before_ref=files.pin(before_path);current=read(before_ref)
        need(before_ref['sha256']==config['journal']['sha256'],'status_failed_copy_changed')
    else:
        raw=read_reference(config['journal']);current=read(config['journal'])
        fd=os.open(before_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        experiment.sync_directory(area);before_ref=files.pin(before_path)
    validate_failed_cleanup(current,original,backend,trial.STATUS_FIELDS)
    need(current['request']==entry['spec'] and current['adapter_fingerprint']==runner.adapter.fingerprint,
         'status_attempt_binding_changed')
    for prior in plan['entries'][:entry['ordinal']]:
        need(experiment.inspect_attempt(plan,prior)['terminal_clean'],'status_prior_attempt_unresolved')
    need(all(not os.path.lexists(runner.root/future['attempt_id']) for future in plan['entries'][entry['ordinal']+1:]),
         'status_future_attempt_exists')
    configuration=read(config['runtime'])
    adapter=read(descriptor['adapter_config'])
    need(adapter['argv']==[plan['runner']['python']['path'],str(Path(config['original_source'])/'full_client_runtime.py'),
             '--config',config['runtime']['path']]
         and configuration['orchestrator']==plan['runner']['trial_script']
         and all(configuration[k]==plan['runner'][k if k!='attempt_root' else 'state_root']
                 for k in ('world_lock','queue_lock','attempt_root')),'status_runtime_binding_changed')
    journal,actual_ref=admission.private_ref(journal_path,owner_uid=operation.uid)
    if proof_path.exists():
        proof_ref=files.pin(proof_path);proof=read(proof_ref)
        validate_proof(proof,config_ref,config,before_ref,current,runner)
        proposed=commit_reconciliation(runner,current,proof_ref,proof['observation'])
        if journal==proposed:
            evidence=admission.trial_terminal(runner,ident,entry['spec'],owner_uid=operation.uid)
            value={'schema_version':1,'kind':KIND,'status':'recovered_unscored','proof':proof_ref,'evidence':evidence,
                   'new_api_requests':0,'cleanup_calls':0,'group_claim_completed':False,'coordinator_changed':False}
            if complete_path.exists():need(read(files.pin(complete_path))==value,'status_completion_changed')
            else:files.create(complete_path,value)
            return value
        need(actual_ref==config['journal'],'status_journal_changed')
        # An observation-only retry is allowed; it cannot repeat cleanup. The
        # original immutable proof remains bound to the same waiting transition.
    else:
        need(actual_ref==config['journal'],'status_journal_changed')
        proof=None
    observation=observe(runtime,configuration,config['waiting_transition'],time.monotonic()+config['timeout_seconds'],attempt_id=ident)
    runner._status(observation['status'],require_idle=True)
    need(observation['waiting_transition']==config['waiting_transition']
         and type(observation['observed_at_ms']) is int and observation['observed_at_ms']>=current['events'][-1]['at_ms'],
         'status_observation_invalid')
    # Re-read all pinned inputs after the potentially slow read-only observation.
    read(config_ref)
    for key in ('authority','claim','recovery','coordinator','backend','runtime'):read(config[key])
    read(descriptor['failure'])
    read_reference(config['implementation'],private=False)
    read_reference(config['journal']);operation.lease._check()
    if proof is None:
        proof={'schema_version':1,'kind':KIND,'configuration':config_ref,'before':before_ref,'backend':config['backend'],
               'recovery':config['recovery'],'observation':observation,'api_calls':0,'cleanup_calls':0}
        validate_proof(proof,config_ref,config,before_ref,current,runner)
        proof_ref=files.create(proof_path,proof)
    else:
        runner._status(proof['observation']['status'],require_idle=True)
        need(proof['observation']['waiting_transition']==observation['waiting_transition'],'status_proof_transition_changed')
    proposed=commit_reconciliation(runner,current,proof_ref,proof['observation'])
    trial.atomic_json(journal_path,proposed)
    # Re-enter only the saved-byte branch; no second observation or action.
    return reconcile_locked(config_ref,config,operation,coordinator,runner,modules,observe=observe)


def execute(config_ref):
    config=read(config_ref)
    need(set(config)==FIELDS and type(config['schema_version']) is int and config['schema_version']==1
         and config['kind']==KIND and type(config['timeout_seconds']) is int and 1<=config['timeout_seconds']<=120
         and isinstance(config['waiting_transition'],str) and re.fullmatch('[a-f0-9]{32}',config['waiting_transition']),
         'status_invalid_configuration')
    need(config['implementation']['path']==str(Path(__file__).resolve()),'status_implementation_mismatch')
    read_reference(config['implementation'],private=False)
    authority=read(config['authority']);sources=authority['source_files']
    need(isinstance(sources,list) and 3<=len(sources)<=64,'status_source_limit')
    old=Path(config['original_source']);need(old.is_absolute() and old.resolve(strict=True)==old,'status_original_source_required')
    paths={r['path']:r for r in sources};need(len(paths)==len(sources),'status_duplicate_source')
    total=0
    for ref in sources:
        raw=read_reference(ref,private=False);total+=len(raw);need(total<=32*1024*1024,'status_source_limit')
    names=('full_client_operation_admission','full_client_experiment','full_client_trial','full_client_runtime','full_client_pre_runtime_abort')
    need(all(str(old/(n+'.py')) in paths for n in names),'status_original_modules_missing')
    need(not any(n in sys.modules for n in names),'status_modules_already_loaded')
    sys.path.insert(0,str(old));modules=tuple(importlib.import_module(n) for n in names)
    admission,experiment,trial,runtime,files=modules
    loaded=[]
    for name,module in list(sys.modules.items()):
        if name.startswith('full_client_') and name!='full_client_post_cleanup_status':
            path=str(Path(module.__file__).resolve());need(path in paths,'status_loaded_source_unpinned')
            read_reference(paths[path],private=False);loaded.append(path)
    plan=experiment.validate_plan(read(authority['subject']['plan']))
    coordinator=experiment.Experiment(plan,authority['subject']['experiment_directory'])
    ident=Path(config['journal']['path']).parent.name
    entry=next((e for e in plan['entries'] if e['attempt_id']==ident),None);need(entry is not None,'status_attempt_not_in_plan')
    fixture=experiment.fixture_for(plan,entry);adapter=read(fixture['adapter_config'])
    runner=trial.TrialRunner(plan['runner']['state_root'],plan['runner']['world_lock'],plan['runner']['queue_lock'],
                            trial.CommandAdapter(adapter['argv'],adapter['dependencies']))
    with admission.admitted(config['authority'],authority['subject'],'finite_group',runner.root,
            claim_ref=config['claim'],required_sources=loaded,owner_uid=os.geteuid()) as operation:
        with coordinator.locked(),runner._locks():
            return reconcile_locked(config_ref,config,operation,coordinator,runner,modules)


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--config-sha256',required=True);args=p.parse_args()
    try:
        need(sys.platform.startswith('linux') and os.geteuid()==0,'status_linux_root_required')
        print(json.dumps(execute({'path':args.config,'sha256':args.config_sha256}),sort_keys=True));return 0
    except Exception as error:
        print(json.dumps({'status':'blocked','code':str(error) if isinstance(error,StatusReconcileError) else 'status_reconciliation_failed',
                          'api_calls':0,'cleanup_calls':0}));return 1
if __name__=='__main__':raise SystemExit(main())
