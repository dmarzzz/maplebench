"""Read-only zero-API native XP-window acceptance, separate from model scoring.

This module does not launch, retry, restore, grant runtime authority, or invent
adaptive cycles. A separately owned executor must produce all pinned artifacts.
"""
import hashlib
import json
import math
from full_client_score import parse_json,read_artifact_bytes,read_json_artifact,same_json
from full_client_xp_windows import (IDENTITY,WINDOW_MS,MAX_LEDGER_BYTES,score_ledger,
    validate_contract,integer,require,PROTOCOL as WINDOW_PROTOCOL)
PROTOCOL='native-xp-ledger-acceptance-v1'
MAX_CONTROL_START_DELAY_MS=5000
MAX_CONTROL_MS=30000


def verify_sdk_receipts(steps,native):
    """Recheck original native SDK receipts with the frozen keyboard contract."""
    from maple_agent import validate_rpc
    require(isinstance(steps,list) and 1<=len(steps)<=native['max_sdk_requests'],'native_sdk_steps_required')
    rpc=[];actions=0
    def observation(value):
        require(isinstance(value,dict) and value.get('ready') is True
                and isinstance(value.get('character'),dict)
                and all(type(value.get(k)) in (int,float) and math.isfinite(value[k])
                        and 0<=value[k]<1500 for k in ('ageMs','renderAgeMs')),
                'native_observation_not_fresh')
    for step in steps:
        require(isinstance(step,dict) and step.get('kind')=='sdk'
                and step.get('method') in ('observe','pressKeys','wait'), 'invalid_native_sdk_step')
        try:
            method,argument=validate_rpc({'type':'rpc','id':step.get('rpcId'),
                'method':step['method'],'args':step.get('args')},
                {'adapter':'full-client','protocol':native['id']})
        except ValueError:
            require(False,'invalid_native_sdk_arguments')
        rpc.append(step['rpcId']);receipt=step.get('result')
        require(isinstance(receipt,dict) and receipt.get('error') in (None,''), 'native_sdk_error')
        if method=='pressKeys':
            require(receipt.get('accepted') is True,'native_input_not_accepted')
            observation(receipt.get('observation'));actions+=1
        elif method=='observe':observation(receipt)
        else:
            # The native envelope requires program_complete, so a clipped wait
            # cannot be accepted as a successful completion of this recipe.
            require(type(receipt.get('waitedMs')) is int and receipt['waitedMs']==argument,
                    'native_wait_not_complete')
    require(len(set(rpc))==len(rpc) and rpc==sorted(rpc),'native_sdk_count_mismatch')
    return actions


def verify_control(control,scenario,identity,window,baseline_sha256,actual,program_raw):
    from full_client_native import validate_contract as native_contract,program
    require(isinstance(scenario,dict) and set(scenario)=={'protocol','native_contract','xp_window_protocol'}
            and scenario['protocol']==PROTOCOL,'native_scenario_required')
    native=native_contract(scenario['native_contract'])
    require(native['baseline_sha256']==baseline_sha256,'native_fixture_mismatch')
    expected_program=program(native).encode();program_hash=hashlib.sha256(expected_program).hexdigest()
    require(program_raw==expected_program and isinstance(actual,dict),'original_native_program_required')
    owner=actual.get('controller',{});execution=actual.get('program',{});timeline=actual.get('timeline',{});timing=actual.get('timing',{})
    require({'protocol','nativeAcceptance','api','trialContext','source','model_api_requests','publication_eligible','score','programSha256','controller','program','timeline','timing'}<=set(actual)
            and actual.get('protocol')==native['id'] and same_json(actual.get('nativeAcceptance'),native)
            and actual.get('api') is None and actual.get('trialContext') is None
            and actual.get('source')=='client telemetry; unscored integration run'
            and type(actual.get('model_api_requests')) is int and actual['model_api_requests']==0
            and actual.get('publication_eligible') is False and actual.get('score') is None
            and actual.get('programSha256')==program_hash
            and isinstance(owner,dict) and {'id','mode','model','returnedModel','trialContext','protocol','nativeAcceptance','status','reason','workerActive','actions'}<=set(owner) and owner.get('id')==identity['run_id']
            and owner.get('mode')=='script' and owner.get('model') is None and owner.get('returnedModel') is None
            and owner.get('trialContext') is None and owner.get('protocol')==native['id']
            and same_json(owner.get('nativeAcceptance'),native)
            and owner.get('status')=='completed' and owner.get('workerActive') is False
            and isinstance(execution,dict) and execution.get('reason')=='program_complete'
            and execution.get('error') is None and owner.get('reason')=='program_complete'
            and timeline.get('status')=='completed','original_native_success_required')
    steps=execution.get('steps')
    actions=verify_sdk_receipts(steps,native)
    require(integer(actions,1,native['max_actions'])
            and type(execution.get('actions')) is int and execution['actions']==actions
            and type(owner.get('actions')) is int and owner['actions']==actions
            and type(execution.get('actionAttempts')) is int and execution['actionAttempts']==actions
            and type(execution.get('rpcRequests')) is int and execution['rpcRequests']==len(steps),
            'native_sdk_count_mismatch')
    require(isinstance(window,dict) and set(window)=={'start_at_ms','deadline_at_ms','window_ms'}
            and all(integer(window[k]) for k in window) and window['window_ms']==WINDOW_MS
            and window['deadline_at_ms']-window['start_at_ms']==300000
            and all(integer(timing.get(k)) for k in ('startedAtMs','endedAtMs','elapsedMs','apiLatencyMs'))
            and timing['apiLatencyMs']==0 and abs(timing['endedAtMs']-timing['startedAtMs']-timing['elapsedMs'])<=25
            and all(integer(timeline.get(k)) for k in ('program_started_ms','program_ended_ms')),
            'native_control_timing_required')
    started=timing['startedAtMs']+timeline['program_started_ms'];ended=timing['startedAtMs']+timeline['program_ended_ms']
    require(window['start_at_ms']<=timing['startedAtMs']<=started
            and started-window['start_at_ms']<=MAX_CONTROL_START_DELAY_MS
            and 0<ended-started<=native['wall_seconds']*1000
            and ended<=timing['endedAtMs']<=window['start_at_ms']+45000,'fixed_native_control_window_required')
    derived={'schema_version':1,'protocol':PROTOCOL,'run_id':identity['run_id'],'model':None,'api_calls':0,
            'started_at_ms':started,'ended_at_ms':ended,'accepted_actions':actions,
            'sdk_requests':len(steps),'program_sha256':program_hash}
    require(same_json(control,derived),'normalized_native_control_mismatch')
    return derived


def verify_coverage(raw,identity,window,*,control=None):
    require(isinstance(raw,bytes) and 0<len(raw)<=256*1024 and raw.endswith(b'\n'),'native_coverage_missing')
    rows=[parse_json(line) for line in raw.splitlines()]
    require(2<=len(rows)<=301,'native_coverage_count')
    fields={'sequence','wall_ms','monotonic_ns','run_id','server_instance_id','account_id','character_id',
            'server_owned','account_online','renderer_fresh','controller_idle'}
    start=window['start_at_ms'];end=window['deadline_at_ms']
    idle_deadline=start+MAX_CONTROL_START_DELAY_MS+MAX_CONTROL_MS
    if control is not None:
        # verify_bundle passes the control derived from original program evidence.
        # Optional bounds may tighten this deadline, never extend the envelope.
        require(isinstance(control,dict) and control.get('protocol')==PROTOCOL
                and control.get('run_id')==identity['run_id'] and control.get('model') is None
                and type(control.get('api_calls')) is int and control['api_calls']==0
                and integer(control.get('started_at_ms')) and integer(control.get('ended_at_ms'))
                and start<=control['started_at_ms']<=start+MAX_CONTROL_START_DELAY_MS
                and 0<control['ended_at_ms']-control['started_at_ms']<=MAX_CONTROL_MS,
                'native_coverage_control_mismatch')
        idle_deadline=control['started_at_ms']+MAX_CONTROL_MS
    for i,row in enumerate(rows):
        require(isinstance(row,dict) and set(row)==fields and type(row['sequence']) is int and row['sequence']==i
                and integer(row['wall_ms']) and integer(row['monotonic_ns'])
                and all(type(row[k]) is type(v) and row[k]==v for k,v in identity.items())
                and all(row[k] is True for k in ('server_owned','account_online','renderer_fresh'))
                and type(row['controller_idle']) is bool,'invalid_native_coverage_sample')
        if i:
            wall=row['wall_ms']-rows[0]['wall_ms'];elapsed=(row['monotonic_ns']-rows[0]['monotonic_ns'])/1000000
            gap=(row['monotonic_ns']-rows[i-1]['monotonic_ns'])/1000000
            require(0<gap<=1500 and abs(wall-elapsed)<=25,'native_coverage_gap_or_clock_jump')
        # Row zero precedes submission and is intentionally idle, even when the
        # subsequent program's measured start shares its millisecond timestamp.
        if i and control is not None and control['started_at_ms']<=row['wall_ms']<control['ended_at_ms']:
            require(row['controller_idle'] is False,'native_control_idle_before_completion')
        # Start may take at most five seconds; execution still lasts at most 30.
        if row['wall_ms']>=idle_deadline:require(row['controller_idle'] is True,'native_control_exceeded_recipe')
    require(rows[0]['wall_ms']==start and end<=rows[-1]['wall_ms']<=end+1000
            and 300000<=(rows[-1]['monotonic_ns']-rows[0]['monotonic_ns'])/1000000<=301000,
            'incomplete_native_coverage')


def collect_passive_coverage(first, observe, append, *, monotonic_ns, sleep):
    """Bounded callback collector; caller already owns and durably started native control.

    `observe` performs one read-only status sample, `append` persists it once.
    No callback is retried after an uncertain read/write and the deadline never
    moves. Runtime locks and identity validation remain the executor's duty.
    """
    require(isinstance(first,dict) and integer(first.get('monotonic_ns')),
            'native_coverage_origin_required')
    origin=first['monotonic_ns'];total=0
    for index in range(301):
        target=origin+index*1000000000
        if index:
            remaining=target-monotonic_ns()
            if remaining>0:sleep(remaining/1000000000)
            require(target<=monotonic_ns()<=target+500000000,'native_observation_deadline_missed')
            row=observe()
        else:row=first
        require(isinstance(row,dict) and type(row.get('sequence')) is int and row['sequence']==index,'native_observation_sequence_mismatch')
        raw=(json.dumps(row,separators=(',',':'),allow_nan=False)+'\n').encode()
        total+=len(raw);require(total<=256*1024,'native_coverage_size_limit')
        append(raw)
    return {'samples':301,'bytes':total,'deadline_monotonic_ns':origin+300000000000}


def verify_bundle(manifest, root):
    """Verify a separate zero-model native interval; never admit an API result."""
    fields={'schema_version','protocol',*IDENTITY,'window','normalization','artifacts','baseline_sha256','scenario_fingerprint',
            'experience_table_sha256'}
    require(isinstance(manifest,dict) and set(manifest)==fields and manifest['schema_version']==1
            and type(manifest['schema_version']) is int and manifest['protocol']==PROTOCOL,'unsupported_manifest')
    arts=manifest['artifacts'];identity={k:manifest[k] for k in IDENTITY}
    expected={'xp_ledger','native_save','native_log','initial_db','final_db','session','scenario','controller_result',
              'baseline_sql','baseline_snapshot','reset','server_log','coverage','native_result','native_program'}
    require(isinstance(arts,dict) and set(arts)==expected,'incomplete_artifact_bundle')
    for name,field in (('baseline_sql','baseline_sha256'),('scenario','scenario_fingerprint')):
        require(arts[name].get('sha256')==manifest[field],'frozen_artifact_hash_mismatch')
        read_artifact_bytes(root,arts[name],name,maximum=64*1024*1024)
    baseline=read_json_artifact(root,arts,'baseline_snapshot');reset=read_json_artifact(root,arts,'reset')
    initial=read_json_artifact(root,arts,'initial_db');final=read_json_artifact(root,arts,'final_db')
    session=read_json_artifact(root,arts,'session');scenario=read_json_artifact(root,arts,'scenario')
    controller=read_json_artifact(root,arts,'controller_result')
    for row in (initial,final):
        require(row.get('schema_version')==1 and type(row['schema_version']) is int
                and row.get('source')=='cosmic_persisted_character' and row.get('run_id')==identity['run_id']
                and row.get('account_logged_in')==0 and type(row['account_logged_in']) is int
                and all(type(row.get('character',{}).get(k)) is int and row['character'][k]==identity[k]
                        for k in ('character_id','account_id'))
                and integer(row.get('captured_at_ms')),'invalid_offline_snapshot')
    require(same_json(initial.get('keymap'),final.get('keymap'))
            and same_json(initial.get('keymap'),baseline.get('keymap'))
            and same_json(initial['character'],baseline.get('character')),'persisted_baseline_or_keymap_changed')
    require(reset.get('run_id')==identity['run_id'] and reset.get('baseline_sha256')==manifest['baseline_sha256']
            and all(reset.get(k) is True for k in ('world_lock_held','queue_lock_held','server_stopped','verified'))
            and integer(reset.get('completed_at_ms')) and reset['completed_at_ms']<=initial['captured_at_ms'],
            'fresh_verified_reset_required')
    require(session.get('run_id')==identity['run_id'] and session.get('server_instance_id')==identity['server_instance_id']
            and session.get('disconnect_kind')=='normal' and session.get('world_lock_held_throughout') is True
            and session.get('queue_lock_held_throughout') is True,'ordinary_owned_session_required')
    window=manifest['window']
    require(same_json(scenario.get('xp_window_protocol'),{'id':WINDOW_PROTOCOL,'window_ms':WINDOW_MS,'wall_seconds':300,
            'normalization':manifest['normalization'],'experience_table_sha256':manifest['experience_table_sha256']}),
            'unfrozen_native_window')
    validate_contract(scenario['xp_window_protocol'])
    actual=read_json_artifact(root,arts,'native_result')
    program_raw=read_artifact_bytes(root,arts['native_program'],'native_program',maximum=65536)
    controller=verify_control(controller,scenario,identity,window,manifest['baseline_sha256'],actual,program_raw)
    coverage=read_artifact_bytes(root,arts['coverage'],'coverage',maximum=256*1024)
    verify_coverage(coverage,identity,window,control=controller)
    require(session.get('controller_started_at_ms')==window['start_at_ms']
            and session.get('controller_ended_at_ms')==window['deadline_at_ms'], 'native_session_timing_mismatch')
    save=session.get('save',{});committed=save.get('committed_at_ms')
    require(save.get('status')=='confirmed' and save.get('run_id')==identity['run_id']
            and save.get('server_instance_id')==identity['server_instance_id'] and save.get('character_id')==identity['character_id']
            and integer(committed) and initial['captured_at_ms']<=session['server_started_at_ms']<=session['login_at_ms']
            <=window['start_at_ms']<window['deadline_at_ms']<=session['controller_ended_at_ms']
            <=session['disconnect_requested_at_ms']<=committed<=session['logged_out_at_ms']<=final['captured_at_ms'],
            'invalid_native_logout_envelope')
    require(arts['native_save']['sha256']==save.get('evidence_sha256')
            and arts['native_log']['sha256']==save.get('native_logs_sha256')
            and arts['server_log']['sha256']==save.get('logs_sha256'),'save_artifact_binding_mismatch')
    require(integer(save.get('log_checked_from_ms')) and save['log_checked_from_ms']<=session['server_started_at_ms']
            and integer(save.get('log_checked_through_ms')) and save['log_checked_through_ms']>=final['captured_at_ms']
            and type(save.get('save_error_count')) is int and save['save_error_count']==0,'incomplete_native_log_review')
    events=[parse_json(line) for line in read_artifact_bytes(root,arts['server_log'],'server_log').splitlines()]
    require(events and all(row.get('run_id')==identity['run_id'] and row.get('server_instance_id')==identity['server_instance_id']
            and integer(row.get('at_ms')) and row.get('event') not in ('save_error','save_failed','server_failed') for row in events)
            and [row['at_ms'] for row in events]==sorted(row['at_ms'] for row in events),'invalid_phase_journal')
    for event,at in (('server_started',session['server_started_at_ms']),('login',session['login_at_ms']),
                     ('logged_out',session['logged_out_at_ms']),('collection_completed',final['captured_at_ms'])):
        matching=[row for row in events if row.get('event')==event]
        require(len(matching)==1 and matching[0]['at_ms']==at,'missing_or_ambiguous_phase_receipt')
    logs=read_artifact_bytes(root,arts['native_log'],'native_log')
    require(logs.count(b'MapleBench persistence journal initialized')==1 and logs.count(b'MapleBench XP ledger initialized')==1
            and all(v not in logs for v in (b'MapleBench XP ledger failed',b'MapleBench persistence journal failed',b'Error saving chr')),
            'native_journal_initialization_or_failure')
    saves=[parse_json(line) for line in read_artifact_bytes(root,arts['native_save'],'native_save').splitlines()]
    save_fields={'schema_version','source','kind',*IDENTITY,'committed_at_ms'}
    require(saves and all(set(row)==save_fields and type(row['schema_version']) is int and row['schema_version']==1
            and row.get('source')=='cosmic_persisted_character' and row.get('kind')=='save_committed'
            and integer(row.get('committed_at_ms'))
            and session['server_started_at_ms']<=row['committed_at_ms']<=final['captured_at_ms']
            and all(type(row.get(k)) is type(v) and row[k]==v for k,v in identity.items()) for row in saves)
            and [row['committed_at_ms'] for row in saves]==sorted(row['committed_at_ms'] for row in saves)
            and sum(row.get('committed_at_ms')==committed for row in saves)==1,'native_commit_missing_or_ambiguous')
    raw=read_artifact_bytes(root,arts['xp_ledger'],'xp_ledger',maximum=MAX_LEDGER_BYTES)
    score=score_ledger(raw,identity=identity,initial={k:initial['character'][k] for k in ('level','exp')},
        final={k:final['character'][k] for k in ('level','exp')},window=window,
        normalization=manifest['normalization'],committed_at_ms=committed)
    header=parse_json(raw.splitlines()[0])
    require(initial['captured_at_ms']<=header['wall_ms']<=session['login_at_ms'],'native_header_outside_new_session')
    require(score['experience_table_sha256']==manifest['experience_table_sha256'],'unfrozen_native_experience_table')
    positive=sum(row.get('kind')=='xp_transaction' and row.get('delta_xp',0)>0
                 and window['start_at_ms']<=row['wall_ms']<window['deadline_at_ms']
                 for row in (parse_json(line) for line in raw.splitlines()))
    return {'schema_version':1,'protocol':PROTOCOL,**identity,'api_calls':0,'model':None,
            'status':'native_xp_hook_verified' if positive else 'insufficient_positive_native_transaction',
            'native_hook_accepted':positive>0,'positive_transactions':positive,
            'diagnostic_windows':score,'artifacts_verified':True,'baseline_reset_verified':True,
            'publication_eligible':False,'visual_acceptance_required':True,
            'scenario_fingerprint':manifest['scenario_fingerprint'],'baseline_sha256':manifest['baseline_sha256']}
