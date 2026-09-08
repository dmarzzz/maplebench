"""Keep the lightweight Java harness on the actual pinned native XP table."""
import hashlib,json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class NativeExperienceTableFixtureTests(unittest.TestCase):
    def test_fixture_is_exact_locked_upstream_source(self):
        self.assertEqual(json.loads((ROOT/'upstream.lock.json').read_text())['cosmic']['commit'],
                         'b01cf27833f568cde52a0a70a38532474eedd4d9')
        raw=(ROOT/'test/persistence/native-source/constants/game/ExpTable.java').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '4faa01f027a11773df0ac7421d59e1b793934282f98e837e06cb967c44629132')
