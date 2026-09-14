"""Compile the actual framed receiver and crypto; replace only socket/dispatch edges."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'test/fixtures/client-packet-framing'
STUBS = {
    'Journey.h': '#pragma once\n',
    'Error.h': '#pragma once\nnamespace jrc { struct Error { enum Code {NONE,CONNECTION}; Error(Code) {} }; }\n',
    'Template/Singleton.h': '''#pragma once
namespace jrc { template<class T> struct Singleton { virtual ~Singleton() = default;
static T& get() {static T t; return t;} }; }
''',
    'Configuration.h': '''#pragma once
#include <string>
namespace jrc { struct MapleStoryServerIp {}; struct MapleStoryServerPort {};
template<class T> struct Setting {static Setting& get(){static Setting s;return s;}
std::string load() const {return "test.invalid";} }; }
''',
    'Console.h': '''#pragma once
#include <string>
#include <vector>
namespace jrc { struct Console {inline static std::vector<std::string> messages;
static Console& get(){static Console c;return c;}
void print(const std::string& s){messages.push_back(s);} }; }
''',
    'Net/SocketWinsock.h': '''#pragma once
#include <algorithm>
#include <array>
#include <cstring>
#include <deque>
#include <vector>
#include "NetConstants.h"
namespace jrc { class SocketWinsock { public:
inline static std::deque<std::vector<int8_t>> chunks;
inline static int closes=0, opens=0;
int8_t storage[MAX_PACKET_LENGTH]{};
bool open(const char*,const char*) {++opens;std::memset(storage,0,sizeof(storage));
 for(int i=0;i<4;++i){storage[7+i]=11+i;storage[11+i]=21+i;}return true;}
bool close(){++closes;return true;}
const int8_t* get_buffer() const{return storage;}
size_t receive(bool*) {if(chunks.empty())return 0;auto v=chunks.front();chunks.pop_front();
 if(v.size()>sizeof(storage))throw std::runtime_error("mock_chunk_overflow");
 std::memcpy(storage,v.data(),v.size());return v.size();}
void dispatch(const int8_t*,size_t){}
}; }
''',
    'Net/PacketSwitch.h': '''#pragma once
#include <functional>
#include <vector>
#include "PacketError.h"
namespace jrc { struct PacketSwitch {
inline static std::vector<std::vector<int8_t>> received;
inline static std::function<void()> handler;
void forward(const int8_t* p,size_t n){received.emplace_back(p,p+n);if(handler)handler();}
}; }
''',
}
PROGRAM = r'''
#include "src/client/Net/Session.h"
#include "src/client/Console.h"
#include <iostream>
#include <stdexcept>
using namespace jrc;
using Bytes=std::vector<int8_t>;
using Packets=std::vector<Bytes>;
void require(bool ok,const char* msg){if(!ok)throw std::runtime_error(msg);}
void reset(){SocketWinsock::chunks.clear();SocketWinsock::closes=0;SocketWinsock::opens=0;
 PacketSwitch::received.clear();PacketSwitch::handler=nullptr;Console::messages.clear();}
Bytes payload(size_t n,int seed=0){Bytes b(n);for(size_t i=0;i<n;++i)b[i]=int8_t((i*73+seed)%256);return b;}
Cryptography sender(){int8_t h[16]{};for(int i=0;i<4;++i){h[7+i]=21+i;h[11+i]=11+i;}return Cryptography(h);}
Bytes wire(const Packets& packets){auto crypto=sender();Bytes out;
 for(auto b:packets){int8_t h[HEADER_LENGTH];crypto.create_header(h,b.size());
  crypto.encrypt(b.data(),b.size());out.insert(out.end(),h,h+HEADER_LENGTH);out.insert(out.end(),b.begin(),b.end());}
 return out;}
void feed(Session& s,const Bytes& bytes,size_t chunk){
 for(size_t i=0;i<bytes.size();i+=chunk){size_t end=std::min(i+chunk,bytes.size());
  SocketWinsock::chunks.emplace_back(bytes.begin()+i,bytes.begin()+end);s.read();}
}
void split_case(const Packets& expected,const Bytes& bytes,size_t split){
 reset();Session s;s.init();
 feed(s,Bytes(bytes.begin(),bytes.begin()+split),MAX_PACKET_LENGTH);
 SocketWinsock::chunks.push_back({});s.read(); // an empty read must preserve partial state
 feed(s,Bytes(bytes.begin()+split,bytes.end()),MAX_PACKET_LENGTH);
 require(PacketSwitch::received==expected,"split stream bytes lost, duplicated or reordered");
 require(s.is_connected(),"valid split disconnected");}
int main(int argc,char** argv){try{
 require(argc==2,"case required");std::string mode=argv[1];
 Packets expected={payload(2,236),payload(17,238),payload(31,125)};Bytes bytes=wire(expected);
 if(mode=="original") {reset();Session s;s.init();auto small=wire({payload(2)});
  feed(s,Bytes(small.begin(),small.begin()+4),4);feed(s,Bytes(small.begin()+4,small.end()),2);
  require(PacketSwitch::received.empty(),"original failure no longer reproduced");}
 else if(mode=="splits") {
  for(size_t i=0;i<=bytes.size();++i)split_case(expected,bytes,i);
  reset();Session s;s.init();feed(s,bytes,1);require(PacketSwitch::received==expected,"byte-at-a-time failed");
  // Every pair of boundaries exercises a split header/body and a coalesced suffix.
  for(size_t i=1;i<bytes.size();++i)for(size_t j=i;j<bytes.size();++j){
   reset();Session t;t.init();feed(t,Bytes(bytes.begin(),bytes.begin()+i),MAX_PACKET_LENGTH);
   feed(t,Bytes(bytes.begin()+i,bytes.begin()+j),MAX_PACKET_LENGTH);
   feed(t,Bytes(bytes.begin()+j,bytes.end()),MAX_PACKET_LENGTH);
   require(PacketSwitch::received==expected,"three-fragment stream mismatch");}
 }
 else if(mode=="coalesced") {Packets many(15000,payload(2));bytes=wire(many);
  reset();Session s;s.init();feed(s,bytes,MAX_PACKET_LENGTH);require(PacketSwitch::received==many,"coalesced mismatch");}
 else if(mode=="bounds") {
#ifdef JOURNEY_USE_CRYPTO
  expected={payload(32768,1),payload(65535,2),payload(2,3)};
#else
  expected={payload(MAX_PACKET_LENGTH,1),payload(2,3)};
#endif
  bytes=wire(expected);split_case(expected,bytes,4);reset();Session s;s.init();feed(s,bytes,4093);
  require(PacketSwitch::received==expected,"maximum payload mismatch");
  require(sizeof(Session)<MAX_PACKET_LENGTH*3,"receiver storage grew beyond fixed buffers");
 }
 else if(mode=="faults") {
  std::vector<size_t> bad={0,1};
#ifndef JOURNEY_USE_CRYPTO
  bad.push_back(MAX_PACKET_LENGTH+1);bad.push_back(0x7fffffff);
#endif
  for(auto length:bad){reset();Session s;s.init();auto c=sender();Bytes h(4);c.create_header(h.data(),length);
   feed(s,h,1);require(!s.is_connected(),"invalid length not rejected at header");
   require(SocketWinsock::closes==1 && PacketSwitch::received.empty(),"invalid frame dispatched");
   require(Console::messages.back()=="Invalid packet payload length","missing framing error");
   feed(s,bytes,1);require(PacketSwitch::received.empty(),"bytes accepted after framing fault");}
 }
 else if(mode=="reconnect") {
  for(size_t cut: {size_t(1),size_t(4),size_t(5)}){
   reset();Session s;s.init();auto incomplete=wire({payload(20)});
   feed(s,Bytes(incomplete.begin(),incomplete.begin()+cut),MAX_PACKET_LENGTH);
   s.reconnect("remote.invalid","8484");feed(s,bytes,1);
   require(PacketSwitch::received==expected,"partial frame leaked across reconnect");}
  reset();Session s;s.init();int callbacks=0;
  PacketSwitch::handler=[&](){if(++callbacks==1)s.reconnect("remote.invalid","8484");};
  feed(s,bytes,MAX_PACKET_LENGTH);require(PacketSwitch::received==Packets{expected.front()},"old coalesced socket tail crossed reconnect");
  PacketSwitch::handler=nullptr;feed(s,wire({expected.back()}),1);
  require(PacketSwitch::received==Packets{expected.front(),expected.back()},"new socket IV/frame failed");
 }
 else if(mode=="handler_error") {reset();Session s;s.init();int count=0;
  PacketSwitch::handler=[&](){if(++count==1)throw PacketError("synthetic bounded handler error");};
  feed(s,bytes,MAX_PACKET_LENGTH);require(PacketSwitch::received==expected,"handler error lost next packet");}
 else if(mode=="unsigned_header") {auto c=sender();int8_t h[4];c.create_header(h,32768);
  require(c.check_length(h)==32768,"encrypted header length sign extended");}
 else throw std::runtime_error("unknown case");
 std::cout<<mode<<" passed\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
'''


@unittest.skipUnless(shutil.which('c++') and shutil.which('patch'), 'C++ compiler and patch required')
class PacketFramingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.binaries = {}
        hashes = json.loads((FIXTURE / 'SHA256.json').read_text())
        for name, digest in hashes.items():
            assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == digest, name
        for patched, crypto in ((False, False), (True, False), (True, True)):
            tree = Path(cls.temp.name) / f'{patched}-{crypto}'
            net = tree / 'src/client/Net'; net.mkdir(parents=True)
            for name in hashes:
                shutil.copyfile(FIXTURE / name, net / name)
            for name, content in STUBS.items():
                path = tree / 'src/client' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            (tree / 'harness.cpp').write_text(PROGRAM)
            if patched:
                subprocess.run(['patch', '-p1', '--batch', '--fuzz=0', '-i',
                    str(ROOT / 'patches/full-client/0015-split-packet-framing.patch')],
                    cwd=tree, check=True, capture_output=True, timeout=5)
            binary = tree / 'framing'
            command = ['c++', '-std=c++17', '-O1', '-Wall', '-Wextra',
                '-Wno-unused-parameter', '-Wno-sign-compare']
            if crypto:
                command += ['-DJOURNEY_USE_CRYPTO']
            command += [str(tree / 'harness.cpp'), str(net / 'Session.cpp'),
                        str(net / 'Cryptography.cpp'), '-o', str(binary)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=25)
            if result.returncode:
                raise RuntimeError(result.stderr)
            cls.binaries[patched, crypto] = binary

    def run_case(self, name, *, patched=True, crypto=False):
        result = subprocess.run([str(self.binaries[patched, crypto]), name],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_original_drops_split_four_byte_header_and_two_byte_payload(self):
        self.run_case('original', patched=False)

    def test_all_single_and_double_splits_and_one_byte_reads(self):
        for crypto in (False, True):
            with self.subTest(crypto=crypto): self.run_case('splits', crypto=crypto)

    def test_coalesced_packets_are_iterative_exact_once(self):
        for crypto in (False, True): self.run_case('coalesced', crypto=crypto)

    def test_fixed_capacity_and_encrypted_high_bit_lengths(self):
        for crypto in (False, True): self.run_case('bounds', crypto=crypto)
        self.run_case('unsigned_header', crypto=True)

    def test_invalid_lengths_close_before_copy_or_dispatch(self):
        for crypto in (False, True): self.run_case('faults', crypto=crypto)

    def test_reconnect_resets_partial_frames_and_discards_old_socket_tail(self):
        for crypto in (False, True): self.run_case('reconnect', crypto=crypto)

    def test_packet_handler_error_preserves_next_frame(self):
        for crypto in (False, True): self.run_case('handler_error', crypto=crypto)


if __name__ == '__main__':
    unittest.main()
