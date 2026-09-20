"""Explicit, operator-only closeout of a proven untouched finite group.

The failed trial and coordinator remain immutable. This is not cleanup, recovery,
scoring, or permission to ignore arbitrary failures. Only a completed original
operation claim plus this exact typed evidence releases the failed-attempt scan.
"""
from __future__ import annotations
import argparse
from contextvars import ContextVar
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time

KIND = 'full-client-pre-runtime-abort-v1'
ID = re.compile(r'[a-f0-9]{32}\Z')
MAX_BYTES = 4 * 1024 * 1024
CONFIG_FIELDS={'schema_version','authority','claim','coordinator','journal','runtime','snapshot','original_source','attempt_ids','implementation','group_unit','group_invocation'}

_BUDGET=ContextVar('pre_runtime_abort_budget',default=None)
def bounded(seconds):
    def decorate(fn):
        @wraps(fn)
        def wrapper(*args,**kwargs):
            if _BUDGET.get() is not None:return fn(*args,**kwargs)
            token=_BUDGET.set([time.monotonic()+seconds,64*1024*1024,4096])
            try:return fn(*args,**kwargs)
            finally:_BUDGET.reset(token)
        return wrapper
    return decorate

def charge(size):
    budget=_BUDGET.get()
    if budget is not None:
        need(time.monotonic()<budget[0] and size<=budget[1] and budget[2]>0,'abort_aggregate_limit')
        budget[1]-=size;budget[2]-=1

class AbortError(RuntimeError): pass

def need(value, code):
    if not value: raise AbortError(code)

def encoded(value): return (json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode()

def raw_read(ref, *, private=False):
    need(isinstance(ref,dict) and set(ref)=={'path','sha256'}, 'abort_invalid_reference')
    path=Path(ref['path'])
    need(path.is_absolute() and path.resolve(strict=True)==path, 'abort_noncanonical_path')
    for parent in (path.parent,):
        info=parent.stat();need(info.st_uid==os.geteuid() and not info.st_mode&(0o077 if private else 0o022),'abort_unprotected_parent')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        a=os.fstat(f.fileno())
        need(stat.S_ISREG(a.st_mode) and a.st_uid==os.geteuid() and a.st_nlink==1 and not a.st_mode&(0o077 if private else 0o022) and a.st_size<=MAX_BYTES,'abort_unprotected_file')
        charge(a.st_size+1);raw=f.read(MAX_BYTES+1);b=os.fstat(f.fileno())
    stamp=lambda x:(x.st_dev,x.st_ino,x.st_mode,x.st_uid,x.st_gid,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
    need(stamp(a)==stamp(b)==stamp(path.stat()) and hashlib.sha256(raw).hexdigest()==ref['sha256'],'abort_reference_changed')
    return raw

def read(ref):
    def pairs(items):
        result={}
        for k,v in items:
            need(k not in result,'abort_duplicate_json_key');result[k]=v
        return result
    def constant(value):raise AbortError('abort_nonfinite_json')
    return json.loads(raw_read(ref,private=True),object_pairs_hook=pairs,parse_constant=constant)

def pin(path):
    path=Path(path);need(path.is_absolute() and path.resolve(strict=True)==path,'abort_noncanonical_path')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        a=os.fstat(f.fileno());need(stat.S_ISREG(a.st_mode) and a.st_uid==os.geteuid() and a.st_nlink==1 and not a.st_mode&0o022 and a.st_size<=MAX_BYTES,'abort_unprotected_file')
        charge(a.st_size+1);raw=f.read(MAX_BYTES+1);b=os.fstat(f.fileno())
    stamp=lambda x:(x.st_dev,x.st_ino,x.st_mode,x.st_uid,x.st_gid,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
    need(stamp(a)==stamp(b)==stamp(path.stat()),'abort_reference_changed')
    ref={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()};read(ref);return ref

def create(path,value):
    raw=encoded(value);fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return pin(path)

def untouched(journal):
    need(journal.get('status')=='failed' and journal.get('api_outcome')=='not_started'
         and journal.get('charged_usage')=={'api_requests':0,'total_tokens':0}
         and journal.get('publication_eligible') is False, 'abort_trial_touched')
    events=journal.get('events');need(isinstance(events,list) and 1<=len(events)<=100,'abort_invalid_events')
    expected=[('attempt_created',None,None),('operation_pending','status',None),
        ('recovery_required',None,'invalid_limit_timeout_seconds'),('recovery_started',None,None),
        ('operation_pending','status',None),('operation_returned','status',None),
        ('operation_pending','cleanup',None),('recovery_required',None,'orchestrator_identity_mismatch')]
    need(len(events)==len(expected),'abort_invalid_events')
    for i,(event,shape) in enumerate(zip(events,expected)):
        need(event.get('sequence')==i and (event.get('kind'),event.get('operation'),event.get('code'))==shape,'abort_unsafe_event')
    need(events[2].get('phase')=='status' and events[3].get('interrupted_phase')=='status'
         and events[7].get('phase')=='cleanup' and journal.get('phase')=='cleanup'
         and journal.get('phase_status')=='pending' and journal.get('failure_code')=='orchestrator_identity_mismatch','abort_unrecognized_failure')
    need(journal.get('receipts')=={'status':{'account_offline':True,'controller_idle':True,'ownership_conflict':False,'queue_idle':True,'ready':True,'server_stopped':True}},'abort_runtime_receipt')

def validate_proof(proof,root, *, observed=True):
    need(set(proof)=={'schema_version','kind','outcome','authority','claim','plan','coordinator','configuration','journal','retired_attempt_ids','observations','api_calls'},'abort_proof_schema')
    need(type(proof.get('schema_version')) is int and proof.get('schema_version')==1 and proof.get('kind')==KIND and proof.get('outcome')=='aborted_before_runtime_no_score','abort_wrong_certificate')
    authority=read(proof['authority']);
    need(set(authority)=={'schema_version','operation_id','kind','gate','subject','source_files'} and type(authority['schema_version']) is int and authority['schema_version']==1,'abort_authority_schema')
    need(isinstance(authority['source_files'],list) and 3<=len(authority['source_files'])<=64,'abort_source_limit')
    for source in authority['source_files']:raw_read(source)
    lock=authority['gate'];need(set(lock)=={'path','device','inode','uid','mode'} and lock['path']==str(root/'.operations/.gate.lock'),'abort_gate_namespace')
    info=Path(lock['path']).lstat();need(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size==0 and (info.st_dev,info.st_ino,info.st_uid,stat.S_IMODE(info.st_mode))==tuple(lock[k] for k in ('device','inode','uid','mode')),'abort_gate_changed')
    claim=read(proof['claim']);need(set(claim)=={'schema_version','operation_id','kind','authority','created_at_ms','owner'} and type(claim['schema_version']) is int and claim['schema_version']==1
        and type(claim['created_at_ms']) is int and claim['created_at_ms']>=0 and set(claim['owner'])=={'pid','uid'} and type(claim['owner']['pid']) is int and claim['owner']['pid']>0 and type(claim['owner']['uid']) is int and claim['owner']['uid']==os.geteuid(),'abort_claim_schema')
    plan=read(proof['plan']);coordinator=read(proof['coordinator'])
    need(proof['coordinator']['path']==str(Path(authority['subject']['experiment_directory'])/'coordinator.json')
         and coordinator.get('plan_sha256')==proof['plan']['sha256'],'abort_coordinator_binding')
    need(authority['kind']==claim['kind']=='finite_group' and claim['authority']==proof['authority'] and claim['operation_id']==authority['operation_id']
         and authority['subject']['plan']==proof['plan'] and plan['runner']['state_root']==str(root),'abort_claim_binding')
    need(Path(proof['claim']['path'])==root/'.operations'/claim['operation_id']/'claim.json','abort_claim_namespace')
    need(isinstance(proof['retired_attempt_ids'],list) and len(proof['retired_attempt_ids'])==4 and all(isinstance(i,str) and ID.fullmatch(i) for i in proof['retired_attempt_ids']),'abort_four_ids_required')
    need(proof['retired_attempt_ids']==[e['attempt_id'] for e in plan['entries']] and len(set(proof['retired_attempt_ids']))==len(proof['retired_attempt_ids']), 'abort_withdrawal_mismatch')
    need(coordinator['status']=='stopped' and len(coordinator['submissions'])==1 and coordinator['submissions'][0]['attempt_id']==plan['entries'][0]['attempt_id']
         and type(coordinator['submissions'][0].get('returncode')) is int and not coordinator['settled'] and 'closure' not in coordinator,'abort_coordinator_touched')
    need(proof['journal']['path']==str(root/plan['entries'][0]['attempt_id']/'journal.json'),'abort_journal_namespace')
    journal=read(proof['journal']);untouched(journal)
    need(journal['request']==plan['entries'][0]['spec'] and journal['attempt_id']==plan['entries'][0]['attempt_id'],'abort_request_changed')
    need(sorted(p.name for p in (root/journal['attempt_id']).iterdir())==['journal.json'],'abort_attempt_artifact')
    need(all(not os.path.lexists(root/i) for i in proof['retired_attempt_ids'][1:]),'abort_future_attempt_exists')
    config=read(proof['configuration']);need(set(config)==CONFIG_FIELDS and type(config['schema_version']) is int and config['schema_version']==1,'abort_configuration_schema');need(config['authority']==proof['authority'] and config['claim']==proof['claim'] and config['journal']==proof['journal'] and config['coordinator']==proof['coordinator'] and config['attempt_ids']==proof['retired_attempt_ids'],'abort_configuration_binding')
    fixture=next(f for f in plan['fixtures'] if f['id']==plan['entries'][0]['fixture_id'])
    adapter=read(fixture['adapter_config']);runtime=read(config['runtime'])
    need(adapter['argv'][-2:]==['--config',config['runtime']['path']] and runtime['baseline']==fixture['baseline'] and runtime['baseline_snapshot']==config['snapshot'] and runtime['runtime_manifest']==fixture['runtime_manifest'],'abort_runtime_binding')
    need(journal['adapter_fingerprint']==fixture['adapter_fingerprint'],'abort_adapter_changed')
    need(type(proof.get('api_calls')) is int and proof['api_calls']==0,'abort_api_claim')
    raw_read(config['implementation'])
    if observed:
        o=proof['observations'];need(set(o)=={'ready','account_offline','baseline_snapshot','browser_transition','services_stopped','api_calls','observed_at_ms','processes_absent','artifacts_absent','group_unit','group_invocation','group_cgroup_empty'},'abort_observation_schema')
        need(all(o[k] is True for k in ('ready','account_offline','services_stopped','processes_absent','artifacts_absent','group_cgroup_empty')) and o['baseline_snapshot']==config['snapshot']
             and isinstance(o['browser_transition'],str) and ID.fullmatch(o['browser_transition'])
             and type(o['observed_at_ms']) is int and o['observed_at_ms']>=claim['created_at_ms']
             and o['group_unit']==config['group_unit'] and o['group_invocation']==config['group_invocation'] and type(o['api_calls']) is int and o['api_calls']==0,'abort_observation_missing')
    return claim

@bounded(15)
def certified(root):
    """Fail closed on partial aborts; no lock acquisition (runner already owns locks)."""
    root=Path(root);base=root/'.pre-runtime-aborts'
    if not os.path.lexists(base): return set(),set()
    need(base.is_dir() and not base.is_symlink() and base.stat().st_uid==os.geteuid() and stat.S_IMODE(base.stat().st_mode)==0o700,'abort_invalid_directory')
    retired=set();failed=set();folders=list(base.iterdir());need(len(folders)<=128,'abort_registry_limit')
    for folder in folders:
        need(ID.fullmatch(folder.name) and folder.is_dir() and not folder.is_symlink(),'abort_invalid_directory')
        cert=read(pin(folder/'certificate.json'));need(set(cert)=={'proof','terminal'},'abort_certificate_schema');proof_ref=cert['proof'];proof=read(proof_ref)
        need(proof_ref['path']==str(folder/'proof.json'),'abort_proof_namespace')
        claim=validate_proof(proof,root)
        need(folder.name==claim['operation_id'],'abort_operation_namespace')
        terminal=read(cert['terminal']);need(set(terminal)=={'schema_version','operation_id','claim_sha256','completed_at_ms','receipt'} and type(terminal['schema_version']) is int and terminal['schema_version']==1 and type(terminal['completed_at_ms']) is int and terminal['completed_at_ms']>=claim['created_at_ms'],'abort_terminal_schema')
        authority=read(proof['authority']);need(terminal['receipt']['path']==str(Path(proof['authority']['path']).parent/'.operation-receipts'/folder.name/'terminal-receipt.json'),'abort_receipt_namespace')
        receipt=read(terminal['receipt']);need(set(receipt)=={'schema_version','operation_id','claim_sha256','status','quiescent','evidence'} and type(receipt['schema_version']) is int and receipt['schema_version']==1,'abort_receipt_schema')
        need(cert['terminal']['path']==str(root/'.operations'/folder.name/'terminal.json')
             and terminal['operation_id']==folder.name and terminal['claim_sha256']==proof['claim']['sha256']
             and receipt['operation_id']==folder.name and receipt['claim_sha256']==proof['claim']['sha256']
             and receipt['status']=='completed' and receipt['quiescent'] is True and receipt['evidence']==[proof_ref], 'abort_terminal_chain')
        need(not retired.intersection(proof['retired_attempt_ids']),'abort_duplicate_retirement')
        retired.update(proof['retired_attempt_ids']);failed.add(proof['retired_attempt_ids'][0])
    return retired,failed

def observe(config,runtime,trial,deadline):
    backend=runtime.CosmicRuntime(read(config['runtime']));backend.host.deadline=deadline
    backend.context={'schema_version':1,'recovery':False};backend.state=None
    status=backend.status();need(status.get('ready') is True and not status.get('ownership_conflict'),'abort_runtime_not_ready')
    for role in ('world','worker','cosmic'):
        unit=backend.unit(role);need(backend.stopped(unit),'abort_live_service')
    need(backend.trial_configuration_absent(backend.unit('cosmic')),'abort_owned_configuration')
    admin=backend.admin('status');session=admin.get('session',{});bridge=admin.get('bridge',{});run=bridge.get('run') or {}
    need(session.get('state')=='waiting' and all(session.get(k) is True for k in ('fresh','pinned','artifactsSettled'))
         and session.get('captureState')=='idle' and run.get('status')=='idle' and run.get('id') is None
         and run.get('workerActive') is False and run.get('leaseReleasePending') is False
         and bridge.get('browserReleasePending') is False and bridge.get('quarantinedRuns')==[],'abort_browser_busy')
    import full_client_collect
    db=backend.config['mysql'];snapshot=full_client_collect.collect(mysql_command=db['command'],defaults_file=db['defaults_file'],database=db['database'],character_id=db['character_id'],account_id=db['account_id'],run_id='pre-runtime-abort',timeout=min(10,backend.host.remaining()))
    expected=read(config['snapshot']);need(snapshot['account_logged_in']==0 and snapshot['character']==expected['character'] and snapshot['keymap']==expected['keymap'],'abort_baseline_changed')
    scripts={backend.config['orchestrator']['path'].encode(),str(Path(config['original_source'])/'full_client_experiment.py').encode()}
    name=config['group_unit'];need(re.fullmatch(r'maplebench-[a-zA-Z0-9-]+\.service',name) and ID.fullmatch(config['group_invocation']),'abort_group_identity')
    output=backend.host.command([backend.config['systemctl'],'show',name,'--no-pager','--property=MainPID,ControlPID,ControlGroup,ActiveState,InvocationID'],maximum=4096)
    unit=dict(line.split('=',1) for line in output.decode().splitlines() if '=' in line)
    need(unit.get('MainPID')==unit.get('ControlPID')=='0' and unit.get('ActiveState') in ('inactive','failed') and unit.get('InvocationID') in ('',config['group_invocation']),'abort_group_active')
    group=unit.get('ControlGroup');need(isinstance(group,str),'abort_group_cgroup_missing')
    if group:
        need(group.startswith('/') and '..' not in Path(group).parts,'abort_group_cgroup_invalid')
        cg=Path('/sys/fs/cgroup')/group.lstrip('/')
        need(cg.resolve()==cg,'abort_group_cgroup_invalid')
        if cg.exists():
            with (cg/'cgroup.events').open('rb') as stream:events=stream.read(4097)
            need(len(events)<=4096 and b'populated 0' in events.splitlines(),'abort_group_cgroup_active')
    procs=list(Path('/proc').iterdir());need(len(procs)<=32768,'abort_process_limit')
    for p in procs:
        if p.name.isdigit():
            backend.host.remaining()
            try:
                with (p/'cmdline').open('rb') as stream:cmd=stream.read(1048577)
                need(len(cmd)<=1048576,'abort_process_argument_limit')
            except FileNotFoundError:continue
            need(not scripts.intersection(cmd.split(b'\0')),'abort_live_orchestrator')
    for ident in config['attempt_ids']:
        for key in ('relay_output_root','native_output_root'):
            root=Path(backend.config[key])
            need(not os.path.lexists(root/ident),'abort_runtime_artifact')
            if root.exists():
                paths=list(root.iterdir());need(len(paths)<=10000,'abort_artifact_limit')
                need(not any(ident in p.name for p in paths),'abort_runtime_artifact')
    return {'ready':True,'account_offline':True,'baseline_snapshot':config['snapshot'],'browser_transition':session.get('transitionId'),'services_stopped':True,'api_calls':0,'observed_at_ms':int(time.time()*1000),'processes_absent':True,'artifacts_absent':True,'group_unit':name,'group_invocation':config['group_invocation'],'group_cgroup_empty':True}

@bounded(120)
def execute(config_ref):
    deadline=time.monotonic()+120
    config=read(config_ref);need(set(config)==CONFIG_FIELDS and type(config['schema_version']) is int and config['schema_version']==1,'abort_invalid_config')
    authority=read(config['authority']);source_refs=authority['source_files']
    need(isinstance(source_refs,list) and 3<=len(source_refs)<=64,'abort_invalid_sources')
    sources={r['path']:r for r in source_refs};need(len(sources)==len(source_refs),'abort_duplicate_sources')
    old=Path(config['original_source']);need(old.is_absolute() and old.resolve()==old,'abort_invalid_source')
    names=('full_client_operation_admission.py','full_client_operation_gate.py','full_client_operation_join.py','full_client_trial.py','full_client_experiment.py','full_client_runtime.py')
    need(all(str(old/n) in sources for n in names),'abort_source_not_authorized')
    for ref in source_refs:raw_read(ref)
    sys.path.insert(0,str(old))
    import full_client_operation_admission as admission
    import full_client_experiment as experiment
    import full_client_trial as trial
    import full_client_runtime as runtime
    import full_client_collect, full_client_score, full_client_freeze
    loaded=[]
    for name,module in list(sys.modules.items()):
        if name.startswith('full_client_') and name!='full_client_pre_runtime_abort':
            path=str(Path(module.__file__).resolve());need(path in sources,'abort_loaded_source_unpinned');raw_read(sources[path]);loaded.append(path)
    raw_read(config['implementation']);need(config['implementation']['path']==str(Path(__file__).resolve()),'abort_implementation_changed')
    authority=read(config['authority']);root=Path(read(authority['subject']['plan'])['runner']['state_root'])
    plan=experiment.validate_plan(read(authority['subject']['plan']));need(config['attempt_ids']==[e['attempt_id'] for e in plan['entries']],'abort_ids_changed')
    coordinator=experiment.Experiment(plan,authority['subject']['experiment_directory'])
    runner=trial.TrialRunner(root,plan['runner']['world_lock'],plan['runner']['queue_lock'],None)
    with admission.admitted(config['authority'],authority['subject'],'finite_group',root,claim_ref=config['claim'],required_sources=loaded,owner_uid=os.geteuid()) as operation:
        base=root/'.pre-runtime-aborts'
        if not base.exists():base.mkdir(mode=0o700)
        folder=base/authority['operation_id']
        if not folder.exists():folder.mkdir(mode=0o700)
        if operation.completed:
            if not (folder/'certificate.json').exists():
                proof_ref=pin(folder/'proof.json');validate_proof(read(proof_ref),root)
                receipt=read(read(operation.terminal)['receipt']);need(receipt['evidence']==[proof_ref],'abort_terminal_chain')
                create(folder/'certificate.json',{'proof':proof_ref,'terminal':operation.terminal})
            certified(root);return {'status':'already_aborted','api_calls':0}
        with coordinator.locked(),runner._locks():
            intent={'configuration':config_ref,'authority':config['authority'],'claim':config['claim']}
            if (folder/'intent.json').exists():need(read(pin(folder/'intent.json'))==intent,'abort_intent_changed')
            else:create(folder/'intent.json',intent)
            if (folder/'proof.json').exists():
                proof_ref=pin(folder/'proof.json');proof=read(proof_ref);validate_proof(proof,root)
                observe(config,runtime,trial,deadline)
            else:
                proof={'schema_version':1,'kind':KIND,'outcome':'aborted_before_runtime_no_score','authority':config['authority'],'claim':config['claim'],'plan':authority['subject']['plan'],'coordinator':config['coordinator'],'configuration':config_ref,'journal':config['journal'],'retired_attempt_ids':config['attempt_ids'],'observations':{'ready':True},'api_calls':0}
                validate_proof(proof,root,observed=False)
                proof['observations']=observe(config,runtime,trial,deadline)
                validate_proof(proof,root);read(config_ref)
                proof_ref=create(folder/'proof.json',proof)
            validate_proof(read(proof_ref),root)
            observe(config,runtime,trial,deadline)
            validate_proof(read(proof_ref),root)
            terminal=operation.finish([proof_ref])
            create(folder/'certificate.json',{'proof':proof_ref,'terminal':terminal})
            certified(root)
            return {'status':'aborted_before_runtime_no_score','api_calls':0,'certificate':pin(folder/'certificate.json')}

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--config-sha256',required=True);args=p.parse_args()
    try:
        need(sys.platform.startswith('linux') and os.geteuid()==0,'abort_linux_root_required')
        print(json.dumps(execute({'path':args.config,'sha256':args.config_sha256}),sort_keys=True));return 0
    except Exception as error:
        print(json.dumps({'status':'blocked','code':str(error) if isinstance(error,AbortError) else 'abort_failed','api_calls':0}));return 1
if __name__=='__main__':raise SystemExit(main())
