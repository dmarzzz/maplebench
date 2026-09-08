"""Local-only relay between the existing program sandbox and the WASM client.

The browser sends numeric game observations and executes bounded keyboard input.
No game account credentials or API keys enter the program sandbox.
"""
import json
import hashlib
import math
import os
import re
import stat
import tempfile
import threading
import time
import uuid
from pathlib import Path

from maple_agent import MODELS, PRESS_KEYS_ACK_SECONDS, bounded_request, execute_program, model_decision, validate_rpc
from full_client_capture import capture_receipt
from full_client_native import PROTOCOL as NATIVE_PROTOCOL, NATIVE_V2_PROTOCOL, validate_contract as validate_native, program as native_program
from full_client_docker import DockerBindingError, validate_binding
from full_client_readiness import ReadinessError, observation_matches, observation_sha256, validate_policy
from full_client_adaptive import AdaptiveError, PROTOCOL as ADAPTIVE_PROTOCOL, run_adaptive, validate_protocol


class ControlError(ValueError):
    """A credential-free failure code that is safe to show in the live UI."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def failure_release(path, run_id, quarantine_id=None, *, create=False):
    """Create once or validate the exact durable acknowledgment after a lost reply."""
    if quarantine_id is None and (path.parent/'quarantine.json').exists():
        try:
            quarantine=json.loads(read_private_file(path.parent/'quarantine.json',4096))
            if (set(quarantine)!={'runId','id','reason'} or quarantine['runId']!=run_id
                    or not isinstance(quarantine['id'],str) or not re.fullmatch('[a-f0-9]{32}',quarantine['id'])
                    or quarantine['reason'] not in ('invalid_controller_evidence','invalid_quarantine_evidence')):raise ValueError()
            quarantine_id=quarantine['id']
        except (OSError,ValueError,TypeError):raise ControlError('invalid_failure_release') from None
    reason='operator_acknowledged_corrupt_evidence' if quarantine_id else 'operator_acknowledged_failure'
    identity={'runId':run_id,'reason':reason}
    if quarantine_id:identity['quarantineId']=quarantine_id
    if create and not os.path.lexists(path):
        raw=(json.dumps(identity|{'releasedAtMs':round(time.time()*1000)},sort_keys=True)+'\n').encode()
        fd,name=tempfile.mkstemp(prefix='.release-',dir=path.parent)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            try:os.link(name,path)
            except FileExistsError:pass
            directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:os.unlink(name)
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as stream:
            before=os.fstat(stream.fileno())
            if not _private_stat(before) or before.st_size>4096:raise ValueError()
            raw=stream.read(4097);after=os.fstat(stream.fileno())
        stamp=lambda st:(st.st_dev,st.st_ino,st.st_mode,st.st_uid,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
        if stamp(before)!=stamp(after) or stamp(after)!=stamp(path.lstat()):raise ValueError()
        def pairs(items):
            result={}
            for k,v in items:
                if k in result:raise ValueError()
                result[k]=v
            return result
        value=json.loads(raw,object_pairs_hook=pairs)
        if (set(value)!=set(identity)|{'releasedAtMs'} or any(value[k]!=v for k,v in identity.items())
                or type(value['releasedAtMs']) is not int or value['releasedAtMs']<0):raise ValueError()
        return value
    except (OSError,ValueError,TypeError,RecursionError):raise ControlError('invalid_failure_release') from None


def has_failure_release(path, run_id):
    try:failure_release(path,run_id);return True
    except ControlError:return False


def _private_stat(value):
    return stat.S_ISREG(value.st_mode) and stat.S_IMODE(value.st_mode) == 0o600 and value.st_uid == os.geteuid()


def validate_private_file(path):
    try:
        valid = _private_stat(Path(path).lstat())
    except OSError:
        valid = False
    if not valid:
        raise ControlError('credential_file_requires_owner_and_mode_0600')


def read_private_file(path, maximum=65536):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'r') as handle:
        value = os.fstat(handle.fileno())
        if not _private_stat(value) or value.st_size > maximum:
            raise ControlError('credential_file_requires_owner_and_mode_0600')
        contents = handle.read(maximum+1)
        if len(contents) > maximum:
            raise ControlError('credential_file_oversized')
        return contents


def write_json(path, value):
    """Readers must see either the previous complete evidence or the new one."""
    write_bytes(path, json.dumps(value, allow_nan=False, indent=2).encode() + b'\n')


def write_bytes(path, data):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _number(value, minimum=0, maximum=2**53-1):
    return type(value) in (int, float) and minimum <= value <= maximum and math.isfinite(value)


def _observation(value):
    if not isinstance(value, dict) or type(value.get('ready')) is not bool:
        raise ControlError('invalid_observation')
    if not value['ready']:
        return {'ready': False}
    character, monsters = value.get('character'), value.get('monsters')
    if not isinstance(character, dict) or not isinstance(monsters, list) or len(monsters) > 1000:
        raise ControlError('invalid_observation')
    fields = ('x', 'y', 'hp', 'maxHp', 'mp', 'maxMp', 'exp', 'mapId', 'level')
    if (not all(_number(character.get(k), -2**31 if k in ('x', 'y') else 0) for k in fields)
            or type(character.get('alive')) is not bool or not 1 <= character['level'] <= 255
            or character['maxHp'] <= 0):
        raise ControlError('invalid_character_observation')
    clean_monsters = []
    for monster in monsters:
        if (not isinstance(monster, dict) or not _number(monster.get('objectId'))
                or not all(_number(monster.get(k), -2**31) for k in ('x', 'y'))):
            raise ControlError('invalid_monster_observation')
        clean_monsters.append({k:monster[k] for k in ('objectId', 'x', 'y')})
    # Do not persist arbitrary browser-provided strings or account-shaped data.
    return {'ready': True, 'source': 'full-client',
            'character':{k:character[k] for k in (*fields, 'alive')}, 'monsters':clean_monsters}

SCENARIO = {'adapter': 'full-client'}
PROMPT = '''You control a level 180 Hero in a private MapleStory v83 full client.
Write a JavaScript async function body using ONLY the frozen SDK:
The harness already wraps and invokes your code as an async function. Use
top-level await, for example: const state = await sdk.observe();
Do not return only an outer function declaration such as async function run().
If you define a helper function, explicitly await its call in the body.
  sdk.observe(): current character {{x,y,hp,maxHp,mp,maxMp,exp,alive,mapId,level}}
    and live monsters [{{objectId,x,y}}]. These are client observations, not scoring.
  sdk.pressKeys(keys, milliseconds): hold 1..3 named keys for 30..1500ms, then release.
    LEFT RIGHT UP DOWN JUMP ATTACK BRANDISH COMBO BOOSTER MAPLE_WARRIOR HP_POTION MP_POTION
  sdk.wait(milliseconds): wait 1..3000ms.
Coordinates increase rightward/downward. Input uses the real client physics and
skills; attacks require facing a nearby monster on the same platform. You cannot
teleport, target by ID, edit stats, or call moveTo/useSkill. Re-observe in loops.
COMBO, BOOSTER, MAPLE_WARRIOR are self buffs. BRANDISH is your main sword attack.
Avoid repeatedly resetting COMBO. Use HP_POTION and MP_POTION when needed.
Earn XP while staying alive. Your program may run for up to {program_seconds} seconds and make
{sdk_request_limit} SDK calls, including at most {action_limit} pressKeys actions. Return before that deadline. There is no automatic combat policy
under your program. Game time continues while the API is thinking. Code runs in a
networkless disposable container. Return JSON {{note,code}}, with a brief intention.
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
        if self.key_file is not None:
            validate_private_file(self.key_file)
        self.lock = threading.Condition()
        self.client = None
        self.last_seen = 0
        self.fresh_until = 0
        self.observation = {'ready': False}
        self.pending = None
        self.cancel_events = {}
        self.leases = {}
        self.release_acks = set()
        self.capture_clock = None
        self.capture_clock_received_ms = None
        self.frame_transit = None
        self.readiness = None
        self.quarantines = {}
        self.run = {'status': 'idle', 'mode': 'manual', 'model': None}
        self._recover_incomplete()

    def _recover_incomplete(self):
        if not self.output.is_dir():
            return
        latest = -1
        for folder in self.output.iterdir():
            if not re.fullmatch('[a-f0-9]{32}', folder.name) or not folder.is_dir():
                continue
            path = folder/'controller.json'
            modified = path.stat().st_mtime_ns if path.is_file() else folder.stat().st_mtime_ns
            try:
                if not path.is_file() or path.stat().st_size > 128*1024:
                    raise ValueError('Oversized controller evidence')
                previous = json.loads(path.read_text())
                if (not isinstance(previous, dict) or previous.get('id')!=folder.name
                        or previous.get('status') not in ('requesting','running','completed','failed')):
                    raise ValueError('Invalid controller evidence')
            except (ValueError, RecursionError, UnicodeError):
                # Preserve the corrupt bytes, record a safe failure, and never retry.
                quarantine_id=uuid.uuid4().hex
                if path.exists(): os.replace(path,folder/f'controller-corrupt-{quarantine_id}.bin')
                write_json(folder/'quarantine.json',{'runId':folder.name,'id':quarantine_id,
                    'reason':'invalid_controller_evidence'})
                previous={'id':folder.name,'status':'failed','mode':'unknown','model':None,
                    'reason':'invalid_controller_evidence','evidenceStatus':'failed','apiOutcome':'uncertain',
                    'quarantined':True,'workerActive':False}
                write_json(folder/'failure.json', {'error':'invalid_controller_evidence',
                    'phase':'recovery','apiOutcome':'uncertain'})
                write_json(path,previous)
            quarantine_path=folder/'quarantine.json'
            if previous.get('quarantined') is True and not quarantine_path.exists():
                write_json(quarantine_path,{'runId':folder.name,'id':uuid.uuid4().hex,
                    'reason':'invalid_quarantine_evidence'})
            if quarantine_path.exists():
                try:
                    if quarantine_path.stat().st_size>128*1024: raise ValueError('invalid_quarantine')
                    quarantine=json.loads(quarantine_path.read_text())
                    if (not isinstance(quarantine,dict) or quarantine.get('runId')!=folder.name
                            or not isinstance(quarantine.get('id'),str) or not re.fullmatch('[a-f0-9]{32}',quarantine['id'])
                            or quarantine.get('reason') not in ('invalid_controller_evidence','invalid_quarantine_evidence')):
                        raise ValueError('invalid_quarantine')
                except (ValueError,RecursionError,UnicodeError):
                    quarantine={'runId':folder.name,'id':uuid.uuid4().hex,'reason':'invalid_quarantine_evidence'}
                    os.replace(quarantine_path,folder/f'quarantine-corrupt-{quarantine["id"]}.bin')
                    write_json(quarantine_path,quarantine)
                try:
                    failure_release(folder/'release.json',folder.name,quarantine['id'])
                    released=True
                except ControlError:released=False
                if not released:
                    self.quarantines[folder.name]=quarantine['id']
                    previous.update(status='failed',quarantined=True,reason=quarantine['reason'],
                                    evidenceStatus='failed',apiOutcome='uncertain')
                    write_json(path,previous)
            recovered = previous.get('workerActive') is True
            previous['workerActive'] = False
            if previous.get('status') in ('requesting', 'running'):
                previous.update(status='failed', reason='process_restarted', evidenceStatus='interrupted')
                write_json(folder/'failure.json', {'controller':previous, 'error':'process_restarted',
                    'phase':'recovery', 'apiOutcome':'receipt_saved' if (folder/'api-response.json').is_file() or (folder/'response.json').is_file()
                    else 'uncertain' if (folder/'api-request.json').is_file() else 'not_started'})
                write_json(path, previous)
            elif recovered:
                write_json(path, previous)
            if (folder/'recording.json').is_file():
                previous['recordingStatus'] = 'saved'
            if modified > latest:
                latest = modified
                self.run = previous

    def fresh(self):
        return time.monotonic() < self.fresh_until and self.observation.get('ready') is True

    def _cancelled(self, run_id):
        return bool(run_id) and (self.output/'cancellations'/f'{run_id}.json').is_file()

    def _check_cancelled(self, run_id):
        if self._cancelled(run_id):
            raise ControlError('run_cancelled')

    def cancel(self, run_id):
        if not isinstance(run_id,str) or not re.fullmatch('[a-f0-9]{32}',run_id):
            raise ControlError('invalid_run_identity')
        with self.lock:
            folder = self.output/run_id
            already_terminal = self.run.get('id')==run_id and self.run.get('status')=='completed'
            api_outcome = 'not_started'
            if (folder/'api-response.json').is_file():
                api_outcome = 'receipt_saved'
            elif (folder/'api-request.json').is_file():
                try:
                    intent = json.loads((folder/'api-request.json').read_text())
                    api_outcome = 'not_started' if intent.get('status') in ('preparing','budget_rejected','readiness_rejected') else 'uncertain'
                except (OSError,ValueError,AttributeError):
                    api_outcome = 'uncertain'
            path = self.output/'cancellations'/f'{run_id}.json'
            if not path.exists():
                path.parent.mkdir(parents=True,exist_ok=True)
                write_json(path,{'runId':run_id,'requestedAtMs':round(time.time()*1000),
                                 'reason':'terminal_quiesce' if already_terminal else 'operator_cancelled',
                                 'apiOutcomeAtCancellation':api_outcome})
            event = self.cancel_events.get(run_id)
            if event is not None: event.set()
            if self.pending and self.pending.get('runId')==run_id:
                self.pending['ack']={'id':self.pending['id'],'ok':False}
                self.lock.notify_all()
            if self.run.get('id')==run_id and not already_terminal:
                self.run.update(status='failed',reason='run_cancelled',cancelled=True,
                                failureAcknowledged=True,apiOutcome=api_outcome)
                write_json(folder/'controller.json',self.run)
            return {'runId':run_id,'cancelled':not already_terminal,'alreadyTerminal':already_terminal,'apiOutcome':api_outcome,
                    'workerActive':run_id in self.cancel_events,
                    'browserReleasePending':self.run.get('id')==run_id and run_id not in self.release_acks}

    def _snapshot(self):
        if not self.fresh():
            raise ControlError('client_state_stale')
        elapsed = max(0, (time.monotonic()-self.last_seen)*1000)
        return json.loads(json.dumps(self.observation)) | {
            'ageMs':self.observation['ageMs']+elapsed,
            'renderAgeMs':self.observation['renderAgeMs']+elapsed}

    def _wait_for_capture(self, run_id, timeout=5):
        deadline=time.monotonic()+timeout
        with self.lock:
            while True:
                self._check_cancelled(run_id)
                if self.run.get('id')!=run_id: raise ControlError('run_owner_changed')
                if self.run.get('captureReady') and self.run.get('captureClockAccepted') and self.fresh(): return
                remaining=deadline-time.monotonic()
                if remaining<=0: raise ControlError('recorder_not_ready')
                self.lock.wait(remaining)

    def _readiness_sample(self, observation, rendered_frames, received_ms, now):
        sampled_now=time.monotonic()
        proof=self.frame_transit
        residence=max(0,(sampled_now-self.last_seen)*1000)
        observation['ageMs']=proof['reported_age_ms']+proof['transit_upper_ms']+residence
        observation['renderAgeMs']=proof['reported_render_age_ms']+proof['transit_upper_ms']+residence
        return {'rendered_frames':rendered_frames,'server_received_at_ms':round(time.time()*1000),
                'run_elapsed_ms':round((sampled_now-self.readiness['run_started'])*1000),
                'map_id':observation['character']['mapId'],'alive':observation['character']['alive'],
                'monster_count':len(observation['monsters']),'age_ms':observation['ageMs'],
                'render_age_ms':observation['renderAgeMs'],'observation_sha256':observation_sha256(observation),
                **proof,'server_residence_ms':max(0,residence)}

    def _record_readiness_frame(self, capture, received_ms, now):
        """Called under the same lock that accepts this run's post-render frame."""
        state=self.readiness
        if state is None:
            return
        valid=(self.run.get('id')==state['run_id'] and self.client==state['client_id']
               and self.run.get('captureClockAccepted')==state['capture_clock_id']
               and self.run.get('captureReady') is True and self.fresh()
               and observation_matches(self.observation,state['policy']))
        if not valid:
            state['samples']=[]; state['generation']+=1
            self.lock.notify_all()
            return
        counter=capture['renderedFrames']
        previous=state.get('counter')
        if previous is not None and counter<previous:
            state['fault']=True
        if previous is not None and counter<=previous:
            self.lock.notify_all()
            return
        if state['samples'] and (now-state['last_received']>=1.5
                or round((now-state['run_started'])*1000)-state['samples'][-1]['frame_received_run_ms']>=1500
                or not 0<=received_ms-state['samples'][-1]['frame_received_at_ms']<1500):
            state['samples']=[]; state['generation']+=1
        if not state['samples']:
            state['first_received']=now
        state['counter']=counter
        state['last_received']=now
        observation=self._snapshot()
        sample=self._readiness_sample(observation,counter,received_ms,now)
        state['samples'].append(sample)
        # Keep the first point and a bounded recent tail, even under frame spam.
        if len(state['samples'])>64: del state['samples'][1]
        state['observation']=observation
        self.lock.notify_all()

    def _wait_for_readiness(self, run, started):
        policy=run['readinessPolicy']
        with self.lock:
            now=time.monotonic()
            self.readiness={'run_id':run['id'],'client_id':run['client'],
                'capture_clock_id':self.run.get('captureClockAccepted'),'policy':policy,
                'run_started':started,'wait_started':now,'wait_started_at_ms':round(time.time()*1000),
                'samples':[],'generation':0,'fault':False}
            state=self.readiness
            deadline=now+policy['timeout_ms']/1000
            while True:
                self._check_cancelled(run['id'])
                if (self.run.get('id')!=run['id'] or self.client!=run['client']
                        or self.run.get('captureClockAccepted')!=state['capture_clock_id'] or state['fault']):
                    raise ControlError('readiness_state_changed')
                now=time.monotonic()
                if now>=deadline: raise ControlError('readiness_timeout')
                samples=state['samples']
                if (len(samples)>=policy['min_samples']
                        and samples[-1]['frame_received_run_ms']-samples[0]['frame_received_run_ms']>=policy['min_span_ms']
                        and samples[-1]['frame_received_at_ms']-samples[0]['frame_received_at_ms']>=policy['min_span_ms']
                        and state['last_received']-state['first_received']>=policy['min_span_ms']/1000
                        and self.run.get('captureReady') and self.fresh()
                        and observation_matches(self._snapshot(),policy)):
                    state['qualified_generation']=state['generation']
                    state['qualified_received']=state['last_received']
                    initial=json.loads(json.dumps(state['observation']))
                    return initial, {'schema_version':1,'run_id':run['id'],'client_id':run['client'],
                        'capture_clock_id':state['capture_clock_id'],
                        'capture_clock_client_received_ms':self.capture_clock_received_ms,
                        'capture_ready_at_ms':self.run['captureReadyAtMs'],'policy':policy,
                        'wait_started_at_ms':state['wait_started_at_ms'],
                        'wait_started_run_ms':round((state['wait_started']-started)*1000),
                        'qualified_at_ms':round(time.time()*1000),'qualified_run_ms':round((now-started)*1000),
                        'samples':json.loads(json.dumps(samples)),
                        'initial_observation_sha256':observation_sha256(initial)}
                self.lock.wait(min(0.2,deadline-now))

    def _readiness_dispatch(self, run, receipt):
        """Recheck the latest frame; never replace the already chosen API input."""
        state=self.readiness
        self._check_cancelled(run['id'])
        if (state is None or state['run_id']!=run['id'] or self.run.get('id')!=run['id']
                or self.client!=receipt['client_id'] or state['fault']
                or state['generation']!=state.get('qualified_generation')
                or self.run.get('captureClockAccepted')!=receipt['capture_clock_id']
                or not self.run.get('captureReady') or not self.fresh()
                or time.monotonic()-state['wait_started']>=state['policy']['timeout_ms']/1000):
            raise ControlError('readiness_state_changed')
        observation=self._snapshot()
        if not observation_matches(observation,state['policy']):
            raise ControlError('readiness_state_changed')
        now=time.monotonic()
        initial=receipt['samples'][-1]
        initial_elapsed=max(0,(now-state['qualified_received'])*1000)
        if max(initial['reported_age_ms'],initial['reported_render_age_ms'])+initial['transit_upper_ms']+initial_elapsed>=1500:
            raise ControlError('readiness_state_changed')
        rounded_elapsed=round((now-state['run_started'])*1000)-initial['run_elapsed_ms']
        if max(initial['age_ms'],initial['render_age_ms'])+rounded_elapsed>=1500:
            raise ControlError('readiness_state_changed')
        sample=self._readiness_sample(observation,state['counter'],
                                      state['samples'][-1]['server_received_at_ms'],now)
        if (max(sample['age_ms'],sample['render_age_ms'])>=1500
                or max(initial['age_ms'],initial['render_age_ms'])+sample['run_elapsed_ms']-initial['run_elapsed_ms']>=1500):
            raise ControlError('readiness_state_changed')
        return {key:value for key,value in sample.items() if key!='server_received_at_ms'} | {
            'checked_at_ms':round(time.time()*1000)}

    def frame(self, body):
        if not isinstance(body, dict):
            raise ValueError('Invalid client frame')
        client = body.get('client')
        if not isinstance(client, str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}', client):
            raise ValueError('Invalid client frame')
        if len(json.dumps(body, allow_nan=False)) > 70000:
            raise ValueError('Oversized observation')
        obs = _observation(body.get('observation'))
        age, render_age, ack = body.get('ageMs'), body.get('renderAgeMs'), body.get('ack')
        if not _number(age) or not _number(render_age):
            raise ControlError('invalid_frame_age')
        if ack is not None and (not isinstance(ack, dict)
                or not isinstance(ack.get('id'), str) or not re.fullmatch('[a-f0-9]{32}', ack['id'])
                or type(ack.get('ok')) is not bool):
            raise ControlError('invalid_input_acknowledgement')
        with self.lock:
            now = time.monotonic()
            server_received_ms=round(time.time()*1000)
            active = self.run['status'] in ('requesting', 'running') or self.run.get('workerActive') or bool(self.leases) or self.pending is not None
            if self.client not in (None, client) and (active or now - self.last_seen < 3):
                raise ControlError('client_already_connected')
            self.client = client
            run_id = self.run.get('id')
            # A restored terminal record is historical evidence, not a live
            # capture-clock session. Ordinary login must work before start()
            # creates the next run and its new recorder/clock handshake.
            settled_history = bool(run_id) and body.get('captureState') == 'idle' and not (
                active or self.cancel_events or self.run.get('leaseReleasePending') or self.quarantines
                or self._cancelled(run_id) and run_id not in self.release_acks
            ) and (
                self.run['status'] == 'completed' and self.run.get('evidenceStatus') == 'saved'
                and self.run.get('recordingStatus') == 'saved'
                and (self.output/run_id/'recording.json').is_file()
                or self.run['status'] == 'failed' and self.run.get('failureAcknowledged') is True
                and has_failure_release(self.output/run_id/'release.json',run_id)
            )
            valid_frame = obs['ready'] and max(age, render_age) < 1500
            hud = body.get('renderedHud')
            hud = {k:hud[k] for k in ('hp', 'mp', 'maxHp', 'maxMp')} if isinstance(hud, dict) and all(
                _number(hud.get(k)) for k in ('hp', 'mp', 'maxHp', 'maxMp')) else None
            self.observation = obs | {'ageMs':age, 'renderAgeMs':render_age, 'renderedHud':hud} if valid_frame else {'ready': False}
            self.last_seen = now
            self.fresh_until = now + (1500-max(age, render_age))/1000 if valid_frame else now
            capture=body.get('capture')
            self.run['captureReady']=bool(not settled_history and self.run.get('id') and valid_frame and isinstance(capture,dict)
                and capture.get('runId')==self.run.get('id') and capture.get('started') is True
                and type(capture.get('renderedFrames')) is int and 0<capture['renderedFrames']<=100000
                and capture.get('interrupted') is False and body.get('captureState')=='recording')
            if self.run['captureReady'] and not self.run.get('captureReadyAtMs'):
                self.run['captureReadyAtMs']=server_received_ms
                write_json(self.output/self.run['id']/'capture-ready.json',
                    {'runId':self.run['id'],'serverReceivedAtMs':server_received_ms,'renderedFrames':capture['renderedFrames']})
            if self.run['captureReady']: self.lock.notify_all()
            if not settled_history and self.run.get('id') and _number(body.get('clientSentAtMs')):
                if not self.run.get('captureClockAccepted'):
                    if self.capture_clock and body.get('captureClockAck')==self.capture_clock['id']:
                        received=body.get('captureClockReceivedAtMs')
                        clock=self.capture_clock
                        valid_clock=(_number(received) and clock['client_sent_ms']<=received<=body['clientSentAtMs']
                            and 0 <= (clock['server_received_ms']-clock['client_sent_ms'])
                                -(clock['server_sent_ms']-received) <= 500)
                        if not self.run.get('readinessPolicy') or valid_clock:
                            self.run['captureClockAccepted']=clock['id']
                            self.capture_clock_received_ms=received if valid_clock else None
                            write_json(self.output/self.run['id']/'capture-clock.json',clock)
                    else:
                        self.capture_clock={'id':uuid.uuid4().hex,'client_sent_ms':body['clientSentAtMs'],
                            'server_received_ms':server_received_ms,'server_sent_ms':round(time.time()*1000)}
            if self.run.get('readinessPolicy') and not settled_history:
                # The recorded handshake gives an offset interval, not equal
                # clocks. Its lower endpoint conservatively bounds POST transit.
                clock=self.capture_clock
                sent=body.get('clientSentAtMs')
                proof_valid=(clock is not None and self.run.get('captureClockAccepted')==clock['id']
                    and _number(self.capture_clock_received_ms) and _number(sent)
                    and sent>=self.capture_clock_received_ms)
                transit=(server_received_ms-(sent+clock['server_sent_ms']-self.capture_clock_received_ms)
                         if proof_valid else -1)
                self.frame_transit=None
                if proof_valid and 0<=transit<=5000:
                    self.frame_transit={'frame_received_at_ms':server_received_ms,
                        'frame_received_run_ms':round((now-self.readiness['run_started'])*1000) if self.readiness else None,
                        'client_sent_at_ms':sent,'reported_age_ms':age,'reported_render_age_ms':render_age,
                        'transit_upper_ms':transit}
                    age+=transit; render_age+=transit
                else:
                    valid_frame=False
                valid_frame=valid_frame and max(age,render_age)<1500
                self.observation=obs | {'ageMs':age,'renderAgeMs':render_age,'renderedHud':hud} if valid_frame else {'ready':False}
                self.fresh_until=now+(1500-max(age,render_age))/1000 if valid_frame else now
                self.run['captureReady']=self.run['captureReady'] and valid_frame
            if settled_history:
                self.frame_transit=None
            else:
                self._record_readiness_frame(capture,server_received_ms,now)
            if (not settled_history and self.run.get('id') and (self.output/self.run['id']).is_dir()
                    and self.run['status'] in ('completed','failed') and not self.run.get('captureTerminal')):
                self.run['captureTerminal']={'id':uuid.uuid4().hex,'serverIssuedAtMs':server_received_ms}
                write_json(self.output/self.run['id']/'capture-terminal.json',self.run['captureTerminal'])
            if (self.pending and ack is not None and ack['id'] == self.pending['id']
                    and self.pending.get('sent') and now < self.pending['deadline']):
                enough_time = now-self.pending['sentAt'] >= self.pending['durationMs']/1000 - 0.001
                self.pending['ack'] = {'id':ack['id'], 'ok':ack['ok'] and valid_frame and enough_time}
                self.lock.notify_all()
            if body.get('releaseAck') == self.run.get('id') and self._cancelled(self.run.get('id')):
                self.release_acks.add(self.run['id'])
                if self.run['id'] not in self.cancel_events:
                    for descriptor in self.leases.pop(self.run['id'],[]): os.close(descriptor)
                    self.run['leaseReleasePending']=False
                    write_json(self.output/self.run['id']/'controller.json',self.run)
            command = None
            dispatch_now = time.monotonic()
            if (valid_frame and self.pending and not self._cancelled(self.pending.get('runId'))
                    and not self.pending.get('sent')
                    and self.pending['deadline']-dispatch_now >= self.pending['durationMs']/1000 + PRESS_KEYS_ACK_SECONDS):
                self.pending['sent'] = True
                self.pending['sentAt'] = dispatch_now
                command = {k: self.pending[k] for k in ('id', 'keys', 'durationMs')}
                command['runId'] = self.run.get('id')
                # The browser subtracts the full request round trip, requiring
                # no shared wall clock to reject a delayed command response.
                command['remainingMs'] = math.floor((self.pending['deadline']-dispatch_now)*1000)
            return {'command': command, 'run': {k:v for k,v in self.run.items() if k not in ('client','dockerBinding')},
                    'clock':self.capture_clock,
                    'releaseKeys':{'runId':self.run['id']} if self._cancelled(self.run.get('id')) else None}

    def request(self, url, payload=None, timeout=3, *, run_id=None, input_deadline=None):
        with self.lock:
            run_id = run_id or self.run.get('id')
            self._check_cancelled(run_id)
            if not self.fresh():
                raise ControlError('client_state_stale')
            if url.endswith('/v1/observe'):
                return self._snapshot()
            if not url.endswith('/v1/action') or not isinstance(payload, dict) or payload.get('type') != 'press_keys':
                raise ValueError('Only full-client keyboard actions are supported')
            _, action = validate_rpc({'type':'rpc','id':1,'method':'pressKeys','args':[payload.get('keys'),payload.get('durationMs')]},
                SCENARIO | ({'protocol':self.run['protocol']} if self.run.get('protocol') in (ADAPTIVE_PROTOCOL,NATIVE_PROTOCOL,NATIVE_V2_PROTOCOL) else {}))
            if self.pending:
                raise ValueError('Another input is in flight')
            pending = {'id': uuid.uuid4().hex, 'keys': action['keys'], 'durationMs': action['durationMs'],
                       'runId':run_id,
                       'deadline': time.monotonic() + min(timeout, 3)}
            if input_deadline is not None:
                pending['deadline']=min(pending['deadline'],input_deadline)
            self.pending = pending
            try:
                while 'ack' not in pending:
                    self._check_cancelled(run_id)
                    left = pending['deadline'] - time.monotonic()
                    if left <= 0:
                        raise TimeoutError('Client did not acknowledge keyboard input')
                    self.lock.wait(left)
                ack = pending['ack']
                self._check_cancelled(run_id)
                accepted = ack['ok'] and self.fresh()
                return {'accepted': accepted, 'observation': self._snapshot() if self.fresh() else {'ready':False},
                        'error': None if accepted else 'Client input was interrupted'}
            finally:
                self.pending = None

    def status(self, *, private=False):
        with self.lock:
            run={k:v for k,v in self.run.items() if k != 'client' and (private or k != 'dockerBinding')}
            # Include explicit quiescence for a cold idle bridge. Inspect live
            # bookkeeping too, so an outstanding worker/input/lease cannot be
            # hidden by an older or prematurely terminal controller record.
            run['workerActive']=(bool(self.cancel_events) or self.pending is not None
                or bool(self.run.get('workerActive')) or self.run.get('status') in ('requesting','running'))
            run['leaseReleasePending']=bool(self.leases) or bool(self.run.get('leaseReleasePending'))
            return {'run':run,
                    'quarantinedRuns':sorted(self.quarantines),
                    'fresh':self.fresh(), 'rendererConnected':self.client is not None and time.monotonic()-self.last_seen < 3,
                    'browserReleasePending':self._cancelled(self.run.get('id')) and self.run.get('id') not in self.release_acks,
                    'frameAgeMs':max(0,round((time.monotonic()-self.last_seen)*1000)) if self.client else None}

    def recording_owner(self, run_id, client=None):
        if not isinstance(run_id, str) or not re.fullmatch('[a-f0-9]{32}', run_id):
            raise ControlError('invalid_recording_run')
        with self.lock:
            path = self.output/run_id/'request.json'
            if not path.is_file():
                raise ControlError('unknown_recording_run')
            owner = json.loads(path.read_text())
            if client is not None and owner.get('client') != client:
                raise ControlError('recording_client_mismatch')
            return owner

    def attach_recording(self, run_id, temporary, digest, client=None, capture=None):
        """A late upload belongs to its original run, regardless of current UI state."""
        with self.lock:
            owner = self.recording_owner(run_id, client)
            folder = self.output/run_id
            receipt = folder/'recording.json'
            if receipt.exists() and json.loads(receipt.read_text()).get('sha256')!=digest:
                raise ControlError('recording_already_saved')
            measured = None
            if capture is not None:
                def read_receipt(name):
                    path=folder/name
                    return json.loads(path.read_text()) if path.is_file() else None
                measured=capture_receipt(capture,owner,read_receipt('capture-ready.json'),
                    read_receipt('capture-clock.json'),read_receipt('capture-terminal.json'))
                if (folder/'capture.json').exists() and json.loads((folder/'capture.json').read_text())!=capture:
                    raise ControlError('capture_metadata_already_saved')
                write_json(folder/'capture.json',capture)
            elif owner.get('trialContext') or owner.get('nativeAcceptance'):
                raise ControlError('trial_capture_metadata_required')
            if receipt.exists():
                previous = json.loads(receipt.read_text())
                if previous.get('sha256') != digest:
                    raise ControlError('recording_already_saved')
                video = previous
            else:
                video = {'path':'video.webm', 'sha256':digest, 'status':'completed', 'reviewed':False,
                         'interrupted':None, 'start_ms':None, 'end_ms':None, 'duration_ms':None,
                         'overlay':{'controller_id':run_id,'mode':owner['mode'],'model':owner['model']}}
                if measured is not None:
                    video.update(measured,capture_sha256=hashlib.sha256((folder/'capture.json').read_bytes()).hexdigest())
            # An identical retry also repairs an interrupted manifest update.
            os.replace(temporary, folder/'video.webm')
            write_json(receipt, video)
            manifest = folder/'publication.json'
            if manifest.exists():
                value = json.loads(manifest.read_text())
                value['video'] = video
                write_json(manifest, value)
            if self.run.get('id') == run_id:
                self.run['recordingStatus'] = 'saved'
            return video

    def _existing_run(self, identity, *, private=False):
        folder = self.output/identity['id']
        try:
            intent = json.loads((folder/'request.json').read_text())
            controller = json.loads((folder/'controller.json').read_text())
        except (OSError, ValueError, RecursionError):
            raise ControlError('run_intent_incomplete') from None
        if not isinstance(intent, dict) or any(intent.get(k) != v for k,v in identity.items()):
            raise ControlError('run_intent_conflict')
        if not isinstance(controller, dict) or controller.get('id') != identity['id']:
            raise ControlError('run_intent_incomplete')
        if self.run.get('id') == identity['id']:
            controller = self.run
        return {k:v for k,v in controller.items() if k != 'client' and (private or k != 'dockerBinding')}

    def release_failed_run(self, run_id):
        """Explicit trusted-operator acknowledgment; never exposed by HTTP."""
        if not isinstance(run_id,str) or not re.fullmatch('[a-f0-9]{32}',run_id):
            raise ControlError('invalid_run_identity')
        with self.lock:
            if (self.pending or self.run.get('workerActive') or self.leases.get(run_id)
                    or self.cancel_events.get(run_id)):
                raise ControlError('run_cannot_be_released')
            if run_id in self.quarantines:
                folder=self.output/run_id
                failure_release(folder/'release.json',run_id,self.quarantines[run_id],create=True)
                previous=json.loads((folder/'controller.json').read_text())
                previous.update(failureAcknowledged=True,quarantined=False)
                write_json(folder/'controller.json',previous)
                if self.run.get('id')==run_id: self.run.update(previous)
                del self.quarantines[run_id]
                return
            if self.run.get('id') != run_id and (self.output/run_id/'quarantine.json').exists():
                # An already acknowledged historical quarantine is immutable.
                failure_release(self.output/run_id/'release.json',run_id)
                return
            if (self.run.get('id') != run_id or self.run['status'] not in ('failed','completed')
                    or self.pending or self.run.get('workerActive') or self.leases.get(run_id)):
                raise ControlError('run_cannot_be_released')
            folder = self.output/run_id
            if self.run['status'] == 'completed' and (folder/'recording.json').is_file():
                raise ControlError('successful_run_cannot_be_discarded')
            failure_release(folder/'release.json',run_id,create=True)
            if self.run['status'] == 'completed':
                self.run.update(status='failed',reason='recording_abandoned',recordingStatus='discarded')
            self.run['failureAcknowledged'] = True
            write_json(folder/'controller.json',self.run)

    def start(self, mode, model=None, duration_seconds=22, *, client=None, run_id=None, request_id=None,
              total_token_limit=None, trial_context=None, docker_image_id=None, docker_binding=None,
              readiness_policy=None, adaptive_protocol=None, native_acceptance=None, lease_fds=(), private=False):
        if mode not in ('script', 'api') or (mode == 'api' and model not in MODELS):
            raise ValueError('Invalid controller selection')
        if native_acceptance is not None:
            try:native_acceptance=validate_native(native_acceptance)
            except (ValueError,TypeError) as error:raise ControlError('invalid_native_acceptance') from None
            if (not private or mode!='script' or model is not None or duration_seconds!=30
                    or adaptive_protocol is not None or trial_context is not None or readiness_policy is not None
                    or total_token_limit is not None or run_id is None or run_id!=request_id
                    or docker_binding is None or docker_image_id is None
                    or not isinstance(lease_fds,(tuple,list)) or len(lease_fds)!=2
                    or not all(type(fd) is int for fd in lease_fds)):
                raise ControlError('native_acceptance_private_contract_required')
        if adaptive_protocol is not None:
            try:adaptive_protocol=validate_protocol(adaptive_protocol)
            except AdaptiveError as error:raise ControlError(str(error)) from None
            if mode!='api' or duration_seconds!=300 or total_token_limit!=adaptive_protocol['max_total_tokens']:
                raise ControlError('adaptive_controller_budget_mismatch')
        if type(duration_seconds) is not int or duration_seconds not in ((30,) if native_acceptance is not None else (300,) if adaptive_protocol is not None else (22, 60)):
            raise ValueError('Run duration must be 22 or 60 seconds')
        if mode == 'script' and native_acceptance is None and duration_seconds != 22:
            raise ValueError('Scripted smoke runs last at most 22 seconds')
        if total_token_limit is not None and (type(total_token_limit) is not int or not 1 <= total_token_limit <= 2**31-1):
            raise ControlError('invalid_total_token_limit')
        if docker_image_id is not None and (not isinstance(docker_image_id,str) or not re.fullmatch('sha256:[a-f0-9]{64}',docker_image_id)):
            raise ControlError('invalid_docker_image_id')
        if trial_context is not None:
            if (mode!='api' or not isinstance(trial_context,dict)
                    or set(trial_context)!={'scenario_fingerprint','baseline_sha256'}
                    or not all(isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value) for value in trial_context.values())):
                raise ControlError('invalid_trial_context')
            trial_context = dict(trial_context)
        for value in (run_id,request_id):
            if value is not None and (not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value)):
                raise ControlError('invalid_run_identity')
        if trial_context is not None and (run_id is None or run_id != request_id):
            raise ControlError('trial_requires_matching_attempt_identity')
        if trial_context is not None and (docker_binding is None or docker_image_id is None):
            raise ControlError('docker_binding_required')
        if trial_context is not None and readiness_policy is None:
            raise ControlError('readiness_policy_required')
        if readiness_policy is not None:
            try:
                readiness_policy=validate_policy(readiness_policy)
            except ReadinessError as error:
                raise ControlError(str(error)) from None
            if trial_context is None: raise ControlError('invalid_readiness_policy')
        if docker_binding is not None:
            try:
                docker_binding = validate_binding(docker_binding)
            except DockerBindingError as error:
                raise ControlError(str(error)) from None
        run_id = run_id or request_id or uuid.uuid4().hex
        request_id = request_id or run_id
        identity = {'id':run_id,'requestId':request_id,'mode':mode,
                    'model':model if mode=='api' else None,'programSeconds':duration_seconds,
                    'totalTokenLimit':total_token_limit,'trialContext':trial_context,'dockerImageId':docker_image_id}
        if docker_binding is not None:
            identity['dockerBinding'] = docker_binding
        if readiness_policy is not None:
            identity['readinessPolicy'] = readiness_policy
        if adaptive_protocol is not None:
            identity['adaptiveProtocol'] = adaptive_protocol
        if native_acceptance is not None:
            identity.update(protocol=native_acceptance['id'],nativeAcceptance=native_acceptance)
        with self.lock:
            claim = self.output/'requests'/f'{request_id}.json'
            if claim.exists():
                try:
                    previous = json.loads(claim.read_text())
                except (OSError, ValueError, RecursionError):
                    raise ControlError('run_intent_incomplete') from None
                if previous != identity:
                    raise ControlError('run_intent_conflict')
                return self._existing_run(identity, private=private)
            if (self.output/run_id).exists():
                return self._existing_run(identity, private=private)
            self._check_cancelled(run_id)
            if self.quarantines:
                raise ControlError('corrupt_runs_require_acknowledgment')
            if trial_context is not None and (not isinstance(lease_fds,(tuple,list)) or len(lease_fds)!=2
                    or not all(type(fd) is int for fd in lease_fds)):
                raise ControlError('trial_requires_guard_lock_descriptors')
            if mode == 'api' and (not self.key_file or not self.key_file.is_file()):
                raise ControlError('api_key_not_configured')
            if (self.run['status'] in ('requesting', 'running') or self.run.get('workerActive') or self.leases
                    or self._cancelled(self.run.get('id')) and self.run.get('id') not in self.release_acks
                    or self.pending or not self.fresh()):
                raise ControlError('client_busy_or_not_ready')
            if client is not None and client != self.client:
                raise ControlError('client_owner_mismatch')
            if self.run.get('id'):
                previous = self.output/self.run['id']
                finalized = self.run['status']=='completed' and self.run.get('evidenceStatus')=='saved' and (previous/'recording.json').is_file()
                if not finalized and not (previous/'release.json').is_file():
                    raise ControlError('previous_run_not_finalized')
            # Claim the request before any worker/API activity. An incomplete claim
            # is never retried automatically, including after process restart.
            claim.parent.mkdir(parents=True,exist_ok=True)
            try:
                descriptor = os.open(claim,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            except FileExistsError:
                raise ControlError('run_intent_already_claimed') from None
            with os.fdopen(descriptor,'w') as handle:
                json.dump(identity,handle); handle.flush(); os.fsync(handle.fileno())
            value = identity | {'status':'requesting', 'adapter':'full-client',
                        'startedAtMs':round(time.time()*1000),
                        'actionLimit':240 if duration_seconds==60 else 80,
                        'sdkRequestLimit':600 if duration_seconds==60 else 100, 'actions':0,
                        'controllerSeconds':duration_seconds+2,'apiTokenUpperBound':None,
                        'workerActive':True,
                        'client':self.client, 'recordingStatus':'pending', 'evidenceStatus':'pending'}
            if native_acceptance is not None:
                value.update(actionLimit=12,sdkRequestLimit=100,controllerSeconds=30,apiOutcome='not_started',publicationEligible=False)
            if adaptive_protocol is not None:
                value.update(actionLimit=adaptive_protocol['max_actions'],sdkRequestLimit=adaptive_protocol['max_sdk_requests'],
                    controllerSeconds=adaptive_protocol['wall_seconds'],cycleProgramSeconds=adaptive_protocol['program_seconds'],
                    protocol=ADAPTIVE_PROTOCOL,cycleNumber=0)
            folder = self.output/value['id']
            folder.mkdir(parents=True)
            write_json(folder/'request.json', value)
            write_json(folder/'controller.json', value)
            self.run = dict(value)
            self.capture_clock = None
            self.capture_clock_received_ms = None
            self.frame_transit = None
            self.readiness = None
            self.cancel_events[run_id] = threading.Event()
            retained = []
            try:
                for descriptor in lease_fds:
                    retained.append(os.dup(descriptor))
                self.leases[run_id] = retained
                threading.Thread(target=self._run, args=(value,), daemon=True).start()
            except Exception:
                for descriptor in retained: os.close(descriptor)
                self.leases.pop(run_id,None); self.cancel_events.pop(run_id,None)
                self.run.update(status='failed',reason='worker_start_failed',workerActive=False)
                write_json(folder/'controller.json',self.run)
                raise
        return {k:v for k,v in value.items() if k != 'client' and (private or k != 'dockerBinding')}

    def _run(self, run):
        if run.get('adaptiveProtocol') is not None:
            return self._run_adaptive(run)
        out = self.output / run['id']
        result = None
        started = time.monotonic()
        started_ms = run['startedAtMs']
        api_ms = 0
        meta = None
        timeline = {'api_started_ms': None, 'api_ended_ms': None}
        program_seconds = run['programSeconds']
        action_limit = run['actionLimit']
        sdk_request_limit = run['sdkRequestLimit']
        phase = 'initial_observation'
        api_outcome = 'not_started'
        final_controller = None
        progress_steps = []
        cancel_event = self.cancel_events.get(run['id'])
        input_deadline = None
        readiness_receipt = None
        readiness_sha256 = None

        def run_request(url, payload=None, timeout=3):
            sent_ms = round((time.monotonic()-started)*1000)
            reply = self.request(url,payload,timeout,run_id=run['id'],input_deadline=input_deadline)
            if (url.endswith('/v1/action') and isinstance(reply,dict) and reply.get('accepted') is True
                    and 'first_input_started_ms' not in timeline):
                # Anchor playback to an input that actually received a reply,
                # using the same monotonic origin as the program timeline.
                timeline['first_input_started_ms'] = sent_ms
                timeline['first_input_acked_ms'] = round((time.monotonic()-started)*1000)
            return reply

        try:
            if run.get('trialContext'):
                phase='capture_prepare'
                self._wait_for_capture(run['id'])
                phase='readiness'
                timeline['readiness_started_ms']=round((time.monotonic()-started)*1000)
                initial,readiness_receipt=self._wait_for_readiness(run,started)
                timeline['readiness_started_ms']=readiness_receipt['wait_started_run_ms']
                timeline['readiness_ended_ms']=readiness_receipt['qualified_run_ms']
            else:
                initial = run_request('/v1/observe')
            code, meta = native_program(run['nativeAcceptance']) if run.get('nativeAcceptance') else SMOKE_CODE, None
            if run['mode'] == 'api':
                api_started = None
                key = read_private_file(self.key_file).strip()
                prompt = PROMPT.format(program_seconds=program_seconds,
                                       action_limit=action_limit, sdk_request_limit=sdk_request_limit)
                phase = 'api_request'
                intent = {'model':run['model'],'status':'preparing',
                    'startedAtMs':round(time.time()*1000),'outputTokenLimit':3000,'timeoutSeconds':50,
                    'totalTokenLimit':run.get('totalTokenLimit'),'tokenUpperBound':None}
                write_json(out/'api-request.json', intent)
                requested = False

                def api_request(url, payload, credential, timeout):
                    nonlocal requested, api_outcome, api_started, readiness_receipt, readiness_sha256
                    if requested:
                        raise ControlError('api_request_limit')
                    with self.lock:
                        self._check_cancelled(run['id'])
                    if run.get('trialContext'):
                        if run.get('dockerBinding') is None:
                            raise ControlError('docker_binding_required')
                        validate_binding(run['dockerBinding'])
                    payload = payload | {'metadata':dict(payload.get('metadata', {}),maplebench_run_id=run['id'])}
                    # Conservative preflight estimate, not a provider-guaranteed
                    # input cap: UTF-8 bytes plus fixed envelope/metadata allowance.
                    bound = (len(payload['instructions'].encode())+len(payload['input'].encode())
                             +len(json.dumps(payload['text']['format']['schema']).encode())+1024+payload['max_output_tokens'])
                    run['apiTokenUpperBound'] = bound
                    with self.lock:
                        self.run['apiTokenUpperBound'] = bound
                    intent.update(tokenUpperBound=bound,tokenBoundMethod='conservative_utf8_schema_bytes_plus_1024_plus_max_output')
                    if run.get('totalTokenLimit') is not None and bound > run['totalTokenLimit']:
                        intent['status']='budget_rejected'
                        write_json(out/'api-request.json',intent)
                        raise ControlError('api_token_budget_too_small')
                    write_json(out/'api-request-body.json', payload)
                    with self.lock:
                        self._check_cancelled(run['id'])
                        if readiness_receipt is not None:
                            readiness_receipt=readiness_receipt | {'dispatch':self._readiness_dispatch(run,readiness_receipt)}
                            write_json(out/'readiness.json',readiness_receipt)
                            readiness_sha256=hashlib.sha256((out/'readiness.json').read_bytes()).hexdigest()
                            intent.update(readiness=readiness_receipt,readinessSha256=readiness_sha256)
                        intent['status']='requesting'
                        write_json(out/'api-request.json',intent)
                        # Disk synchronization can take time. Recheck after it,
                        # before marking the single provider request submitted.
                        try:
                            self._check_cancelled(run['id'])
                            if readiness_receipt is not None:
                                self._readiness_dispatch(run,readiness_receipt)
                        except ControlError:
                            intent['status']='readiness_rejected'
                            write_json(out/'api-request.json',intent)
                            raise
                        api_started=time.monotonic()
                        timeline['api_started_ms']=round((api_started-started)*1000)
                        requested = True
                        api_outcome = 'uncertain'
                    response = bounded_request(url, payload, credential, timeout)
                    write_json(out/'api-response.json', response)
                    api_outcome = 'receipt_saved'
                    if run.get('trialContext') and (not isinstance(response.get('metadata'),dict)
                            or response['metadata'].get('maplebench_run_id')!=run['id']):
                        raise ControlError('api_run_identity_mismatch')
                    return response

                try:
                    choice, meta = model_decision(run['model'], prompt, {'observation':initial}, key,
                                                 output_tokens=3000, timeout=50, request_fn=api_request)
                finally:
                    del key
                api_ms = round((time.monotonic()-api_started)*1000) if api_started is not None else 0
                timeline['api_ended_ms'] = round((time.monotonic()-started)*1000)
                write_json(out/'response.json', meta)
                api_outcome = 'receipt_saved'
                with self.lock:
                    self._check_cancelled(run['id'])
                phase = 'api_validation'
                if not choice:
                    raise ControlError('api_invalid_program')
                if meta.get('model') != run['model']:
                    raise ControlError('api_model_mismatch')
                code = choice['code']
                write_json(out/'program.json', choice)
            else:
                write_json(out/'program.json', {'note':'Scripted native acceptance; no model' if run.get('nativeAcceptance') else 'Deterministic adapter smoke test; no model', 'code':code})
            write_bytes(out/'program.js', code.encode())
            phase = 'program_start'
            run_request('/v1/observe')
            with self.lock:
                self._check_cancelled(run['id'])
                self.run.update(status='running', returnedModel=meta.get('model') if meta else None)
                write_json(out/'controller.json',self.run)
            # A renderer must acknowledge a started recorder and an actual
            # post-render frame. A fixed delay cannot establish capture coverage.
            self._wait_for_capture(run['id'])
            timeline['program_started_ms'] = round((time.monotonic()-started)*1000)
            with self.lock:
                self._check_cancelled(run['id'])
                self.run.update(programStartedAtMs=round(time.time()*1000))

            def record_progress(step):
                with self.lock:
                    if self.run.get('id') == run['id'] and self.run.get('status') == 'running':
                        progress_steps.append(step)
                        if step.get('method') == 'pressKeys' and step.get('result', {}).get('accepted') is True:
                            self.run['actions'] += 1

            phase = 'program_execution'
            program_started=time.monotonic()
            input_deadline=program_started+program_seconds
            result = execute_program(code, SCENARIO | ({'protocol':run['nativeAcceptance']['id']} if run.get('nativeAcceptance') else {}), 'http://127.0.0.1:8840',
                                     deadline=time.monotonic()+program_seconds+2, program_seconds=program_seconds,
                                     max_actions=action_limit, max_requests=sdk_request_limit,
                                     request_fn=run_request, step_callback=record_progress,cancel_event=cancel_event,
                                     **({'docker_binding':run['dockerBinding']} if run.get('dockerBinding') else {}),
                                     **({'docker_image':run['dockerImageId']} if run.get('dockerImageId') else {}))
            timeline['program_ended_ms'] = round((time.monotonic()-started)*1000)
            phase = 'final_observation'
            final = run_request('/v1/observe')
            if (result['reason']=='program_timeout' and result.get('error') is None
                    and time.monotonic()-program_started>=program_seconds):
                result['reason']='time_limit'
            interrupted = any(step.get('method') == 'pressKeys' and step.get('result', {}).get('accepted') is not True
                              for step in result['steps'])
            acknowledged = sum(step.get('kind')=='sdk' and step.get('method')=='pressKeys'
                               and step.get('result',{}).get('accepted') is True for step in result['steps'])
            complete_receipts = (type(result.get('actions')) is int and result['actions']==acknowledged
                                 and result['steps']==progress_steps
                                 and not any(step.get('kind')=='sdk_error' for step in result['steps']))
            legitimate=(result['reason']=='program_complete'
                or result['reason']=='death' and final['character']['alive'] is False
                or result['reason']=='action_limit' and result['actions']==action_limit
                or result['reason']=='time_limit' and time.monotonic()-program_started>=program_seconds)
            status = 'completed' if legitimate and result.get('error') is None and not interrupted and complete_receipts else 'failed'
            reason = ('action_receipt_mismatch' if not complete_receipts and result.get('error') is None
                      else 'input_interrupted' if interrupted and result.get('error') is None else result['reason'])
            timeline['status'] = status
            phase = 'evidence_save'
            result_document = {'controller':run | {'status':status, 'reason':reason,'workerActive':False,'actions':result['actions'], 'returnedModel':meta.get('model') if meta else None}, 'program':result, 'initial':initial,
                                         'final':final, 'source':'full-client-trial' if run.get('trialContext') else 'client telemetry; unscored integration run',
                                         'trialContext':run.get('trialContext'),
                                         **({'protocol':run['nativeAcceptance']['id'],'nativeAcceptance':run['nativeAcceptance'],'model_api_requests':0,
                                              'publication_eligible':False,'score':None} if run.get('nativeAcceptance') else {}),
                                         'timing':{'startedAtMs':started_ms, 'endedAtMs':round(time.time()*1000),
                                                   'elapsedMs':round((time.monotonic()-started)*1000),
                                                   'apiLatencyMs':api_ms},
                                         'api':meta,
                                         **({'readiness':readiness_receipt,'readinessSha256':readiness_sha256}
                                            if readiness_receipt is not None else {}),
                                         'timeline':timeline,
                                         'programSha256':hashlib.sha256(code.encode()).hexdigest(),
                                         'observedXpDelta':final['character']['exp']-initial['character']['exp']
                                             if final['character']['level']==initial['character']['level'] else None}
            publication = {
                'schema_version':1, 'run_kind':'native_acceptance' if run.get('nativeAcceptance') else 'integration',
                'result':result_document,
                'budgets':{'api_requests':1 if run['mode']=='api' else 0, 'output_tokens':0 if run.get('nativeAcceptance') else 3000,
                           'total_tokens':run.get('totalTokenLimit'), 'program_ms':program_seconds*1000,
                           'run_ms':(program_seconds+(63 if readiness_receipt is not None else 53))*1000, 'actions':action_limit,
                           'sdk_requests':sdk_request_limit},
                'timeline':timeline,
                'scenario':{'id':'hero-full-client-skeletons-integration',
                            'fingerprint':None, 'reset_fingerprint':None},
                'score':None, 'video':None}
            with self.lock:
                self._check_cancelled(run['id'])
                if (out/'recording.json').is_file():
                    publication['video'] = json.loads((out/'recording.json').read_text())
                write_json(out/'result.json',result_document)
                write_json(out/'publication.json', publication)
                self.run.update(status=status, reason=reason, actions=result['actions'], evidenceStatus='saved')
                final_controller = dict(self.run)
                write_json(out/'controller.json', final_controller)
        except Exception as error:
            # Avoid writing arbitrary exception strings from credential-bearing I/O.
            reason = (error.code if isinstance(error, ControlError) else str(error)
                      if isinstance(error, DockerBindingError) else type(error).__name__)
            if result is None and progress_steps:
                result = {'reason':reason,'actions':sum(step.get('method')=='pressKeys'
                              and step.get('result',{}).get('accepted') is True for step in progress_steps),
                          'steps':progress_steps,'error':reason}
            with self.lock:
                self.run.update(status='failed', reason=reason, failurePhase=phase,
                                apiOutcome=api_outcome, evidenceStatus='failed')
                final_controller = dict(self.run)
            try:
                if phase=='readiness':
                    timeline['readiness_ended_ms']=round((time.monotonic()-started)*1000)
                write_json(out/'failure.json', {'controller':final_controller, 'error':reason,
                    'phase':phase,'apiOutcome':api_outcome,'program':result,'timeline':timeline,
                    **({'readiness':readiness_receipt,'readinessSha256':readiness_sha256}
                       if readiness_receipt is not None else {})})
            except OSError:
                pass
        finally:
            with self.lock:
                if self.leases.get(run['id']) and self.run.get('status')=='failed' and not self._cancelled(run['id']):
                    try:
                        cancellation=self.output/'cancellations'/f'{run["id"]}.json'
                        cancellation.parent.mkdir(parents=True,exist_ok=True)
                        write_json(cancellation,{'runId':run['id'],'requestedAtMs':round(time.time()*1000),
                            'reason':'worker_failed','apiOutcomeAtCancellation':api_outcome})
                    except OSError:
                        # No input can resume; retain the locks for explicit repair.
                        self.run.update(reason='release_journal_failed',evidenceStatus='failed')
                retain_lease=bool(self.leases.get(run['id']) and self.run.get('status')=='failed'
                    and run['id'] not in self.release_acks)
                self.run['leaseReleasePending']=retain_lease
                if final_controller is not None:
                    final_controller['workerActive'] = False
                    final_controller['leaseReleasePending']=retain_lease
                if self.run.get('id')==run['id']:
                    self.run['workerActive'] = False
                try:
                    write_json(out/'controller.json', final_controller or run)
                except OSError:
                    if self.run.get('id') == run['id']:
                        self.run.update(status='failed',reason='evidence_write_failed',evidenceStatus='failed')
                finally:
                    self.cancel_events.pop(run['id'],None)
                    if not retain_lease:
                        for descriptor in self.leases.pop(run['id'],[]): os.close(descriptor)

    def _run_adaptive(self, run):
        """Actual adaptive API execution; intentionally separate evidence schema."""
        out=self.output/run['id'];started=time.monotonic()-(time.time()-run['startedAtMs']/1000);final_controller=None
        readiness=None;trace=None;api_outcome='not_started';input_deadline=None;first_input={};adaptive_started=None
        def check_cancelled():
            with self.lock:
                try:self._check_cancelled(run['id'])
                except ControlError as error:raise AdaptiveError(error.code) from None
        def persist_bytes(name,raw):
            path=out/name
            if Path(name).is_absolute() or '..' in Path(name).parts:raise ControlError('invalid_adaptive_artifact_path')
            path.parent.mkdir(parents=True,exist_ok=True)
            write_bytes(path,raw)
            return {'path':name,'sha256':hashlib.sha256(raw).hexdigest()}
        def persist_json(name,value):
            return persist_bytes(name,json.dumps(value,allow_nan=False,separators=(',',':')).encode()+b'\n')
        def request(url,payload=None,timeout=3):
            sent=time.monotonic()
            value=self.request(url,payload,timeout,run_id=run['id'],input_deadline=input_deadline)
            if url.endswith('/v1/action') and value.get('accepted') is True and not first_input:
                first_input.update(started=sent,acked=time.monotonic())
            return value
        def phase(**value):
            nonlocal input_deadline,adaptive_started,readiness
            input_deadline=value['deadline'];adaptive_started=input_deadline-300
            if value['phase']=='preparing':return
            if value['phase']=='requesting':
                if run.get('dockerBinding') is not None:validate_binding(run['dockerBinding'])
                if readiness is not None and value['cycle']==0:
                    with self.lock:
                        readiness=readiness|{'dispatch':self._readiness_dispatch(run,readiness)}
                        write_json(out/'readiness.json',readiness)
                        check_cancelled();self._readiness_dispatch(run,readiness)
            with self.lock:
                check_cancelled()
                self.run.update(status='running' if value['phase']=='waiting_for_deadline' else value['phase'],
                    adaptivePhase=value['phase'],cycleNumber=value['cycle'],
                    adaptiveStartedAtMs=round((time.time()-(time.monotonic()-adaptive_started))*1000),
                    apiRequestsStarted=value['counters']['api_requests_started'],
                    apiTokenUpperBound=value['counters']['reserved_tokens'])
                self.run.setdefault('programStartedAtMs',round(time.time()*1000))
                write_json(out/'controller.json',self.run)
        def progress(step):
            with self.lock:
                if self.run.get('id')==run['id'] and step.get('method')=='pressKeys' and step.get('result',{}).get('accepted') is True:
                    self.run['actions']+=1
        def provider(url,body,timeout):
            nonlocal readiness,api_outcome
            check_cancelled()
            remaining=min(timeout,input_deadline-time.monotonic())
            if remaining<=0:raise AdaptiveError('adaptive_wall_deadline')
            key=read_private_file(self.key_file).strip();api_outcome='uncertain'
            try:return bounded_request(url,body,key,remaining)
            finally:del key
        def execute(code,**kwargs):
            return execute_program(code,SCENARIO|{'protocol':ADAPTIVE_PROTOCOL},'http://127.0.0.1:8840',request_fn=request,
                cancel_event=self.cancel_events.get(run['id']),
                **({'docker_binding':run['dockerBinding']} if run.get('dockerBinding') else {}),
                **({'docker_image':run['dockerImageId']} if run.get('dockerImageId') else {}),**kwargs)
        try:
            self._wait_for_capture(run['id'])
            if run.get('trialContext'):
                initial,readiness=self._wait_for_readiness(run,started)
            else:initial=request('/v1/observe')
            value=run_adaptive(run_id=run['id'],model=run['model'],protocol=run['adaptiveProtocol'],
                initial=initial,observe=lambda timeout:request('/v1/observe',timeout=timeout),request_api=provider,
                execute=execute,persist_json=persist_json,persist_bytes=persist_bytes,cancel_check=check_cancelled,
                on_phase=phase,on_step=progress,clock=time.monotonic,wall_clock=time.time)
            trace=value['trace'];api_outcome=('confirmed' if trace['counters']['api_requests_started']==trace['counters']['api_responses_confirmed']
                else 'uncertain' if trace['counters']['api_requests_started'] else 'not_started')
            if first_input:
                trace['timing'].update(first_input_started_ms=round((first_input['started']-adaptive_started)*1000),
                    first_input_acked_ms=round((first_input['acked']-adaptive_started)*1000))
            trace_ref=persist_json('adaptive.json',trace)
            # This terminal observation is diagnostic and cannot authorize input
            # after the wall deadline or stand in for persisted XP collection.
            final=request('/v1/observe')
            status,reason=trace['status'],trace['reason'];counters=trace['counters']
            origin=trace['timing']['wall_started_at_ms']-run['startedAtMs']
            api_cycles=[c for c in trace['cycles'] if c.get('api_outcome')=='confirmed']
            ended_wall=round(time.time()*1000);terminal_ms=ended_wall-run['startedAtMs']
            timeline={'adaptive_started_ms':origin,
                'adaptive_ended_ms':terminal_ms,
                'api_started_ms':origin+api_cycles[0]['timing']['api_started_ms'] if api_cycles else None,
                'api_ended_ms':origin+api_cycles[-1]['timing']['api_ended_ms'] if api_cycles else None,
                'program_started_ms':origin,'program_ended_ms':terminal_ms,
                'readiness_started_ms':readiness['wait_started_run_ms'] if readiness else None,
                'readiness_ended_ms':readiness['qualified_run_ms'] if readiness else None,
                'first_input_started_ms':origin+trace['timing']['first_input_started_ms'] if first_input else None,
                'first_input_acked_ms':origin+trace['timing']['first_input_acked_ms'] if first_input else None,
                'status':status}
            result={'schema_version':1,'protocol':ADAPTIVE_PROTOCOL,'source':'full-client-adaptive-pilot',
                'controller':run|{'status':status,'reason':reason,'workerActive':False,
                    'actions':counters['actions'],'returnedModel':run['model'] if counters['api_responses_confirmed'] else None},
                'initial':initial,'final':final,'readiness':readiness,
                'readinessSha256':hashlib.sha256((out/'readiness.json').read_bytes()).hexdigest() if readiness else None,
                'adaptive':trace,'adaptiveTrace':trace_ref,'timeline':timeline,
                'trialContext':run.get('trialContext'),'program':{'actions':counters['actions'],
                    'actionAttempts':counters['action_attempts'],'rpcRequests':counters['sdk_requests'],'steps':value['steps'],
                    'reason':reason,'error':trace['error']},
                'timing':{'startedAtMs':run['startedAtMs'],'endedAtMs':ended_wall,
                    'elapsedMs':round((time.monotonic()-started)*1000),
                    'apiLatencyMs':sum(c['timing'].get('api_ended_ms',c['timing'].get('api_started_ms',0))-c['timing'].get('api_started_ms',0)
                                       for c in trace['cycles'])},
                'observedXpDelta':final['character']['exp']-initial['character']['exp']
                    if final['character']['level']==initial['character']['level'] else None,
                'persistedNetXp':None,'authoritativePeakXpPerMinute':None,
                'publicationEligible':False,'publicationBlocker':'adaptive_trial_evidence_adapter_required'}
            publication={'schema_version':3,'protocol':ADAPTIVE_PROTOCOL,'run_kind':'adaptive_pilot',
                'result':result,'video':json.loads((out/'recording.json').read_text()) if (out/'recording.json').is_file() else None,
                'score':None,'publication_eligible':False,'reason':'adaptive_trial_evidence_adapter_required'}
            with self.lock:
                check_cancelled();persist_json('result.json',result);persist_json('publication.json',publication)
                self.run.update(status=status,reason=reason,actions=counters['actions'],apiOutcome=api_outcome,
                    returnedModel=result['controller']['returnedModel'],evidenceStatus='saved' if status=='completed' else 'failed')
                final_controller=dict(self.run)
                write_json(out/'controller.json',final_controller)
        except Exception as error:
            reason=error.code if isinstance(error,ControlError) else str(error) if isinstance(error,(AdaptiveError,DockerBindingError)) else type(error).__name__
            with self.lock:
                self.run.update(status='failed',reason=reason,failurePhase='adaptive_controller',
                    apiOutcome=api_outcome,evidenceStatus='failed');final_controller=dict(self.run)
            try:write_json(out/'failure.json',{'controller':final_controller,'error':reason,'adaptive':trace,'apiOutcome':api_outcome})
            except OSError:pass
        finally:
            # Match the legacy worker's no-replay cleanup contract. Failed leased
            # attempts retain ownership until explicit cancellation/release.
            with self.lock:
                if self.leases.get(run['id']) and self.run.get('status')=='failed' and not self._cancelled(run['id']):
                    try:
                        cancellation=self.output/'cancellations'/f'{run["id"]}.json';cancellation.parent.mkdir(parents=True,exist_ok=True)
                        write_json(cancellation,{'runId':run['id'],'requestedAtMs':round(time.time()*1000),
                            'reason':'worker_failed','apiOutcomeAtCancellation':api_outcome})
                    except OSError:self.run.update(reason='release_journal_failed',evidenceStatus='failed')
                retain=bool(self.leases.get(run['id']) and self.run.get('status')=='failed' and run['id'] not in self.release_acks)
                self.run.update(workerActive=False,leaseReleasePending=retain)
                if final_controller is not None:final_controller.update(workerActive=False,leaseReleasePending=retain)
                try:write_json(out/'controller.json',final_controller or self.run)
                except OSError:self.run.update(status='failed',reason='evidence_write_failed',evidenceStatus='failed')
                finally:
                    self.cancel_events.pop(run['id'],None)
                    if not retain:
                        for descriptor in self.leases.pop(run['id'],[]):os.close(descriptor)
