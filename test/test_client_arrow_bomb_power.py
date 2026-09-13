"""Compile the actual skill-loader expression, with an inert numeric NX node."""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ArrowBombPowerTest(unittest.TestCase):
    def test_pinned_missing_damage_field_and_unrelated_skill_defaults(self):
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler, 'C++ compiler required')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root/'src/client/Data/SkillData.cpp'
            target.parent.mkdir(parents=True)
            shutil.copyfile(ROOT/'test/fixtures/client-attack-flags/SkillData.cpp', target)
            for patch in ('0005-fixture-attack-flags.patch', '0006-training-toolkit-attack-flags.patch',
                          '0011-arrow-bomb-power.patch'):
                subprocess.run(['patch', '-p1', '--batch', '--fuzz=0', '-i',
                    str(ROOT/'patches/full-client'/patch)], cwd=root, check=True,
                    capture_output=True, timeout=5)
            expression = re.search(r'float damage = static_cast<float>.*?;', target.read_text(), re.S).group()
            code = r'''
#include <cassert>
#include <cmath>
#include <map>
#include <string>
struct Node {
 bool present=false;double value=0;
 double get_real(double fallback=0)const{return present?value:fallback;}
};
float read(int id,std::map<std::string,Node> sub){EXPRESSION return damage;}
int main(){
 // Exact native Arrow Bomb level30 fields: x130; damage absent.
 assert(std::abs(read(3101005,{{"x",{true,130}}})-1.3f)<1e-6);
 assert(read(3101005,{{"damage",{true,160}},{"x",{true,130}}})==1.6f);
 assert(read(3101005,{{"damage",{true,0}},{"x",{true,130}}})==0);
 assert(read(3101005,{})==0);
 // Buff x, another attack's x, and unknown skills do not gain invented damage.
 for(int id:{1111002,3121002,2001002,3111003,9999999}){
   assert(read(id,{{"x",{true,130}}})==0);
   assert(read(id,{{"damage",{true,260}},{"x",{true,130}}})==2.6f);
 }
}
'''.replace('EXPRESSION', expression)
            (root/'test.cpp').write_text(code)
            built = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                str(root/'test.cpp'), '-o', str(root/'test')], capture_output=True, text=True, timeout=20)
            self.assertEqual(built.returncode, 0, built.stderr)
            subprocess.run([str(root/'test')], check=True, capture_output=True, timeout=5)
