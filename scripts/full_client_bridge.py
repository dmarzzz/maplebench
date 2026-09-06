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

from maple_agent import MODELS, bounded_request, execute_program, model_decision, validate_rpc
from full_client_capture import capture_receipt


class ControlError(ValueError):
    """A credential-free failure code that is safe to show in the live UI."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


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
                    if (folder/'release.json').stat().st_size>128*1024: raise ValueError('invalid_release')
                    release=json.loads((folder/'release.json').read_text())
                except (OSError,ValueError,RecursionError,UnicodeError):
                    release={}
                if not isinstance(release,dict) or release.get('quarantineId')!=quarantine['id']:
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
                    api_outcome = 'not_started' if intent.get('status') in ('preparing','budget_rejected') else 'uncertain'
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
            valid_frame = obs['ready'] and max(age, render_age) < 1500
            hud = body.get('renderedHud')
            hud = {k:hud[k] for k in ('hp', 'mp', 'maxHp', 'maxMp')} if isinstance(hud, dict) and all(
                _number(hud.get(k)) for k in ('hp', 'mp', 'maxHp', 'maxMp')) else None
            self.observation = obs | {'ageMs':age, 'renderAgeMs':render_age, 'renderedHud':hud} if valid_frame else {'ready': False}
            self.last_seen = now
            self.fresh_until = now + (1500-max(age, render_age))/1000 if valid_frame else now
            capture=body.get('capture')
            self.run['captureReady']=bool(self.run.get('id') and valid_frame and isinstance(capture,dict)
                and capture.get('runId')==self.run.get('id') and capture.get('started') is True
                and type(capture.get('renderedFrames')) is int and 0<capture['renderedFrames']<=100000
                and capture.get('interrupted') is False and body.get('captureState')=='recording')
            if self.run['captureReady'] and not self.run.get('captureReadyAtMs'):
                self.run['captureReadyAtMs']=server_received_ms
                write_json(self.output/self.run['id']/'capture-ready.json',
                    {'runId':self.run['id'],'serverReceivedAtMs':server_received_ms,'renderedFrames':capture['renderedFrames']})
            if self.run['captureReady']: self.lock.notify_all()
            if self.run.get('id') and _number(body.get('clientSentAtMs')):
                if not self.run.get('captureClockAccepted'):
                    if self.capture_clock and body.get('captureClockAck')==self.capture_clock['id']:
                        self.run['captureClockAccepted']=self.capture_clock['id']
                        write_json(self.output/self.run['id']/'capture-clock.json',self.capture_clock)
                    else:
                        self.capture_clock={'id':uuid.uuid4().hex,'client_sent_ms':body['clientSentAtMs'],
                            'server_received_ms':server_received_ms,'server_sent_ms':round(time.time()*1000)}
            if (self.run.get('id') and (self.output/self.run['id']).is_dir()
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
            if valid_frame and self.pending and not self._cancelled(self.pending.get('runId')) and not self.pending.get('sent') and self.pending['deadline'] > now:
                self.pending['sent'] = True
                self.pending['sentAt'] = now
                command = {k: self.pending[k] for k in ('id', 'keys', 'durationMs')}
                command['runId'] = self.run.get('id')
            return {'command': command, 'run': {k:v for k,v in self.run.items() if k != 'client'},
                    'clock':self.capture_clock,
                    'releaseKeys':{'runId':self.run['id']} if self._cancelled(self.run.get('id')) else None}

    def request(self, url, payload=None, timeout=3, *, run_id=None):
        with self.lock:
            run_id = run_id or self.run.get('id')
            self._check_cancelled(run_id)
            if not self.fresh():
                raise ControlError('client_state_stale')
            if url.endswith('/v1/observe'):
                return self._snapshot()
            if not url.endswith('/v1/action') or not isinstance(payload, dict) or payload.get('type') != 'press_keys':
                raise ValueError('Only full-client keyboard actions are supported')
            _, action = validate_rpc({'type':'rpc','id':1,'method':'pressKeys','args':[payload.get('keys'),payload.get('durationMs')]}, SCENARIO)
            if self.pending:
                raise ValueError('Another input is in flight')
            pending = {'id': uuid.uuid4().hex, 'keys': action['keys'], 'durationMs': action['durationMs'],
                       'runId':run_id,
                       'deadline': time.monotonic() + min(timeout, 3)}
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

    def status(self):
        with self.lock:
            return {'run':{k:v for k,v in self.run.items() if k != 'client'},
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
            elif owner.get('trialContext'):
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

    def _existing_run(self, identity):
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
        return {k:v for k,v in controller.items() if k != 'client'}

    def release_failed_run(self, run_id):
        """Explicit trusted-operator acknowledgment; never exposed by HTTP."""
        if not isinstance(run_id,str) or not re.fullmatch('[a-f0-9]{32}',run_id):
            raise ControlError('invalid_run_identity')
        with self.lock:
            if run_id in self.quarantines:
                folder=self.output/run_id
                write_json(folder/'release.json',{'runId':run_id,'quarantineId':self.quarantines[run_id],
                    'reason':'operator_acknowledged_corrupt_evidence','releasedAtMs':round(time.time()*1000)})
                previous=json.loads((folder/'controller.json').read_text())
                previous.update(failureAcknowledged=True,quarantined=False)
                write_json(folder/'controller.json',previous)
                if self.run.get('id')==run_id: self.run.update(previous)
                del self.quarantines[run_id]
                return
            if (self.run.get('id') != run_id or self.run['status'] not in ('failed','completed')
                    or self.pending or self.run.get('workerActive') or self.leases.get(run_id)):
                raise ControlError('run_cannot_be_released')
            folder = self.output/run_id
            if self.run['status'] == 'completed' and (folder/'recording.json').is_file():
                raise ControlError('successful_run_cannot_be_discarded')
            write_json(folder/'release.json', {'runId':run_id,'reason':'operator_acknowledged_failure',
                                             'releasedAtMs':round(time.time()*1000)})
            if self.run['status'] == 'completed':
                self.run.update(status='failed',reason='recording_abandoned',recordingStatus='discarded')
            self.run['failureAcknowledged'] = True
            write_json(folder/'controller.json',self.run)

    def start(self, mode, model=None, duration_seconds=22, *, client=None, run_id=None, request_id=None,
              total_token_limit=None, trial_context=None, docker_image_id=None, lease_fds=()):
        if mode not in ('script', 'api') or (mode == 'api' and model not in MODELS):
            raise ValueError('Invalid controller selection')
        if type(duration_seconds) is not int or duration_seconds not in (22, 60):
            raise ValueError('Run duration must be 22 or 60 seconds')
        if mode == 'script' and duration_seconds != 22:
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
        run_id = run_id or request_id or uuid.uuid4().hex
        request_id = request_id or run_id
        identity = {'id':run_id,'requestId':request_id,'mode':mode,
                    'model':model if mode=='api' else None,'programSeconds':duration_seconds,
                    'totalTokenLimit':total_token_limit,'trialContext':trial_context,'dockerImageId':docker_image_id}
        with self.lock:
            claim = self.output/'requests'/f'{request_id}.json'
            if claim.exists():
                try:
                    previous = json.loads(claim.read_text())
                except (OSError, ValueError, RecursionError):
                    raise ControlError('run_intent_incomplete') from None
                if previous != identity:
                    raise ControlError('run_intent_conflict')
                return self._existing_run(identity)
            if (self.output/run_id).exists():
                return self._existing_run(identity)
            self._check_cancelled(run_id)
            if self.quarantines:
                raise ControlError('corrupt_runs_require_acknowledgment')
            if trial_context is not None and (not isinstance(lease_fds,(tuple,list)) or len(lease_fds)!=2
                    or not all(type(fd) is int for fd in lease_fds)):
                raise ControlError('trial_requires_guard_lock_descriptors')
            if mode == 'api' and (not self.key_file or not self.key_file.is_file()):
                raise ValueError('API key file is not configured')
            if (self.run['status'] in ('requesting', 'running') or self.run.get('workerActive') or self.leases
                    or self._cancelled(self.run.get('id')) and self.run.get('id') not in self.release_acks
                    or self.pending or not self.fresh()):
                raise ValueError('Client busy or not ready')
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
            folder = self.output/value['id']
            folder.mkdir(parents=True)
            write_json(folder/'request.json', value)
            write_json(folder/'controller.json', value)
            self.run = dict(value)
            self.capture_clock = None
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
        return {k:v for k,v in value.items() if k != 'client'}

    def _run(self, run):
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

        def run_request(url, payload=None, timeout=3):
            return self.request(url,payload,timeout,run_id=run['id'])

        try:
            if run.get('trialContext'):
                phase='capture_prepare'
                self._wait_for_capture(run['id'])
                phase='initial_observation'
            initial = run_request('/v1/observe')
            code, meta = SMOKE_CODE, None
            if run['mode'] == 'api':
                api_started = time.monotonic()
                timeline['api_started_ms'] = round((api_started-started)*1000)
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
                    nonlocal requested, api_outcome
                    if requested:
                        raise ControlError('api_request_limit')
                    with self.lock:
                        self._check_cancelled(run['id'])
                    requested = True
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
                    intent['status']='requesting'
                    with self.lock:
                        self._check_cancelled(run['id'])
                        write_json(out/'api-request.json',intent)
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
                api_ms = round((time.monotonic()-api_started)*1000)
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
                write_json(out/'program.json', {'note':'Deterministic adapter smoke test; no model', 'code':code})
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
                progress_steps.append(step)
                if step.get('method') != 'pressKeys' or step.get('result', {}).get('accepted') is not True:
                    return
                with self.lock:
                    if self.run.get('id') == run['id'] and self.run.get('status') == 'running':
                        self.run['actions'] += 1

            phase = 'program_execution'
            program_started=time.monotonic()
            result = execute_program(code, SCENARIO, 'http://127.0.0.1:8840',
                                     deadline=time.monotonic()+program_seconds+2, program_seconds=program_seconds,
                                     max_actions=action_limit, max_requests=sdk_request_limit,
                                     request_fn=run_request, step_callback=record_progress,cancel_event=cancel_event,
                                     **({'docker_image':run['dockerImageId']} if run.get('dockerImageId') else {}))
            timeline['program_ended_ms'] = round((time.monotonic()-started)*1000)
            phase = 'final_observation'
            final = run_request('/v1/observe')
            if (result['reason']=='program_timeout' and result.get('error') is None
                    and time.monotonic()-program_started>=program_seconds):
                result['reason']='time_limit'
            interrupted = any(step.get('method') == 'pressKeys' and step.get('result', {}).get('accepted') is not True
                              for step in result['steps'])
            legitimate=(result['reason']=='program_complete'
                or result['reason']=='death' and final['character']['alive'] is False
                or result['reason']=='action_limit' and result['actions']==action_limit
                or result['reason']=='time_limit' and time.monotonic()-program_started>=program_seconds)
            status = 'completed' if legitimate and not interrupted else 'failed'
            reason = 'input_interrupted' if interrupted else result['reason']
            timeline['status'] = status
            phase = 'evidence_save'
            result_document = {'controller':run | {'status':status, 'workerActive':False,'actions':result['actions'], 'returnedModel':meta.get('model') if meta else None}, 'program':result, 'initial':initial,
                                         'final':final, 'source':'full-client-trial' if run.get('trialContext') else 'client telemetry; unscored integration run',
                                         'trialContext':run.get('trialContext'),
                                         'timing':{'startedAtMs':started_ms, 'endedAtMs':round(time.time()*1000),
                                                   'elapsedMs':round((time.monotonic()-started)*1000),
                                                   'apiLatencyMs':api_ms},
                                         'api':meta,
                                         'timeline':timeline,
                                         'programSha256':hashlib.sha256(code.encode()).hexdigest(),
                                         'observedXpDelta':final['character']['exp']-initial['character']['exp']
                                             if final['character']['level']==initial['character']['level'] else None}
            publication = {
                'schema_version':1, 'run_kind':'integration',
                'result':result_document,
                'budgets':{'api_requests':1 if run['mode']=='api' else 0, 'output_tokens':3000,
                           'total_tokens':run.get('totalTokenLimit'), 'program_ms':program_seconds*1000,
                           'run_ms':(program_seconds+53)*1000, 'actions':action_limit,
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
            reason = error.code if isinstance(error, ControlError) else type(error).__name__
            if result is None and progress_steps:
                result = {'reason':reason,'actions':sum(step.get('method')=='pressKeys' for step in progress_steps),
                          'steps':progress_steps,'error':reason}
            with self.lock:
                self.run.update(status='failed', reason=reason, failurePhase=phase,
                                apiOutcome=api_outcome, evidenceStatus='failed')
                final_controller = dict(self.run)
            try:
                write_json(out/'failure.json', {'controller':final_controller, 'error':reason,
                    'phase':phase,'apiOutcome':api_outcome,'program':result,'timeline':timeline})
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
