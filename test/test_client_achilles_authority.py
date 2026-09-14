"""Compile the real passive/contact/wire path; no server or game is started."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'test/fixtures/client-achilles'


def body(source,signature):
    start=source.index(signature);brace=source.index('{',start);end=brace+1;depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]


DECLARATIONS=r'''
#include <cassert>
#include <cmath>
#include <cstdint>
#include <vector>
namespace nl { struct node {
    float value;
    node operator[](const char*) const {return *this;}
    explicit operator float() const {return value;}
}; }
namespace jrc {
template<class T> struct Point { T value; T x() const{return value;} };
struct Attack {enum Type{CLOSE};};
struct Equipstat {enum Id{WDEF};};
struct CharStats {
    float reducedamage=0;
    mutable int base_reads=0;
    int get_total(Equipstat::Id) const {
        // A distinct second value detects a second base calculation, including
        // a future RNG-backed defense source. The current formula has no RNG.
        return ++base_reads==1?20:100;
    }
    float get_stance() const{return 0;}
    void set_reducedamage(float);
    float get_reducedamage() const;
    int32_t calculate_damage(int32_t) const;
#if FIXED
    int32_t calculate_damage_before_passives(int32_t) const;
    int32_t mitigate_damage(int32_t) const;
#endif
};
struct AchillesBuff {void apply_to(CharStats&,nl::node) const;};
struct OutPacket {
    enum Opcode{TAKE_DAMAGE=48};
    std::vector<uint8_t> bytes;
    explicit OutPacket(Opcode code){bytes.push_back(code);bytes.push_back(0);}
    void write_byte(int8_t value){bytes.push_back(static_cast<uint8_t>(value));}
    void write_int(int32_t value){for(int i=0;i<4;i++)bytes.push_back((static_cast<uint32_t>(value)>>(i*8))&255);}
    void write_time(){write_int(0x12345678);}
};
'''

PLAYER=r'''
struct Player {
    enum State{STANDING,DIED};
    CharStats stats;
    int shown=-1;
    State state=STANDING;
    bool ladder=false;
    struct Physics {double hspeed=0,vforce=0;int get_x() const{return 0;}} phobj;
    struct Random {int calls=0;bool above(float){++calls;return true;}} randomizer;
    void show_damage(int damage){shown=damage;}
    MobAttackResult damage(const MobAttack&);
};
'''

CHECKS=r'''
}
int wire_damage(const jrc::TakeDamagePacket& packet) {
    assert(packet.bytes.size()==21);
    assert(packet.bytes[0]==48 && packet.bytes[6]==255 && packet.bytes[7]==0);
    uint32_t value=0;for(int i=0;i<4;i++)value|=uint32_t(packet.bytes[8+i])<<(8*i);
    return static_cast<int32_t>(value);
}
// This is the matched server's compound assignment, with Java int truncation.
// The pinned handler test also verifies its position before persisted HP loss.
int server_achilles(int damage,int x){return static_cast<int>(damage*(x/1000.0));}
int main(int argc,char**) {
    using namespace jrc;
    AchillesBuff buff;
    MobAttack attack(2000,Point<int16_t>{100},8190003,77);
    if(argc==1){
        Player player;
        auto result=player.damage(attack);TakeDamagePacket packet(result,TakeDamagePacket::TOUCH);
        assert(player.stats.base_reads==1 && player.randomizer.calls==1);
        assert(player.shown==1100 && result.damage==1100 && wire_damage(packet)==1100);
        assert(result.mobid==8190003 && result.oid==77 && result.direction==0);
        assert(player.phobj.hspeed==-1.5 && player.phobj.vforce==-3.5);
        return 0;
    }
    for(int level=1;level<=30;level++) {
        Player player;int x=1000-level*5;
        buff.apply_to(player.stats,nl::node{static_cast<float>(x)});
        auto result=player.damage(attack);TakeDamagePacket packet(result,TakeDamagePacket::TOUCH);
        assert(player.stats.base_reads==1 && player.randomizer.calls==1);
        const int base=1100;
#if FIXED
        assert(std::abs(player.stats.get_reducedamage()-level*.005f)<1e-6f);
        assert(wire_damage(packet)==base);
        int persisted_loss=server_achilles(wire_damage(packet),x);
        assert(persisted_loss==static_cast<int>(base*x/1000.0));
        assert(player.shown==persisted_loss);
        if(level==30){assert(persisted_loss==935);assert(persisted_loss!=794);}
#else
        assert(std::abs(player.stats.get_reducedamage()-x/1000.0f)<1e-6f);
        assert(wire_damage(packet)==player.shown);
        assert(server_achilles(wire_damage(packet),x)<base/5);
#endif
    }
    // A stat rebuild/removal restores zero reduction; it must not retain the
    // previously learned passive. Existing init_totalstats owns this reset.
    Player removed;buff.apply_to(removed.stats,nl::node{850});removed.stats.set_reducedamage(0);
    auto normal=removed.damage(attack);assert(normal.damage==1100 && removed.shown==1100);
    Player corpse;corpse.state=Player::DIED;
    corpse.damage(attack);assert(corpse.randomizer.calls==0 && corpse.stats.base_reads==1);
    Player on_ladder;on_ladder.ladder=true;
    on_ladder.damage(attack);assert(on_ladder.randomizer.calls==0 && on_ladder.stats.base_reads==1);
    // Zero attack has no knockback/RNG while preserving a zero wire miss.
    Player miss;attack.watk=0;auto zero=miss.damage(attack);
    assert(zero.damage==0 && miss.shown==0 && miss.randomizer.calls==0 && miss.stats.base_reads==1);
#if FIXED
    // Non-divisible bases must truncate the remaining amount, not the removed
    // amount:101*850/1000=85. Server-owned mitigation must still happen once.
    CharStats fraction;buff.apply_to(fraction,nl::node{850});
    assert(fraction.mitigate_damage(101)==85);
    for(int level=1;level<=30;level++){
        int x=1000-5*level;buff.apply_to(fraction,nl::node{static_cast<float>(x)});
        for(int base:{0,1,2,7,99,101,999,1100,2150,12000,99999})
            assert(fraction.mitigate_damage(base)==server_achilles(base,x));
    }
#endif
    return 0;
}
'''


class AchillesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw=(FIXTURE/'sha256.json').read_bytes()
        # This pins original source inputs, not a replaceable expected behavior.
        if hashlib.sha256(raw).hexdigest()!='0d9f70080c7f97a97ab5e57a7e6534dc2d7d9eaf628d18b1386f893787866d79':
            raise AssertionError('fixture manifest changed')
        expected=json.loads(raw)
        for path,digest in expected.items():
            if hashlib.sha256((FIXTURE/path).read_bytes()).hexdigest()!=digest:raise AssertionError(path)
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.directory=Path(cls.temp.name)
        compiler=shutil.which('clang++') or shutil.which('c++')
        if not compiler:raise unittest.SkipTest('C++17 compiler required')
        cls.binaries=[]
        for fixed in (0,1):
            root=cls.directory/str(fixed);shutil.copytree(FIXTURE,root)
            if fixed:
                applied=subprocess.run(['patch','--batch','--fuzz=0','-p3','-i',str(ROOT/'patches/full-client/0022-achilles-authority.patch')],cwd=root,text=True,capture_output=True,timeout=10)
                if applied.returncode:raise AssertionError(applied.stdout+applied.stderr)
            stats=(root/'Character/CharStats.cpp').read_text();passives=(root/'Character/PassiveBuffs.cpp').read_text()
            attack=(root/'Gameplay/Combat/Attack.h').read_text();packets=(root/'Net/Packets/AttackAndSkillPackets.h').read_text()
            source=DECLARATIONS+body(attack,'struct MobAttack\n')+';\n'+body(attack,'struct MobAttackResult\n')+';\n'+PLAYER
            source+=body(packets,'class TakeDamagePacket :')+';\n'
            source+=body(passives,'void AchillesBuff::apply_to')+'\n'
            for signature in ('void CharStats::set_reducedamage','float CharStats::get_reducedamage','int32_t CharStats::calculate_damage('):
                source+=body(stats,signature)+'\n'
            if fixed:
                for signature in ('int32_t CharStats::calculate_damage_before_passives','int32_t CharStats::mitigate_damage'):
                    source+=body(stats,signature)+'\n'
            source+=body((root/'Character/Player.cpp').read_text(),'MobAttackResult Player::damage')+'\n'+CHECKS
            path=root/'check.cpp';path.write_text(source);binary=root/'check'
            compiled=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror',f'-DFIXED={fixed}',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=20)
            if compiled.returncode:raise AssertionError(compiled.stdout+compiled.stderr)
            cls.binaries.append(binary)

    def test_ordinary_contact_and_wire_without_passive_are_unchanged(self):
        for binary in self.binaries:subprocess.run([str(binary)],check=True,capture_output=True,timeout=5)

    def test_all_levels_send_one_base_and_only_server_applies_passive_to_hp(self):
        for binary in self.binaries:subprocess.run([str(binary),'all-levels'],check=True,capture_output=True,timeout=5)

    def test_actual_server_orders_other_mitigation_around_one_achilles_factor(self):
        server=(FIXTURE/'server/TakeDamageHandler.java').read_text()
        factor='damage *= (achilles1.getEffect(achilles).getX() / 1000.0);'
        self.assertEqual(server.count(factor),1)
        self.assertLess(server.index('damage = p.readInt();'),server.index(factor))
        self.assertLess(server.index('chr.getBuffedValue(BuffStat.POWERGUARD)'),server.index(factor))
        self.assertLess(server.index(factor),server.index('chr.getBuffedValue(BuffStat.MAGIC_GUARD)'))
        self.assertLess(server.index(factor),server.index('chr.addMPHP(-damage, -mpattack);'))
        source=(FIXTURE/'Character/CharStats.cpp').read_text()
        self.assertIn('reducedamage = 0.0f;',body(source,'void CharStats::init_totalstats'))
        passive=(FIXTURE/'Character/PassiveBuffs.cpp').read_text()
        self.assertIn('buffs[SkillId::ACHILLES_HERO] = std::make_unique<AchillesBuff>();',passive)


if __name__=='__main__':unittest.main()
