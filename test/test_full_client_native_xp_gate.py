"""Synthetic native ledgers and mocked decoding; these are not live acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import full_client_native_xp_gate as gate
from full_client_native_xp_acceptance import verify_bundle
from full_client_score import EvidenceError
import test_full_client_native_xp_acceptance as native_fixtures
import test_full_client_xp_publication as model_fixtures
import full_client_xp_publication as publication
import test_full_client_native_xp_runtime as producer_fixtures


class NativeGateTests(unittest.TestCase):
    def setUp(self):
        self.f = native_fixtures.NativeEnvelopeTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root = self.f.root.resolve(); self.f.root = self.root
        for name in ('initial_db', 'final_db', 'baseline_snapshot'):
            value = json.loads((self.root / self.f.arts[name]['path']).read_bytes())
            value['character']['job'] = 112
            if name == 'baseline_snapshot': value['account_logged_in'] = 0
            self.f.save(name, value)
        self.manifest = copy.deepcopy(self.f.manifest)
        self.checked = verify_bundle(self.manifest, self.root)
        self.arts = copy.deepcopy(self.manifest['artifacts'])
        self.arts['baseline'] = self.arts.pop('baseline_sql')
        self.runtime = {'schema_version': 2,
            'server_jar': {'path': '/candidate/Cosmic.jar', 'sha256': '1' * 64},
            'extra_files': [{'path': '/release/native.py', 'sha256': '2' * 64}]}
        self.put('runtime_manifest', self.runtime)
        self.native = self.read('scenario')['native_contract']
        logout=self.producer_receipts()
        self.checked=verify_bundle(self.manifest,self.root)
        self.put('native_xp_manifest', self.manifest); self.put('native_xp_result', self.checked)
        self.put('video', b'SYNTHETIC VIDEO: decoding is explicitly mocked', raw=True)
        self.put('recording', {'status': 'completed', 'interrupted': False, 'post_render_capture': True,
            'overlay': {'controller_id': 'a' * 32, 'mode': 'script', 'model': None},
            'sha256': self.arts['video']['sha256'], 'end_wall_ms': 1020100})
        for name in ('controller', 'capture', 'capture_ready', 'capture_clock', 'capture_terminal', 'video_probe'):
            self.put(name, {'fixture': 'synthetic'})
        restored = copy.deepcopy(self.read('initial_db')); restored['captured_at_ms'] = 1305000
        self.put('restored_db', restored)
        self.complete = {'schema_version': 1, 'protocol': gate.NATIVE,
            **{k: self.manifest[k] for k in gate.IDENTITY},
            'status': 'native_xp_collected_awaiting_visual_review', 'api_calls': 0, 'model': None,
            'publication_eligible': False, 'clean': True, 'native_restored': True, 'failure': None,
            'result': self.checked, 'artifacts': self.arts}
        self.backend = {'attempt_id': 'a' * 32, 'server_instance_id': 'b' * 32,
            'maintenance_protocol': gate.NATIVE, 'clean': True, 'native_restored': True,
            'publication_eligible': False, 'ordinary_logout': logout['ordinary_logout'], 'artifacts': self.arts,
            'session':logout['session'],'committed_at_ms':logout['committed_at_ms'],
            'intents': ['restore_baseline', 'native_control_submit', 'disconnect', 'native_xp_restore_after']}
        self.context = {'schema_version': 1, 'protocol': gate.PROTOCOL, 'root': str(self.root),
            'run_id': 'a' * 32, 'runtime_manifest': self.arts['runtime_manifest']}
        self.model_root = self.root.parent / (self.root.name + '-model'); self.model_root.mkdir()
        self.addCleanup(self.model_root.rmdir)
        self.model_context = {'run_id': 'c' * 32, 'runtime_manifest_sha256': self.arts['runtime_manifest']['sha256'],
            'request': {'baseline_sha256': self.manifest['baseline_sha256']}}
        self.row = {'adaptive': {'class_profile': self.native['profile']}, 'normalization': self.manifest['normalization'],
            'provenance': {'native_server_jar_sha256': '1' * 64,
                'experience_table_sha256': self.manifest['experience_table_sha256']}}
        self.probe = {'duration_ms': 20100, 'presentation_span_ms': 20099, 'presentation_extent_ms': 20100}
        self.repin()

    def producer_receipts(self):
        """Use actual executor/disconnect producers with mocked host boundaries."""
        f=producer_fixtures.ExecutorTests();f.setUp();self.addCleanup(f.doCleanups);f.window_fixture()
        backend=f.backend;backend.native=self.native
        backend.config['mysql'].update({k:self.manifest[k] for k in ('character_id','account_id')})
        backend.native_window()
        self.runtime.update(backend.manifest,docker_binding=backend.docker_binding())
        self.put('runtime_manifest',self.runtime)
        for key in ('window_origin','native_request'):
            ref=backend.state['artifacts'][key]
            self.put(key,json.loads((backend.directory/ref['path']).read_bytes()))
        ref=backend.state['artifacts']['coverage']
        self.arts['coverage']=self.write('producer-coverage.jsonl',(backend.directory/ref['path']).read_bytes(),True)
        self.manifest['artifacts']['coverage']=self.arts['coverage']
        session=self.read('session');native=backend.directory/'native-save';native.mkdir()
        (native/'save.jsonl').write_bytes((self.root/self.arts['native_save']['path']).read_bytes())
        backend.state['native_directory']=str(native)
        backend.owned_server=MagicMock();backend.account_state=MagicMock(return_value=0)
        f.host.now.side_effect=[session['disconnect_requested_at_ms'],session['logged_out_at_ms']]
        backend.request_ordinary_disconnect()
        self.assertNotIn('confirmed',backend.state['ordinary_logout'])
        return backend.state

    def write(self, filename, value, raw=False):
        data = value if raw else (json.dumps(value, sort_keys=True) + '\n').encode()
        (self.root / filename).write_bytes(data)
        return {'path': filename, 'sha256': hashlib.sha256(data).hexdigest()}

    def put(self, name, value, raw=False):
        self.arts[name] = self.write(name + ('.webm' if raw else '.json'), value, raw)

    def read(self, name):
        return json.loads((self.root / self.arts[name]['path']).read_bytes())

    def repin(self):
        self.context['complete'] = self.write('complete.json', self.complete)
        self.context['backend'] = self.write('backend-state.json', self.backend)
        self.review = {'schema_version': 1, 'protocol': gate.NATIVE_REVIEW, 'reviewed_at_ms': 1306000,
            'binding': {'run_id': 'a' * 32, 'model': None,
                'complete_sha256': self.context['complete']['sha256'], 'backend_sha256': self.context['backend']['sha256'],
                'runtime_manifest_sha256': self.arts['runtime_manifest']['sha256'],
                'native_manifest_sha256': self.arts['native_xp_manifest']['sha256'],
                'video_sha256': self.arts['video']['sha256'], 'capture_sha256': self.arts['capture']['sha256'],
                'recording_sha256': self.arts['recording']['sha256'], 'class_profile_sha256': gate.digest(self.native['profile'])},
            'observations': {name: {'start_ms': 100, 'end_ms': 200} for name in
                ('vertical_jump', 'monster_contact', 'native_class_hud', 'script_overlay')}}
        self.context['visual_review'] = self.write('review.json', self.review)

    def verify(self):
        with patch('full_client_publish._probe_video', return_value=self.probe) as probe, \
             patch('full_client_publish.verify_capture_bundle', return_value={}) as capture, \
             patch('full_client_capture.verify_video_duration') as duration:
            result = gate.verify_native(self.context, model_root=self.model_root,
                model_context=self.model_context, model_projection=self.row)
            probe.assert_called_once(); capture.assert_called_once()
            self.assertEqual(duration.call_args.args[2], self.native['capture_duration_policy'])
            return result

    def test_original_ledger_recomputed_before_operator_attestation(self):
        result = self.verify()
        self.assertEqual(result['status'], 'native_runtime_evidence_rechecked')
        self.assertNotIn('publication_eligible', result)
        for private in ('/candidate', str(self.root), 'account_id', 'character_id', 'observations'):
            self.assertNotIn(private, json.dumps(result))

    def test_accepted_boolean_or_missing_pins_cannot_bypass_evidence(self):
        for context in ({'accepted': True}, self.context | {'accepted': True}, self.context | {'visual_review': None}):
            with self.subTest(context=context), self.assertRaises(EvidenceError):
                gate.verify_native(context, model_root=self.model_root, model_context=self.model_context,
                                   model_projection=self.row)

    def test_native_identity_cannot_be_the_api_run_or_namespace(self):
        self.model_context['run_id'] = 'a' * 32
        with self.assertRaisesRegex(EvidenceError, 'separate_native_identity'): self.verify()
        self.model_context['run_id'] = 'c' * 32; self.context['root'] = str(self.model_root)
        with self.assertRaisesRegex(EvidenceError, 'separate_native_identity'): self.verify()

    def test_failed_native_closeout_cannot_be_accepted(self):
        for change in ({'failure': {'reason': 'failed'}}, {'clean': False}, {'native_restored': False},
                       {'status': 'failed_native_xp_closed'}, {'model': 'gpt-6-astra'}, {'api_calls': 1}):
            original = copy.deepcopy(self.complete); self.complete.update(change); self.repin()
            with self.subTest(change=change), self.assertRaises(EvidenceError): self.verify()
            self.complete = original

    def test_ordinary_logout_and_one_submission_required(self):
        original=copy.deepcopy(self.backend['ordinary_logout'])
        self.backend['ordinary_logout']={'confirmed':True};self.repin()
        with self.assertRaisesRegex(EvidenceError, 'native_ordinary_logout'): self.verify()
        self.backend['ordinary_logout']=original
        self.backend['intents'].append('native_control_submit'); self.repin()
        with self.assertRaisesRegex(EvidenceError, 'native_backend'): self.verify()

    def test_producer_origin_request_and_logout_are_bound_to_original_evidence(self):
        for key,change in (('window_origin',{'wall_ms':1000001}),
                           ('native_request',{'run_id':'f'*32}),
                           ('native_request',{'docker_image_id':'sha256:'+'f'*64})):
            original=self.read(key);self.put(key,original|change);self.repin()
            with self.subTest(key=key,change=change),self.assertRaisesRegex(EvidenceError,'native_(window_origin|submission_receipt)'):
                self.verify()
            self.put(key,original)
        for key in ('save_committed_at_ms','logged_out_at_ms','disconnect_requested_at_ms'):
            original=self.backend['ordinary_logout'][key]
            self.backend['ordinary_logout'][key]+=1;self.repin()
            with self.subTest(key=key),self.assertRaisesRegex(EvidenceError,'native_ordinary_logout'):
                self.verify()
            self.backend['ordinary_logout'][key]=original

    def test_runtime_class_baseline_table_and_normalization_are_pinned(self):
        cases = ((self.model_context, 'runtime_manifest_sha256', '9' * 64),
                 (self.model_context['request'], 'baseline_sha256', '9' * 64),
                 (self.row['provenance'], 'native_server_jar_sha256', '9' * 64),
                 (self.row['provenance'], 'experience_table_sha256', '9' * 64),
                 (self.row, 'normalization', {}), (self.row['adaptive'], 'class_profile', {}))
        for owner, key, value in cases:
            old = owner[key]; owner[key] = value
            with self.subTest(key=key), self.assertRaises(EvidenceError): self.verify()
            owner[key] = old

    def test_actual_restored_offline_baseline_required(self):
        restored = self.read('restored_db'); restored['character']['exp'] += 1
        self.put('restored_db', restored); self.repin()
        with self.assertRaisesRegex(EvidenceError, 'actual_restored_baseline'): self.verify()

    def test_recording_overlay_and_45_second_bound(self):
        self.probe['duration_ms'] = 45001
        with self.assertRaisesRegex(EvidenceError, 'native_video_45s_bound'): self.verify()
        self.probe['duration_ms'] = 20100; recording = self.read('recording')
        recording['overlay']['mode'] = 'api'; self.put('recording', recording); self.repin()
        with self.assertRaisesRegex(EvidenceError, 'native_script_recording'): self.verify()

    def test_visual_review_exact_hash_intervals_and_time(self):
        for kind in ('hash', 'time', 'interval', 'missing'):
            self.repin()
            if kind == 'hash': self.review['binding']['video_sha256'] = '0' * 64
            elif kind == 'time': self.review['reviewed_at_ms'] = 1000000
            elif kind == 'interval': self.review['observations']['vertical_jump']['end_ms'] = 45001
            else: del self.review['observations']['monster_contact']
            self.context['visual_review'] = self.write('review.json', self.review)
            with self.subTest(kind=kind), self.assertRaises(EvidenceError): self.verify()

    def test_corrupt_native_ledger_not_replaced_by_claimed_result(self):
        (self.root / self.arts['xp_ledger']['path']).write_bytes(b'forged')
        with self.assertRaises(EvidenceError): self.verify()

    def test_complete_zero_native_hook_does_not_open_the_gate(self):
        from test_full_client_xp_windows import Ledger
        ledger = Ledger(initial={'level': 180, 'exp': 0}, origin=999900, threshold=1000000000)
        ledger.commit(1302000)
        self.put('xp_ledger', ledger.bytes(), raw=True)
        final = self.read('final_db'); final['character']['exp'] = 0; self.put('final_db', final)
        for key in ('xp_ledger', 'final_db'): self.manifest['artifacts'][key] = self.arts[key]
        self.put('native_xp_manifest', self.manifest)
        checked = verify_bundle(self.manifest, self.root)
        self.assertEqual(checked['status'], 'insufficient_positive_native_transaction')
        self.put('native_xp_result', checked); self.complete['result'] = checked; self.repin()
        with self.assertRaisesRegex(EvidenceError, 'positive_complete_native_xp_evidence'): self.verify()

    def test_decoder_failure_not_replaced_by_saved_probe(self):
        with patch('full_client_publish._probe_video', side_effect=ValueError('decode_failed')):
            with self.assertRaisesRegex(ValueError, 'decode_failed'):
                gate.verify_native(self.context, model_root=self.model_root,
                    model_context=self.model_context, model_projection=self.row)


    def test_backend_changed_during_decode_refused(self):
        def swap(*args):
            (self.root / self.context['backend']['path']).write_bytes(b'{}'); return self.probe
        with patch('full_client_publish._probe_video', side_effect=swap), \
             patch('full_client_publish.verify_capture_bundle'), patch('full_client_capture.verify_video_duration'):
            with self.assertRaises(EvidenceError):
                gate.verify_native(self.context, model_root=self.model_root,
                    model_context=self.model_context, model_projection=self.row)

    def test_native_ledger_and_capture_verifiers_integrate_without_stubbed_acceptance(self):
        from full_client_capture import capture_receipt
        result = self.read('native_result'); result['controller']['client'] = 'renderer'
        self.put('native_result', result)
        timestamps = [i * 1000 for i in (*range(0, 20001, 500), 20299)]
        durations = [b - a for a, b in zip(timestamps, timestamps[1:])] + [1000]
        ledger = {'schema_version': 1, 'codec': 'vp8', 'timebase_us': 1000, 'flushed': True,
            'submitted_timestamps_us': timestamps, 'encoded_timestamps_us': timestamps,
            'durations_us': durations, 'encoded_sha256': ['d' * 64] * len(timestamps)}
        ledger_raw = json.dumps(ledger, separators=(',', ':'))
        video_bytes = (self.root / self.arts['video']['path']).stat().st_size
        receipt = {'schema_version': 1, 'codec': 'vp8', 'timebase_us': 1000,
            'submitted_frames': len(timestamps), 'encoded_frames': len(timestamps), 'flushed': True,
            'ledger_sha256': hashlib.sha256(ledger_raw.encode()).hexdigest(), 'ledger_bytes': len(ledger_raw),
            'webm_sha256': self.arts['video']['sha256'], 'webm_bytes': video_bytes}
        clock = {'id': 'e' * 32, 'client_sent_ms': 999900,
            'server_received_ms': 1000000, 'server_sent_ms': 1000000}
        anchor = {'runId': 'a' * 32, 'serverReceivedAtMs': 1000000, 'renderedFrames': 1}
        terminal = {'id': 'f' * 32, 'serverIssuedAtMs': 1020110}
        raw = {'schema_version': 3, 'run_id': 'a' * 32, 'client_id': 'renderer',
            'start_wall_ms': 999900, 'end_wall_ms': 1020200, 'duration_ms': 20300,
            'first_frame_wall_ms': 999900, 'last_frame_wall_ms': 1020199,
            'first_frame_offset_ms': 0, 'last_frame_offset_ms': 20299,
            'rendered_frames': len(timestamps), 'max_frame_gap_ms': 500,
            'hidden': False, 'errors': 0, 'relay_lost': False, 'interrupted': False,
            'clock': clock | {'client_received_ms': 1000000}, 'terminal_token': terminal['id'],
            'capture_duration_policy': self.native['capture_duration_policy'], 'encoder_receipt': receipt}
        for name, value in (('capture', raw), ('capture_clock', clock), ('capture_ready', anchor),
                            ('capture_terminal', terminal)): self.put(name, value)
        owner = result['controller'] | {'startedAtMs': result['timing']['startedAtMs']}
        recording = capture_receipt(raw, owner, anchor, clock, terminal) | {
            'status': 'completed', 'sha256': self.arts['video']['sha256'],
            'capture_sha256': self.arts['capture']['sha256'],
            'overlay': {'controller_id': 'a' * 32, 'mode': 'script', 'model': None}}
        self.put('recording', recording)
        self.manifest['artifacts']['native_result'] = self.arts['native_result']
        self.put('native_xp_manifest', self.manifest)
        checked = verify_bundle(self.manifest, self.root)
        self.put('native_xp_result', checked); self.complete['result'] = checked; self.repin()
        probe = {'duration_ms': 20300, 'presentation_span_ms': 20299, 'presentation_extent_ms': 20300,
            'last_packet_duration_ms': 1, 'frames': len(timestamps),
            'packet_timestamps_us': timestamps, 'packet_durations_us': durations,
            'packet_sha256': ledger['encoded_sha256'], 'encoder_ledger_json': ledger_raw,
            'webm_sha256': self.arts['video']['sha256'], 'webm_bytes': video_bytes}
        with patch('full_client_publish._probe_video', return_value=probe):
            accepted = gate.verify_native(self.context, model_root=self.model_root,
                model_context=self.model_context, model_projection=self.row)
            self.assertEqual(accepted['status'], 'native_runtime_evidence_rechecked')
            probe['frames'] += 1
            with self.assertRaisesRegex(ValueError, 'recording_encoded_frames_mismatch'):
                gate.verify_native(self.context, model_root=self.model_root,
                    model_context=self.model_context, model_projection=self.row)


class ModelPublicationGateTests(unittest.TestCase):
    """Real synthetic model ledger/cycle projection; native gate explicitly stubbed."""
    def setUp(self):
        self.f = model_fixtures.NativePublicationTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root = self.f.root; self.context = self.f.context
        self.raw = self.f.project(strict=True)
        self.native = {'status': 'native_runtime_evidence_rechecked', 'sha256': '3' * 64}
        provenance = self.raw['provenance']
        self.review = {'schema_version': 1, 'protocol': gate.MODEL_REVIEW, 'reviewed_at_ms': 1400000,
            'binding': {'run_id': self.context['run_id'], 'model': self.context['request']['model'],
                'video_sha256': self.raw['recording']['sha256'],
                'xp_manifest_sha256': provenance['artifact_sha256']['xp_manifest'],
                'capture_sha256': provenance['artifact_sha256']['capture'],
                'recording_sha256': provenance['artifact_sha256']['recording'],
                'runtime_manifest_sha256': self.context['runtime_manifest_sha256'],
                'projection_provenance_sha256': gate.digest(provenance), 'native_acceptance_sha256': self.native['sha256']},
            'observations': {label: {'start_ms': 100, 'end_ms': 200} for label in
                ('exact_model_overlay', 'recording_matches_actions_and_waits', 'native_hud')}}
        self.repin()

    def repin(self):
        self.ref = self.f.h.save('model-review.json', self.review)

    def project(self, *, strict=False, native_error=None, **kwargs):
        with patch('full_client_publish._probe_video', return_value=self.f.probe), \
             patch('full_client_native_xp_gate.verify_native', return_value=self.native, side_effect=native_error):
            fn = publication.verify_attempt if strict else publication.project_attempt
            return fn(self.root, self.context, **kwargs)

    def test_default_call_is_identical_and_publication_remains_blocked(self):
        self.assertEqual(self.project(strict=True), self.raw)
        self.assertEqual(self.project(), self.raw)
        self.assertFalse(self.raw['publication_eligible']); self.assertFalse(self.raw['ranked'])

    def test_native_gate_alone_requires_independent_model_video_review(self):
        result = self.project(native_acceptance={'synthetic_gate_stub': True})
        self.assertEqual(result['native_runtime_acceptance'], self.native)
        self.assertEqual(result['publication_blocker'], 'model_recording_visual_review_required')
        self.assertEqual(result['recording']['visual_review'], 'not_assessed')
        self.assertFalse(result['publication_eligible'])

    def test_exact_model_video_review_changes_eligibility_but_never_ranking_or_protocol(self):
        result = self.project(strict=True, native_acceptance={'synthetic_gate_stub': True}, recording_review=self.ref)
        self.assertTrue(result['publication_eligible']); self.assertFalse(result['ranked'])
        self.assertIsNone(result['publication_blocker'])
        self.assertEqual(result['wall_budget_ms'], 300000)
        self.assertEqual(result['protocol'], publication.PROTOCOL)
        self.assertEqual(result['recording']['visual_review_sha256'], self.ref['sha256'])

    def test_invalid_native_gate_preserves_verified_signed_metric(self):
        self.f.make(initial_exp=5000, final_exp=4500); self.context = self.f.context
        result = self.project(native_acceptance={'accepted': True}, native_error=EvidenceError('invalid_gate'))
        self.assertEqual(result['status'], 'verified_native_windows')
        self.assertEqual(result['persisted_net_xp'], -500)
        self.assertEqual(result['windows'][0]['net_xp'], -500)
        self.assertFalse(result['publication_eligible'])
        self.assertEqual(result['publication_blocker'], 'native_runtime_acceptance_unverified')
        with self.assertRaises(EvidenceError):
            self.project(strict=True, native_acceptance={}, native_error=EvidenceError('invalid_gate'))

    def test_wrong_model_video_manifest_native_gate_or_provenance_review_refuses(self):
        original = copy.deepcopy(self.review)
        for key in ('run_id', 'model', 'video_sha256', 'xp_manifest_sha256', 'native_acceptance_sha256',
                    'projection_provenance_sha256', 'runtime_manifest_sha256'):
            self.review = copy.deepcopy(original); self.review['binding'][key] = 'changed'; self.repin()
            result = self.project(native_acceptance={}, recording_review=self.ref)
            self.assertFalse(result['publication_eligible'])
            self.assertEqual(result['publication_blocker'], 'model_recording_visual_review_unverified')
            self.assertEqual(result['persisted_net_xp'], self.raw['persisted_net_xp'])
            self.assertEqual(result['recording']['visual_review'], 'not_assessed')

    def test_bare_review_boolean_and_review_without_native_acceptance_cannot_publish(self):
        result = self.project(native_acceptance={}, recording_review={'accepted': True})
        self.assertFalse(result['publication_eligible'])
        result = self.project(recording_review=self.ref)
        self.assertFalse(result['publication_eligible'])
        self.assertEqual(result['persisted_net_xp'], self.raw['persisted_net_xp'])

    def test_missing_model_metric_evidence_stays_unknown_despite_supplied_reviews(self):
        (self.root / self.f.refs['xp_ledger']['path']).unlink()
        result = self.project(native_acceptance={}, recording_review=self.ref)
        self.assertEqual(result['status'], 'unknown'); self.assertIsNone(result['persisted_net_xp'])
        self.assertFalse(result['publication_eligible'])

    def test_observation_only_zero_model_is_reviewable_without_positive_action_requirement(self):
        class ObserveOnly(model_fixtures.Harness):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs); self.code = 'await sdk.observe();'
            def execute(self, code, **kwargs):
                self.programs.append((code, kwargs)); self.now += min(self.program_seconds, kwargs['program_seconds'])
                step = {'kind': 'sdk', 'rpcId': 1, 'method': 'observe', 'args': [], 'result': self.observation()}
                kwargs['step_callback'](step)
                return {'actions': 0, 'actionAttempts': 0, 'rpcRequests': 1, 'steps': [step],
                        'reason': 'program_complete', 'error': None}
        with patch.object(model_fixtures, 'Harness', ObserveOnly):
            self.f.make(final_exp=0, transitions=[])
        self.context = self.f.context; self.raw = self.f.project(strict=True)
        provenance = self.raw['provenance']; binding = self.review['binding']
        binding['video_sha256'] = self.raw['recording']['sha256']
        for name in ('xp_manifest', 'capture', 'recording'):
            binding[name + '_sha256'] = provenance['artifact_sha256'][name]
        binding['projection_provenance_sha256'] = gate.digest(provenance)
        binding['runtime_manifest_sha256'] = self.context['runtime_manifest_sha256']; self.repin()
        result = self.project(strict=True, native_acceptance={}, recording_review=self.ref)
        self.assertEqual(self.f.result['adaptive']['counters']['actions'], 0)
        self.assertEqual(result['persisted_net_xp'], 0)
        self.assertTrue(result['publication_eligible']); self.assertFalse(result['ranked'])
