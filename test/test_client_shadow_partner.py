"""Compile native buff admission -> Combat -> Mob rolls -> actual AttackPacket.

Only asset/stat storage, movement/rendering and the socket are inert. This is
source validation, not qualification of a live class or official-client parity.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'test/fixtures/client-shadow-partner'
PATCH = ROOT / 'patches/full-client/0020-shadow-partner.patch'


def method(source, signature):
    start = source.index(signature)
    at = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[at] == '{') - (source[at] == '}')
        at += 1
    return source[start:at]


DECLARATIONS = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <string>
#include <vector>
#include "src/client/Gameplay/Combat/Attack.h"
#if FIXED
#include "src/client/Gameplay/Combat/ShadowPartnerPolicy.h"
#endif
namespace nl {
struct node {
 std::string path;
 node operator[](const std::string& s)const{return {path+"/"+s};}
 node operator[](const char* s)const{return (*this)[std::string(s)];}
 operator int32_t()const;
};
namespace nx {node skill{"skill"};}
}
std::map<std::string,int> assets;
nl::node::operator int32_t()const {auto i=assets.find(path);return i==assets.end()?0:i->second;}
namespace jrc {
namespace Weapon {enum Type{NONE,CLAW,BOW,CROSSBOW,GUN,SWORD,STAFF};}
namespace InventoryType {enum Id{NONE,USE,ETC,CASH};Id by_item_id(int id){return id/1000000==4?ETC:USE;}}
namespace Buffstat {enum Id{NONE,SHADOWPARTNER,SHADOW_CLAW,SOULARROW,LENGTH};}
struct Buff {Buffstat::Id stat=Buffstat::NONE;int16_t value=0;int32_t skillid=0;};
namespace Maplestat {enum Id{HP,MP};}
struct Job {bool allowed=true;bool can_use(int)const{return allowed;}};
struct Stats {Job job;int hp=12000,mp=6000;const Job& get_job()const{return job;}
 int get_stat(Maplestat::Id id)const{return id==Maplestat::HP?hp:mp;}};
struct Skillbook {std::map<int,int> levels{{4111002,30},{4121006,30},{4121007,30},{4001344,20},{4111005,30}};
 int get_level(int id)const{auto it=levels.find(id);return it==levels.end()?0:it->second;}};
struct Inventory {struct Item{int id,count;};std::map<std::pair<int,int>,Item> items;
 int get_slotmax(InventoryType::Id)const{return 24;}
 int get_item_id(InventoryType::Id t,int slot)const{auto i=items.find({t,slot});return i==items.end()?0:i->second.id;}
 int16_t get_item_count(InventoryType::Id t,int slot)const{auto i=items.find({t,slot});return i==items.end()?0:i->second.count;}
 uint16_t get_bulletcount()const{return get_item_count(InventoryType::USE,1);}};
uint16_t effective_ammunition(uint16_t count,bool bow,bool soul){return bow&&soul?65535:count;}
struct SkillData {
 struct Stats{int hpcost=0,mpcost=0,bulletcost=1;};int id;
 static SkillData get(int id){return {id};}int get_masterlevel()const{return 30;}
 Weapon::Type get_required_weapon()const{return Weapon::NONE;}
 Stats get_stats(int level)const{Stats s;if(id==4111002||id==4121006){auto d=nl::nx::skill[id==4111002?"411.img":"412.img"]["skill"][std::to_string(id)]["level"][std::to_string(level)];s.mpcost=d["mpCon"];s.bulletcost=d["bulletConsume"];}
 else s.bulletcost=id==4121007?3:id==4001344?2:1;return s;}
};
struct Player;
struct SpecialMove {
 enum ForbidReason{FBR_NONE,FBR_WEAPONTYPE,FBR_HPCOST,FBR_MPCOST,FBR_BULLETCOST,FBR_COOLDOWN,FBR_OTHER};
 int id;explicit SpecialMove(int id):id(id){};virtual ~SpecialMove()=default;
 bool is_attack()const{return id!=4111002&&id!=4121006;}bool is_skill()const{return id!=0;}
 int32_t get_id()const{return id;}
 virtual ForbidReason can_use(int32_t,Weapon::Type,const Job&,uint16_t,uint16_t,uint16_t)const=0;
 void apply_useeffects(Player&)const{};void apply_actions(Player&,Attack::Type)const{};
 void apply_stats(Player&,Attack& a)const{a.hitcount=id==4121007?3:id==4001344?2:1;a.mobcount=2;a.skill=id;}
};
struct Skill:SpecialMove{int skillid;Skill(int id):SpecialMove(id),skillid(id){}
 ForbidReason can_use(int32_t,Weapon::Type,const Job&,uint16_t,uint16_t,uint16_t)const override;};
struct RegularAttack:SpecialMove{RegularAttack():SpecialMove(0){}
 ForbidReason can_use(int32_t,Weapon::Type,const Job&,uint16_t,uint16_t,uint16_t)const override;};
struct Player {
 enum State{STAND,PRONE,LADDER,ROPE,DIED};State state=STAND;bool cooldown=false;
 Weapon::Type weapon=Weapon::CLAW;Inventory inventory;Stats stats;Skillbook skillbook;
 std::array<Buff,Buffstat::LENGTH> buffs{};
 Weapon::Type get_weapontype()const{return weapon;}bool has_cooldown(int)const{return cooldown;}
 int get_skilllevel(int id)const{return skillbook.get_level(id);}int get_oid()const{return 700;}
 const Skillbook& get_skills()const{return skillbook;}
 bool is_dead()const;void give_buff(Buff);void cancel_buff(Buffstat::Id);bool has_buff(Buffstat::Id)const;
 SpecialMove::ForbidReason can_use(const SpecialMove&)const;
#if FIXED
 int32_t shadow_partner_percent(bool)const;
#endif
 Attack prepare_attack(bool)const{Attack a;a.type=weapon==Weapon::CLAW||weapon==Weapon::BOW?Attack::RANGED:weapon==Weapon::STAFF?Attack::MAGIC:Attack::CLOSE;
 a.claw_projectile=weapon==Weapon::CLAW;a.mindamage=100;a.maxdamage=600;a.critical=.5;return a;}
 void set_afterimage(int){};
};
struct Rng {mutable int roll=0;mutable int chance=0;
 bool below(float f)const{if(f>=1)return true;return (++chance%2)==0;}
 double next_real(double,double)const{return (++roll)*100;}};
float spell_hit_chance(int,int,int,int){return 1;}
struct Mob {int level=1,avoid=0;bool awaitdeath=true;int updates=0;Rng randomizer;
 double calculate_mindamage(int,double x,bool)const{return x;}double calculate_maxdamage(int,double x,bool)const{return x;}
 float calculate_hitchance(int,int)const{return 1;}void update_movement(){++updates;}
 std::vector<std::pair<int32_t,bool>> calculate_damage(const Attack&);
 std::pair<int32_t,bool> next_damage(double,double,float,float,int32_t,int32_t)const;
};
struct Mobs {Mob mob;int targets=1;AttackResult send_attack(const Attack& a){AttackResult r(a);r.mobcount=targets;
 for(int i=0;i<targets;++i)r.damagelines[100+i]=mob.calculate_damage(a);return r;}};
struct OutPacket {enum Opcode{CLOSE_ATTACK=44,RANGED_ATTACK=45,MAGIC_ATTACK=46};std::vector<uint8_t> bytes;
 inline static std::vector<uint8_t> dispatched;
 OutPacket(int op){write_short(op);}void skip(size_t n){bytes.insert(bytes.end(),n,0);}
 void write_byte(int8_t x){bytes.push_back(x);}void write_short(int16_t x){write_byte(x);write_byte(x>>8);}
 void write_int(int32_t x){for(int i=0;i<4;++i)write_byte(static_cast<uint32_t>(x)>>(8*i));}
 void dispatch(){dispatched=bytes;}};
struct UseSkillPacket:OutPacket{UseSkillPacket(int,int):OutPacket(99){}};
struct Combat {Player& player;Mobs& mobs;AttackResult shown;
 void apply_move(const SpecialMove&);bool is_teleport_skill(int)const{return false;}bool apply_teleport(const SpecialMove&){return false;}
 void extract_effects(Player&,const SpecialMove&,const AttackResult& r){shown=r;}
 void apply_use_movement(const SpecialMove&){}void apply_result_movement(const SpecialMove&,const AttackResult&){}
};
'''

CHECKS = r'''
}
int main(int argc,char** argv){using namespace jrc;assert(argc==2);load_assets();std::string mode=argv[1];
 Player p;p.inventory.items[{InventoryType::USE,1}]={2070006,800};p.inventory.items[{InventoryType::ETC,1}]={4006001,2};
 p.give_buff({Buffstat::SHADOWPARTNER,80,4111002});Mobs mobs;Combat combat{p,mobs,{}};Skill triple(4121007),partner(4111002),stars(4121006);
 if(mode=="original"){combat.apply_move(triple);assert(combat.shown.hitcount==3);assert(combat.shown.damagelines.at(100).size()==3);
  p.inventory.items[{InventoryType::ETC,1}].count=0;assert(p.can_use(partner)==SpecialMove::FBR_NONE);return 0;}
#if FIXED
 if(mode=="native_packet"){
  for(int id:{0,4001344,4121007,4111005}){const int base=id==4121007?3:id==4001344?2:1;
   mobs.mob.randomizer={};mobs.mob.updates=0;Skill skill(id);RegularAttack regular;
   combat.apply_move(id?static_cast<const SpecialMove&>(skill):static_cast<const SpecialMove&>(regular));
   auto& r=combat.shown;assert(r.hitcount==2*base && r.damagelines.at(100).size()==size_t(2*base));
   assert(mobs.mob.updates==1 && mobs.mob.randomizer.roll==2*base);
   auto& bytes=OutPacket::dispatched;assert(bytes[0]==45 && bytes[3]==(0x10|2*base));
   assert(bytes.size()==size_t(30+18+2*base*4+4));
   for(int n=0;n<2*base;++n){int raw=0;for(int b=0;b<4;++b)raw|=bytes[48+n*4+b]<<(8*b);
    int expected=(n+1)*100;if(n>=base)expected=expected*(id?50:80)/100;
    assert(raw==expected && r.damagelines.at(100)[n].first==expected);
    assert(r.damagelines.at(100)[n].second==bool((n+1)%2==0));}
  }
 }
 else if(mode=="all_levels"){
  for(int level=1;level<=30;++level){p.skillbook.levels[4111002]=level;
   auto data=nl::nx::skill["411.img"]["skill"]["4111002"]["level"][std::to_string(level)];
   p.give_buff({Buffstat::SHADOWPARTNER,static_cast<int16_t>(int(data["x"])),4111002});
   assert(p.shadow_partner_percent(false)==int(data["x"]));assert(p.shadow_partner_percent(true)==int(data["y"]));
   mobs.mob.randomizer={};combat.apply_move(triple);assert(combat.shown.damagelines.at(100)[3].first==400*int(data["y"])/100);
  }
 }
 else if(mode=="buff_identity"){
  p.cancel_buff(Buffstat::SHADOWPARTNER);combat.apply_move(triple);assert(combat.shown.hitcount==3);
  for(Buff invalid:std::vector<Buff>{{Buffstat::SHADOWPARTNER,80,14111000},{Buffstat::SHADOWPARTNER,0,4111002}}){p.give_buff(invalid);assert(p.shadow_partner_percent(true)==0);}
  p.give_buff({Buffstat::SHADOWPARTNER,80,4111002});p.skillbook.levels[4111002]=0;assert(p.shadow_partner_percent(true)==0);
  p.skillbook.levels[4111002]=31;assert(p.shadow_partner_percent(true)==0);p.skillbook.levels[4111002]=30;
  p.give_buff({Buffstat::SHADOWPARTNER,20,4111002});assert(p.shadow_partner_percent(true)==0);
  p.give_buff({Buffstat::SHADOWPARTNER,80,4111002});
  for(auto weapon:{Weapon::BOW,Weapon::SWORD,Weapon::STAFF}){p.weapon=weapon;combat.apply_move(triple);assert(combat.shown.hitcount==3);}
 }
 else if(mode=="resource_admission"){
  p.inventory.items[{InventoryType::ETC,1}].count=0;assert(p.can_use(partner)==SpecialMove::FBR_OTHER);
  p.inventory.items[{InventoryType::CASH,1}]={4006001,99};assert(p.can_use(partner)==SpecialMove::FBR_OTHER);
  p.inventory.items[{InventoryType::ETC,1}].count=1;assert(p.can_use(partner)==SpecialMove::FBR_NONE);
  p.stats.mp=54;assert(p.can_use(partner)==SpecialMove::FBR_MPCOST);p.stats.mp=6000;
  p.inventory.items[{InventoryType::USE,1}].count=5;assert(p.can_use(triple)==SpecialMove::FBR_BULLETCOST);
  p.inventory.items[{InventoryType::USE,1}].count=6;assert(p.can_use(triple)==SpecialMove::FBR_NONE);
  p.give_buff({Buffstat::SHADOW_CLAW,0,4121006});p.inventory.items[{InventoryType::USE,1}].count=5;assert(p.can_use(triple)==SpecialMove::FBR_BULLETCOST);
  p.inventory.items[{InventoryType::USE,1}].count=199;assert(p.can_use(stars)==SpecialMove::FBR_BULLETCOST);
  p.inventory.items[{InventoryType::USE,2}]={2070000,1};assert(p.can_use(stars)==SpecialMove::FBR_BULLETCOST);
  p.inventory.items[{InventoryType::USE,1}].count=200;assert(p.can_use(stars)==SpecialMove::FBR_NONE);
  assert(p.inventory.get_bulletcount()==200 && p.inventory.get_item_count(InventoryType::ETC,1)==1);
  p.cancel_buff(Buffstat::SHADOWPARTNER);p.inventory.items[{InventoryType::USE,1}].count=3;assert(p.can_use(triple)==SpecialMove::FBR_NONE);
 }
 else if(mode=="lines_and_bounds"){
  Attack a;a.type=Attack::RANGED;a.hitcount=6;AttackResult r(a);r.damagelines[1]={{10,false},{11,true},{12,false},{0,false},{1,true},{999999,true}};
  r.damagelines[2]=r.damagelines[1];scale_shadow_partner(r,21);
  for(auto& target:r.damagelines){auto& d=target.second;assert(d[0].first==10 && d[1].first==11 && d[2].first==12);
   assert(d[3]==std::make_pair(0,false) && d[4]==std::make_pair(1,true) && d[5]==std::make_pair(209999,true));}
  auto original=r.damagelines;for(int bad:{0,-1,101}){scale_shadow_partner(r,bad);assert(r.damagelines==original);}
  for(int count:{0,1,3,15,16,255}){r.hitcount=count;scale_shadow_partner(r,50);assert(r.damagelines==original);}
  r.hitcount=6;r.type=Attack::MAGIC;scale_shadow_partner(r,50);assert(r.damagelines==original);
 }
 else if(mode=="native_critical"){
  Attack a;a.type=Attack::RANGED;a.hitcount=6;a.critical=.5;a.mindamage=100;a.maxdamage=600;
  a.weapon_damage_percent=150;a.critical_bonus_percent=100;
  AttackResult r(a);r.damagelines[1]=mobs.mob.calculate_damage(a);scale_shadow_partner(r,50);
  const std::vector<std::pair<int32_t,bool>> expected{{150,false},{500,true},{450,false},{500,true},{375,false},{750,true}};
  assert(r.damagelines.at(1)==expected && mobs.mob.randomizer.chance==6 && mobs.mob.randomizer.roll==6);
 }
 else assert(false);
#else
 assert(false);
#endif
 std::cout<<mode<<" passed\n";
}
'''


@unittest.skipUnless(shutil.which('c++') and shutil.which('patch'), 'C++ and patch required')
class ShadowPartnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.binaries = {}
        assert hashlib.sha256((FIXTURE / 'SHA256.json').read_bytes()).hexdigest() == 'aa462498d69fb1d0508ed8bb7eb94c6d6edfbe9ee4a26648014479a47328e79d'
        assert hashlib.sha256((FIXTURE / 'skill-scalars.json').read_bytes()).hexdigest() == '88f95038046cb1cfc450a84cf2c8298f8cec1762e273bf479fd2e0062c244ff5'
        for name, digest in json.loads((FIXTURE / 'SHA256.json').read_text()).items():
            assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == digest, name
        scalar = json.loads((FIXTURE / 'skill-scalars.json').read_text())
        assert scalar['all_levels_nx_xml_equal'] is True
        assert scalar['description_percent_parity_all_levels'] is True
        loads = ['void load_assets(){']
        for skill, levels in scalar['skills'].items():
            for level, fields in levels.items():
                for key, value in fields.items():
                    loads.append(f'assets["skill/{skill[:3]}.img/skill/{skill}/level/{level}/{key}"]={value};')
        loads.append('}')
        for fixed in (False, True):
            tree = Path(cls.temp.name) / str(fixed)
            source = tree / 'src/client'
            shutil.copytree(FIXTURE, source)
            if fixed:
                subprocess.run(['patch', '-p1', '--batch', '--fuzz=0', '-i', str(PATCH)],
                    cwd=tree, capture_output=True, check=True, timeout=5)
            template = source / 'Template/Rectangle.h'
            template.parent.mkdir()
            template.write_text('#pragma once\nnamespace jrc {template<class T>struct Point{};template<class T>struct Rectangle{};}\n')
            bodies = ''
            for file, signatures in {
                'Character/Player.cpp': ['    bool Player::is_dead()', '    void Player::give_buff(',
                    '    void Player::cancel_buff(', '    bool Player::has_buff(',
                    '    SpecialMove::ForbidReason Player::can_use('] +
                    (['    int32_t Player::shadow_partner_percent('] if fixed else []),
                'Gameplay/Combat/Skill.cpp': ['    SpecialMove::ForbidReason Skill::can_use('],
                'Gameplay/Combat/RegularAttack.cpp': ['    SpecialMove::ForbidReason RegularAttack::can_use('],
                'Gameplay/Combat/Combat.cpp': ['    void Combat::apply_move('],
                'Gameplay/MapleMap/Mob.cpp': ['    std::vector<std::pair<int32_t, bool>> Mob::calculate_damage(',
                    '    std::pair<int32_t, bool> Mob::next_damage('],
            }.items():
                text = (source / file).read_text()
                bodies += '\n'.join(method(text, sig) for sig in signatures) + '\n'
            packet = method((source / 'Net/Packets/AttackAndSkillPackets.h').read_text(), '    class AttackPacket') + ';\n'
            code = DECLARATIONS + packet + bodies + '}\n' + '\n'.join(loads) + '\nnamespace jrc {\n' + CHECKS
            (tree / 'test.cpp').write_text(code)
            binary = tree / 'partner'
            result = subprocess.run(['c++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror',
                '-DFIXED=' + str(int(fixed)), str(tree / 'test.cpp'), '-o', str(binary)],
                capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise AssertionError(result.stderr)
            cls.binaries[fixed] = binary

    def case(self, name, fixed=True):
        result = subprocess.run([str(self.binaries[fixed]), name], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_original_omits_partner_lines_and_local_rock_admission(self): self.case('original', False)
    def test_actual_combat_damage_and_packet_counts_and_bytes(self): self.case('native_packet')
    def test_all_30_inspected_levels_use_distinct_normal_and_skill_scalars(self): self.case('all_levels')
    def test_received_buff_identity_cancellation_and_unrelated_weapon_routes(self): self.case('buff_identity')
    def test_real_rock_and_star_admission_without_local_consumption(self): self.case('resource_admission')
    def test_second_half_only_misses_crit_flags_multiple_targets_and_bounds(self): self.case('lines_and_bounds')
    def test_native_critical_arithmetic_precedes_partner_scaling_without_reroll(self): self.case('native_critical')


if __name__ == '__main__':
    unittest.main()
