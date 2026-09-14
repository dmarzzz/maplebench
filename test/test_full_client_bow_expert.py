"""Compile production patch bodies with inert stat/NX storage (no game assets).

Values are pinned Skill.wz 3120005 level30 (mastery16,x10) and its
String.wz description: bow-only mastery90%, WATK+10. Ordinary mastery
uses mastery10,x20 => mastery60%, ACC+20. This is not live qualification.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'patches/full-client/0009-bow-expert.patch'


class BowExpertTest(unittest.TestCase):
    def test_compiled_production_effects_and_both_passive_orders(self):
        compiler = shutil.which('c++')
        if not compiler:
            self.skipTest('C++ compiler required')
        # Compile exactly the postimage C++ statements, not Python replicas.
        lines = PATCH.read_text().splitlines()
        post = '\n'.join(line[1:] for line in lines
                         if line.startswith((' ', '+')) and not line.startswith('+++'))
        expert = re.search(r'class BowExpertBuff final.*?\n    };', post, re.S).group()
        ordinary = re.search(r'float mastery =.*?stats.add_value\(Equipstat::ACC, level\["x"\]\);', post, re.S).group()
        registration = re.search(r'buffs\[3120005\] = .*?;', post).group()
        cpp = r'''
#include <cassert>
#include <cmath>
#include <map>
#include <memory>
#include <string>
#include <initializer_list>
namespace Weapon { enum Type { BOW, CROSSBOW, CLAW, SWORD }; }
namespace Equipstat { enum Id { WATK, ACC }; }
namespace nl { struct node { int mastery, x;
 int operator[](const char* key) const { return std::string(key)=="mastery"?mastery:x; } }; }
struct CharStats {
 Weapon::Type weapon; float mastery=0.1f; int watk=100, accuracy=0;
 Weapon::Type get_weapontype() const { return weapon; }
 float get_mastery() const { return mastery; }
 void set_mastery(float value) { mastery=value; }
 void add_value(Equipstat::Id id,int value) { (id==Equipstat::WATK?watk:accuracy)+=value; }
};
struct PassiveBuff { virtual ~PassiveBuff()=default;
 virtual bool is_applicable(CharStats&,nl::node) const=0;
 virtual void apply_to(CharStats&,nl::node) const=0; };
''' + expert + '\nvoid ordinary(CharStats& stats,nl::node level) {\n' + ordinary + r'''
}
int main() {
 std::map<int,std::unique_ptr<PassiveBuff>> buffs;
''' + registration + r'''
 auto& expert=*buffs.at(3120005);
 for(auto weapon:{Weapon::BOW,Weapon::CROSSBOW,Weapon::CLAW,Weapon::SWORD}) {
  CharStats stats{weapon};
  assert(expert.is_applicable(stats,{16,10})==(weapon==Weapon::BOW));
  if(expert.is_applicable(stats,{16,10})) expert.apply_to(stats,{16,10});
  assert(stats.watk==(weapon==Weapon::BOW?110:100));
  assert(stats.accuracy==0);
 }
 for(bool expert_first:{false,true}) {
  CharStats stats{Weapon::BOW};
  if(expert_first) expert.apply_to(stats,{16,10});
  ordinary(stats,{10,20});
  if(!expert_first) expert.apply_to(stats,{16,10});
  assert(std::abs(stats.mastery-0.9f)<0.00001f);
  assert(stats.watk==110 && stats.accuracy==20);
 }
 for(auto weapon:{Weapon::CROSSBOW,Weapon::CLAW,Weapon::SWORD}) {
  CharStats stats{weapon};ordinary(stats,{10,20});
  assert(std::abs(stats.mastery-0.6f)<0.00001f);
  assert(stats.watk==100 && stats.accuracy==20);
 }
 // Fresh stat rebuild removes passive effects; no persistent WATK stacking.
 CharStats rebuilt{Weapon::BOW};ordinary(rebuilt,{1,1});
 assert(std::abs(rebuilt.mastery-0.15f)<0.00001f);
 assert(rebuilt.watk==100 && rebuilt.accuracy==1);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            (p/'test.cpp').write_text(cpp)
            subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            str(p/'test.cpp'), '-o', str(p/'test')],
                           check=True, capture_output=True, timeout=20)
            subprocess.run([str(p/'test')], check=True, capture_output=True, timeout=5)
