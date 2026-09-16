"""Inference-inclusive controller for the independently versioned skill suite.

This module is an execution kernel, not a trial admission authority or scorer.
The caller must hold the ordinary world/queue/runner leases, register the unique
plan entry durably, qualify readiness, and bind the native ledger clock before
using it. All I/O is injected so deadline and failure behavior can be tested
without an API, browser, database or synthetic gameplay claim.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time

from maple_agent import MODELS, model_decision
from full_client_skill_tasks import validate_contract, descriptor as describe_task

PROTOCOL = 'full-client-skill-tasks-v1'
SHORT_TASKS = frozenset(('platforming-v1', 'native-teleport-v1', 'potion-use-v1'))
EXTENDED_TASKS = frozenset(('buff-upkeep-v1', 'portal-navigation-v1', 'return-to-hunt-v1'))
MAX_EVIDENCE_BYTES = 4 * 1024 * 1024
SHA = re.compile(r'[a-f0-9]{64}\Z')


class SkillControllerError(ValueError):
    """Only fixed, credential-free reason codes escape this boundary."""


def require(value, code):
    if not value:
        raise SkillControllerError(code)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def protocol(task_id):
    require(task_id in SHORT_TASKS | EXTENDED_TASKS, 'unknown_skill_task')
    short = task_id in SHORT_TASKS
    return {'schema_version': 1, 'id': PROTOCOL, 'task_id': task_id,
            'wall_seconds': 120 if short else 300,
            'max_api_requests': 4 if short else 12,
            'max_output_tokens': 3000, 'max_total_tokens': 96000 if short else 240000,
            'program_seconds': 10 if short else 20,
            'max_actions': 600 if short else 1600,
            'max_sdk_requests': 2000 if short else 6000,
            'request_timeout_seconds': 30 if short else 50,
            'minimum_request_admission_seconds': 15,
            'request_closeout_reserve_seconds': 10, 'settlement_seconds': 5,
            'input_ack_budget_seconds': 3, 'passive_interval_ms': 1000,
            'reasoning_effort': 'low', 'recent_programs': 2, 'recent_receipts': 5,
            'early_success_allowed': short}


def validate_protocol(value):
    require(isinstance(value, dict) and isinstance(value.get('task_id'), str),
            'invalid_skill_controller_protocol')
    expected = protocol(value['task_id'])
    require(encoded(value) == encoded(expected), 'skill_controller_protocol_changed')
    return expected


def offer(value, remaining):
    """Recomputed immediately before each dispatch; never extends the deadline."""
    p = validate_protocol(value)
    require(type(remaining) in (int, float) and math.isfinite(remaining), 'invalid_remaining_time')
    return {'admitted': remaining >= p['minimum_request_admission_seconds'],
            'request_timeout_seconds': max(0, min(p['request_timeout_seconds'],
                remaining - p['request_closeout_reserve_seconds'])),
            'program_seconds': max(0, min(p['program_seconds'], remaining - p['settlement_seconds']))}


def prompt(value, descriptor):
    p = validate_protocol(value)
    # The admission adapter supplies the separately validated public descriptor.
    require(isinstance(descriptor, dict) and len(encoded(descriptor)) <= 16000,
            'invalid_skill_task_descriptor')
    return f'''You control the real MapleStory v83 full client for one frozen skill task.
Task descriptor: {encoded(descriptor).decode()}
The {p['wall_seconds']}-second clock includes all model latency, execution and waits.
The clock starts immediately before the first model request. There is no automatic
movement or combat while the model is thinking. Accomplish this task's stated goal.
Return JSON {{note,code}}: note is a short intention, code is a JavaScript async
function BODY, wrapped and invoked exactly once. Use top-level await. Defining a
function without calling it does nothing. Programs are never repaired or replayed.
SDK: await sdk.observe(); await sdk.pressKeys(keys, milliseconds);
await sdk.wait(milliseconds). pressKeys holds 1..3 allowed keys for 30..1500ms,
then releases them; wait accepts 1..3000ms. Use only the task's declared controls.
Coordinates increase right and down. Observation resources, geometry, skill and
item information describe the game; observations and key acknowledgments are
diagnostic, never the authoritative task score. No state editing, shell, imports,
network, assets, account data or undeclared methods are available to the program.
Each response may execute for at most {p['program_seconds']} seconds, reduced after
inference to the original deadline minus 5 seconds. A full 3-second input interval
must fit before any key action. Re-observe inside the program as needed.
At most {p['max_api_requests']} model requests, {p['max_actions']} action attempts and
{p['max_sdk_requests']} SDK requests are available across this trial. Request output
is limited to 3000 tokens. A new request needs at least 15 seconds remaining;
its timeout is min({p['request_timeout_seconds']}, remaining-10) seconds.
The next request includes the last two programs and their last five SDK receipts.
Local variables do not survive between responses. There is no memory from other
trials, reflection run, candidate search, fallback policy or retry after an
uncertain request or input. Exhausted budgets cause passive observation only.
'''


def fresh_observation(value):
    require(isinstance(value, dict) and value.get('ready') is True
            and isinstance(value.get('character'), dict), 'skill_observation_unavailable')
    require(all(type(value.get(k)) in (int, float) and math.isfinite(value[k])
                and 0 <= value[k] < 1500 for k in ('ageMs', 'renderAgeMs')),
            'skill_observation_stale')
    c = value['character']
    require(type(c.get('alive')) is bool and type(c.get('level')) is int
            and c['level'] == 180, 'skill_character_unavailable')
    return value


def run_skill_task(*, run_id, plan_entry_id, execution_manifest_sha256, model,
                   controller_protocol, task_contract, initial, observe,
                   request_api, execute, persist_json, persist_bytes, cancel_check,
                   reserve_request, verified_terminal, on_phase=lambda **_: None,
                   on_step=lambda _: None, clock=time.monotonic,
                   wall_clock=time.time, sleep=time.sleep):
    """Execute one admitted trial, retaining uncertain outcomes without replay.

    reserve_request must durably reserve the maximum dollar charge and reject a
    replay for (execution manifest, plan entry, cycle) before returning. It must
    never recycle an uncertain reservation. verified_terminal reads a trusted,
    immutable verifier artifact and returns its identity/hash, or None. It does
    not consume client assertions. Scoring/closeout remains outside this kernel.
    """
    p = validate_protocol(controller_protocol)
    task_contract = validate_contract(task_contract)
    require(task_contract['purpose'] in ('model-development', 'model-comparative')
            and task_contract['task_id'] == p['task_id'], 'skill_model_contract_required')
    task_descriptor = describe_task(task_contract)
    require(model in MODELS and isinstance(run_id, str) and re.fullmatch('[a-f0-9]{32}', run_id)
            and isinstance(plan_entry_id, str) and re.fullmatch('[a-z0-9][a-z0-9_.-]{0,159}', plan_entry_id)
            and isinstance(execution_manifest_sha256, str) and SHA.fullmatch(execution_manifest_sha256),
            'invalid_skill_trial_identity')
    instructions = prompt(p, task_descriptor)
    fresh_observation(initial)
    counters = {k: 0 for k in ('api_requests_started', 'api_responses_confirmed', 'reserved_tokens',
                              'actual_input_tokens', 'actual_output_tokens', 'actual_total_tokens',
                              'actions', 'action_attempts', 'sdk_requests')}
    trace = {'schema_version': 1, 'protocol': PROTOCOL, 'protocol_sha256': digest(p),
             'run_id': run_id, 'plan_entry_id': plan_entry_id,
             'execution_manifest_sha256': execution_manifest_sha256,
             'requested_model': model, 'limits': p, 'task_contract_sha256': digest(task_contract),
             'status': 'preparing', 'reason': None,
             'timing': {}, 'counters': counters, 'cycles': [], 'terminal_verifier': None,
             'instructions': persist_bytes('skill-task-prompt.txt', instructions.encode())}
    recent, steps, response_ids = [], [], set()
    final, receipt_bytes, started, deadline = initial, 0, None, None

    def offset():
        return None if started is None else round((clock() - started) * 1000)

    def save():
        require(len(encoded(trace)) <= MAX_EVIDENCE_BYTES, 'skill_trace_size_limit')
        persist_json('skill-controller.json', trace)

    def phase(name, cycle):
        on_phase(phase=name, cycle=cycle, deadline=deadline, counters=dict(counters))

    def terminal():
        if not p['early_success_allowed']:
            return False
        receipt = verified_terminal()
        if receipt is None:
            return False
        require(isinstance(receipt, dict) and set(receipt) == {
            'run_id', 'plan_entry_id', 'execution_manifest_sha256', 'status', 'evidence_sha256', 'completion_ms'}
            and all(receipt.get(k) == trace[k] for k in ('run_id', 'plan_entry_id', 'execution_manifest_sha256'))
            and receipt.get('status') == 'success' and isinstance(receipt.get('evidence_sha256'), str)
            and SHA.fullmatch(receipt['evidence_sha256'])
            and type(receipt.get('completion_ms')) in (int, float)
            and 0 <= receipt['completion_ms'] < p['wall_seconds'] * 1000
            and receipt['completion_ms'] <= offset(), 'invalid_skill_terminal_verifier')
        trace['terminal_verifier'] = receipt
        trace.update(status='completed', reason='verified_early_success')
        save()
        return True

    def passive(reason):
        nonlocal final
        trace['passive_reason'] = reason
        phase('waiting_for_deadline', len(trace['cycles']))
        save()
        while clock() < deadline:
            cancel_check()
            if terminal():
                return
            remaining = deadline - clock()
            if remaining > 3:
                final = fresh_observation(observe(3))
                if final['character']['alive'] is False:
                    trace.update(status='completed', reason='death')
                    return
            remaining = deadline - clock()
            if remaining > 0:
                sleep(min(1, remaining))
        trace.update(status='completed', reason=reason)

    try:
        save()
        for index in range(p['max_api_requests']):
            cancel_check()
            if started is not None:
                if terminal():
                    break
                if clock() >= deadline:
                    trace.update(status='completed', reason='wall_time_limit')
                    break
                if counters['action_attempts'] >= p['max_actions']:
                    passive('action_limit'); break
                if counters['sdk_requests'] >= p['max_sdk_requests']:
                    passive('sdk_request_limit'); break
                if not offer(p, deadline-clock())['admitted']:
                    passive('request_window_closed'); break
            current = initial if index == 0 else fresh_observation(observe(min(3, deadline-clock())))
            final = current
            if current['character']['alive'] is False:
                trace.update(status='completed', reason='death'); break
            cycle = {'index': index, 'requested_model': model, 'returned_model': None,
                     'status': 'preparing', 'api_outcome': 'not_started', 'timing': {},
                     'observation': current}
            trace['cycles'].append(cycle)
            prefix = f'cycles/{index:03d}/'
            value = {'task': task_descriptor, 'observation': current, 'recent_programs': recent[-2:],
                     'remaining_seconds': p['wall_seconds'] if started is None else max(0, deadline-clock()),
                     'remaining_actions': p['max_actions']-counters['action_attempts'],
                     'remaining_sdk_requests': p['max_sdk_requests']-counters['sdk_requests'],
                     'cycle_index': index}
            submitted = False

            def provider(url, payload, _key, _timeout):
                nonlocal submitted, started, deadline
                require(not submitted, 'skill_cycle_replay_refused')
                cancel_check()
                body = payload | {'service_tier': 'default', 'metadata': {
                    'maplebench_run_id': run_id, 'maplebench_plan_entry_id': plan_entry_id,
                    'maplebench_manifest': execution_manifest_sha256, 'maplebench_cycle_index': str(index)}}
                reservation = len(encoded(body)) + 1024 + p['max_output_tokens']
                if counters['reserved_tokens'] + reservation > p['max_total_tokens']:
                    raise SkillControllerError('skill_token_reservation_limit')
                cycle['request'] = persist_json(prefix+'api-request.json', body)
                if started is not None and not offer(p, deadline-clock())['admitted']:
                    raise SkillControllerError('skill_request_window_closed')
                cycle['dollar_reservation'] = reserve_request(
                    plan_entry_id=plan_entry_id, execution_manifest_sha256=execution_manifest_sha256,
                    cycle=index, model=model, input_token_upper_bound=reservation-p['max_output_tokens'],
                    output_token_upper_bound=p['max_output_tokens'])
                # Durable intent precedes dispatch; a lost reply never permits replay.
                submitted = True
                counters['api_requests_started'] += 1
                counters['reserved_tokens'] += reservation
                cycle.update(status='requesting', api_outcome='uncertain', token_reservation=reservation)
                save()
                if started is None:
                    started = clock()
                    deadline = started + p['wall_seconds']
                    wall_started = round(wall_clock()*1000)
                    trace['timing'].update(wall_started_at_ms=wall_started,
                        wall_deadline_at_ms=wall_started+p['wall_seconds']*1000)
                phase('requesting', index)
                slot = offer(p, deadline-clock())
                if not slot['admitted']:
                    # Intent stays reserved although dispatch is known not to occur.
                    cycle['api_outcome'] = 'not_dispatched_window_closed'
                    raise SkillControllerError('skill_request_window_closed')
                cycle['timing']['api_started_ms'] = offset()
                cycle['request_timeout_seconds'] = slot['request_timeout_seconds']
                save()
                slot = offer(p, deadline-clock())
                if not slot['admitted']:
                    cycle['api_outcome'] = 'not_dispatched_window_closed'
                    raise SkillControllerError('skill_request_window_closed')
                cycle['request_timeout_seconds'] = slot['request_timeout_seconds']
                response = request_api(url, body, slot['request_timeout_seconds'])
                cycle['timing']['api_ended_ms'] = offset()
                cycle['response'] = persist_json(prefix+'api-response.json', response)
                cycle['api_outcome'] = 'receipt_saved'
                save()
                require(isinstance(response, dict) and response.get('metadata') == body['metadata'],
                        'skill_api_identity_mismatch')
                require(cycle['timing']['api_ended_ms']-cycle['timing']['api_started_ms']
                        <= slot['request_timeout_seconds']*1000+1, 'skill_provider_timeout_overrun')
                return response

            try:
                choice, meta = model_decision(model, instructions, value, None,
                    output_tokens=p['max_output_tokens'], timeout=p['request_timeout_seconds'], request_fn=provider)
            except SkillControllerError as error:
                if str(error) in ('skill_token_reservation_limit', 'skill_request_window_closed') and started is not None:
                    passive(str(error)); break
                raise
            response_id = meta.get('id')
            require(isinstance(response_id, str) and 0 < len(response_id) <= 200 and response_id not in response_ids,
                    'skill_api_response_identity_invalid')
            response_ids.add(response_id)
            cycle.update(response_id=response_id, returned_model=meta.get('model'), usage=meta.get('usage'))
            require(meta.get('model') == model, 'skill_api_model_mismatch')
            usage = meta.get('usage')
            require(isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] >= 0
                for k in ('input_tokens', 'output_tokens', 'total_tokens'))
                and usage['input_tokens'] + usage['output_tokens'] == usage['total_tokens'], 'skill_api_usage_invalid')
            require(usage['output_tokens'] <= p['max_output_tokens']
                and usage['input_tokens'] <= cycle['token_reservation']-p['max_output_tokens']
                and usage['total_tokens'] <= cycle['token_reservation']
                and counters['actual_total_tokens']+usage['total_tokens'] <= p['max_total_tokens'],
                'skill_actual_token_limit')
            for key in ('input_tokens', 'output_tokens', 'total_tokens'):
                counters['actual_'+key] += usage[key]
            counters['api_responses_confirmed'] += 1
            cycle.update(api_outcome='confirmed', status='response_received')
            save()
            if terminal():
                break
            if choice is None:
                cycle['status'] = 'invalid_program'
                recent.append({'error': 'Response incomplete or invalid; no code executed.'})
                continue
            code = choice['code']
            cycle['program'] = persist_bytes(prefix+'program.js', code.encode())
            cycle['choice'] = persist_json(prefix+'program.json', choice)
            remaining = deadline-p['settlement_seconds']-clock()
            if remaining < p['input_ack_budget_seconds']:
                passive('execution_window_closed'); break
            final = fresh_observation(observe(min(3, remaining)))
            if final['character']['alive'] is False:
                trace.update(status='completed', reason='death'); break
            cycle_steps = []

            def record(step):
                nonlocal receipt_bytes
                receipt_bytes += len(encoded(step))
                require(receipt_bytes <= MAX_EVIDENCE_BYTES, 'skill_sdk_evidence_size_limit')
                cycle_steps.append(step)
                steps.append(dict(step, cycle_index=index))
                on_step(step)

            execution_deadline = deadline-p['settlement_seconds']
            cycle.update(status='running', execution_deadline_ms=p['wall_seconds']*1000-5000)
            cycle['timing']['program_started_ms'] = offset()
            save()
            phase('running', index)
            program_seconds = min(p['program_seconds'], execution_deadline-clock())
            if program_seconds < p['input_ack_budget_seconds']:
                passive('execution_window_closed'); break
            execution = execute(code, deadline=execution_deadline, program_seconds=program_seconds,
                max_actions=value['remaining_actions'], max_requests=value['remaining_sdk_requests'], step_callback=record)
            cycle['timing']['program_ended_ms'] = offset()
            cycle['execution'] = execution
            cycle['execution_receipt'] = persist_json(prefix+'execution.json', execution)
            require(isinstance(execution, dict) and execution.get('steps') == cycle_steps,
                    'skill_execution_receipts_mismatch')
            acknowledged = sum(s.get('kind') == 'sdk' and s.get('method') == 'pressKeys'
                               and s.get('result', {}).get('accepted') is True for s in cycle_steps)
            require(type(execution.get('actions')) is int and execution['actions'] == acknowledged
                and type(execution.get('actionAttempts')) is int
                and acknowledged <= execution['actionAttempts'] <= value['remaining_actions']
                and type(execution.get('rpcRequests')) is int
                and len(cycle_steps) <= execution['rpcRequests'] <= value['remaining_sdk_requests'],
                'skill_execution_counters_mismatch')
            counters['actions'] += acknowledged
            counters['action_attempts'] += execution['actionAttempts']
            counters['sdk_requests'] += execution['rpcRequests']
            require(not any(s.get('kind') == 'sdk_error' or s.get('method') == 'pressKeys'
                and s.get('kind') == 'sdk' and s.get('result', {}).get('accepted') is not True for s in cycle_steps),
                'skill_input_receipt_uncertain')
            require(execution.get('reason') not in ('infrastructure_error', 'replaced'), 'skill_execution_unavailable')
            cycle['status'] = 'executed'
            save()
            if execution.get('reason') == 'death':
                trace.update(status='completed', reason='death'); break
            recent.append({'note': choice['note'][:240], 'code': code,
                'execution': {k: execution.get(k) for k in ('reason', 'error', 'actions', 'actionAttempts', 'rpcRequests')},
                'recent_receipts': cycle_steps[-5:]})
        else:
            passive('api_request_limit')
    except Exception as error:
        trace.update(status='failed', reason=str(error) if isinstance(error, SkillControllerError) else type(error).__name__)
    finally:
        trace['timing']['controller_ended_ms'] = offset()
        if started is not None:
            trace['timing']['wall_elapsed_ms'] = min(p['wall_seconds']*1000, offset())
            trace['timing']['cleanup_overrun_ms'] = max(0, offset()-p['wall_seconds']*1000)
        save()
    return {'trace': trace, 'initial': initial, 'final': final, 'steps': steps}
