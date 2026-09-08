"""Offline verification of every cycle in an adaptive pilot, never a ranking.

This authenticates consistency within trusted collector files, not the host.
Persisted net XP is verified separately from native logout/database receipts.
"""
from full_client_adaptive import PROTOCOL, PASSIVE_STOP_REASONS, digest, prompt, validate_protocol
from full_client_score import EvidenceError, parse_json, read_artifact_bytes, same_json
from maple_agent import model_decision, validate_rpc
import math
import json


def require(value):
    if not value:
        raise EvidenceError('adaptive: inconsistent aggregate cycle evidence')


def references(result):
    """Only the fixed relative cycle layout may be copied from the relay."""
    trace = result['adaptive']
    refs = [(result['adaptiveTrace'], 'adaptive.json'), (trace['instructions'], 'adaptive-prompt.txt')]
    require(isinstance(trace['cycles'], list) and len(trace['cycles']) <= 16)
    for index, cycle in enumerate(trace['cycles']):
        require(cycle.get('index') == index and type(cycle['index']) is int)
        for key, filename in (('request', 'api-request.json'), ('response', 'api-response.json'),
                              ('program', 'program.js'), ('choice', 'program.json'),
                              ('execution_receipt', 'execution.json')):
            ref = cycle.get(key)
            if ref is not None:
                refs.append((ref, f'cycles/{index:03d}/{filename}'))
    require(all(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}
                and ref['path'] == path for ref, path in refs))
    return [ref for ref, _ in refs]


def verify_result(result, root, *, protocol, model):
    p = validate_protocol(protocol)
    trace = result['adaptive']
    horizon=p.get('horizon_policy')
    reserve_ms=(50+p['program_seconds']+5)*1000 if horizon else None
    for ref in references(result):
        read_artifact_bytes(root, ref, 'adaptive', maximum=16 * 1024 * 1024)
    require(same_json(parse_json(read_artifact_bytes(root, result['adaptiveTrace'], 'adaptive')), trace))
    require(trace.get('schema_version') == 1 and type(trace['schema_version']) is int
            and trace.get('protocol') == result.get('protocol') == PROTOCOL
            and trace.get('protocol_sha256') == digest(p) and same_json(trace.get('limits'), p)
            and trace.get('requested_model') == model == result['controller'].get('model')
            and trace.get('run_id') == result['controller'].get('id')
            and result.get('source') == 'full-client-adaptive-pilot'
            and same_json(result['controller'].get('adaptiveProtocol'), p)
            and trace.get('status') == result['controller'].get('status') == 'completed'
            and trace.get('error') is None and trace.get('reason') in
                ('wall_time_limit', 'action_limit', 'sdk_request_limit', 'token_reservation_limit', 'death', 'api_request_limit', 'request_window_closed'))
    require(horizon is not None or trace['reason']!='request_window_closed' and 'horizon_wait' not in trace)
    instructions = prompt(p)
    require(read_artifact_bytes(root, trace['instructions'], 'instructions') == instructions.encode())
    timing, counters = trace['timing'], trace['counters']
    for key in ('wall_started_at_ms', 'wall_deadline_at_ms', 'wall_ended_at_ms',
                'controller_ended_ms', 'wall_elapsed_ms', 'cleanup_overrun_ms'):
        require(type(timing.get(key)) is int and 0 <= timing[key] <= 2**53-1)
    require(timing['wall_deadline_at_ms'] == timing['wall_started_at_ms'] + 300000
            and timing['wall_ended_at_ms'] == timing['wall_started_at_ms'] + timing['controller_ended_ms']
            and timing['wall_elapsed_ms'] == min(300000, timing['controller_ended_ms'])
            and timing['cleanup_overrun_ms'] == max(0, timing['controller_ended_ms'] - 300000)
            and timing['cleanup_overrun_ms'] <= 5000)
    total = {key: 0 for key in ('api_requests_started', 'api_responses_confirmed', 'reserved_tokens',
             'actual_input_tokens', 'actual_output_tokens', 'actual_total_tokens',
             'actions', 'action_attempts', 'sdk_requests')}
    steps, intervals, recent = [], [], []
    last = 0; response_ids=set()
    def observation(obs):
        require(isinstance(obs,dict) and obs.get('ready') is True and isinstance(obs.get('character'),dict)
                and all(type(obs.get(k)) in (int,float) and math.isfinite(obs[k]) and 0<=obs[k]<1500
                        for k in ('ageMs','renderAgeMs')))
    wait=trace.get('horizon_wait')
    stopped_for=wait.get('reason') if isinstance(wait,dict) else trace['reason']
    for index, cycle in enumerate(trace['cycles']):
        t = cycle['timing']
        require(type(t.get('observed_ms')) is int and last <= t['observed_ms'] <= 300000
                and cycle['requested_model'] == model)
        if horizon:observation(cycle['observation'])
        if cycle['status'] == 'budget_rejected':
            require(index == len(trace['cycles'])-1 and stopped_for == 'token_reservation_limit'
                    and cycle['api_outcome'] == 'not_started' and cycle['request'] is None and cycle['response'] is None
                    and type(cycle['token_reservation']) is int
                    and total['reserved_tokens'] + cycle['token_reservation'] > p['max_total_tokens'])
            last=t['observed_ms'];continue
        window_closed=cycle['status']=='window_closed'
        if window_closed:
            require(horizon is not None and index==len(trace['cycles'])-1
                and stopped_for=='request_window_closed' and cycle['api_outcome']=='not_started'
                and cycle['response'] is None and cycle['program'] is None and cycle['execution'] is None
                and cycle['usage'] is None and cycle['returned_model'] is None
                and 'api_started_ms' not in t and 'api_ended_ms' not in t
                and type(t.get('window_closed_ms')) is int
                and max(t['observed_ms'],300000-reserve_ms)<=t['window_closed_ms']<=timing['controller_ended_ms'])
            last=t['window_closed_ms']
            if cycle['request'] is None:continue
        request = parse_json(read_artifact_bytes(root, cycle['request'], 'request'))
        identity = {'maplebench_run_id': trace['run_id'], 'maplebench_cycle_index': str(index)}
        value = parse_json(request['input'])
        require(set(value) == {'observation', 'recent_programs', 'remaining_seconds', 'remaining_actions',
                               'remaining_sdk_requests', 'cycle_index'}
                and value['cycle_index'] == index and type(value['cycle_index']) is int
                and same_json(value['observation'], cycle['observation'])
                and (index != 0 or same_json(value['observation'], result['initial']))
                and same_json(value['recent_programs'], recent[-2:])
                and value['remaining_actions'] == p['max_actions'] - total['action_attempts']
                and value['remaining_sdk_requests'] == p['max_sdk_requests'] - total['sdk_requests']
                and type(value['remaining_seconds']) in (int, float) and 0 < value['remaining_seconds'] <= 300
                and request.get('metadata') == identity)
        if window_closed:
            def unsent_request(_url, body, _key, _timeout):
                require(same_json(body | {'metadata':identity},request))
                return {}
            model_decision(model,instructions,value,None,output_tokens=p['max_output_tokens'],
                           timeout=50,request_fn=unsent_request)
            continue
        response = parse_json(read_artifact_bytes(root, cycle['response'], 'response'))
        require(response.get('metadata')==identity)
        def saved_response(_url, body, _key, _timeout):
            require(same_json(body | {'metadata': identity}, request))
            return response
        choice, meta = model_decision(model, instructions, value, None,
            output_tokens=p['max_output_tokens'], timeout=1, request_fn=saved_response)
        require(isinstance(meta['id'],str) and 0<len(meta['id'])<=200 and meta['id'] not in response_ids
                and cycle.get('response_id')==meta['id'])
        response_ids.add(meta['id'])
        require(meta['model'] == cycle['returned_model'] == model
                and meta['status'] == cycle['response_status'] and cycle['api_outcome'] == 'confirmed'
                and same_json(meta['usage'], cycle['usage']))
        usage = meta['usage']
        require(all(type(usage.get(key)) is int and usage[key] >= 0 for key in ('input_tokens', 'output_tokens', 'total_tokens'))
                and usage['input_tokens'] + usage['output_tokens'] == usage['total_tokens']
                and usage['output_tokens'] <= p['max_output_tokens'])
        reservation = len(json.dumps(request, ensure_ascii=False).encode()) + 1024 + p['max_output_tokens']
        require(cycle['token_reservation'] == reservation
                and all(type(t.get(k)) is int for k in ('api_started_ms', 'api_ended_ms'))
                and t['observed_ms'] <= t['api_started_ms'] < 300000
                and t['api_started_ms'] <= t['api_ended_ms'] <= timing['controller_ended_ms'])
        if horizon:
            require(type(cycle.get('request_timeout_seconds')) is int and cycle['request_timeout_seconds']==50
                and t['api_started_ms']<=300000-reserve_ms
                and t['api_ended_ms']-t['api_started_ms']<=55000)
        total['api_requests_started'] += 1; total['api_responses_confirmed'] += 1
        total['reserved_tokens'] += reservation
        for key in ('input_tokens', 'output_tokens', 'total_tokens'):
            total['actual_' + key] += usage[key]
        intervals.append({'index': index, 'started_at_ms': timing['wall_started_at_ms'] + t['api_started_ms'],
                          'ended_at_ms': timing['wall_started_at_ms'] + t['api_ended_ms']})
        last = t['api_ended_ms']
        if cycle.get('program'):
            require(choice is not None and meta['status'] == 'completed'
                    and same_json(parse_json(read_artifact_bytes(root, cycle['choice'], 'choice')), choice)
                    and read_artifact_bytes(root, cycle['program'], 'program') == choice['code'].encode())
        execution = cycle.get('execution')
        if execution is None:
            require(cycle.get('execution_receipt') is None)
            if cycle['status'] == 'invalid_program':
                require(choice is None)
                recent.append({'error': 'Model response was incomplete or invalid; no code executed.'})
            else:
                require(index == len(trace['cycles'])-1 and trace['reason'] in ('death', 'wall_time_limit'))
            continue
        require(choice is not None and cycle.get('program') and cycle['status'] == 'executed'
                and same_json(parse_json(read_artifact_bytes(root, cycle['execution_receipt'], 'execution')), execution)
                and all(type(t.get(k)) is int for k in ('program_started_ms', 'program_ended_ms'))
                and last <= t['program_started_ms'] < 300000
                and t['program_started_ms'] <= t['program_ended_ms'] <= timing['controller_ended_ms']
                and t['program_ended_ms'] - t['program_started_ms'] <= p['program_seconds']*1000 + 5000
                and execution.get('reason') in ('completed', 'program_complete', 'program_error', 'program_timeout', 'output_limit', 'time_limit', 'action_limit', 'rpc_limit', 'death'))
        cycle_steps = execution['steps']
        require(isinstance(cycle_steps, list) and all(isinstance(step, dict) for step in cycle_steps))
        accepted = sum(step.get('kind') == 'sdk' and step.get('method') == 'pressKeys'
                       and step.get('result', {}).get('accepted') is True for step in cycle_steps)
        require(all(step.get('kind') != 'sdk_error' and (step.get('method') != 'pressKeys'
                    or step.get('result', {}).get('accepted') is True) for step in cycle_steps)
                and type(execution.get('actions')) is int and execution['actions'] == accepted
                and type(execution.get('actionAttempts')) is int and execution['actionAttempts'] >= accepted
                and type(execution.get('rpcRequests')) is int and execution['rpcRequests'] >= len(cycle_steps))
        held_ms=0; seen=set()
        observation(cycle['observation']); observation(cycle['pre_execution_observation'])
        for step_index, step in enumerate(cycle_steps):
            if step.get('kind')=='rejected_rpc':
                rpc=step.get('rpc'); invalid=False
                try:
                    validate_rpc(rpc,{'adapter':'full-client','protocol':PROTOCOL})
                    invalid=rpc['id'] in seen
                except (ValueError,TypeError):invalid=True
                require(invalid and isinstance(step.get('error'),str) and len(step['error'])<=512)
                continue
            require(step.get('kind')=='sdk' and type(step.get('rpcId')) is int and step['rpcId'] not in seen)
            seen.add(step['rpcId'])
            try:
                method, argument=validate_rpc({'type':'rpc','id':step['rpcId'],'method':step.get('method'),
                    'args':step.get('args')},{'adapter':'full-client','protocol':PROTOCOL})
            except ValueError:raise EvidenceError('adaptive: invalid SDK arguments') from None
            receipt=step.get('result'); require(isinstance(receipt,dict) and receipt.get('error') in (None,''))
            if method=='pressKeys':
                require(receipt.get('accepted') is True); observation(receipt.get('observation'))
                held_ms+=argument['durationMs']
            elif method=='observe':observation(receipt)
            else:
                waited=receipt.get('waitedMs')
                require(type(waited) is int and 0<=waited<=argument
                        and (waited==argument or step_index==len(cycle_steps)-1
                             and execution['reason'] in ('time_limit','program_timeout')))
                held_ms+=waited
        require(held_ms<=min(p['program_seconds']*1000,300000-t['program_started_ms'])+5
                and held_ms<=t['program_ended_ms']-t['program_started_ms']+5
                and execution['actionAttempts']==accepted)
        total['actions'] += accepted; total['action_attempts'] += execution['actionAttempts']
        total['sdk_requests'] += execution['rpcRequests']
        steps.extend(dict(step, cycle_index=index) for step in cycle_steps)
        last = t['program_ended_ms']
        recent.append({'note': choice['note'][:240], 'code': choice['code'],
            'execution': {k: execution.get(k) for k in ('reason', 'error', 'actions', 'actionAttempts', 'rpcRequests')},
            'recent_receipts': cycle_steps[-5:]})
    require(sum(len(json.dumps({k:v for k,v in step.items() if k!='cycle_index'},sort_keys=True,
                separators=(',',':'),allow_nan=False).encode()) for step in steps)<=p['max_evidence_bytes'])
    require(same_json(total, counters) and 1 <= total['api_requests_started'] <= p['max_api_requests']
            and total['reserved_tokens'] <= p['max_total_tokens'] and total['actual_total_tokens'] <= p['max_total_tokens']
            and total['actions'] <= total['action_attempts'] <= p['max_actions']
            and total['sdk_requests'] <= p['max_sdk_requests'] and same_json(steps, result['program']['steps'])
            and result['program']['actions'] == total['actions']
            and result['program']['actionAttempts'] == total['action_attempts']
            and result['program']['rpcRequests'] == total['sdk_requests'])
    if horizon:
        require('horizon_wait' in trace)
        if wait is None:
            require(trace['reason'] in ('death','wall_time_limit'))
        else:
            require(isinstance(wait,dict) and set(wait)=={'reason','started_ms','ended_ms','counters','samples'}
                and wait['reason'] in PASSIVE_STOP_REASONS
                and trace['reason'] in (wait['reason'],'death')
                and all(type(wait.get(k)) is int for k in ('started_ms','ended_ms'))
                and last<=wait['started_ms']<=wait['ended_ms']<=timing['controller_ended_ms']
                and same_json(wait['counters'],counters)
                and isinstance(wait['samples'],list) and len(wait['samples'])<=301)
            previous=wait['started_ms'];dead=False
            for sample in wait['samples']:
                require(isinstance(sample,dict) and set(sample)=={'observed_ms','ageMs','renderAgeMs','character'}
                    and type(sample['observed_ms']) is int and not dead
                    and previous<=sample['observed_ms']<=min(previous+5000,wait['ended_ms'])
                    and isinstance(sample['character'],dict)
                    and set(sample['character'])<=set(('x','y','hp','maxHp','mp','maxMp','exp','level','mapId','alive'))
                    and type(sample['character'].get('alive')) is bool
                    and all(type(v) is bool if k=='alive' else type(v) in (int,float) and math.isfinite(v)
                            for k,v in sample['character'].items()))
                observation(sample|{'ready':True})
                previous=sample['observed_ms'];dead=sample['character']['alive'] is False
            require(wait['ended_ms']-previous<=5000)
            if trace['reason']=='death':require(dead)
            else:require(not dead and timing['wall_elapsed_ms']==300000 and wait['ended_ms']>=300000)
            if wait['reason']=='request_window_closed':require(wait['started_ms']>=300000-reserve_ms)
    timeline = result['timeline']; origin = timing['wall_started_at_ms'] - result['timing']['startedAtMs']
    require(origin >= 0 and timeline['adaptive_started_ms'] == timeline['program_started_ms'] == origin
            and timeline['api_started_ms'] == intervals[0]['started_at_ms'] - result['timing']['startedAtMs']
            and timeline['api_ended_ms'] == intervals[-1]['ended_at_ms'] - result['timing']['startedAtMs']
            and origin + timing['controller_ended_ms'] <= timeline['program_ended_ms'] <= origin + timing['controller_ended_ms'] + 3100
            and timeline['program_ended_ms'] == timeline['adaptive_ended_ms']
            and result['timing']['endedAtMs'] >= result['timing']['startedAtMs'] + timeline['program_ended_ms'] - 5)
    reason=stopped_for
    if reason=='wall_time_limit':require(timing['wall_elapsed_ms']==300000)
    if reason=='api_request_limit':require(total['api_requests_started']==p['max_api_requests'])
    if reason=='action_limit':require(total['action_attempts']==p['max_actions'])
    if reason=='sdk_request_limit':require(total['sdk_requests']==p['max_sdk_requests'])
    first, ack = timing.get('first_input_started_ms'), timing.get('first_input_acked_ms')
    if total['actions']:
        require(type(first) is int and type(ack) is int and 0 <= first <= ack <= 300000
                and any(c.get('execution') and c['execution']['actions'] > 0
                        and c['timing']['program_started_ms'] <= first <= ack <= c['timing']['program_ended_ms']
                        for c in trace['cycles'])
                and timeline.get('first_input_started_ms') == origin + first
                and timeline.get('first_input_acked_ms') == origin + ack)
    else:
        require(first is None and ack is None and timeline.get('first_input_started_ms') is None
                and timeline.get('first_input_acked_ms') is None)
    return {'counters': total, 'api_intervals': intervals, 'wall_elapsed_ms': timing['wall_elapsed_ms'],
            'api_ms': sum(v['ended_at_ms'] - v['started_at_ms'] for v in intervals),
            'authoritative_peak_xp_per_minute': None, 'publication_eligible': False}
