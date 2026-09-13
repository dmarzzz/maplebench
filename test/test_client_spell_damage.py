"""Compile actual Player/Skill/Mob methods before and after the spell repair.

Only data storage, graphics and RNG are inert. The attack struct, stat plumbing,
spell branch, defense, hit roll and emitted damage lines are production C++.
No game assets, server, API requests or synthetic benchmark result are used.
"""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_client_fixture_attack_flags import method

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'test/fixtures/client-magic-damage'
PINS = {
    'Attack.h': 'bc49385ca8dafb21008de975a26a0bea587ad2da8ffb8049f5d3f390bca11567',
    'Player.cpp': 'c00f250c959a0988870155cad4cbdc31592e15818bbf9efc091e6c6967765b01',
    'Skill.cpp': 'd2a66dcb19bb093e4159e8d1322f7e2bed5316b631b57a70dd8eb2fd1251ed14',
    'Mob.cpp': 'c2c152761ecbdc2e347b3074a07ec9f3ec59982aae669e17e5bf37ab9660f78a',
}
PATHS = {'Attack.h': 'Gameplay/Combat/Attack.h', 'Skill.cpp': 'Gameplay/Combat/Skill.cpp',
         'Player.cpp': 'Character/Player.cpp', 'Mob.cpp': 'Gameplay/MapleMap/Mob.cpp'}
GEOMETRY = r'''
#pragma once
namespace jrc {
template<class T> struct Point {};
template<class T> struct Rectangle { bool empty() const { return true; } };
}
'''
STUBS = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <map>
#include <string>
#include "src/client/Gameplay/Combat/Attack.h"
namespace nl { struct node {
 std::string path;
 node operator[](const std::string& key) const {return {path+"/"+key};}
 node operator[](const char* key) const {return {path+"/"+key};}
 operator int32_t() const {return path=="/221.img/skill/2210001/level/30/y"?140:100;}
}; namespace nx {node skill;}}
namespace jrc {
namespace Weapon {enum Type {BOW,CROSSBOW,CLAW,GUN,WAND,STAFF,SWORD};}
namespace Equipstat {enum Id {INT,LUK,MAGIC,ACC};}
namespace Maplestat {enum Id {LEVEL};}
namespace Buffstat {enum Id {SOULARROW};}
namespace SkillId {enum {THREE_SNAILS=1000};}
bool has_ranged_projectile(bool present,bool,bool) {return present;}
int projectile_visual(int id,bool,bool,bool) {return id;}
struct Stats {
 int intelligence=757,luck=123,magic=140,accuracy=1000;
 double physical=3000;
 int get_total(Equipstat::Id id) const {
  switch(id){case Equipstat::INT:return intelligence;case Equipstat::LUK:return luck;
   case Equipstat::MAGIC:return magic;case Equipstat::ACC:return accuracy;} return 0;
 }
 double get_mindamage() const {return physical;} double get_maxdamage() const {return physical;}
 float get_critical() const {return .05f;} float get_ignoredef() const {return 0;}
 int get_stat(Maplestat::Id) const {return 180;}
 Rectangle<int16_t> get_range() const {return {};}
};
struct Inventory {bool has_projectile() const {return true;}int get_bulletid() const {return 0;}};
struct Char {
 bool amplified=false;
 int get_skilllevel(int id) const {return id==2110001?0:id==2210001?(amplified?30:0):30;}
 struct Look {int get_stance() const {return 0;}};
 struct Afterimage {Rectangle<int16_t> get_range() const {return {};}};
 Look get_look() const {return {};}Afterimage get_afterimage() const {return {};}
};
struct Player:Char {
 enum {STAND,PRONE};int state=STAND;bool flip=false;
 Weapon::Type weapon=Weapon::STAFF;Stats stats;Inventory inventory;
 Weapon::Type get_weapontype() const {return weapon;}
 bool has_buff(Buffstat::Id) const {return false;}
 Point<int16_t> get_position() const {return {};}
 int get_integer_attackspeed() const {return 6;}
 Attack prepare_attack(bool) const;
};
struct SkillData {
 struct Stats {int fixdamage=0,matk=180,mastery=10;double damage=2;
  float critical=0,ignoredef=0,hrange=1;int mobcount=6,bulletcount=1,attackcount=1;
  Rectangle<int16_t> range;};
 int id; static SkillData get(int id){return {id};}
 Stats get_stats(int) const {Stats s;if(id==2221007)s.matk=570;
  if(id==1121008){s.matk=0;s.attackcount=2;}if(id==1000){s.matk=0;s.fixdamage=40;}return s;}
};
struct Skill {int skillid;bool projectile=false,overregular=false;
 void apply_stats(const Char&,Attack&) const;};
struct Randomizer {
 mutable float last_probability=0;
 bool below(float probability) const {last_probability=probability;return probability>=0.5f;}
 double next_real(double minimum,double maximum) const {return (minimum+maximum)/2;}
};
struct Mob {
 int16_t level=110;int avoid=37,mdef=700,wdef=800;bool awaitdeath=false;
 Randomizer randomizer;void update_movement() {}
 float calculate_hitchance(int16_t,int32_t) const;
 double calculate_mindamage(int16_t,double,bool) const;
 double calculate_maxdamage(int16_t,double,bool) const;
 std::vector<std::pair<int32_t,bool>> calculate_damage(const Attack&);
 std::pair<int32_t,bool> next_damage(double,double,float,float) const;
};
'''
CHECKS = r'''
}
int main() {using namespace jrc;
 Player player;Mob mob;
 auto chain=player.prepare_attack(true);Skill{2221006}.apply_stats(player,chain);
 auto blizzard=player.prepare_attack(true);Skill{2221007}.apply_stats(player,blizzard);
 #if FIXED
 assert(chain.totalmagic==897 && chain.intelligence==757 && chain.luck==123);
 // Independently evaluated fixed fixture: base MIN47/MAX61, then spell MAD180.
 assert(chain.mindamage==8460 && chain.maxdamage==10980);
 assert(blizzard.mindamage==26790 && blizzard.maxdamage==34770);
 assert(chain.critical==0 && chain.damagetype==Attack::DMG_MAGIC);
 auto lines=mob.calculate_damage(chain);assert(lines.size()==1 && lines[0].first==9335);
 player.amplified=true;
 auto amplified=player.prepare_attack(true);Skill{2221006}.apply_stats(player,amplified);
 assert(amplified.mindamage==11700 && amplified.maxdamage==15300);
 assert(mob.calculate_damage(amplified)[0].first==13115);
 // Equipment magic and INT must independently change generated attack damage.
 player.stats.magic+=50;auto equipment=player.prepare_attack(true);Skill{2221006}.apply_stats(player,equipment);
 assert(equipment.maxdamage>amplified.maxdamage);
 player.stats.intelligence+=50;auto intelligence=player.prepare_attack(true);Skill{2221006}.apply_stats(player,intelligence);
 assert(intelligence.maxdamage>equipment.maxdamage);
 // WATK-derived range is not an input to ordinary magic attacks.
 player.stats.physical=9000;auto physical=player.prepare_attack(true);Skill{2221006}.apply_stats(player,physical);
 assert(physical.maxdamage==intelligence.maxdamage);
 assert(spell_range(897,757,180,0,100).minimum<spell_range(897,757,180,10,100).minimum);
 assert(spell_range(897,757,180,0,100).maximum==10980);
 assert(spell_hit_chance(757,123,0,37)==1);
 assert(spell_hit_chance(0,0,0,37)==0.01f);
 assert(spell_hit_chance(0,0,0,0)==1);
 assert(spell_hit_chance(300,10,10,37)<spell_hit_chance(300,10,0,37));
 // The actual Mob branch uses INT/LUK magic accuracy, not physical accuracy.
 chain.accuracy=0;assert(mob.calculate_damage(chain)[0].first>0);
 chain.intelligence=0;chain.luck=0;assert(mob.calculate_damage(chain)[0].first==0);
 #else
 // Regression witness: different powers previously shared the same physical range.
 assert(chain.mindamage==3000 && chain.maxdamage==3000);
 assert(chain.maxdamage==blizzard.maxdamage);
 assert(chain.matk==180 && blizzard.matk==570);
 #endif
 // Ordinary weapon and fixed-damage branches retain their prior computation.
 player.weapon=Weapon::SWORD;player.stats.physical=3000;
 auto weapon=player.prepare_attack(true);Skill{1121008}.apply_stats(player,weapon);
 assert(weapon.type==Attack::CLOSE && weapon.damagetype==Attack::DMG_WEAPON);
 assert(weapon.mindamage==6000 && weapon.maxdamage==6000 && weapon.hitcount==2);
 auto weaponlines=mob.calculate_damage(weapon);assert(weaponlines.size()==2);
 assert(weaponlines[0].first==5560 && weaponlines[1].first==5560);
 auto fixed=player.prepare_attack(true);Skill{1000}.apply_stats(player,fixed);
 assert(fixed.damagetype==Attack::DMG_FIXED && mob.calculate_damage(fixed)[0].first==40);
 player.weapon=Weapon::STAFF;
 assert(player.prepare_attack(false).type==Attack::CLOSE);
 assert(player.prepare_attack(false).maxdamage==300);
}
'''


class SpellDamageTests(unittest.TestCase):
    def test_actual_damage_pipeline_and_regression_witness(self):
        compiler = shutil.which('c++')
        if not compiler:
            self.fail('C++ compiler is required to qualify the spell repair')
        for name, sha in PINS.items():
            self.assertEqual(hashlib.sha256((FIXTURE/name).read_bytes()).hexdigest(), sha)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for fixed in (False, True):
                tree = root / str(fixed)
                for name, path in PATHS.items():
                    dest = tree / 'src/client' / path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(FIXTURE/name, dest)
                if fixed:
                    subprocess.run(['patch', '-p1', '--batch', '--fuzz=0', '-i',
                        str(ROOT/'patches/full-client/0008-spell-damage.patch')],
                        cwd=tree, check=True, capture_output=True, timeout=5)
                geometry = tree/'src/client/Template/Rectangle.h'
                geometry.parent.mkdir(parents=True);geometry.write_text(GEOMETRY)
                declarations = STUBS
                if fixed:
                    declarations = '#include "src/client/Gameplay/Combat/SpellDamagePolicy.h"\n' + declarations
                signatures = {
                    'Player.cpp': ['Attack Player::prepare_attack'],
                    'Skill.cpp': ['void Skill::apply_stats'],
                    'Mob.cpp': ['float Mob::calculate_hitchance', 'double Mob::calculate_mindamage',
                        'double Mob::calculate_maxdamage', 'std::vector<std::pair<int32_t, bool>> Mob::calculate_damage',
                        'std::pair<int32_t, bool> Mob::next_damage'],
                }
                methods = '\n'.join(method((tree/'src/client'/PATHS[name]).read_text(), sig)
                                    for name, sigs in signatures.items() for sig in sigs)
                (tree/'test.cpp').write_text(declarations + methods + CHECKS)
                built = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-DFIXED='+str(int(fixed)), str(tree/'test.cpp'), '-o', str(tree/'test')],
                    capture_output=True, text=True, timeout=20)
                self.assertEqual(built.returncode, 0, built.stderr)
                executed = subprocess.run([str(tree/'test')], capture_output=True, text=True, timeout=5)
                self.assertEqual(executed.returncode, 0, executed.stderr)


if __name__ == '__main__':
    unittest.main()
