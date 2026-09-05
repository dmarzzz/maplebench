#!/usr/bin/env python3
"""OpenAI code controller; trusted HTTP proxy around disposable Docker programs.

The queue owns scenario resets, recording, and server-authoritative scoring.
Generated JavaScript never runs in the Python worker or a host Node process.
"""
import json
import math
import os
from pathlib import Path
import select
import selectors
import shlex
import subprocess
import sys
import time
import urllib.parse
import uuid

MODELS = ('gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna')
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_LINE_BYTES = 16384
MAX_PROGRAM_OUTPUT = 131072
SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {'note': {'type': 'string'}, 'code': {'type': 'string'}},
    'required': ['note', 'code'],
}
PROMPT = '''You control a character in an offline MapleStory v83 simulation.
Write a short JavaScript async function body using the provided frozen `sdk`.
It may contain loops, local variables, and console.log. Top-level await works.
SDK methods (all return promises):
  sdk.observe() -> current character, monsters, drops, and inventory
  sdk.moveTo(x, y) -> movement action receipt; movement continues over time
  sdk.attack(targetId) -> basic attack receipt
  sdk.useSkill(skillId, targetId) -> learned skill action receipt
  sdk.useItem(itemId) -> consume an inventory item allowed by the scenario
  sdk.wait(milliseconds) -> wait 1..3000 milliseconds
Action receipts have accepted, error, and usually observation. Only supplied
scenario skill IDs may be used. Select targets from observed monster objectId.
Coordinates increase rightward/downward. Follow actual footholds and allow
movement/attack cooldown time; accepted movement does not mean arrival.
Aim to achieve the scenario objective while remaining alive. Your program is
replaced by your next response; local variables do not survive. Re-observe
inside loops. Return before the program deadline; you may issue fewer actions.
The container has no network, secrets, game assets, or host files. Access the
game only through sdk. No reset, stat editing, admin, or automatic grind API
exists. Do not attempt shell execution, imports, or protocol manipulation.
Return JSON with code and a short note describing intended actions, not private
reasoning. Wall-clock game time includes model/API latency; the game is live
while you think. Score comes from server events, never from your own output.'''

# Credentials go through stdin to this trusted helper, never argv or Docker.
# Reading a bounded response and subprocess timeout impose a wall-clock bound
# even if a remote peer trickles bytes indefinitely (socket timeouts do not).
HTTP_WORKER = r'''
import json, sys, urllib.request, urllib.error
try:
    value = json.load(sys.stdin)
    headers = {'Content-Type': 'application/json'}
    if value.get('key'): headers['Authorization'] = 'Bearer ' + value['key']
    body = value.get('payload')
    req = urllib.request.Request(value['url'], data=None if body is None else json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=value['timeout']) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024: raise ValueError()
    print(json.dumps({'ok': True, 'value': json.loads(raw)}))
except urllib.error.HTTPError as error:
    print(json.dumps({'ok': False, 'error': 'HTTP ' + str(error.code)}))
except Exception:
    print(json.dumps({'ok': False, 'error': 'Request failed'}))
'''


class AgentError(RuntimeError):
    pass


class BudgetLimit(AgentError):
    pass


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def bounded_request(url, payload=None, key=None, timeout=20):
    if timeout <= 0:
        raise TimeoutError('Request deadline reached')
    encoded = json.dumps({'url': url, 'payload': payload, 'key': key, 'timeout': timeout}).encode()
    try:
        result = subprocess.run([sys.executable, '-c', HTTP_WORKER], input=encoded,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise TimeoutError('Request deadline reached') from None
    try:
        envelope = json.loads(result.stdout)
        if result.returncode or not envelope['ok']:
            raise AgentError(envelope.get('error', 'Request failed'))
        return envelope['value']
    except (ValueError, KeyError, TypeError):
        raise AgentError('Invalid endpoint response') from None


def validate_base_url(base_url):
    parsed = urllib.parse.urlsplit(base_url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username or parsed.password or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment):
        raise ValueError('Game endpoint must be a localhost HTTP origin')
    return base_url.rstrip('/')


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid ' + label)
    return value


def allowed_skills(scenario):
    values = scenario.get('allowed_skills', scenario.get('allowedSkillIds', scenario.get('allowed_skill_ids', [])))
    return {_integer(value, 1, 99999999, 'scenario skill ID') for value in values}


def validate_rpc(message, scenario):
    """Return (method, translated server action or delay); no dynamic dispatch."""
    if not isinstance(message, dict) or set(message) != {'type', 'id', 'method', 'args'} or message['type'] != 'rpc':
        raise ValueError('Invalid SDK request envelope')
    _integer(message['id'], 1, 10000, 'SDK request ID')
    method, args = message['method'], message['args']
    if type(method) is not str or type(args) is not list:
        raise ValueError('Invalid SDK request')
    if method == 'observe' and not args:
        return method, None
    if method == 'wait' and len(args) == 1:
        return method, _integer(args[0], 1, 3000, 'wait duration')
    if method == 'moveTo' and len(args) == 2:
        bounds = scenario.get('coordinate_bounds', {})
        x = _integer(args[0], max(-10000, bounds.get('min_x', -10000)), min(10000, bounds.get('max_x', 10000)), 'x coordinate')
        y = _integer(args[1], max(-5000, bounds.get('min_y', -5000)), min(5000, bounds.get('max_y', 5000)), 'y coordinate')
        action = {'type': 'move_to', 'position': {'x': x, 'y': y}}
    elif method == 'attack' and len(args) == 1:
        action = {'type': 'basic_attack', 'targetId': _integer(args[0], 1, 2147483647, 'target ID')}
    elif method == 'useSkill' and len(args) == 2:
        skill = _integer(args[0], 1, 99999999, 'skill ID')
        if skill not in allowed_skills(scenario):
            raise ValueError('Skill is not allowed in this scenario')
        action = {'type': 'use_skill', 'skillId': skill, 'targetId': _integer(args[1], 1, 2147483647, 'target ID')}
    elif method == 'useItem' and len(args) == 1:
        item = _integer(args[0], 1, 99999999, 'item ID')
        items = scenario.get('allowed_items', [])
        if item not in {_integer(value, 1, 99999999, 'scenario item ID') for value in items}:
            raise ValueError('Item is not allowed in this scenario')
        action = {'type': 'use_item', 'itemId': item}
    else:
        raise ValueError('SDK method or arguments are not allowed')
    actions = scenario.get('allowedActions', scenario.get('allowed_actions', ['move_to', 'basic_attack', 'use_skill', 'use_item']))
    if action['type'] not in actions:
        raise ValueError('Action is not allowed in this scenario')
    return method, action


def docker_prefix():
    # Operator configuration only; never supplied by generated code or scenario.
    prefix = shlex.split(os.environ.get('MAPLEBENCH_DOCKER_COMMAND', 'docker'))
    if not prefix:
        raise ValueError('Empty Docker command')
    return prefix


def docker_command(image, container_name, program_seconds):
    if not isinstance(image, str) or not image or image.startswith('-'):
        raise ValueError('Invalid sandbox image')
    script = Path(__file__).with_name('agent-sandbox.mjs').read_text()
    return docker_prefix() + ['run', '--rm', '--pull=never', '--name', container_name, '-i',
            '--network=none', '--read-only', '--cap-drop=ALL',
            '--security-opt=no-new-privileges:true', '--user=65534:65534',
            '--cpus=0.5', '--memory=256m', '--memory-swap=256m', '--pids-limit=32',
            '--ulimit=nofile=64:64', '--stop-timeout=1', '--log-driver=none',
            '--entrypoint=/usr/bin/timeout', image, '--signal=KILL',
            str(math.ceil(program_seconds + 1)), '/usr/local/bin/node',
            '--max-old-space-size=96', '--input-type=module', '-e', script]


def _write_packet(pipe, value, deadline):
    data = memoryview((json.dumps(value) + '\n').encode())
    if len(data) > MAX_RESPONSE_BYTES:
        raise AgentError('SDK response exceeded size limit')
    while data:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([], [pipe], [], remaining)[1]:
            raise TimeoutError('Program deadline reached')
        try:
            written = os.write(pipe.fileno(), data)
            data = data[written:]
        except BlockingIOError:
            continue


def execute_program(code, scenario, base_url, *, deadline, max_actions=500,
                    program_seconds=15, docker_image='node:22.19.0-bookworm-slim',
                    request_fn=bounded_request, step_callback=None, stop_when=None):
    """Run untrusted code in Docker and proxy its validated, bounded SDK calls."""
    if not isinstance(code, str) or not code.strip() or len(code) > 12000:
        raise ValueError('Invalid program size')
    base_url = validate_base_url(base_url)
    end = min(deadline, time.monotonic() + program_seconds)
    remaining = end - time.monotonic()
    if remaining <= 0:
        return {'reason': 'time_limit', 'actions': 0, 'error': None, 'steps': []}
    name = 'maplebench-agent-' + uuid.uuid4().hex
    command = docker_command(docker_image, name, remaining)
    # No OPENAI_API_KEY or other inherited credential reaches the Docker CLI.
    # The container receives only image defaults; no --env/volume/socket mounts.
    cli_env = {key: os.environ[key] for key in ('PATH', 'HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'XDG_RUNTIME_DIR') if key in os.environ}
    process = None
    selector = selectors.DefaultSelector()
    steps, logs, actions, rpc_count, output_bytes = [], [], 0, 0, 0
    seen_ids = set()
    buffer = b''
    outcome = {'reason': 'program_error', 'error': 'Sandbox exited without completion'}

    def record(step):
        steps.append(step)
        if step_callback:
            step_callback(step)

    try:
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, env=cli_env, bufsize=0)
        except OSError:
            raise AgentError('Docker sandbox could not start') from None
        for pipe in (process.stdin, process.stdout, process.stderr):
            os.set_blocking(pipe.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
        selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
        _write_packet(process.stdin, {'type': 'init', 'code': code, 'timeoutMs': max(1, int(remaining * 1000))}, end)
        finished = False
        while not finished:
            if time.monotonic() >= end:
                outcome = {'reason': 'time_limit' if end == deadline else 'program_timeout', 'error': None}
                break
            ready = selector.select(min(0.1, end - time.monotonic()))
            if not ready and process.poll() is not None:
                if process.returncode in (125, 126, 127):
                    outcome = {'reason': 'infrastructure_error', 'error': 'Docker image or runtime unavailable'}
                break
            for key, _ in ready:
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output_bytes += len(chunk)
                if output_bytes > MAX_PROGRAM_OUTPUT:
                    outcome = {'reason': 'output_limit', 'error': 'Sandbox output limit reached'}
                    finished = True; break
                if key.data == 'stderr':
                    # Never persist runtime stderr; Docker errors may name hosts.
                    continue
                buffer += chunk
                if len(buffer.split(b'\n')[-1]) > MAX_LINE_BYTES:
                    raise AgentError('Sandbox protocol line exceeded size limit')
                while b'\n' in buffer:
                    raw, buffer = buffer.split(b'\n', 1)
                    if len(raw) > MAX_LINE_BYTES:
                        raise AgentError('Sandbox protocol line exceeded size limit')
                    try:
                        message = json.loads(raw)
                    except (ValueError, UnicodeDecodeError):
                        raise AgentError('Invalid sandbox protocol') from None
                    if not isinstance(message, dict):
                        raise AgentError('Invalid sandbox protocol')
                    kind = message.get('type')
                    if kind == 'log':
                        if len(logs) < 16 and isinstance(message.get('text'), str):
                            logs.append(message['text'][:1024])
                        continue
                    if kind == 'done':
                        outcome = {'reason': 'program_complete' if message.get('ok') is True else 'program_error',
                                   'error': None if message.get('ok') is True else str(message.get('error', 'Program failed'))[:512]}
                        finished = True; break
                    rpc_count += 1
                    if rpc_count > 100:
                        outcome = {'reason': 'rpc_limit', 'error': 'Program SDK request limit reached'}
                        finished = True; break
                    rpc_id = message.get('id')
                    try:
                        method, action = validate_rpc(message, scenario)
                        if rpc_id in seen_ids:
                            raise ValueError('SDK request ID was reused')
                        seen_ids.add(rpc_id)
                    except ValueError as error:
                        record({'kind': 'rejected_rpc', 'error': str(error)})
                        # Invalid IDs cannot be safely correlated with the JS SDK.
                        if type(rpc_id) is not int or not 1 <= rpc_id <= 10000:
                            raise AgentError('Invalid SDK request ID') from None
                        _write_packet(process.stdin, {'id': rpc_id, 'ok': False, 'error': str(error)}, end)
                        continue
                    if method not in ('observe', 'wait') and actions >= max_actions:
                        outcome = {'reason': 'action_limit', 'error': None}
                        finished = True; break
                    left = end - time.monotonic()
                    if left <= 0:
                        raise TimeoutError('Program deadline reached')
                    if method == 'wait':
                        delay = min(action / 1000, left)
                        time.sleep(delay)
                        result = {'waitedMs': round(delay * 1000)}
                    elif method == 'observe':
                        result = request_fn(base_url + '/v1/observe', timeout=min(3, left))
                    else:
                        actions += 1
                        result = request_fn(base_url + '/v1/action', action, timeout=min(3, left))
                    step = {'kind': 'sdk', 'method': method, 'args': message['args'], 'result': result}
                    record(step)
                    obs = result if method == 'observe' else result.get('observation', {}) if isinstance(result, dict) else {}
                    if obs.get('character', {}).get('alive') is False:
                        outcome = {'reason': 'death', 'error': None}; finished = True; break
                    if stop_when and obs.get('character') and stop_when(obs):
                        outcome = {'reason': 'completed', 'error': None}; finished = True; break
                    _write_packet(process.stdin, {'id': rpc_id, 'ok': True, 'result': result}, end)
                if finished:
                    break
    except TimeoutError:
        outcome = {'reason': 'time_limit' if time.monotonic() >= deadline else 'program_timeout', 'error': None}
    except (AgentError, BrokenPipeError, OSError) as error:
        outcome = {'reason': 'infrastructure_error' if process is None else 'program_error',
                   'error': str(error) if isinstance(error, AgentError) else 'Sandbox pipe closed'}
    finally:
        selector.close()
        if process is not None:
            for pipe in (process.stdin, process.stdout, process.stderr):
                pipe.close()
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=2)
            # Also kill the daemon-owned container, including forked children.
            try:
                subprocess.run(docker_prefix() + ['rm', '-f', name], env=cli_env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=3, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass  # Its independent GNU timeout still applies.
    return outcome | {'actions': actions, 'steps': steps, 'logs': logs}


def model_decision(model, instructions, input_value, api_key, *, output_tokens, timeout, request_fn=bounded_request):
    body = {'model': model, 'store': False, 'reasoning': {'effort': 'low'},
            'instructions': instructions, 'input': json.dumps(input_value), 'max_output_tokens': output_tokens,
            'text': {'format': {'type': 'json_schema', 'name': 'maple_program', 'strict': True, 'schema': SCHEMA}}}
    response = request_fn('https://api.openai.com/v1/responses', body, api_key, timeout)
    meta = {key: response.get(key) for key in ('id', 'model', 'usage', 'service_tier', 'status')}
    if response.get('status') != 'completed':
        return None, meta
    text = ''.join(content.get('text', '') for item in response.get('output', []) if item.get('type') == 'message'
                   for content in item.get('content', []) if content.get('type') == 'output_text')
    try:
        choice = json.loads(text)
        if (set(choice) != {'note', 'code'} or type(choice['note']) is not str or type(choice['code']) is not str
                or not 0 < len(choice['code']) <= 12000 or len(choice['note']) > 2000):
            return None, meta
    except (TypeError, ValueError):
        return None, meta
    return choice, meta


def run_agent(model, scenario, base_url, api_key, output_dir, *, max_calls=12,
              max_output_tokens=1800, max_total_tokens=30000, wall_seconds=90,
              program_seconds=15, max_actions=500, docker_image='node:22.19.0-bookworm-slim',
              on_decision=None, stop_when=None, request_fn=bounded_request,
              execute_fn=execute_program):
    """Run one already-reset trial. Callback returning False stops for budget.

    on_decision receives each persisted decision including response.usage before
    executing its code. Callback BudgetLimit exceptions also stop cleanly.
    SDK steps are flushed to steps.jsonl after each request for crash recovery.
    """
    if model not in MODELS:
        raise ValueError('Model is not in the OpenAI API comparison set')
    base_url = validate_base_url(base_url)
    for value, low, high, label in ((max_calls, 1, 1000, 'API call budget'),
                                   (max_output_tokens, 256, 10000, 'output token budget'),
                                   (max_total_tokens, 1024, 10000000, 'total token budget'),
                                   (max_actions, 1, 10000, 'action budget')):
        _integer(value, low, high, label)
    if not 1 <= wall_seconds <= 3600 or not 1 <= program_seconds <= 60:
        raise ValueError('Invalid time budget')
    allowed_skills(scenario)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    # Send only public scenario fields; runner configuration may contain paths.
    public_scenario = {key: scenario[key] for key in ('id', 'name', 'description', 'objective',
                       'allowed_skills', 'allowedSkillIds', 'allowed_skill_ids', 'allowed_items', 'skills', 'character',
                       'coordinate_bounds', 'allowed_actions', 'allowedActions') if key in scenario}
    instructions = PROMPT + '\nScenario: ' + json.dumps(public_scenario) + '\nProgram limit: ' + str(program_seconds) + ' seconds.'
    controller = {'name': 'OpenAI Responses API (programmable SDK)', 'model': model,
                  'reasoning': 'low', 'scenario': scenario.get('id', 'unknown'),
                  'inference': 'api.openai.com', 'sandbox': 'Docker; no network; no credentials',
                  'limits': {'calls': max_calls, 'outputTokensPerCall': max_output_tokens,
                             'totalTokens': max_total_tokens, 'wallSeconds': wall_seconds,
                             'programSeconds': program_seconds, 'actions': max_actions}}
    write_json(out / 'controller.json', controller)
    (out / 'prompt.txt').write_text(instructions + '\n')
    decisions, recent, usages = [], [], []
    started = time.monotonic()
    deadline = started + wall_seconds
    token_count = actions = api_requests_started = 0
    reason, failure = 'decision_limit', None

    with (out / 'steps.jsonl').open('a', buffering=1) as step_file:
        def persist_step(step):
            step_file.write(json.dumps({'turn': len(decisions) - 1} | step) + '\n')
            step_file.flush()

        try:
            for turn in range(max_calls):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = 'time_limit'; break
                obs = request_fn(base_url + '/v1/observe', timeout=min(3, remaining))
                if obs.get('character', {}).get('alive') is False:
                    reason = 'death'; break
                if stop_when and stop_when(obs):
                    reason = 'completed'; break
                if actions >= max_actions:
                    reason = 'action_limit'; break
                input_value = {'observation': obs, 'recent_programs': recent[-2:],
                               'remainingSeconds': round(deadline - time.monotonic(), 2),
                               'remainingActions': max_actions - actions}
                # A conservative UTF-8 byte bound avoids another API call when
                # remaining tokens cannot cover its input plus capped output.
                reservation = len((instructions + json.dumps(input_value) + json.dumps(SCHEMA)).encode()) + max_output_tokens + 1024
                if token_count + reservation > max_total_tokens:
                    reason = 'budget_limit'; break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = 'time_limit'; break
                before = time.monotonic()
                api_requests_started += 1
                choice, metadata = model_decision(model, instructions, input_value, api_key,
                                                 output_tokens=max_output_tokens, timeout=min(45, remaining), request_fn=request_fn)
                usage = metadata.get('usage') or {}
                measured = usage.get('total_tokens', usage.get('input_tokens', 0) + usage.get('output_tokens', 0))
                # Missing usage cannot silently evade the configured budget.
                consumed = measured if type(measured) is int and measured > 0 else reservation
                token_count += consumed
                usages.append(usage)
                decision = {'turn': turn, 'tMs': obs.get('nowMs'),
                            'latencyMs': round((time.monotonic() - before) * 1000),
                            'choice': choice, 'response': metadata, 'accountedTokens': consumed}
                decisions.append(decision)
                write_json(out / 'decisions.json', decisions)
                if on_decision and on_decision(decision) is False:
                    reason = 'budget_limit'; break
                if token_count >= max_total_tokens:
                    reason = 'budget_limit'; break
                if time.monotonic() >= deadline:
                    reason = 'time_limit'; break
                if choice is None:
                    recent.append({'error': 'Model response incomplete or invalid; return a shorter complete program.'})
                    continue
                result = execute_fn(choice['code'], scenario, base_url, deadline=deadline,
                                    max_actions=max_actions - actions, program_seconds=program_seconds,
                                    docker_image=docker_image, request_fn=request_fn,
                                    step_callback=persist_step, stop_when=stop_when)
                actions += result['actions']
                decision['execution'] = {key: result[key] for key in ('reason', 'error', 'actions', 'logs') if key in result}
                write_json(out / 'decisions.json', decisions)
                recent.append({'note': choice['note'][:240], 'code': choice['code'],
                               'result': decision['execution'],
                               'recent_receipts': [dict(method=s.get('method'), args=s.get('args'),
                                   accepted=s.get('result', {}).get('accepted'), error=s.get('result', {}).get('error'))
                                   for s in result.get('steps', [])[-5:] if isinstance(s.get('result'), dict)]})
                if result['reason'] in ('death', 'completed', 'time_limit', 'action_limit', 'infrastructure_error'):
                    reason, failure = result['reason'], result.get('error'); break
        except BudgetLimit:
            reason = 'budget_limit'
        except TimeoutError:
            reason = 'time_limit' if time.monotonic() >= deadline else 'infrastructure_error'
            failure = None if reason == 'time_limit' else 'Endpoint request timed out'
        except Exception as error:
            reason = 'infrastructure_error'
            failure = str(error) if isinstance(error, AgentError) else type(error).__name__
    result = {'reason': reason, 'error': failure, 'decisions': len(decisions),
              'apiUsage': usages, 'accountedTokens': token_count, 'actions': actions,
              'apiRequestsStarted': api_requests_started,
              'usage_complete': api_requests_started == len(usages) and all(
                  type(usage.get('total_tokens')) is int and usage['total_tokens'] > 0 for usage in usages),
              'durationMs': round((time.monotonic() - started) * 1000), 'controller': controller}
    write_json(out / 'agent-result.json', result)
    return result
