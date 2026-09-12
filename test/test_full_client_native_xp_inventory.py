"""Synthetic inventory transactions only; no database, game or paid API."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import full_client_native_xp_inventory as inventory
from full_client_native import contract
from full_client_skill_toolkit import NATIVE_PROTOCOL, toolkit
from full_client_toolkit_fixture import transform
from test_full_client_skill_toolkit import sql_fixture, definitions, CLASSES


class InventoryTests(unittest.TestCase):
    identity={'run_id':'a'*32,'server_instance_id':'b'*32,'character_id':5,'account_id':2}
    runtime_hash='c'*64

    def fixture(self, cls='night_lord'):
        policy=toolkit(cls);raw,_=transform(sql_fixture(cls),policy,definitions(policy))
        native=contract(cls,hashlib.sha256(raw).hexdigest(),protocol=NATIVE_PROTOCOL)
        rows=inventory.expected(native,raw,character_id=5,account_id=2)
        return native,raw,rows

    def snapshot(self,native,items,phase,at):
        header={'kind':'character','character_id':5,'account_id':2,'job':native['skill_toolkit']['job'],
                'level':180,'account_logged_in':0,'transactional_tables':3}
        return inventory.parse(self.raw([header,*items]),native=native,**self.identity,
            phase=phase,runtime_manifest_sha256=self.runtime_hash,captured_at_ms=at)

    @staticmethod
    def raw(rows):return b'\n'.join(json.dumps(row).encode() for row in rows)+b'\n'

    def triplet(self,cls='night_lord',*,potion=1,ammo=3):
        native,raw,items=self.fixture(cls);after=copy.deepcopy(items)
        for row in after:
            row['inventoryitemid']+=1000
            if row['itemid']==2000005:row['quantity']-=potion
        projectile=next((r for r in after if r['itemid']!=2000005),None)
        if projectile is not None:projectile['quantity']-=ammo
        after=[r for r in after if r['quantity']]
        values=[self.snapshot(native,rows,phase,at) for rows,phase,at in
                ((items,'before_login',100),(after,'after_logout',200),(items,'after_restore',300))]
        args=dict(native=native,baseline_sql=raw,identity=self.identity,runtime_manifest_sha256=self.runtime_hash,
            session={'server_started_at_ms':150,'logged_out_at_ms':190},reset={'completed_at_ms':90},final_db={'captured_at_ms':210})
        return values,args

    def test_consistent_read_only_query_excludes_sensitive_fields_and_bounds_rows(self):
        sql=inventory.sql(5,2).decode()
        self.assertIn('WITH CONSISTENT SNAPSHOT, READ ONLY',sql);self.assertIn('LIMIT 257',sql)
        self.assertEqual(sql.count('COMMIT;'),1)
        for token in ('INSERT ','UPDATE ','DELETE ','REPLACE ','DROP ','password','owner','name','email'):
            self.assertNotIn(token,sql)
        for bad in (True,0,-1,'5;DROP',2**31):
            with self.assertRaises(ValueError):inventory.sql(bad,2)

    def test_all_classes_bind_exact_finite_inventory_with_regenerated_save_ids(self):
        for cls in CLASSES:
            values,args=self.triplet(cls,ammo=0 if cls=='bowmaster' else 3)
            proof=inventory.verify_triplet(*values,**args)
            self.assertEqual(proof['potions_consumed'],1)
            self.assertEqual(proof['ammunition_consumed'],3 if cls=='night_lord' else 0 if cls=='bowmaster' else None)
            self.assertIsNone(proof['native_attack_count']);self.assertIsNone(proof['model_score'])
            self.assertFalse(proof['class_accepted'])

    def test_potion_and_stars_require_actual_depletion_but_cleanup_does_not(self):
        for cls,potion,ammo,reason in (('hero',0,0,'positive_potion'),('night_lord',1,0,'positive_star')):
            values,args=self.triplet(cls,potion=potion,ammo=ammo)
            with self.assertRaisesRegex(ValueError,reason):inventory.verify_triplet(*values,**args)
            clean=inventory.verify_restored(values[2],**{k:args[k] for k in ('native','baseline_sql','identity','runtime_manifest_sha256')})
            self.assertTrue(clean['inventory_restored'])

    def test_exhausted_stacks_can_disappear_without_inventing_attack_counts(self):
        values,args=self.triplet('night_lord',potion=100,ammo=800)
        proof=inventory.verify_triplet(*values,**args)
        self.assertEqual((proof['potions_consumed'],proof['ammunition_consumed']),(100,800))

    def test_wrong_owner_phase_timing_restore_and_inventory_growth_fail_closed(self):
        for field in ('owner','runtime','toolkit','phase','time','restore','grow','move','unexpected'):
            values,args=self.triplet()
            if field=='owner':values[1]['native_acceptance_id']='d'*32
            elif field=='runtime':values[1]['runtime_manifest_sha256']='d'*64
            elif field=='toolkit':values[1]['toolkit_sha256']='d'*64
            elif field=='phase':values[1]['phase']='before_login'
            elif field=='time':values[1]['captured_at_ms']=180
            elif field=='restore':values[2]['use_inventory'][0]['quantity']-=1
            elif field=='grow':values[1]['use_inventory'][1]['quantity']=801
            elif field=='move':values[1]['use_inventory'][-1]['position']=25
            else:values[1]['use_inventory'][1]['itemid']=2000006
            with self.subTest(field=field),self.assertRaises(ValueError):inventory.verify_triplet(*values,**args)

    def test_online_duplicate_extra_fields_and_nontransactional_snapshot_refused(self):
        values,args=self.triplet();value=values[0]
        for change in ('online','tables','duplicate','private','bool'):
            v=copy.deepcopy(value)
            if change=='online':v['character']['account_logged_in']=1
            elif change=='tables':v['character']['transactional_tables']=2
            elif change=='duplicate':v['use_inventory'][1]['position']=1
            elif change=='private':v['use_inventory'][0]['owner']='private field forbidden'
            else:v['use_inventory'][0]['quantity']=True
            with self.assertRaises(ValueError):inventory.check_snapshot(v,native=args['native'],identity=self.identity,
                phase='before_login',runtime_manifest_sha256=self.runtime_hash)

    def backend(self,root):
        native,raw,items=self.fixture();snapshot=self.snapshot(native,items,'before_login',100)
        defaults=root/'mysql.cnf';defaults.write_text('[client]\n# synthetic\n');defaults.chmod(0o600)
        host=SimpleNamespace(deadline=time.monotonic()+30,now=lambda:100,
            command=Mock(return_value=self.raw([snapshot['character'],*items])))
        return SimpleNamespace(native=native,run_id=self.identity['run_id'],identity=lambda:self.identity,
            host=host,config={'baseline':{'sha256':native['baseline_sha256']},'runtime_manifest':{'sha256':self.runtime_hash},
                'mysql':{'command':['/usr/bin/mysql'],'database':'maplebench','defaults_file':str(defaults),'character_id':5,'account_id':2}},
            state={'reset':{'run_id':self.identity['run_id'],'baseline_sha256':native['baseline_sha256'],'verified':True},
                   'intents':['restore_baseline','native_xp_restore_after']},safe_boundary=Mock(),disconnect=Mock(),
            stopped=Mock(return_value=True),unit=lambda name:name)

    def test_owned_collection_preserves_deadline_checks_locks_and_verifies_saved_logout(self):
        with tempfile.TemporaryDirectory() as temp:
            backend=self.backend(Path(temp).resolve());deadline=backend.host.deadline
            original=backend.host.command.return_value
            def command(argv,**kwargs):
                self.assertLessEqual(backend.host.deadline,time.monotonic()+5)
                self.assertEqual(backend.safe_boundary.call_count,2)
                self.assertEqual(kwargs,{'data':inventory.sql(5,2),'maximum':inventory.MAX_BYTES})
                self.assertFalse(any('password=' in token for token in argv));return original
            backend.host.command.side_effect=command
            receipt=inventory.collect_owned(backend,'after_logout')
            self.assertEqual(receipt['phase'],'after_logout');self.assertEqual(backend.host.deadline,deadline)
            self.assertEqual(backend.safe_boundary.call_count,3);backend.disconnect.assert_called_once()

    def test_lost_ownership_or_uncertain_query_never_retries_and_restores_deadline(self):
        for error in ('guard','query','save'):
            with tempfile.TemporaryDirectory() as temp:
                backend=self.backend(Path(temp).resolve());deadline=backend.host.deadline
                if error=='guard':backend.safe_boundary.side_effect=ValueError('ownership_lost')
                elif error=='query':backend.host.command.side_effect=TimeoutError('uncertain')
                else:backend.disconnect.side_effect=ValueError('save_unconfirmed')
                with self.assertRaises((ValueError,TimeoutError)):inventory.collect_owned(backend,'after_logout')
                self.assertEqual(backend.host.command.call_count,1 if error=='query' else 0)
                self.assertEqual(backend.host.deadline,deadline)


if __name__=='__main__':unittest.main()
