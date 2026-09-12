"""Compile the actual patched packet serializer against a bounded in-memory sink.

The test fixture is the unmodified upstream AGPL header. No game, network,
server, WASM build or invented model result is involved.
"""
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'test/fixtures/full-client/AttackAndSkillPackets.h'
FIXTURE_SHA = '2870c20586e49454a63ff7e70c7e3d084cd77cb6bd2ebe6e7ed6eca979014c4e'
EXTENDED = (3121004, 3221001, 5221004, 13111002)

OUT_PACKET = r'''
#pragma once
#include <cstdint>
#include <vector>
namespace jrc {
class OutPacket {
 public:
 enum Opcode {CLOSE_ATTACK=44,RANGED_ATTACK=45,MAGIC_ATTACK=46,TAKE_DAMAGE=48,USE_SKILL=91};
 std::vector<uint8_t> bytes;
 explicit OutPacket(Opcode opcode) {write_byte(opcode);write_byte(0);}
 void write_byte(uint8_t value) {bytes.push_back(value);}
 void write_int(int32_t value) {for(int i=0;i<4;i++)write_byte(static_cast<uint32_t>(value)>>(i*8));}
 void skip(int count) {for(int i=0;i<count;i++)write_byte(0);}
 void write_time() {write_int(0);}
};
}
'''
ATTACK = r'''
#pragma once
#include <cstdint>
#include <map>
#include <vector>
#include <utility>
namespace jrc {
struct Attack {enum Type {CLOSE,RANGED,MAGIC};};
struct AttackResult {
 Attack::Type type; uint8_t mobcount,hitcount,display,toleft,stance,speed;
 int32_t skill,charge;
 std::map<int32_t,std::vector<std::pair<int32_t,bool>>> damagelines;
};
struct MobAttackResult {int32_t damage,mobid,oid;uint8_t direction;};
}
'''
PROGRAM = r'''
#include "src/client/Net/Packets/AttackAndSkillPackets.h"
#include <iostream>
#include <string>
int main(int argc,char** argv) {
 if(argc!=4)return 2;
 jrc::AttackResult attack{};
 const std::string type=argv[1];
 attack.type=type=="ranged"?jrc::Attack::RANGED:type=="close"?jrc::Attack::CLOSE:jrc::Attack::MAGIC;
 attack.skill=std::stoi(argv[2]);attack.mobcount=static_cast<uint8_t>(std::stoi(argv[3]));
 attack.hitcount=2;attack.display=0x45;attack.toleft=1;attack.stance=0x11;attack.speed=6;
 for(int i=0;i<attack.mobcount;i++)attack.damagelines[0x11223344+i]={{12345+i,false},{23456+i,true}};
 jrc::AttackPacket packet(attack);
 std::cout.write(reinterpret_cast<const char*>(packet.bytes.data()),packet.bytes.size());
}
'''


class ServerReader:
    """The active Cosmic parseDamage header/target reads, independently ordered."""
    def __init__(self, raw):
        self.raw, self.offset = raw, 0

    def take(self, count):
        if self.offset+count > len(self.raw): raise ValueError('packet_underflow')
        result=self.raw[self.offset:self.offset+count];self.offset+=count;return result

    def byte(self): return self.take(1)[0]
    def integer(self): return struct.unpack('<i',self.take(4))[0]

    def header(self, ranged):
        self.take(2)  # opcode was dispatched before parseDamage
        self.byte(); packed=self.byte(); skill=self.integer()
        self.take(8);display=self.byte();direction=self.byte();stance=self.byte()
        self.byte();speed=self.byte()
        if ranged:
            self.byte();rangedirection=self.byte();self.take(7)
            if skill in EXTENDED:self.take(4)
        else:
            rangedirection=None;self.take(4)
        return {'skill':skill,'targets':packed>>4,'hits':packed&15,'display':display,
                'direction':direction,'stance':stance,'speed':speed,'rangedirection':rangedirection}

    def targets(self, header):
        result=[]
        for _ in range(header['targets']):
            oid=self.integer();self.take(4);self.take(4);self.take(4);self.take(2)
            hits=[self.integer() for _ in range(header['hits'])]
            self.take(4)
            result.append((oid,hits))
        return result


@unittest.skipUnless(shutil.which('c++') and shutil.which('patch'), 'C++ compiler and patch required')
class RangedHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.folder=Path(cls.temp.name)
        assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest()==FIXTURE_SHA
        cls.executables={}
        for patched in (False,True):
            tree=cls.folder/('patched' if patched else 'original')
            header=tree/'src/client/Net/Packets/AttackAndSkillPackets.h';header.parent.mkdir(parents=True)
            shutil.copyfile(FIXTURE,header)
            (tree/'src/client/Net/OutPacket.h').write_text(OUT_PACKET)
            attack=tree/'src/client/Gameplay/Combat/Attack.h';attack.parent.mkdir(parents=True);attack.write_text(ATTACK)
            (tree/'packet.cpp').write_text(PROGRAM)
            if patched:
                subprocess.run([shutil.which('patch'),'-p1','--batch','--fuzz=0','-i',
                    str(ROOT/'patches/full-client/0004-ranged-header-padding.patch')],cwd=tree,
                    check=True,capture_output=True,timeout=5)
            binary=tree/'packet'
            subprocess.run([shutil.which('c++'),'-std=c++11','-Wall','-Wextra','-Werror','-O0',
                str(tree/'packet.cpp'),'-o',str(binary)],check=True,capture_output=True,timeout=20)
            cls.executables[patched]=binary

    def packet(self, skill, count=1, *, patched=True, kind='ranged'):
        return subprocess.check_output([str(self.executables[patched]),kind,str(skill),str(count)],timeout=5)

    def test_original_hurricane_header_loses_target_identity(self):
        reader=ServerReader(self.packet(3121004,patched=False));reader.header(True)
        self.assertNotEqual(reader.integer(),0x11223344)
        with self.assertRaisesRegex(ValueError,'underflow'):
            ServerReader(self.packet(3121004,0,patched=False)).header(True)

    def test_all_four_skill_headers_align_first_target_and_damage(self):
        for skill in EXTENDED:
            with self.subTest(skill=skill):
                reader=ServerReader(self.packet(skill));header=reader.header(True)
                self.assertEqual(reader.offset,34)  # opcode2 + extended body32
                self.assertEqual(header,{'skill':skill,'targets':1,'hits':2,'display':0x45,
                    'direction':1,'stance':0x11,'speed':6,'rangedirection':1})
                self.assertEqual(reader.integer(),0x11223344)
                reader.take(14)
                self.assertEqual([reader.integer(),reader.integer()],[12345,23456])

    def test_hurricane_multiple_targets_round_trip_the_server_layout(self):
        reader=ServerReader(self.packet(3121004,2));header=reader.header(True)
        self.assertEqual(reader.targets(header),[(0x11223344,[12345,23456]),(0x11223345,[12346,23457])])
        self.assertEqual(reader.offset,len(reader.raw))

    def test_empty_special_attack_still_contains_the_complete_header(self):
        for skill in EXTENDED:
            with self.subTest(skill=skill):
                reader=ServerReader(self.packet(skill,0));self.assertEqual(reader.header(True)['targets'],0)
                self.assertEqual(reader.offset,len(reader.raw));self.assertEqual(len(reader.raw),34)

    def test_regular_and_unrelated_ranged_packets_are_byte_identical(self):
        for skill in (0,3111004,3211004,4121007,3121003,3121005,13111001,13111003):
            with self.subTest(skill=skill):
                self.assertEqual(self.packet(skill,2),self.packet(skill,2,patched=False))
                reader=ServerReader(self.packet(skill,2));header=reader.header(True)
                self.assertEqual(reader.offset,30)
                self.assertEqual(reader.targets(header),[(0x11223344,[12345,23456]),(0x11223345,[12346,23457])])

    def test_nonranged_packets_are_byte_identical_even_for_the_same_ids(self):
        for kind in ('close','magic'):
            for skill in (0,*EXTENDED):
                with self.subTest(kind=kind,skill=skill):
                    self.assertEqual(self.packet(skill,2,kind=kind),self.packet(skill,2,patched=False,kind=kind))


if __name__=='__main__':unittest.main()
