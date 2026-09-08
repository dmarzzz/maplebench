"""Public projection of a complete adaptive pilot's native and cycle evidence.

No provider calls or deployment. This deliberately does not accept a legacy
single-call score as an aggregate result or derive a peak rate from net XP.
"""
import re
import os
from pathlib import Path

from full_client_dashboard import Reader, integer, mapping, model, number, project_attempt
from full_client_gallery import copy_recording, directory
from full_client_publication import (ADAPTIVE_PROTOCOL, MAX_ADAPTIVE_VIDEO, digest,
    encoded, require, missing_row)
from full_client_research import CLASSES, TASKS
from full_client_score import same_json, verify_trial_bundle, read_json_artifact

VERIFIED = 'adaptive_runner_verified_receipts_rechecked'


def checked_profile(plan, scenario_path, public_profile):
    from full_client_adaptive import validate_protocol
    fixture=plan['fixtures'][0];path=Path(scenario_path)
    scenario=Reader().json(directory(path.parent),path.name,fixture['scenario']['sha256'])
    require(scenario.get('protocol')==ADAPTIVE_PROTOCOL,'adaptive_scenario_required')
    protocol=validate_protocol(scenario.get('adaptive_protocol'))
    require(all(entry['spec'].get('schema_version')==2 and entry['spec'].get('protocol')==ADAPTIVE_PROTOCOL
                for entry in plan['entries']),'adaptive_specs_required')
    require(same_json(scenario.get('trial_budgets'),fixture['budgets']),'adaptive_fixture_budget_mismatch')
    profile=public_profile
    require(isinstance(profile,dict) and set(profile)=={'protocol_id','class_id','task_id'}
            and profile['protocol_id']==ADAPTIVE_PROTOCOL and profile['class_id'] in CLASSES
            and profile['class_id']!='undeclared' and profile['task_id'] in TASKS,
            'explicit_adaptive_public_profile_required')
    class_names={'hero':'Hero','bowmaster':'Bowmaster','ice_lightning_arch_mage':'Ice/Lightning Arch Mage',
                 'shadower':'Shadower','bishop':'Bishop'}
    require(protocol['profile']['class_name']==class_names[profile['class_id']],
            'adaptive_public_class_mismatch')
    return profile,scenario


def verified_adaptive_score(reader,folder,journal):
    from full_client_adaptive_evidence import verify_result
    from full_client_publish import _verify_docker_execution, _verify_readiness_policy
    spec=journal['request'];ident=journal['attempt_id'];requested=model(spec.get('model'))
    require(spec.get('schema_version')==2 and spec.get('protocol')==ADAPTIVE_PROTOCOL and requested
            and journal.get('status')=='completed'
            and any(mapping(event).get('kind')=='evidence_verified' for event in journal.get('events',[])),
            'adaptive_runner_verification_pending')
    refs=mapping(mapping(mapping(journal.get('receipts')).get('collect_final')).get('artifacts'))
    evidence=reader.artifact(folder,refs,'persistence');result=read_json_artifact(folder,refs,'result')
    scenario=reader.artifact(folder,refs,'scenario');controller=mapping(result.get('controller'))
    score=verify_trial_bundle(evidence,folder,refs)
    context={'scenario_fingerprint':spec['scenario_fingerprint'],'baseline_sha256':spec['baseline_sha256']}
    require(score.get('schema_version')==2 and score.get('protocol')==ADAPTIVE_PROTOCOL
            and score.get('run_id')==ident and same_json(score,reader.artifact(folder,refs,'score'))
            and same_json(score,journal.get('score')) and score.get('authoritative_peak_xp_per_minute') is None
            and score.get('scenario_fingerprint')==spec['scenario_fingerprint']
            and score.get('baseline_sha256')==spec['baseline_sha256']
            and score.get('level')==scenario['adaptive_protocol']['profile']['level']
            and refs['scenario']['sha256']==spec['scenario_fingerprint']
            and refs['baseline']['sha256']==spec['baseline_sha256']
            and controller.get('id')==ident and controller.get('model')==requested
            and controller.get('mode')=='api' and controller.get('status')=='completed'
            and same_json(result.get('trialContext'),context) and same_json(controller.get('trialContext'),context)
            and re.fullmatch('sha256:[a-f0-9]{64}',str(controller.get('dockerImageId',''))),
            'adaptive_runner_receipts_inconsistent')
    checked=verify_result(result,folder,protocol=scenario['adaptive_protocol'],model=requested)
    _verify_docker_execution({'result':result,'artifacts':refs},folder)
    _verify_readiness_policy({'result':result,'artifacts':refs,'budgets':scenario.get('budgets'),
                              'timeline':result['timeline']},folder,evidence,scenario)
    group=digest(encoded({'protocol':ADAPTIVE_PROTOCOL,'scenario':spec['scenario_fingerprint'],
        'baseline':spec['baseline_sha256'],'budgets':spec['budgets'],
        'runtime':refs['runtime_manifest']['sha256'],'docker_image':controller['dockerImageId']}))
    return score,result,group,refs,checked


def public_cycles(result,checked):
    trace=result['adaptive'];cycles=[]
    allowed_status={'executed','invalid_program','budget_rejected','window_closed','response_saved','not_executed','completed'}
    allowed_reason={'completed','program_complete','program_error','program_timeout','output_limit',
                    'time_limit','action_limit','rpc_limit','death'}
    for cycle in trace['cycles']:
        execution=mapping(cycle.get('execution'))
        reason=execution.get('reason')
        row={'index':cycle['index'],'requested_model':model(cycle.get('requested_model')),
             'returned_model':model(cycle.get('returned_model')),
             'status':cycle.get('status') if cycle.get('status') in allowed_status else 'details_unavailable',
             'api_outcome':cycle.get('api_outcome') if cycle.get('api_outcome') in ('confirmed','not_started') else 'unknown',
             'timing':{k:v for k,v in mapping(cycle.get('timing')).items()
                       if k in ('observed_ms','window_closed_ms','api_started_ms','api_ended_ms','program_started_ms','program_ended_ms')
                       and integer(v,305000) is not None},
             'usage':{k:v for k,v in mapping(cycle.get('usage')).items()
                      if k in ('input_tokens','output_tokens','total_tokens') and integer(v,240000) is not None},
             'actions':integer(execution.get('actions'),2400),
             'action_attempts':integer(execution.get('actionAttempts'),2400),
             'sdk_requests':integer(execution.get('rpcRequests'),10000),
             'execution_reason':reason if reason in allowed_reason else None,
             'artifact_sha256':{k:v['sha256'] for k in ('request','response','program','choice','execution_receipt')
                                if isinstance((v:=cycle.get(k)),dict)}}
        character=mapping(mapping(cycle.get('observation')).get('character'))
        row['diagnostic_observation']={k:v for k,v in character.items()
            if (k in ('x','y','hp','maxHp','mp','maxMp','exp','level') and number(v,-2**31,2**53-1))
                or (k=='alive' and type(v) is bool)}
        cycles.append(row)
    public={'verification':'all_cycle_receipts_rechecked','cycles':cycles,
        'counters':checked['counters'],'wall_budget_ms':300000,'wall_elapsed_ms':checked['wall_elapsed_ms'],
        'api_ms':checked['api_ms'],'end_reason':trace['reason'],
        'full_wall_budget_used':checked['wall_elapsed_ms']==300000,
        'authoritative_peak_xp_per_minute':None,'ranked':False,
        'class_profile':{k:trace['limits']['profile'][k] for k in ('id','class_name','level','skill_keys')}}
    if trace['limits'].get('horizon_policy'):
        public['horizon_policy']=trace['limits']['horizon_policy']
        wait=trace.get('horizon_wait')
        public['horizon_wait']=None if wait is None else {
            'reason':wait['reason'],'started_ms':wait['started_ms'],'ended_ms':wait['ended_ms'],
            'observation_count':len(wait['samples'])}
    return public


def playback_cue(result,recording,actions):
    if not actions:return None
    timeline=result['timeline'];start=recording.get('start_ms');end=recording.get('end_ms')
    duration=recording.get('duration_ms');uncertainty=recording.get('timing_uncertainty_ms')
    begin=timeline.get('program_started_ms');finish=timeline.get('program_ended_ms')
    target=timeline.get('first_input_started_ms');ack=timeline.get('first_input_acked_ms')
    if (recording.get('timing_method')!='browser_monotonic_duration_with_measured_clock_offset'
            or not number(start,-335000,335000) or not number(end,0,670000)
            or not number(duration,1,335000) or not number(uncertainty,0,100)
            or not number(begin,0,335000) or not number(finish,begin,335000)
            or not start<=begin<finish<=end or abs(end-start-duration)>100
            or not number(target,begin,finish) or not number(ack,target,finish)):
        return None
    origin=0
    if recording.get('capture_duration_policy',{}).get('id')=='post-render-encoded-frame-v1':
        origin=recording.get('first_frame_offset_ms')
        if not number(origin,0,duration):return None
    offset=target-start-origin
    return {'start_ms':round(max(0,offset-250)),'basis':'first_acknowledged_input',
            'timing_uncertainty_ms':uncertainty} if 0<=offset<duration-origin else None


def project_member(entry,fixture,attempt_root,recordings,scenario):
    ident=entry['attempt_id'];folder=attempt_root/ident
    if not os.path.lexists(folder):return missing_row(entry)
    row=missing_row(entry)
    try:
        directory(folder);reader=Reader();journal=reader.json(folder,'journal.json')
        require(journal.get('attempt_id')==ident and same_json(journal.get('request'),entry['spec'])
                and journal.get('adapter_fingerprint')==fixture['adapter_fingerprint'],'cohort_request_mismatch')
        stamps=[event.get('at_ms') for event in journal.get('events',[]) if isinstance(event,dict)]
        stamp=max([v for v in stamps if integer(v) is not None],default=0)
        row=project_attempt(reader,ident,folder,None,{},None,stamp,'/recordings/')
        row.update(protocol_id=ADAPTIVE_PROTOCOL,mode='api',returned_model=None,attribution='pending',
                   api_usage={},persisted_xp=None,comparison_group=None,score_verification='unverified',
                   recording_publication='not_ready',publication_evidence=None,recording=None,
                   adaptive={'verification':'unverified','cycles':[],'authoritative_peak_xp_per_minute':None})
        if journal.get('status')!='completed':return row
        score,result,group,refs,checked=verified_adaptive_score(Reader(),folder,journal)
        require(refs['runtime_manifest']['sha256']==fixture['runtime_manifest']['sha256']
                and same_json(result['adaptive']['limits'],scenario['adaptive_protocol']),
                'adaptive_fixture_mismatch')
        counters=checked['counters']
        row.update(status='completed',persisted_xp=score['metrics']['net_xp'],alive_at_logout=score['alive_at_logout'],
            score_verification=VERIFIED,comparison_group=group,returned_model=entry['model'],attribution='exact',
            api_usage={k:counters['actual_'+k] for k in ('input_tokens','output_tokens','total_tokens')},
            api_response_saved=True,actions=counters['actions'],acknowledged_actions=counters['actions'],
            action_attempts=counters['action_attempts'],sdk_calls=counters['sdk_requests'],
            action_verification='receipts_rechecked',no_op=counters['actions']==0,
            adaptive=public_cycles(result,checked),timing=score['timing']|{'wall_ms':checked['wall_elapsed_ms']},
            publication_evidence={'status':'aggregate_checked','reason_code':None})
        if number(result.get('observedXpDelta'),-2**53+1):row['diagnostic_xp']=result['observedXpDelta']
        try:
            from full_client_publish import _probe_video, verify_capture_bundle
            recording=reader.artifact(folder,refs,'recording');video=refs['video']
            require(recording.get('status')=='completed' and recording.get('interrupted') is False
                    and recording.get('post_render_capture') is True and recording.get('sha256')==video.get('sha256')
                    and recording.get('overlay')=={'controller_id':ident,'mode':'api','model':entry['model']}
                    and Path(video['path']).suffix=='.webm','adaptive_recording_receipt_inconsistent')
            verify_capture_bundle({'result':result,'artifacts':refs,'video':recording},folder)
            target=recordings/(ident+'.webm')
            copy_recording(folder,video,target,{},maximum=MAX_ADAPTIVE_VIDEO)
            measured=_probe_video(target,video['sha256'],maximum_ms=335000)
            from full_client_capture import verify_video_duration
            verify_video_duration(measured,recording,scenario['adaptive_protocol'].get('capture_duration_policy'))
            row['recording']={'url':'./recordings/'+ident+'.webm','sha256':video['sha256'],
                              'reviewed':recording.get('reviewed') is True}
            cue=playback_cue(result,recording,counters['actions'])
            if cue is not None:row['recording']['playback']=cue
            row['recording_publication']='verified_bytes'
            row['publication_evidence']={'status':'adaptive_checked','reason_code':None}
        except (ValueError,OSError,TypeError,KeyError,RecursionError):
            (recordings/(ident+'.webm')).unlink(missing_ok=True)
            row['recording']=None;row['recording_publication']='unavailable'
        require(same_json(Reader().json(folder,'journal.json'),journal),'publication_evidence_changed')
        return row
    except (ValueError,OSError,TypeError,KeyError,RecursionError):
        (recordings/(ident+'.webm')).unlink(missing_ok=True)
        row.update(status='unavailable',failure_code='adaptive_evidence_unavailable',persisted_xp=None,
                   score_verification='unverified',comparison_group=None,recording=None,
                   action_verification='unverified',no_op=None,recording_publication='unavailable',
                   publication_evidence=None,returned_model=None,attribution='pending',
                   adaptive={'verification':'unverified','cycles':[],'authoritative_peak_xp_per_minute':None})
        return row
