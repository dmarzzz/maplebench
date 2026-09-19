import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'scripts', 'knowledge_pack.py')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import knowledge_pack  # noqa: E402
import full_client_skill_qualification as qualification  # noqa: E402


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    return path


class KnowledgePackTest(unittest.TestCase):
    def test_manifest_binds_sorted_paths_and_contents(self):
        with tempfile.TemporaryDirectory() as root:
            pack = os.path.join(root, 'fixture')
            write(pack, 'b.md', 'second\n')
            write(pack, 'a.md', 'first\n')
            manifest = knowledge_pack.build(pack)
            self.assertEqual(manifest['schema_version'], 1)
            self.assertEqual(manifest['pack_id'], 'fixture')
            self.assertEqual(manifest['file_count'], 2)
            self.assertEqual([entry['path'] for entry in manifest['files']], ['a.md', 'b.md'])
            self.assertEqual(manifest['total_bytes'], len('first\n') + len('second\n'))
            self.assertEqual(len(manifest['pack_sha256']), 64)

    def test_rename_changes_the_pack_hash(self):
        """Path is bound into the hash, so moving content is a different pack."""
        with tempfile.TemporaryDirectory() as root:
            first = os.path.join(root, 'p1')
            write(first, 'skills.md', 'body\n')
            second = os.path.join(root, 'p1-renamed', 'p1')
            write(second, 'monsters.md', 'body\n')
            self.assertNotEqual(knowledge_pack.build(first)['pack_sha256'],
                                knowledge_pack.build(second)['pack_sha256'])

    def test_content_change_changes_the_pack_hash(self):
        with tempfile.TemporaryDirectory() as root:
            pack = os.path.join(root, 'fixture')
            write(pack, 'a.md', 'before\n')
            before = knowledge_pack.build(pack)['pack_sha256']
            write(pack, 'a.md', 'after\n')
            self.assertNotEqual(before, knowledge_pack.build(pack)['pack_sha256'])

    def test_nested_paths_are_recorded_with_forward_slashes(self):
        with tempfile.TemporaryDirectory() as root:
            pack = os.path.join(root, 'fixture')
            write(pack, os.path.join('deep', 'inner.md'), 'nested\n')
            manifest = knowledge_pack.build(pack)
            self.assertEqual([entry['path'] for entry in manifest['files']], ['deep/inner.md'])

    def test_empty_unexpected_suffix_and_symlink_packs_are_refused(self):
        with tempfile.TemporaryDirectory() as root:
            empty = os.path.join(root, 'empty')
            os.makedirs(empty)
            with self.assertRaises(knowledge_pack.PackError):
                knowledge_pack.build(empty)

            binary = os.path.join(root, 'binary')
            write(binary, 'notes.txt', 'plain\n')
            with self.assertRaises(knowledge_pack.PackError):
                knowledge_pack.build(binary)

            linked = os.path.join(root, 'linked')
            write(linked, 'real.md', 'real\n')
            os.symlink(os.path.join(linked, 'real.md'), os.path.join(linked, 'alias.md'))
            with self.assertRaises(knowledge_pack.PackError):
                knowledge_pack.build(linked)

            linked_dir = os.path.join(root, 'linked-dir')
            write(linked_dir, 'real/a.md', 'real\n')
            os.symlink(os.path.join(linked_dir, 'real'), os.path.join(linked_dir, 'alias'))
            with self.assertRaises(knowledge_pack.PackError):
                knowledge_pack.build(linked_dir)

            missing = os.path.join(root, 'absent')
            with self.assertRaises(knowledge_pack.PackError):
                knowledge_pack.build(missing)

    def test_dotfiles_are_excluded(self):
        with tempfile.TemporaryDirectory() as root:
            pack = os.path.join(root, 'fixture')
            write(pack, 'a.md', 'kept\n')
            write(pack, '.hidden.md', 'ignored\n')
            manifest = knowledge_pack.build(pack)
            self.assertEqual([entry['path'] for entry in manifest['files']], ['a.md'])

    def test_oversized_file_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            pack = os.path.join(root, 'fixture')
            write(pack, 'big.md', 'x' * (knowledge_pack.MAX_FILE_BYTES + 1))
            with self.assertRaises(knowledge_pack.PackError):
                knowledge_pack.build(pack)

    def test_cli_prints_manifest_and_uses_documented_exit_codes(self):
        with tempfile.TemporaryDirectory() as root:
            pack = os.path.join(root, 'fixture')
            write(pack, 'a.md', 'body\n')

            ok = subprocess.run([sys.executable, SCRIPT, pack], capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(json.loads(ok.stdout)['pack_id'], 'fixture')

            invalid = os.path.join(root, 'invalid')
            write(invalid, 'a.txt', 'body\n')
            self.assertEqual(
                subprocess.run([sys.executable, SCRIPT, invalid], capture_output=True).returncode, 1)
            self.assertEqual(
                subprocess.run([sys.executable, SCRIPT], capture_output=True).returncode, 2)

    def test_committed_hero_cave_pack_is_hashable(self):
        """The shipped pack must stay a valid, hashable frozen input."""
        pack = os.path.join(ROOT, 'knowledge', 'hero-cave')
        manifest = knowledge_pack.build(pack)
        self.assertEqual(manifest['pack_id'], 'hero-cave')
        self.assertIn('README.md', [entry['path'] for entry in manifest['files']])
        self.assertEqual(len(manifest['pack_sha256']), 64)

    def test_frozen_reference_renders_exact_files_and_refuses_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            pack = os.path.join(root, 'fixture')
            write(pack, 'guide.md', 'guide\n')
            write(pack, 'plan.json', '{"status":"planned"}\n')
            reference = knowledge_pack.build(pack)
            rendered = knowledge_pack.prompt_text(pack, reference)
            self.assertIn('--- BEGIN guide.md ---', rendered)
            self.assertIn('--- BEGIN plan.json ---', rendered)
            write(pack, 'guide.md', 'changed\n')
            with self.assertRaises(knowledge_pack.PackError) as caught:
                knowledge_pack.prompt_text(pack, reference)
            self.assertEqual(str(caught.exception), 'pack_manifest_mismatch')

    def test_manifest_validation_rejects_unbound_or_unsafe_entries(self):
        with tempfile.TemporaryDirectory() as root:
            pack = os.path.join(root, 'fixture')
            write(pack, 'guide.md', 'guide\n')
            manifest = knowledge_pack.build(pack)
            knowledge_pack.validate_manifest(manifest)
            manifest['files'][0]['path'] = '../guide.md'
            with self.assertRaises(knowledge_pack.PackError):
                knowledge_pack.validate_manifest(manifest)

    def test_committed_v1_pack_is_scoped_and_all_release_checks_are_planned(self):
        pack = os.path.join(ROOT, 'knowledge', 'hero-180-map-240040511-v1')
        manifest = knowledge_pack.build(pack)
        self.assertEqual(manifest['pack_id'], 'hero-180-map-240040511-v1')
        plan = qualification.load(os.path.join(pack, 'skill-qualification.json'))
        self.assertEqual(plan['fixture']['expected_map_id'], 240040511)
        self.assertTrue(all(row['release_status'] == 'planned' for row in plan['controls']))
        self.assertIsNone(plan['native_release_result'])

    def test_qualification_plan_cannot_invent_a_successful_cast(self):
        path = os.path.join(ROOT, 'knowledge', 'hero-180-map-240040511-v1',
                            'skill-qualification.json')
        with open(path, encoding='utf-8') as handle:
            plan = json.load(handle)
        plan['controls'][6]['release_status'] = 'native_accepted'
        plan['native_release_result'] = {'successful_cast': True}
        with self.assertRaises(qualification.QualificationError):
            qualification.validate(plan)

    def test_expanded_hero_toolkit_is_exact_and_keeps_exclusions_visible(self):
        kit = qualification.hero_toolkit.toolkit()
        self.assertEqual([(row['slot'], row['name'], row['skill_id'], row['level'])
                          for row in kit['skills']], [
            ('PRIMARY_SKILL','Brandish',1121008,30),
            ('SECONDARY_SKILL','Combo Attack',1111002,30),
            ('BUFF_1','Sword Booster',1101004,20),
            ('BUFF_2','Maple Warrior',1121000,20),
            ('SKILL_5','Rush',1121006,30),
            ('SKILL_6','Sword Coma',1111005,30),
            ('SKILL_7','Sword Panic',1111003,30),
            ('SKILL_8','Power Stance',1121002,30),
            ('SKILL_9','Rage',1101006,20),
            ('SKILL_10','Power Guard',1101007,30),
            ('SKILL_11','Enrage',1121010,8),
            ('SKILL_12',"Hero's Will",1121011,5),
            ('SKILL_13','Shout',1111008,30),
            ('SKILL_14','Armor Crash',1111007,20),
            ('SKILL_15','Iron Body',1001003,6),
            ('SKILL_16','Power Strike',1001004,20),
            ('SKILL_17','Slash Blast',1001005,20)])
        self.assertEqual([row['name'] for row in kit['passives']],
                         ['Sword Mastery','Advanced Combo','Achilles',
                          'Final Attack: Sword','Improved HP Recovery',
                          'Improved Max HP Increase','Improved MP Recovery',
                          'Axe Mastery'])
        self.assertTrue(any('Monster Magnet' in item for item in kit['unsupported']))
        self.assertTrue(any('Guardian' in item for item in kit['unsupported']))
        self.assertEqual(qualification.hero_toolkit.expected_keymap(kit), [
            [30,1,1121008],[31,1,1111002],[32,1,1101004],[33,1,1121000],
            [34,1,1121006],[35,1,1111005],[39,1,1001005],
            [44,1,1111003],[45,1,1121002],
            [46,1,1101006],[47,1,1101007],[48,1,1121010],[49,1,1121011],
            [50,1,1111008],[51,1,1111007],[52,1,1001003],[53,1,1001004]])
        self.assertEqual(len(qualification.hero_toolkit.expected_skills(kit)), 25)
        altered = json.loads(json.dumps(kit))
        altered['skills'][5]['release_qualification'] = 'native_accepted'
        with self.assertRaises(ValueError):
            qualification.hero_toolkit.validate_toolkit(altered)


if __name__ == '__main__':
    unittest.main()
