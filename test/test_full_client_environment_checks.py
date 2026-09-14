"""Synthetic emitter-shaped receipts; decoder/clock transports are mocked.

Capture/ledger, ordinary-save graph and SDK verification use production code.
No game, model, deployment, or live qualification is performed by these tests.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import full_client_environment_checks as checks
import full_client_native as native
from full_client_capture import capture_receipt
from full_client_native_xp_inventory import parse as inventory
from full_client_publication import digest, encoded, verify_package, publication_state
from full_client_publish import _measure_video_probe
from full_client_vercel import checked_payload, PUBLIC_NAME
import test_full_client_catalog as catalog_fixture
import test_full_client_native as native_fixture


class Fixture:
    def __init__(self, root, cls='hero', ident='a'*32):
        self.folder = root / ident; self.folder.mkdir(); self.refs = {}; self.values = {}
        self.ident = ident; self.source = 'e'*40; self.verifier = 'f'*64
        self.native = native.contract(cls, 'b'*64, protocol=native.PRODUCTIVITY_V2_PROTOCOL)
        self.save('runtime_manifest', {'schema_version': 2, 'private_machine': 'must-never-export'})
        self.runtime = self.refs['runtime_manifest']['sha256']
        self.identity = {'run_id': ident, 'server_instance_id': 'c'*32, 'character_id': 5, 'account_id': 2}
        first = {'character_id': 5, 'account_id': 2, 'job': checks.JOBS[cls], 'map_id': 240040511,
            'level': 180, 'exp': 73250, 'hp': 9000, 'mp': 9000, 'max_hp': 9000, 'max_mp': 9000, 'spawn_point': 0}
        def snapshot(at, char):
            return {'schema_version': 1, 'source': 'cosmic_persisted_character', 'run_id': ident,
                'captured_at_ms': at, 'account_logged_in': 0, 'character': char, 'keymap': [{'key': 30, 'skill': 1}]}
        self.save('initial_db', snapshot(12000, first)); self.save('baseline_snapshot', snapshot(9000, first))
        self.save('final_db', snapshot(203000, first | {'exp': 78000}))
        self.save('restored_db', snapshot(204000, first))
        self.save('reset', {'run_id': ident, 'baseline_sha256': 'b'*64, 'completed_at_ms': 11000,
            'world_lock_held': True, 'queue_lock_held': True, 'server_stopped': True, 'verified': True})
        header = {'kind': 'character', 'character_id': 5, 'account_id': 2, 'job': checks.JOBS[cls],
            'level': 180, 'account_logged_in': 0, 'transactional_tables': 3}
        items = [{'kind': 'use', 'inventoryitemid': 8, 'itemid': 2000005, 'position': 1, 'quantity': 80}]
        for phase, at in [('before_login', 13000), ('after_logout', 202800), ('after_restore', 204100)]:
            self.save('inventory_' + phase, inventory(b'\n'.join(encoded(x) for x in [header, *items]),
                native=self.native, run_id=ident, server_instance_id='c'*32, phase=phase,
                character_id=5, account_id=2, runtime_manifest_sha256=self.runtime, captured_at_ms=at))
        self.save('scenario', self.native); self.save('program', native.program(self.native).encode(), raw=True)
        obs = {'ready': True, 'source': 'full-client', 'ageMs': 10, 'renderAgeMs': 10, 'character': {'alive': True}}
        steps = [{'kind': 'sdk', 'rpcId': 1, 'method': 'pressKeys', 'args': [['PRIMARY_SKILL'], 100],
            'result': {'accepted': True, 'observation': obs}}]
        f = native_fixture.encoded_native_fixture(); count = 7200; duration = 180000
        timestamps = [i*25000 for i in range(count)]; durations = [25000]*(count-1)+[23000]
        ledger = {'schema_version': 1, 'codec': 'vp8', 'timebase_us': 1000, 'flushed': True,
            'submitted_timestamps_us': timestamps, 'encoded_timestamps_us': timestamps,
            'durations_us': durations, 'encoded_sha256': ['d'*64]*count}
        ledger_raw = json.dumps(ledger, separators=(',', ':')); video = b'SYNTHETIC VIDEO'
        encoder = {'schema_version': 1, 'codec': 'vp8', 'timebase_us': 1000, 'flushed': True,
            'submitted_frames': count, 'encoded_frames': count, 'ledger_sha256': digest(ledger_raw.encode()),
            'ledger_bytes': len(ledger_raw), 'webm_sha256': digest(video), 'webm_bytes': len(video)}
        f.value.update(run_id=ident, duration_ms=duration, end_wall_ms=10020+duration,
            last_frame_wall_ms=10022+timestamps[-1]/1000, last_frame_offset_ms=2+timestamps[-1]/1000,
            rendered_frames=count, max_frame_gap_ms=25, encoder_receipt=encoder)
        f.anchor['runId'] = ident; f.terminal['serverIssuedAtMs'] = 199900
        owner = f.owner | {'id': ident, 'protocol': self.native['id'], 'mode': 'script', 'model': None,
            'nativeAcceptance': self.native, 'returnedModel': None, 'trialContext': None, 'status': 'completed',
            'workerActive': False, 'reason': 'program_complete', 'actions': 1}
        self.result = {'protocol': self.native['id'], 'nativeAcceptance': self.native, 'controller': owner,
            'trialContext': None, 'api': None, 'model_api_requests': 0, 'score': None, 'publication_eligible': False,
            'programSha256': digest(native.program(self.native).encode()), 'private_marker': 'must-never-export',
            'program': {'actions': 1, 'actionAttempts': 1, 'rpcRequests': 1, 'reason': 'program_complete', 'error': None, 'steps': steps},
            'timing': {'startedAtMs': 20000, 'endedAtMs': 199500, 'apiLatencyMs': 0},
            'timeline': {'status': 'completed', 'api_started_ms': None, 'api_ended_ms': None,
                'program_started_ms': 100, 'program_ended_ms': 179500, 'first_input_started_ms': 200, 'first_input_acked_ms': 300}}
        self.save('result', self.result)
        for key, value in [('capture', f.value), ('capture_ready', f.anchor), ('capture_clock', f.clock), ('capture_terminal', f.terminal)]:
            self.save(key, value)
        recording = capture_receipt(f.value, owner, f.anchor, f.clock, f.terminal)
        self.save('recording', recording | {'sha256': digest(video), 'capture_sha256': self.refs['capture']['sha256']})
        raw_probe = {'streams': [{'width': 800, 'height': 720, 'nb_read_frames': str(count)}],
            'format': {'tags': {'MAPLEBENCH_ENCODER_LEDGER_V1': ledger_raw}},
            'packets': [{'pts_time': str(t/1000000), 'duration_time': str(d/1000000), 'flags': '__', 'data_hash': 'SHA256:'+'d'*64}
                        for t,d in zip(timestamps, durations)]}
        self.probe = _measure_video_probe(raw_probe, maximum_ms=185000, duration_policy=self.native['capture_duration_policy'])
        self.probe.update(webm_sha256=digest(video), webm_bytes=len(video))
        self.save('video_probe', self.probe); self.save('video', video, raw=True)
        self.save('save', encoded({'schema_version': 1, 'source': 'cosmic_persisted_character', 'kind': 'save_committed',
            **self.identity, 'committed_at_ms': 202450}), raw=True)
        self.save('native_log', b'Synthetic persistence journal\n', raw=True)
        self.save('clock', {'schema_version': 1, 'capture_start_wall_ms': f.value['start_wall_ms'],
            'capture_end_wall_ms': f.value['end_wall_ms'], 'samples': 'synthetic transport fixture'})
        self.qualification = {'schema_version': 1, 'status': 'qualified', 'kind': 'operational_clock_measurement',
            'simulation_wall_ratio': 1.0, 'simulation_delta_ms': 180000, 'wall_delta_ms': 180000,
            'max_pending_ms': 0, 'capture_fps': 40.0, 'capture_duration_ms': 180000, 'sample_count': 181,
            'renderer': {'renderer': 'Private synthetic GPU label'}, 'api_calls': 0}
        self.save_clock(); self.rebind()

    def save(self, name, value, raw=False):
        filename = name + ('.webm' if name == 'video' else '.js' if name == 'program' else '.txt' if raw else '.json')
        data = value if raw else encoded(value); (self.folder/filename).write_bytes(data)
        self.values[name] = copy.deepcopy(value); self.refs[name] = {'path': filename, 'sha256': digest(data)}

    def save_clock(self):
        self.save('clock_qualification', {'schema_version': 1, 'run_id': self.ident, 'native_protocol': self.native['id'],
            'source_revision': self.source, 'runtime_manifest_sha256': self.runtime,
            'capture_sha256': self.refs['capture']['sha256'], 'video_sha256': self.refs['video']['sha256'],
            'clock_sha256': self.refs['clock']['sha256'], 'verifier_sha256': self.verifier, 'qualification': self.qualification})

    def rebind(self):
        artifacts = {k: copy.deepcopy(self.refs[k]) for k in checks.BOUND_ARTIFACTS}
        session = {'server_started_at_ms': 14000, 'login_at_ms': 16000,
            'disconnect_requested_at_ms': 202200, 'logged_out_at_ms': 202700}
        logout = {'schema_version': 1, 'source': 'cosmic_ordinary_disconnect', **self.identity,
            'disconnect_requested_at_ms': 202200, 'logged_out_at_ms': 202700, 'save_committed_at_ms': 202450}
        self.save('backend', {'attempt_id': self.ident, 'server_instance_id': 'c'*32, 'schema_version': 1,
            'maintenance_protocol': checks.MAINTENANCE_PROTOCOL, 'clean': True, 'native_restored': True,
            'publication_eligible': False, 'intents': ['disconnect', 'native_restore_after'], 'artifacts': artifacts,
            'initial': self.values['initial_db'], 'reset': self.values['reset'], 'session': session,
            'ordinary_logout': logout, 'committed_at_ms': 202450,
            'native_warmup': {'source': 'observation_only_after_ordinary_login_before_capture',
                'requested_ms': 3000, 'started_at_ms': 16000, 'ended_at_ms': 19000,
                'status_observations': 15, 'new_inputs': 0, 'api_calls': 0},
            'native_settlement': {'source': 'observation_only_after_saved_capture_before_ordinary_logout',
                'requested_ms': 2000, 'started_at_ms': 200100, 'ended_at_ms': 202100,
                'status_observations': 10, 'new_inputs': 0, 'api_calls': 0,
                'diagnostic_saved_xp_includes_ordinary_late_settlement': True}})
        common = {'schema_version': 1, 'protocol': checks.MAINTENANCE_PROTOCOL, 'api_calls': 0, 'model': None,
            'clean': True, 'native_restored': True, 'publication_eligible': False, 'class_accepted': False,
            'xp_qualification': False, 'artifacts': artifacts}
        self.save('executor_complete', common | self.identity | {'status': 'native_productivity_collected_unscored', 'failure': None})
        self.save('outer_complete', common | {'acceptance_id': self.ident, 'status': 'native_productivity_closed_unscored',
            'executor_complete': self.refs['executor_complete'], 'backend_state_ref': self.refs['backend']})

    def row(self):
        return checks.project_check(self.folder, self.refs, source_revision=self.source, runtime_manifest_sha256=self.runtime,
            clock_verifier_sha256=self.verifier, qualify_clock=lambda *args: self.qualification,
            probe_video=lambda *args, **kwargs: self.probe)

    def selection(self):
        path = self.folder/'artifacts.json'; path.write_bytes(encoded(self.refs))
        return {'folder': str(self.folder), 'artifacts': path.name, 'artifacts_sha256': digest(path.read_bytes()),
            'source_revision': self.source, 'runtime_manifest_sha256': self.runtime, 'clock_verifier_sha256': self.verifier}


class EnvironmentChecksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name).resolve()
        self.fixture = Fixture(self.root)

    def test_actual_emitter_shapes_recheck_capture_save_and_return_only_scripted_outcome(self):
        row = self.fixture.row()
        self.assertEqual(row['saved_xp_delta'], 4750); self.assertEqual(row['program_elapsed_ms'], 179400)
        self.assertEqual(row['recording']['duration_ms'], 180000); self.assertEqual(row['clock_evidence']['capture_fps'], 40)
        self.assertEqual(row['actions'], 1); self.assertIsNone(row['model']); self.assertIsNone(row['score'])
        self.assertFalse(row['ranked']); self.assertFalse(row['publication_eligible']); self.assertFalse(row['class_accepted'])
        for private in ('must-never-export', 'Private synthetic GPU label', 'account_id', 'character_id', 'samples', self.fixture.folder.as_posix()):
            self.assertNotIn(private, json.dumps(row))
        self.assertEqual(row['recording']['playback']['basis'], 'first_acknowledged_input')
        self.assertEqual(row['warmup_elapsed_ms'], 3000)
        self.assertEqual(row['post_recording_settlement_ms'], 2000)
        self.assertEqual(row['saved_xp_scope'], 'includes_post_recording_ordinary_settlement')

    def test_original_status_only_warmup_and_settlement_are_required_and_ordered(self):
        changes=[('native_warmup', {'requested_ms': 2000}), ('native_warmup', {'new_inputs': 1}),
            ('native_warmup', {'status_observations': True}), ('native_warmup', {'started_at_ms': 15000}),
            ('native_warmup', {'ended_at_ms': 18997}), ('native_warmup', {'ended_at_ms': 20100}),
            ('native_settlement', {'started_at_ms': 199500}), ('native_settlement', {'ended_at_ms': 202201}),
            ('native_settlement', {'api_calls': 1}),
            ('native_settlement', {'diagnostic_saved_xp_includes_ordinary_late_settlement': False})]
        for field,change in changes:
            with self.subTest(field=field,change=change):
                self.fixture.rebind();backend=copy.deepcopy(self.fixture.values['backend']);backend[field].update(change)
                self.fixture.save('backend',backend)
                outer=copy.deepcopy(self.fixture.values['outer_complete']);outer['backend_state_ref']=self.fixture.refs['backend']
                self.fixture.save('outer_complete',outer)
                with self.assertRaisesRegex(ValueError,'status_only_pause'):self.fixture.row()
        self.fixture.rebind()
        pause=self.fixture.values['backend']['native_warmup']
        # A slow status reply may overshoot the request; the original executor
        # uses its whole 720s deadline, with no invented 3.5s pause deadline.
        self.assertEqual(checks.observation_pause(pause|{'ended_at_ms':20500},source=pause['source'],
            requested_ms=3000,earliest=16000,latest=21000),4500)
        with self.assertRaises(ValueError):
            checks.observation_pause(pause|{'ended_at_ms':740000},source=pause['source'],
                requested_ms=3000,earliest=16000,latest=800000)

    def test_zero_negative_and_death_remain_honest_outcomes(self):
        for delta, hp in ((0, 9000), (-500, 0)):
            value = copy.deepcopy(self.fixture.values['final_db']); value['character'].update(exp=73250+delta, hp=hp)
            self.fixture.save('final_db', value); self.fixture.rebind(); row = self.fixture.row()
            self.assertEqual(row['saved_xp_delta'], delta); self.assertEqual(row['alive_at_logout'], hp>0)

    def test_no_boolean_bypass_or_legacy_relabelled_program(self):
        for change in (lambda v: v.update(model_api_requests=1), lambda v: v['controller'].update(model='gpt-6-astra'),
            lambda v: v.update(programSha256='0'*64), lambda v: v['program']['steps'][0]['result'].update(accepted=False),
            lambda v: v.update(publication_eligible=True)):
            value=copy.deepcopy(self.fixture.result); change(value); self.fixture.save('result',value); self.fixture.rebind()
            with self.assertRaises(ValueError): self.fixture.row()
        self.fixture.save('result', self.fixture.result)
        self.fixture.save('program', native.program(native.contract('hero','b'*64,protocol=native.PRODUCTIVITY_PROTOCOL)).encode(), raw=True)
        self.fixture.rebind()
        with self.assertRaisesRegex(ValueError,'original_script'): self.fixture.row()

    def test_cleanup_restore_and_ordinary_save_graph_cannot_be_faked(self):
        for name, change in [('executor_complete',lambda v:v.update(failure={'error':'failed'})),
            ('outer_complete',lambda v:v.update(status='native_cleanup_only_closed_no_replay')),
            ('backend',lambda v:v.update(ordinary_logout={'confirmed':True})),
            ('restored_db',lambda v:v['character'].update(exp=10)),
            ('save',lambda v:b''), ('inventory_after_restore',lambda v:v['use_inventory'][0].update(quantity=79))]:
            with self.subTest(name=name):
                before=copy.deepcopy(self.fixture.values[name]); value=copy.deepcopy(before)
                out=change(value); value=out if isinstance(out,bytes) else value
                self.fixture.save(name,value,raw=isinstance(value,bytes))
                if name not in ('executor_complete','outer_complete','backend'):self.fixture.rebind()
                with self.assertRaises(ValueError):self.fixture.row()
                self.fixture.save(name,before,raw=isinstance(before,bytes)); self.fixture.rebind()

    def test_clock_must_match_exact_capture_source_and_rerun_qualification(self):
        original=copy.deepcopy(self.fixture.values['clock_qualification'])
        for change in ({'run_id':'b'*32},{'capture_sha256':'b'*64},{'verifier_sha256':'b'*64},
                       {'source_revision':'b'*40},{'qualification':{'status':'qualified'}}):
            self.fixture.save('clock_qualification',original|change)
            with self.assertRaisesRegex(ValueError,'clock_qualification'):self.fixture.row()
        self.fixture.save('clock_qualification',original)
        self.fixture.save('clock',self.fixture.values['clock']|{'capture_start_wall_ms':0});self.fixture.save_clock()
        with self.assertRaisesRegex(ValueError,'clock_capture_interval'):self.fixture.row()

    def test_missing_first_input_cue_and_changed_video_bytes_are_rejected(self):
        result=copy.deepcopy(self.fixture.result);result['timeline'].pop('first_input_started_ms')
        self.fixture.save('result',result);self.fixture.rebind()
        with self.assertRaisesRegex(ValueError,'input_cue'):self.fixture.row()
        self.fixture.save('result',self.fixture.result);self.fixture.rebind()
        (self.fixture.folder/self.fixture.refs['video']['path']).write_bytes(b'different')
        with self.assertRaisesRegex(ValueError,'video_changed'):self.fixture.row()

    def test_real_backup_subdirectories_preserve_original_artifact_reference_graph(self):
        # Operational backups preserve acceptance/ and maintenance/ without
        # rewriting the original artifact references inside the backend.
        acceptance=self.fixture.folder/'acceptance';acceptance.mkdir()
        maintenance=self.fixture.folder/'maintenance';maintenance.mkdir()
        for name,ref in self.fixture.refs.items():
            prefix='maintenance' if name=='outer_complete' else 'acceptance'
            (self.fixture.folder/ref['path']).rename(self.fixture.folder/prefix/ref['path'])
            ref['path']=prefix+'/'+ref['path']
        self.assertEqual(self.fixture.row()['saved_xp_delta'],4750)

    def test_decoder_mismatch_and_clock_quality_fail_closed(self):
        with patch.object(checks,'verify_video_duration', wraps=checks.verify_video_duration) as verify:
            self.fixture.row(); self.assertEqual(verify.call_args.args[2],self.fixture.native['capture_duration_policy'])
        self.fixture.probe['duration_ms']=1
        with self.assertRaises(ValueError):self.fixture.row()
        self.fixture.probe['duration_ms']=179998
        for change in ({'capture_fps':29},{'simulation_wall_ratio':.98},{'max_pending_ms':8},{'sample_count':True}):
            old=copy.deepcopy(self.fixture.qualification);self.fixture.qualification.update(change);self.fixture.save_clock()
            with self.assertRaises(ValueError):self.fixture.row()
            self.fixture.qualification=old

    def test_exact_mount_and_four_class_attachment_preserve_model_results_and_every_old_file(self):
        catalog=catalog_fixture.CatalogTests();catalog.setUp()
        try:
            original,snapshot=catalog.compose([catalog.package(catalog.fixture(),count=4)])
            fixtures=[self.fixture]+[Fixture(self.root,cls,format(i,'x')*32)for i,cls in enumerate(checks.CLASSES[1:],1)]
            output=self.root/'public';output.mkdir()
            byhash={f.refs['video']['sha256']:f.probe for f in fixtures}
            result=checks.attach_checks(original,[f.selection()for f in fixtures],output,
                qualify_clock=lambda *args:self.fixture.qualification,probe_video=lambda path,sha,**kwargs:byhash[sha])
            site=Path(result['site']);new=json.loads((site/'results.json').read_bytes())
            self.assertEqual({k:v for k,v in new.items()if k!='environment_checks'},snapshot)
            self.assertEqual([r['class_id']for r in new['environment_checks']],list(checks.CLASSES))
            for file in Path(original['site']).rglob('*'):
                if file.is_file() and file.relative_to(original['site']).as_posix() not in ('results.json','recording-manifest.json'):
                    self.assertEqual(file.read_bytes(),(site/file.relative_to(original['site'])).read_bytes())
            manifest=verify_package(Path(result['primary_package']),result['primary_content_sha256'])
            self.assertEqual(publication_state(Path(result['primary_package']),result['primary_content_sha256']),'unclaimed')
            checked_payload(site,Path(result['inventory']),result['inventory_sha256'],manifest)
            stripped=copy.deepcopy(manifest);stripped['content'].pop('environment_checks_payload_sha256')
            stripped['content_sha256']=digest(encoded(stripped['content']))
            with self.assertRaisesRegex(ValueError,'environment_checks_payload_binding_required'):
                checked_payload(site,Path(result['inventory']),result['inventory_sha256'],stripped)
            with self.assertRaisesRegex(ValueError,'environment_checks_payload_binding'):
                checked_payload(Path(original['site']),Path(original['inventory']),original['inventory_sha256'],manifest)
            with self.assertRaisesRegex(ValueError,'four_classes'):
                checks.attach_checks(original,[self.fixture.selection()],output,qualify_clock=Mock())
        finally:catalog.tearDown()
        self.assertTrue(PUBLIC_NAME.fullmatch('checks/'+'a'*32+'/recordings/'+'a'*32+'.webm'))
        for name in ('checks/'+'a'*32+'/recordings/'+'b'*32+'.webm','checks/'+'a'*32+'/result.json','checks/../save.json'):
            self.assertIsNone(PUBLIC_NAME.fullmatch(name))

    def test_existing_preview_and_its_claim_remain_immutable_in_new_publication_identity(self):
        import test_full_client_skill_preview_publication as preview_fixture
        from full_client_publication import claim_publication
        from full_client_skill_preview_publication import attach_previews
        previous=preview_fixture.SkillPreviewPublicationTests();previous.setUp()
        catalog=catalog_fixture.CatalogTests();catalog.setUp()
        try:
            original,_=catalog.compose([catalog.package(catalog.fixture(),count=4)])
            preview_output=self.root/'previews';preview_output.mkdir()
            ref_path=previous.folder/'artifacts.json';ref_path.write_bytes(encoded(previous.refs))
            original=attach_previews(original,[{'folder':str(previous.folder),'artifacts':ref_path.name,
                'artifacts_sha256':digest(ref_path.read_bytes())}],preview_output)
            claim_publication(Path(original['primary_package']),original['primary_content_sha256'])
            claim=(Path(original['primary_package'])/'publication-intent.json').read_bytes()
            snapshot=json.loads((Path(original['site'])/'results.json').read_bytes())
            fixtures=[self.fixture]+[Fixture(self.root,cls,format(i,'x')*32)for i,cls in enumerate(checks.CLASSES[1:],1)]
            output=self.root/'checks';output.mkdir()
            result=checks.attach_checks(original,[f.selection()for f in fixtures],output,
                qualify_clock=lambda *args:self.fixture.qualification,probe_video=lambda *args,**kwargs:self.fixture.probe)
            new=json.loads((Path(result['site'])/'results.json').read_bytes())
            self.assertEqual({k:v for k,v in new.items()if k!='environment_checks'},snapshot)
            self.assertEqual((Path(original['primary_package'])/'publication-intent.json').read_bytes(),claim)
            self.assertEqual(publication_state(Path(result['primary_package']),result['primary_content_sha256']),'unclaimed')
            manifest=verify_package(Path(result['primary_package']),result['primary_content_sha256'])
            checked_payload(Path(result['site']),Path(result['inventory']),result['inventory_sha256'],manifest)
            self.assertEqual(manifest['content']['skill_preview_payload_sha256'],manifest['content']['environment_checks_payload_sha256'])
        finally:catalog.tearDown();previous.tearDown()


if __name__=='__main__':unittest.main()
