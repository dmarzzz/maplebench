"""Native XP ledger verification and fixed-window progression scoring.

This is a separate future evidence protocol. It never upgrades historical
initial/final XP or treats absent ledger coverage as a zero score.
"""
from __future__ import annotations
import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re

from full_client_score import EvidenceError, parse_json, read_artifact_bytes, read_json_artifact, same_json

PROTOCOL='full-client-xp-windows-v1'
SOURCE='cosmic_native_xp_ledger'
WINDOW_MS=15000
MAX_LEDGER_BYTES=64*1024*1024
IDENTITY=('run_id','server_instance_id','character_id','account_id')


def require(value, code):
    if not value:raise EvidenceError('xp_windows: '+code)


def integer(value, low=0, high=2**53-1):
    return type(value) is int and low<=value<=high


def multiplier(value):
    require(isinstance(value,dict) and set(value)=={'numerator','denominator'}
            and all(integer(value[k],1,1000000) for k in value),'invalid_multiplier')
    return Fraction(value['numerator'],value['denominator'])


def score_ledger(raw, *, identity, initial, final, window, normalization, committed_at_ms):
    require(isinstance(raw,bytes) and 0<len(raw)<=MAX_LEDGER_BYTES and raw.endswith(b'\n'),'missing_or_truncated_ledger')
    require(integer(committed_at_ms),'invalid_commit_time')
    require(set(identity)==set(IDENTITY) and all(isinstance(identity[k],str) and re.fullmatch('[a-f0-9]{32}',identity[k])
            for k in ('run_id','server_instance_id')) and all(integer(identity[k],1,2**31-1)
            for k in ('character_id','account_id')),'invalid_identity')
    require(isinstance(window,dict) and set(window)=={'start_at_ms','deadline_at_ms','window_ms'}
            and window['window_ms']==WINDOW_MS and integer(window['window_ms'])
            and all(integer(window[k]) for k in ('start_at_ms','deadline_at_ms'))
            and WINDOW_MS<=window['deadline_at_ms']-window['start_at_ms']<=1800000,'invalid_window_contract')
    require(set(normalization)=={'server_xp_multiplier','simulation_speed_multiplier'},'invalid_normalization')
    server=multiplier(normalization['server_xp_multiplier']);simulation=multiplier(normalization['simulation_speed_multiplier'])
    rows=[];previous='0'*64;last_wall=0;last_ns=0
    common={'schema_version','source','kind',*IDENTITY,'sequence','wall_ms','elapsed_ns','previous_sha256'}
    for index,line in enumerate(raw.splitlines(keepends=True)):
        require(index<100000 and len(line)<=65536,'ledger_limit')
        row=parse_json(line)
        require(isinstance(row,dict) and all(type(row.get(k)) is type(v) and row[k]==v for k,v in identity.items())
                and row.get('schema_version')==1 and type(row['schema_version']) is int
                and row.get('source')==SOURCE and type(row.get('sequence')) is int and row['sequence']==index
                and row.get('previous_sha256')==previous,'ledger_chain_or_identity_mismatch')
        require(integer(row.get('wall_ms')) and integer(row.get('elapsed_ns'))
                and row['wall_ms']>=last_wall and row['elapsed_ns']>=last_ns,'unordered_native_clock')
        if index==0:
            expected=common|{'level','exp','thresholds','server_xp_multiplier','simulation_speed_multiplier'}
            require(row.get('kind')=='header' and row['elapsed_ns']==0,'missing_native_header')
        elif row.get('kind')=='xp_transaction':
            expected=common|{'cause','before_level','before_exp','after_level','after_exp','delta_xp','world_exp_rate'}
        else:
            expected=common|{'level','exp','world_exp_rate'}
            require(row.get('kind')=='save_committed','unknown_native_event')
        require(set(row)==expected,'invalid_native_event_fields')
        if rows:
            require(abs(row['wall_ms']-rows[0]['wall_ms']-row['elapsed_ns']//1000000)<=25,'native_clock_discontinuity')
        rows.append(row);previous=hashlib.sha256(line).hexdigest();last_wall=row['wall_ms'];last_ns=row['elapsed_ns']
    header=rows[0];thresholds=header['thresholds']
    require(isinstance(thresholds,list) and len(thresholds)==199 and all(integer(n,1,2**31-1) for n in thresholds),
            'invalid_native_experience_table')
    require(same_json({k:header[k] for k in normalization},normalization),'native_multiplier_mismatch')
    def progression(state):
        require(isinstance(state,dict) and set(state)=={'level','exp'} and integer(state['level'],1,200)
                and integer(state['exp'],0,2**31-1)
                and (state['exp']==0 if state['level']==200 else state['exp']<thresholds[state['level']-1]),
                'invalid_progression_state')
        return sum(thresholds[:state['level']-1])+state['exp']
    initial_total=progression(initial);final_total=progression(final)
    state={k:header[k] for k in ('level','exp')}
    require(same_json(state,initial) and header['wall_ms']<=window['start_at_ms'],'native_baseline_mismatch')
    changes=[]
    for row in rows[1:]:
        require(integer(row.get('world_exp_rate'),1,1000000) and Fraction(row['world_exp_rate'])==server,
                'native_server_rate_changed')
        if row['kind']=='xp_transaction':
            require(row['cause']=='xp_transaction','unsupported_direct_progression_mutation')
            before={'level':row['before_level'],'exp':row['before_exp']}
            after={'level':row['after_level'],'exp':row['after_exp']}
            require(same_json(before,state),'unobserved_progression_change')
            require(integer(after['level'],before['level'],200),'unsupported_level_decrease')
            delta=progression(after)-progression(before)
            require(integer(row['delta_xp'],-2**53+1) and row['delta_xp']==delta,'native_delta_mismatch')
            state=after;changes.append((row['wall_ms'],delta))
        else:
            require(same_json({k:row[k] for k in state},state),'native_save_state_mismatch')
    require(rows[-1]['kind']=='save_committed' and rows[-1]['wall_ms']==committed_at_ms
            and committed_at_ms>=window['deadline_at_ms'] and same_json(state,final),'missing_terminal_save_coverage')
    require(sum(delta for _,delta in changes)==final_total-initial_total,'persisted_progression_reconciliation_failed')
    start,end=window['start_at_ms'],window['deadline_at_ms'];count=(end-start)//WINDOW_MS
    deltas=[0]*count
    for at,delta in changes:
        if start<=at<start+count*WINDOW_MS:deltas[(at-start)//WINDOW_MS]+=delta
    result=[];peak=Fraction(0)
    for index,delta in enumerate(deltas):
        rate=Fraction(delta*60000,WINDOW_MS)/server/simulation
        peak=max(peak,rate)
        result.append({'index':index,'start_at_ms':start+index*WINDOW_MS,'end_at_ms':start+(index+1)*WINDOW_MS,
                       'net_xp':delta,'normalized_xp_per_minute':float(rate),'best_so_far':float(peak)})
    return {'schema_version':1,'protocol':PROTOCOL,'source':SOURCE,**identity,
        'complete_windows':count,'incomplete_tail_ms':(end-start)%WINDOW_MS,'windows':result,
        'peak_normalized_xp_per_minute':float(peak),'task_score':float(peak),
        'persisted_net_xp':final_total-initial_total,
        'control_window_net_xp':sum(delta for at,delta in changes if start<=at<end),
        'ledger_sha256':hashlib.sha256(raw).hexdigest(),
        'experience_table_sha256':hashlib.sha256(json.dumps(thresholds,separators=(',',':')).encode()).hexdigest(),
        'normalization':normalization,'publication_eligible':False}


def verify_bundle(manifest, root):
    """Check native bytes and a full 300-second adaptive control interval.

    Longer controller protocols need their own accepted adapter. Arithmetic above
    supports their windows; this entry point will not assume such runs occurred.
    """
    fields={'schema_version','protocol',*IDENTITY,'window','normalization','artifacts','baseline_sha256','scenario_fingerprint',
            'experience_table_sha256'}
    require(isinstance(manifest,dict) and set(manifest)==fields and manifest['schema_version']==1
            and type(manifest['schema_version']) is int and manifest['protocol']==PROTOCOL,'unsupported_manifest')
    arts=manifest['artifacts'];identity={k:manifest[k] for k in IDENTITY}
    expected={'xp_ledger','native_save','native_log','initial_db','final_db','session','scenario','controller_result',
              'baseline_sql','baseline_snapshot','reset','server_log'}
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
    from full_client_adaptive_evidence import verify_result
    from full_client_adaptive import PROTOCOL as ADAPTIVE
    require(scenario.get('protocol')==controller.get('protocol')==ADAPTIVE,'unsupported_controller_protocol')
    require(all(controller.get('initial',{}).get('character',{}).get(k)==initial['character'].get(k)
                for k in ('level','exp')),'controller_baseline_mismatch')
    verified=verify_result(controller,root,protocol=scenario['adaptive_protocol'],model=controller['controller']['model'])
    t=controller['adaptive']['timing'];window=manifest['window']
    require(verified['wall_elapsed_ms']==300000 and controller['controller']['id']==identity['run_id']
            and same_json(window,{'start_at_ms':t['wall_started_at_ms'],'deadline_at_ms':t['wall_deadline_at_ms'],'window_ms':WINDOW_MS})
            and same_json(scenario.get('xp_window_protocol'),{'id':PROTOCOL,'window_ms':WINDOW_MS,'wall_seconds':300,
                'normalization':manifest['normalization'],'experience_table_sha256':manifest['experience_table_sha256']}),
            'unfrozen_or_incomplete_control_window')
    require(session.get('controller_started_at_ms')==window['start_at_ms']
            and session.get('controller_ended_at_ms')==controller['timing']['startedAtMs']+controller['timeline']['program_ended_ms'],
            'controller_session_timing_mismatch')
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
    return score|{'artifacts_verified':True,'baseline_reset_verified':True,
        'publication_blocker':'new_native_runtime_and_baseline_acceptance_required'}


def aggregate_task_scores(scores):
    require(isinstance(scores,list) and scores and all(type(n) in (int,float) and math.isfinite(n) and n>=0 for n in scores),
            'missing_or_invalid_task_score')
    return sum(math.log1p(n) for n in scores)/len(scores)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('manifest',type=Path);parser.add_argument('--artifact-root',type=Path,required=True)
    args=parser.parse_args()
    try:
        require(args.manifest.stat().st_size<=1024*1024,'manifest_limit')
        result=verify_bundle(parse_json(args.manifest.read_bytes()),args.artifact_root)
    except (EvidenceError,OSError,KeyError,TypeError,ValueError):
        print(json.dumps({'scored':False,'protocol':PROTOCOL,'score':None,'reason':'missing_or_inconsistent_native_window_evidence'}));return 1
    print(json.dumps({'scored':True,'score':result},allow_nan=False));return 0

if __name__=='__main__':raise SystemExit(main())
