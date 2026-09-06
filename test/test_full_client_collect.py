import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from full_client_collect import parse_snapshot, save_snapshot, snapshot_sql


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.character = dict(character_id=7, account_id=3, level=180, exp=100, hp=1000,
                              mp=300, max_hp=1000, max_mp=500, map_id=240040511, spawn_point=0, job=112)
        self.row = {'character': self.character, 'account_logged_in': 0}
        self.keys = [[29, 5, 52], [57, 5, 53], [85, 5, 52]]

    def parse(self):
        return parse_snapshot('\n'.join(json.dumps(v) for v in [self.row, *self.keys]),
                              run_id='attempt-1', captured_at_ms=1000, character_id=7, account_id=3)

    def test_exact_offline_snapshot_and_gameplay_bindings(self):
        result = self.parse()
        self.assertEqual(result['character'], self.character)
        self.assertEqual(result['keymap'], self.keys)
        self.assertNotIn('name', json.dumps(result))

    def test_online_or_wrong_identity_rejected(self):
        self.row['account_logged_in'] = 1
        with self.assertRaises(ValueError): self.parse()
        self.row['account_logged_in'] = 0
        self.character['account_id'] = 4
        with self.assertRaises(ValueError): self.parse()

    def test_original_menu_type_regression_and_duplicate_key_rejected(self):
        self.keys[1][1] = 4
        with self.assertRaisesRegex(ValueError, 'keymap'): self.parse()
        self.keys[1][1] = 5
        self.keys.append([57, 5, 53])
        with self.assertRaisesRegex(ValueError, 'keymap'): self.parse()

    def test_sql_is_read_only_and_identity_not_interpolatable(self):
        sql = snapshot_sql(7, 3)
        self.assertIn('READ ONLY', sql)
        self.assertNotIn('UPDATE', sql)
        for value in ['7 OR 1=1', True, -1]:
            with self.assertRaises(ValueError): snapshot_sql(value, 3)

    def test_artifact_create_once_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'initial.json'
            digest = save_snapshot(path, self.parse())
            self.assertEqual(len(digest), 64)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError): save_snapshot(path, self.parse())


if __name__ == '__main__': unittest.main()
