import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('maplebench',Path(__file__).resolve().parents[1]/'scripts/maplebench.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class DurableQueueTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.q=m.Queue(self.temp.name); self.addCleanup(self.q.db.close)
        self.config=m.validate_manifest({'scenarios':['henesys-warrior'],'max_api_calls':12,'max_total_tokens':20000,'max_calls_per_trial':12,'max_tokens_per_trial':20000})
        with self.q.db:
            self.q.db.execute('INSERT INTO batches VALUES(?,?,?,?)',('b',json.dumps(self.config),0,'queued'))
            for index in range(2):
                self.q.db.execute('INSERT INTO trials(id,batch_id,ordinal,model,scenario,repetition,status) VALUES(?,?,?,?,?,?,?)',(f't{index}','b',index,m.MODELS[0],'henesys-warrior',1,'queued'))

    def test_restart_preserves_attempt_and_charges_unknown_spend(self):
        t=self.q.claim(); self.assertEqual(t['attempt'],1)
        self.assertEqual(self.q.recover(),1)
        self.assertEqual(self.q.usage('b'),{'calls':12,'tokens':20000})
        self.assertIsNone(self.q.claim())
        self.assertEqual(self.q.db.execute('SELECT status FROM attempts').fetchone()[0],'interrupted')
        self.assertEqual({r[0] for r in self.q.db.execute('SELECT status FROM trials')},{'budget_exhausted'})

    def test_completed_work_not_repeated_and_unused_reservation_released(self):
        t=self.q.claim(); self.q.finish(t,{'reason':'death','usage_complete':True,'apiUsage':[{'total_tokens':1200}]})
        self.assertEqual(self.q.recover(),0)
        second=self.q.claim(); self.assertEqual(second['id'],'t1'); self.assertEqual(second['reserved_calls'],11)
        self.assertEqual(second['reserved_tokens'],18800)
        self.assertEqual(self.q.db.execute('SELECT status FROM trials WHERE id="t0"').fetchone()[0],'completed')

    def test_infrastructure_retry_bounded_and_keeps_prior_attempt(self):
        t=self.q.claim(); self.q.finish(t,{'reason':'infrastructure_error','usage_complete':True,'apiUsage':[]},infrastructure=True)
        t=self.q.claim();self.assertEqual(t['attempt'],2)
        self.q.finish(t,{'reason':'infrastructure_error','usage_complete':True,'apiUsage':[]},infrastructure=True)
        self.assertEqual(self.q.db.execute('SELECT status FROM trials WHERE id="t0"').fetchone()[0],'infrastructure_error')
        self.assertEqual(self.q.db.execute('SELECT count(*) FROM attempts WHERE trial_id="t0"').fetchone()[0],2)

    def test_completed_score_is_adopted_after_worker_crash(self):
        t=self.q.claim()
        path=self.q.root/'b'/t['attempt_dir']/'score.json'
        m.atomic_json(path,{'backend':'cosmic-v83','model':t['model'],'trialId':t['id'],'attempt':1,
            'reason':'completed','usage_complete':True,'apiUsage':[{'total_tokens':1200}]})
        self.q.recover()
        self.assertEqual(self.q.db.execute('SELECT status FROM trials WHERE id="t0"').fetchone()[0],'rendering')
        self.assertEqual(self.q.usage('b'),{'calls':1,'tokens':1200})
        self.assertEqual(self.q.claim()['id'],'t1')

    def test_manifest_rejects_path_traversal_and_unbounded_batches(self):
        for value in [{'scenarios':['../private']},{'scenarios':['s'],'repetitions':0},{'scenarios':['s'],'models':['local-model']},{'scenarios':['s'],'max_api_calls':True}]:
            with self.assertRaises(ValueError):m.validate_manifest(value)

    def test_score_uses_only_authoritative_events_within_cutoff(self):
        obs=[{'nowMs':100,'character':{'hp':10,'alive':True}}, {'nowMs':1100,'character':{'hp':8,'alive':True}}]
        events=[{'kind':'xp_gain','amount':100,'tMs':0},{'kind':'xp_gain','amount':10,'tMs':900},{'kind':'xp_gain','amount':99,'tMs':1101}]
        score=m.score_run(obs,events,{})
        self.assertEqual(score['xpGainedThisRun'],10);self.assertEqual(score['durationMs'],1000)
        self.assertFalse(score['peakWindowComplete'])

if __name__=='__main__':unittest.main()
