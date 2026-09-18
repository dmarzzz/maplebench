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


if __name__ == '__main__':
    unittest.main()
