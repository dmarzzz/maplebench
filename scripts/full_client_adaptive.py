"""Versioned, inference-inclusive adaptive full-client pilot controller.

This executes model-authored programs unchanged. It does not score client XP or
turn this pilot into the future 30-minute/15-second-window research protocol.
"""
from __future__ import annotations
import hashlib
import json
import math
import re
import time

from maple_agent import MODELS, model_decision

PROTOCOL = 'full-client-adaptive-pilot-v1'
KEYS = frozenset('LEFT RIGHT UP DOWN JUMP ATTACK PRIMARY_SKILL SECONDARY_SKILL BUFF_1 BUFF_2 HP_POTION MP_POTION'.split())
DEFAULT_PROTOCOL = {'schema_version':1,'id':PROTOCOL,'wall_seconds':300,'program_seconds':20,
    'max_api_requests':12,'max_output_tokens':3000,'max_total_tokens':120000,
    'max_actions':1600,'max_sdk_requests':6000,'max_evidence_bytes':4*1024*1024,
    'profile':{'id':'hero-180','class_name':'Hero','level':180,
               'skill_keys':{'PRIMARY_SKILL':'Brandish','SECONDARY_SKILL':'Combo Attack','BUFF_1':'Booster','BUFF_2':'Maple Warrior'}}}

# Optional policy: absent means the original pilot's exact prompt and stop behavior.
FULL_HORIZON_POLICY = {'id':'full-horizon-reserve-v1','request_timeout_seconds':50,
    'settlement_reserve_seconds':5,'passive_observation_interval_ms':1000}
CAPTURE_COHORT_RECIPE = 'full-horizon-capture-cohort-v1'
PASSIVE_STOP_REASONS = frozenset(('request_window_closed','api_request_limit',
    'action_limit','sdk_request_limit','token_reservation_limit'))

class AdaptiveError(ValueError):
    """Only fixed credential-free codes cross the controller boundary."""

def require(value,code):
    if not value:raise AdaptiveError(code)

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def validate_protocol(value):
    require(isinstance(value,dict) and set(DEFAULT_PROTOCOL)<=set(value)<=set(DEFAULT_PROTOCOL)|{'horizon_policy','capture_duration_policy'},'invalid_adaptive_protocol')
    require(value.get('schema_version')==1 and type(value['schema_version']) is int
            and value.get('id')==PROTOCOL and type(value.get('wall_seconds')) is int
            and value['wall_seconds']==300,'invalid_adaptive_protocol')
    bounds={'program_seconds':(1,30),'max_api_requests':(1,16),'max_output_tokens':(256,3000),
            'max_total_tokens':(1024,240000),'max_actions':(1,2400),'max_sdk_requests':(1,10000),
            'max_evidence_bytes':(65536,4*1024*1024)}
    require(all(type(value.get(k)) is int and a<=value[k]<=b for k,(a,b) in bounds.items()),'invalid_adaptive_limits')
    if 'horizon_policy' in value:
        require(digest(value['horizon_policy'])==digest(FULL_HORIZON_POLICY),'invalid_adaptive_horizon_policy')
    if 'capture_duration_policy' in value:
        from full_client_capture import validate_duration_policy
        try:validate_duration_policy(value['capture_duration_policy'])
        except (ValueError,TypeError):raise AdaptiveError('invalid_capture_duration_policy') from None
    profile=value.get('profile')
    require(isinstance(profile,dict) and set(profile)=={'id','class_name','level','skill_keys'}
            and isinstance(profile['id'],str) and re.fullmatch('[a-z0-9][a-z0-9-]{0,63}',profile['id'])
            and isinstance(profile['class_name'],str) and re.fullmatch('[A-Za-z0-9 ()/,-]{1,64}',profile['class_name'])
            and type(profile['level']) is int and 1<=profile['level']<=255
            and isinstance(profile['skill_keys'],dict) and set(profile['skill_keys'])<=KEYS
            and all(isinstance(v,str) and re.fullmatch('[A-Za-z0-9 ()+/:,-]{1,80}',v) for v in profile['skill_keys'].values()),
            'invalid_adaptive_profile')
    return json.loads(json.dumps(value))


def capture_cohort_protocol(profile):
    """Prepare the next frozen cohort; this does not mutate defaults or run it.

    The larger allowance is a conservative reservation ceiling, not a target
    token spend. Every model in a fixture receives the same bounded contract.
    """
    from full_client_capture import CAPTURE_DURATION_POLICY
    value=json.loads(json.dumps(DEFAULT_PROTOCOL))
    value.update(profile=profile,max_total_tokens=240000,
        horizon_policy=FULL_HORIZON_POLICY,capture_duration_policy=CAPTURE_DURATION_POLICY)
    return validate_protocol(value)

def prompt(protocol):
    p=validate_protocol(protocol)
    text = f'''You control the real MapleStory v83 full client with this frozen profile:
{json.dumps(p['profile'],sort_keys=True)}
Discover and improve a gameplay strategy through repeated observation and code.
This is one {p['wall_seconds']}-second wall-clock pilot, including model latency,
planning, execution and waits. Game time continues while you think. Programs run
serially; there is no fallback policy or automatic combat during planning.
Each response supplies a JavaScript async function BODY. The harness wraps and
invokes the body once. Use top-level await. Defining async function run() alone
does nothing; explicitly await your helpers. Code is never repaired or replayed.
Frozen SDK:
  sdk.observe(): character {{x,y,hp,maxHp,mp,maxMp,exp,alive,mapId,level}} and
    monsters [{{objectId,x,y}}]. Client XP is diagnostic, never authoritative score.
  sdk.pressKeys(keys, milliseconds): hold 1..3 keys for 30..1500ms, then release.
    LEFT RIGHT UP DOWN JUMP ATTACK PRIMARY_SKILL SECONDARY_SKILL BUFF_1 BUFF_2 HP_POTION MP_POTION
  sdk.wait(milliseconds): wait 1..3000ms.
PRIMARY_SKILL, SECONDARY_SKILL, BUFF_1 and BUFF_2 press A, S, D and F.
The profile declares the actual skill behind each mapped key; undeclared skill
keys are not promised to be useful. Coordinates increase right/down. Face nearby
monsters on your platform to attack. Re-observe and respond to HP/MP and movement.
No arbitrary position edits, stat edits, shell, imports, network, assets or
account credentials are available. A mapped native Teleport skill is allowed. Each program gets at most {p['program_seconds']} seconds and the
remaining aggregate SDK/action budget. Return before its deadline. Local program
variables do not survive between responses. The next input contains your recent
programs and their actual outcomes, so you can revise your own strategy.
Return JSON {{note,code}} with a short intention, not private reasoning.
'''
    if 'horizon_policy' in p:
        reserve=50+p['program_seconds']+5
        text+=f'''Frozen full-horizon policy: a new request requires at least {reserve} seconds
remaining (50 seconds for inference, {p['program_seconds']} for execution, 5 for settlement).
Once that reserve or a confirmed aggregate budget is exhausted, the harness only
observes the live world until the 300-second deadline. It does not press keys or
call the model during that wait. Death, cancellation and failures still stop early.
'''
    return text

def run_adaptive(*, run_id, model, protocol, initial, observe, request_api,
                 execute, persist_json, persist_bytes, cancel_check,
                 on_phase=lambda **_:None, on_step=lambda _:None,
                 clock=time.monotonic, wall_clock=time.time, sleep=time.sleep):
    """Run serial observation/API/program cycles under one monotonic deadline.

Injected I/O is the existing trusted bridge. request_api accepts provider URL,
body and a bounded timeout; credentials remain exclusively in that callback.
Persistence callbacks return {path,sha256} relative to this run's directory.
The returned trace is not a persisted-XP or publication-validation receipt.
"""
    protocol=validate_protocol(protocol)
    require(model in MODELS and isinstance(run_id,str) and re.fullmatch('[a-f0-9]{32}',run_id),'invalid_adaptive_identity')
    started=clock();started_wall=round(wall_clock()*1000);deadline=started+protocol['wall_seconds']
    on_phase(phase='preparing',cycle=0,deadline=deadline,counters={})
    instructions=prompt(protocol)
    horizon=protocol.get('horizon_policy')
    reserve=50+protocol['program_seconds']+5 if horizon else None
    counters={k:0 for k in ('api_requests_started','api_responses_confirmed','reserved_tokens','actual_input_tokens',
        'actual_output_tokens','actual_total_tokens','actions','action_attempts','sdk_requests')}
    trace={'schema_version':1,'protocol':PROTOCOL,'protocol_sha256':digest(protocol),'run_id':run_id,
        'requested_model':model,'limits':protocol,'status':'running','reason':None,
        'timing':{'wall_started_at_ms':started_wall,'wall_deadline_at_ms':started_wall+300000,
                  'first_input_started_ms':None,'first_input_acked_ms':None},
        'counters':counters,'cycles':[],
        'scoring':{'persisted_net_xp':None,'authoritative_peak_xp_per_minute':None,
                   'authoritative_window_status':'not_collected_by_controller'}}
    if horizon:trace['horizon_wait']=None
    trace['instructions']=persist_bytes('adaptive-prompt.txt',instructions.encode())
    recent=[];steps=[];final=initial;error=None;receipt_bytes=0;response_ids=set()
    def offset():return round((clock()-started)*1000)
    def save():persist_json('adaptive.json',trace)
    def stop(reason,failed=False):
        trace.update(status='failed' if failed else 'completed',reason=reason)
    def bounded_observe():
        cancel_check();remaining=deadline-clock()
        require(remaining>0,'adaptive_wall_deadline')
        value=observe(min(3,remaining))
        require(isinstance(value,dict) and value.get('ready') is True and isinstance(value.get('character'),dict),
                'adaptive_observation_unavailable')
        return value
    def finish(reason):
        nonlocal final
        if not horizon or reason not in PASSIVE_STOP_REASONS:
            stop(reason);return
        wait={'reason':reason,'started_ms':offset(),'ended_ms':None,
              'counters':dict(counters),'samples':[]}
        trace['horizon_wait']=wait
        on_phase(phase='waiting_for_deadline',cycle=len(trace['cycles'])-1,
                 deadline=deadline,counters=dict(counters))
        save()
        try:
            while clock()<deadline:
                cancel_check();remaining=deadline-clock()
                # Never shorten an observation timeout against the normal end.
                # The final <=4s is a cancellable passive wait, with no input RPC.
                if remaining>4:
                    value=observe(3)
                    require(isinstance(value,dict) and value.get('ready') is True
                        and isinstance(value.get('character'),dict)
                        and type(value['character'].get('alive')) is bool
                        and all(type(value.get(k)) in (int,float) and math.isfinite(value[k])
                                and 0<=value[k]<1500 for k in ('ageMs','renderAgeMs')),
                        'adaptive_observation_unavailable')
                    final=value;character=value['character']
                    compact={k:v for k,v in character.items()
                        if k in ('x','y','hp','maxHp','mp','maxMp','exp','level','mapId','alive')
                        and (type(v) is bool and k=='alive' or type(v) in (int,float) and math.isfinite(v))}
                    require(len(wait['samples'])<301,'adaptive_passive_sample_limit')
                    wait['samples'].append({'observed_ms':offset(),'ageMs':value['ageMs'],
                        'renderAgeMs':value['renderAgeMs'],'character':compact})
                    save()
                    if character.get('alive') is False:
                        stop('death');return
                remaining=deadline-clock()
                if remaining>0:sleep(min(horizon['passive_observation_interval_ms']/1000,remaining))
            stop(reason)
        finally:
            wait['ended_ms']=offset();save()
    def window_open():return not horizon or deadline-clock()>=reserve
    def usage_counts(meta):
        usage=meta.get('usage')
        require(isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0
                for k in ('input_tokens','output_tokens','total_tokens'))
                and usage['input_tokens']+usage['output_tokens']==usage['total_tokens'],'adaptive_usage_missing_or_invalid')
        return usage
    try:
        save()
        for index in range(protocol['max_api_requests']):
            cancel_check()
            if clock()>=deadline:stop('wall_time_limit');break
            if counters['action_attempts']>=protocol['max_actions']:finish('action_limit');break
            if counters['sdk_requests']>=protocol['max_sdk_requests']:finish('sdk_request_limit');break
            if horizon and not window_open():finish('request_window_closed');break
            current=initial if index==0 else bounded_observe()
            final=current
            require(isinstance(current,dict) and current.get('ready') is True and isinstance(current.get('character'),dict),
                    'adaptive_observation_unavailable')
            require(current['character'].get('level')==protocol['profile']['level'],'adaptive_profile_level_mismatch')
            if current['character'].get('alive') is False:stop('death');break
            if not window_open():finish('request_window_closed');break
            cycle={'index':index,'requested_model':model,'returned_model':None,'status':'preparing',
                'observation':current,'timing':{'observed_ms':offset()},'api_outcome':'not_started',
                'request':None,'response':None,'program':None,'execution':None,'usage':None}
            trace['cycles'].append(cycle)
            prefix=f'cycles/{index:03d}/'
            remaining_actions=protocol['max_actions']-counters['action_attempts']
            remaining_sdk=protocol['max_sdk_requests']-counters['sdk_requests']
            value={'observation':current,'recent_programs':recent[-2:],
                'remaining_seconds':round(max(0,deadline-clock()),3),'remaining_actions':remaining_actions,
                'remaining_sdk_requests':remaining_sdk,'cycle_index':index}
            submitted=False
            def provider(url,payload,_unused,timeout):
                nonlocal submitted
                require(not submitted,'adaptive_cycle_replay_refused')
                cancel_check();require(clock()<deadline,'adaptive_wall_deadline')
                def require_window():
                    if not window_open():
                        cycle.update(status='window_closed',api_outcome='not_started')
                        cycle['timing']['window_closed_ms']=offset();save()
                        raise AdaptiveError('adaptive_request_window_closed')
                require_window()
                body=payload|{'metadata':{'maplebench_run_id':run_id,'maplebench_cycle_index':str(index)}}
                reservation=len(json.dumps(body,ensure_ascii=False).encode())+1024+protocol['max_output_tokens']
                # Reserve before dispatch; unused reservation is not recycled.
                # Actual provider usage must also fit the remaining declared cap.
                if counters['reserved_tokens']+reservation>protocol['max_total_tokens']:
                    cycle.update(status='budget_rejected',token_reservation=reservation);save()
                    raise AdaptiveError('adaptive_token_reservation_limit')
                cycle['request']=persist_json(prefix+'api-request.json',body)
                cancel_check();require(clock()<deadline,'adaptive_wall_deadline')
                if horizon:
                    # Readiness and artifact persistence may consume the reserve.
                    # Check again before marking or dispatching any provider call.
                    on_phase(phase='requesting',cycle=index,deadline=deadline,counters=dict(counters))
                    require_window()
                submitted=True;counters['api_requests_started']+=1;counters['reserved_tokens']+=reservation
                cycle.update(status='requesting',api_outcome='uncertain',token_reservation=reservation)
                save()
                if not horizon:on_phase(phase='requesting',cycle=index,deadline=deadline,counters=dict(counters))
                cycle['timing']['api_started_ms']=offset()
                if horizon:cycle['request_timeout_seconds']=50
                save()
                if horizon:
                    # A slow durable write can also close the reserve. No provider
                    # callback has run yet, so reverse only this unsent reservation.
                    if not window_open():
                        counters['api_requests_started']-=1;counters['reserved_tokens']-=reservation
                        cycle['timing'].pop('api_started_ms',None)
                        cycle.pop('request_timeout_seconds',None)
                        require_window()
                    cycle['timing']['api_started_ms']=offset()
                remaining=deadline-clock();require(remaining>0,'adaptive_wall_deadline')
                response=request_api(url,body,50 if horizon else min(timeout,remaining))
                cycle['timing']['api_ended_ms']=offset()
                cycle['response']=persist_json(prefix+'api-response.json',response)
                cycle['api_outcome']='receipt_saved';save()
                require(isinstance(response,dict) and response.get('metadata')==body['metadata'],
                        'adaptive_api_cycle_identity_mismatch')
                if horizon:require(cycle['timing']['api_ended_ms']-cycle['timing']['api_started_ms']<=55000,
                                   'adaptive_request_timeout_overrun')
                return response
            try:
                choice,meta=model_decision(model,instructions,value,None,output_tokens=protocol['max_output_tokens'],
                    timeout=50 if horizon else min(50,max(0.001,deadline-clock())),request_fn=provider)
            except AdaptiveError as failure:
                if str(failure)=='adaptive_token_reservation_limit':finish('token_reservation_limit');break
                if str(failure)=='adaptive_request_window_closed':finish('request_window_closed');break
                raise
            response_id=meta.get('id')
            require(isinstance(response_id,str) and 0<len(response_id)<=200 and response_id not in response_ids,
                    'adaptive_api_response_identity_invalid')
            response_ids.add(response_id);cycle['response_id']=response_id
            cycle['returned_model']=meta.get('model');cycle['usage']=meta.get('usage');cycle['response_status']=meta.get('status')
            require(meta.get('model')==model,'adaptive_api_model_mismatch')
            usage=usage_counts(meta)
            require(usage['output_tokens']<=protocol['max_output_tokens']
                    and counters['actual_total_tokens']+usage['total_tokens']<=protocol['max_total_tokens'],
                    'adaptive_actual_token_limit_exceeded')
            for key in ('input_tokens','output_tokens','total_tokens'):counters['actual_'+key]+=usage[key]
            counters['api_responses_confirmed']+=1
            cycle['api_outcome']='confirmed';cycle['status']='response_received';save()
            cancel_check()
            if clock()>=deadline:stop('wall_time_limit');break
            if choice is None:
                cycle['status']='invalid_program';recent.append({'error':'Model response was incomplete or invalid; no code executed.'});save();continue
            code=choice['code'];cycle['program']=persist_bytes(prefix+'program.js',code.encode())
            cycle['choice']=persist_json(prefix+'program.json',choice)
            current=bounded_observe();final=current
            if current['character'].get('alive') is False:stop('death');break
            cycle['pre_execution_observation']=current
            cycle['timing']['program_started_ms']=offset();cycle['status']='running';save()
            on_phase(phase='running',cycle=index,deadline=deadline,counters=dict(counters))
            cycle_steps=[]
            def record(step):
                nonlocal receipt_bytes
                receipt_bytes+=len(json.dumps(step,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
                require(receipt_bytes<=protocol['max_evidence_bytes'],'adaptive_evidence_byte_limit')
                cycle_steps.append(step);steps.append(dict(step,cycle_index=index));on_step(step)
            execution=execute(code,deadline=deadline,program_seconds=min(protocol['program_seconds'],max(0,deadline-clock())),
                              max_actions=remaining_actions,max_requests=remaining_sdk,step_callback=record)
            cycle['timing']['program_ended_ms']=offset();cycle['execution']=execution
            cycle['execution_receipt']=persist_json(prefix+'execution.json',execution)
            require(isinstance(execution,dict) and execution.get('steps')==cycle_steps,'adaptive_execution_receipts_mismatch')
            acknowledged=sum(step.get('kind')=='sdk' and step.get('method')=='pressKeys'
                             and step.get('result',{}).get('accepted') is True for step in cycle_steps)
            require(type(execution.get('actions')) is int and execution['actions']==acknowledged
                and type(execution.get('actionAttempts')) is int and acknowledged<=execution['actionAttempts']<=remaining_actions
                and type(execution.get('rpcRequests')) is int and len(cycle_steps)<=execution['rpcRequests']<=remaining_sdk,
                'adaptive_execution_counters_mismatch')
            counters['actions']+=acknowledged;counters['action_attempts']+=execution['actionAttempts'];counters['sdk_requests']+=execution['rpcRequests']
            cycle['status']='executed';save()
            interrupted=any(step.get('kind')=='sdk_error' or step.get('method')=='pressKeys'
                and step.get('result',{}).get('accepted') is not True for step in cycle_steps)
            require(not interrupted,'adaptive_input_receipt_uncertain')
            reason=execution.get('reason')
            if reason in ('infrastructure_error','replaced'):raise AdaptiveError('adaptive_execution_unavailable')
            if reason=='death':stop('death');break
            if counters['action_attempts']>=protocol['max_actions']:finish('action_limit');break
            if counters['sdk_requests']>=protocol['max_sdk_requests']:finish('sdk_request_limit');break
            if clock()>=deadline:stop('wall_time_limit');break
            recent.append({'note':choice['note'][:240],'code':code,'execution':{k:execution.get(k)
                for k in ('reason','error','actions','actionAttempts','rpcRequests')},
                'recent_receipts':cycle_steps[-5:]})
        else:finish('api_request_limit')
    except Exception as failure:
        error=str(failure) if isinstance(failure,AdaptiveError) else type(failure).__name__
        stop(error,True)
    finally:
        ended=offset()
        trace['timing']['controller_ended_ms']=ended
        trace['timing']['wall_ended_at_ms']=started_wall+ended
        trace['timing']['wall_elapsed_ms']=min(300000,max(0,ended))
        trace['timing']['cleanup_overrun_ms']=max(0,ended-300000)
        trace['error']=error
        save()
    return {'trace':trace,'initial':initial,'final':final,'steps':steps}
