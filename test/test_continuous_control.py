"""Prove replanning does not stop control and replacements never overlap."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

spec=importlib.util.spec_from_file_location('continuous_agent',Path(__file__).parents[1]/'scripts/maple_agent.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
OBS={'nowMs':0,'character':{'alive':True},'monsters':[]}
SCENARIO={'id':'test','allowed_skills':[]}

class ContinuousControlTest(unittest.TestCase):
    def test_actions_continue_during_api_request_with_one_executor_and_stable_turn_ids(self):
        counts={'calls':0,'active':0,'peak':0,'steps':0}
        def request(url,payload=None,key=None,timeout=None):
            if url.endswith('/v1/observe'):return OBS
            counts['calls']+=1
            if counts['calls']==2:
                before=counts['steps'];time.sleep(.12)
                self.assertGreater(counts['steps'],before,'Executor stopped during model inference')
                self.assertIn('active_program',json.loads(payload['input']))
            return {'status':'completed','model':a.MODELS[0],'usage':{'total_tokens':100},
                'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'note':'control','code':str(counts['calls'])})}]}]}
        def execute(code,scenario,url,**kw):
            counts['active']+=1;counts['peak']=max(counts['peak'],counts['active']);steps=[]
            try:
                while len(steps)<kw['max_actions']:
                    if kw['cancel_event'].wait(.01):return {'reason':'replaced','actions':len(steps),'steps':steps}
                    step={'kind':'sdk','method':'attack','args':[1],'result':{'accepted':True}}
                    steps.append(step);counts['steps']+=1;kw['step_callback'](step)
                    if code=='2':return {'reason':'completed','actions':len(steps),'steps':steps}
                return {'reason':'action_limit','actions':len(steps),'steps':steps}
            finally:counts['active']-=1
        with tempfile.TemporaryDirectory() as out:
            result=a.run_agent(a.MODELS[0],SCENARIO,'http://127.0.0.1:8790','synthetic-test-key',out,
                control_mode='continuous',replan_seconds=.04,wall_seconds=5,max_calls=2,max_actions=50,
                max_total_tokens=50000,request_fn=request,execute_fn=execute)
            self.assertEqual(result['reason'],'completed');self.assertEqual(counts['peak'],1)
            self.assertEqual(result['actions'],counts['steps'])
            steps=[json.loads(x) for x in (Path(out)/'steps.jsonl').read_text().splitlines()]
            self.assertEqual([s['turn'] for s in steps],[0]*(len(steps)-1)+[1])
            ds=json.loads((Path(out)/'decisions.json').read_text())
            self.assertEqual(ds[0]['execution']['reason'],'replaced')
            self.assertNotIn('synthetic-test-key',''.join(p.read_text() for p in Path(out).iterdir()))
        self.assertEqual(counts['active'],0)

    def test_action_cap_and_api_failure_stop_and_reap_current_program(self):
        for fail in (False,True):
            calls=[0];ended=threading.Event()
            def request(url,payload=None,key=None,timeout=None):
                if url.endswith('/v1/observe'):return OBS
                calls[0]+=1
                if fail and calls[0]==2:raise TimeoutError('simulated API timeout')
                return {'status':'completed','model':a.MODELS[0],'usage':{'total_tokens':100},
                    'output':[{'type':'message','content':[{'type':'output_text','text':'{"note":"loop","code":"loop"}'}]}]}
            def execute(code,scenario,url,**kw):
                n=0
                try:
                    while n<kw['max_actions']:
                        if kw['cancel_event'].wait(.01):return {'reason':'replaced','actions':n,'steps':[]}
                        n+=1;kw['step_callback']({'kind':'sdk','method':'attack','result':{}})
                    return {'reason':'action_limit','actions':n,'steps':[]}
                finally:ended.set()
            with tempfile.TemporaryDirectory() as out:
                r=a.run_agent(a.MODELS[0],SCENARIO,'http://127.0.0.1:8790','synthetic-test-key',out,
                    control_mode='continuous',replan_seconds=.03,max_actions=100 if fail else 2,
                    max_calls=3,wall_seconds=5,max_total_tokens=50000,request_fn=request,execute_fn=execute)
                self.assertEqual(r['reason'],'infrastructure_error' if fail else 'action_limit')
                self.assertLessEqual(r['actions'],100 if fail else 2);self.assertTrue(ended.is_set())
                if fail:self.assertFalse(r['usage_complete'])
