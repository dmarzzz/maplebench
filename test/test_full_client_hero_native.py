"""Hero toolkit native contract/evidence tests; no game, DB, build, or API."""
import copy
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))

from full_client_hero_native_evidence import TASK_ID, verify_events
from full_client_hero_toolkit import toolkit
from full_client_native import (HERO_TOOLKIT_PROTOCOL, contract, program,
                                validate_contract)


class Ledger:
    def __init__(self, native):
        self.native = native
        self.rows = []
        self.previous = '0'*64
        self.identity = {'schema_version':1,'source':'cosmic_native_skill_ledger',
            'run_id':'b'*32,'server_instance_id':'c'*32,'character_id':5,
            'account_id':2,'task_id':TASK_ID,
            'binding_sha256':__import__('full_client_native').fingerprint(native),
            'runtime_sha256':'d'*64}
        self.start_ns = 1000000000
        self.start_wall = 2000000000000

    def add(self, kind, data):
        sequence = len(self.rows)
        elapsed = sequence * 1000000
        row = dict(self.identity, kind=kind, sequence=sequence,
                   event_id=f'e{sequence:08d}', elapsed_ns=elapsed,
                   wall_ms=self.start_wall + sequence,
                   previous_sha256=self.previous, data=data)
        raw = (json.dumps(row, sort_keys=True, separators=(',', ':'))+'\n').encode()
        self.previous = hashlib.sha256(raw).hexdigest()
        self.rows.append(raw)
        return row['event_id']

    def bytes(self):
        return b''.join(self.rows)

    def expected(self):
        raw = self.bytes()
        return {'run_id':'b'*32,'server_instance_id':'c'*32,
            'character_id':5,'account_id':2,'runtime_sha256':'d'*64,
            'ledger_sha256':hashlib.sha256(raw).hexdigest(),
            'start_monotonic_ns':self.start_ns,
            'start_wall_ms':self.start_wall,'duration_ns':120000000000}


def actor(*, hp=12000, mp=6000, combo=0, buffs=None, stats=None):
    return {'job':112,'level':180,'map_id':240040511,'hp':hp,'mp':mp,
        'max_hp':12000,'max_mp':6000,'x':0,'y':0,'combo_orbs':combo,
        'active_buffs':[] if buffs is None else copy.deepcopy(buffs),
        'stats':{'str':900,'dex':100,'weapon_attack':100,'weapon_defense':500}
            if stats is None else copy.deepcopy(stats),
        'alive':hp>0,'online':True,'snapshot_atomic':False}


def native_ledger(*, rebuild_before_panic=True, first_build_damage=True,
                  first_build_mp_cost=10, combo_before_finishers=True):
    native = contract('hero', 'a'*64, protocol=HERO_TOOLKIT_PROTOCOL)
    ledger = Ledger(native)
    state = actor()
    ledger.add('header', {'start_monotonic_ns':ledger.start_ns,
        'deadline_elapsed_ns':120000000000,'movement_physics_validated':False,
        'teleport_causal_link_supported':False,
        'coverage_source':'ordinary_hero_skill_handlers',
        'resource_coverage':'apply_hp_mp_change_only',
        'inventory_coverage':'not_collected','initial':copy.deepcopy(state)})

    levels = {skill['skill_id']:skill['level'] for skill in toolkit()['skills']}

    def invoke(skill, route, *, buff_value=None, hp_cost=0, mp_cost=10,
               damage=False, combo_after=None, stat_change=None):
        nonlocal state
        before = copy.deepcopy(state)
        transaction = ledger.add('transaction_begin', {
            'transaction_kind':'skill_apply',
            'subject_id':skill,'skill_level':levels[skill],
            'parent_transaction_id':''})
        resource = ledger.add('resource_transaction', {
            'transaction_id':transaction,'hp_before':before['hp'],
            'mp_before':before['mp'],'hp_after':before['hp']-hp_cost,
            'mp_after':before['mp']-mp_cost,'max_hp':12000,'max_mp':6000,
            'route':'apply_hp_mp_change','native_stat_lock_held':True})
        state['hp'] -= hp_cost
        state['mp'] -= mp_cost
        if combo_after is not None:
            state['combo_orbs'] = combo_after
        if buff_value is not None:
            values = {row[0]:row[1] for row in state['active_buffs']}
            values[skill] = buff_value
            state['active_buffs'] = [[key,values[key]] for key in sorted(values)]
        if stat_change:
            state['stats'].update(stat_change)
        damage_ids = []
        if damage:
            damage_ids.append(ledger.add('monster_damage', {
                'transaction_id':transaction,'skill_id':skill,'object_id':99,
                'hp_before':10000,'hp_after':9900,'hp_loss':100,
                'killed':False,'route':'ordinary_monster_damage'}))
        summary = ledger.add('skill_commit', {
            'transaction_id':transaction,'skill_id':skill,
            'skill_level':levels[skill],'route':route,'committed':True,
            'map_id':240040511,'hp_before':before['hp'],'hp_after':state['hp'],
            'mp_before':before['mp'],'mp_after':state['mp'],
            'combo_orbs_before':before['combo_orbs'],
            'combo_orbs_after':state['combo_orbs'],
            'position_before':{'x':before['x'],'y':before['y']},
            'position_after':{'x':state['x'],'y':state['y']},
            'active_buffs_before':before['active_buffs'],
            'active_buffs_after':state['active_buffs'],
            'stats_before':before['stats'],'stats_after':state['stats'],
            'resource_event_ids':[resource],'damage_event_ids':damage_ids,
            'endpoint_snapshots_atomic':False})
        ledger.add('transaction_end', {'transaction_id':transaction,'committed':True})
        return summary

    # Every buff uses the ordinary native SpecialMove path.
    invoke(1111002, 'special_move_apply_to', buff_value=1)
    invoke(1101004, 'special_move_apply_to', buff_value=-2, hp_cost=10)
    invoke(1121000, 'special_move_apply_to', buff_value=10,
           stat_change={'str':990,'dex':110})
    invoke(1121002, 'special_move_apply_to', buff_value=90)
    invoke(1101006, 'special_move_apply_to', buff_value=20,
           stat_change={'weapon_attack':120,'weapon_defense':450})
    invoke(1101007, 'special_move_apply_to', buff_value=40)
    invoke(1121008, 'close_range_damage_handler', damage=first_build_damage,
           mp_cost=first_build_mp_cost, combo_after=1)
    invoke(1121006, 'close_range_damage_handler', damage=True, combo_after=2)
    if not combo_before_finishers:
        state['active_buffs'] = [row for row in state['active_buffs']
                                 if row[0] != 1111002]
    invoke(1111005, 'close_range_damage_handler', damage=True, combo_after=0)
    invoke(1121008, 'close_range_damage_handler', damage=True,
           combo_after=1 if rebuild_before_panic else 0)
    invoke(1111003, 'close_range_damage_handler', damage=True, combo_after=0)
    ledger.add('terminal', {'complete':True,
        'event_count_before_terminal':len(ledger.rows),
        'qualification_claim':False,'actor':copy.deepcopy(state)})
    return native, ledger.bytes(), ledger.expected()


class HeroNativeTests(unittest.TestCase):
    def test_contract_reuses_native_path_and_program_invokes_core_ten(self):
        value = contract('hero', 'a'*64, protocol=HERO_TOOLKIT_PROTOCOL)
        self.assertEqual(validate_contract(value), value)
        self.assertEqual((value['wall_seconds'],value['max_actions'],
                          value['max_sdk_requests'],value['capture_max_ms']),
                         (120,128,600,125000))
        code = program(value)
        selected = set(value['qualification_skill_ids'])
        for skill in value['skill_toolkit']['skills']:
            if skill['skill_id'] not in selected:
                continue
            self.assertTrue("'"+skill['slot']+"'" in code
                            or '"'+skill['slot']+'"' in code)
        self.assertEqual(len(selected), 10)
        self.assertLess(code.index('"SECONDARY_SKILL"'),
                        code.index("'PRIMARY_SKILL'"))
        with self.assertRaises(ValueError):
            contract('bowmaster','a'*64,protocol=HERO_TOOLKIT_PROTOCOL)
        changed = copy.deepcopy(value)
        changed['skill_toolkit']['skills'][0]['level'] = 1
        with self.assertRaises(ValueError):
            validate_contract(changed)

    @unittest.skipUnless(shutil.which('node'),
                         'Node is required for finite Hero recipe execution')
    def test_recipe_lands_on_fresh_lower_floor_and_never_attacks_stale_airborne(self):
        native = contract('hero', 'a' * 64, protocol=HERO_TOOLKIT_PROTOCOL)
        code = program(native)
        fixture = r"""
const body=BODY;
async function exercise(mode){
  const stale=mode==='stale',scarce=mode==='scarce';
  let now=0,requests=0,descent=0,landed=false;
  let monsterX=1120,monsterDirection=-1,landedObserves=0;
  const actions=[];
  const character={x:669,y:1129,hp:12000,maxHp:12000,mp:6000,maxMp:6000,
    exp:0,mapId:240040511,level:180,alive:true};
  Date.now=()=>now;
  const moveMonster=ms=>{
    if(stale||!landed)return;
    monsterX+=monsterDirection*ms*.08;
    while(monsterX<950||monsterX>1150){
      if(monsterX<950){monsterX=1900-monsterX;monsterDirection=1;}
      if(monsterX>1150){monsterX=2300-monsterX;monsterDirection=-1;}
    }
  };
  const observe=()=>{
    const staticAirborne=stale&&descent===2;
    const visible=!scarce||!landed||landedObserves<=1;
    return {ready:true,ageMs:staticAirborne?400:10,
      renderAgeMs:staticAirborne?400:10,character:{...character},
      monsters:visible?[{objectId:1,x:stale?character.x+58:monsterX,
        y:character.y}]:[]};
  };
  const sdk={
    async observe(){requests++;if(landed)landedObserves++;return observe();},
    async wait(ms){requests++;now+=ms;moveMonster(ms);
      if(!stale&&descent===2&&!landed&&ms>=350){
        landed=true;character.x=842;character.y=1454;
      }
      return {waitedMs:ms};},
    async pressKeys(keys,ms){requests++;actions.push({keys:[...keys],ms,at:now});now+=ms;
      moveMonster(ms);
      if(keys[0]==='RIGHT'&&ms===250&&descent<2){
        descent++;Object.assign(character,descent===1?{x:731,y:1131}:{x:814,y:1310});
      }
      if(landed&&keys.length===1&&ms===250&&keys[0]==='RIGHT')character.x+=55;
      if(landed&&keys.length===1&&ms===250&&keys[0]==='LEFT')character.x-=55;
      if(landed&&keys.length===1&&ms===250)character.y=character.x>900?1468:1454;
      return {accepted:true,observation:observe()};}
  };
  await (new Function('sdk','return (async()=>{'+body+'})()'))(sdk);
  return {actions,requests,elapsed:now};
}
(async()=>process.stdout.write(JSON.stringify({fresh:await exercise('fresh'),
  stale:await exercise('stale'),scarce:await exercise('scarce')})))()
  .catch(error=>{console.error(error);process.exitCode=1;});
""".replace('BODY', json.dumps(code))
        result = subprocess.run([shutil.which('node'), '--max-old-space-size=64',
            '-e', fixture], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = json.loads(result.stdout)
        fresh = evidence['fresh']
        selected = set(native['qualification_skill_ids'])
        by_slot = {skill['slot']: skill['skill_id']
                   for skill in native['skill_toolkit']['skills']}
        buffs = [skill['slot'] for skill in native['skill_toolkit']['skills']
                 if skill['skill_id'] in selected and skill['route'] == 'buff']
        sequence = ['PRIMARY_SKILL'] * 2 + ['SKILL_6'] \
            + ['PRIMARY_SKILL'] * 2 + ['SKILL_7']
        expected = buffs + sequence * 2 + ['SKILL_5'] * 2
        core = [key for row in fresh['actions'] for key in row['keys']
                if by_slot.get(key) in selected]
        self.assertEqual(core, expected)
        self.assertEqual({by_slot[key] for key in core}, selected)
        self.assertNotIn('JUMP', [key for row in fresh['actions']
                                  for key in row['keys']])
        lower_floor_moves = [row for row in fresh['actions']
            if row['keys'] in (['LEFT'], ['RIGHT']) and row['ms'] == 250]
        self.assertEqual([row['keys'] for row in lower_floor_moves[:2]],
                         [['RIGHT'], ['RIGHT']])
        reposition = lower_floor_moves[2:]
        self.assertGreaterEqual(len(reposition), 1)
        self.assertLessEqual(len(reposition), 8)
        stale_attacks = {'ATTACK', 'PRIMARY_SKILL', 'SKILL_5', 'SKILL_6', 'SKILL_7'}
        self.assertTrue(all(len(row['keys']) == 2 for row in fresh['actions']
                            if stale_attacks.intersection(row['keys'])))
        self.assertLessEqual(len(fresh['actions']), native['max_actions'])
        self.assertLessEqual(fresh['requests'], native['max_sdk_requests'])
        self.assertLess(fresh['elapsed'], native['wall_seconds'] * 1000)
        self.assertFalse(stale_attacks.intersection(
            key for row in evidence['stale']['actions'] for key in row['keys']))
        self.assertLessEqual(evidence['scarce']['requests'],
                             native['max_sdk_requests'])
        self.assertLessEqual(len(evidence['scarce']['actions']),
                             native['max_actions'])
        self.assertLess(evidence['scarce']['elapsed'],
                        native['wall_seconds'] * 1000)

    def test_effect_level_ledger_qualifies_all_ten_without_using_acks(self):
        native, raw, expected = native_ledger()
        receipt = verify_events(raw, native, expected)
        self.assertEqual(receipt['status'], 'success')
        self.assertEqual(receipt['reason_code'], 'all_core_skills_qualified')
        self.assertEqual(receipt['qualified_skills'],
                         sorted(toolkit()['native_qualification_skill_ids']))
        self.assertFalse(receipt['publication_eligible'])
        self.assertFalse(receipt['runtime_lifecycle_verified'])

    def test_finisher_requires_fresh_observed_orb_rebuild(self):
        native, raw, expected = native_ledger(rebuild_before_panic=False)
        receipt = verify_events(raw, native, expected)
        self.assertEqual(receipt['status'], 'gameplay_failure')
        self.assertEqual(receipt['reason_code'], 'hero_skill_effect_missing')

    def test_orb_build_requires_combo_buff_positive_damage_and_mp_cost(self):
        for changes in ({'first_build_damage':False},
                        {'first_build_mp_cost':0},
                        {'combo_before_finishers':False}):
            with self.subTest(changes=changes):
                native, raw, expected = native_ledger(**changes)
                receipt = verify_events(raw, native, expected)
                self.assertEqual(receipt['status'], 'gameplay_failure')

    def test_hash_or_contract_mutation_fails_closed(self):
        native, raw, expected = native_ledger()
        altered = bytearray(raw)
        altered[-2] = ord(' ')
        self.assertEqual(verify_events(bytes(altered),native,expected)['reason_code'],
                         'hero_ledger_hash_mismatch')
        changed = copy.deepcopy(native)
        changed['profile']['level'] = 179
        self.assertEqual(verify_events(raw,changed,expected)['reason_code'],
                         'invalid_contract')


if __name__ == '__main__':
    unittest.main()
