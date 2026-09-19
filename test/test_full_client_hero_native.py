"""Hero toolkit native contract/evidence tests; no game, DB, build, or API."""
import copy
import hashlib
import json
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
        self.assertLess(code.index("['SKILL_6','SKILL_7']"),
                        code.rindex("await cast(finisher)"))
        with self.assertRaises(ValueError):
            contract('bowmaster','a'*64,protocol=HERO_TOOLKIT_PROTOCOL)
        changed = copy.deepcopy(value)
        changed['skill_toolkit']['skills'][0]['level'] = 1
        with self.assertRaises(ValueError):
            validate_contract(changed)

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
