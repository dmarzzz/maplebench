"""Compile actual packet readers/handlers and actual queued Mob lifetime methods."""
import hashlib,json,shutil,subprocess,tempfile,unittest
from pathlib import Path
from test_client_mob_lifecycle import method,BASE,MOB_STUB,HEADER,FIXTURE as LIFE
ROOT=Path(__file__).resolve().parents[1];FIXTURE=ROOT/'test/fixtures/client-mob-status'
PARSER=r'''
#include "src/client/Net/Handlers/Helpers/MobStatusPacket.h"
#include <cassert>
#include <vector>
namespace jrc {
struct Mobs {int calls=0;int oid=0;bool cancel=false;MobMovementStatus received;
 void apply_status(int o,const MobMovementStatus&s,bool c){++calls;oid=o;received=s;cancel=c;}};
struct Stage {Mobs mobs;static Stage&get(){static Stage s;return s;}Mobs&get_mobs(){return mobs;}};
struct ApplyMobStatusHandler{void handle(InPacket&)const;};struct CancelMobStatusHandler{void handle(InPacket&)const;};
HANDLERS
}
using namespace jrc;
void put(std::vector<int8_t>&v,int64_t n,int bytes){for(int i=0;i<bytes;++i)v.push_back((n>>(8*i))&255);}
std::vector<int8_t> make(bool cancel=false,bool spawn=false,bool reflected=false){std::vector<int8_t>v;
 if(!spawn)put(v,77,4);
 int first=2|(reflected?0x20000000:0),second=1|0x40|0x80|0x100;
 if(spawn){put(v,first,4);put(v,first,4);put(v,second,4);put(v,second,4);}
 else{put(v,0,8);put(v,first,4);put(v,second,4);}
 if(!cancel){for(int val:{10,19,-40,1,1}){put(v,val,2);put(v,3121007,4);put(v,-1,2);}
  if(reflected){put(v,10,2);put(v,120,4);put(v,-1,2);put(v,5,4);if(spawn)put(v,100,4);}
 }
 if(!spawn){if(!cancel)put(v,reflected?3:5,1);put(v,0,4);}
 else put(v,1234,2);return v;
}
int main(){
 for(bool reflection:{false,true}){auto bytes=make(false,false,reflection);
  for(size_t n=0;n<bytes.size();++n){Stage::get().mobs.calls=0;InPacket p(bytes.data(),n);bool failed=false;
   try{ApplyMobStatusHandler{}.handle(p);}catch(const PacketError&){failed=true;}
   assert(failed&&Stage::get().mobs.calls==0);
  }
  InPacket p(bytes.data(),bytes.size());ApplyMobStatusHandler{}.handle(p);auto&m=Stage::get().mobs;
  assert(m.calls==1&&m.oid==77&&!m.cancel&&m.received.speed==-40&&m.received.fields==0x1c0);
  auto extra=bytes;extra.push_back(0);InPacket e(extra.data(),extra.size());bool failed=false;
  try{ApplyMobStatusHandler{}.handle(e);}catch(const PacketError&){failed=true;}assert(failed&&m.calls==1);
  auto spawn=make(false,true,reflection);InPacket q(spawn.data(),spawn.size());auto s=read_mob_status(q,false);
  assert(s.movement.fields==0x1c0&&s.movement.speed==-40&&q.read_short()==1234);
 }
 auto bytes=make(true);for(size_t n=0;n<bytes.size();++n){Stage::get().mobs.calls=0;InPacket p(bytes.data(),n);
  bool failed=false;try{CancelMobStatusHandler{}.handle(p);}catch(const PacketError&){failed=true;}
  assert(failed&&Stage::get().mobs.calls==0);}
 InPacket p(bytes.data(),bytes.size());CancelMobStatusHandler{}.handle(p);assert(Stage::get().mobs.cancel);
 auto unknown=make();unknown[19]|=int8_t(0x80);InPacket bad(unknown.data(),unknown.size());bool failed=false;
 try{ApplyMobStatusHandler{}.handle(bad);}catch(const PacketError&){failed=true;}assert(failed);
 auto wrong=make();wrong[4]=1;InPacket b(wrong.data(),wrong.size());failed=false;
 try{ApplyMobStatusHandler{}.handle(b);}catch(const PacketError&){failed=true;}assert(failed);
}
'''
LIFECHECK=r'''
#include "src/client/Gameplay/MapleMap/affected.cpp"
#include <cassert>
using namespace jrc;
Optional<Mob> get(MapMobs&m){return m.mobs.get(1);}
int main(){Physics p;MapMobs m;MobMovementStatus freeze{0x100,0},slow{0x40,-50},stun{0x80,0};
 m.apply_status(1,freeze,false);m.spawn({1,0,10,0},{});m.update(p);assert(!get(m)->movement_status.stopped());
 m.clear();m.spawn({1,0,10,0},{});m.apply_status(1,freeze,false);m.set_control(1,true);m.update(p);
 assert(get(m)->movement_status.stopped());
 m.apply_status(1,stun,false);m.apply_status(1,freeze,true);assert(get(m)->movement_status.stopped());
 m.apply_status(1,stun,true);assert(!get(m)->movement_status.stopped());
 m.apply_status(1,slow,false);assert(get(m)->movement_status.force(0.1,0.001)==0.05);
 m.spawn({1,0,10,1},freeze);m.apply_status(1,freeze,true);m.update(p);assert(!get(m)->movement_status.stopped());
 for(int k=0;k<=2;++k){m.clear();m.spawn({1,0,10,0},freeze);m.apply_status(1,stun,false);m.remove(1,k);
  m.apply_status(1,slow,false);m.spawn({1,0,10,0},{});m.update(p);assert(get(m)->movement_status.fields==0);}
 m.clear();m.spawn({1,0,10,0},freeze);m.clear();m.update(p);assert(m.mobs.size()==0&&m.movement_status.empty());
 m.spawn({1,0,10,0},freeze);m.update(p);auto mob=get(m);mob->phobj={1,2,3,4};
 assert(mob->stop_status_motion());assert(mob->phobj.hspeed==0&&mob->phobj.vspeed==0&&mob->phobj.hforce==0&&mob->phobj.vforce==0);
 mob->kill(1);assert(!mob->is_alive()&&mob->movement_status.fields==0&&!mob->stop_status_motion());
 MobMovementStatus s{0x40,-40};assert(s.force(0.1,0.001)==0.06);s.speed=-500;assert(s.force(0.1,0.001)==0);
 s.speed=500;assert(s.force(0.1,0.001)==0.2);s.merge({0x40,0},true);assert(s.force(0.1,0.001)==0.1);assert(s.force(0.35,0.001)==0.35);
}
'''

@unittest.skipUnless(shutil.which('c++'),'C++ compiler required')
class MobStatusTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);cls.tree=Path(cls.temp.name)
  for name,sha in json.loads((FIXTURE/'manifest.json').read_text()).items():assert hashlib.sha256((FIXTURE/name).read_bytes()).hexdigest()==sha,name
  shutil.copytree(FIXTURE,cls.tree/'src/client')
  subprocess.run(['patch','-p1','--batch','--fuzz=0','-i',str(ROOT/'patches/full-client/0021-monster-movement-status.patch')],cwd=cls.tree,check=True,capture_output=True,timeout=5)
 def compile_run(self,name,code,extras=()):
  p=self.tree/(name+'.cpp');p.write_text(code);binary=self.tree/name
  result=subprocess.run(['c++','-std=c++17','-O1','-Wall','-Wextra','-Werror',str(p),*map(str,extras),'-o',str(binary)],capture_output=True,text=True,timeout=25)
  self.assertEqual(result.returncode,0,result.stderr);subprocess.run([str(binary)],check=True,capture_output=True,timeout=5)
 def test_actual_dynamic_handlers_masks_and_all_truncations(self):
  point=self.tree/'src/client/Template/Point.h';point.parent.mkdir(parents=True,exist_ok=True)
  point.write_text('#pragma once\nnamespace jrc {template<class T>struct Point{T x,y;};}\n')
  source=(self.tree/'src/client/Net/Handlers/MapObjectHandlers.cpp').read_text()
  handlers='\n'.join(method(source,s) for s in ['    void ApplyMobStatusHandler::handle','    void CancelMobStatusHandler::handle'])
  self.compile_run('parser',PARSER.replace('HANDLERS',handlers),[self.tree/'src/client/Net/InPacket.cpp'])
 def test_actual_lifetimes_cancel_clear_and_movement(self):
  folder=self.tree/'src/client/Gameplay/MapleMap'
  for name in ['MapObjects.cpp','MapObjects.h']:shutil.copyfile(LIFE/name,folder/name)
  template=self.tree/'src/client/Template';template.mkdir(exist_ok=True);shutil.copyfile(LIFE/'Optional.h',template/'Optional.h')
  src=(folder/'MapMobs.cpp').read_text();affected=src[:src.index('    void MapMobs::send_mobhp(')]+'\n}\n'
  mob=(folder/'Mob.cpp').read_text();affected+='namespace jrc {\n'+'\n'.join(method(mob,s) for s in ['    void Mob::kill(','    bool Mob::is_alive() const','    bool Mob::stop_status_motion()'])+'\n}\n'
  (folder/'affected.cpp').write_text(affected)
  stub=MOB_STUB.replace('#include "MapObject.h"','#include "MapObject.h"\n#include "MobMovementStatus.h"').replace('int serial;','MobMovementStatus movement_status;\n struct Ph{double hspeed,vspeed,hforce,vforce;};Ph phobj{};\n bool stop_status_motion();\n void set_movement_status(const MobMovementStatus&s){movement_status=s;}\n int serial;')
  header=HEADER.replace('#include <queue>','#include <queue>\n#include <unordered_map>\n#include "MobMovementStatus.h"').replace('void spawn(MobSpawn&&);','void spawn(MobSpawn&&,MobMovementStatus initial={});\n void apply_status(int32_t,const MobMovementStatus&,bool);\n std::unordered_map<int32_t,MobMovementStatus> movement_status;')
  for name,text in [('MapObject.h',BASE),('Layer.h','#pragma once\n#include "MapObject.h"\n'),('Mob.h',stub),('MapMobs.h',header)]: (folder/name).write_text(text)
  self.compile_run('life',LIFECHECK,[folder/'MapObjects.cpp'])

 def test_actual_update_halts_ai_without_killing_and_resumes_slow(self):
  source=(FIXTURE/'Gameplay/MapleMap/Mob.cpp').read_text()
  # This is the actual patched update body; graphics and terrain are inert seams.
  source=(self.tree/'src/client/Gameplay/MapleMap/Mob.cpp').read_text()
  code=r'''
#include "src/client/Gameplay/MapleMap/MobMovementStatus.h"
#include <array>
#include <cassert>
namespace jrc {
struct PhysicsObject {static constexpr int TURNATEDGES=1;};
struct Ph {double hspeed=1,vspeed=1,hforce=1,vforce=1;int fhlayer=2;bool onground=true;
 bool is_flag_not_set(int)const{return false;}void set_flag(int){}void normalize(){}};
struct Physics {mutable int moved=0;struct FH{void update_fh(Ph&)const{}}fh;
 void move_object(Ph&)const{++moved;}const FH&get_fht()const{return fh;}};
struct Animation {int calls=0;bool update(){++calls;return true;}};
struct Opacity {double v=1;void operator-=(double x){v-=x;}void operator+=(double x){v+=x;}double last()const{return v;}void set(double x){v=x;}};
struct Mob {
 enum Stance {STAND,MOVE,HIT,JUMP,DIE};enum Direction {UPWARDS,DOWNWARDS,STRAIGHT};
 bool active=true,dead=false,dying=false,fading=false,fadein=false,awaitdeath=false;
 bool canfly=false,canmove=true,control=true,flip=true;Stance stance=MOVE;Direction flydirection=STRAIGHT;
 int counter=1,ai=0,packets=0;double speed=0.1,flyspeed=0.05;Ph phobj;Opacity opacity;
 std::array<Animation,5>animations{};Animation effects,showhp;MobMovementStatus movement_status;
 void set_stance(Stance x){stance=x;}void next_move(){++ai;}void update_movement(){++packets;}
 bool is_alive()const;bool stop_status_motion();int8_t update(const Physics&);
};
'''
  code+='\n'.join(method(source,s) for s in ['    bool Mob::is_alive() const','    bool Mob::stop_status_motion()','    int8_t Mob::update('])
  code+=r'''
}
int main(){using namespace jrc;Physics p;Mob m;m.movement_status={0x80,0};
 for(int i=0;i<500;++i)m.update(p);
 assert(m.is_alive()&&m.active&&m.counter==1&&m.ai==0&&m.packets==0&&p.moved==0);
 assert(m.effects.calls==500&&m.showhp.calls==500&&m.animations[Mob::MOVE].calls==500);
 assert(m.phobj.hspeed==0&&m.phobj.vspeed==0&&m.phobj.hforce==0&&m.phobj.vforce==0);
 m.movement_status.merge({0x80,0},true);m.movement_status.merge({0x40,-50},false);m.update(p);
 assert(p.moved==1&&m.counter==2&&m.phobj.hforce==0.05);
 m.movement_status.merge({0x40,0},true);m.update(p);assert(m.phobj.hforce==0.1&&p.moved==2);
 m.movement_status={0x100,0};m.stance=Mob::DIE;m.dying=true;m.update(p);assert(!m.active&&m.dead);
}
'''
  self.compile_run('movement',code)
