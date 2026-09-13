"""Compile actual native admission and buff methods around the Shadow Stars fix.

Player/Skill methods, skill classification, scalar loading, and ammunition
policy are production C++. Only storage and external I/O are inert. The two
skill-level inputs are inspected NX/XML scalar facts, not bundled game assets.
No server, model, native build, or benchmark qualification is exercised.
"""
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import test_client_fixture_attack_flags as flags
import test_client_spell_damage as spell

ROOT = Path(__file__).resolve().parents[1]

STORAGE = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <map>
#include <string>
#include <unordered_map>
#include "SkillId.h"
#include "AmmunitionPolicy.h"
namespace jrc {
namespace Weapon {enum Type {NONE, BOW, CROSSBOW, CLAW, GUN, SWORD, STAFF};}
namespace InventoryType {enum Id {USE, CASH};}
namespace Maplestat {enum Id {HP, MP};}
namespace Buffstat {enum Id {NONE, SHADOW_CLAW, SOULARROW, BOOSTER, LENGTH};}
struct Buff {
 Buffstat::Id stat=Buffstat::NONE;int16_t value=0;int32_t skillid=0,duration=0;
};
struct Job {bool allowed=true;bool can_use(int) const {return allowed;}};
struct Scalar {
 int value;bool present;
 int get_integer(int fallback) const {return present?value:fallback;}
 operator int32_t() const {return present?value:0;}
};
struct Node {
 std::map<std::string,int> values;
 Scalar operator[](const char* name) const {
  auto found=values.find(name);
  return {found==values.end()?0:found->second,found!=values.end()};
 }
};
struct SkillData {
 enum {NONE=0,ATTACK=1,RANGED=2};
 struct Stats {uint8_t bulletcount;int16_t bulletcost;int32_t hpcost,mpcost;};
 int id,flags;bool passive;
 static int fee_override;static int hp_cost;static Weapon::Type required;
 explicit SkillData(int n):id(n),flags(flags_of(n)),passive((n%10000)/1000==0) {}
 static SkillData get(int id){return SkillData(id);}
 static Stats load(const Node& sub);
 Stats get_stats(int level) const {
  // Scalar parity: Shadow Stars 4121006 level1/30, bulletConsume=200,
  // mpCon=15/25. The client counts 30 level records for its masterlevel;
  // the separate root masterLevel=10 is not the learned-level ceiling.
  if(id==4121006)return load({{{"bulletConsume",fee_override},
     {"mpCon",level==1?15:25},{"hpCon",hp_cost}}});
  return load({{{"bulletConsume",id==4121007?3:1}}});
 }
 int get_masterlevel() const {return 30;}
 Weapon::Type get_required_weapon() const {return required;}
 int32_t flags_of(int32_t) const;bool is_attack() const;
};
int SkillData::fee_override=200;
int SkillData::hp_cost=0;
Weapon::Type SkillData::required=Weapon::NONE;
struct SpecialMove {
 enum ForbidReason {FBR_NONE,FBR_OTHER,FBR_COOLDOWN,FBR_HPCOST,
                   FBR_MPCOST,FBR_WEAPONTYPE,FBR_BULLETCOST};
 virtual bool is_attack() const=0;virtual bool is_skill() const=0;
 virtual int32_t get_id() const=0;
 virtual ForbidReason can_use(int32_t,Weapon::Type,const Job&,uint16_t,
                             uint16_t,uint16_t) const=0;
 virtual ~SpecialMove()=default;
};
struct Skill:SpecialMove {
 int skillid;explicit Skill(int id):skillid(id){}
 bool is_attack() const override;bool is_skill() const override;
 int32_t get_id() const override;
 ForbidReason can_use(int32_t,Weapon::Type,const Job&,uint16_t,
                     uint16_t,uint16_t) const override;
};
struct Inventory {
 struct Item {int32_t id;int16_t count;};
 std::map<std::pair<InventoryType::Id,int16_t>,Item> items;
 uint16_t selected_count=0;uint8_t slotmax=24;
 uint8_t get_slotmax(InventoryType::Id) const {return slotmax;}
 int32_t get_item_id(InventoryType::Id type,int16_t slot) const {
  auto it=items.find({type,slot});return it==items.end()?0:it->second.id;
 }
 int16_t get_item_count(InventoryType::Id type,int16_t slot) const {
  auto it=items.find({type,slot});return it==items.end()?0:it->second.count;
 }
 uint16_t get_bulletcount() const {return selected_count;}
};
struct Skillbook {int level=30;int get_level(int) const {return level;}};
struct Stats {
 uint16_t hp=12000,mp=6000;Job job;
 const Job& get_job() const {return job;}
 uint16_t get_stat(Maplestat::Id stat) const {return stat==Maplestat::HP?hp:mp;}
};
struct Player {
 enum State {STAND,PRONE,LADDER,ROPE,DIED};State state=STAND;
 bool cooldown=false;Weapon::Type weapon=Weapon::CLAW;
 Inventory inventory;Skillbook skillbook;Stats stats;
 std::array<Buff,Buffstat::LENGTH> buffs{};
 Weapon::Type get_weapontype() const {return weapon;}
 bool has_cooldown(int) const {return cooldown;}
 bool is_dead() const;void give_buff(Buff);void cancel_buff(Buffstat::Id);
 bool has_buff(Buffstat::Id) const;
 SpecialMove::ForbidReason can_use(const SpecialMove&) const;
};
'''

CHECKS = r'''
}
int main(int argc,char** argv){using namespace jrc;
 assert(argc==2);const std::string test=argv[1];
 const auto none=SpecialMove::FBR_NONE,ammo=SpecialMove::FBR_BULLETCOST;
 Skill stars(4121006);Player p;
 if(test=="regression"){
  p.give_buff({Buffstat::SHADOW_CLAW,0,4121006,120000});
  assert(p.has_buff(Buffstat::SHADOW_CLAW)==bool(FIXED));
  assert(p.can_use(stars)==(FIXED?ammo:none));
  return 0;
 }
 assert(FIXED);
 if(test=="presence"){
  assert(!p.has_buff(Buffstat::SHADOW_CLAW));
  // This is the exact server payload shape: zero value, real skill identity.
  p.give_buff({Buffstat::SHADOW_CLAW,0,4121006,62000});
  assert(p.has_buff(Buffstat::SHADOW_CLAW));
  p.cancel_buff(Buffstat::SHADOW_CLAW);
  assert(!p.has_buff(Buffstat::SHADOW_CLAW));
  p.give_buff({Buffstat::SHADOW_CLAW,0,4121006,120000});
  assert(p.has_buff(Buffstat::SHADOW_CLAW));
  p.cancel_buff(Buffstat::SHADOW_CLAW);
  assert(!p.has_buff(Buffstat::SHADOW_CLAW));
  p.give_buff({Buffstat::SHADOW_CLAW,1,4121007,120000});
  assert(!p.has_buff(Buffstat::SHADOW_CLAW));
  p.buffs[Buffstat::SHADOW_CLAW]={Buffstat::BOOSTER,0,4121006,120000};
  assert(!p.has_buff(Buffstat::SHADOW_CLAW));
  p.give_buff({Buffstat::SOULARROW,0,3101004,120000});
  assert(!p.has_buff(Buffstat::SOULARROW));
  p.give_buff({Buffstat::SOULARROW,1,3101004,120000});
  assert(p.has_buff(Buffstat::SOULARROW));
 }
 else if(test=="levels"){
  for(int level:{1,30}){
   p.skillbook.level=level;const int mp=level==1?15:25;p.stats.mp=mp;
   const auto loaded=SkillData::get(4121006).get_stats(level);
   assert(loaded.bulletcost==200 && loaded.mpcost==mp);
   assert(p.can_use(stars)==ammo);
   p.inventory.items[{InventoryType::USE,1}]={2070000,199};
   assert(p.can_use(stars)==ammo);
   p.inventory.items[{InventoryType::USE,1}]={2070000,200};
   assert(p.can_use(stars)==none);
   p.stats.mp=mp-1;assert(p.can_use(stars)==SpecialMove::FBR_MPCOST);
   p.inventory.items.clear();
  }
  // It consumes the loaded value, not a duplicated 200 constant in admission.
  p.stats.mp=6000;SkillData::fee_override=250;
  p.inventory.items[{InventoryType::USE,1}]={2070006,249};
  assert(p.can_use(stars)==ammo);
  p.inventory.items[{InventoryType::USE,1}]={2070006,250};
  assert(p.can_use(stars)==none);
  for(int fee:{0,-1}){SkillData::fee_override=fee;assert(p.can_use(stars)==ammo);}
 }
 else if(test=="stacks"){
  // The authoritative cast pays from ONE stack; two short stacks do not add.
  p.inventory.items[{InventoryType::USE,1}]={2070000,100};
  p.inventory.items[{InventoryType::USE,2}]={2070006,100};
  assert(p.can_use(stars)==ammo);
  p.inventory.items[{InventoryType::USE,24}]={2070006,200};
  assert(p.can_use(stars)==none);
  p.inventory.items.erase({InventoryType::USE,24});
  // No virtual ammunition, wrong category, cash item, or outside-slot item.
  p.inventory.selected_count=30000;p.weapon=Weapon::BOW;
  p.give_buff({Buffstat::SOULARROW,1,3101004,120000});
  for(int id:{2000000,2060000,2061000,2330000,5021000,2080000}){
   p.inventory.items[{InventoryType::USE,3}]={id,30000};
   assert(p.can_use(stars)==ammo);
  }
  p.inventory.items[{InventoryType::CASH,4}]={2070000,30000};
  p.inventory.items[{InventoryType::USE,0}]={2070000,30000};
  p.inventory.items[{InventoryType::USE,25}]={2070000,30000};
  assert(p.can_use(stars)==ammo);
  for(int count:{0,-1}){
   p.inventory.items[{InventoryType::USE,3}]={2070000,int16_t(count)};
   assert(p.can_use(stars)==ammo);
  }
  // The buff's source has no weapon requirement; do not invent a claw gate.
  p.inventory.items[{InventoryType::USE,3}]={2070000,200};
  for(auto weapon:{Weapon::BOW,Weapon::CLAW,Weapon::SWORD,Weapon::STAFF}){
   p.weapon=weapon;assert(p.can_use(stars)==none);
  }
 }
 else if(test=="gates"){
  p.inventory.items[{InventoryType::USE,1}]={2070000,200};
  for(int level:{0,-1,31}){
   p.skillbook.level=level;assert(p.can_use(stars)==SpecialMove::FBR_OTHER);
  }
  p.skillbook.level=30;p.stats.job.allowed=false;
  assert(p.can_use(stars)==SpecialMove::FBR_OTHER);
  p.stats.job.allowed=true;SkillData::hp_cost=10;p.stats.hp=10;
  assert(p.can_use(stars)==SpecialMove::FBR_HPCOST);
  p.stats.hp=11;assert(p.can_use(stars)==none);
  SkillData::required=Weapon::BOW;
  assert(p.can_use(stars)==SpecialMove::FBR_WEAPONTYPE);
  SkillData::required=Weapon::NONE;p.cooldown=true;
  assert(p.can_use(stars)==SpecialMove::FBR_COOLDOWN);
  p.cooldown=false;
  for(auto state:{Player::PRONE,Player::DIED}){
   p.state=state;assert(p.can_use(stars)==SpecialMove::FBR_OTHER);
  }
  p.state=Player::STAND;assert(p.can_use(stars)==none);
 }
 else if(test=="server_owned"){
  p.inventory.items[{InventoryType::USE,1}]={2070000,400};
  assert(p.can_use(stars)==none && p.can_use(stars)==none);
  assert(p.inventory.get_item_count(InventoryType::USE,1)==400);
  assert(!p.has_buff(Buffstat::SHADOW_CLAW));
  // Ordinary inventory packets, represented by inert storage here, own fees.
  p.inventory.items[{InventoryType::USE,1}].count=200;
  p.give_buff({Buffstat::SHADOW_CLAW,0,4121006,120000});
  assert(p.can_use(stars)==none);
  assert(p.inventory.get_item_count(InventoryType::USE,1)==200);
  p.inventory.items[{InventoryType::USE,1}].count=0;
  assert(p.has_buff(Buffstat::SHADOW_CLAW) && p.can_use(stars)==ammo);
  p.cancel_buff(Buffstat::SHADOW_CLAW);
  assert(p.inventory.get_item_count(InventoryType::USE,1)==0);
 }
 else if(test=="projectiles"){
  Skill triple(4121007),booster(4101003),soul(3101004);
  assert(!stars.is_attack() && triple.is_attack());
  for(bool buff:{false,true}){
   if(buff)p.give_buff({Buffstat::SHADOW_CLAW,0,4121006,120000});
   else p.cancel_buff(Buffstat::SHADOW_CLAW);
   for(auto weapon:{Weapon::CLAW,Weapon::GUN}){
    p.weapon=weapon;
    for(int count:{0,2,3}){
     p.inventory.selected_count=count;
     assert(p.can_use(triple)==(count>=3?none:ammo));
    }
    p.inventory.selected_count=0;
    assert(p.can_use(booster)==none);
    assert(!has_ranged_projectile(false,false,p.has_buff(Buffstat::SOULARROW)));
    assert(projectile_visual(0,false,false,p.has_buff(Buffstat::SOULARROW))==0);
   }
  }
  p.weapon=Weapon::BOW;assert(p.can_use(soul)==none);
  assert(p.can_use(triple)==ammo);
  p.give_buff({Buffstat::SOULARROW,1,3101004,120000});
  assert(p.can_use(triple)==none);
  assert(has_ranged_projectile(false,true,p.has_buff(Buffstat::SOULARROW)));
  assert(projectile_visual(0,true,false,p.has_buff(Buffstat::SOULARROW))==2060000);
  assert(p.can_use(stars)==ammo); // Soul Arrow still cannot pay a real star fee.
 }
 else assert(false);
}
'''


class ShadowStarsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('c++')
        if not compiler:
            raise unittest.SkipTest('C++ compiler required')
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        tree = Path(cls.temp.name)
        for name, digest in spell.PINS.items():
            data = (spell.FIXTURE / name).read_bytes()
            assert hashlib.sha256(data).hexdigest() == digest
            dest = tree / 'src/client' / spell.PATHS[name]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        skill_data = (flags.FIXTURE / 'SkillData.cpp').read_bytes()
        assert hashlib.sha256(skill_data).hexdigest() == flags.PINS['SkillData.cpp']
        assert hashlib.sha256((flags.FIXTURE / 'SkillId.h').read_bytes()).hexdigest() == flags.PINS['SkillId.h']
        dest = tree / 'src/client/Data/SkillData.cpp'
        dest.parent.mkdir(parents=True)
        dest.write_bytes(skill_data)
        for name in ('0005-fixture-attack-flags.patch',
                     '0006-training-toolkit-attack-flags.patch',
                     '0008-spell-damage.patch', '0010-critical-passives.patch',
                     '0012-claw-skill-base.patch'):
            patch = ROOT / 'patches/full-client' / name
            if name.startswith('0010-'):
                # As in the critical pipeline harness, declarations/storage
                # replace Mob.h/CharStats.cpp. Apply every copied source hunk.
                selected = ''.join(block for block in re.split(
                    r'(?=^--- )', patch.read_text(), flags=re.M)
                    if any(block.startswith('--- a/src/client/' + path + '\n')
                           for path in spell.PATHS.values()))
                patch = tree / 'critical-copied-sources.patch'
                patch.write_text(selected)
            result = subprocess.run(['patch', '-p1', '--batch', '--fuzz=0', '-i',
                                     str(patch)], cwd=tree, capture_output=True,
                                    text=True, timeout=5)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
        data_source = dest.read_text()
        # Compile the exact native scalar loader statements with inert node I/O.
        start = data_source.index('uint8_t bulletcount =')
        end = data_source.index('float chance =', start)
        scalar_loader = ('SkillData::Stats SkillData::load(const Node& sub){\n'
                         + data_source[start:end]
                         + 'return {bulletcount,bulletcost,hpcost,mpcost};}\n')
        classification = '\n'.join(flags.method(data_source, signature) for signature in
                                     ('int32_t SkillData::flags_of',
                                      'bool SkillData::is_attack'))
        cls.binaries = []
        for fixed in (False, True):
            if fixed:
                subprocess.run(['patch', '-p1', '--batch', '--fuzz=0', '-i', str(ROOT /
                                'patches/full-client/0013-shadow-stars-cost-and-presence.patch')],
                               cwd=tree, check=True, capture_output=True, timeout=5)
            player = (tree / 'src/client/Character/Player.cpp').read_text()
            skill = (tree / 'src/client/Gameplay/Combat/Skill.cpp').read_text()
            methods = '\n'.join(flags.method(player, signature) for signature in
                                ('SpecialMove::ForbidReason Player::can_use',
                                 'bool Player::is_dead', 'void Player::give_buff',
                                 'void Player::cancel_buff', 'bool Player::has_buff'))
            methods += '\n' + '\n'.join(flags.method(skill, signature) for signature in
                                        ('SpecialMove::ForbidReason Skill::can_use',
                                         'bool Skill::is_attack', 'bool Skill::is_skill',
                                         'int32_t Skill::get_id'))
            source = tree / f'check-{int(fixed)}.cpp'
            source.write_text(STORAGE + scalar_loader + classification + methods + CHECKS)
            binary = source.with_suffix('')
            command = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                       f'-DFIXED={int(fixed)}', '-I', str(flags.FIXTURE), '-I',
                       str(ROOT / 'patches/full-client'), str(source), '-o', str(binary)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=20)
            if result.returncode:
                raise AssertionError(result.stderr)
            cls.binaries.append(binary)

    def run_case(self, case, fixed=True):
        result = subprocess.run([str(self.binaries[int(fixed)]), case],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_old_failure_and_corrected_admission(self):
        self.run_case('regression', fixed=False)
        self.run_case('regression')

    def test_zero_value_presence_and_authoritative_cancel(self):
        self.run_case('presence')

    def test_level_one_and_thirty_loaded_costs(self):
        self.run_case('levels')

    def test_single_star_stack_categories_and_equipped_weapon(self):
        self.run_case('stacks')

    def test_existing_level_job_hp_mp_weapon_cooldown_and_state_gates(self):
        self.run_case('gates')

    def test_admission_does_not_mutate_inventory_or_grant_buff(self):
        self.run_case('server_owned')

    def test_real_projectile_admission_and_soul_arrow_unchanged(self):
        self.run_case('projectiles')


if __name__ == '__main__':
    unittest.main()
