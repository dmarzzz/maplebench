"""Native toolkit acceptance structure only; no game, API, SQL or video decode."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import full_client_native as native
import full_client_native_xp_acceptance as acceptance
import full_client_skill_toolkit as skills
import test_full_client_native_xp_gate as gate_fixtures
from full_client_score import EvidenceError


class ToolkitNativeXpTests(unittest.TestCase):
    def setUp(self):
        self.g = gate_fixtures.NativeGateTests(); self.g.setUp(); self.addCleanup(self.g.doCleanups)
        g = self.g
        g.native = native.contract('hero', g.manifest['baseline_sha256'], protocol=skills.NATIVE_PROTOCOL)
        scenario = g.read('scenario'); scenario['native_contract'] = g.native; g.put('scenario', scenario)
        g.manifest['scenario_fingerprint'] = g.arts['scenario']['sha256']
        program = native.program(g.native).encode(); g.put('native_program', program, raw=True)
        result = g.read('native_result'); result.update(protocol=g.native['id'], nativeAcceptance=g.native,
            programSha256=hashlib.sha256(program).hexdigest())
        result['controller'].update(protocol=g.native['id'], nativeAcceptance=g.native)
        result['timeline']['program_ended_ms'] = 60000
        result['timing'].update(endedAtMs=1060100, elapsedMs=60100)
        # Reuse original receipt count; exercise an extra actual toolkit slot.
        result['program']['steps'][0]['args'][0] = [g.native['skill_toolkit']['skills'][-1]['slot']]
        g.put('native_result', result)
        control = g.read('controller_result'); control.update(ended_at_ms=1060000,
            program_sha256=result['programSha256']); g.put('controller_result', control)
        coverage = [json.loads(line) for line in (g.root/g.arts['coverage']['path']).read_bytes().splitlines()]
        for row in coverage: row['controller_idle'] = row['sequence']==0 or row['wall_ms']>=1060000
        g.put('coverage', b''.join(json.dumps(row).encode()+b'\n' for row in coverage), raw=True)
        for name in g.manifest['artifacts']:
            g.manifest['artifacts'][name] = g.arts['baseline' if name=='baseline_sql' else name]
        checked = acceptance.verify_bundle(g.manifest, g.root)
        g.put('native_xp_manifest', g.manifest); g.put('native_xp_result', checked)
        g.complete['result'] = checked
        g.row['adaptive']['class_profile'] = copy.deepcopy(g.native['profile'])
        g.row['provenance']['skill_toolkit_sha256'] = skills.fingerprint(g.native['skill_toolkit'])
        g.probe = {'duration_ms':60100,'presentation_span_ms':60099,'presentation_extent_ms':60100}
        self.repin_review()

    def repin_review(self):
        g = self.g; g.repin()
        g.review['binding']['skill_toolkit_sha256'] = skills.fingerprint(g.native['skill_toolkit'])
        g.review['observations'].update({'skill_'+s['slot']:{'start_ms':100,'end_ms':200}
                                      for s in g.native['skill_toolkit']['skills']})
        g.context['visual_review'] = g.write('review.json', g.review)

    def test_canonical_sixty_second_native_control_and_all_skill_review(self):
        accepted = self.g.verify()
        self.assertEqual(accepted['skill_toolkit_sha256'], skills.fingerprint(self.g.native['skill_toolkit']))
        self.assertEqual(self.g.complete['result']['diagnostic_windows']['complete_windows'], 20)
        self.assertGreater(self.g.complete['result']['positive_transactions'], 0)

    def test_overall_positive_xp_does_not_replace_missing_skill_effect(self):
        label = next(k for k in self.g.review['observations'] if k.startswith('skill_'))
        del self.g.review['observations'][label]
        self.g.context['visual_review'] = self.g.write('review.json', self.g.review)
        with self.assertRaisesRegex(EvidenceError, 'visual_observations_required'): self.g.verify()

    def test_old_or_changed_model_toolkit_cannot_reuse_native_qualification(self):
        for value in (None, '1'*64):
            self.g.row['provenance']['skill_toolkit_sha256'] = value
            with self.subTest(value=value), self.assertRaisesRegex(EvidenceError, 'native_model_toolkit_mismatch'):
                self.g.verify()

    def test_seventy_five_second_capture_is_still_a_hard_bound(self):
        self.g.probe['duration_ms'] = 75001
        with self.assertRaisesRegex(EvidenceError, 'native_video_75s_bound'): self.g.verify()

    def test_unfrozen_extended_duration_and_false_idle_are_refused(self):
        raw = (self.g.root/self.g.arts['coverage']['path']).read_bytes()
        control = self.g.read('controller_result')
        with self.assertRaisesRegex(EvidenceError, 'native_coverage_control_mismatch'):
            acceptance.verify_coverage(raw, {k:self.g.manifest[k] for k in acceptance.IDENTITY},
                self.g.manifest['window'], control=control)
        rows = [json.loads(line) for line in raw.splitlines()]; rows[40]['controller_idle'] = True
        with self.assertRaisesRegex(EvidenceError, 'native_control_idle_before_completion'):
            acceptance.verify_coverage(b''.join(json.dumps(row).encode()+b'\n' for row in rows),
                {k:self.g.manifest[k] for k in acceptance.IDENTITY},self.g.manifest['window'],
                control=control,native_contract=self.g.native)


if __name__=='__main__':unittest.main()
