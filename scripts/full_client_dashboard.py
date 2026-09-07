#!/usr/bin/env python3
"""Bounded read-only projection of private full-client attempts.

build_snapshot(attempt_root, relay_root=None, live_status=None,
               recording_map=None, limit=50) returns public-safe JSON only.
The completed runner is trusted to have performed full bundle verification;
this exporter rechecks its small hashed receipts and recomputes persisted XP.
Input attempts and accepted acknowledgments are separate. Legacy results count
attempts in program.actions; current results also preserve actionAttempts.
Only complete checked execution receipts support a no_op boolean. Persisted XP
and publication status remain independent of incomplete input receipts.
It never repeats baseline/video hashing, invokes a controller, grants ranked
eligibility, or copies recordings. Expose only the exported JSON and new static
ui/full-client-dashboard assets, never either private input directory.

CLI --output replaces one snapshot atomically (0600; --public-output uses 0644).
Only explicit --watch-seconds repeats exports for a finite window. It never
starts a service. --admin-socket can read private status and has no write op.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import socket
import stat
import struct
import tempfile
import time
from urllib.parse import urlsplit

from full_client_score import parse_json, score_trial, same_json
from full_client_trial import PHASES, RUNTIME_ERROR_CODES
from maple_agent import MODELS, validate_rpc

RUN=re.compile(r'[a-f0-9]{32}\Z')
SHA=re.compile(r'[a-f0-9]{64}\Z')
PUBLICATION_VERDICT=re.compile(r'publication-verdict-([a-f0-9]{7,40})\.json\Z')
ACTION_COUNT_REASON='result.program.actions: count must match the complete input receipt list.'
MAX_VERDICTS=16
MAX_FILE=4*1024*1024
MAX_READ=64*1024*1024
STATUSES={'running','completed','failed','interrupted','recovering','recovered'}
BRIDGE_STATUSES={'idle','requesting','running','completed','failed'}
PHASE_NAMES=set(PHASES)|{'created','status'}
FAILURES=RUNTIME_ERROR_CODES|frozenset('adapter_failed operation_failed trial_timeout operation_timeout model_mismatch controller_incomplete evidence_baseline_mismatch evidence_attempt_mismatch cleanup_unconfirmed runtime_not_idle run_cancelled recorder_not_ready client_state_stale api_model_mismatch api_invalid_program api_token_budget_too_small input_interrupted program_error process_restarted invalid_controller_evidence corrupt_runs_require_acknowledgment'.split())


class ProjectionError(ValueError): pass


def number(value,minimum=0,maximum=2**53-1):
    return type(value) in (int,float) and minimum<=value<=maximum and math.isfinite(value)


def integer(value,maximum=2**53-1):
    return value if type(value) is int and 0<=value<=maximum else None


def model(value): return value if isinstance(value,str) and value in MODELS else None
def mapping(value): return value if isinstance(value,dict) else {}
def digest(value): return value if isinstance(value,str) and SHA.fullmatch(value) else None
def failure(value): return value if isinstance(value,str) and value in FAILURES else 'details_unavailable'


class Reader:
    def __init__(self): self.remaining=MAX_READ

    def json(self,root,name,expected=None,maximum=MAX_FILE):
        if not isinstance(name,str) or '\\' in name or '\x00' in name:
            raise ProjectionError('invalid_artifact_reference')
        relative=PurePosixPath(name)
        if relative.is_absolute() or not relative.parts or any(part in ('.','..') for part in relative.parts):
            raise ProjectionError('invalid_artifact_reference')
        target=root
        for part in relative.parts:
            target=target/part
            if target.is_symlink(): raise ProjectionError('symlink_evidence')
        with os.fdopen(os.open(target,os.O_RDONLY|os.O_NOFOLLOW),'rb') as stream:
            before=os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=min(MAX_FILE,maximum,self.remaining):
                raise ProjectionError('evidence_read_limit')
            raw=stream.read(before.st_size+1)
            after=os.fstat(stream.fileno()); current=target.stat()
        self.remaining-=len(raw)
        fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
        if len(raw)!=before.st_size or any(getattr(before,k)!=getattr(after,k) or getattr(before,k)!=getattr(current,k) for k in fields):
            raise ProjectionError('evidence_changed')
        if expected is not None and (not digest(expected) or hashlib.sha256(raw).hexdigest()!=expected):
            raise ProjectionError('evidence_hash_mismatch')
        value=parse_json(raw)
        if not isinstance(value,dict): raise ProjectionError('invalid_evidence')
        return value

    def optional(self,root,name):
        try: return self.json(root,name)
        except FileNotFoundError: return None

    def artifact(self,root,refs,name):
        reference=mapping(refs.get(name))
        if not digest(reference.get('sha256')): raise ProjectionError('missing_hashed_receipt')
        return self.json(root,reference.get('path'),reference['sha256'])


def directories(root):
    if root is None: return {},False
    root=Path(root)
    if not root.is_absolute() or root.resolve()!=root or not root.is_dir():
        raise ProjectionError('invalid_input_directory')
    found={}; truncated=False
    with os.scandir(root) as entries:
        for index,entry in enumerate(entries):
            if index>=2000:
                truncated=True; break
            if RUN.fullmatch(entry.name) and entry.is_dir(follow_symlinks=False):
                found[entry.name]=(root/entry.name,entry.stat(follow_symlinks=False).st_mtime_ns)
    return found,truncated


def recording_prefix(value):
    if not isinstance(value,str) or not re.fullmatch(r'/(?:[A-Za-z0-9_-]{1,48}/){0,3}recordings/',value):
        raise ProjectionError('invalid_recording_prefix')
    return value


def recording_url(value,prefix='/recordings/'):
    prefix=recording_prefix(prefix)
    if not isinstance(value,str) or len(value)>512 or any(ch in value for ch in ('\\','%','\n','\r')):
        return None
    try:
        parsed=urlsplit(value)
        if parsed.query or parsed.fragment or parsed.username or parsed.password: return None
        if parsed.netloc:
            if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1') or not parsed.port:
                return None
        elif parsed.scheme or not value.startswith('/') or value.startswith('//'): return None
        if (not parsed.path.startswith(prefix) or not parsed.path.endswith(('.webm','.mp4'))
                or '..' in PurePosixPath(parsed.path).parts
                or not re.fullmatch(re.escape(prefix)+r'[A-Za-z0-9_./-]+',parsed.path)):
            return None
        return value
    except ValueError: return None


def verified_score(reader,folder,journal):
    spec=mapping(journal.get('request')); run_id=journal['attempt_id']
    events=journal.get('events')
    if (journal.get('status')!='completed' or not isinstance(events,list)
            or not any(mapping(event).get('kind')=='evidence_verified' for event in events)):
        raise ProjectionError('runner_verification_pending')
    refs=mapping(mapping(mapping(journal.get('receipts')).get('collect_final')).get('artifacts'))
    evidence=reader.artifact(folder,refs,'persistence')
    recomputed=score_trial(evidence)|{'artifacts_verified':True}
    saved=reader.artifact(folder,refs,'score')
    result=reader.artifact(folder,refs,'result')
    request=reader.artifact(folder,refs,'api_request')
    response=reader.artifact(folder,refs,'api_response')
    controller=mapping(result.get('controller')); api=mapping(result.get('api'))
    requested=model(spec.get('model'))
    context={'scenario_fingerprint':spec.get('scenario_fingerprint'),'baseline_sha256':spec.get('baseline_sha256')}
    if (not requested or not same_json(saved,recomputed) or not same_json(journal.get('score'),recomputed)
            or recomputed.get('run_id')!=run_id or result.get('source')!='full-client-trial'
            or controller.get('id')!=run_id or controller.get('status')!='completed' or controller.get('mode')!='api'
            or result.get('trialContext')!=context or controller.get('trialContext')!=context
            or any(item!=requested for item in (controller.get('model'),controller.get('returnedModel'),api.get('model'),request.get('model'),response.get('model')))
            or api.get('status')!='completed' or response.get('status')!='completed'
            or mapping(request.get('metadata')).get('maplebench_run_id')!=run_id
            or mapping(response.get('metadata')).get('maplebench_run_id')!=run_id
            or recomputed.get('scenario_fingerprint')!=digest(spec.get('scenario_fingerprint'))
            or recomputed.get('baseline_sha256')!=digest(spec.get('baseline_sha256'))
            or mapping(refs.get('scenario')).get('sha256')!=spec.get('scenario_fingerprint')
            or mapping(refs.get('baseline')).get('sha256')!=spec.get('baseline_sha256')):
        raise ProjectionError('runner_receipts_inconsistent')
    runtime=digest(mapping(refs.get('runtime_manifest')).get('sha256'))
    budgets=mapping(spec.get('budgets'))
    names=('total_seconds','operation_seconds','controller_seconds','max_actions','max_api_requests','max_output_tokens','max_total_tokens')
    if (not runtime or set(budgets)!=set(names) or any(integer(budgets[k],10000000) is None or budgets[k]<1 for k in names)
            or not re.fullmatch('sha256:[a-f0-9]{64}',str(controller.get('dockerImageId','')))):
        raise ProjectionError('comparison_inputs_unavailable')
    group={'scenario':spec['scenario_fingerprint'],'baseline':spec['baseline_sha256'],
           'budgets':budgets,'runtime':runtime,'docker_image':controller['dockerImageId']}
    group_id=hashlib.sha256(json.dumps(group,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return recomputed,result,group_id,refs


def action_evidence(result,action_limit):
    """Summarize an already hashed, runner-bound result without promoting it.

    Count only accepted bounded pressKeys receipts. A legacy attempted input
    can have no returned receipt; that preserves the accepted subset while
    preventing a complete/no-op claim. Live or relay-only counters never enter
    this function, and no raw SDK arguments/errors are exported.
    """
    value={'actions':None,'acknowledged_actions':None,'action_attempts':None,
           'action_verification':'receipts_incomplete','no_op':None,'sdk_calls':None}
    program=mapping(result.get('program')); controller=mapping(result.get('controller'))
    if integer(action_limit,10000) is None or action_limit<1: return value
    reported=integer(program.get('actions'),action_limit)
    # Historical executor incremented actions before the endpoint response.
    # The distinct actionAttempts field marks the newer acknowledged counter.
    attempts=integer(program.get('actionAttempts'),action_limit) if 'actionAttempts' in program else reported
    value['action_attempts']=attempts
    steps=program.get('steps'); sdk_limit=integer(controller.get('sdkRequestLimit'),10000)
    if not isinstance(steps,list) or sdk_limit is None or not 1<=sdk_limit or len(steps)>sdk_limit:
        return value

    def fresh(observation):
        observation=mapping(observation)
        return (observation.get('ready') is True and observation.get('source')=='full-client'
            and all(number(observation.get(key),0,1499.999) for key in ('ageMs','renderAgeMs')))

    acknowledged=0; presses=0; complete=True
    for index,raw in enumerate(steps):
        step=mapping(raw); method=step.get('method'); receipt=mapping(step.get('result'))
        if method=='pressKeys': presses+=1
        if step.get('kind')!='sdk' or method not in ('observe','wait','pressKeys'):
            complete=False; continue
        try:
            validate_rpc({'type':'rpc','id':index+1,'method':method,'args':step.get('args')},
                         {'adapter':'full-client'})
        except (ValueError,TypeError,KeyError):
            complete=False; continue
        valid=receipt.get('error') in (None,'')
        if method=='pressKeys':
            valid=valid and receipt.get('accepted') is True and fresh(receipt.get('observation'))
            if valid: acknowledged+=1
        elif method=='observe': valid=valid and fresh(receipt)
        else:
            waited=receipt.get('waitedMs'); requested=step['args'][0]
            valid=valid and number(waited,0,requested) and (waited==requested
                or program.get('reason')=='time_limit' and index==len(steps)-1)
        complete=complete and valid
    value.update(actions=acknowledged,acknowledged_actions=acknowledged)
    if attempts is not None and attempts<presses:
        value['action_attempts']=None  # A counter cannot erase receipts already present.
    complete=(complete and program.get('error') is None
        and program.get('reason') in ('program_complete','completed','time_limit','action_limit','death')
        and fresh(result.get('initial')) and fresh(result.get('final'))
        and integer(controller.get('actions'),action_limit)==reported
        and reported is not None and attempts is not None and reported==attempts==presses==acknowledged)
    if complete:
        value.update(action_verification='receipts_rechecked',no_op=attempts==0,sdk_calls=len(steps))
    return value


def playback_cue(result,recording,actions):
    """Map verified controller timing to the original, untrimmed recording.

    Older receipts locate program launch, not its first input. Never invent an
    input timestamp from API latency, a counter, or a no-op result.
    """
    if actions.get('action_verification')!='receipts_rechecked' or not actions.get('actions'):
        return None
    timeline=mapping(result.get('timeline'))
    start=recording.get('start_ms'); end=recording.get('end_ms')
    duration=recording.get('duration_ms'); uncertainty=recording.get('timing_uncertainty_ms')
    program_start=timeline.get('program_started_ms'); program_end=timeline.get('program_ended_ms')
    if (recording.get('interrupted') is not False or recording.get('post_render_capture') is not True
            or recording.get('timing_method')!='browser_monotonic_duration_with_measured_clock_offset'
            or not number(start,-125000,125000) or not number(end,0,250000)
            or not number(duration,1,125000) or not number(uncertainty,0,100)
            or not number(program_start,0,125000) or not number(program_end,program_start,125000)
            or not start<=program_start<program_end<=end
            or abs((end-start)-duration)>100):
        return None
    target=program_start; basis='program_start'
    if 'first_input_started_ms' in timeline or 'first_input_acked_ms' in timeline:
        target=timeline.get('first_input_started_ms'); ack=timeline.get('first_input_acked_ms')
        if not number(target,program_start,program_end) or not number(ack,target,program_end):
            return None
        basis='first_acknowledged_input'
    offset=target-start
    if not 0<=offset<duration: return None
    return {'start_ms':round(max(0,offset-250)), 'basis':basis,
            'timing_uncertainty_ms':uncertainty}


def publication_evidence(reader,folder,run_id,refs,result,score,recording,now_ms):
    """Project a private validator receipt without granting ranked eligibility.

    The trusted validator is not rerun on a dashboard refresh. Its receipt must
    bind the exact reviewed manifest and the runner's existing hashed evidence.
    No private reason text or validator metadata crosses this projection.
    """
    candidates=[]
    with os.scandir(folder) as entries:
        for index,entry in enumerate(entries):
            if index>=256: raise ProjectionError('publication_discovery_limit')
            match=PUBLICATION_VERDICT.fullmatch(entry.name)
            if not match: continue
            if not entry.is_file(follow_symlinks=False) or len(candidates)>=MAX_VERDICTS:
                raise ProjectionError('publication_discovery_limit')
            value=reader.json(folder,entry.name,maximum=64*1024)
            at=integer(value.get('validated_at_ms'))
            verdict=mapping(value.get('verdict')); reasons=verdict.get('reasons')
            if (type(value.get('schema_version')) is not int or value['schema_version']!=1
                    or value.get('run_id')!=run_id or value.get('validator_source_commit')!=match[1]
                    or not digest(value.get('validator_sha256')) or not digest(value.get('reviewed_manifest_sha256'))
                    or at is None or not 0<at<=now_ms or value.get('externally_published') is not False
                    or type(verdict.get('ready')) is not bool or not isinstance(reasons,list)
                    or len(reasons)>32 or any(not isinstance(reason,str) or not 0<len(reason)<=1000 for reason in reasons)
                    or (not reasons)!=verdict['ready']):
                raise ProjectionError('invalid_publication_receipt')
            candidates.append(value)
    if not candidates: return {'status':'awaiting_review','reason_code':None}
    candidates.sort(key=lambda value:value['validated_at_ms'],reverse=True)
    if len(candidates)>1 and candidates[0]['validated_at_ms']==candidates[1]['validated_at_ms']:
        raise ProjectionError('ambiguous_publication_receipt')
    latest=candidates[0]
    reviewed=reader.json(folder,'publication-reviewed.json',latest['reviewed_manifest_sha256'])
    reviewed_refs=mapping(reviewed.get('artifacts')); video=mapping(reviewed.get('video'))
    video_ref=mapping(refs.get('video')); ended=mapping(result.get('timing')).get('endedAtMs')
    if (type(reviewed.get('schema_version')) is not int or reviewed['schema_version']!=2
            or reviewed.get('run_kind')!='ranked'
            or not same_json(reviewed.get('result'),result) or not same_json(reviewed.get('score'),score)
            or not same_json(reviewed.get('timeline'),result.get('timeline'))
            or any(not same_json(reviewed_refs.get(name),reference) for name,reference in refs.items())
            or not number(ended) or latest['validated_at_ms']<ended
            or video.get('reviewed') is not True or not digest(recording.get('sha256'))
            or recording.get('status')!='completed'
            or mapping(recording.get('overlay')).get('controller_id')!=run_id
            or mapping(recording.get('overlay')).get('mode')!='api'
            or mapping(recording.get('overlay')).get('model')!=mapping(result.get('controller')).get('model')
            or video.get('path')!=video_ref.get('path') or video.get('sha256')!=video_ref.get('sha256')
            or not same_json({k:v for k,v in video.items() if k!='reviewed'},
                             {k:v for k,v in recording.items() if k!='reviewed'})):
        raise ProjectionError('publication_manifest_mismatch')
    review=reader.artifact(folder,reviewed_refs,'video_review')
    reviewed_at=integer(review.get('reviewed_at_ms'))
    if (review.get('run_id')!=run_id or review.get('video_sha256')!=recording['sha256']
            or review.get('reviewed') is not True or review.get('post_render_capture') is not True
            or not same_json(review.get('overlay'),recording.get('overlay'))
            or reviewed_at is None or not ended<=reviewed_at<=latest['validated_at_ms']):
        raise ProjectionError('publication_review_mismatch')
    verdict=latest['verdict']
    return {'status':'passed' if verdict['ready'] else 'blocked',
            'reason_code':None if verdict['ready'] else
                          'receipts_incomplete' if verdict['reasons']==[ACTION_COUNT_REASON] else 'details_unavailable'}


def project_attempt(reader,run_id,folder,relay_folder,live,recording_map,now_ms,prefix):
    row={'id':run_id,'kind':'trial' if folder else 'integration','status':'unavailable','phase':None,'mode':'unknown',
         'requested_model':None,'returned_model':None,'attribution':'unknown','failure_code':None,'failure_phase':None,
         'api_outcome':None,'api_response_saved':False,'api_usage':{},'charged_usage':{},
         'created_at_ms':None,'updated_at_ms':None,'actions':None,'action_limit':None,
         'reported_actions':None,'acknowledged_actions':None,'action_attempts':None,
         'action_verification':'unverified','no_op':None,
         'diagnostic_xp':None,'alive_at_last_observation':None,'alive_at_logout':None,
         'persisted_xp':None,'score_verification':'pending','comparison_group':None,
         'ranked':False,'publication_eligible':False,'publication_evidence':None,
         'timing':{},'recording':None,'phase_states':{}}
    journal={}; result={}; controller={}; refs={}; recording={}; score={}
    try:
        if folder:
            journal=reader.json(folder,'journal.json')
            if journal.get('attempt_id')!=run_id: raise ProjectionError('attempt_identity_mismatch')
            spec=mapping(journal.get('request'))
            row.update(status=journal.get('status') if journal.get('status') in STATUSES else 'unavailable',
                phase=journal.get('phase') if journal.get('phase') in PHASE_NAMES else None,
                requested_model=model(spec.get('model')),
                action_limit=integer(mapping(spec.get('budgets')).get('max_actions'),10000))
            if journal.get('failure_code') is not None: row['failure_code']=failure(journal['failure_code'])
            row['api_outcome']=journal.get('api_outcome') if journal.get('api_outcome') in ('not_started','uncertain','confirmed') else None
            row['charged_usage']={key:value for key,value in mapping(journal.get('charged_usage')).items()
                if key in ('api_requests','total_tokens') and integer(value) is not None}
            events=journal.get('events')
            stamps=[mapping(event).get('at_ms') for event in events[:10000]] if isinstance(events,list) else []
            stamps=[value for value in stamps if integer(value) is not None]
            if stamps: row.update(created_at_ms=min(stamps),updated_at_ms=max(stamps))
            for event in events[:10000] if isinstance(events,list) else []:
                event=mapping(event)
                if event.get('operation') in PHASES and event.get('kind') in ('operation_pending','operation_returned'):
                    row['phase_states'][event['operation']]='pending' if event['kind']=='operation_pending' else 'returned'
                if event.get('phase') in PHASES and event.get('kind')=='recovery_required':
                    row['phase_states'][event['phase']]='failed'
            if row['failure_code']:
                row['failure_phase']=row['phase']
                for event in events[:10000] if isinstance(events,list) else []:
                    event=mapping(event)
                    if event.get('kind')=='recovery_required' and event.get('phase') in PHASE_NAMES:
                        row['failure_phase']=event['phase']
            refs=mapping(mapping(mapping(journal.get('receipts')).get('collect_final')).get('artifacts'))
            if row['status']=='completed':
                try:
                    score,result,group_id,refs=verified_score(reader,folder,journal)
                    row.update(persisted_xp=score['metrics']['net_xp'],alive_at_logout=score['alive_at_logout'],
                        score_verification='runner_verified_receipts_rechecked',comparison_group=group_id)
                    row['timing']={k:v for k,v in score['timing'].items() if number(v)}
                except (ValueError,OSError,TypeError,KeyError,RecursionError):
                    row['score_verification']='unverified'
            if not result and refs:
                try: result=reader.artifact(folder,refs,'result')
                except (ValueError,OSError,TypeError,KeyError,RecursionError): pass
        if relay_folder:
            candidate=reader.optional(relay_folder,'controller.json')
            if candidate and candidate.get('id')==run_id: controller=candidate
            if not result:
                candidate=reader.optional(relay_folder,'result.json')
                if candidate and mapping(candidate.get('controller')).get('id')==run_id: result=candidate
            recording=reader.optional(relay_folder,'recording.json') or {}
        if result: controller=mapping(result.get('controller'))
        live_run=mapping(live.get('run'))
        if live_run.get('id')==run_id:
            controller=live_run
            row['live']=True
            row['renderer_fresh']=live.get('fresh') is True
        row['mode']=controller.get('mode') if controller.get('mode') in ('api','script') else 'unknown'
        row['controller_status']=controller.get('status') if controller.get('status') in BRIDGE_STATUSES else None
        if not folder:
            row['status']=controller.get('status') if controller.get('status') in BRIDGE_STATUSES else 'unavailable'
            row['requested_model']=model(controller.get('model'))
            row['score_verification']='integration_unscored'
            if row['status']=='failed': row['failure_code']=failure(controller.get('reason'))
        returned=model(controller.get('returnedModel')) or model(mapping(result.get('api')).get('model'))
        row['api_response_saved']=bool(returned and mapping(result.get('api')).get('status')=='completed')
        row['api_usage']={key:value for key,value in mapping(mapping(result.get('api')).get('usage')).items()
            if key in ('input_tokens','output_tokens','total_tokens') and integer(value) is not None}
        row['returned_model']=returned
        row['attribution']='exact' if returned and returned==row['requested_model']==model(controller.get('model')) else 'mismatch' if returned else 'pending'
        if row['attribution']!='exact': row['comparison_group']=None
        row['reported_actions']=integer(controller.get('actions'),10000)
        row['action_limit']=row['action_limit'] or integer(controller.get('actionLimit'),10000)
        if row['score_verification']=='runner_verified_receipts_rechecked':
            row.update(action_evidence(result,row['action_limit']))
        xp=result.get('observedXpDelta')
        if number(xp,-2**53+1): row['diagnostic_xp']=xp
        alive=mapping(mapping(result.get('final')).get('character')).get('alive')
        if type(alive) is bool: row['alive_at_last_observation']=alive
        observation=mapping(live.get('observation'))
        if live_run.get('id')==run_id and live.get('fresh') is True and observation.get('ready') is True:
            if all(number(observation.get(key),0,1499.999) for key in ('ageMs','renderAgeMs')):
                character=mapping(observation.get('character'))
                if type(character.get('alive')) is bool: row['alive_at_last_observation']=character['alive']
                initial=mapping(result.get('initial'))
                if not initial and relay_folder:
                    payload=reader.optional(relay_folder,'api-request-body.json')
                    if payload and isinstance(payload.get('input'),str):
                        initial=mapping(mapping(parse_json(payload['input'])).get('observation'))
                before=mapping(initial.get('character'))
                if (number(character.get('exp')) and number(before.get('exp'))
                        and integer(character.get('level'),255) is not None and character['level']==before.get('level')):
                    row['diagnostic_xp']=character['exp']-before['exp']
        for key,field in (('api_ms','apiLatencyMs'),('elapsed_ms','elapsedMs')):
            value=mapping(result.get('timing')).get(field)
            if key not in row['timing'] and number(value): row['timing'][key]=value
        if refs:
            try: recording=reader.artifact(folder,refs,'recording')
            except (ValueError,OSError,TypeError,KeyError,RecursionError): recording={}
        if row['score_verification']=='runner_verified_receipts_rechecked':
            try: row['publication_evidence']=publication_evidence(reader,folder,run_id,refs,result,score,recording,now_ms)
            except (ValueError,OSError,TypeError,KeyError,RecursionError):
                row['publication_evidence']={'status':'blocked','reason_code':'evidence_unavailable'}
        approved=mapping(mapping(recording_map).get(run_id))
        url=recording_url(approved.get('url'),prefix)
        if (url and digest(approved.get('sha256')) and approved['sha256']==recording.get('sha256')
                and recording.get('status')=='completed'
                and mapping(recording.get('overlay')).get('controller_id')==run_id
                and mapping(recording.get('overlay')).get('model')==row['requested_model']
                and mapping(recording.get('overlay')).get('mode')==row['mode']):
            row['recording']={'url':url,'sha256':approved['sha256'],'reviewed':recording.get('reviewed') is True}
            if row['score_verification']=='runner_verified_receipts_rechecked':
                cue=playback_cue(result,recording,row)
                if cue is not None: row['recording']['playback']=cue
    except (ValueError,OSError,TypeError,KeyError,RecursionError):
        row.update(status='unavailable',failure_code='evidence_unavailable',persisted_xp=None,
                   score_verification='unverified',comparison_group=None,
                   actions=None,acknowledged_actions=None,action_attempts=None,
                   action_verification='unverified',no_op=None)
    if row['created_at_ms'] is not None:
        row['timing']['attempt_elapsed_ms']=max(0,(now_ms if row['status'] in ('running','recovering') else row['updated_at_ms'])-row['created_at_ms'])
    return row


def build_snapshot(attempt_root,relay_root=None,*,live_status=None,recording_map=None,limit=50,now_ms=None,
                   recording_path_prefix='/recordings/'):
    if type(limit) is not int or not 1<=limit<=100: raise ProjectionError('invalid_limit')
    now_ms=round(time.time()*1000) if now_ms is None else now_ms
    if integer(now_ms) is None: raise ProjectionError('invalid_clock')
    prefix=recording_prefix(recording_path_prefix)
    attempts,cut_a=directories(attempt_root); relay,cut_b=directories(relay_root)
    live=mapping(live_status)
    if live.get('ok') is True: live=mapping(live.get('result'))
    if 'bridge' in live: live=mapping(live.get('bridge'))|{'observation':live.get('observation')}
    live_id=mapping(live.get('run')).get('id')
    combined=dict(relay); combined.update(attempts)
    ordered=sorted(combined,key=lambda key:(key==live_id,combined[key][1]),reverse=True)
    reader=Reader()
    rows=[project_attempt(reader,key,attempts.get(key,(None,))[0],relay.get(key,(None,))[0],live,recording_map,now_ms,prefix)
          for key in ordered[:limit]]
    groups={}
    for row in rows:
        if row['comparison_group'] and row['status']=='completed':
            groups.setdefault(row['comparison_group'],[]).append(row)
    comparisons=[]
    for key,members in groups.items():
        models=sorted({row['requested_model'] for row in members})
        comparisons.append({'id':key,'models':models,'ready':len(models)>=2,'ranked':False,
            'attempt_ids':[row['id'] for row in members],'scope':'displayed_attempts',
            'reason':'same_frozen_inputs' if len(models)>=2 else 'another_model_required'})
    return {'schema_version':1,'generated_at_ms':now_ms,'source':'full_client_private_receipt_projection',
            'verification':'completed_runner_receipts_rechecked','ranked':False,
            'recording_prefix':prefix,'truncated':cut_a or cut_b or len(ordered)>limit,'attempts':rows,'comparisons':comparisons}


def write_snapshot(path,value,*,public=False):
    path=Path(path)
    if not path.is_absolute() or path.parent.resolve()!=path.parent or path.is_symlink():
        raise ProjectionError('invalid_output_path')
    raw=json.dumps(value,allow_nan=False,separators=(',',':')).encode()+b'\n'
    fd,temporary=tempfile.mkstemp(prefix='.results-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw); stream.flush(); os.fchmod(stream.fileno(),0o644 if public else 0o600); os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def read_admin_status(path,timeout=1):
    """The only socket request this exporter can issue is read-only status."""
    path=Path(path)
    if not path.is_absolute() or path.parent.resolve()!=path.parent or len(os.fsencode(path))>100:
        raise ProjectionError('invalid_status_socket')
    before=path.lstat(); parent=path.parent.lstat()
    expected_uid=before.st_uid if os.geteuid()==0 else os.geteuid()
    if (not stat.S_ISSOCK(before.st_mode) or stat.S_IMODE(before.st_mode)!=0o600 or before.st_uid!=expected_uid
            or not stat.S_ISDIR(parent.st_mode) or stat.S_IMODE(parent.st_mode)!=0o700 or parent.st_uid!=expected_uid):
        raise ProjectionError('untrusted_status_socket')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        deadline=time.monotonic()+timeout
        client.settimeout(timeout);client.connect(str(path))
        if hasattr(socket,'SO_PEERCRED'):
            _,peer_uid,_=struct.unpack('3i',client.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i')))
            if peer_uid not in (0,expected_uid): raise ProjectionError('untrusted_status_peer')
        client.sendall(b'{"op":"status"}\n')
        raw=b''
        while not raw.endswith(b'\n'):
            remaining=deadline-time.monotonic()
            if remaining<=0: raise ProjectionError('status_timeout')
            client.settimeout(remaining)
            block=client.recv(min(65536,256*1024+1-len(raw)))
            if not block: raise ProjectionError('incomplete_status_response')
            raw+=block
            if len(raw)>256*1024: raise ProjectionError('status_response_limit')
    after=path.lstat()
    if any(getattr(before,key)!=getattr(after,key) for key in ('st_dev','st_ino','st_uid','st_mode')):
        raise ProjectionError('status_socket_changed')
    result=parse_json(raw)
    if not isinstance(result,dict) or result.get('ok') is not True or not isinstance(result.get('result'),dict):
        raise ProjectionError('status_unavailable')
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt-root',type=Path,required=True)
    parser.add_argument('--relay-root',type=Path)
    parser.add_argument('--live-status-file',type=Path)
    parser.add_argument('--admin-socket',type=Path)
    parser.add_argument('--recording-map',type=Path)
    parser.add_argument('--recording-prefix',default='/recordings/')
    parser.add_argument('--limit',type=int,default=50)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--public-output',action='store_true')
    parser.add_argument('--watch-seconds',type=int,default=0,help='Finite export window: 0 once, otherwise 1–3600 seconds; refresh every 2 seconds')
    args=parser.parse_args(argv)
    try:
        if (not 0<=args.watch_seconds<=3600 or args.watch_seconds and not args.output
                or args.admin_socket and args.live_status_file):
            raise ProjectionError('invalid_export_options')
        def option(path):
            if path is None: return None
            if not path.is_absolute() or path.parent.resolve()!=path.parent: raise ProjectionError('invalid_input_path')
            return Reader().json(path.parent,path.name)
        deadline=time.monotonic()+args.watch_seconds
        while True:
            live=option(args.live_status_file);live_available=None
            if args.admin_socket:
                try:
                    live=read_admin_status(args.admin_socket,timeout=min(1,max(.001,deadline-time.monotonic())) if args.watch_seconds else 1)
                    live_available=True
                except (ValueError,OSError,TypeError,RecursionError):
                    live=None;live_available=False
            snapshot=build_snapshot(args.attempt_root,args.relay_root,live_status=live,
                recording_map=option(args.recording_map),limit=args.limit,recording_path_prefix=args.recording_prefix)
            snapshot['live_status_available']=live_available
            if args.output: write_snapshot(args.output,snapshot,public=args.public_output)
            else: print(json.dumps(snapshot,allow_nan=False))
            remaining=deadline-time.monotonic()
            if not args.watch_seconds or remaining<=0: break
            time.sleep(min(2,remaining))
            if time.monotonic()>=deadline: break
        return 0
    except (ValueError,OSError,TypeError,KeyError,RecursionError):
        print('{"error":"dashboard_projection_unavailable"}')
        return 1


if __name__=='__main__': raise SystemExit(main())
