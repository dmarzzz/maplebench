"""Compile actual patched Combat state transitions with observable dependency fakes."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from test_client_hurricane_channel import method

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'test/fixtures/client-hurricane-channel'
BASE=r'''
#include <cassert>
#include <cstdint>
#include <string>
#include <vector>
namespace jrc {
struct Constants {static constexpr int TIMESTEP=8;};
struct KeyAction {enum Id {LEFT,RIGHT,UP,DOWN,JUMP,ATTACK};};
struct Weapon {enum Type {BOW,CROSSBOW,CLAW,NONE};};
struct SpecialMove {enum ForbidReason {FBR_NONE,FBR_OTHER,FBR_COOLDOWN};int id=3121004;};
struct Stats {Weapon::Type weapon=Weapon::BOW;Weapon::Type get_weapontype()const{return weapon;}};
struct Player {
 Stats stats;bool dead=false,climbing=false,sitting=false,attacking=false;
 bool learned=true,cooldown=false;int mp=1000,ammo=1000,poses=0;bool keys[6]={};
 bool is_dead()const{return dead;}bool is_climbing()const{return climbing;}
 bool is_sitting()const{return sitting;}bool is_key_down(KeyAction::Id k)const{return keys[k];}
 Stats& get_stats(){return stats;}
 bool can_attack()const{return !attacking&&!dead&&!climbing&&!sitting&&stats.weapon!=Weapon::NONE;}
 SpecialMove::ForbidReason can_use(const SpecialMove&)const {
  return !learned||cooldown||mp<9||ammo<1?SpecialMove::FBR_OTHER:SpecialMove::FBR_NONE;
 }
 void attack(const std::string& action){assert(action=="shoot1");attacking=true;++poses;}
};
struct ForbidSkillMessage {ForbidSkillMessage(SpecialMove::ForbidReason,Weapon::Type){} void drop(){}};
struct Combat {
 Player player;bool hurricane_key_down=false,hurricane_active=false;
 int32_t hurricane_until_shot_ms=0;int16_t teleport_cooldown=0;
 SpecialMove move;int now=0;std::vector<int> shots;
 const SpecialMove& get_move(int id){move.id=id;return move;}
 bool is_teleport_skill(int)const{return false;}
 void apply_move(const SpecialMove& m){assert(m.id==3121004);shots.push_back(now);player.attack("shoot1");}
 bool channel_permitted();void cancel_channel();void send_skill_key(int32_t,bool);
 void update_channel();void clear();bool use_move(int32_t);
 void ticks(int count){while(count--){now+=8;update_channel();}}
};
'''
CHECKS=r'''
}
using namespace jrc;
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];
 if(mode=="cadence") {Combat c;c.send_skill_key(3121004,true);assert(c.shots.empty());
  c.ticks(119);assert(c.shots.empty());c.ticks(1);assert(c.shots==std::vector<int>{960});
  for(int i=0;i<100;++i){c.send_skill_key(3121004,true);c.ticks(15);}
  assert(c.shots.size()==101);for(size_t i=1;i<c.shots.size();++i)assert(c.shots[i]-c.shots[i-1]==120);
  // The previous attack pose never blocks the next pulse. No weapon-speed input is used.
  assert(c.player.attacking);c.send_skill_key(3121004,false);c.ticks(200);assert(c.shots.size()==101);
  c.send_skill_key(3121004,false);c.ticks(200);assert(c.shots.size()==101);
 }
 else if(mode=="short_hold") {Combat c;c.send_skill_key(3121004,true);c.ticks(119);
  c.send_skill_key(3121004,false);c.ticks(1000);assert(c.shots.empty());}
 else if(mode=="admission") {for(int i=0;i<10;++i){Combat c;
  switch(i){case 0:c.player.dead=true;break;case 1:c.player.climbing=true;break;
   case 2:c.player.sitting=true;break;case 3:c.player.stats.weapon=Weapon::CROSSBOW;break;
   case 4:c.player.mp=8;break;case 5:c.player.ammo=0;break;case 6:c.player.learned=false;break;
   case 7:c.player.cooldown=true;break;case 8:c.player.attacking=true;break;case 9:c.player.keys[KeyAction::RIGHT]=true;}
  c.send_skill_key(3121004,true);c.ticks(1000);assert(c.shots.empty());
 }}
 else if(mode=="stop") {for(int i=0;i<10;++i){Combat c;c.send_skill_key(3121004,true);c.ticks(120);
  switch(i){case 0:c.player.dead=true;break;case 1:c.player.climbing=true;break;
   case 2:c.player.sitting=true;break;case 3:c.player.stats.weapon=Weapon::CLAW;break;
   case 4:c.player.mp=8;break;case 5:c.player.ammo=0;break;case 6:c.player.learned=false;break;
   case 7:c.player.cooldown=true;break;case 8:c.cancel_channel();break;case 9:c.player.keys[KeyAction::LEFT]=true;}
  c.ticks(1000);assert(c.shots.size()==1);assert(!c.hurricane_active);
  c.player=Player{};c.send_skill_key(3121004,true);c.ticks(1000);assert(c.shots.size()==1);
  c.send_skill_key(3121004,false);c.send_skill_key(3121004,true);c.ticks(120);assert(c.shots.size()==2);
 }}
 else if(mode=="map") {Combat c;c.send_skill_key(3121004,true);c.ticks(120);c.clear();
  c.player=Player{};c.send_skill_key(3121004,true);c.ticks(1000);assert(c.shots.size()==1);
  c.send_skill_key(3121004,false);c.send_skill_key(3121004,true);c.ticks(120);assert(c.shots.size()==2);
 }
 else if(mode=="other_attack") {Combat c;c.send_skill_key(3121004,true);c.ticks(120);
  c.use_move(0);c.ticks(1000);assert(c.shots.size()==1&&!c.hurricane_active);}
 else assert(false);
}
'''

class HurricaneHoldTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  compiler=shutil.which('c++')
  if not compiler: raise unittest.SkipTest('C++ compiler required')
  cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);root=Path(cls.temp.name)
  for name,digest in json.loads((FIXTURE/'manifest.json').read_text()).items():
   if hashlib.sha256((FIXTURE/name).read_bytes()).hexdigest()!=digest:raise AssertionError(name)
  shutil.copytree(FIXTURE,root/'src/client')
  subprocess.run(['patch','-p1','--batch','-i',str(ROOT/'patches/full-client/0018-hurricane-channel.patch')],cwd=root,check=True,capture_output=True,timeout=5)
  src=(root/'src/client/Gameplay/Combat/Combat.cpp').read_text()
  bodies='\n'.join(method(src,s) for s in ['bool Combat::channel_permitted','void Combat::cancel_channel','void Combat::send_skill_key','void Combat::update_channel','void Combat::clear','bool Combat::use_move'])
  p=root/'test.cpp';p.write_text(BASE+bodies+CHECKS);cls.binary=root/'test'
  result=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror',str(p),'-o',str(cls.binary)],capture_output=True,text=True,timeout=25)
  if result.returncode:raise AssertionError(result.stderr)
 def check_case(self,name):subprocess.run([str(self.binary),name],check=True,capture_output=True,timeout=5)
 def test_cadence_and_release(self):self.check_case('cadence')
 def test_release_during_preparation(self):self.check_case('short_hold')
 def test_admission(self):self.check_case('admission')
 def test_death_resources_movement_and_explicit_cancel(self):self.check_case('stop')
 def test_map_clear_requires_fresh_press(self):self.check_case('map')
 def test_other_attack_cancels_channel(self):self.check_case('other_attack')
