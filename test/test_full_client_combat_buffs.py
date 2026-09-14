"""Compile pinned production buff reception -> Player -> Skill -> Mob methods.

Numeric NX data, stat storage, UI and RNG are inert; production method bodies,
Buff/Attack types and EnumMap storage are retained. No runtime/API or game assets.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_client_spell_damage as spell
import test_full_client_critical_passives as critical
from test_client_fixture_attack_flags import method

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'test/fixtures/client-combat-buffs'
PATCH = ROOT / 'patches/full-client/0017-combat-buff-semantics.patch'
PINS_SHA = '58775fd73e5c64aca496b2e901aefd2b4eb4865d507e4878c09fe4964234c01f'


def replace(text, old, new):
    if text.count(old) != 1:
        raise AssertionError('fixture declaration changed: ' + old[:100])
    return text.replace(old, new)


def declarations(fixed):
    s = critical.declarations(True, '(void)id;float damage = static_cast<float>(sub["x"].get_real(100)) / 100;')
    s = replace(s, '#include "src/client/Gameplay/Combat/SpellDamagePolicy.h"',
                '#include "src/client/Gameplay/Combat/SpellDamagePolicy.h"\n'
                '#include "src/client/Character/Buff.h"\n'
                '#include "src/client/Character/Inventory/Weapon.h"\n'
                '#include "src/client/Template/EnumMap.h"\n'
                '#include <cstring>\n#include <memory>\n')
    if fixed:
        s = '#include "src/client/Gameplay/Combat/CombatBuffPolicy.h"\n' + s
    s = replace(s, 'namespace Weapon {enum Type {BOW,CROSSBOW,CLAW,GUN,WAND,STAFF,SWORD};}', '')
    s = replace(s, 'namespace Buffstat {enum Id {SOULARROW};}', '')
    s = replace(s, 'namespace Maplestat {enum Id {LEVEL};}', 'namespace Maplestat {enum Id {LEVEL,HP,MP};}')
    s = replace(s, 'struct Stats {\n int intelligence', 'struct Job {};\nstruct Stats {Job job;const Job& get_job()const{return job;}\n int intelligence')
    s = replace(s, 'struct Inventory {bool present=true;',
        'namespace InventoryType {enum Id {USE};}\nstruct Inventory {\n'
        'int get_slotmax(InventoryType::Id)const{return 0;}\n'
        'int get_item_id(InventoryType::Id,int)const{return 0;}\n'
        'int get_item_count(InventoryType::Id,int)const{return 0;}\n'
        'int get_bulletcount()const{return 100;}bool present=true;')
    s = replace(s, 'struct Player:Char {', '''struct SpecialMove {
 enum ForbidReason {FBR_NONE,FBR_WEAPONTYPE,FBR_HPCOST,FBR_MPCOST,FBR_BULLETCOST,FBR_COOLDOWN,FBR_OTHER};
 int id; mutable int fallback_calls=0;
 bool is_skill()const{return id!=0;} bool is_attack()const{return true;}
 int get_id()const{return id;}
 ForbidReason can_use(int,Weapon::Type,const Job&,uint16_t,uint16_t,uint16_t)const{
  ++fallback_calls;return FBR_NONE;}
};
struct Skillbook {int get_level(int)const{return 30;}};
int effective_ammunition(int count,bool,bool){return count;}
struct Player:Char {Skillbook skillbook;EnumMap<Buffstat::Id,Buff> buffs;
 bool dead=false,cooldown=false; bool is_dead()const{return dead;}
 bool has_cooldown(int)const{return cooldown;}
 SpecialMove::ForbidReason can_use(const SpecialMove&)const;
 void give_buff(Buff);void cancel_buff(Buffstat::Id);
''')
    s = replace(s, 'enum {STAND,PRONE};', 'enum {STAND,PRONE,LADDER,ROPE};')
    s = replace(s, ' bool has_buff(Buffstat::Id) const {return false;}', ' bool has_buff(Buffstat::Id) const;')
    s = replace(s, ' if(id==3000001 || id==4100001)', ' if(id==3000001 || id==4100001 || id==1111002 || id==1120003)')
    s = replace(s, '  if(id==1121008)s.damage=2.6f;', '''  if(id==1111003 || id==1111004){s.matk=0;s.damage=3.5f;}
  if(id==1111005 || id==1111006){s.matk=0;s.damage=2.0f;}
  if(id==1121008)s.damage=2.6f;''')
    # Preserve the actual NX lookup expressions in Player and Skill. The store
    # supplies independently measured scalar examples, not game files.
    start=s.index('namespace nl { struct node {')
    end=s.index('namespace jrc {', start)
    s=s[:start]+'''namespace nl {
 std::map<std::string,int> scalars;
 struct node {
  std::string path;
  node operator[](const std::string& key)const{return {path+"/"+key};}
  node operator[](const char* key)const{return {path+"/"+key};}
  operator int32_t()const{auto it=scalars.find(path);return it==scalars.end()?0:it->second;}
 };
 namespace nx {node skill;}
}
'''+s[end:]
    if fixed:
        s=replace(s,'next_damage(double,double,float,float,int32_t,int32_t) const;',
                  'next_damage(double,double,float,float,int32_t,int32_t,double) const;')
    # Actual packet payload decoding and ordinary receive/cancel handlers.
    s += r'''
struct InPacket {
 std::vector<uint8_t> bytes;size_t offset=0;
 int16_t read_short(){uint16_t v=bytes.at(offset)|(uint16_t(bytes.at(offset+1))<<8);offset+=2;return static_cast<int16_t>(v);}
 int32_t read_int(){uint32_t v=0;for(int i=0;i<4;++i)v|=uint32_t(bytes.at(offset++))<<(8*i);return static_cast<int32_t>(v);}
};
struct Stage {Player player;static Stage& get(){static Stage stage;return stage;}Player& get_player(){return player;}};
struct UIBuffList {void add_buff(int,int){}};
struct UI {static UI& get(){static UI ui;return ui;}template<class T>std::unique_ptr<T> get_element(){return nullptr;}};
struct ApplyBuffHandler {void handle_buff(InPacket&,Buffstat::Id)const;};
struct CancelBuffHandler {void handle_buff(InPacket&,Buffstat::Id)const;};
void receive(Buffstat::Id stat,int16_t value,int32_t skill){
 InPacket packet;auto put=[&](uint32_t x,int n){for(int i=0;i<n;++i)packet.bytes.push_back((x>>(8*i))&255);};
 put(static_cast<uint16_t>(value),2);put(skill,4);put(200000,4);
 ApplyBuffHandler{}.handle_buff(packet,stat);assert(packet.offset==10);
}
void cancel(Buffstat::Id stat){InPacket packet;CancelBuffHandler{}.handle_buff(packet,stat);assert(packet.offset==0);}
void scalar(int id,int level,const char* name,int value){
 const auto text=std::to_string(id);nl::scalars["/"+text.substr(0,3)+".img/skill/"+text+"/level/"+std::to_string(level)+"/"+name]=value;
}
void setup(){
 nl::scalars.clear();scalar(2210001,30,"y",140);
 scalar(1111002,1,"damage",100);scalar(1111002,1,"x",3);
 scalar(1111002,7,"damage",109);scalar(1111002,7,"x",3);
 scalar(1111002,11,"damage",112);scalar(1111002,11,"x",4);
 scalar(1111002,30,"damage",120);scalar(1111002,30,"x",5);
 scalar(1120003,1,"damage",121);scalar(1120003,1,"x",6);
 scalar(1120003,5,"damage",125);scalar(1120003,5,"x",6);
 scalar(1120003,29,"damage",149);scalar(1120003,29,"x",10);
 scalar(1120003,30,"damage",150);scalar(1120003,30,"x",10);
}
'''
    return s


CASES = r'''
}
int main(int argc,char**argv){using namespace jrc;assert(argc==2);setup();
 auto close=[](double a,double b){return std::abs(a-b)<.00001;};
 auto& p=Stage::get().get_player();p.stats.physical=100;p.weapon=Weapon::SWORD_2H;
 Mob m;m.avoid=0;m.wdef=20;m.mdef=700;m.randomizer.draw=.1f;
 auto attack=[&](int skill){auto a=p.prepare_attack(skill!=0);if(skill)Skill{skill}.apply_stats(p,a);else a.hitcount=1;return a;};
 const std::string test=argv[1];
 #if !BUFF_FIXED
 (void)close;
 p.learned[1111002]=30;p.learned[1120003]=30;receive(Buffstat::COMBO,11,1111002);
 for(auto line:m.calculate_damage(attack(1121008)))assert(line==std::make_pair(231,false));
 p.weapon=Weapon::BOW;p.learned[3000001]=20;receive(Buffstat::SHARP_EYES,(15<<8)|140,3121002);
 assert(std::abs(attack(3121004).critical-.4)<.00001);
 for(auto line:m.calculate_damage(attack(3121004)))assert(line==std::make_pair(178,true));
 cancel(Buffstat::COMBO);SpecialMove finisher{1111003};assert(p.can_use(finisher)==SpecialMove::FBR_NONE);
 return 0;
 #else
 if(test=="combo"){
  p.learned[1111002]=30;
  assert(attack(1121008).weapon_damage_multiplier==1);
  receive(Buffstat::COMBO,1,1111002);assert(attack(0).combo_orbs==0);
  for(int count=2;count<=6;++count){
   receive(Buffstat::COMBO,count,1111002);auto a=attack(1121008);
   assert(a.combo_orbs==count-1 && close(a.weapon_damage_multiplier,(120+(count-2)*5)/100.0));
   for(auto line:m.calculate_damage(a))assert(line==std::make_pair(int(89*(260*a.weapon_damage_multiplier)/100),false));
  }
  auto full=attack(1121008);for(auto line:m.calculate_damage(full))assert(line==std::make_pair(323,false));
  p.learned[1120003]=30;
  receive(Buffstat::COMBO,2,1111002);assert(close(attack(0).weapon_damage_multiplier,1.5));
  receive(Buffstat::COMBO,6,1111002);assert(close(attack(0).weapon_damage_multiplier,1.7));
  receive(Buffstat::COMBO,7,1111002);assert(close(attack(0).weapon_damage_multiplier,1.74));
  receive(Buffstat::COMBO,11,1111002);auto max=attack(1121008);
  assert(max.combo_orbs==10 && close(max.weapon_damage_multiplier,1.9));
  assert(max.mindamage==100 && max.weapon_damage_percent==260);
  for(auto line:m.calculate_damage(max))assert(line==std::make_pair(439,false));
  for(auto line:m.calculate_damage(attack(0)))assert(line==std::make_pair(169,false));
  // No local accrual, consumption or cache: preparing/calculating is read-only.
  assert(p.buffs[Buffstat::COMBO].value==11);
  for(auto weapon:{Weapon::SWORD_1H,Weapon::SWORD_2H,Weapon::AXE_1H,Weapon::AXE_2H}){
   p.weapon=weapon;assert(close(attack(0).weapon_damage_multiplier,1.9));}
  for(auto weapon:{Weapon::BOW,Weapon::CLAW,Weapon::MACE_1H,Weapon::STAFF}){
   p.weapon=weapon;assert(attack(0).combo_orbs==0 && attack(0).weapon_damage_multiplier==1);}
  p.weapon=Weapon::SWORD_2H;cancel(Buffstat::COMBO);assert(attack(0).weapon_damage_multiplier==1);
 }else if(test=="levels"){
  p.learned[1111002]=1;receive(Buffstat::COMBO,4,1111002);
  assert(attack(0).combo_orbs==3 && close(attack(0).weapon_damage_multiplier,1));
  p.learned[1111002]=7;assert(close(attack(0).weapon_damage_multiplier,1.11));
  p.learned[1111002]=11;receive(Buffstat::COMBO,5,1111002);assert(close(attack(0).weapon_damage_multiplier,1.17));
  p.learned[1111002]=30;p.learned[1120003]=1;
  receive(Buffstat::COMBO,2,1111002);assert(close(attack(0).weapon_damage_multiplier,1.21));
  receive(Buffstat::COMBO,7,1111002);assert(close(attack(0).weapon_damage_multiplier,1.45));
  p.learned[1120003]=5;assert(close(attack(0).weapon_damage_multiplier,1.49));
  // An old larger authoritative count cannot exceed the newly learned cap.
  receive(Buffstat::COMBO,11,1111002);assert(attack(0).combo_orbs==6);
  p.learned.erase(1120003);assert(attack(0).combo_orbs==5 && close(attack(0).weapon_damage_multiplier,1.4));
  p.learned.erase(1111002);assert(attack(0).combo_orbs==0 && attack(0).weapon_damage_multiplier==1);
  p.learned[1111002]=30;receive(Buffstat::COMBO,11,11111001);assert(attack(0).weapon_damage_multiplier==1);
  receive(Buffstat::COMBO,-1,1111002);assert(attack(0).weapon_damage_multiplier==1);
 }else if(test=="finishers"){
  p.learned[1111002]=30;p.learned[1120003]=30;
  for(int id:{1111003,1111004,1111005,1111006}){
   cancel(Buffstat::COMBO);SpecialMove move{id};assert(p.can_use(move)==SpecialMove::FBR_OTHER && move.fallback_calls==0);
   receive(Buffstat::COMBO,1,1111002);assert(p.can_use(move)==SpecialMove::FBR_OTHER && move.fallback_calls==0);
   for(int orbs=1;orbs<=10;++orbs){
    receive(Buffstat::COMBO,orbs+1,1111002);assert(p.can_use(move)==SpecialMove::FBR_NONE);
    auto a=attack(id);const double combos[]={1.5,1.55,1.6,1.65,1.7,1.74,1.78,1.82,1.86,1.9};
    const double finish[]={1,1.2,1.54,2,2.5,2.5,2.5,2.5,2.5,2.5};
    assert(close(a.weapon_damage_multiplier,combos[orbs-1]*finish[orbs-1]));
    const int skill=id==1111003||id==1111004?350:200;
    for(auto line:m.calculate_damage(a))assert(line==std::make_pair(int(89*(skill*combos[orbs-1]*finish[orbs-1])/100),false));
    assert(p.buffs[Buffstat::COMBO].value==orbs+1);
   }
   // Ordinary server orb-consume resets to count1, without local mutation.
   receive(Buffstat::COMBO,1,1111002);assert(p.can_use(move)==SpecialMove::FBR_OTHER);
  }
  // Original published example: AC29,9orbs,Panic350 ->1618.75%.
  p.learned[1120003]=29;receive(Buffstat::COMBO,10,1111002);
  auto published=attack(1111003);assert(close(published.weapon_damage_multiplier,4.625));
  for(auto line:m.calculate_damage(published))assert(line==std::make_pair(1440,false));
  cancel(Buffstat::COMBO);SpecialMove regular{1121008};assert(p.can_use(regular)==SpecialMove::FBR_NONE);
 }else if(test=="sharp_eyes"){
  p.weapon=Weapon::BOW;p.learned[3000001]=20;
  receive(Buffstat::SHARP_EYES,(15<<8)|140,3121002);auto a=attack(3121004);
  assert(close(a.critical,.55) && a.critical_bonus_percent==240);
  for(auto line:m.calculate_damage(a))assert(line==std::make_pair(302,true));
  m.randomizer.draw=.54f;for(auto line:m.calculate_damage(a))assert(line.second);
  m.randomizer.draw=.55f;for(auto line:m.calculate_damage(a))assert(line==std::make_pair(89,false));
  m.randomizer.draw=.1f;
  // A physical class without a passive still gains SE, including a party buff.
  p.weapon=Weapon::SWORD_2H;a=attack(1121008);assert(close(a.critical,.15) && a.critical_bonus_percent==140);
  for(auto line:m.calculate_damage(a))assert(line==std::make_pair(356,true));
  p.weapon=Weapon::BOW;p.learned[3000001]=1;
  receive(Buffstat::SHARP_EYES,(1<<8)|111,3221002);a=attack(3121004);
  assert(close(a.critical,.13) && a.critical_bonus_percent==116);
  cancel(Buffstat::SHARP_EYES);a=attack(3121004);assert(close(a.critical,.12) && a.critical_bonus_percent==5);
  p.learned[3000001]=20;receive(Buffstat::SHARP_EYES,(15<<8)|140,3121002);
  p.inventory.present=false;a=attack(0);assert(a.type==Attack::CLOSE && close(a.critical,.15) && a.critical_bonus_percent==140);
  p.inventory.present=true;p.weapon=Weapon::CLAW;p.learned[4100001]=30;
  a=attack(4121007);assert(close(a.critical,.65) && a.critical_bonus_percent==240);
  receive(Buffstat::SHARP_EYES,(15<<8)|140,9999999);assert(close(attack(0).critical,.5));
 }else if(test=="order_and_damage_types"){
  p.learned[1111002]=30;p.learned[1120003]=30;
  receive(Buffstat::COMBO,11,1111002);receive(Buffstat::SHARP_EYES,(15<<8)|140,3121002);
  auto a=attack(1121008);for(auto line:m.calculate_damage(a))assert(line==std::make_pair(564,true));
  cancel(Buffstat::COMBO);cancel(Buffstat::SHARP_EYES);
  receive(Buffstat::SHARP_EYES,(15<<8)|140,3121002);receive(Buffstat::COMBO,11,1111002);
  assert(m.calculate_damage(attack(1121008))==m.calculate_damage(a));
  cancel(Buffstat::COMBO);for(auto line:m.calculate_damage(attack(1121008)))assert(line==std::make_pair(356,true));
  receive(Buffstat::COMBO,11,1111002);cancel(Buffstat::SHARP_EYES);
  for(auto line:m.calculate_damage(attack(1121008)))assert(line==std::make_pair(439,false));
  receive(Buffstat::SHARP_EYES,(15<<8)|140,3121002);
  p.weapon=Weapon::STAFF;auto magic=attack(2221006);magic.weapon_damage_multiplier=99;
  magic.critical=1;magic.critical_bonus_percent=999;
  for(auto line:m.calculate_damage(magic))assert(line==std::make_pair(9335,false));
  p.weapon=Weapon::SWORD_2H;auto fixed=attack(1000);fixed.weapon_damage_multiplier=99;
  for(auto line:m.calculate_damage(fixed))assert(line==std::make_pair(40,false));
  p.weapon=Weapon::BOW;p.learned[3000001]=20;
  // Existing Arrow Bomb splash exception retains defense-before-critical.
  for(auto line:m.calculate_damage(attack(3101005)))assert(line==std::make_pair(404,true));
  m.avoid=1000000;m.randomizer.draw=1;for(auto line:m.calculate_damage(a))assert(line==std::make_pair(0,false));
  m.randomizer.draw=0;
  assert(m.next_damage(600000,600000,1,1,260,140,1.9)==std::make_pair(999999,true));
  assert(m.next_damage(0,0,1,0,100,0,1.9)==std::make_pair(1,false));
 }else{assert(false);}
 #endif
}
'''


class CombatBuffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler=shutil.which('c++')
        if not cls.compiler:raise AssertionError('C++ compiler required')
        if hashlib.sha256((FIXTURE/'sha256.json').read_bytes()).hexdigest()!=PINS_SHA:
            raise AssertionError('source fixture pin manifest changed')
        pins=json.loads((FIXTURE/'sha256.json').read_text())
        for path,sha in pins.items():
            if hashlib.sha256((FIXTURE/path).read_bytes()).hexdigest()!=sha:
                raise AssertionError('pinned production source changed: '+path)
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        cls.binaries={}
        signatures={
          'Character/Player.cpp':['SpecialMove::ForbidReason Player::can_use','Attack Player::prepare_attack','void Player::give_buff','void Player::cancel_buff','bool Player::has_buff'],
          'Gameplay/Combat/Skill.cpp':['void Skill::apply_stats'],
          'Gameplay/MapleMap/Mob.cpp':['float Mob::calculate_hitchance','double Mob::calculate_mindamage','double Mob::calculate_maxdamage','std::vector<std::pair<int32_t, bool>> Mob::calculate_damage','std::pair<int32_t, bool> Mob::next_damage'],
          'Net/Handlers/PlayerHandlers.cpp':['void ApplyBuffHandler::handle_buff','void CancelBuffHandler::handle_buff'],
        }
        for fixed in (False,True):
            tree=Path(cls.tmp.name)/str(fixed);dest=tree/'src/client'
            shutil.copytree(FIXTURE,dest)
            if fixed:
                result=subprocess.run(['patch','-p1','--batch','--fuzz=0','-i',str(PATCH)],cwd=tree,capture_output=True,text=True,timeout=5)
                if result.returncode:raise AssertionError(result.stdout+result.stderr)
            (dest/'Template/Rectangle.h').write_text(spell.GEOMETRY)
            methods='\n'.join(method((dest/path).read_text(),sig) for path,sigs in signatures.items() for sig in sigs)
            source=tree/'test.cpp';source.write_text(declarations(fixed)+methods+CASES)
            binary=tree/'test'
            result=subprocess.run([cls.compiler,'-std=c++17','-Wall','-Wextra','-Werror','-Wno-error=deprecated-declarations','-DBUFF_FIXED='+str(int(fixed)),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=20)
            if result.returncode:raise AssertionError(result.stderr)
            cls.binaries[fixed]=binary

    def run_case(self,name,fixed=True):
        result=subprocess.run([str(self.binaries[fixed]),name],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_original_missing_buffs_and_finisher_admission(self):self.run_case('old',False)
    def test_server_received_combo_and_current_weapon_gate(self):self.run_case('combo')
    def test_asset_levels_capacity_and_learned_skill_removal(self):self.run_case('levels')
    def test_finisher_admission_damage_and_server_consumption(self):self.run_case('finishers')
    def test_sharp_eyes_chance_bonus_party_and_cancel(self):self.run_case('sharp_eyes')
    def test_buff_order_nonzero_defense_critical_magic_fixed_and_caps(self):self.run_case('order_and_damage_types')


if __name__=='__main__':unittest.main()
