"""Compile real pinned client classification and Combat dispatch with inert I/O."""
import hashlib,shutil,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'test/fixtures/client-attack-flags'
PINS={'SkillData.cpp':'c61ec79f241d23579730ad76f2d42e9be681d262f702105076ad360fa4c55ce9','SkillId.h':'2c463df66f9720e52717371c004cf40acf4a212240bbe0188ee5a1018fa24242','Combat.cpp':'3c4521660455ae9b272dc6643e83b8a30a696df4bb8700021c5d30b31877df52'}
def method(source,signature):
 start=source.index(signature);brace=source.index('{',start);depth=1;i=brace+1
 while depth:
  depth+=(source[i]=='{')-(source[i]=='}');i+=1
 return source[start:i]
class FixtureAttackFlagsTest(unittest.TestCase):
 def test_actual_classification_and_combat_packet_branch(self):
  compiler=shutil.which('c++')
  if not compiler:self.skipTest('C++ compiler required')
  for name,digest in PINS.items():self.assertEqual(hashlib.sha256((FIXTURE/name).read_bytes()).hexdigest(),digest)
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory);dest=p/'src/client/Data/SkillData.cpp';dest.parent.mkdir(parents=True);shutil.copyfile(FIXTURE/'SkillData.cpp',dest)
   subprocess.run(['patch','-p1','--batch','-i',str(ROOT/'patches/full-client/0005-fixture-attack-flags.patch')],cwd=p,check=True,capture_output=True,timeout=5)
   original=(FIXTURE/'SkillData.cpp').read_text();patched=dest.read_text()
   for fixed,source in [(False,original),(True,patched)]:
    declarations=r'''
#include <cstdint>
#include <unordered_map>
#include <cassert>
#include "SkillId.h"
namespace jrc {
struct SkillData { enum {NONE=0,ATTACK=1,RANGED=2}; int flags; bool passive;
 explicit SkillData(int id): flags(flags_of(id)),passive((id%10000)/1000==0) {}
 int32_t flags_of(int32_t) const; bool is_attack() const; };
int attack_packets=0,use_packets=0,targets=0,effects=0;
struct Attack {enum Type {CLOSE,RANGED,MAGIC};Type type=RANGED;};
struct AttackResult {int attacker=0;};
struct Skills {int get_level(int) const {return 30;}};
struct Player {Attack prepare_attack(bool){return {};};void set_afterimage(int){};int get_oid(){return 1;};Skills get_skills(){return {};}};
struct Mobs {AttackResult send_attack(Attack){++targets;return {};}};
struct SpecialMove {int id;SkillData data;explicit SpecialMove(int n):id(n),data(n){};
 bool is_attack()const{return data.is_attack();} bool is_skill()const{return true;} int get_id()const{return id;}
 void apply_useeffects(Player&)const{} void apply_actions(Player&,Attack::Type)const{} void apply_stats(Player&,Attack&)const{}};
struct AttackPacket {explicit AttackPacket(AttackResult){};void dispatch(){++attack_packets;}};
struct UseSkillPacket {UseSkillPacket(int,int){};void dispatch(){++use_packets;}};
struct Combat {Player player;Mobs mobs;void apply_move(const SpecialMove&);
 bool is_teleport_skill(int)const{return false;}bool apply_teleport(const SpecialMove&){return false;}
 void extract_effects(Player&,const SpecialMove&,AttackResult&){++effects;}
 void apply_use_movement(const SpecialMove&){} void apply_result_movement(const SpecialMove&,AttackResult&){} };
'''
    methods='\n'.join([method(source,'int32_t SkillData::flags_of'),method(source,'bool SkillData::is_attack'),method((FIXTURE/'Combat.cpp').read_text(),'void Combat::apply_move')])
    checks=r'''
}
int main(){using namespace jrc;Combat combat;
 for(int id:{3121004,3111004,2221006}){assert(SkillData(id).is_attack()==FIXED);combat.apply_move(SpecialMove(id));}
 assert(attack_packets==(FIXED?3:0));assert(targets==attack_packets);assert(effects==attack_packets);assert(use_packets==(FIXED?0:3));
 for(int id:{3101004,3121002,2001002,2201001}){assert(!SkillData(id).is_attack());combat.apply_move(SpecialMove(id));}
 assert(use_packets==(FIXED?4:7));assert(SkillData(SkillId::BRANDISH).is_attack());
 assert(!SkillData(9999999).is_attack());assert(!SkillData(3120005).is_attack());
}
'''.replace('FIXED','true' if fixed else 'false')
    (p/'test.cpp').write_text(declarations+methods+checks)
    subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(FIXTURE),str(p/'test.cpp'),'-o',str(p/'test')],check=True,capture_output=True,timeout=20)
    subprocess.run([str(p/'test')],check=True,capture_output=True,timeout=5)
