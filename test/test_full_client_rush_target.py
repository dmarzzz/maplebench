"""Compile the selected client's real target selection and Rush caller path.

The operator source fixture contains no assets. Small stand-ins supply monster
positions and damage, while the actual attack result, selection, and Rush
functions determine the selected endpoints and movement destination.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


def function(text, signature):
    start = text.index(signature)
    opening = text.index('{', start)
    depth = 1
    index = opening + 1
    while depth:
        depth += (text[index] == '{') - (text[index] == '}')
        index += 1
    return text[start:index]


class NativeRushTargetTest(unittest.TestCase):
    def test_actual_selected_endpoints_drive_rush(self):
        source = os.environ.get('MAPLEBENCH_TEST_CLIENT_SOURCE')
        if not source:
            self.skipTest('Operator native source fixture not supplied')
        source = Path(source).resolve(strict=True)
        attack = (source/'Gameplay/Combat/Attack.h').read_text()
        mobs = (source/'Gameplay/MapleMap/MapMobs.cpp').read_text()
        combat = (source/'Gameplay/Combat/Combat.cpp').read_text()
        actual_types = '\n'.join((
            function(attack, 'struct Attack\n') + ';',
            function(attack, 'struct AttackResult\n') + ';',
        ))
        actual = '\n'.join((
            function(mobs, 'AttackResult MapMobs::send_attack('),
            function(mobs, 'std::vector<int32_t> MapMobs::find_closest('),
            function(mobs, 'Point<int16_t> MapMobs::get_mob_position('),
            function(combat, 'void Combat::apply_rush('),
        ))
        compiler = shutil.which(os.environ.get('CXX', 'c++'))
        self.assertIsNotNone(compiler, 'Rush source check requires a C++ compiler')
        harness = r'''#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <map>
#include <memory>
#include <unordered_map>
#include <vector>
namespace jrc {
template<class T> struct Point {
    T px=0,py=0;
    Point()=default;
    Point(T x,T y):px(x),py(y){}
    T x()const{return px;} T y()const{return py;}
    uint16_t distance(Point p)const{return static_cast<uint16_t>(
        std::hypot(double(px-p.px),double(py-p.py)));}
};
template<class T> struct Rectangle {
    T left=0,right=0,top=0,bottom=0;
    Rectangle()=default;
    Rectangle(int l,int r,int t,int b):left(static_cast<T>(l)),right(static_cast<T>(r)),
        top(static_cast<T>(t)),bottom(static_cast<T>(b)){}
    T l()const{return left;} T r()const{return right;}
    T t()const{return top;} T b()const{return bottom;}
};
}
namespace jrc {
''' + actual_types + r'''
template<class T> using Optional=T*;
struct Mob {
    int32_t oid;Point<int16_t> position;
    bool is_alive()const{return true;}
    bool is_in_range(const Rectangle<int16_t>&)const{return true;}
    int32_t get_oid()const{return oid;}
    Point<int16_t> get_position()const{return position;}
    Point<int16_t> get_body_position()const{return position;}
    std::vector<std::pair<int32_t,bool>> calculate_damage(const Attack&)const{
        return {{123,false}};
    }
};
struct Mobs {
    std::map<int32_t,std::shared_ptr<Mob>> values;
    int32_t unavailable=0;
    auto begin()const{return values.begin();} auto end()const{return values.end();}
    Mob* get(int32_t id)const{
        const auto it=values.find(id);
        return it==values.end()||id==unavailable?nullptr:it->second.get();
    }
};
struct MapMobs {
    Mobs mobs;
    AttackResult send_attack(const Attack&);
    std::vector<int32_t> find_closest(Rectangle<int16_t>,Point<int16_t>,uint8_t)const;
    Point<int16_t> get_mob_position(int32_t)const;
};
struct Player {
    bool rushed=false;int16_t target=-1;
    void rush(int16_t x){rushed=true;target=x;}
};
struct Combat {
    MapMobs& mobs;Player player;
    explicit Combat(MapMobs& m):mobs(m){}
    void apply_rush(const AttackResult&);
};
''' + actual + r'''
bool check(unsigned present,unsigned limit,int32_t unavailable=0){
    MapMobs mobs;mobs.mobs.unavailable=unavailable;
    for(unsigned i=1;i<=present;i++){
        const int32_t id=1000+static_cast<int32_t>(i);
        mobs.mobs.values[id]=std::make_shared<Mob>(Mob{id,
            Point<int16_t>(static_cast<int16_t>(i*10),0)});
    }
    Attack attack;attack.mobcount=static_cast<uint8_t>(limit);attack.hitcount=1;
    attack.skill=1121006;attack.range={-250,0,-50,0};
    const AttackResult result=mobs.send_attack(attack);
    std::vector<int32_t> expected;
    for(unsigned i=1;i<=std::min(present,limit);i++)
        if(static_cast<int32_t>(1000+i)!=unavailable)expected.push_back(1000+i);
    const unsigned selected=static_cast<unsigned>(expected.size());
    const int32_t first=selected?expected.front():0,last=selected?expected.back():0;
    if(result.mobcount!=selected||result.damagelines.size()!=selected
       ||result.hitcount!=1||result.skill!=1121006
       ||result.first_oid!=first||result.last_oid!=last){
        std::cerr<<"Wrong endpoints or unchanged damage metadata for "
                 <<present<<" available targets and cap "<<limit<<"\n";
        return false;
    }
    for(int32_t id:expected){
        const auto found=result.damagelines.find(id);
        if(found==result.damagelines.end()||found->second.size()!=1
           ||found->second[0].first!=123)return false;
    }
    Combat combat(mobs);combat.apply_rush(result);
    if(combat.player.rushed!=(selected>0)
       ||(selected&&combat.player.target!=static_cast<int16_t>((last-1000)*10))){
        std::cerr<<"Rush did not use the last actual target\n";return false;
    }
    return true;
}
}
int main(){
    // Single and partial groups exposed the uninitialized last-target read.
    // Zero targets must not rush; larger groups retain the target cap.
    for(unsigned count:{1u,14u,15u,20u,0u})
        if(!jrc::check(count,15))return 1;
    if(!jrc::check(3,0))return 2;
    // A selected candidate can disappear before damage application; use the
    // first and last monsters that actually supplied damage lines.
    if(!jrc::check(3,15,1003)||!jrc::check(3,15,1001))return 3;
}
'''
        with tempfile.TemporaryDirectory(prefix='maplebench-rush-target-') as directory:
            root = Path(directory)
            (root/'rush.cpp').write_text(harness)
            # Deterministically expose uninitialized endpoint members in the
            # old source; this flag does not change initialized candidate data.
            compiled = subprocess.run([compiler, '-std=c++17', '-O0', '-Wall', '-Wextra',
                                       '-Werror', '-ftrivial-auto-var-init=pattern',
                                       '-I', str(source), str(root/'rush.cpp'),
                                       '-o', str(root/'rush')], capture_output=True,
                                      text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr.strip())
            result = subprocess.run([str(root/'rush')], capture_output=True,
                                    text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr.strip())


if __name__ == '__main__':
    unittest.main()
