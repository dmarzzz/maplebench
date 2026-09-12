"""Native-window projection with synthetic native/controller/capture evidence."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import full_client_xp_publication as publication
import full_client_xp_windows as windows
import full_client_adaptive as adaptive
from full_client_adaptive_publication import verified_adaptive_score
from full_client_dashboard import Reader
from full_client_capture import capture_receipt, CAPTURE_DURATION_POLICY
from full_client_publish import SETTLEMENT_POLICY
from full_client_score import EvidenceError
from docker_binding_fixture import local_binding
from test_full_client_adaptive import Harness
import test_full_client_xp_windows as native_fixtures
from test_full_client_xp_windows import Ledger, IDENTITY, NORM


class NativePublicationTests(unittest.TestCase):
    def setUp(self):
        self.f = native_fixtures.BundleTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        self.root = self.f.root.resolve()
        self.model = 'gpt-6-astra'; self.ident = 'a' * 32
        self.binding = local_binding(self, self.root)
        self.make()

    def read(self, name):
        return json.loads((self.root / self.refs[name]['path']).read_text())

    def save(self, name, value, raw=False):
        suffix = '.webm' if name == 'video' else ('.bin' if raw else '.json')
        content = value if raw else json.dumps(value).encode()
        ref = self.h.raw(name + suffix, content); self.refs[name] = ref
        return ref

    def make(self, *, progression=False, final_level=180, final_exp=4500, initial_exp=0, normalization=None, transitions=None, frame_policy=False, horizon=None):
        self.h = Harness(self.root, calls=12)
        self.h.p['horizon_policy'] = copy.deepcopy(horizon or adaptive.FULL_HORIZON_POLICY)
        if frame_policy:
            self.h.p['capture_duration_policy'] = copy.deepcopy(CAPTURE_DURATION_POLICY)
        ordinary_observation = self.h.observation
        def initial_observation():
            value = ordinary_observation(); value['character']['exp'] = initial_exp
            return value
        self.h.observation = initial_observation
        if progression:
            self.h.p['progression_policy'] = copy.deepcopy(adaptive.NATIVE_PROGRESSION_POLICY)
            old = self.h.observation
            def observe():
                value = old()
                if self.h.now >= 25: value['character'].update(level=final_level, exp=final_exp)
                return value
            self.h.observation = observe
        self.h.run(sleep=lambda seconds: setattr(self.h, 'now', self.h.now + seconds))
        self.result = self.h.result()
        # Start from the complete native fixture, preserving its fixed field contracts.
        self.refs = copy.deepcopy(self.f.arts)
        for source, target in (('native_save', 'save'), ('baseline_sql', 'baseline'), ('controller_result', 'result')):
            self.refs[target] = self.refs.pop(source)
        scenario = self.read('scenario')
        scenario['adaptive_protocol'] = copy.deepcopy(self.h.p)
        scenario['instructions_sha256'] = self.result['adaptive']['instructions']['sha256']
        scenario['settlement_policy'] = copy.deepcopy(SETTLEMENT_POLICY)
        scenario['trial_budgets'] = {'total_seconds': 1200, 'operation_seconds': 360, 'controller_seconds': 300,
            'max_actions': 1600, 'max_api_requests': 12, 'max_output_tokens': 36000, 'max_total_tokens': 120000}
        scenario['xp_window_protocol']['normalization'] = copy.deepcopy(normalization or NORM)
        self.save('scenario', scenario)
        initial = self.read('initial_db'); initial['character']['exp'] = initial_exp
        baseline = self.read('baseline_snapshot'); baseline['character']['exp'] = initial_exp
        self.save('initial_db', initial); self.save('baseline_snapshot', baseline)
        final = self.read('final_db'); final['character'].update(level=final_level, exp=final_exp)
        self.save('final_db', final)
        self.ledger = Ledger(initial={'level': 180, 'exp': initial_exp}, origin=999900, threshold=1000000000,
                             normalization=normalization)
        for at, level, exp in (transitions if transitions is not None else [(1025000 if progression else 1005000, final_level, final_exp)]):
            self.ledger.transition(at, level, exp)
        self.ledger.commit(1302000); self.save('xp_ledger', self.ledger.bytes(), raw=True)
        session = self.read('session'); session['upload_observed_at_ms'] = 1300500
        self.save('session', session)
        upload = {'schema_version': 1, 'source': 'full_client_runtime_status', **IDENTITY,
            'observed_at_ms': 1300500, 'status': {'bridge': {'run': {'id': self.ident, 'status': 'completed',
                'evidenceStatus': 'saved', 'recordingStatus': 'saved', 'workerActive': False,
                'leaseReleasePending': False}, 'browserReleasePending': False}, 'session': {'artifactsSettled': True}}}
        self.save('upload_status', upload)
        runtime = {'schema_version': 2, 'docker_binding': self.binding, 'docker_image_id': 'sha256:' + 'f' * 64,
                   'server_jar': {'path': '/private/synthetic-server.jar', 'sha256': 'e' * 64}}
        self.save('runtime_manifest', runtime)
        request = {'schema_version': 3, 'protocol': windows.PROTOCOL, 'model': self.model,
                   'scenario_fingerprint': self.refs['scenario']['sha256'], 'baseline_sha256': self.refs['baseline']['sha256'],
                   'budgets': scenario['trial_budgets']}
        trial_context = {key: request[key] for key in ('scenario_fingerprint', 'baseline_sha256')}
        self.result['trialContext'] = trial_context
        self.result['controller'].update(mode='api', client='synthetic-browser', trialContext=trial_context,
            dockerImageId=runtime['docker_image_id'], dockerBinding=self.binding)
        self.result['observedXpDelta'] = 999999999
        self.save('result', self.result)
        self.save('video', b'SYNTHETIC NONDECODABLE VIDEO', raw=True)
        start = self.result['timing']['startedAtMs']; end = self.result['timing']['endedAtMs']
        clock = {'id': 'synthetic-clock', 'client_sent_ms': start, 'server_received_ms': start, 'server_sent_ms': start}
        ready = {'runId': self.ident, 'serverReceivedAtMs': start + 20, 'renderedFrames': 1}
        terminal = {'id': 'f' * 32, 'serverIssuedAtMs': end + 10}
        capture = {'schema_version': 1, 'run_id': self.ident, 'client_id': 'synthetic-browser',
            'start_wall_ms': start, 'end_wall_ms': end + 100, 'duration_ms': end + 100 - start,
            'first_frame_wall_ms': start + 10, 'last_frame_wall_ms': end + 90,
            'rendered_frames': 9000, 'max_frame_gap_ms': 34, 'hidden': False, 'errors': 0,
            'relay_lost': False, 'interrupted': False, 'clock': clock | {'client_received_ms': start},
            'terminal_token': terminal['id']}
        if frame_policy:
            capture.update(schema_version=2, capture_duration_policy=copy.deepcopy(CAPTURE_DURATION_POLICY),
                first_frame_offset_ms=109, last_frame_offset_ms=capture['duration_ms'] - 96,
                first_frame_wall_ms=start + 109, last_frame_wall_ms=end + 4, max_frame_gap_ms=215)
        for name, value in [('capture', capture), ('capture_clock', clock), ('capture_ready', ready), ('capture_terminal', terminal)]:
            self.save(name, value)
        recording = {'status': 'completed', 'sha256': self.refs['video']['sha256'],
            'capture_sha256': self.refs['capture']['sha256'],
            'overlay': {'controller_id': self.ident, 'mode': 'api', 'model': self.model},
            **capture_receipt(capture, {'id': self.ident, 'client': 'synthetic-browser',
                'startedAtMs': start, 'protocol': adaptive.PROTOCOL, 'adaptiveProtocol': self.h.p}, ready, clock, terminal)}
        self.save('recording', recording)
        names = {'native_save': 'save', 'baseline_sql': 'baseline', 'controller_result': 'result'}
        self.manifest = copy.deepcopy(self.f.manifest)
        self.manifest.update(scenario_fingerprint=request['scenario_fingerprint'],
                             normalization=scenario['xp_window_protocol']['normalization'])
        self.manifest['artifacts'] = {name: self.refs[names.get(name, name)] for name in self.f.manifest['artifacts']}
        self.save('xp_manifest', self.manifest)
        score = windows.verify_trial_bundle(self.manifest, self.root, self.refs); self.save('score', score)
        counts = self.result['adaptive']['counters']
        self.journal = {'schema_version': 1, 'attempt_id': self.ident, 'request': request, 'adapter_fingerprint': '9' * 64,
            'status': 'completed', 'phase': 'status', 'phase_status': 'returned', 'api_outcome': 'confirmed',
            'charged_usage': {'api_requests': counts['api_responses_confirmed'], 'total_tokens': counts['actual_total_tokens']},
            'events': [{'sequence': 0, 'kind': 'created'}, {'sequence': 1, 'kind': 'evidence_verified'}], 'score': score,
            'receipts': {'collect_final': {'artifacts': self.refs}, 'cleanup': {'attempt_id': self.ident, 'clean': True},
                         'status': {k: k != 'ownership_conflict' for k in publication.STATUS_FIELDS}}}
        self.backend = {'attempt_id': self.ident, 'clean': True, 'ordinary_logout': {'confirmed': True},
                        'xp_header': {'sha256': hashlib.sha256(self.ledger.rows[0]).hexdigest()}}
        self.context = {'schema_version': 1, 'protocol': publication.PROTOCOL, 'run_id': self.ident, 'request': request,
            'adapter_fingerprint': '9' * 64, 'runtime_manifest_sha256': self.refs['runtime_manifest']['sha256'],
            'scorer_sha256': hashlib.sha256(Path(windows.__file__).read_bytes()).hexdigest()}
        self.repin()
        self.probe = {'duration_ms': recording['duration_ms'], 'width': 1024, 'height': 768, 'frames': 9000}
        if frame_policy:
            extent = recording['duration_ms'] - 117.265
            self.probe.update(duration_ms=extent, presentation_span_ms=extent - 1,
                presentation_extent_ms=extent, last_packet_duration_ms=1, frames=9001)

    def repin(self):
        self.context['journal'] = self.h.save('journal.json', self.journal)
        self.context['backend'] = self.h.save('backend-state.json', self.backend)

    def project(self, strict=False):
        with patch('full_client_publish._probe_video', return_value=self.probe) as probe:
            value = (publication.verify_attempt if strict else publication.project_attempt)(self.root, self.context)
        return value

    def assertUnknown(self):
        value = self.project()
        self.assertEqual(value['status'], 'unknown')
        for key in ('authoritative_peak_xp_per_minute', 'persisted_net_xp', 'complete_windows', 'recording'):
            self.assertIsNone(value[key])
        self.assertEqual(value['windows'], []); self.assertFalse(value['publication_eligible'])
        self.assertNotIn(str(self.root), json.dumps(value))

    def test_complete_native_projection_has_twenty_windows_and_exact_provenance(self):
        value = self.project(strict=True)
        self.assertEqual(value['authoritative_peak_xp_per_minute'], 18000)
        self.assertEqual(value['persisted_net_xp'], 4500); self.assertEqual(value['control_window_net_xp'], 4500)
        self.assertEqual(len(value['windows']), 20); self.assertEqual(value['windows'][0]['start_ms'], 0)
        self.assertEqual(value['windows'][-1]['end_ms'], 300000)
        self.assertEqual(value['requested_model'], value['returned_model'])
        self.assertEqual(len(value['adaptive']['cycles']), 8)
        self.assertIsNone(value['adaptive']['authoritative_peak_xp_per_minute'])
        self.assertEqual(value['provenance']['artifact_sha256']['xp_ledger'], self.refs['xp_ledger']['sha256'])
        self.assertFalse(value['ranked']); self.assertFalse(value['publication_eligible'])
        text = json.dumps(value)
        for private in ('synthetic baseline', '/private/', str(self.root), 'account_id', 'character_id', 'recent_programs', 'code'):
            self.assertNotIn(private, text)

    def test_level_progression_requires_native_context_and_is_not_legacy_net_xp(self):
        self.make(progression=True, final_level=181, final_exp=0)
        value = self.project(strict=True)
        self.assertEqual((value['initial_level'], value['final_level']), (180, 181))
        self.assertEqual(value['persisted_net_xp'], 1000000000)
        self.assertEqual(value['authoritative_peak_xp_per_minute'], 4000000000)
        with self.assertRaises(ValueError): verified_adaptive_score(Reader(), self.root, self.journal)

    def test_final_slot_keeps_twenty_native_windows_and_exact_controller_receipts(self):
        self.make(horizon=adaptive.FINAL_SLOT_POLICY)
        value = self.project(strict=True)
        self.assertEqual(value['complete_windows'], 20)
        self.assertEqual(value['authoritative_peak_xp_per_minute'], 18000)
        self.assertEqual(value['adaptive']['horizon_policy'], adaptive.FINAL_SLOT_POLICY)
        self.assertFalse(value['publication_eligible'])

    def test_zero_is_only_published_with_complete_evidence(self):
        self.make(final_exp=0, transitions=[])
        self.assertEqual(self.project(strict=True)['authoritative_peak_xp_per_minute'], 0)
        (self.root / self.refs['xp_ledger']['path']).unlink(); self.assertUnknown()

    def test_signed_losses_and_deadline_xp_are_separate_from_peak(self):
        self.make(final_exp=100, transitions=[(1005000, 180, 4500), (1020000, 180, 0), (1300000, 180, 100)])
        value = self.project(strict=True)
        self.assertEqual(value['windows'][1]['net_xp'], -4500)
        self.assertEqual(value['authoritative_peak_xp_per_minute'], 18000)
        self.assertEqual(value['control_window_net_xp'], 0); self.assertEqual(value['persisted_net_xp'], 100)

    def test_negative_total_is_preserved_with_only_the_peak_zero_floor(self):
        self.make(initial_exp=5000, final_exp=4500)
        value = self.project(strict=True)
        self.assertEqual(value['persisted_net_xp'], -500)
        self.assertEqual(value['control_window_net_xp'], -500)
        self.assertEqual(value['windows'][0]['normalized_xp_per_minute'], -2000)
        self.assertEqual(value['authoritative_peak_xp_per_minute'], 0)

    def test_declared_rate_and_speed_are_removed(self):
        norm = {'server_xp_multiplier': {'numerator': 2, 'denominator': 1},
                'simulation_speed_multiplier': {'numerator': 3, 'denominator': 1}}
        self.make(normalization=norm)
        self.assertEqual(self.project(strict=True)['authoritative_peak_xp_per_minute'], 3000)

    def test_native_commit_coverage_missing_remains_unknown_after_rehash(self):
        raw = b''.join(self.ledger.rows[:-1]); self.save('xp_ledger', raw, raw=True)
        self.manifest['artifacts']['xp_ledger'] = self.refs['xp_ledger']; self.save('xp_manifest', self.manifest)
        self.repin(); self.assertUnknown()

    def test_earlier_cycle_and_native_save_corruption_cannot_use_last_cycle_or_client_xp(self):
        for name in ('save', 'xp_ledger'):
            p = self.root / self.refs[name]['path']; old = p.read_bytes(); p.write_bytes(b'{}')
            self.assertUnknown(); p.write_bytes(old)
        p = self.root / self.result['adaptive']['cycles'][0]['response']['path']; p.write_bytes(b'{}')
        self.assertUnknown()

    def test_context_pins_and_saved_score_cannot_be_substituted(self):
        for key in ('scorer_sha256', 'runtime_manifest_sha256', 'adapter_fingerprint'):
            old = self.context[key]; self.context[key] = '0' * 64; self.assertUnknown(); self.context[key] = old
        self.journal['score']['task_score'] = 1; self.repin(); self.assertUnknown()

    def test_ordinary_logout_startup_header_cleanup_and_usage_are_required(self):
        for obj, key, bad in ((self.backend, 'clean', False), (self.backend, 'ordinary_logout', {'confirmed': False}),
                             (self.backend, 'xp_header', {'sha256': '0' * 64}), (self.journal, 'api_outcome', 'uncertain'),
                             (self.journal, 'charged_usage', {'api_requests': 0, 'total_tokens': 0})):
            old = copy.deepcopy(obj[key]); obj[key] = bad; self.repin(); self.assertUnknown()
            obj[key] = old; self.repin()

    def test_explicit_postrender_policy_uses_frame_endpoints_with_native_windows(self):
        self.make(frame_policy=True)
        value = self.project(strict=True)
        self.assertEqual(value['authoritative_peak_xp_per_minute'], 18000)
        self.assertEqual(value['provenance']['capture_duration_policy'], CAPTURE_DURATION_POLICY)
        self.assertAlmostEqual(self.read('recording')['duration_ms'] - value['recording']['duration_ms'], 117.265)
        self.assertEqual(value['complete_windows'], 20)

    def test_progression_and_capture_optins_compose_without_changing_legacy_prompt(self):
        self.make(progression=True, final_level=181, final_exp=0, frame_policy=True)
        value = self.project(strict=True)
        self.assertEqual(value['final_level'], 181)
        self.assertEqual(value['authoritative_peak_xp_per_minute'], 4000000000)
        plain = copy.deepcopy(self.h.p); plain.pop('capture_duration_policy')
        self.assertEqual(adaptive.prompt(plain), adaptive.prompt(self.h.p))

    def test_forged_frame_count_span_or_tail_cannot_use_optin_allowance(self):
        self.make(frame_policy=True)
        original = copy.deepcopy(self.probe)
        for change in ({'frames': 9002}, {'presentation_span_ms': 300199},
                       {'last_packet_duration_ms': 251}, {'presentation_extent_ms': 335001},
                       {'presentation_span_ms': 299000}):
            self.probe = original | change; self.assertUnknown()

    def test_raw_schema_or_undeclared_policy_cannot_be_inferred_from_video(self):
        self.make(frame_policy=True)
        capture = self.read('capture'); capture['schema_version'] = 1
        self.save('capture', capture); self.repin(); self.assertUnknown()
        self.make()
        recording = self.read('recording'); recording['capture_duration_policy'] = copy.deepcopy(CAPTURE_DURATION_POLICY)
        self.save('recording', recording); self.repin(); self.assertUnknown()

    def test_recording_policy_or_monotonic_endpoint_corruption_stays_unknown(self):
        self.make(frame_policy=True)
        recording = self.read('recording'); recording['first_frame_offset_ms'] += 1
        self.save('recording', recording); self.repin(); self.assertUnknown()
        self.make(frame_policy=True)
        recording = self.read('recording'); recording['capture_duration_policy']['max_endpoint_gap_ms'] = 500
        self.save('recording', recording); self.repin(); self.assertUnknown()

    def test_corrupt_recording_or_old_duration_tolerance_stays_unknown(self):
        p = self.root / self.refs['video']['path']; raw = p.read_bytes(); p.write_bytes(b'bad')
        self.assertUnknown(); p.write_bytes(raw)
        self.probe['duration_ms'] -= 117.265; self.assertUnknown()

    def test_capture_overlay_and_terminal_receipt_must_match(self):
        recording = self.read('recording'); recording['overlay']['model'] = 'gpt-5.6-sol'
        self.save('recording', recording); self.repin(); self.assertUnknown()

    def test_frozen_settlement_refuses_incomplete_upload_after_rehash(self):
        upload = self.read('upload_status'); upload['status']['session']['artifactsSettled'] = False
        self.save('upload_status', upload); self.repin(); self.assertUnknown()

    def test_changed_contract_prompt_or_class_cannot_be_substituted(self):
        scenario = self.read('scenario'); scenario['adaptive_protocol']['profile']['class_name'] = 'Bowmaster'
        self.save('scenario', scenario); self.repin(); self.assertUnknown()

    def test_decoder_failure_and_journal_swap_are_unknown(self):
        with patch('full_client_publish._probe_video', side_effect=EvidenceError('synthetic decode refusal')):
            value = publication.project_attempt(self.root, self.context)
        self.assertIsNone(value['authoritative_peak_xp_per_minute'])
        def changed(*args, **kwargs):
            (self.root / 'journal.json').write_text('{}')
            return self.probe
        with patch('full_client_publish._probe_video', side_effect=changed):
            value = publication.project_attempt(self.root, self.context)
        self.assertEqual(value['status'], 'unknown')

    def test_legacy_or_unpinned_context_is_rejected_before_artifact_reads(self):
        for change in ({'protocol': adaptive.PROTOCOL}, {'request': self.context['request'] | {'schema_version': 2, 'protocol': adaptive.PROTOCOL}},
                       {'journal': {'path': '../journal.json', 'sha256': '0' * 64}}):
            with self.assertRaises(ValueError): publication.project_attempt(self.root, self.context | change)

    def test_missing_capture_fields_and_symlinked_evidence_never_produce_a_score(self):
        p = self.root / self.refs['capture']['path']; p.unlink(); p.symlink_to(self.root / self.refs['result']['path'])
        self.assertUnknown()

    def test_no_model_or_game_actions_are_called_by_projection(self):
        with patch('full_client_runtime.CosmicRuntime.perform', side_effect=AssertionError('runtime action')):
            self.assertEqual(self.project(strict=True)['status'], 'verified_native_windows')


if __name__ == '__main__': unittest.main()
