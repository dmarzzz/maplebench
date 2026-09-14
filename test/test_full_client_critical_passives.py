"""Exercise actual native Player -> Skill -> Mob critical damage methods.

Uses the pinned public C++ fixtures from the spell regression. Only asset/stat
storage and RNG are inert; no game assets, server or model request is used.
Critical Shot/Throw prop/damage were independently matched in pinned NX/XML.
Sharp Eyes stacking remains unsupported and is deliberately not fabricated.
"""
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import test_client_spell_damage as spell
import test_client_fixture_attack_flags as flags
from test_client_fixture_attack_flags import method

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'patches/full-client/0010-critical-passives.patch'


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise AssertionError('native fixture stub changed: ' + old[:80])
    return text.replace(old, new)


def declarations(fixed, expression):
    text = spell.STUBS
    text = replace_once(text, 'enum Id {INT,LUK,MAGIC,ACC}', 'enum Id {INT,LUK,MAGIC,ACC,WATK}')
    text = replace_once(text, 'int intelligence=757,luck=123,magic=140,accuracy=1000;',
        'int intelligence=757,luck=123,magic=140,accuracy=1000,weaponattack=100;int strength=0,dexterity=0;')
    text = replace_once(text, 'case Equipstat::MAGIC:return magic;',
        'case Equipstat::WATK:return weaponattack;case Equipstat::MAGIC:return magic;')
    text = replace_once(text, 'double get_mindamage() const {return physical;} double get_maxdamage() const {return physical;}',
        'double get_mindamage() const {return physical+strength+dexterity;} double get_maxdamage() const {return physical+strength+dexterity;}')
    text = replace_once(text,
        'struct Inventory {bool has_projectile() const {return true;}',
        'struct Inventory {bool present=true;bool has_projectile() const {return present;}')
    text = replace_once(text, ' bool amplified=false;',
        ' bool amplified=false;std::map<int,int> learned;')
    text = replace_once(text,
        ' int get_skilllevel(int id) const {return id==2110001?0:id==2210001?(amplified?30:0):30;}',
        ''' int get_skilllevel(int id) const {
 if(id==3000001 || id==4100001) {auto it=learned.find(id);return it==learned.end()?0:it->second;}
 return id==2110001?0:id==2210001?(amplified?30:0):30;
 }''')
    text = replace_once(text, '  float critical=0,ignoredef=0,hrange=1;',
        '  float chance=0,critical=0,ignoredef=0,hrange=1;')
    text = replace_once(text,
        ''' Stats get_stats(int) const {Stats s;if(id==2221007)s.matk=570;
  if(id==1121008){s.matk=0;s.attackcount=2;}if(id==1000){s.matk=0;s.fixdamage=40;}return s;}''',
        ''' Stats get_stats(int level) const {Stats s;if(id==2221007)s.matk=570;
  if(id==3000001){s.matk=0;s.chance=level==1?.12f:.40f;s.damage=level==1?1.05f:2.0f;}
  if(id==4100001){s.matk=0;s.chance=level==1?.21f:.50f;s.damage=level==1?1.13f:2.0f;}
  if(id==3121004 || id==3111006){s.matk=0;s.damage=1;s.bulletcount=id==3111006?4:1;}
  if(id==4121007 || id==4001344){s.matk=0;s.damage=1.5;s.bulletcount=id==4121007?3:2;}
  if(id==3101005){s.matk=0;s.damage=native_damage(id,{{"x",{true,130}}});}
  if(id==1121006){s.matk=0;s.damage=1.3f;}
  if(id==1121008)s.damage=2.6f;
  if(id==1121008){s.matk=0;s.attackcount=2;}if(id==1000){s.matk=0;s.fixdamage=40;}return s;}''')
    text = replace_once(text, ' mutable float last_probability=0;',
        ' mutable float last_probability=0;float draw=.10f;')
    text = replace_once(text, 'return probability>=0.5f;', 'return draw<probability;')
    if fixed:
        text = replace_once(text, 'next_damage(double,double,float,float) const;',
                            'next_damage(double,double,float,float,int32_t,int32_t) const;')
    loader = r'''
#include <map>
#include <string>
struct NumericNode {bool present=false;double value=0;
 double get_real(double fallback=0)const{return present?value:fallback;}};
float native_damage(int id,std::map<std::string,NumericNode> sub){EXPRESSION return damage;}
'''.replace('EXPRESSION', expression)
    return '#include "src/client/Gameplay/Combat/SpellDamagePolicy.h"\n' + loader + text


CHECKS = r'''
}
int main() {using namespace jrc;
 Player p;Mob m;m.avoid=0;m.wdef=0;m.mdef=0;p.stats.physical=100;
 p.weapon=Weapon::BOW;
 #if !CRIT_FIXED
 // Regression witness: learned Critical Shot did not affect native attacks.
 assert(p.prepare_attack(false).critical==.05f);
 p.learned[3000001]=20;auto old=p.prepare_attack(true);Skill{3121004}.apply_stats(p,old);
 assert(old.critical==.05f);
 return 0;
 #else
 auto close=[](double a,double b){return std::abs(a-b)<.00001;};
 auto shot=p.prepare_attack(false);
 assert(shot.type==Attack::RANGED && shot.critical==0 && shot.critical_bonus_percent==0);
 p.learned[3000001]=20;
 shot=p.prepare_attack(false);shot.hitcount=1;
 assert(close(shot.critical,.4) && shot.critical_bonus_percent==100);
 assert(m.calculate_damage(shot)[0]==std::make_pair(200,true));
 // The real native skill producer must preserve the profile and pass all lines.
 auto strafe=p.prepare_attack(true);Skill{3111006}.apply_stats(p,strafe);
 assert(strafe.damagetype==Attack::DMG_WEAPON && strafe.hitcount==4);
 auto lines=m.calculate_damage(strafe);assert(lines.size()==4);
 for(auto line:lines) assert(line==std::make_pair(200,true));
 m.randomizer.draw=.45f;
 for(auto line:m.calculate_damage(strafe)) assert(line==std::make_pair(100,false));
 // Crossbows inherit Critical Shot, but a claw cannot borrow that learned skill.
 p.weapon=Weapon::CROSSBOW;assert(close(p.prepare_attack(false).critical,.4));
 p.weapon=Weapon::CLAW;assert(p.prepare_attack(false).critical==0);
 p.learned[4100001]=30;
 auto triple=p.prepare_attack(true);Skill{4121007}.apply_stats(p,triple);
 assert(close(triple.critical,.5) && triple.hitcount==3);
 for(auto line:m.calculate_damage(triple)) assert(line==std::make_pair(250,true));
 // Low-level WZ damage percentages are used; there is no hardcoded 1.5x.
 p.learned[4100001]=1; m.randomizer.draw=.1f;
 auto low=p.prepare_attack(false);low.hitcount=1;
 assert(close(low.critical,.21) && low.critical_bonus_percent==13);
 assert(m.calculate_damage(low)[0]==std::make_pair(113,true));
 p.weapon=Weapon::BOW;p.learned[3000001]=1;
 low=p.prepare_attack(false);low.hitcount=1;
 assert(close(low.critical,.12) && low.critical_bonus_percent==5);
 assert(m.calculate_damage(low)[0]==std::make_pair(105,true));
 // Current learned state is consulted every attack, without cache/order leaks.
 p.learned.erase(3000001);assert(p.prepare_attack(false).critical==0);
 p.learned[3000001]=20;assert(close(p.prepare_attack(false).critical,.4));
 p.learned.clear();p.learned[4100001]=30;p.learned[3000001]=20;
 assert(close(p.prepare_attack(false).critical,.4));
 p.weapon=Weapon::CLAW;assert(close(p.prepare_attack(false).critical,.5));
 // Actual prepare_attack melee fallback must not produce projectile criticals.
 p.inventory.present=false;
 assert(p.prepare_attack(false).type==Attack::CLOSE && p.prepare_attack(false).critical==0);
 p.inventory.present=true;p.state=Player::PRONE;
 assert(p.prepare_attack(true).type==Attack::CLOSE && p.prepare_attack(true).critical==0);
 p.state=Player::STAND;
 for(auto weapon:{Weapon::SWORD,Weapon::STAFF,Weapon::WAND,Weapon::GUN}) {
  p.weapon=weapon;assert(p.prepare_attack(false).critical==0);
 }
 // Spell and fixed-damage branches never borrow a physical critical profile.
 p.weapon=Weapon::STAFF;auto magic=p.prepare_attack(true);Skill{2221006}.apply_stats(p,magic);
 assert(magic.type==Attack::MAGIC && magic.critical==0);
 magic.critical=1;magic.critical_bonus_percent=100; // defense against a stale producer
 for(auto line:m.calculate_damage(magic)) assert(!line.second);
 p.weapon=Weapon::BOW;auto fixed=p.prepare_attack(true);Skill{1000}.apply_stats(p,fixed);
 assert(fixed.critical>.39 && fixed.damagetype==Attack::DMG_FIXED);
 assert(m.calculate_damage(fixed)[0]==std::make_pair(40,false));

 // Nonzero defense precedes the ordinary skill coefficient, with and without
 // critical. The RNG uses midpoint defense:100-(20*.55)=89 defended base.
 m.wdef=20;p.stats.physical=100;p.weapon=Weapon::BOW;m.randomizer.draw=.1f;
 auto ordinary=p.prepare_attack(false);ordinary.hitcount=1;
 assert(m.calculate_damage(ordinary)[0]==std::make_pair(178,true));
 auto strafe_def=p.prepare_attack(true);Skill{3111006}.apply_stats(p,strafe_def);
 assert(strafe_def.mindamage==100 && strafe_def.weapon_damage_percent==100);
 for(auto line:m.calculate_damage(strafe_def))assert(line==std::make_pair(178,true));
 m.randomizer.draw=.45f;
 for(auto line:m.calculate_damage(strafe_def))assert(line==std::make_pair(89,false));
 p.weapon=Weapon::CLAW;
 auto triple_def=p.prepare_attack(true);Skill{4121007}.apply_stats(p,triple_def);
 assert(triple_def.weapon_damage_percent==150 && triple_def.critical_bonus_percent==100);
 for(auto line:m.calculate_damage(triple_def))assert(line==std::make_pair(222,true));
 // Hero skills have no passive critical. Defense order changes coherently,
 // rather than changing with whether the character learned Critical Shot.
 p.weapon=Weapon::SWORD;
 auto brandish=p.prepare_attack(true);Skill{1121008}.apply_stats(p,brandish);
 assert(brandish.mindamage==100 && brandish.weapon_damage_percent==260 && brandish.critical==0);
 for(auto line:m.calculate_damage(brandish))assert(line==std::make_pair(231,false));
 auto rush=p.prepare_attack(true);Skill{1121006}.apply_stats(p,rush);
 assert(rush.weapon_damage_percent==130);
 for(auto line:m.calculate_damage(rush))assert(line==std::make_pair(115,false));
 auto melee=p.prepare_attack(false);melee.hitcount=1;
 assert(m.calculate_damage(melee)[0]==std::make_pair(89,false));
 // Arrow Bomb's actual patched NX-loader expression resolves absent damage
 // from x130. Its splash range is130, defended119, then a2x critical=238.
 // Separate impact/splash targeting remains outside this formula repair.
 p.weapon=Weapon::BOW;m.randomizer.draw=.1f;
 auto bomb=p.prepare_attack(true);Skill{3101005}.apply_stats(p,bomb);
 assert(bomb.mindamage==130 && bomb.weapon_damage_percent==100);
 for(auto line:m.calculate_damage(bomb))assert(line==std::make_pair(238,true));
 m.randomizer.draw=.45f;
 for(auto line:m.calculate_damage(bomb))assert(line==std::make_pair(119,false));
 // Mage and fixed damage do not inherit either physical coefficient or bonus.
 p.weapon=Weapon::STAFF;m.mdef=700;
 auto spell_attack=p.prepare_attack(true);Skill{2221006}.apply_stats(p,spell_attack);
 assert(m.calculate_damage(spell_attack)[0]==std::make_pair(9335,false));
 spell_attack.weapon_damage_percent=900;spell_attack.critical_bonus_percent=900;
 assert(m.calculate_damage(spell_attack)[0]==std::make_pair(9335,false));
 fixed.weapon_damage_percent=900;fixed.critical_bonus_percent=900;
 assert(m.calculate_damage(fixed)[0]==std::make_pair(40,false));
 // Misses do not become critical hits; existing floor and cap remain unchanged.
 m.randomizer.draw=1;assert(m.next_damage(100,100,0,.5,100,100)==std::make_pair(0,false));
 m.randomizer.draw=0;assert(m.next_damage(0,0,1,0,100,100)==std::make_pair(1,false));
 assert(m.next_damage(600000,600000,1,1,100,100)==std::make_pair(999999,true));
 assert(m.next_damage(100.75,100.75,1,1,100,100)==std::make_pair(201,true));
 #endif
}
'''


CLAW_CHECKS = r'''
}
int main(){using namespace jrc;
 Player p;p.weapon=Weapon::CLAW;p.stats.physical=321;p.stats.luck=400;p.stats.weaponattack=100;
 Mob m;m.avoid=0;m.wdef=20;m.mdef=700;
 // These are actual Player-produced skill inputs; ordinary ranged throws keep
 // their current stat-panel base rather than gaining the special skill range.
 auto basic=p.prepare_attack(false);basic.hitcount=1;
 assert(basic.weaponattack==100 && basic.claw_projectile && basic.mindamage==321);
 assert(m.calculate_damage(basic)[0]==std::make_pair(310,false));
 auto triple=p.prepare_attack(true);Skill{4121007}.apply_stats(p,triple);
 assert(triple.mindamage==1000 && triple.maxdamage==2000 && triple.weapon_damage_percent==150);
 assert(triple.hitcount==3);
 // Defended midpoint1489, coefficient1.5, final truncation2233.
 for(auto line:m.calculate_damage(triple))assert(line==std::make_pair(2233,false));
 auto lucky=p.prepare_attack(true);Skill{4001344}.apply_stats(p,lucky);
 assert(lucky.mindamage==1000 && lucky.maxdamage==2000 && lucky.hitcount==2);
 for(auto line:m.calculate_damage(lucky))assert(line==std::make_pair(2233,false));
 // Critical Throw adds100%, after defense, to the150% skill coefficient.
 p.learned[4100001]=30;
 triple=p.prepare_attack(true);Skill{4121007}.apply_stats(p,triple);
 for(auto line:m.calculate_damage(triple))assert(line==std::make_pair(3722,true));
 // LUK and current WATK (equips/projectile/buffs upstream) independently alter
 // the special range. Other physical range inputs do not.
 p.stats.luck=800;
 auto luk=p.prepare_attack(true);Skill{4121007}.apply_stats(p,luk);
 assert(luk.mindamage==2000 && luk.maxdamage==4000);
 p.stats.weaponattack=150;
 auto watk=p.prepare_attack(true);Skill{4121007}.apply_stats(p,watk);
 assert(watk.weaponattack==150 && watk.mindamage==3000 && watk.maxdamage==6000);
 // The inert Stats storage exposes strength/dexterity through its ordinary
 // range; production prepare_attack/Skill must overwrite that range for TT.
 p.stats.strength=100;p.stats.dexterity=200;
 auto unrelated=p.prepare_attack(true);Skill{4121007}.apply_stats(p,unrelated);
 assert(unrelated.mindamage==watk.mindamage && unrelated.maxdamage==watk.maxdamage);
 auto regular=p.prepare_attack(false);
 assert(regular.mindamage==621 && regular.maxdamage==621);
 p.stats.strength=0;p.stats.dexterity=0;p.stats.physical=9999;
 unrelated=p.prepare_attack(true);Skill{4001344}.apply_stats(p,unrelated);
 assert(unrelated.mindamage==watk.mindamage && unrelated.maxdamage==watk.maxdamage);
 assert(p.prepare_attack(false).mindamage==9999);
 // IDs alone cannot give a non-claw or non-projectile attack the special base.
 p.weapon=Weapon::BOW;
 auto wrong=p.prepare_attack(true);Skill{4121007}.apply_stats(p,wrong);
 assert(!wrong.claw_projectile && wrong.mindamage==9999);
 p.weapon=Weapon::CLAW;p.inventory.present=false;
 auto empty=p.prepare_attack(true);Skill{4121007}.apply_stats(p,empty);
 assert(empty.type==Attack::CLOSE && !empty.claw_projectile && empty.mindamage==999.9);
 p.inventory.present=true;p.state=Player::PRONE;
 auto prone=p.prepare_attack(true);Skill{4001344}.apply_stats(p,prone);
 assert(prone.type==Attack::CLOSE && !prone.claw_projectile && prone.mindamage==999.9);
 p.state=Player::STAND;
 // A different physical skill on a claw preserves the ordinary range.
 auto other=p.prepare_attack(true);Skill{1121008}.apply_stats(p,other);
 assert(other.mindamage==9999 && other.weapon_damage_percent==260);
 // Mage uses its unchanged INT/total-magic branch, even with larger WATK.
 p.weapon=Weapon::STAFF;
 auto magic=p.prepare_attack(true);Skill{2221006}.apply_stats(p,magic);
 assert(!magic.claw_projectile && magic.mindamage==8460 && magic.maxdamage==10980);
 assert(m.calculate_damage(magic)[0]==std::make_pair(9335,false));
 p.stats.weaponattack=999;
 auto magic_watk=p.prepare_attack(true);Skill{2221006}.apply_stats(p,magic_watk);
 assert(magic_watk.mindamage==magic.mindamage && magic_watk.maxdamage==magic.maxdamage);
}
'''


class CriticalPassiveTests(unittest.TestCase):
    def test_actual_native_producer_skill_damage_and_legacy_regression(self):
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler, 'C++ compiler is required for native critical regression')
        for name, sha in spell.PINS.items():
            self.assertEqual(hashlib.sha256((spell.FIXTURE/name).read_bytes()).hexdigest(), sha)
        # Mob.h and CharStats.cpp changes are also in the release patch. The
        # compiler harness supplies their declarations/storage; select only the
        # actual methods/Attack sources copied by the existing spell fixture.
        selected = ''.join(block for block in re.split(r'(?=^--- )', PATCH.read_text(), flags=re.M)
                           if block.startswith('--- a/') and any(
                               block.startswith('--- a/src/client/'+path+'\n') for path in spell.PATHS.values()))
        with tempfile.TemporaryDirectory() as directory:
            for fixed, claw_fixed in ((False,False),(True,False),(True,True)):
                with self.subTest(critical_repair=fixed,claw_repair=claw_fixed):
                    tree = Path(directory)/(str(fixed)+'-'+str(claw_fixed))
                    for name, path in spell.PATHS.items():
                        dest = tree/'src/client'/path
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(spell.FIXTURE/name, dest)
                    target = tree/'src/client/Data/SkillData.cpp'
                    target.parent.mkdir(parents=True)
                    fixture = flags.FIXTURE/'SkillData.cpp'
                    self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(), flags.PINS['SkillData.cpp'])
                    shutil.copyfile(fixture,target)
                    for name in ('0005-fixture-attack-flags.patch','0006-training-toolkit-attack-flags.patch',
                                 '0011-arrow-bomb-power.patch'):
                        subprocess.run(['patch','-p1','--batch','--fuzz=0','-i',
                                        str(ROOT/'patches/full-client'/name)],cwd=tree,check=True,
                                       capture_output=True,timeout=5)
                    expression = re.search(r'float damage = static_cast<float>.*?;', target.read_text(), re.S).group()
                    for name, content in [('magic.patch', (ROOT/'patches/full-client/0008-spell-damage.patch').read_text()),
                                          ('critical.patch', selected if fixed else ''),
                                          ('claw.patch', (ROOT/'patches/full-client/0012-claw-skill-base.patch').read_text() if claw_fixed else '')]:
                        if not content:continue
                        patch = tree/name;patch.write_text(content)
                        applied = subprocess.run(['patch', '-p1', '--batch', '--fuzz=0', '-i', str(patch)],
                                                 cwd=tree, capture_output=True, text=True, timeout=5)
                        self.assertEqual(applied.returncode, 0, applied.stdout+applied.stderr)
                    geometry = tree/'src/client/Template/Rectangle.h'
                    geometry.parent.mkdir(parents=True);geometry.write_text(spell.GEOMETRY)
                    signatures = {
                        'Player.cpp':['Attack Player::prepare_attack'],
                        'Skill.cpp':['void Skill::apply_stats'],
                        'Mob.cpp':['float Mob::calculate_hitchance','double Mob::calculate_mindamage',
                                   'double Mob::calculate_maxdamage',
                                   'std::vector<std::pair<int32_t, bool>> Mob::calculate_damage',
                                   'std::pair<int32_t, bool> Mob::next_damage'],
                    }
                    methods = '\n'.join(method((tree/'src/client'/spell.PATHS[name]).read_text(), sig)
                                        for name,sigs in signatures.items() for sig in sigs)
                    (tree/'test.cpp').write_text(declarations(fixed, expression)+methods+(CLAW_CHECKS if claw_fixed else CHECKS))
                    built = subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror',
                                            '-DCRIT_FIXED='+str(int(fixed)),str(tree/'test.cpp'),'-o',str(tree/'test')],
                                           capture_output=True,text=True,timeout=20)
                    self.assertEqual(built.returncode,0,built.stderr)
                    ran = subprocess.run([str(tree/'test')],capture_output=True,text=True,timeout=5)
                    self.assertEqual(ran.returncode,0,ran.stderr)


if __name__=='__main__':unittest.main()
