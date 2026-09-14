"""Compile the actual ordinary buff handler, packet reader and stat application.

Synthetic packets use the matching Cosmic writer's ordinary ten-byte entries.
No game assets, live server, browser or model are used.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'test/fixtures/client-buff-wire-order'
FIXTURE_MANIFEST_SHA256='abfbf2051b5a1038582009bc754c6d56e8ed9fe9d83482437ddb7a72a4c1d819'


def method(source, signature):
    start=source.index(signature); brace=source.index('{',start);depth=1;end=brace+1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]+'\n'


STATS=r'''
#pragma once
#include "EquipStat.h"
#include "../Template/EnumMap.h"
#include <unordered_map>
namespace jrc {
struct Weapon { enum Type { CLAW }; };
class CharStats {
public:
 EnumMap<Equipstat::Id,int32_t> totalstats,buffdeltas;
 std::unordered_map<Equipstat::Id,float> percentages;
 int speed=4;
 void init_totalstats(){totalstats.clear();buffdeltas.clear();percentages.clear();totalstats[Equipstat::SPEED]=100;totalstats[Equipstat::JUMP]=100;totalstats[Equipstat::WATK]=10;totalstats[Equipstat::WDEF]=70;speed=4;}
 void set_weapontype(Weapon::Type){} void close_totalstats(){}
 int32_t get_total(Equipstat::Id stat)const;
 void set_total(Equipstat::Id stat,int32_t value);
 void add_buff(Equipstat::Id stat,int32_t value);
 void add_value(Equipstat::Id stat,int32_t value){set_total(stat,get_total(stat)+value);}
 void add_percent(Equipstat::Id stat,float percent){percentages[stat]+=percent;}
 void set_stance(float){} void set_attackspeed(int8_t value){speed+=value;}
};
}
'''

HARNESS=r'''
#include <cstdint>
#include <iostream>
#include <map>
#include <vector>
#include <type_traits>
#include "src/client/Character/ActiveBuffs.h"
#include "src/client/Character/StatCaps.h"
#include "src/client/Net/InPacket.h"
namespace jrc {
struct UIStatsinfo {void update_all_stats(){}};
int buff_icon_updates=0;
struct UIBuffList {void add_buff(int32_t,int32_t){++buff_icon_updates;}};
struct UI {static UI& get(){static UI value;return value;}template<class T>T* get_element(){if constexpr(std::is_same<T,UIBuffList>::value){static UIBuffList list;return &list;}else return nullptr;}};
struct Inventory {void recalc_stats(Weapon::Type){}int get_stat(Equipstat::Id)const{return 0;}};
struct Skillbook {std::vector<std::pair<int,int>> collect_passives()const{return {};}};
struct PassiveBuffs {void apply_buff(CharStats&,int,int)const{}};
struct Player {
 CharStats stats;Inventory inventory;Skillbook skillbook;PassiveBuffs passive_buffs;ActiveBuffs active_buffs;
 EnumMap<Buffstat::Id,Buff> buffs;
 Weapon::Type get_weapontype()const{return Weapon::CLAW;}
 void recalc_stats(bool equipchanged);
 void give_buff(Buff buff);void cancel_buff(Buffstat::Id stat);
};
struct Stage {Player player;static Stage& get(){static Stage value;return value;}Player& get_player(){return player;}};
class PacketHandler {public:virtual ~PacketHandler(){}virtual void handle(InPacket&)const=0;};
__DECLARATIONS__
__STAT_METHODS__
__PLAYER_METHODS__
__HANDLER_METHODS__
}
using namespace jrc;
template<class T>void put(std::vector<int8_t>& bytes,T value){using U=typename std::make_unsigned<T>::type;U n=static_cast<U>(value);for(size_t i=0;i<sizeof(T);i++)bytes.push_back(static_cast<int8_t>(n>>(i*8)));}
std::vector<int8_t> packet(uint64_t first,uint64_t second,std::vector<std::pair<int16_t,int32_t>> fields){
 std::vector<int8_t>b;put(b,first);put(b,second);
 for(auto field:fields){put(b,field.first);put(b,field.second);put(b,int32_t(200000));}
 // Exact ordinary giveBuff trailer: int0, byte0, first value(int).
 put(b,int32_t(0));put(b,int8_t(0));put(b,int32_t(fields.empty()?0:fields[0].first));return b;
}
size_t apply(uint64_t first,uint64_t second,std::vector<std::pair<int16_t,int32_t>> fields){auto b=packet(first,second,fields);InPacket recv(b.data(),b.size());ApplyBuffHandler().handle(recv);return recv.length();}
void cancel(uint64_t first,uint64_t second){std::vector<int8_t>b;put(b,first);put(b,second);put(b,int8_t(1));InPacket recv(b.data(),b.size());CancelBuffHandler().handle(recv);if(recv.length()!=1)throw std::runtime_error("cancel consumed values");}
int main(int argc,char**argv){
 if(argc!=2)return 2;std::string mode=argv[1];auto&p=Stage::get().player;p.recalc_stats(false);
 try{
 if(mode=="haste"){
  auto left=apply(0,0x8000000000ULL|0x10000000000ULL,{{40,4101004},{20,4101004}});
  std::cout<<p.stats.get_total(Equipstat::SPEED)<<' '<<p.stats.get_total(Equipstat::JUMP)<<' '<<left<<' ';
  cancel(0,0x8000000000ULL|0x10000000000ULL);std::cout<<p.stats.get_total(Equipstat::SPEED)<<' '<<p.stats.get_total(Equipstat::JUMP);
 }else if(mode=="combo"){
  auto left=apply(0,0x20000000000000ULL,{{1,1111002}});std::cout<<left<<' '<<p.buffs[Buffstat::COMBO].value<<' '<<p.buffs[Buffstat::SUMMON].skillid<<' ';
  apply(0,0x20000000000000ULL,{{6,1111002}});std::cout<<p.buffs[Buffstat::COMBO].value<<' ';
  apply(0,0x20000000000000ULL,{{1,1111002}});std::cout<<p.buffs[Buffstat::COMBO].value<<' ';
  cancel(0,0x20000000000000ULL);std::cout<<p.buffs[Buffstat::COMBO].skillid;
 }else if(mode=="rage"){
  auto left=apply(0,0x100000000ULL|0x200000000ULL,{{20,1101006},{-20,1101006}});
  std::cout<<p.stats.get_total(Equipstat::WATK)<<' '<<p.stats.get_total(Equipstat::WDEF)<<' '<<left;
 }else if(mode=="single"){
  apply(0,0x80000000000ULL,{{-2,4101003}});apply(0,0x100ULL,{{0,4121006}});apply(0,0x20ULL,{{3980,3121002}});
  std::cout<<p.stats.speed<<' '<<p.buffs[Buffstat::SHADOW_CLAW].value<<' '<<p.buffs[Buffstat::SHADOW_CLAW].skillid<<' '<<p.buffs[Buffstat::SHARP_EYES].value;
 }else if(mode=="cross_mask"){
  auto left=apply(0x200000000ULL,0x8000000000ULL,{{40,4101004},{100,2111005}});
  std::cout<<p.buffs[Buffstat::SPEED].value<<' '<<p.buffs[Buffstat::ELEMENTAL_RESET].value<<' '<<left;
 }else if(mode=="other_aliases"){
  auto left=apply(0,0x4000000000ULL|0x800000000000000ULL,{{7,9000001},{60,4211003}});
  std::cout<<left<<' '<<p.buffs[Buffstat::HANDS].value<<' '<<p.buffs[Buffstat::SHOWDASH].skillid<<' '<<p.buffs[Buffstat::PICKPOCKET].value<<' '<<p.buffs[Buffstat::PUPPET].skillid;
 }else if(mode=="cancel_unknown"){
  apply(0,0x8000000000ULL|0x10000000000ULL,{{40,4101004},{20,4101004}});
  cancel(0,1ULL|0x8000000000ULL);
  std::cout<<p.stats.get_total(Equipstat::SPEED)<<' '<<p.stats.get_total(Equipstat::JUMP)<<' '<<p.buffs[Buffstat::SPEED].skillid<<' '<<p.buffs[Buffstat::JUMP].skillid;
 }else if(mode=="truncated_second"||mode=="truncated_second_no_trailer"){
  auto b=packet(0,0x8000000000ULL|0x10000000000ULL,{{40,4101004},{20,4101004}});
  // Delete the final tuple byte, retaining the actual nine-byte trailer.
  b.erase(b.begin()+35);if(mode=="truncated_second_no_trailer")b.resize(35);
  InPacket recv(b.data(),b.size());
  try{ApplyBuffHandler().handle(recv);return 3;}catch(const PacketError&){
   std::cout<<p.buffs[Buffstat::SPEED].skillid<<' '<<p.buffs[Buffstat::JUMP].skillid<<' '<<buff_icon_updates<<' '<<p.stats.get_total(Equipstat::SPEED)<<' '<<p.stats.get_total(Equipstat::JUMP);
  }
 }else if(mode=="unknown"){
  try{apply(0,1ULL|0x8000000000ULL,{{9,9000001},{40,4101004}});return 3;}catch(const PacketError&){std::cout<<p.buffs[Buffstat::SPEED].skillid;}
 }else if(mode=="truncated_value"){
  std::vector<int8_t>b;put(b,uint64_t(0));put(b,uint64_t(0x8000000000ULL));b.resize(25,0);InPacket recv(b.data(),b.size());try{ApplyBuffHandler().handle(recv);return 3;}catch(const PacketError&){std::cout<<p.buffs[Buffstat::SPEED].skillid;}
 }else if(mode=="truncated"){
  std::vector<int8_t>b(15,0);InPacket recv(b.data(),b.size());try{ApplyBuffHandler().handle(recv);return 3;}catch(const PacketError&){std::cout<<p.buffs[Buffstat::SPEED].skillid;}
 }else return 4;
 }catch(const PacketError&){std::cout<<"packet_error";}
 std::cout<<'\n';
}
'''


class BuffWireOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);cls.tree=Path(cls.temp.name)
        if hashlib.sha256((FIXTURE/'SHA256.json').read_bytes()).hexdigest()!=FIXTURE_MANIFEST_SHA256:raise ValueError('source_fixture_manifest_changed')
        for name,expected in json.loads((FIXTURE/'SHA256.json').read_text()).items():
            if hashlib.sha256((FIXTURE/name).read_bytes()).hexdigest()!=expected:raise ValueError('source_fixture_changed:'+name)
        paths={'Buff.h':'Character/Buff.h','Buff.cpp':'Character/Buff.cpp','ActiveBuffs.h':'Character/ActiveBuffs.h',
               'ActiveBuffs.cpp':'Character/ActiveBuffs.cpp','EquipStat.h':'Character/EquipStat.h','EquipStat.cpp':'Character/EquipStat.cpp',
               'StatCaps.h':'Character/StatCaps.h','EnumMap.h':'Template/EnumMap.h','Enumeration.h':'Template/Enumeration.h',
               'InPacket.h':'Net/InPacket.h','InPacket.cpp':'Net/InPacket.cpp','PacketError.h':'Net/PacketError.h','Point.h':'Template/Point.h',
               'PlayerHandlers.cpp':'Net/Handlers/PlayerHandlers.cpp','PlayerHandlers.h':'Net/Handlers/PlayerHandlers.h'}
        for name,path in paths.items():
            dest=cls.tree/'src/client'/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((FIXTURE/name).read_bytes())
        (cls.tree/'src/client/Character/CharStats.h').write_text(STATS)
        (cls.tree/'nlnx').mkdir();(cls.tree/'nlnx/node.hpp').write_text('namespace nl {struct node {int x()const{return 0;}int y()const{return 0;}};}\n')
        before=(FIXTURE/'PlayerHandlers.cpp').read_text()
        subprocess.run(['patch','-p1','--batch','--fuzz=0','-i',str(ROOT/'patches/full-client/0023-ordinary-buff-wire-order.patch')],cwd=cls.tree,check=True,capture_output=True,timeout=10)
        after=(cls.tree/'src/client/Net/Handlers/PlayerHandlers.cpp').read_text()
        before_header=(FIXTURE/'PlayerHandlers.h').read_text();after_header=(cls.tree/'src/client/Net/Handlers/PlayerHandlers.h').read_text()
        stats=(FIXTURE/'CharStats.cpp').read_text();player=(FIXTURE/'Player.cpp').read_text()
        bodies='\n'.join(method(stats,s) for s in ('    int32_t CharStats::get_total','    void CharStats::set_total','    void CharStats::add_buff'))
        players='\n'.join(method(player,s) for s in ('    void Player::recalc_stats','    void Player::give_buff','    void Player::cancel_buff'))
        for name,source,header in [('before',before,before_header),('after',after,after_header)]:
            decl=header[header.index('    class BuffHandler'):header.index('    // Force a stats recalculation.')]
            handlers='\n'.join(method(source,s) for s in ('    void BuffHandler::handle','    void ApplyBuffHandler::handle_buff','    void CancelBuffHandler::handle_buff'))
            harness=HARNESS.replace('__DECLARATIONS__',decl).replace('__STAT_METHODS__',bodies).replace('__PLAYER_METHODS__',players).replace('__HANDLER_METHODS__',handlers)
            path=cls.tree/(name+'.cpp');path.write_text(harness)
            result=subprocess.run([shutil.which('c++'),'-std=c++17','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations','-I',str(cls.tree),str(path),
                str(cls.tree/'src/client/Net/InPacket.cpp'),str(cls.tree/'src/client/Character/Buff.cpp'),
                str(cls.tree/'src/client/Character/ActiveBuffs.cpp'),str(cls.tree/'src/client/Character/EquipStat.cpp'),
                '-o',str(cls.tree/name)],capture_output=True,text=True,timeout=30)
            if result.returncode:raise RuntimeError(result.stderr)

    def probe(self,mode,binary='after'):
        return subprocess.check_output([str(self.tree/binary),mode],timeout=3,text=True).strip()

    def test_haste_wire_values_and_cancel_reach_real_stat_application(self):
        self.assertEqual(self.probe('haste'),'140 120 9 100 100')

    def test_combo_one_payload_alias_and_server_reset(self):
        self.assertEqual(self.probe('combo'),'9 1 0 6 1 0')
        self.assertNotEqual(self.probe('combo','before'),'9 1 0 6 1 0')

    def test_rage_other_multibuff_values_keep_signed_meaning(self):
        self.assertEqual(self.probe('rage'),'30 50 9')

    def test_signed_zero_and_packed_single_buffs_unchanged(self):
        self.assertEqual(self.probe('single'),'2 0 4121006 3980')

    def test_server_declaration_order_across_mask_words(self):
        self.assertEqual(self.probe('cross_mask'),'40 100 9')
        self.assertEqual(self.probe('other_aliases'),'9 7 0 60 0')

    def test_unknown_and_truncated_masks_cannot_reassign_speed(self):
        self.assertEqual(self.probe('unknown'),'0')
        self.assertEqual(self.probe('truncated'),'0')
        self.assertEqual(self.probe('truncated_value'),'0')

    def test_entire_two_value_body_is_checked_before_player_or_ui_mutation(self):
        self.assertEqual(self.probe('truncated_second'),'0 0 0 100 100')
        self.assertEqual(self.probe('truncated_second_no_trailer'),'0 0 0 100 100')

    def test_cancel_keeps_known_bits_when_unknown_bits_are_also_set(self):
        self.assertEqual(self.probe('cancel_unknown'),'100 120 0 4101004')

    def test_packet_bytes_follow_pinned_server_writer_and_skill_loader(self):
        writer=(FIXTURE/'PacketCreator.java').read_text();give=method(writer,'    public static Packet giveBuff(')
        for fragment in ('writeLongMask(p, statups);','for (Pair<BuffStat, Integer> statup : statups)',
                         'p.writeShort(statup.getRight().shortValue());','p.writeInt(buffid);','p.writeInt(bufflength);'):
            self.assertIn(fragment,give)
        effect=(FIXTURE/'StatEffect.java').read_text()
        self.assertLess(effect.index('addBuffStatPairToListIfNotZero(statups, BuffStat.SPEED,'),effect.index('addBuffStatPairToListIfNotZero(statups, BuffStat.JUMP,'))
        enum=(FIXTURE/'BuffStat.java').read_text()
        self.assertIn('SPEED(0x8000000000L)',enum);self.assertIn('JUMP(0x10000000000L)',enum)
        self.assertLess(enum.index('SPEED(0x8000000000L)'),enum.index('ELEMENTAL_RESET(0x200000000L, true)'))


if __name__=='__main__':unittest.main()
