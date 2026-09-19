"""Offline Hero fixture expansion tests; no DB, game, API, or host operation."""
import copy
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))

from full_client_hero_fixture import replace, table, transform
from full_client_hero_toolkit import expected_keymap, expected_skills, toolkit


def fixture():
    rows = {
        'accounts': (['id','loggedin','password'],
                     [[2,0,"'__PRIVATE_PASSWORD_PLACEHOLDER__'"]]),
        'characters': (['id','accountid','job','level','map','hp','maxhp','mp',
                        'maxmp','exp','ap','sp'],
                       [[5,2,112,180,240040511,12000,12000,6000,6000,73250,0,
                         "'0,0,0,0,0,0,0,0,0,0'"]]),
        'skills': (['id','skillid','characterid','skilllevel','masterlevel','expiration'],
                   [[index+1, skill, 5, level,
                     level if skill//10000 == 112 else 0, -1]
                    for index, (skill, level) in enumerate(expected_skills(toolkit()))]),
        'keymap': (['id','characterid','key','type','action'],
                   [[1,5,29,5,52],[2,5,57,5,53]]
                   + [[index+3,5,key,kind,action]
                      for index,(key,kind,action) in enumerate(expected_keymap(toolkit()))]),
        'inventoryitems': (['inventoryitemid','characterid','itemid','inventorytype',
                            'position','quantity'],
                           [[1,5,1402037,-1,-11,1],[2,5,2000005,2,1,100]]),
    }
    text = '-- Synthetic private-shape fixture; never connected to a DB.\n'
    for name, (columns, values) in rows.items():
        text += 'CREATE TABLE `'+name+'` (\n' + ',\n'.join(
            '  `'+column+'` int' for column in columns) + '\n) ENGINE=InnoDB;\n'
        text += 'INSERT INTO `'+name+'` VALUES ' + ','.join(
            '('+','.join(map(str, row))+')' for row in values) + ';\n'
    return text.encode()


class HeroFixtureTests(unittest.TestCase):
    def test_already_expanded_baseline_is_byte_identical(self):
        original = fixture()
        transformed, expected = transform(original)
        self.assertEqual(transformed, original)
        self.assertEqual(expected['skills'], expected_skills(toolkit()))
        self.assertEqual(expected['selected_keymap'], expected_keymap(toolkit()))
        self.assertFalse(expected['equipment_replaced'])
        self.assertEqual(expected['runtime_mutations'], 0)

    def test_missing_rows_are_replaced_without_touching_private_or_fixture_state(self):
        original = fixture().decode()
        _, skills, _ = table(original, 'skills')
        _, keys, _ = table(original, 'keymap')
        original = replace(original, 'skills', skills[:-1])
        original = replace(original, 'keymap', [row for row in keys if row['key'] != '47'])
        transformed, _ = transform(original.encode())
        before, after = original, transformed.decode()
        for name in ('accounts','characters','inventoryitems'):
            self.assertEqual(table(before, name)[1], table(after, name)[1])
        self.assertEqual(sorted([[int(row['skillid']),int(row['skilllevel'])]
                                 for row in table(after,'skills')[1]]),
                         expected_skills(toolkit()))
        selected = {row[0] for row in expected_keymap(toolkit())}
        self.assertEqual(sorted([[int(row['key']),int(row['type']),int(row['action'])]
                                 for row in table(after,'keymap')[1]
                                 if int(row['key']) in selected]),
                         expected_keymap(toolkit()))

    def test_wrong_fixture_identity_or_weapon_fails_closed(self):
        original = fixture().decode()
        for name, change in (
            ('characters', lambda row: row.update(map='240050300')),
            ('inventoryitems', lambda row: row.update(itemid='1302000')),
            ('accounts', lambda row: row.update(loggedin='1')),
        ):
            changed = original
            _, rows, _ = table(changed, name)
            rows = copy.deepcopy(rows)
            target = rows[0]
            if name == 'inventoryitems':
                target = next(row for row in rows if row['position'] == '-11')
            change(target)
            changed = replace(changed, name, rows)
            with self.subTest(name=name), self.assertRaises(ValueError):
                transform(changed.encode())


if __name__ == '__main__':
    unittest.main()
