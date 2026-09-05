#!/usr/bin/env python3
"""Durable single-world batch queue. All runtime state and secrets stay outside Git."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import tempfile
import time
import urllib.request
import uuid

REPO = Path(__file__).resolve().parent.parent
# Resolve sibling modules from this copy, including immutable batch snapshots.
sys.path.insert(0, str(Path(__file__).resolve().parent))
MODELS = ['gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna']
TERMINAL = {'completed', 'infrastructure_error', 'budget_exhausted', 'cancelled'}
SLUG = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}$')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,prefix='.'+path.name+'.',delete=False) as f:
        temporary=Path(f.name)
        try:
            f.write(json.dumps(value,indent=2)+'\n'); f.flush(); os.fsync(f.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True); raise
    try: os.replace(temporary,path)
    finally: temporary.unlink(missing_ok=True)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def bounded_int(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer in [{minimum}, {maximum}]')
    return value


def validate_manifest(config):
    if not isinstance(config,dict): raise ValueError('Manifest must be an object')
    known={'control_mode','name','models','scenarios','repetitions','duration_seconds','program_seconds','max_calls_per_trial','max_tokens_per_trial','max_api_calls','max_total_tokens','max_attempts','max_actions_per_trial'}
    if set(config)-known: raise ValueError('Unknown manifest fields')
    config = dict(config)
    models = config.get('models', MODELS)
    if not isinstance(models, list) or not models or len(set(models)) != len(models) or any(m not in MODELS for m in models):
        raise ValueError('models must be a unique nonempty list of supported OpenAI API models')
    scenarios = config.get('scenarios', [])
    if not isinstance(scenarios, list) or not scenarios or any(not isinstance(s, str) or not SLUG.fullmatch(s) for s in scenarios):
        raise ValueError('scenarios must be scenario identifiers')
    config['models'] = models
    config['repetitions'] = bounded_int(config.get('repetitions', 1), 'repetitions', 1, 50)
    if len(models) * len(scenarios) * config['repetitions'] > 200:
        raise ValueError('A batch is limited to 200 trials')
    defaults = {'max_calls_per_trial': (12, 1, 120), 'max_tokens_per_trial': (20000, 1024, 500000),
                'max_api_calls': (240, 1, 10000), 'max_total_tokens': (400000, 1024, 10000000),
                'max_actions_per_trial': (500, 1, 10000), 'max_attempts': (2, 1, 3), 'program_seconds': (20, 1, 60)}
    for key, (default, low, high) in defaults.items():
        config[key] = bounded_int(config.get(key, default), key, low, high)
    if 'duration_seconds' in config:
        config['duration_seconds'] = bounded_int(config['duration_seconds'], 'duration_seconds', 5, 1800)
    if config.get('control_mode', 'serial') not in ('serial', 'continuous'):
        raise ValueError('Unknown controller mode')
    config['control_mode'] = config.get('control_mode', 'serial')
    config['backend'] = 'cosmic-v83'
    config['randomness'] = 'unseeded combat; identical initial database snapshot'
    return config


class Queue:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / 'queue.sqlite3', timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, config TEXT NOT NULL, created REAL NOT NULL, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS trials(id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id),
              ordinal INTEGER NOT NULL, model TEXT NOT NULL, scenario TEXT NOT NULL, repetition INTEGER NOT NULL,
              status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0, result TEXT, attempt_dir TEXT);
            CREATE TABLE IF NOT EXISTS attempts(trial_id TEXT NOT NULL REFERENCES trials(id), number INTEGER NOT NULL,
              status TEXT NOT NULL, reserved_calls INTEGER NOT NULL, reserved_tokens INTEGER NOT NULL,
              used_calls INTEGER, used_tokens INTEGER, started REAL NOT NULL, finished REAL,
              error TEXT, PRIMARY KEY(trial_id,number));
        ''')
        self.db.commit()

    def config(self, batch):
        row = self.db.execute('SELECT config FROM batches WHERE id=?', (batch,)).fetchone()
        if not row: raise ValueError('Unknown batch')
        return json.loads(row['config'])

    def usage(self, batch):
        row = self.db.execute('''SELECT COALESCE(SUM(COALESCE(a.used_calls,a.reserved_calls)),0) calls,
            COALESCE(SUM(COALESCE(a.used_tokens,a.reserved_tokens)),0) tokens
            FROM attempts a JOIN trials t ON t.id=a.trial_id WHERE t.batch_id=?''', (batch,)).fetchone()
        return dict(row)

    def recover(self):
        # Called only while holding the global world lock. Preserve every interrupted
        # attempt and charge its reservation; uncertain provider usage is never free.
        rows = self.db.execute("SELECT * FROM trials WHERE status='running'").fetchall()
        for t in rows:
            conf = self.config(t['batch_id'])
            saved = self.root / t['batch_id'] / (t['attempt_dir'] or '') / 'score.json'
            try:
                result=json.loads(saved.read_text())
                valid=result.get('backend')=='cosmic-v83' and result.get('model')==t['model'] and result.get('trialId')==t['id'] and result.get('attempt')==t['attempt']
            except (OSError,ValueError,TypeError): valid=False
            if valid:
                infra=result.get('reason') in {'api_error','error','infrastructure_error'}
                self.finish(dict(t),result,infrastructure=infra)
                if not infra:
                    with self.db: self.db.execute("UPDATE trials SET status='rendering' WHERE id=?",(t['id'],))
                continue
            status = 'queued' if t['attempt'] < conf['max_attempts'] else 'infrastructure_error'
            with self.db:
                self.db.execute("UPDATE attempts SET status='interrupted',finished=?,error='worker interrupted' WHERE trial_id=? AND number=?", (time.time(), t['id'], t['attempt']))
                self.db.execute('UPDATE trials SET status=?,result=? WHERE id=?', (status, json.dumps({'reason':'interrupted','error':'worker interrupted'}), t['id']))
        return len(rows)

    def claim(self, batch=None):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            where = "t.status='queued'" + (' AND t.batch_id=?' if batch else '')
            candidates = self.db.execute(f'SELECT t.* FROM trials t JOIN batches b ON b.id=t.batch_id WHERE {where} ORDER BY b.created,t.ordinal', (batch,) if batch else ()).fetchall()
            for row in candidates:
                t = dict(row); c = self.config(t['batch_id']); used = self.usage(t['batch_id'])
                calls = min(c['max_calls_per_trial'], c['max_api_calls'] - used['calls'])
                tokens = min(c['max_tokens_per_trial'], c['max_total_tokens'] - used['tokens'])
                if calls < 1 or tokens < 1024:
                    self.db.execute("UPDATE trials SET status='budget_exhausted',result=? WHERE id=?", (json.dumps({'reason':'budget_exhausted'}), t['id']))
                    continue
                number = t['attempt'] + 1
                attempt_dir = f"trials/{t['id']}/attempt-{number:02d}"
                self.db.execute("UPDATE trials SET status='running',attempt=?,attempt_dir=? WHERE id=?", (number, attempt_dir, t['id']))
                self.db.execute("INSERT INTO attempts(trial_id,number,status,reserved_calls,reserved_tokens,started) VALUES(?,?,'running',?,?,?)", (t['id'],number,calls,tokens,time.time()))
                self.db.execute("UPDATE batches SET status='running' WHERE id=?", (t['batch_id'],))
                self.db.commit()
                t.update(status='running',attempt=number,attempt_dir=attempt_dir,reserved_calls=calls,reserved_tokens=tokens)
                return t
            self.db.commit()
            return None
        except BaseException:
            self.db.rollback(); raise

    def finish(self, t, result, infrastructure=False):
        c = self.config(t['batch_id'])
        status = 'queued' if infrastructure and t['attempt'] < c['max_attempts'] else 'infrastructure_error' if infrastructure else 'completed'
        usage = result.get('apiUsage', [])
        calls = len(usage) if result.get('usage_complete') else None
        tokens = max(result.get('accountedTokens',0),sum(u.get('total_tokens', 0) for u in usage)) if calls is not None else None
        with self.db:
            self.db.execute('UPDATE attempts SET status=?,used_calls=?,used_tokens=?,finished=?,error=? WHERE trial_id=? AND number=?',
                ('infrastructure_error' if infrastructure else 'completed',calls,tokens,time.time(),result.get('error'),t['id'],t['attempt']))
            self.db.execute('UPDATE trials SET status=?,result=? WHERE id=?', (status,json.dumps(result),t['id']))

    def publish(self, batch):
        from maple_gallery import build_gallery
        c = self.config(batch)
        trials = []
        for row in self.db.execute('SELECT * FROM trials WHERE batch_id=? ORDER BY ordinal', (batch,)):
            t = dict(row); result = json.loads(t.pop('result') or '{}')
            attempts = [dict(a) for a in self.db.execute('SELECT number,status,error,started,finished FROM attempts WHERE trial_id=? ORDER BY number',(t['id'],))]
            t.update(metrics=result, reason=result.get('reason'), error=result.get('error'), backend='cosmic-v83', attempts=attempts)
            if t['attempt_dir']:
                video = self.root / batch / t['attempt_dir'] / 'video' / 'henesys-overlay.mp4'
                if video.is_file(): t['video_path'] = str(video.relative_to(self.root / batch))
            trials.append(t)
        state = 'completed' if all(t['status'] in TERMINAL for t in trials) else 'running' if any(t['status'] in {'running','rendering'} for t in trials) else 'queued'
        if state == 'completed' and any(t['status'] != 'completed' for t in trials): state = 'completed_with_errors'
        with self.db: self.db.execute('UPDATE batches SET status=? WHERE id=?',(state,batch))
        batch_data = dict(c, id=batch, status=state, usage=self.usage(batch))
        atomic_json(self.root / batch / 'queue.json', {'batch':batch_data,'trials':trials})
        build_gallery(self.root / batch, batch_data, trials)
        return batch_data, trials


def freeze_source(destination):
    # Only implementation files from known source directories; never runtime outputs.
    files = []
    for folder in ['scripts', 'scenarios', 'configs']:
        for p in sorted((REPO / folder).glob('*')):
            if p.is_file() and not p.is_symlink() and p.suffix in {'.py','.mjs','.html','.json','.sql'}:
                relative = p.relative_to(REPO)
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, target)
                files.append((str(relative), digest(target)))
    checksum = hashlib.sha256(json.dumps(files).encode()).hexdigest()
    return checksum


def submit(queue, manifest, batch, work):
    if not SLUG.fullmatch(batch): raise ValueError('Invalid batch identifier')
    config = validate_manifest(json.loads(Path(manifest).read_text()))
    dest = queue.root / batch
    if dest.exists(): raise ValueError('Batch already exists; use worker to resume it')
    # Resolve all inputs before creating a batch, so a typo never leaves queued work.
    scenarios=[]
    for scenario_id in config['scenarios']:
        scenario = json.loads((REPO / 'scenarios' / f'{scenario_id}.json').read_text())
        if scenario['id'] != scenario_id: raise ValueError('Scenario ID mismatch')
        if scenario.get('status')=='experimental': raise ValueError('Experimental scenario has not passed gameplay validation')
        scenarios.append(scenario)
    snapshot = Path(os.environ['MAPLEBENCH_DB_SNAPSHOT']).resolve()
    server_jar = Path(os.environ.get('MAPLEBENCH_SERVER_JAR', str(work / 'runtime-cosmic/Server.jar'))).resolve()
    if not snapshot.is_file() or not server_jar.is_file(): raise ValueError('Missing database snapshot or server JAR')
    dest.mkdir(parents=True)
    try:
        config['source_sha256'] = freeze_source(dest / '_source')
        config['git_commit'] = subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        frozen = dest / '_runtime'; frozen.mkdir(mode=0o700)
        for name, source in [('baseline.sql',snapshot),('Server.jar',server_jar)]:
            shutil.copy2(source, frozen / name); (frozen / name).chmod(0o600)
            config[name.replace('.','_') + '_sha256'] = digest(frozen / name)
        # Freeze every game input used by the dedicated process, including private
        # configuration. This directory is never served by the public gallery.
        runtime=work/'runtime-cosmic'
        shutil.copy2(runtime/'config.yaml',frozen/'config.yaml'); (frozen/'config.yaml').chmod(0o600)
        for name,source in [('scripts',runtime/'scripts'),('wz',work/'server-data/wz')]:
            subprocess.run(['cp','-a','--reflink=auto',str(source.resolve()),str(frozen/name)],check=True)
        (frozen/'baked').mkdir()
        for name in sorted({sc.get('render_map','henesys') for sc in scenarios} | {sc.get('render_character','warrior') for sc in scenarios}):
            if not SLUG.fullmatch(name): raise ValueError('Invalid baked asset identifier')
            shutil.copytree(work/'baked'/name,frozen/'baked'/name)
        shutil.copy2(work/'maplewright/target/release/client',frozen/'render-client')
        (frozen/'render-client').chmod(0o700)
        config['renderer_sha256']=digest(frozen/'render-client')
        config['shared_monster_art']='Shared localhost assetd; keep game assets and assetd fixed while batches run'
        config['frozen_inputs']=['controller source','server JAR','WZ XML','server scripts','server configuration','map and character bakes','renderer binary','database snapshot']
        # Pin the actual local Docker image, so a tag update cannot change queued code execution.
        docker = os.environ.get('MAPLEBENCH_DOCKER_IMAGE','node:22.19.0-bookworm-slim')
        import shlex
        command = shlex.split(os.environ.get('MAPLEBENCH_DOCKER_COMMAND','docker'))
        config['docker_image'] = subprocess.check_output(command + ['image','inspect','--format','{{.Id}}',docker], text=True).strip()
        atomic_json(dest / 'manifest.json', config)
        ordinal = 0
        with queue.db:
            queue.db.execute('INSERT INTO batches VALUES(?,?,?,?)',(batch,json.dumps(config),time.time(),'queued'))
            for repetition in range(1, config['repetitions'] + 1):
                # Rotate model order across repetitions to reduce time-order effects.
                models = config['models']; offset = (repetition-1) % len(models)
                for model in models[offset:] + models[:offset]:
                    for scenario in config['scenarios']:
                        ordinal += 1
                        trial_id = f'{hashlib.sha256(batch.encode()).hexdigest()[:10]}-{ordinal:03d}-{model}-{scenario}-r{repetition}'
                        queue.db.execute('INSERT INTO trials(id,batch_id,ordinal,model,scenario,repetition,status) VALUES(?,?,?,?,?,?,?)',
                            (trial_id,batch,ordinal,model,scenario,repetition,'queued'))
    except BaseException:
        if not queue.db.execute('SELECT 1 FROM batches WHERE id=?',(batch,)).fetchone(): shutil.rmtree(dest)
        raise
    queue.publish(batch)
    return {'batch':batch,'trials':ordinal,'gallery':str(dest/'index.html')}


def request(base, endpoint, payload=None, timeout=3):
    req=urllib.request.Request(base+endpoint, data=None if payload is None else json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as r: return json.load(r)


def sudo(*args, **kwargs):
    return subprocess.run(['sudo','-n',*args],check=True,timeout=120,**kwargs)


def reset_world(work, batch_dir, scenario, out, trial_id):
    override = Path('/run/systemd/system/maplebench-cosmic.service.d/zz-maplebench-batch.conf')
    name=scenario['character_name']
    if not re.fullmatch('[A-Za-z0-9]{1,12}',name): raise ValueError('Unsafe synthetic character name')
    map_id=bounded_int(scenario['map_id'],'map_id',1,999999999)
    sudo('systemctl','stop','maplebench-cosmic')
    with (batch_dir / '_runtime/baseline.sql').open('rb') as f:
        sudo('mysql','maplebench',stdin=f,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    seed = batch_dir / '_source' / scenario['seed_sql']
    if not seed.resolve().is_relative_to((batch_dir/'_source/scripts').resolve()): raise ValueError('Invalid seed path')
    with seed.open('rb') as f: sudo('mysql','maplebench',stdin=f,stdout=subprocess.DEVNULL)
    allowed = {'level','job','str','dex','int','luk','hp','mp','maxhp','maxmp','exp','meso'}
    updates=[]
    for key,value in scenario['reset'].items():
        if key not in allowed: raise ValueError('Unknown reset field')
        bounded_int(value,key,0,2_000_000_000)
        updates.append(f'`{key}`={value}')
    sql=f"UPDATE characters SET {','.join(updates)},map={map_id} WHERE name='{name}'; SELECT id FROM characters WHERE name='{name}';"
    character_id=int(subprocess.check_output(['sudo','-n','mysql','-N','maplebench','-e',sql],text=True).strip())
    env={'MAPLEBENCH_ENABLED':'true','MAPLEBENCH_BOT_NAME':name,'MAPLEBENCH_CHARACTER_ID':str(character_id),
         'MAPLEBENCH_MAP_ID':str(map_id),'MAPLEBENCH_PRESET':scenario['preset'],
         'MAPLEBENCH_DEMO_MOBS':str(scenario.get('demo_mobs',False)).lower(),
         'MAPLEBENCH_EPISODE':str(out/'server-episode.jsonl'),'MAPLEBENCH_TASK_ID':scenario['id'],
         'MAPLEBENCH_SEED':trial_id}
    env['MAPLEBENCH_EXCLUDED_ONESHOT_MOBS'] = ','.join(str(bounded_int(mid,'excluded one-shot monster',1,99999999))
                                                     for mid in scenario.get('excluded_oneshot_monsters', []))
    start_mode = scenario.get('start_mode', 'live')
    if start_mode not in ('live', 'first_action'): raise ValueError('Invalid episode start mode')
    env['MAPLEBENCH_START_MODE'] = start_mode
    for item in scenario.get('inventory', []):
        item_id = item['item_id']
        role = 'HP' if item_id in (2000002, 2001001) else 'MP' if item_id in (2000003, 2000006) else None
        if role is None: raise ValueError('Unsupported scenario potion')
        id_key = 'MAPLEBENCH_' + role + '_POTION_ID'
        if id_key in env: raise ValueError('Scenario must select one potion per resource')
        env[id_key] = str(item_id)
        env['MAPLEBENCH_' + role + '_POTIONS'] = str(bounded_int(item['quantity'],'potion quantity',0,100))
    if scenario.get('spawn'):
        env['MAPLEBENCH_SPAWN_X']=str(bounded_int(scenario['spawn']['x'],'spawn x',-10000,10000))
        env['MAPLEBENCH_SPAWN_Y']=str(bounded_int(scenario['spawn']['y'],'spawn y',-5000,5000))
    def unit_quote(value):
        if any(c in value for c in '\n\r\x00'): raise ValueError('Invalid service configuration')
        return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    content='[Service]\n'+'\n'.join('Environment='+unit_quote(k+'='+v) for k,v in env.items())+'\nWorkingDirectory='+str(batch_dir/'_runtime').replace('%','%%')+'\nExecStart=\nExecStart=/usr/bin/java -Xmx4g '+unit_quote('-Dwz-path='+str(batch_dir/'_runtime/wz'))+' -jar '+unit_quote(str(batch_dir/'_runtime/Server.jar'))+'\n'
    sudo('mkdir','-p',str(override.parent))
    sudo('tee',str(override),input=content,text=True,stdout=subprocess.DEVNULL)
    sudo('systemctl','daemon-reload'); sudo('systemctl','start','maplebench-cosmic')
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        try:
            obs=request('http://127.0.0.1:8790','/v1/observe'); c=obs['character']
            if c['id']==character_id and c['name']==name and c['mapId']==map_id and c['level']==scenario['reset']['level'] and c['exp']==0 and c['alive'] and len(obs['monsters'])>0:
                return obs
        except Exception: pass
        time.sleep(1)
    raise RuntimeError('Scenario did not become ready')


def score_run(observations, events, agent):
    from combat_metrics import summarize_combat
    if not observations: raise ValueError('No server observations recorded')
    start,end=observations[0]['nowMs'],observations[-1]['nowMs']
    events=[e for e in events if start<=e['tMs']<=end]
    xp=[e for e in events if e['kind']=='xp_gain' and e['amount']>0]
    total=sum(e['amount'] for e in xp)
    peak=max((sum(f['amount'] for f in xp if e['tMs']-60000 < f['tMs'] <= e['tMs']) for e in xp),default=0)
    final=observations[-1]['character']
    return dict(agent,**summarize_combat(observations, events),backend='cosmic-v83',durationMs=max(0,end-start),xpGainedThisRun=total,totalXp=total,
                monsterSimulation=observations[0].get('monsterSimulation','stationary-v0'),
                averageXpPerMinute=total*60000/max(1,end-start),peak60sXpPerMinute=peak,
                peakWindowComplete=end-start>=60000,finalHp=final['hp'],alive=final['alive'],
                accepted=sum(e.get('accepted',False) for e in events if e['kind']=='action'),
                rejected=sum(not e.get('accepted',False) for e in events if e['kind']=='action'))


def execute_trial(batch_dir, t, work):
    from maple_agent import run_agent
    config=json.loads((batch_dir/'manifest.json').read_text())
    scenario=json.loads((batch_dir/'_source/scenarios'/f"{t['scenario']}.json").read_text())
    if 'duration_seconds' in config: scenario['duration_seconds']=config['duration_seconds']
    out=batch_dir/t['attempt_dir']; out.mkdir(parents=True,exist_ok=True)
    for name in ('baseline.sql','Server.jar'):
        if digest(batch_dir/'_runtime'/name) != config[name.replace('.','_')+'_sha256']:
            raise RuntimeError('Frozen runtime checksum mismatch')
    initial=reset_world(work,batch_dir,scenario,out,t['id'])
    base='http://127.0.0.1:8790'
    if request(base,'/health').get('backend')!='cosmic-v83': raise RuntimeError('Expected Cosmic server')
    atomic_json(out/'scenario.json',scenario)
    atomic_json(out/'provenance.json',{'source_sha256':config['source_sha256'],'git_commit':config['git_commit'],
        'monster_simulation':initial.get('monsterSimulation','stationary-v0'),
        'mechanics_version':initial.get('mechanicsVersion','combat-trace-v1'),
        'server_sha256':config['Server_jar_sha256'],'snapshot_sha256':config['baseline_sql_sha256'],
        'docker_image':config['docker_image'],'randomness':config['randomness'],'backend':'cosmic-v83'})
    observations=[initial]; done=threading.Event(); errors=[]
    def record():
        with (out/'observations.jsonl').open('a',buffering=1) as f:
            f.write(json.dumps(initial)+'\n')
            while not done.wait(0.1):
                try:
                    obs=request(base,'/v1/observe'); observations.append(obs); f.write(json.dumps(obs)+'\n')
                except Exception as e: errors.append(type(e).__name__)
    recorder=threading.Thread(target=record,daemon=True); recorder.start()
    key=os.environ.get('OPENAI_API_KEY')
    if not key: key=Path(os.environ['MAPLEBENCH_API_KEY_FILE']).read_text().strip()
    try:
        result=run_agent(t['model'],scenario,base,key,out,max_calls=t['reserved_calls'],max_total_tokens=t['reserved_tokens'],
            max_output_tokens=2200,wall_seconds=scenario['duration_seconds'],program_seconds=config['program_seconds'],
            docker_image=config['docker_image'],max_actions=config['max_actions_per_trial'],control_mode=config.get('control_mode','serial'),stop_when=(lambda obs: not any(m['alive'] for m in obs['monsters'])) if scenario.get('demo_mobs') else None)
    finally:
        done.set(); recorder.join(timeout=4)
    observations.append(request(base,'/v1/observe'))
    hard_end=initial['nowMs'] + scenario['duration_seconds']*1000
    observations=[obs for obs in observations if obs['nowMs']<=hard_end]
    cutoff=observations[-1]['nowMs']
    events=[e for e in request(base,'/v1/events?since_seq=0') if e['tMs']<=cutoff]
    sudo('systemctl','stop','maplebench-cosmic')
    atomic_json(out/'observations.json',observations)
    (out/'episode.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    result.update(observationErrors=len(errors),model=t['model'])
    score=score_run(observations,events,result)
    score.update(trialId=t['id'],attempt=t['attempt'])
    atomic_json(out/'score.json',score)
    return score


def render_trial(batch_dir,t,work):
    out=batch_dir/t['attempt_dir']
    scenario=json.loads((out/'scenario.json').read_text())
    env=dict(os.environ,MAPLEBENCH_WORK=str(work),MAPLEBENCH_CHARACTER_DIR=str(batch_dir/'_runtime/baked'/scenario.get('render_character','warrior')),
             MAPLEBENCH_MAP_DIR=str(batch_dir/'_runtime/baked'/scenario.get('render_map','henesys')),MAPLEBENCH_MAP_ID=str(scenario['map_id']),
             MAPLEBENCH_MAP_NAME=scenario.get('map_name',scenario['name']),MAPLEBENCH_FIXTURE_LABEL='Town combat fixture' if scenario.get('demo_mobs') else 'Natural monster spawns',
             MAPLEBENCH_ATTACK_POSE='swingO1' if scenario['preset']=='warrior' else 'swingT1',MAPLEBENCH_KEEP_FRAMES='false',MAPLEBENCH_RENDER_CLIENT=str(batch_dir/'_runtime/render-client'))
    with (out/'render.log').open('w') as log:
        child=subprocess.Popen(['node',str(batch_dir/'_source/scripts/render-cosmic-clip.mjs'),str(out)],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            if child.wait(timeout=3600): raise RuntimeError('Renderer failed')
        except BaseException:
            if child.poll() is None: os.killpg(child.pid,signal.SIGKILL); child.wait()
            raise
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss','1','-i',str(out/'video/henesys-overlay.mp4'),'-frames:v','1',str(out/'video/poster.jpg')],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=30)


def valid_video(video, duration_ms):
    if not video.is_file() or video.stat().st_size < 1024: return False
    try:
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(video)],timeout=10))
        return float(info['format']['duration']) >= max(0.01,duration_ms/1000-0.5)
    except (subprocess.SubprocessError,ValueError,KeyError,OSError): return False


def finish_render(queue,t,work):
    row=queue.db.execute('SELECT result FROM trials WHERE id=?',(t['id'],)).fetchone()
    score=json.loads(row['result'] or '{}')
    video=queue.root/t['batch_id']/t['attempt_dir']/'video/henesys-overlay.mp4'
    attempts=score.get('render_attempts',0)
    while not valid_video(video,score.get('durationMs',0)) and attempts<2:
        attempts+=1
        score['render_attempts']=attempts
        with queue.db: queue.db.execute('UPDATE trials SET result=? WHERE id=?',(json.dumps(score),t['id']))
        try:
            render_trial(queue.root/t['batch_id'],t,work)
            score.pop('render_error',None)
        except Exception as e:
            score['render_error']=type(e).__name__
    with queue.db: queue.db.execute("UPDATE trials SET status='completed',result=? WHERE id=?",(json.dumps(score),t['id']))


def recover_renders(queue,batch,work):
    where="status IN ('completed','rendering')" + (' AND batch_id=?' if batch else '')
    for row in queue.db.execute(f'SELECT * FROM trials WHERE {where}',(batch,) if batch else ()).fetchall():
        t=dict(row)
        if t['attempt_dir'] and (queue.root/t['batch_id']/t['attempt_dir']/'score.json').is_file():
            finish_render(queue,t,work)


def worker(queue,batch,work,watch=False):
    lock=(work/'private/maplebench-world.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    legacy=(work/'maplebench/artifacts/.cosmic-queue.lock').open('a')
    fcntl.flock(legacy,fcntl.LOCK_EX|fcntl.LOCK_NB)
    queue.recover()
    recover_renders(queue,batch,work)
    restored=False
    while True:
        t=queue.claim(batch)
        if not t:
            for row in queue.db.execute('SELECT id FROM batches'): queue.publish(row['id'])
            if not restored:
                restore_world(); restored=True
            if not watch: break
            time.sleep(3); continue
        restored=False
        batch_dir=queue.root/t['batch_id']
        queue.publish(t['batch_id'])
        print(json.dumps({'trial':t['id'],'attempt':t['attempt'],'status':'running'}),flush=True)
        # Execute frozen Python source in a child. A source update cannot change
        # a batch halfway through, including controller or renderer behavior.
        out=batch_dir/t['attempt_dir']; out.mkdir(parents=True,exist_ok=True)
        atomic_json(out/'trial.json',t)
        recorded=False
        try:
            cmd=[sys.executable,str(batch_dir/'_source/scripts/maplebench.py'),'execute','--batch-dir',str(batch_dir),'--trial',str(out/'trial.json'),'--work',str(work)]
            timeout=queue.config(t['batch_id']).get('duration_seconds',1800)+240
            with (out/'worker.log').open('w') as log:
                child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    returncode=child.wait(timeout=timeout)
                except BaseException:
                    os.killpg(child.pid,signal.SIGKILL); child.wait(); raise
            if returncode: raise RuntimeError('Trial process failed; see worker.log')
            score=json.loads((out/'score.json').read_text())
            infra=score.get('reason') in {'api_error','error','infrastructure_error'}
            queue.finish(t,score,infrastructure=infra)
            recorded=True
            # Scoring is committed before rendering: failed or interrupted renders
            # can be retried without issuing another paid model request.
            if not infra:
                with queue.db: queue.db.execute("UPDATE trials SET status='rendering' WHERE id=?",(t['id'],))
                queue.publish(t['batch_id'])
                finish_render(queue,t,work)
        except Exception as e:
            if recorded:
                atomic_json(out/'publication-error.json',{'error':type(e).__name__})
            else:
                queue.finish(t,{'reason':'infrastructure_error','error':type(e).__name__,'usage_complete':False},infrastructure=True)
        queue.publish(t['batch_id'])
        print(json.dumps({'trial':t['id'],'status':queue.db.execute('SELECT status FROM trials WHERE id=?',(t['id'],)).fetchone()[0]}),flush=True)


def restore_world():
    override='/run/systemd/system/maplebench-cosmic.service.d/zz-maplebench-batch.conf'
    sudo('rm','-f',override); sudo('systemctl','daemon-reload'); sudo('systemctl','restart','maplebench-cosmic')


def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='command',required=True)
    for command in ['submit','worker','status','render','cancel']:
        q=sub.add_parser(command); q.add_argument('--root',default='artifacts/batches'); q.add_argument('--batch')
        q.add_argument('--work',default=os.environ.get('MAPLEBENCH_WORK','..'))
        if command=='submit': q.add_argument('manifest')
        if command=='worker': q.add_argument('--watch',action='store_true')
    q=sub.add_parser('execute'); q.add_argument('--batch-dir',required=True); q.add_argument('--trial',required=True); q.add_argument('--work',required=True)
    args=p.parse_args(); work=Path(args.work).resolve()
    if args.command=='execute':
        result=execute_trial(Path(args.batch_dir),json.loads(Path(args.trial).read_text()),work)
        print(json.dumps(result)); return
    queue=Queue(args.root)
    if args.command=='submit':
        print(json.dumps(submit(queue,args.manifest,args.batch or time.strftime('batch-%Y%m%d-%H%M%S'),work)))
    elif args.command=='worker': worker(queue,args.batch,work,args.watch)
    elif args.command=='status':
        batches=[args.batch] if args.batch else [r['id'] for r in queue.db.execute('SELECT id FROM batches ORDER BY created')]
        for batch in batches:
            info,trials=queue.publish(batch)
            print(json.dumps({'batch':batch,'status':info['status'],'usage':info['usage'],'trials':[{'id':t['id'],'status':t['status'],'reason':t['reason'],'xp':t['metrics'].get('xpGainedThisRun')} for t in trials]}))
    elif args.command=='cancel':
        if not args.batch: p.error('cancel requires --batch')
        with queue.db:
            queue.db.execute("UPDATE trials SET status='cancelled',result=? WHERE batch_id=? AND status='queued'",(json.dumps({'reason':'cancelled before execution'}),args.batch))
        queue.publish(args.batch)
    elif args.command=='render':
        if not args.batch: p.error('render requires --batch')
        for row in queue.db.execute("SELECT * FROM trials WHERE batch_id=? AND status IN ('completed','rendering')",(args.batch,)).fetchall():
            t=dict(row); render_trial(queue.root/args.batch,t,work)
            with queue.db: queue.db.execute("UPDATE trials SET status='completed' WHERE id=?",(t['id'],))
        queue.publish(args.batch)


if __name__=='__main__': main()
