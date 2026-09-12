"""Synthetic thirty-minute model trace and native ledger; no API or runtime."""
import copy
import json
import unittest

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))

import full_client_adaptive as adaptive
import full_client_xp_windows as windows
from full_client_score import EvidenceError
from test_full_client_adaptive import Harness
import test_full_client_xp_windows as fixtures


class LongNativeWindowTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.BundleTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        self.h = Harness(self.f.root, calls=72)
        self.h.p = adaptive.long_horizon_protocol(self.h.p['profile'])
        self.h.run(sleep=lambda seconds: setattr(self.h, 'now', self.h.now + seconds))
        self.f.save('controller_result', self.h.result())
        scenario = self.read('scenario')
        scenario['adaptive_protocol'] = self.h.p; scenario['xp_window_protocol']['wall_seconds'] = 1800
        self.f.manifest['scenario_fingerprint'] = self.f.save('scenario', scenario)['sha256']
        self.f.manifest['window']['deadline_at_ms'] = 2800000
        final = self.read('final_db'); final['captured_at_ms'] = 2804000; final['character']['exp'] = 100
        self.f.save('final_db', final)
        ledger = fixtures.Ledger(initial={'level': 180, 'exp': 0}, origin=999900, threshold=1000000000)
        ledger.transition(1005000, 180, 4500); ledger.transition(2799999, 180, 5000)
        ledger.transition(2800000, 180, 100); ledger.commit(2802000)
        self.f.save('xp_ledger', ledger.bytes(), True)
        native = self.read_lines('native_save'); native[0]['committed_at_ms'] = 2802000
        self.f.bind_save_artifact('native_save', self.lines(native), 'evidence_sha256')
        events = self.read_lines('server_log')
        for event in events:
            if event['at_ms'] >= 1300000: event['at_ms'] += 1500000
        self.f.bind_save_artifact('server_log', self.lines(events), 'logs_sha256')
        session = self.read('session')
        for obj in (session, session['save']):
            for key, value in list(obj.items()):
                if key.endswith('_ms') and type(value) is int and value >= 1300000:
                    obj[key] = value + 1500000
        self.f.save('session', session)

    def read(self, name):
        return json.loads((self.f.root / self.f.arts[name]['path']).read_bytes())

    def read_lines(self, name):
        return [json.loads(line) for line in (self.f.root / self.f.arts[name]['path']).read_bytes().splitlines()]

    @staticmethod
    def lines(rows):
        return b''.join(json.dumps(row).encode() + b'\n' for row in rows)

    def test_real_synthetic_trace_and_ledger_cover_120_windows(self):
        result = windows.verify_bundle(self.f.manifest, self.f.root)
        self.assertEqual(result['complete_windows'], 120)
        self.assertEqual(result['control_window_net_xp'], 5000)
        self.assertEqual(result['persisted_net_xp'], 100)
        self.assertEqual(result['windows'][-1]['net_xp'], 500)
        self.assertEqual(result['peak_normalized_xp_per_minute'], 18000)
        self.assertFalse(result['publication_eligible'])

    def test_no_clock_stretch_or_old_policy_upgrade(self):
        scenario = self.read('scenario')
        for change in ({'wall_seconds': 300}, {'horizon_policy': adaptive.FINAL_SLOT_POLICY}):
            changed = copy.deepcopy(scenario); changed['adaptive_protocol'].update(change)
            self.f.manifest['scenario_fingerprint'] = self.f.save('scenario', changed)['sha256']
            with self.subTest(change=change), self.assertRaises(ValueError):
                windows.verify_bundle(self.f.manifest, self.f.root)

    def test_window_contract_must_match_exact_controller_horizon(self):
        scenario = self.read('scenario'); scenario['xp_window_protocol']['wall_seconds'] = 300
        self.f.manifest['scenario_fingerprint'] = self.f.save('scenario', scenario)['sha256']
        with self.assertRaisesRegex(EvidenceError, 'unfrozen_or_incomplete_control_window'):
            windows.verify_bundle(self.f.manifest, self.f.root)

    def test_unfinished_save_is_unknown_even_with_full_model_clock(self):
        self.f.manifest['window']['deadline_at_ms'] += 15000
        with self.assertRaisesRegex(EvidenceError, 'unfrozen_or_incomplete_control_window'):
            windows.verify_bundle(self.f.manifest, self.f.root)


if __name__ == '__main__': unittest.main()
