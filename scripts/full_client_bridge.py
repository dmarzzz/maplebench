"""Local-only relay between the existing program sandbox and the WASM client.

The browser sends numeric game observations and executes bounded keyboard input.
No game account credentials or API keys enter the program sandbox.
"""
import json
import hashlib
import threading
import time
import uuid
from pathlib import Path

from maple_agent import MODELS, execute_program, model_decision, validate_rpc, write_json

SCENARIO = {'adapter': 'full-client'}
PROMPT = '''You control a level 180 Hero in a private MapleStory v83 full client.
Write a JavaScript async function body using ONLY the frozen SDK:
  sdk.observe(): current character {x,y,hp,maxHp,mp,maxMp,exp,alive,mapId,level}
    and live monsters [{objectId,x,y}]. These are client observations, not scoring.
  sdk.pressKeys(keys, milliseconds): hold 1..3 named keys for 30..1500ms, then release.
    LEFT RIGHT UP DOWN JUMP ATTACK BRANDISH COMBO BOOSTER MAPLE_WARRIOR HP_POTION MP_POTION
  sdk.wait(milliseconds): wait 1..3000ms.
Coordinates increase rightward/downward. Input uses the real client physics and
skills; attacks require facing a nearby monster on the same platform. You cannot
teleport, target by ID, edit stats, or call moveTo/useSkill. Re-observe in loops.
COMBO, BOOSTER, MAPLE_WARRIOR are self buffs. BRANDISH is your main sword attack.
Avoid repeatedly resetting COMBO. Use HP_POTION and MP_POTION when needed.
Earn XP while staying alive. Your program may run for up to 22 seconds and make
100 SDK calls. Return before that deadline. There is no automatic combat policy
under your program. Game time continues while the API is thinking. Code runs in a
networkless disposable container. Return JSON {note,code}, with a brief intention.
'''
SMOKE_CODE = '''
await sdk.pressKeys(['COMBO'], 100);
await sdk.wait(500);
await sdk.pressKeys(['BOOSTER'], 100);
await sdk.wait(500);
for (let i=0;i<12;i++) {
  const o=await sdk.observe();
  const c=o.character;
  if(c.hp<c.maxHp*0.65) await sdk.pressKeys(['HP_POTION'],100);
  if(c.mp<c.maxMp*0.25) await sdk.pressKeys(['MP_POTION'],100);
  const ms=o.monsters.filter(m=>Math.abs(m.y-c.y)<65).sort((a,b)=>Math.abs(a.x-c.x)-Math.abs(b.x-c.x));
  if(ms.length) {
    const dx=ms[0].x-c.x;
    await sdk.pressKeys([dx<0?'LEFT':'RIGHT'],Math.abs(dx)>140?500:30);
    await sdk.pressKeys(['BRANDISH'],650);
  } else await sdk.pressKeys(['LEFT'],700);
  await sdk.wait(160);
}
'''


class FullClientBridge:
    def __init__(self, output, key_file=None):
        self.output = Path(output)
        self.key_file = Path(key_file) if key_file else None
        self.lock = threading.Condition()
        self.client = None
        self.last_seen = 0
        self.observation = {'ready': False}
        self.pending = None
        self.run = {'status': 'idle', 'mode': 'manual', 'model': None}

    def fresh(self):
        return time.monotonic() - self.last_seen < 1.5 and self.observation.get('ready') is True

    def frame(self, body):
        client = body.get('client')
        obs = body.get('observation', {})
        if not isinstance(client, str) or len(client) > 64 or not isinstance(obs, dict):
            raise ValueError('Invalid client frame')
        if len(json.dumps(obs)) > 64000:
            raise ValueError('Oversized observation')
        with self.lock:
            if self.client not in (None, client) and time.monotonic() - self.last_seen < 3:
                raise ValueError('A client is already connected')
            self.client = client
            age = body.get('ageMs')
            render_age = body.get('renderAgeMs')
            valid_frame = (type(age) in (int, float) and 0 <= age < 1500
                           and type(render_age) in (int, float) and 0 <= render_age < 1500)
            self.observation = obs | {'ageMs':age, 'renderAgeMs':render_age, 'renderedHud':body.get('renderedHud')} if valid_frame else {'ready': False}
            self.last_seen = time.monotonic()
            ack = body.get('ack')
            if self.pending and isinstance(ack, dict) and ack.get('id') == self.pending['id']:
                self.pending['ack'] = ack
                self.lock.notify_all()
            command = None
            if self.pending and not self.pending.get('sent') and self.pending['deadline'] > time.monotonic():
                self.pending['sent'] = True
                command = {k: self.pending[k] for k in ('id', 'keys', 'durationMs')}
            return {'command': command, 'run': dict(self.run)}

    def request(self, url, payload=None, timeout=3):
        with self.lock:
            if not self.fresh():
                raise ValueError('Full client is not ready or its observation is stale')
            if url.endswith('/v1/observe'):
                return self.observation
            if not url.endswith('/v1/action') or not isinstance(payload, dict) or payload.get('type') != 'press_keys':
                raise ValueError('Only full-client keyboard actions are supported')
            _, action = validate_rpc({'type':'rpc','id':1,'method':'pressKeys','args':[payload.get('keys'),payload.get('durationMs')]}, SCENARIO)
            if self.pending:
                raise ValueError('Another input is in flight')
            pending = {'id': uuid.uuid4().hex, 'keys': action['keys'], 'durationMs': action['durationMs'],
                       'deadline': time.monotonic() + min(timeout, 3)}
            self.pending = pending
            try:
                while 'ack' not in pending:
                    left = pending['deadline'] - time.monotonic()
                    if left <= 0:
                        raise TimeoutError('Client did not acknowledge keyboard input')
                    self.lock.wait(left)
                ack = pending['ack']
                return {'accepted': ack.get('ok') is True, 'observation': self.observation,
                        'error': None if ack.get('ok') is True else 'Client input was interrupted'}
            finally:
                self.pending = None

    def start(self, mode, model=None):
        if mode not in ('script', 'api') or (mode == 'api' and model not in MODELS):
            raise ValueError('Invalid controller selection')
        if mode == 'api' and (not self.key_file or not self.key_file.is_file()):
            raise ValueError('API key file is not configured')
        with self.lock:
            if self.run['status'] in ('requesting', 'running') or not self.fresh():
                raise ValueError('Client busy or not ready')
            self.run = {'id':uuid.uuid4().hex, 'status':'requesting', 'mode':mode,
                        'model':model if mode=='api' else None, 'adapter':'full-client'}
            value = dict(self.run)
        threading.Thread(target=self._run, args=(value,), daemon=True).start()
        return value

    def _run(self, run):
        out = self.output / run['id']
        out.mkdir(parents=True)
        result = None
        started = time.monotonic()
        started_ms = round(time.time()*1000)
        api_ms = 0
        meta = None
        timeline = {'api_started_ms': None, 'api_ended_ms': None}
        try:
            initial = self.request('/v1/observe')
            code, meta = SMOKE_CODE, None
            if run['mode'] == 'api':
                api_started = time.monotonic()
                timeline['api_started_ms'] = round((api_started-started)*1000)
                key = self.key_file.read_text().strip()
                choice, meta = model_decision(run['model'], PROMPT, {'observation':initial}, key,
                                             output_tokens=3000, timeout=50)
                del key
                api_ms = round((time.monotonic()-api_started)*1000)
                timeline['api_ended_ms'] = round((time.monotonic()-started)*1000)
                write_json(out/'response.json', meta)
                if not choice:
                    raise ValueError('API did not return a completed valid program')
                if meta.get('model') != run['model']:
                    raise ValueError('API returned a different model')
                code = choice['code']
                write_json(out/'program.json', choice)
            else:
                write_json(out/'program.json', {'note':'Deterministic adapter smoke test; no model', 'code':code})
            with self.lock:
                self.run.update(status='running', returnedModel=meta.get('model') if meta else None)
            # Allow the client recorder to start before the first input.
            time.sleep(0.6)
            timeline['program_started_ms'] = round((time.monotonic()-started)*1000)
            result = execute_program(code, SCENARIO, 'http://127.0.0.1:8840',
                                     deadline=time.monotonic()+24, program_seconds=22,
                                     max_actions=80, request_fn=self.request)
            timeline['program_ended_ms'] = round((time.monotonic()-started)*1000)
            final = self.request('/v1/observe')
            interrupted = any(step.get('method') == 'pressKeys' and step.get('result', {}).get('accepted') is not True
                              for step in result['steps'])
            status = 'completed' if result['reason'] == 'program_complete' and not interrupted else 'failed'
            reason = 'input_interrupted' if interrupted else result['reason']
            timeline['status'] = status
            write_json(out/'result.json', {'controller':run | {'status':status, 'returnedModel':meta.get('model') if meta else None}, 'program':result, 'initial':initial,
                                         'final':final, 'source':'client telemetry; unscored integration run',
                                         'timing':{'startedAtMs':started_ms, 'endedAtMs':round(time.time()*1000),
                                                   'elapsedMs':round((time.monotonic()-started)*1000),
                                                   'apiLatencyMs':api_ms},
                                         'api':meta,
                                         'timeline':timeline,
                                         'programSha256':hashlib.sha256(code.encode()).hexdigest(),
                                         'observedXpDelta':final['character']['exp']-initial['character']['exp']})
            with self.lock:
                self.run.update(status=status, reason=reason, actions=result['actions'])
            write_json(out/'publication.json', {
                'schema_version':1, 'run_kind':'integration',
                'result':json.loads((out/'result.json').read_text()),
                'budgets':{'api_requests':1 if run['mode']=='api' else 0, 'output_tokens':3000,
                           'total_tokens':None, 'program_ms':22000, 'run_ms':75000, 'actions':80},
                'timeline':timeline,
                'scenario':{'id':'hero-full-client-skeletons-integration',
                            'fingerprint':None, 'reset_fingerprint':None},
                'score':None, 'video':None})
        except Exception as error:
            # Avoid writing arbitrary exception strings from credential-bearing I/O.
            with self.lock:
                self.run.update(status='failed', reason=type(error).__name__)
            write_json(out/'failure.json', {'controller':run, 'error':type(error).__name__, 'program':result})
        finally:
            with self.lock:
                write_json(out/'controller.json', self.run)
