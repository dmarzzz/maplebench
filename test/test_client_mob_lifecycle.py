"""Compile changed MapMobs methods, real MapObjects, and real Mob kill/alive bodies."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'test/fixtures/client-mob-lifecycle'
MOB=ROOT/'test/fixtures/client-magic-damage/Mob.cpp'
BASE=r'''
#pragma once
#include <cstdint>
#include <vector>
#include <utility>
namespace jrc {
template<class T> struct Point {T px=0,py=0;T x()const{return px;}T y()const{return py;}};
struct Physics{};struct Layer {using Id=int;static constexpr int LENGTH=8;};
struct MapObject {int32_t oid;int8_t layer;Point<int16_t> position;bool active=true;
 MapObject(int32_t o,int8_t l,Point<int16_t> p):oid(o),layer(l),position(p){};
 virtual ~MapObject()=default;virtual void draw(double,double,float)const=0;
 virtual int8_t update(const Physics&){return layer;}
 virtual bool is_active()const{return active;}virtual void makeactive(){active=true;}
 int8_t get_layer()const{return layer;}int32_t get_oid()const{return oid;}
 Point<int16_t> get_position()const{return position;}
}; }
'''
MOB_STUB=r'''
#pragma once
#include "MapObject.h"
namespace jrc {struct Mob:MapObject {
 inline static int created=0;inline static std::vector<int32_t> creation_order,drawn;
 int serial;int8_t control;bool dying=false,dead=false,fading=false,awaitdeath=false;
 Mob(int32_t oid,int8_t layer,Point<int16_t> p,int8_t mode):MapObject(oid,layer,p),serial(++created),control(mode){creation_order.push_back(oid);}
 void set_control(int8_t mode){control=mode;}void apply_death(){dying=true;}
 bool is_alive()const;void kill(int8_t);void draw(double,double,float)const override{drawn.push_back(oid);}
}; }
'''
HEADER=r'''
#pragma once
#include "MapObjects.h"
#include "Mob.h"
#include <queue>
namespace jrc {
struct MobSpawn {int32_t oid;int8_t layer;int16_t x;int8_t mode;
 int32_t get_oid()const{return oid;}int8_t get_mode()const{return mode;}
 std::unique_ptr<MapObject> instantiate()const{return std::make_unique<Mob>(oid,layer,Point<int16_t>{x,0},mode);}};
struct MapMobs {MapObjects mobs;std::queue<MobSpawn> spawns;
 void draw(Layer::Id,double,double,float)const;void update(const Physics&);
 std::vector<std::pair<int32_t,Point<int16_t>>> get_alive_positions()const;
 void spawn(MobSpawn&&);void remove(int32_t,int8_t);void clear();void set_control(int32_t,bool);
}; }
'''
PROGRAM=r'''
#include "src/client/Gameplay/MapleMap/affected.cpp"
#include <iostream>
#include <stdexcept>
using namespace jrc;
void need(bool yes,const char* reason){if(!yes)throw std::runtime_error(reason);}
Optional<Mob> mob(MapMobs& m,int oid=1){return m.mobs.get(oid);}
void event(MapMobs& m,int index){switch(index){
 case 0:m.spawn({1,0,10,0});break; // initial full spawn
 case 1:m.spawn({1,0,10,1});break; // initial controller with complete spawn data
 case 2:m.set_control(1,false);break;
 case 3:m.remove(1,0);break;
 case 4:m.remove(1,1);break;
 case 5:m.set_control(1,false);break;
 case 6:m.spawn({1,3,30,0});break; // normal-login refresh, same OID
 case 7:m.spawn({1,3,30,2});break; // full controller packet
}}
int main(int argc,char**argv){try{need(argc==2,"case required");std::string mode=argv[1];Physics p;
 if(mode=="original") {
  MapMobs m;event(m,0);event(m,1);m.update(p);for(int i=2;i<8;++i)event(m,i);m.update(p);
  need(mob(m) && !mob(m)->is_alive(),"original retained dying-state failure not reproduced");
  MapMobs q;q.spawn({2,0,20,0});q.remove(2,0);q.update(p);
  need(mob(q,2) && mob(q,2)->is_alive(),"original queued-kill resurrection not reproduced");
 }
 else if(mode=="refresh_splits") {
  // Every boundary can occur before or after a game update: all 128 partitions.
  for(unsigned mask=0;mask<128;++mask){MapMobs m;
   for(int i=0;i<8;++i){event(m,i);if(i<7 && (mask&(1u<<i)))m.update(p);}m.update(p);
   need(m.mobs.size()==1 && mob(m) && mob(m)->is_alive(),"refresh batching changed final alive state");
   need(mob(m)->get_position().x()==30 && mob(m)->get_layer()==3 && mob(m)->control==2,"new lifetime spawn fields lost");
   need(m.get_alive_positions().size()==1,"alive observation missing");
   Mob::drawn.clear();m.draw(0,0,0,1);need(Mob::drawn.empty(),"stale previous layer retains OID");
   m.draw(3,0,0,1);need(Mob::drawn==std::vector<int32_t>{1},"new layer draws zero or duplicated OIDs");}
 }
 else if(mode=="final_kill") {
  for(int animation: {0,1,2}){MapMobs m;m.spawn({1,0,10,0});m.spawn({1,0,10,2});m.remove(1,animation);m.update(p);
   need(m.mobs.size()==0 && m.spawns.empty(),"last kill resurrected queued lifetime");}
 }
 else if(mode=="unrelated_fifo") {MapMobs m;Mob::creation_order.clear();
  m.spawn({1,0,10,0});m.spawn({2,1,20,0});m.spawn({1,2,12,1});m.spawn({3,2,30,0});
  m.remove(1,1);m.spawn({1,3,40,0});m.update(p);
  need(Mob::creation_order==std::vector<int32_t>({2,3,1}),"unrelated queue order changed");
  need(m.mobs.size()==3 && mob(m)->get_position().x()==40,"later same-OID lifetime was cancelled");}
 else if(mode=="alive_duplicate") {MapMobs m;m.spawn({1,0,10,1});m.update(p);int serial=mob(m)->serial;
  m.spawn({1,3,99,2});m.update(p);
  need(mob(m)->serial==serial && mob(m)->control==2 && mob(m)->get_position().x()==10 && mob(m)->get_layer()==0,"live controller duplicate recreated object");
  m.spawn({1,3,99,0});m.update(p);need(mob(m)->serial==serial && mob(m)->control==2,"mode zero duplicate cleared live control");}
 else if(mode=="unknown_animation") {
  for(int animation: {-128,-1,3,7,127}){MapMobs m;m.spawn({1,0,10,0});m.spawn({2,1,20,1});m.remove(1,animation);m.update(p);
   need(m.mobs.size()==2 && mob(m)->is_alive() && mob(m,2)->is_alive(),"unknown kill cancelled queued spawn");}
 }
 else if(mode=="kill_animation") {
  for(int animation: {0,1,2,7}){MapMobs m;m.spawn({1,0,10,1});m.update(p);int serial=mob(m)->serial;
   m.remove(1,animation);need(m.mobs.size()==1 && mob(m)->serial==serial,"kill eagerly destroyed instantiated animation");
   need(mob(m)->active==(animation!=0),"active kill behavior changed");
   need(mob(m)->dying==(animation==1||animation==2) && mob(m)->fading==(animation==2),"death animation flags changed");}
 }
 else { throw std::runtime_error("unknown case"); }
 std::cout<<mode<<" passed\n";
 return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
'''


def method(text, signature):
    start=text.index(signature);brace=text.index('{',start);i=brace+1;depth=1
    while depth:
        depth+=(text[i]=='{')-(text[i]=='}');i+=1
    return text[start:i]


@unittest.skipUnless(shutil.which('c++') and shutil.which('patch'),'C++ compiler and patch required')
class MobLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);cls.binaries={}
        for name,sha in json.loads((FIXTURE/'SHA256.json').read_text()).items():
            assert hashlib.sha256((FIXTURE/name).read_bytes()).hexdigest()==sha,name
        assert hashlib.sha256(MOB.read_bytes()).hexdigest()=='c2c152761ecbdc2e347b3074a07ec9f3ec59982aae669e17e5bf37ab9660f78a', 'Mob fixture changed'
        for patched in (False,True):
            tree=Path(cls.temp.name)/str(patched);folder=tree/'src/client/Gameplay/MapleMap';folder.mkdir(parents=True)
            for name in ('MapMobs.cpp','MapObjects.cpp','MapObjects.h'):shutil.copyfile(FIXTURE/name,folder/name)
            templates=tree/'src/client/Template';templates.mkdir(parents=True);shutil.copyfile(FIXTURE/'Optional.h',templates/'Optional.h')
            if patched:
                subprocess.run(['patch','-p1','--batch','--fuzz=0','-i',str(ROOT/'patches/full-client/0016-mob-lifecycle-order.patch')],cwd=tree,check=True,capture_output=True,timeout=5)
            source=(folder/'MapMobs.cpp').read_text()
            affected=source[:source.index('    void MapMobs::send_mobhp(')]+'\n}\n'
            mob=MOB.read_text();affected+='namespace jrc {\n'+method(mob,'    void Mob::kill(')+'\n'+method(mob,'    bool Mob::is_alive() const')+'\n}\n'
            (folder/'affected.cpp').write_text(affected)
            for name,raw in [('MapObject.h',BASE),('Layer.h','#pragma once\n#include "MapObject.h"\n'),('Mob.h',MOB_STUB),('MapMobs.h',HEADER)]:
                (folder/name).write_text(raw)
            (tree/'harness.cpp').write_text(PROGRAM);binary=tree/'lifecycle'
            result=subprocess.run(['c++','-std=c++17','-O1','-Wall','-Wextra','-Werror',str(tree/'harness.cpp'),str(folder/'MapObjects.cpp'),'-o',str(binary)],capture_output=True,text=True,timeout=20)
            if result.returncode:raise RuntimeError(result.stderr)
            cls.binaries[patched]=binary

    def case(self,name,patched=True):
        r=subprocess.run([str(self.binaries[patched]),name],capture_output=True,text=True,timeout=5)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_original_dying_reuse_and_pending_kill_failures_reproduced(self):self.case('original',False)
    def test_actual_normal_login_refresh_all_update_partitions(self):self.case('refresh_splits')
    def test_last_kill_cancels_all_earlier_queued_spawns(self):self.case('final_kill')
    def test_unrelated_pending_oids_keep_order_and_later_spawn_survives(self):self.case('unrelated_fifo')
    def test_alive_controller_duplicate_keeps_object_and_existing_semantics(self):self.case('alive_duplicate')
    def test_instantiated_kill_animation_is_preserved(self):self.case('kill_animation')
    def test_unknown_kill_animation_is_noop_for_pending_spawns(self):self.case('unknown_animation')

if __name__=='__main__':unittest.main()
