"""Synthetic, deterministic adaptive protocol tests. No services or API calls."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import full_client_adaptive as adaptive
from full_client_adaptive_evidence import verify_result
from full_client_score import EvidenceError, score_trial
from full_client_trial import TrialError, validate_spec

RUN='a'*32
MODEL='gpt-6-astra'

class Harness:
    def __init__(self, root, *, calls=2):
        self.root=Path(root);self.now=0.;self.api_calls=[];self.programs=[];self.observations=[]
        self.p=copy.deepcopy(adaptive.DEFAULT_PROTOCOL);self.p['max_api_requests']=calls
        self.api_seconds=10;self.program_seconds=20;self.response_edit=lambda r:r
        self.code="await sdk.pressKeys(['ATTACK'],100);"
        self.execution_edit=lambda e:e
    def observation(self):
        value={'ready':True,'ageMs':0,'renderAgeMs':0,'character':{'x':len(self.observations),'y':1,
            'level':180,'hp':100,'maxHp':100,'mp':100,'maxMp':100,'exp':0,'alive':True,'mapId':1},'monsters':[]}
        self.observations.append(value);return value
    def raw(self, name, raw):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        return {'path':name,'sha256':hashlib.sha256(raw).hexdigest()}
    def save(self, name, value):return self.raw(name,json.dumps(value).encode())
    def provider(self, url, body, timeout):
        self.api_calls.append((copy.deepcopy(body),timeout));self.now+=self.api_seconds
        response={'id':'resp_synthetic_'+str(len(self.api_calls)), 'status':'completed','model':MODEL,
            'metadata':body['metadata'],'usage':{'input_tokens':100,'output_tokens':20,'total_tokens':120},
            'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'note':'test intention','code':self.code})}]}]}
        return self.response_edit(response)
    def execute(self, code, **kwargs):
        self.programs.append((code,kwargs));self.now+=min(self.program_seconds,kwargs['program_seconds'])
        step={'kind':'sdk','rpcId':1,'method':'pressKeys','args':[['ATTACK'],100],
              'result':{'accepted':True,'observation':self.observation()}}
        kwargs['step_callback'](step)
        return self.execution_edit({'actions':1,'actionAttempts':1,'rpcRequests':1,'steps':[step],
                                    'reason':'program_complete','error':None})
    def run(self, **overrides):
        initial=self.observation()
        args=dict(run_id=RUN,model=MODEL,protocol=self.p,initial=initial,observe=lambda timeout:self.observation(),
            request_api=self.provider,execute=self.execute,persist_json=self.save,persist_bytes=self.raw,
            cancel_check=lambda:None,clock=lambda:self.now,wall_clock=lambda:1000+self.now)
        args.update(overrides);self.value=adaptive.run_adaptive(**args);return self.value
    def result(self):
        trace=self.value['trace'];origin=100;cycles=trace['cycles']
        api=[c for c in cycles if c.get('api_outcome')=='confirmed']
        executed=[c for c in cycles if c.get('execution') and c['execution']['actions']]
        if executed:
            trace['timing'].update(first_input_started_ms=executed[0]['timing']['program_started_ms'],
                                  first_input_acked_ms=executed[0]['timing']['program_started_ms']+100)
        result={'schema_version':1,'protocol':adaptive.PROTOCOL,'source':'full-client-adaptive-pilot',
            'controller':{'id':RUN,'model':MODEL,'status':trace['status'],'adaptiveProtocol':self.p},
            'initial':self.value['initial'],'adaptive':trace,'adaptiveTrace':self.save('adaptive.json',trace),
            'program':{'steps':self.value['steps'],'actions':trace['counters']['actions'],
                'actionAttempts':trace['counters']['action_attempts'],'rpcRequests':trace['counters']['sdk_requests']},
            'timing':{'startedAtMs':999900,'endedAtMs':1000000+round(self.now*1000)},
            'timeline':{'adaptive_started_ms':origin,'program_started_ms':origin,
                'adaptive_ended_ms':origin+round(self.now*1000),'program_ended_ms':origin+round(self.now*1000),
                'first_input_started_ms':origin+trace['timing']['first_input_started_ms'] if executed else None,
                'first_input_acked_ms':origin+trace['timing']['first_input_acked_ms'] if executed else None,
                'api_started_ms':origin+api[0]['timing']['api_started_ms'],
                'api_ended_ms':origin+api[-1]['timing']['api_ended_ms']}}
        return result

class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.h=Harness(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_repeated_fresh_observations_and_exact_code(self):
        result=self.h.run();trace=result['trace']
        self.assertEqual(trace['status'],'completed');self.assertEqual(trace['reason'],'api_request_limit')
        self.assertEqual(trace['counters']['actions'],2);self.assertEqual(trace['counters']['actual_total_tokens'],240)
        self.assertNotEqual(trace['cycles'][0]['observation'],trace['cycles'][1]['observation'])
        self.assertTrue(all(code==self.h.code for code,_ in self.h.programs))
        request=self.h.api_calls[1][0];value=json.loads(request['input'])
        self.assertEqual(value['recent_programs'][0]['code'],self.h.code)
        self.assertEqual(value['remaining_actions'],self.h.p['max_actions']-1)
        self.assertEqual(request['metadata'],{'maplebench_run_id':RUN,'maplebench_cycle_index':'1'})
        checked=verify_result(self.h.result(),self.h.root,protocol=self.h.p,model=MODEL)
        self.assertEqual(checked['api_ms'],20000);self.assertEqual(checked['wall_elapsed_ms'],60000)
        self.assertIsNone(checked['authoritative_peak_xp_per_minute'])
    def test_five_minute_clock_counts_inference_and_program_time(self):
        self.h.p['max_api_requests']=16
        value=self.h.run();self.assertEqual(value['trace']['reason'],'wall_time_limit')
        self.assertEqual(value['trace']['timing']['wall_elapsed_ms'],300000)
        self.assertEqual(len(self.h.api_calls),10)
        self.assertEqual(verify_result(self.h.result(),self.h.root,protocol=self.h.p,model=MODEL)['wall_elapsed_ms'],300000)
    def test_late_api_response_never_executes(self):
        self.h.api_seconds=301;value=self.h.run()
        self.assertEqual(value['trace']['reason'],'wall_time_limit');self.assertEqual(self.h.programs,[])
        self.assertEqual(len(self.h.api_calls),1);self.assertLessEqual(self.h.api_calls[0][1],50)
    def test_uncertain_provider_outcome_stops_without_replay(self):
        def failed(*args):self.h.api_calls.append(args);raise TimeoutError('private detail')
        value=self.h.run(request_api=failed);self.assertEqual(value['trace']['status'],'failed')
        self.assertEqual(value['trace']['cycles'][0]['api_outcome'],'uncertain')
        self.assertEqual(len(self.h.api_calls),1);self.assertEqual(self.h.programs,[])
        self.assertNotIn('private detail',json.dumps(value))
    def test_duplicate_response_id_cannot_be_reused_as_a_second_cycle(self):
        self.h.response_edit=lambda r:r|{'id':'resp_same'}
        trace=self.h.run()['trace']
        self.assertEqual(trace['status'],'failed');self.assertEqual(len(self.h.programs),1)
        self.assertEqual(trace['reason'],'adaptive_api_response_identity_invalid')

    def test_stale_acknowledgement_is_not_accepted_as_checked_action_evidence(self):
        self.h.run();result=self.h.result();cycle=result['adaptive']['cycles'][0]
        cycle['execution']['steps'][0]['result']['observation']['ageMs']=1500
        cycle['execution_receipt']=self.h.save('cycles/000/execution.json',cycle['execution'])
        result['adaptiveTrace']=self.h.save('adaptive.json',result['adaptive'])
        with self.assertRaises(EvidenceError):verify_result(result,self.h.root,protocol=self.h.p,model=MODEL)

    def test_wrong_model_or_metadata_or_usage_never_executes(self):
        for mutate in (lambda r:r|{'model':'gpt-5.6-sol'},lambda r:r|{'metadata':{}},
                       lambda r:r|{'usage':None},lambda r:r|{'usage':{'input_tokens':1,'output_tokens':2,'total_tokens':4}}):
            with self.subTest(mutate=mutate):
                h=Harness(self.h.root);h.response_edit=mutate
                self.assertEqual(h.run()['trace']['status'],'failed');self.assertEqual(h.programs,[])
    def test_invalid_program_is_reported_and_new_model_cycle_may_fix_it(self):
        first=[True]
        def invalid(r):
            if first.pop() if first else False:r['output']=[]
            return r
        self.h.response_edit=invalid;trace=self.h.run()['trace']
        self.assertEqual(trace['cycles'][0]['status'],'invalid_program')
        self.assertEqual(len(self.h.programs),1)
        self.assertIn('no code executed',json.loads(self.h.api_calls[1][0]['input'])['recent_programs'][0]['error'])
        verify_result(self.h.result(),self.h.root,protocol=self.h.p,model=MODEL)
    def test_declared_function_is_never_silently_invoked(self):
        self.h.code='async function run(){ await sdk.pressKeys(["ATTACK"],100); }'
        self.h.run();self.assertEqual(self.h.programs[0][0],self.h.code)
    def test_token_reservation_prevents_even_first_call(self):
        self.h.p['max_total_tokens']=1024
        trace=self.h.run()['trace'];self.assertEqual(trace['reason'],'token_reservation_limit')
        self.assertEqual(self.h.api_calls,[]);self.assertEqual(trace['counters']['api_requests_started'],0)
    def test_aggregate_action_and_sdk_limits_are_not_reset(self):
        self.h.p['max_actions']=1;trace=self.h.run()['trace']
        self.assertEqual(trace['reason'],'action_limit');self.assertEqual(len(self.h.api_calls),1)
        self.h=Harness(self.h.root);self.h.p['max_sdk_requests']=1
        self.assertEqual(self.h.run()['trace']['reason'],'sdk_request_limit')
    def test_counter_or_input_receipt_uncertainty_stops(self):
        self.h.execution_edit=lambda e:e|{'actions':2}
        self.assertEqual(self.h.run()['trace']['status'],'failed');self.assertEqual(len(self.h.api_calls),1)
    def test_byte_tampering_and_cross_cycle_reference_refused(self):
        self.h.run();result=self.h.result()
        ref=result['adaptive']['cycles'][0]['program'];path=self.h.root/ref['path'];raw=path.read_bytes()
        path.write_bytes(raw+b' ')
        with self.assertRaises(EvidenceError):verify_result(result,self.h.root,protocol=self.h.p,model=MODEL)
        path.write_bytes(raw);result['adaptive']['cycles'][1]['program']=copy.deepcopy(ref)
        with self.assertRaises(EvidenceError):verify_result(result,self.h.root,protocol=self.h.p,model=MODEL)
    def test_aggregate_totals_recomputed_from_all_cycles(self):
        self.h.run();result=self.h.result();result['adaptive']['counters']['actual_total_tokens']=120
        result['adaptiveTrace']=self.h.save('adaptive.json',result['adaptive'])
        with self.assertRaises(EvidenceError):verify_result(result,self.h.root,protocol=self.h.p,model=MODEL)
    def test_class_contract_is_frozen_and_prompt_uses_declared_class(self):
        self.h.p['profile']={'id':'bowmaster-180','class_name':'Bowmaster','level':180,'skill_keys':{'PRIMARY_SKILL':'Hurricane'}}
        text=adaptive.prompt(self.h.p);self.assertIn('Hurricane',text);self.assertNotIn('Combo Attack',text)
        malformed=copy.deepcopy(self.h.p);malformed['wall_seconds']=True
        with self.assertRaises(adaptive.AdaptiveError):adaptive.validate_protocol(malformed)
    def test_native_bowmaster_names_and_mage_teleport_are_preserved(self):
        profile={'id':'bowmaster-180','class_name':'Bowmaster','level':180,
                 'skill_keys':{'PRIMARY_SKILL':'Hurricane','BUFF_1':'Soul Arrow : Bow'}}
        self.h.p['profile']=profile
        self.assertEqual(adaptive.validate_protocol(self.h.p)['profile'],profile)
        text=adaptive.prompt(self.h.p)
        self.assertIn('Soul Arrow : Bow',text)
        self.assertIn('A mapped native Teleport skill is allowed.',text)
        self.assertNotIn('No teleport',text)

    def test_neutral_skill_slots_are_versioned_and_legacy_keys_unchanged(self):
        from maple_agent import validate_rpc
        rpc={'type':'rpc','id':1,'method':'pressKeys','args':[['PRIMARY_SKILL'],100]}
        with self.assertRaises(ValueError):validate_rpc(rpc,{'adapter':'full-client'})
        self.assertEqual(validate_rpc(rpc,{'adapter':'full-client','protocol':adaptive.PROTOCOL})[1]['keys'],['PRIMARY_SKILL'])
        rpc['args'][0]=['BRANDISH']
        self.assertEqual(validate_rpc(rpc,{'adapter':'full-client'})[1]['keys'],['BRANDISH'])
        with self.assertRaises(ValueError):validate_rpc(rpc,{'adapter':'full-client','protocol':adaptive.PROTOCOL})

    def test_trial_spec_version_separates_legacy_and_adaptive(self):
        from test_full_client_trial import spec
        old=spec();old['budgets']['max_api_requests']=2
        with self.assertRaises(TrialError):validate_spec(old)
        new=spec();new.update(schema_version=2,protocol=adaptive.PROTOCOL)
        new['budgets'].update(total_seconds=1200,operation_seconds=360,controller_seconds=300,max_api_requests=12,
                              max_output_tokens=36000,max_total_tokens=120000)
        self.assertEqual(validate_spec(new),new)
        new['protocol']='future-ranking'
        with self.assertRaises(TrialError):validate_spec(new)
    def test_interleaved_persistence_timing_preserves_signed_net_xp(self):
        from test_full_client_score import fixture
        value=fixture();value.update(schema_version=2,protocol=adaptive.PROTOCOL)
        session=value['session'];session.update(protocol=adaptive.PROTOCOL,controller_started_at_ms=2100,
            api_ended_at_ms=6000,adaptive_trace_sha256='a'*64,
            api_intervals=[{'index':0,'started_at_ms':2200,'ended_at_ms':3000},
                           {'index':1,'started_at_ms':5500,'ended_at_ms':6000}])
        value['final']['character']['exp']-=500
        score=score_trial(value);self.assertEqual(score['metrics']['net_xp'],-500);self.assertEqual(score['timing']['api_ms'],1300)
        self.assertIsNone(score['authoritative_peak_xp_per_minute'])
        value['schema_version']=1
        with self.assertRaises(EvidenceError):score_trial(value)

if __name__=='__main__':unittest.main()
