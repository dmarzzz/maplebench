"""Synthetic offline fixtures: no game assets, credentials or database access."""
import copy,hashlib,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_potion_fixture import ID,geometry,transform
from full_client_toolkit_fixture import table

def ddl(name,cols,rows):
    return 'CREATE TABLE `'+name+'` (\n'+''.join('  `'+c+'` text,\n' for c in cols)+') ENGINE=InnoDB;\nINSERT INTO `'+name+'` VALUES '+','.join('('+','.join(r)+')' for r in rows)+';\n'

SQL=(ddl('accounts',['id','loggedin','password'],[['9','0',"'SYNTHETIC_NOT_A_CREDENTIAL'"]])+
 ddl('characters',['id','accountid','job','level','hp','mp','maxhp','maxmp','map','spawnpoint'],[['7','9','222','180','12000','16000','12000','16000','240040511','0']])+
 ddl('keymap',['id','characterid','key','type','action'],[['1','7','29','5','52'],['2','7','91','2','2000005']])+
 ddl('skills',['id','characterid','skillid'],[['1','7','2201002']])+
 ddl('inventoryitems',['inventoryitemid','characterid','inventorytype','position','itemid','quantity','owner','expiration'],[['1','7','-1','-11','1382000','1',"''",'-1'],['2','7','2','1','2000005','100',"''",'-1'],['3','7','4','1','4006001','10',"''",'-1']])).encode()
XML=b'''<imgdir name="000000003.img"><imgdir name="info"><int name="fieldLimit" value="8256"/></imgdir><imgdir name="foothold"><imgdir name="0"><imgdir name="0"><imgdir name="5"><int name="x1" value="0"/><int name="y1" value="1235"/><int name="x2" value="90"/><int name="y2" value="1235"/></imgdir></imgdir></imgdir></imgdir><imgdir name="portal"><imgdir name="0"><int name="pt" value="0"/><int name="x" value="49"/><int name="y" value="1178"/></imgdir></imgdir></imgdir>'''
DEFINITIONS=json.dumps({'status':'nx_xml_scalars_verified_not_live_qualified','items':{'2000005':{'nx_xml_scalar_match':True,'spec':{'hpR':100,'mpR':100}}}}).encode()

def binding(sql=SQL,definitions=DEFINITIONS,xml=XML):
    return {'id':ID,'task_id':'potion-use-v1','parent_sha256':hashlib.sha256(sql).hexdigest(),'definitions_sha256':hashlib.sha256(definitions).hexdigest(),'map_xml_sha256':hashlib.sha256(xml).hexdigest(),'map_id':3,'geometry':geometry(xml,3)}

class PotionFixtureTest(unittest.TestCase):
    def test_three_exact_fractions_and_preserved_ordinary_equipment_accounts_skills(self):
        for variant,mp in [(1,1600),(2,2400),(3,3200)]:
            out,e=transform(SQL,DEFINITIONS,XML,binding(),variant)
            c=table(out.decode(),'characters')[1][0]
            self.assertEqual(c['mp'],str(mp));self.assertEqual(c['hp'],'12000');self.assertEqual(c['map'],'3');self.assertEqual(c['spawnpoint'],'0')
            for name in ['accounts','skills']:
                self.assertEqual(table(SQL.decode(),name)[1],table(out.decode(),name)[1])
            items=table(out.decode(),'inventoryitems')[1]
            self.assertEqual(items[0],table(SQL.decode(),'inventoryitems')[1][0])
            self.assertEqual([(r['itemid'],r['quantity']) for r in items if r['inventorytype']=='2'],[('2000005','1')])
            self.assertFalse(any(r['inventorytype']=='4' for r in items))
            self.assertEqual({r['key'] for r in table(out.decode(),'keymap')[1]},{'57','16','17'})
            self.assertEqual(e['status'],'offline_candidate_not_live_qualified');self.assertIn('actual_no_active_buffs',e['required_live_checks'])
    def test_empty_negative_removes_resource_without_inventing_or_equipment_loss(self):
        out,e=transform(SQL,DEFINITIONS,XML,binding(),2,True)
        self.assertEqual(e['use_inventory'],[]);self.assertEqual(len(table(out.decode(),'inventoryitems')[1]),1)
        self.assertEqual(e['stored_mp'],2400)
    def test_tampered_source_definition_and_geometry_refused(self):
        for sql,defs,xml in [(SQL+b'\n',DEFINITIONS,XML),(SQL,DEFINITIONS+b' ',XML),(SQL,DEFINITIONS,XML+b' ')]:
            with self.assertRaisesRegex(ValueError,'pinned_input_changed'):transform(sql,defs,xml,binding(),1)
        b=binding();b['geometry']['expected_landing']['y']+=1
        with self.assertRaisesRegex(ValueError,'frozen_geometry_changed'):transform(SQL,DEFINITIONS,XML,b,1)
    def test_wrong_class_online_account_noncanonical_potion_and_persisted_effects(self):
        wrong=SQL.replace(b"'222'",b"'112'") if b"'222'" in SQL else SQL.replace(b',222,180,',b',112,180,')
        with self.assertRaisesRegex(ValueError,'mage_180_required'):transform(wrong,DEFINITIONS,XML,binding(wrong),1)
        online=SQL.replace(b'(9,0,',b'(9,1,')
        with self.assertRaisesRegex(ValueError,'single_offline_actor'):transform(online,DEFINITIONS,XML,binding(online),1)
        defs=DEFINITIONS.replace(b'"mpR": 100',b'"mpR": 80')
        with self.assertRaisesRegex(ValueError,'power_elixir'):transform(SQL,defs,XML,binding(definitions=defs),1)
        sql=SQL+b'INSERT INTO `cooldowns` VALUES (7,1);\n'
        with self.assertRaisesRegex(ValueError,'persisted_effects'):transform(sql,DEFINITIONS,XML,binding(sql),1)
    def test_potion_forbidden_script_or_narrow_ground_rejected(self):
        for xml in [XML.replace(b'value="8256"',b'value="4096"'),XML.replace(b'<int name="fieldLimit"',b'<string name="onUserEnter" value="script"/><int name="fieldLimit"'),XML.replace(b'value="90"',b'value="60"')]:
            with self.assertRaises(ValueError):geometry(xml,3)
    def test_no_rounding_or_unknown_variant(self):
        sql=SQL.replace(b'16000',b'16001')
        with self.assertRaisesRegex(ValueError,'exact_native_base'):transform(sql,DEFINITIONS,XML,binding(sql),1)
        for variant in [0,4,True]:
            with self.assertRaisesRegex(ValueError,'variant_required'):transform(SQL,DEFINITIONS,XML,binding(),variant)

if __name__=='__main__':unittest.main()
