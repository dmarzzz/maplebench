"""Compile actual native SkillData route selection from an operator source tree.

No assets or full native client are needed. The build receipt pins the inspected
source tree; the fixture path is deliberately absent from ordinary CI.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class HeroNativeRouteTest(unittest.TestCase):
    def test_all_seventeen_declared_routes(self):
        source = os.environ.get('MAPLEBENCH_TEST_CLIENT_SOURCE')
        if not source:
            self.skipTest('Operator native source fixture not supplied')
        source = Path(source).resolve(strict=True)
        text = (source / 'Data/SkillData.cpp').read_text()
        start = text.index('    int32_t SkillData::flags_of(int32_t id) const')
        end = text.index('    bool SkillData::is_passive() const', start)
        exact_function = text[start:end]
        compiler = shutil.which(os.environ.get('CXX', 'c++'))
        self.assertIsNotNone(compiler, 'Source-route check requires a C++ compiler')
        # Expectations come from the ordinary Cosmic handlers, not this map:
        # seven physical attacks, nine self buffs/cures, one enemy debuff cast.
        expected = {
            1121008: 1, 1111002: 0, 1101004: 0, 1121000: 0,
            1121006: 1, 1111005: 1, 1111003: 1, 1121002: 0,
            1101006: 0, 1101007: 0, 1121010: 0, 1121011: 0,
            1111008: 1, 1111007: 0, 1001003: 0, 1001004: 1,
            1001005: 1,
        }
        checks = '\n'.join(
            f'if (data.flags_of({skill}) != {flags}) return {index};'
            for index, (skill, flags) in enumerate(expected.items(), 1))
        harness = '''#include <cstdint>
#include <unordered_map>
#include "Character/SkillId.h"
namespace jrc {
class SkillData { public:
    enum Flags {NONE=0,ATTACK=1,RANGED=2};
    int32_t flags_of(int32_t) const;
};
''' + exact_function + '''
}
int main() {jrc::SkillData data;
''' + checks + '\n}\n'
        with tempfile.TemporaryDirectory(prefix='maplebench-hero-routes-') as directory:
            root = Path(directory)
            (root/'routes.cpp').write_text(harness)
            subprocess.run([compiler, '-std=c++17', '-O0', '-Wall', '-Wextra',
                            '-Werror', '-I', str(source), str(root/'routes.cpp'),
                            '-o', str(root/'routes')], check=True,
                           capture_output=True, timeout=30)
            result = subprocess.run([str(root/'routes')], capture_output=True,
                                    timeout=5)
            failed = list(expected)[result.returncode-1] if 1 <= result.returncode <= 17 else None
            self.assertEqual(result.returncode, 0, f'Wrong native packet route for skill {failed}')


if __name__ == '__main__':
    unittest.main()
