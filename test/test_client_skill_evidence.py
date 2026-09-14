"""Compile the native diagnostic serializer with inert state collaborators.

This verifies observability, not gameplay effects or benchmark admission.
"""
import hashlib
import re
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'test/fixtures/client-skill-evidence'
PATHS = {'Player.h': 'Character/Player.h', 'Stage.cpp': 'Gameplay/Stage.cpp',
         'Buff.h': 'Character/Buff.h', 'EquipStat.h': 'Character/EquipStat.h',
         'Enumeration.h': 'Template/Enumeration.h'}
HARNESS = r'''
#include <cstdint>
#include <map>
#include <iostream>
namespace jrc { namespace Maplestat { enum Id {HP, MP}; } }
#include "src/client/Gameplay/SkillEvidence.h"
namespace jrc {
struct Stats {
    int get_stat(Maplestat::Id key) const { return key==Maplestat::HP ? 500 : 1234; }
    int get_total(Equipstat::Id key) const { return 100 + static_cast<int>(key); }
};
struct Position { int x() const {return -17;} int y() const {return 92;} };
struct Player {
    Stats stats;
    std::map<Buffstat::Id, Buff> received;
    const char* name = "DO_NOT_EXPORT_PLAYER_NAME";
    const Stats& get_stats() const {return stats;}
    Position get_position() const {return {};}
    bool is_dead() const {return false;}
    int8_t get_integer_attackspeed() const {return 6;}
    const auto& get_received_buffs() const {return received;}
};
}
int main(int argc, char** argv) {
    using namespace jrc;
    if(argc!=2) return 2;
    Player player;
    std::string mode=argv[1];
    if(mode=="values") {
        player.received[Buffstat::SHADOW_CLAW]={Buffstat::SHADOW_CLAW,0,4121006,120000};
        player.received[Buffstat::BOOSTER]={Buffstat::BOOSTER,-2,4101003,200000};
        player.received[Buffstat::SHARP_EYES]={Buffstat::SHARP_EYES,3980,3121002,300000};
    } else if(mode=="cancelled") {
        player.received[Buffstat::SHADOW_CLAW]={};
        player.received[Buffstat::BOOSTER]={Buffstat::NONE,2,4101003,200000};
        player.received[Buffstat::SHARP_EYES]={Buffstat::WATK,40,3121002,300000};
        player.received[Buffstat::WDEF]={Buffstat::WDEF,40,0,300000};
    } else if(mode=="full") {
        for(int i=1;i<Buffstat::LENGTH;++i) {
            auto key=static_cast<Buffstat::Id>(i);
            player.received[key]={key,32767,1000000+i,2147483647};
        }
    } else if(mode!="empty") { return 3; }
    // Repeat reads must not mutate state or advance a timer.
    auto first=skill_evidence_json(player,240040511);
    if(first!=skill_evidence_json(player,240040511)) return 4;
    std::cout << first << '\n';
}
'''


class SkillEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('c++')
        if not compiler:
            raise RuntimeError('C++ compiler required for native evidence tests')
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.tree = Path(cls.directory.name)
        pins = json.loads((FIXTURE/'SHA256.json').read_text())
        for name, path in PATHS.items():
            raw = (FIXTURE/name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != pins[name]:
                raise ValueError('changed_source_fixture:'+name)
            dest = cls.tree/'src/client'/path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
        subprocess.run(['patch', '-p1', '--batch', '--fuzz=0', '-i',
                        str(ROOT/'patches/full-client/0019-skill-effect-observation.patch')],
                       cwd=cls.tree, check=True, capture_output=True, timeout=10)
        (cls.tree/'harness.cpp').write_text(HARNESS)
        cls.binary = cls.tree/'probe'
        subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        '-I', str(cls.tree), str(cls.tree/'harness.cpp'), '-o', str(cls.binary)],
                       check=True, capture_output=True, timeout=30)

    def probe(self, mode):
        raw = subprocess.check_output([str(self.binary), mode], timeout=5)
        self.assertLess(len(raw), 16*1024)
        self.assertNotIn(b'DO_NOT_EXPORT_PLAYER_NAME', raw)
        return json.loads(raw)

    def test_empty_state_is_diagnostic_and_contains_actual_totals(self):
        value = self.probe('empty')
        self.assertEqual(value['source'], 'native-client-diagnostic')
        self.assertEqual(value['receivedBuffs'], [])
        self.assertEqual((value['hp'], value['mp'], value['x'], value['y']), (500,1234,-17,92))
        self.assertEqual(value['attackSpeed'], 6)
        self.assertEqual(len(value['totals']), 12)
        self.assertNotIn('qualified', value)
        self.assertNotIn('score', value)

    def test_preserves_zero_signed_and_packed_buff_values(self):
        buffs = {b['skillId']: b for b in self.probe('values')['receivedBuffs']}
        self.assertEqual(buffs[4121006]['value'], 0)
        self.assertEqual(buffs[4101003]['value'], -2)
        self.assertEqual(buffs[3121002]['value'], 3980)
        self.assertEqual(buffs[4121006]['receivedDurationMs'], 120000)
        self.assertNotIn('remainingMs', buffs[4121006])

    def test_cancelled_invalid_or_mismatched_slots_are_omitted(self):
        self.assertEqual(self.probe('cancelled')['receivedBuffs'], [])

    def test_enum_sized_full_buff_state_remains_bounded(self):
        value = self.probe('full')
        self.assertGreater(len(value['receivedBuffs']), 60)
        self.assertLess(len(value['receivedBuffs']), 100)

    def test_inactive_javascript_object_is_one_emscripten_macro_argument(self):
        after = (self.tree/'src/client/Gameplay/Stage.cpp').read_text()
        call = re.search(r'EM_ASM\(\{.*?^ {12}\}\);', after, flags=re.S|re.M).group()
        # Like Emscripten, the first macro argument is stringified JS while
        # subsequent arguments are C++ expressions. A bare object comma must
        # not split JavaScript into those C++ arguments.
        prefix = ('void native_asm_stub(const char*) {}\n'
                  '#define EM_ASM(code, ...) native_asm_stub(#code, ##__VA_ARGS__)\n'
                  'void inactive() {\n')
        probe = self.tree/'macro-probe.cpp'
        probe.write_text(prefix+call+'\n}\n')
        compiler = shutil.which('c++')
        subprocess.run([compiler,'-std=c++17','-fsyntax-only',str(probe)],
                       check=True,capture_output=True,timeout=15)
        broken=call.replace('({schemaVersion:1, ready:false})','{schemaVersion:1, ready:false}')
        self.assertNotEqual(broken,call)
        probe.write_text(prefix+broken+'\n}\n')
        result=subprocess.run([compiler,'-std=c++17','-fsyntax-only',str(probe)],
                              capture_output=True,timeout=15)
        self.assertNotEqual(result.returncode,0)

    def test_existing_agent_observation_stays_separate_and_inactive_state_clears(self):
        before = (FIXTURE/'Stage.cpp').read_text()
        after = (self.tree/'src/client/Gameplay/Stage.cpp').read_text()
        start = '            data << "{\\"ready\\":true'
        end = '            }, json.c_str());'
        def original_observation(source):
            return source[source.index(start):source.index(end)+len(end)]
        self.assertEqual(original_observation(before), original_observation(after))
        self.assertIn('Module.MapleBenchSkillState = ({schemaVersion:1, ready:false})', after)
        self.assertIn('Module.MapleBenchSkillState.capturedAt = Module.MapleBenchObservation.capturedAt', after)


if __name__ == '__main__':
    unittest.main()
