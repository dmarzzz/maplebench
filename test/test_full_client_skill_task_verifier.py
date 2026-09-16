"""Synthetic native event streams: none are gameplay, native qualification or API runs."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from test_full_client_skill_tasks import fixture
import full_client_skill_tasks as tasks
import full_client_skill_task_verifier as verifier


def context():
    return dict(run_id='a'*32,server_instance_id='b'*32,character_id=7,account_id=9,
                runtime_sha256='d'*64,ledger_sha256='0'*64,start_monotonic_ns=1000000000,
                start_wall_ms=1700000000000,duration_ns=120000000000)


def boundary(contract,**changes):
    initial=contract['binding']['initial']
    return dict(item_id=2000005,quantity=initial['power_elixirs'],hp=initial['hp'],mp=initial['mp'],
                max_hp=initial['max_hp'],max_mp=initial['max_mp'],alive=True,online=True,snapshot_atomic=False,**changes)


def events(contract,*,positive=True,terminal_ns=None):
    initial=boundary(contract)
    output=[('header',0,dict(start_monotonic_ns=1000000000,deadline_elapsed_ns=120000000000,
        movement_physics_validated=False,teleport_causal_link_supported=False,
        coverage_source='accepted_movement_packets_only',resource_coverage='apply_hp_mp_change_only',
        inventory_coverage='remove_item_only',initial=initial))]
    actor=copy.deepcopy(initial)
    if positive:
        tid='e00000001'
        output += [
            ('transaction_begin',1000000000,dict(transaction_kind='item_use',subject_id=2000005,skill_level=0,parent_transaction_id='')),
            # Actual UseItemHandler removes the item BEFORE applying its effect.
            ('inventory_transaction',1001000000,dict(transaction_id=tid,inventory_type='USE',slot=1,item_id=2000005,
                slot_quantity_before=1,slot_quantity_after=0,route='inventory_remove_item',native_inventory_lock_held=False)),
            ('resource_transaction',1002000000,dict(transaction_id=tid,hp_before=12000,hp_after=12000,
                mp_before=initial['mp'],mp_after=16000,max_hp=12000,max_mp=16000,route='apply_hp_mp_change',native_stat_lock_held=True)),
            ('item_effect_result',1003000000,dict(transaction_id=tid,item_id=2000005,applied=True,route='item_stat_effect_apply_to')),
            ('item_transaction',1004000000,dict(transaction_id=tid,item_id=2000005,route='ordinary_item_packet',committed=True,
                quantity_before=1,quantity_after=0,hp_before=12000,hp_after=12000,mp_before=initial['mp'],mp_after=16000,
                max_hp=12000,max_mp=16000,alive=True,resource_event_ids=['e00000003'],inventory_event_ids=['e00000002'],endpoint_snapshots_atomic=False)),
            ('transaction_end',1005000000,dict(transaction_id=tid,committed=True))]
        actor.update(quantity=0,mp=16000)
    output.append(('terminal',terminal_ns if terminal_ns is not None else 2000000000 if positive else 120000000000,
                   dict(complete=True,event_count_before_terminal=len(output),qualification_claim=False,actor=actor)))
    return output


def serialize(contract,events,*,mutate_row=None):
    expected=context();raw=b'';previous='0'*64
    for sequence,(kind,elapsed,data) in enumerate(events):
        row={k:expected[k] for k in ('run_id','server_instance_id','character_id','account_id','runtime_sha256')}
        row.update(schema_version=1,source=tasks.LEDGER_SOURCE,kind=kind,task_id=contract['task_id'],
                   binding_sha256=contract['binding_sha256'],sequence=sequence,event_id=f'e{sequence:08d}',
                   elapsed_ns=elapsed,wall_ms=expected['start_wall_ms']+elapsed//1000000,
                   previous_sha256=previous,data=data)
        if mutate_row:mutate_row(row)
        line=json.dumps(row,separators=(',',':'),sort_keys=True).encode()+b'\n'
        raw+=line;previous=hashlib.sha256(line).hexdigest()
    expected['ledger_sha256']=hashlib.sha256(raw).hexdigest()
    return raw,expected


class SkillTaskVerifierTests(unittest.TestCase):
    def setUp(self):
        self.c=tasks.contract('potion-use-v1',1,fixture('potion-use-v1'))

    def verify(self,rows=None,contract=None,mutate_row=None):
        c=contract or self.c;raw,expected=serialize(c,rows if rows is not None else events(c),mutate_row=mutate_row)
        return verifier.verify_ledger(raw,c,expected)

    def test_linked_ordinary_item_restoration_passes_all_three_variants(self):
        for variant in (1,2,3):
            c=tasks.contract('potion-use-v1',variant,fixture('potion-use-v1',variant))
            result=self.verify(contract=c)
            self.assertEqual(result['status'],'success',result)
            self.assertEqual(result['outcome'],dict(criterion_met=True,completion_ms=1005.0,alive=True,items_consumed=1,mp_fraction=1.0))
            self.assertEqual(len(result['evidence']['event_ids']),6)
            self.assertFalse(result['publication_eligible']);self.assertFalse(result['runtime_lifecycle_verified'])

    def test_noop_is_a_closed_gameplay_failure_not_success_or_zero_evidence(self):
        result=self.verify(events(self.c,positive=False))
        self.assertEqual(result['status'],'gameplay_failure',result)
        self.assertEqual(result['outcome'],dict(criterion_met=False,completion_ms=None,alive=True,items_consumed=0,mp_fraction=.1))
        self.assertEqual(self.verify(events(self.c,positive=False,terminal_ns=119999999999))['status'],'invalid')

    def test_passive_mp_cannot_substitute_for_linked_item(self):
        rows=events(self.c,positive=False)
        rows.insert(1,('resource_transaction',2000000000,dict(transaction_id='',hp_before=12000,hp_after=12000,
            mp_before=1600,mp_after=16000,max_hp=12000,max_mp=16000,route='apply_hp_mp_change',native_stat_lock_held=True)))
        rows[-1][2]['actor']['mp']=16000;rows[-1][2]['event_count_before_terminal']=2
        result=self.verify(rows)
        self.assertEqual(result['status'],'gameplay_failure',result)
        self.assertEqual(result['outcome']['mp_fraction'],1.0)
        self.assertFalse(result['outcome']['criterion_met'])

    def test_empty_inventory_request_has_no_effect_and_fails(self):
        c=tasks.contract('potion-use-v1',1,fixture('potion-use-v1',control='empty-inventory'),control='empty-inventory')
        rows=events(c,positive=False)
        positive=events(self.c);summary=copy.deepcopy(positive[5][2])
        summary.update(quantity_before=0,quantity_after=0,mp_after=1600,committed=False,resource_event_ids=[],inventory_event_ids=[])
        rows[1:1]=[positive[1],('item_transaction',1004000000,summary),('transaction_end',1005000000,dict(transaction_id='e00000001',committed=False))]
        rows[-1][2]['event_count_before_terminal']=4
        self.assertEqual(self.verify(rows,c)['status'],'gameplay_failure')

    def test_half_open_deadline_and_late_settlement_cannot_rescue(self):
        for last_ns,success in ((119999999999,True),(120000000000,False),(120000000001,False)):
            rows=events(self.c,terminal_ns=121000000000)
            rows[6]=(rows[6][0],last_ns,rows[6][2])
            result=self.verify(rows)
            self.assertEqual(result['status'],'success' if success else 'gameplay_failure',result)
            self.assertEqual(result['outcome']['items_consumed'],int(success))

    def test_effect_false_is_known_failure_despite_handler_returning_true(self):
        rows=events(self.c,terminal_ns=120000000000)
        del rows[3]
        rows[3][2]['applied']=False
        rows[4][2].update(resource_event_ids=[],mp_after=1600)
        rows[-1][2]['actor']['mp']=1600;rows[-1][2]['event_count_before_terminal']=6
        result=self.verify(rows)
        self.assertEqual(result['status'],'gameplay_failure',result)
        self.assertEqual(result['outcome']['items_consumed'],1)

    def test_child_references_route_lock_and_incomplete_effect_fail_closed(self):
        mutations=[
            lambda r:r[5][2].update(resource_event_ids=[]),
            lambda r:r[5][2].update(resource_event_ids=['e00000003','e00000003']),
            lambda r:r[5][2].update(resource_event_ids=['e00000002']),
            lambda r:r[3][2].update(transaction_id=''),
            lambda r:r[3][2].update(transaction_id='e00000009'),
            lambda r:r[5][2].update(route='native_item_helper'),
            lambda r:r[3][2].update(native_stat_lock_held=False),
            lambda r:r[4][2].update(item_id=2000006),
            lambda r:r[5][2].update(mp_before=1500),
            lambda r:r[2][2].update(slot_quantity_after=1),
            lambda r:r[-1][2]['actor'].update(quantity=1),
            lambda r:r[6][2].update(committed=False),
        ]
        for mutate in mutations:
            rows=events(self.c);mutate(rows)
            self.assertEqual(self.verify(rows)['status'],'invalid',str(mutate))

    def test_dead_restoration_does_not_pass_alive_requirement(self):
        rows=events(self.c,terminal_ns=2000000000)
        rows[3][2].update(hp_after=0);rows[5][2].update(hp_after=0,alive=False)
        rows[-1][2]['actor'].update(hp=0,alive=False)
        result=self.verify(rows)
        self.assertEqual(result['status'],'gameplay_failure',result)
        self.assertFalse(result['outcome']['alive'])

    def test_missing_terminal_wrong_identity_bytes_and_duplicate_keys_invalid(self):
        raw,expected=serialize(self.c,events(self.c))
        for changed in (raw+b' ',raw[:-1],raw.replace(b'ordinary_item_packet',b'native_item_helper')):
            self.assertEqual(verifier.verify_ledger(changed,self.c,expected)['status'],'invalid')
        altered=dict(expected,character_id=10)
        self.assertEqual(verifier.verify_ledger(raw,self.c,altered)['reason_code'],'ledger_identity_mismatch')
        rows=events(self.c)[:-1]
        self.assertEqual(self.verify(rows)['reason_code'],'closed_native_window_required')
        duplicate=raw.replace(b'"schema_version":1',b'"schema_version":1,"schema_version":1',1)
        expected['ledger_sha256']=hashlib.sha256(duplicate).hexdigest()
        self.assertEqual(verifier.verify_ledger(duplicate,self.c,expected)['reason_code'],'ledger_json_invalid')

    def test_counter_clock_reset_drift_and_forged_capabilities_invalid(self):
        mutations=[lambda r:r.update(sequence=1) if r['sequence']==2 else None,
                   lambda r:r.update(wall_ms=r['wall_ms']+26) if r['sequence']==3 else None,
                   lambda r:r.update(elapsed_ns=0) if r['sequence']==4 else None,
                   lambda r:r['data'].update(movement_physics_validated=True) if r['kind']=='header' else None,
                   lambda r:r['data']['initial'].update(mp=1601) if r['kind']=='header' else None,
                   lambda r:r['data']['actor'].update(online=False) if r['kind']=='terminal' else None]
        for mutate in mutations:self.assertEqual(self.verify(mutate_row=mutate)['status'],'invalid')

    def test_platforming_and_teleport_remain_unqualified_not_inferred_from_packets(self):
        for task,reason in (('platforming-v1','native_grounded_physics_coverage_unavailable'),
                            ('native-teleport-v1','native_teleport_causal_link_unavailable')):
            c=tasks.contract(task,1,fixture(task));result=self.verify(events(c,positive=False),c)
            self.assertEqual(result['status'],'invalid');self.assertEqual(result['reason_code'],reason)
            self.assertIsNone(result['outcome'])

    def test_malformed_types_return_fixed_reason_without_data_leakage(self):
        rows=events(self.c);rows[5][2]['hp_after']='private-token-value'
        result=self.verify(rows)
        self.assertEqual(result['status'],'invalid');self.assertNotIn('private-token-value',json.dumps(result))
        self.assertEqual(verifier.verify_ledger(b'x',None,{})['reason_code'],'invalid_contract')


if __name__=='__main__':unittest.main()
