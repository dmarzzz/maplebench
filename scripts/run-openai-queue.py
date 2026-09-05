#!/usr/bin/env python3
"""Bounded, serialized OpenAI API experiments against the dedicated Cosmic service.

Only model-produced game primitives reach the bridge. No shell/code tool is
offered to a model. Credentials and run artifacts are never part of the repo.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.error
import urllib.request

MODELS = ['gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna']
PROMPT = '''You control a level-15 Warrior in a real MapleStory v83 simulation.
Earn XP by defeating the three Slimes, while staying alive. You have a sword
and level-1 Power Strike (skillId 1001004). Choose every target and primitive.
There is no automatic grinding, targeting, or skill-selection policy.
Coordinates use x rightward and y downward; ground here is y=334. A Slime's
position has y=333. Move to a reachable ground point near a target; a basic
sword attack needs approximately 50 pixels horizontal range. Movement takes
time (roughly 70 pixels/second) and attacks have an animation cooldown.
You may request up to three primitives at once, each with a wait afterward.
Use observed objectId values as targetId. Move using x,y; unused fields must
be null. wait does nothing except wait. Never invent a target or change stats.
Return JSON matching the schema. The note is a brief action intention, not
private reasoning. You receive the current observation and recent outcomes.
The run ends after all monsters die, 90 seconds, or 12 API decisions.'''

SCHEMA = {'type': 'object', 'additionalProperties': False,
          'properties': {'note': {'type': 'string'}, 'actions': {
              'type': 'array', 'minItems': 1, 'maxItems': 3, 'items': {
                  'type': 'object', 'additionalProperties': False,
                  'properties': {
                      'type': {'type': 'string', 'enum': ['move_to', 'basic_attack', 'use_skill', 'wait']},
                      'x': {'type': ['integer', 'null']}, 'y': {'type': ['integer', 'null']},
                      'targetId': {'type': ['integer', 'null']}, 'skillId': {'type': ['integer', 'null']},
                      'waitMs': {'type': 'integer', 'minimum': 100, 'maximum': 3000}},
                  'required': ['type', 'x', 'y', 'targetId', 'skillId', 'waitMs']}}},
          'required': ['note', 'actions']}


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def request(url, payload=None, key=None, timeout=20):
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    req = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # Avoid emitting response bodies containing account information.
        raise RuntimeError(f'HTTP {error.code} from request endpoint') from None


def model_decision(model, observation, recent, key, timeout=35):
    body = {'model': model, 'store': False, 'reasoning': {'effort': 'low'},
            'max_output_tokens': 1400,
            'instructions': PROMPT,
            'input': json.dumps({'observation': observation, 'recent_outcomes': recent[-5:]}),
            'text': {'format': {'type': 'json_schema', 'name': 'maple_actions', 'strict': True, 'schema': SCHEMA}}}
    response = request('https://api.openai.com/v1/responses', body, key, timeout)
    if response.get('status') != 'completed':
        raise RuntimeError('OpenAI response was not completed')
    text = ''.join(c.get('text', '') for item in response.get('output', [])
                   if item.get('type') == 'message' for c in item.get('content', [])
                   if c.get('type') == 'output_text')
    return json.loads(text), {k: response.get(k) for k in ['id', 'model', 'usage', 'service_tier']}


def translate_action(action):
    kind = action['type']
    delay = action['waitMs']
    if type(delay) is not int or not 100 <= delay <= 3000:
        raise ValueError('Invalid action delay')
    if kind == 'wait':
        return None, delay
    if kind == 'move_to':
        x, y = action['x'], action['y']
        if type(x) is not int or type(y) is not int or not (-10000 <= x <= 10000 and -5000 <= y <= 5000):
            raise ValueError('Invalid movement coordinates')
        return {'type': kind, 'position': {'x': x, 'y': y}}, delay
    if kind not in ['basic_attack', 'use_skill'] or type(action['targetId']) is not int or action['targetId'] <= 0:
        raise ValueError('Invalid attack')
    result = {'type': kind, 'targetId': action['targetId']}
    if kind == 'use_skill':
        if action['skillId'] != 1001004:
            raise ValueError('Skill is not part of this scenario')
        result['skillId'] = action['skillId']
    return result, delay


def reset_scenario(base):
    # This harness is explicitly for the dedicated disposable MapleBench DB/service.
    subprocess.run(['sudo', '-n', 'systemctl', 'stop', 'maplebench-cosmic'], check=True, timeout=40)
    subprocess.run(['sudo', '-n', 'mysql', 'maplebench', '-e',
                    "UPDATE characters SET level=15, exp=0, hp=500, mp=100, maxhp=500, maxmp=100, "
                    "job=100, str=70, dex=15, luk=4, `int`=4, map=100000000 WHERE name='Agent01';"],
                   check=True, timeout=20, stdout=subprocess.DEVNULL)
    subprocess.run(['sudo', '-n', 'systemctl', 'start', 'maplebench-cosmic'], check=True, timeout=20)
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        try:
            obs = request(base + '/v1/observe', timeout=2)
            c = obs['character']
            if c['mapId'] == 100000000 and c['level'] == 15 and c['exp'] == 0 and c['hp'] == 500 and len(obs['monsters']) == 3:
                return obs
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError('Dedicated scenario did not become ready with expected initial state')


def run_model(model, out, base, key):
    initial = reset_scenario(base)
    out.mkdir(parents=True, exist_ok=True)
    controller = {'name': 'OpenAI Responses API', 'model': model, 'reasoning': 'low',
                  'scenario': 'henesys-slimes-warrior-v1', 'inference': 'api.openai.com'}
    write_json(out / 'controller.json', controller)
    (out / 'prompt.txt').write_text(PROMPT)
    observations, errors, recent, decisions = [initial], [], [], []
    done = threading.Event()

    def record():
        while not done.wait(0.1):
            try:
                observations.append(request(base + '/v1/observe', timeout=2))
            except Exception as error:
                errors.append({'kind': 'observation', 'error': type(error).__name__})

    recorder = threading.Thread(target=record, daemon=True)
    recorder.start()
    started = time.monotonic()
    failure = None
    reason = 'time_limit'
    try:
        for turn in range(12):
            obs = request(base + '/v1/observe')
            if not obs['character']['alive']:
                reason = 'death'; break
            if not any(m['alive'] for m in obs['monsters']):
                reason = 'completed'; break
            remaining = 90 - (time.monotonic() - started)
            if remaining <= 0:
                break
            before = time.monotonic()
            choice, meta = model_decision(model, obs, recent, key, timeout=max(1, min(35, remaining)))
            decision = {'turn': turn, 'tMs': obs['nowMs'], 'latencyMs': round((time.monotonic() - before) * 1000),
                        'choice': choice, 'response': meta}
            decisions.append(decision)
            write_json(out / 'decisions.json', decisions)
            for raw in choice['actions'][:3]:
                if time.monotonic() - started >= 90:
                    break
                action, delay = translate_action(raw)
                outcome = {'type': 'wait', 'accepted': True} if action is None else request(base + '/v1/action', action)
                recent.append({'action': action, 'accepted': outcome.get('accepted'), 'error': outcome.get('error'),
                               'exp': outcome.get('observation', {}).get('character', {}).get('exp')})
                time.sleep(min(delay / 1000, max(0, 90 - (time.monotonic() - started))))
        else:
            reason = 'decision_limit'
    except Exception as error:
        failure = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        reason = 'error'
    finally:
        time.sleep(1)
        done.set(); recorder.join(timeout=3)
    observations.append(request(base + '/v1/observe'))
    events = request(base + '/v1/events?since_seq=0')
    write_json(out / 'observations.json', observations)
    (out / 'episode.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
    final = observations[-1]['character']
    score = {'model': model, 'controller': controller, 'reason': reason, 'error': failure,
             'durationMs': round((time.monotonic() - started) * 1000), 'decisions': len(decisions),
             'xpGainedThisRun': sum(e['amount'] for e in events if e['kind'] == 'xp_gain'),
             'finalHp': final['hp'], 'alive': final['alive'],
             'accepted': sum(e['accepted'] for e in events if e['kind'] == 'action'),
             'rejected': sum(not e['accepted'] for e in events if e['kind'] == 'action'),
             'observationErrors': len(errors), 'apiUsage': [d['response']['usage'] for d in decisions]}
    write_json(out / 'score.json', score)
    return score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='artifacts/openai-batch-001')
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args()
    key = os.environ.get('OPENAI_API_KEY')
    if not key:
        key = Path(os.environ['MAPLEBENCH_API_KEY_FILE']).read_text().strip()
    base = 'http://127.0.0.1:8790'
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    lock = (out.parent / '.cosmic-queue.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    queue = [{'model': model, 'status': 'queued'} for model in MODELS]
    write_json(out / 'queue.json', queue)
    if args.preflight:
        for model in MODELS:
            decision, meta = model_decision(model, {'preflight': 'Return a single wait action for 100 ms.'}, [], key)
            print(json.dumps({'model': model, 'returnedModel': meta['model'], 'ok': bool(decision['actions'])}), flush=True)
        return
    for index, entry in enumerate(queue):
        entry['status'] = 'running'; write_json(out / 'queue.json', queue)
        print(json.dumps({'model': entry['model'], 'status': 'running'}), flush=True)
        try:
            result = run_model(entry['model'], out / f'{index + 1:02d}-{entry["model"]}', base, key)
            entry.update(status='failed' if result['error'] else 'completed', result=result)
        except Exception as error:
            entry.update(status='failed', error=type(error).__name__)
        write_json(out / 'queue.json', queue)
        print(json.dumps(entry), flush=True)


if __name__ == '__main__':
    main()
