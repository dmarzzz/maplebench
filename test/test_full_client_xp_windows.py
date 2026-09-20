"""Synthetic native ledger/scoring tests; these are not game or API runs."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_score import EvidenceError
from full_client_xp_windows import PROTOCOL,score_ledger,verify_bundle,aggregate_task_scores

IDENTITY={'run_id':'a'*32,'server_instance_id':'b'*32,'character_id':7,'account_id':9}
NORM={'server_xp_multiplier':{'numerator':1,'denominator':1},'simulation_speed_multiplier':{'numerator':1,'denominator':1}}

class Ledger:
    def __init__(self, *, initial=None, origin=1000, normalization=None, threshold=1000):
        self.initial=initial or {'level':1,'exp':900};self.state=copy.deepcopy(self.initial)
        self.origin=origin;self.normalization=normalization or copy.deepcopy(NORM)
        self.thresholds=[threshold]*199;self.rows=[]
        self.add('header',origin,**self.state,thresholds=self.thresholds,**self.normalization)
    def add(self,kind,at,**fields):
        row={'schema_version':1,'source':'cosmic_native_xp_ledger','kind':kind,**IDENTITY,
             'sequence':len(self.rows),'wall_ms':at,'elapsed_ns':(at-self.origin)*1000000,
             'previous_sha256':hashlib.sha256(self.rows[-1]).hexdigest() if self.rows else '0'*64,**fields}
        self.rows.append(json.dumps(row,separators=(',',':')).encode()+b'\n')
    def transition(self,at,level,exp,cause='xp_transaction'):
        before=self.state;after={'level':level,'exp':exp}
        delta=sum(self.thresholds[:level-1])+exp-sum(self.thresholds[:before['level']-1])-before['exp']
        self.add('xp_transaction',at,cause=cause,before_level=before['level'],before_exp=before['exp'],
                 after_level=level,after_exp=exp,delta_xp=delta,world_exp_rate=self.normalization['server_xp_multiplier']['numerator'])
        self.state=after
    def commit(self,at):self.add('save_committed',at,**self.state,world_exp_rate=self.normalization['server_xp_multiplier']['numerator'])
    def bytes(self):return b''.join(self.rows)
    def score(self, *, start=2000,end=32000,committed=33000):
        return score_ledger(self.bytes(),identity=IDENTITY,initial=self.initial,final=self.state,
            window={'start_at_ms':start,'deadline_at_ms':end,'window_ms':15000},normalization=self.normalization,
            committed_at_ms=committed)
    def mutate(self,index,edit):
        rows=[json.loads(row) for row in self.rows];edit(rows[index]);self.rows=[]
        for index,row in enumerate(rows):
            row['previous_sha256']=hashlib.sha256(self.rows[-1]).hexdigest() if self.rows else '0'*64
            self.rows.append(json.dumps(row,separators=(',',':')).encode()+b'\n')

class WindowTests(unittest.TestCase):
    def test_half_open_aligned_windows_exclude_deadline_but_keep_save_net(self):
        ledger=Ledger();ledger.transition(2000,2,0);ledger.transition(16999,2,50)
        ledger.transition(17000,2,100);ledger.transition(31999,2,200);ledger.transition(32000,2,300);ledger.commit(33000)
        score=ledger.score();self.assertEqual([w['net_xp'] for w in score['windows']],[150,150])
        self.assertEqual(score['task_score'],600);self.assertEqual(score['control_window_net_xp'],300)
        self.assertEqual(score['persisted_net_xp'],400)
    def test_death_loss_preserved_and_peak_has_only_the_declared_zero_floor(self):
        ledger=Ledger(initial={'level':2,'exp':100});ledger.transition(3000,2,0);ledger.commit(33000)
        score=ledger.score();self.assertEqual(score['windows'][0]['normalized_xp_per_minute'],-400)
        self.assertEqual(score['task_score'],0);self.assertEqual(score['persisted_net_xp'],-100)
    def test_level_cap_discards_excess_instead_of_counting_nominal_grant(self):
        ledger=Ledger(initial={'level':199,'exp':900});ledger.transition(3000,200,0);ledger.commit(33000)
        self.assertEqual(ledger.score()['persisted_net_xp'],100)
    def test_declared_server_and_speed_multipliers_are_removed(self):
        norm=copy.deepcopy(NORM);norm['server_xp_multiplier']['numerator']=4;norm['simulation_speed_multiplier']['numerator']=2
        ledger=Ledger(normalization=norm);ledger.transition(3000,2,100);ledger.commit(33000)
        self.assertEqual(ledger.score()['task_score'],100)
    def test_complete_native_zero_windows_are_valid(self):
        ledger=Ledger();ledger.commit(33000);score=ledger.score()
        self.assertEqual(score['complete_windows'],2);self.assertEqual(score['task_score'],0)
    def test_missing_footer_or_coverage_is_unknown_never_zero(self):
        ledger=Ledger()
        with self.assertRaises(EvidenceError):ledger.score()
        ledger.commit(20000)
        with self.assertRaises(EvidenceError):ledger.score(committed=20000)
    def test_incomplete_tail_is_excluded_from_peak_but_included_in_control_net(self):
        ledger=Ledger();ledger.transition(35000,2,100);ledger.commit(37000)
        score=ledger.score(end=36000,committed=37000)
        self.assertEqual(score['incomplete_tail_ms'],4000);self.assertEqual(score['task_score'],0)
        self.assertEqual(score['control_window_net_xp'],200)
    def test_thirty_minute_arithmetic_has_120_complete_windows(self):
        ledger=Ledger();ledger.commit(1803000)
        self.assertEqual(ledger.score(end=1802000,committed=1803000)['complete_windows'],120)
    def test_removed_or_reordered_event_breaks_chain(self):
        ledger=Ledger();ledger.transition(3000,2,0);ledger.commit(33000);ledger.rows.pop(1)
        with self.assertRaises(EvidenceError):ledger.score()
    def test_rechained_lies_still_fail_state_delta_clock_and_rate_checks(self):
        for mutate in (lambda r:r.update(before_exp=899),lambda r:r.update(delta_xp=1000),
                       lambda r:r.update(world_exp_rate=2),lambda r:r.update(elapsed_ns=0),
                       lambda r:r.update(cause='set_exp'),lambda r:r.update(after_level=True)):
            ledger=Ledger();ledger.transition(3000,2,0);ledger.commit(33000);ledger.mutate(1,mutate)
            with self.subTest(mutate=mutate),self.assertRaises(EvidenceError):ledger.score()
    def test_wrong_identity_final_snapshot_and_multiplier_fail(self):
        ledger=Ledger();ledger.commit(33000);ledger.state={'level':1,'exp':899}
        with self.assertRaises(EvidenceError):ledger.score()
        ledger=Ledger();ledger.commit(33000);ledger.mutate(1,lambda r:r.update(character_id=8))
        with self.assertRaises(EvidenceError):ledger.score()
        with self.assertRaises(EvidenceError):score_ledger(b'',identity=IDENTITY,initial={},final={},window={},normalization={},committed_at_ms=1)
    def test_suite_aggregate_does_not_impute_missing_tasks(self):
        self.assertAlmostEqual(aggregate_task_scores([0,3]),0.6931471805599453)
        for scores in ([],[None],[float('nan')],[-1]):
            with self.assertRaises(EvidenceError):aggregate_task_scores(scores)

class BundleTests(unittest.TestCase):
    def setUp(self):
        from test_full_client_adaptive import Harness
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.h=Harness(self.root,calls=16)
        self.h.run();self.result=self.h.result();self.arts={}
        def save(name,value,raw=False):
            ref=self.h.raw(name+'.bin',value) if raw else self.h.save(name+'.json',value)
            self.arts[name]=ref;return ref
        self.save=save
        row={'character_id':7,'account_id':9,'level':180,'exp':0,'hp':100}
        keys=[[29,5,52],[57,5,53]]
        initial={'schema_version':1,'source':'cosmic_persisted_character','run_id':'a'*32,'account_logged_in':0,
                 'captured_at_ms':999800,'character':row,'keymap':keys}
        final=copy.deepcopy(initial);final['captured_at_ms']=1304000;final['character']['exp']=4500
        baseline={'character':row,'keymap':keys};save('baseline_snapshot',baseline)
        sql=save('baseline_sql',b'-- synthetic baseline',True)
        save('initial_db',initial);save('final_db',final);save('controller_result',self.result)
        table_hash=hashlib.sha256(json.dumps([1000000000]*199,separators=(',',':')).encode()).hexdigest()
        scenario={'protocol':'full-client-adaptive-pilot-v1','adaptive_protocol':self.h.p,
                  'xp_window_protocol':{'id':PROTOCOL,'window_ms':15000,'wall_seconds':300,'normalization':NORM,
                                        'experience_table_sha256':table_hash}}
        scenario_ref=save('scenario',scenario)
        ledger=Ledger(initial={'level':180,'exp':0},origin=999900,threshold=1000000000)
        ledger.transition(1005000,180,4500);ledger.commit(1302000);save('xp_ledger',ledger.bytes(),True)
        save('native_save',(json.dumps({'schema_version':1,'source':'cosmic_persisted_character',**IDENTITY,
                                      'kind':'save_committed','committed_at_ms':1302000})+'\n').encode(),True)
        save('native_log',b'MapleBench persistence journal initialized\nMapleBench XP ledger initialized\n',True)
        events=[{'run_id':'a'*32,'server_instance_id':'b'*32,'event':name,'at_ms':at} for name,at in
                [('server_started',999850),('login',999950),('logged_out',1303000),('collection_completed',1304000)]]
        save('server_log',b''.join(json.dumps(event).encode()+b'\n' for event in events),True)
        session={'run_id':'a'*32,'server_instance_id':'b'*32,'disconnect_kind':'normal',
            'world_lock_held_throughout':True,'queue_lock_held_throughout':True,'server_started_at_ms':999850,'login_at_ms':999950,
            'controller_started_at_ms':1000000,'controller_ended_at_ms':1300000,'disconnect_requested_at_ms':1301000,'logged_out_at_ms':1303000,
            'save':{'status':'confirmed','run_id':'a'*32,'server_instance_id':'b'*32,'character_id':7,'committed_at_ms':1302000,
                    'log_checked_from_ms':999850,'log_checked_through_ms':1304000,'save_error_count':0,
                    'evidence_sha256':self.arts['native_save']['sha256'],'native_logs_sha256':self.arts['native_log']['sha256'],
                    'logs_sha256':self.arts['server_log']['sha256']}}
        save('session',session);save('reset',{'run_id':'a'*32,'baseline_sha256':sql['sha256'],
            'world_lock_held':True,'queue_lock_held':True,'server_stopped':True,'verified':True,'completed_at_ms':999700})
        self.manifest={'schema_version':1,'protocol':PROTOCOL,**IDENTITY,'artifacts':self.arts,
            'window':{'start_at_ms':1000000,'deadline_at_ms':1300000,'window_ms':15000},'normalization':NORM,
            'baseline_sha256':sql['sha256'],'scenario_fingerprint':scenario_ref['sha256'],
            'experience_table_sha256':table_hash}
    def tearDown(self):self.temp.cleanup()
    def bind_save_artifact(self,name,raw,field):
        ref=self.save(name,raw,True)
        session=json.loads((self.root/self.arts['session']['path']).read_text())
        session['save'][field]=ref['sha256'];self.save('session',session)
    def test_full_native_save_controller_and_reset_bundle(self):
        result=verify_bundle(self.manifest,self.root)
        self.assertEqual(result['complete_windows'],20);self.assertEqual(result['task_score'],18000)
        self.assertEqual(result['persisted_net_xp'],4500);self.assertTrue(result['artifacts_verified'])
        self.assertTrue(result['baseline_reset_verified']);self.assertFalse(result['publication_eligible'])
    def test_failed_native_sync_or_unfrozen_window_never_gets_zero(self):
        original=(self.root/self.arts['native_log']['path']).read_bytes()
        self.bind_save_artifact('native_log',original+b'MapleBench XP ledger failed\n','native_logs_sha256')
        with self.assertRaisesRegex(EvidenceError,'native_journal_initialization_or_failure'):verify_bundle(self.manifest,self.root)
        self.bind_save_artifact('native_log',original,'native_logs_sha256');self.manifest['window']['start_at_ms']+=1
        with self.assertRaises(EvidenceError):verify_bundle(self.manifest,self.root)
    def test_reset_corruption_invalidates_window_score(self):
        self.save('reset',{'run_id':'a'*32,'verified':False})
        with self.assertRaises(EvidenceError):verify_bundle(self.manifest,self.root)
    def test_wrong_native_commit_or_duplicated_phase_is_refused_after_rehash(self):
        original=(self.root/self.arts['native_save']['path']).read_bytes();row=json.loads(original)
        row['account_id']=10;self.bind_save_artifact('native_save',json.dumps(row).encode()+b'\n','evidence_sha256')
        with self.assertRaisesRegex(EvidenceError,'native_commit_missing_or_ambiguous'):verify_bundle(self.manifest,self.root)
        self.bind_save_artifact('native_save',original,'evidence_sha256')
        events=(self.root/self.arts['server_log']['path']).read_bytes().splitlines(keepends=True)
        row=json.loads(events[0]);row['at_ms']+=1;events.insert(1,json.dumps(row).encode()+b'\n')
        self.bind_save_artifact('server_log',b''.join(events),'logs_sha256')
        with self.assertRaisesRegex(EvidenceError,'missing_or_ambiguous_phase_receipt'):verify_bundle(self.manifest,self.root)
    def test_incomplete_log_review_and_unfrozen_table_are_unknown(self):
        session=json.loads((self.root/self.arts['session']['path']).read_text())
        session['save']['log_checked_through_ms']=1303999;self.save('session',session)
        with self.assertRaises(EvidenceError):verify_bundle(self.manifest,self.root)
        session['save']['log_checked_through_ms']=1304000;self.save('session',session)
        self.manifest['experience_table_sha256']='0'*64
        with self.assertRaises(EvidenceError):verify_bundle(self.manifest,self.root)

if __name__=='__main__':unittest.main()
