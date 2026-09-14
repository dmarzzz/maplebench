"""Bounded synthetic USE/ETC proof tests; no game, database or model calls."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import full_client_native_xp_inventory as inventory
from full_client_native import contract
from full_client_skill_toolkit import toolkit, POLICY_V2_ID, NATIVE_V2_PROTOCOL
from full_client_toolkit_fixture import transform, table, replace
from test_full_client_skill_toolkit import sql_fixture, definitions, CLASSES
import test_full_client_native_xp_inventory as legacy_inventory


class InventoryV2Tests(unittest.TestCase):
    identity = legacy_inventory.InventoryTests.identity
    runtime_hash = legacy_inventory.InventoryTests.runtime_hash
    snapshot = legacy_inventory.InventoryTests.snapshot
    raw = staticmethod(legacy_inventory.InventoryTests.raw)

    def fixture(self, cls='night_lord'):
        policy = toolkit(cls, policy_id=POLICY_V2_ID)
        facts = definitions(policy)
        facts['items']['4006001'] = {'info': {'price':1}, 'nx_xml_scalar_match':True}
        if cls == 'hero':
            facts['skills']['1120004']['level_values'] = {'x':850}
        if cls == 'night_lord':
            facts['skills']['4111002']['level_values'].update(itemCon=4006001, itemConNo=1)
            facts['skills']['4121006']['level_values']['bulletConsume'] = 200
        raw, _ = transform(sql_fixture(cls), policy, facts)
        # Exercise a frozen baseline with one unrelated ETC row. Normal v2
        # preparation replaces the whole ETC tab; proof must still account
        # for the entire tab rather than inspect only declared summon rocks.
        text = raw.decode()
        rows = table(text, 'inventoryitems')[1]
        extra = copy.deepcopy(next(r for r in rows if r['inventorytype']=='2'))
        extra.update(inventoryitemid='999', itemid='4000000', inventorytype='4', position='7', quantity='9')
        raw = replace(text, 'inventoryitems', [*rows, extra]).encode()
        native = contract(cls, hashlib.sha256(raw).hexdigest(), protocol=NATIVE_V2_PROTOCOL)
        use = inventory.expected(native, raw, character_id=5, account_id=2)
        etc = inventory.expected_etc(native, raw, character_id=5, account_id=2)
        return native, raw, [*use, *etc]

    def triplet(self, cls='night_lord', *, potion=1, ammo=3, rocks=1):
        native, raw, items = self.fixture(cls)
        after = copy.deepcopy(items)
        used_ammo = False
        for row in after:
            row['inventoryitemid'] += 1000
            if row['itemid'] == 2000005:
                row['quantity'] -= potion
            elif row['itemid'] == 4006001:
                row['quantity'] -= rocks
            elif row['kind'] == 'use' and not used_ammo:
                row['quantity'] -= ammo
                used_ammo = True
        after = [r for r in after if r['quantity']]
        values = [self.snapshot(native, rows, phase, at) for rows, phase, at in
                  ((items, 'before_login', 100), (after, 'after_logout', 200), (items, 'after_restore', 300))]
        args = dict(native=native, baseline_sql=raw, identity=self.identity,
                    runtime_manifest_sha256=self.runtime_hash,
                    session={'server_started_at_ms':150, 'logged_out_at_ms':190},
                    reset={'completed_at_ms':90}, final_db={'captured_at_ms':210})
        return values, args

    def test_v2_etc_cost_and_cleanup_are_bound_to_original_evidence(self):
        for cls in CLASSES:
            values, args = self.triplet(cls)
            proof = inventory.verify_triplet(*values, **args)
            self.assertEqual(proof['protocol'], 'native-toolkit-resource-proof-v2')
            self.assertEqual(proof['etc_items_consumed'], {'4006001':1} if cls=='night_lord' else {})
            self.assertTrue(proof['etc_inventory_restored'])
            self.assertFalse(proof['class_accepted'])
            self.assertIsNone(proof['native_attack_count'])

    def test_positive_rock_cost_required_but_failed_attempt_can_still_restore(self):
        values, args = self.triplet(rocks=0)
        with self.assertRaisesRegex(ValueError, 'positive_summon_rock'):
            inventory.verify_triplet(*values, **args)
        inventory.verify_restored(values[2], **{k:args[k] for k in
                                  ('native','baseline_sql','identity','runtime_manifest_sha256')})

    def test_etc_growth_movement_substitution_depletion_and_bad_restore_refused(self):
        for change in ('grow', 'move', 'substitute', 'unrelated', 'restore', 'missing'):
            values, args = self.triplet()
            if change == 'restore':
                values[2]['etc_inventory'][0]['quantity'] -= 1
            elif change == 'missing':
                del values[1]['etc_inventory']
            else:
                rock = next(r for r in values[1]['etc_inventory'] if r['itemid']==4006001)
                if change=='grow': rock['quantity']=11
                elif change=='move': rock['position']=20
                elif change=='substitute': rock['itemid']=4006000
                else: next(r for r in values[1]['etc_inventory'] if r['itemid']==4000000)['quantity']-=1
            with self.subTest(change=change), self.assertRaises(ValueError):
                inventory.verify_triplet(*values, **args)

    def test_shared_slot_numbers_across_tabs_allowed_but_shared_row_ids_refused(self):
        native, _, items = self.fixture()
        self.snapshot(native, items, 'before_login', 100)
        extra = copy.deepcopy(items)
        extra[-1]['inventoryitemid']=extra[0]['inventoryitemid']
        with self.assertRaisesRegex(ValueError, 'duplicate_slot_or_row'):
            self.snapshot(native, extra, 'before_login', 100)

    def test_legacy_query_unchanged_and_extended_query_is_one_read_only_transaction(self):
        old = inventory.sql(5, 2)
        self.assertNotIn(b"'etc'", old)
        self.assertEqual(hashlib.sha256(old).hexdigest(), '8fe7c55f4e2044aa6e209a90a2e6ebc286550dea1226f91fe4c7ffd8516db4eb')
        query = inventory.sql(5, 2, include_etc=True)
        self.assertEqual(query.count(b'START TRANSACTION'), 1)
        self.assertEqual(query.count(b'COMMIT;'), 1)
        self.assertIn(b'inventorytype=2', query)
        self.assertIn(b'inventorytype=4', query)
        self.assertEqual(query.count(b'LIMIT 257'), 2)
        for token in (b'password', b'owner', b'INSERT ', b'UPDATE ', b'DELETE '):
            self.assertNotIn(token, query)
        with self.assertRaises(ValueError):
            inventory.sql(5, 2, include_etc=1)

    def test_legacy_receipt_cannot_silently_accept_etc_fields(self):
        legacy = legacy_inventory.InventoryTests()
        native, _, items = legacy.fixture()
        items.append({'kind':'etc','inventoryitemid':999,'itemid':4006001,'position':1,'quantity':10})
        with self.assertRaises(ValueError):
            legacy.snapshot(native, items, 'before_login', 100)

    def test_owned_v2_collection_reads_both_tabs_in_the_same_transaction(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = legacy_inventory.InventoryTests().backend(Path(temp).resolve())
            native, raw, items = self.fixture()
            value = self.snapshot(native, items, 'before_login', 100)
            backend.native = native
            backend.config['baseline']['sha256'] = native['baseline_sha256']
            backend.state['reset']['baseline_sha256'] = native['baseline_sha256']
            backend.host.command.return_value = self.raw([value['character'], *items])
            result = inventory.collect_owned(backend, 'after_logout')
            self.assertEqual(result['etc_inventory'], value['etc_inventory'])
            self.assertEqual(backend.host.command.call_count, 1)
            self.assertEqual(backend.host.command.call_args.kwargs['data'], inventory.sql(5, 2, include_etc=True))
            backend.disconnect.assert_called_once()


if __name__ == '__main__':
    unittest.main()
