import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from full_client_collect import parse_snapshot, save_snapshot, snapshot_sql, validate_toolkit_snapshot
from full_client_hero_toolkit import toolkit, expected_keymap, expected_skills


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

    def hero_raw(self):
        policy=toolkit()
        return '\n'.join(json.dumps(row) for row in [self.row,
            *sorted(self.keys+expected_keymap(policy)),
            *({'learned_skill':row} for row in expected_skills(policy))])

    def parse_hero(self,raw=None):
        return parse_snapshot(self.hero_raw() if raw is None else raw,run_id='attempt-hero',
            captured_at_ms=1000,character_id=7,account_id=3,skill_toolkit=toolkit())

    def test_optional_hero_snapshot_binds_seventeen_controls_and_twenty_five_learned_skills(self):
        result=self.parse_hero()
        self.assertEqual(result['learned_skills'],expected_skills(toolkit()))
        self.assertEqual(result['skill_toolkit_id'],toolkit()['id'])
        self.assertEqual(result['keymap'],sorted(self.keys+expected_keymap(toolkit())))
        self.assertEqual(len(result['learned_skills']),25)
        self.assertEqual(len(result['keymap']),20)
        self.assertNotIn('learned_skills',self.parse())
        self.assertNotIn('FROM skills',snapshot_sql(7,3))
        sql=snapshot_sql(7,3,skill_toolkit=toolkit())
        self.assertIn('READ ONLY',sql)
        self.assertIn('FROM skills',sql)
        self.assertIn('IN (29,30,31,32,33,34,35,39,44,45,46,47,48,49,50,51,52,53,57,85)',sql)
        self.assertEqual(sql.count('COMMIT;'),1)

    def test_hero_snapshot_rejects_missing_wrong_duplicate_or_misordered_skill_rows(self):
        raw=self.hero_raw();rows=raw.splitlines()
        for values in (rows[:-1],rows+[rows[-1]],rows[:-2]+[rows[-1],rows[-2]],
                       rows[:-1]+[json.dumps({'learned_skill':[1121008,29]})]):
            with self.subTest(values=values[-2:]),self.assertRaises(ValueError):
                self.parse_hero('\n'.join(values))
        for mutate in (lambda value:value['keymap'][1].__setitem__(1,4),
                       lambda value:value['keymap'].pop(1),
                       lambda value:value['learned_skills'][0].__setitem__(1,True),
                       lambda value:value['character'].update(job=111),
                       lambda value:value.update(skill_toolkit_id='unbound')):
            value=self.parse_hero();mutate(value)
            with self.assertRaises(ValueError):validate_toolkit_snapshot(value,toolkit())


if __name__ == '__main__': unittest.main()
