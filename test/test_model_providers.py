"""Native provider contracts and synthetic receipts; no provider/network calls."""
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import maple_agent
import model_providers as providers
from full_client_adaptive_evidence import verify_result
from full_client_bridge import ControlError, FullClientBridge
from full_client_score import EvidenceError
from test_full_client_adaptive import Harness, RUN


MODEL = 'claude-opus-5'
CHOICE = {'note': 'Synthetic attack intention', 'code': "await sdk.pressKeys(['ATTACK'],100);"}


def response(model=MODEL, index=0, **changes):
    return {'id': 'msg_synthetic_' + str(index), 'type': 'message', 'role': 'assistant', 'model': model,
            'stop_reason': 'end_turn', 'stop_sequence': None,
            'usage': {'input_tokens': 100, 'output_tokens': 20,
                      'cache_creation_input_tokens': 5, 'cache_read_input_tokens': 7},
            'content': [{'type': 'text', 'text': json.dumps(CHOICE)}]} | changes


class NativeHarness(Harness):
    def __init__(self, root, **kwargs):
        super().__init__(root, **kwargs)
        self.model = MODEL
        self.code = CHOICE['code']

    def provider(self, url, body, timeout):
        if url != providers.ENDPOINTS['anthropic']:
            raise AssertionError('wrong native provider endpoint')
        self.api_calls.append((copy.deepcopy(body), timeout))
        self.now += self.api_seconds
        return self.response_edit(response(self.model, len(self.api_calls)))

    def run(self, **overrides):
        return super().run(**({'model': self.model} | overrides))

    def result(self):
        value = super().result()
        value['controller']['model'] = self.model
        return value


class ProviderContractTests(unittest.TestCase):
    def test_original_openai_body_and_metadata_are_preserved(self):
        model = providers.OPENAI_MODELS[0]
        url, body = providers.program_request(model, 'Fixture prompt', {'observation': {}}, 1000)
        self.assertEqual(url, 'https://api.openai.com/v1/responses')
        self.assertEqual(body, {'model': model, 'store': False, 'reasoning': {'effort': 'low'},
            'instructions': 'Fixture prompt', 'input': '{"observation": {}}', 'max_output_tokens': 1000,
            'text': {'format': {'type': 'json_schema', 'name': 'maple_program', 'strict': True, 'schema': providers.SCHEMA}}})
        bound = providers.bind_request_identity(model, body, RUN, 1)
        self.assertEqual(bound['metadata'], {'maplebench_run_id': RUN, 'maplebench_cycle_index': '1'})
        self.assertTrue(providers.response_identity_matches(model, {'metadata': bound['metadata']}, RUN, 1))
        self.assertFalse(providers.response_identity_matches(model, {'metadata': bound['metadata']}, RUN, 0))
        self.assertEqual(maple_agent.MODELS[:4], providers.OPENAI_MODELS)

    def test_native_contract_uses_supported_schema_and_native_identity(self):
        for model in providers.ANTHROPIC_MODELS:
            with self.subTest(model=model):
                calls = []
                def request(url, body, key, timeout):
                    calls.append((url, body, key, timeout))
                    return response(model)
                choice, meta = maple_agent.model_decision(model, 'Fixture prompt', {'observation': {}},
                    'synthetic-test-credential', output_tokens=3000, timeout=5, request_fn=request)
                self.assertEqual(choice, CHOICE)
                self.assertEqual(len(calls), 1)
                url, body, key, timeout = calls[0]
                self.assertEqual(url, 'https://api.anthropic.com/v1/messages')
                self.assertEqual(body, {'model': model, 'system': 'Fixture prompt', 'messages': [
                    {'role': 'user', 'content': '{"observation": {}}'}], 'max_tokens': 3000,
                    'thinking': {'type': 'adaptive'},
                    'output_config': {'effort': 'low', 'format': {'type': 'json_schema', 'schema': providers.SCHEMA}}})
                self.assertEqual(providers.request_input(model, body), body['messages'][0]['content'])
                bound = providers.bind_request_identity(model, body, RUN, 0)
                self.assertEqual(bound['metadata'], {'user_id': 'maplebench:' + RUN + ':0'})
                self.assertNotIn('metadata', response(model))
                self.assertTrue(providers.response_identity_matches(model, response(model), RUN, 0))
                self.assertEqual(meta['usage'], {'input_tokens': 112, 'output_tokens': 20, 'total_tokens': 132})
                self.assertEqual(meta['native_usage'], response(model)['usage'])

    def test_provider_headers_only_pass_in_trusted_worker_stdin(self):
        sentinel = 'synthetic-test-credential'
        for model in (providers.OPENAI_MODELS[0], MODEL):
            url, body = providers.program_request(model, 'Fixture prompt', {}, 256)
            done = subprocess.CompletedProcess([], 0, stdout=b'{"ok":true,"value":{}}')
            with patch.object(maple_agent.subprocess, 'run', return_value=done) as worker:
                maple_agent.bounded_request(url, body, sentinel, 5)
            self.assertNotIn(sentinel, str(worker.call_args.args))
            sent = json.loads(worker.call_args.kwargs['input'])
            self.assertNotIn(sentinel, json.dumps(sent['payload']))
            self.assertEqual(worker.call_args.kwargs['stderr'], subprocess.DEVNULL)
            if model == MODEL:
                self.assertEqual(sent['headers'], {'Content-Type': 'application/json',
                    'anthropic-version': '2023-06-01', 'x-api-key': sentinel})
            else:
                self.assertEqual(sent['headers'], {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + sentinel})

    def test_unknown_models_and_mutable_schema_cannot_change_contract(self):
        with self.assertRaisesRegex(ValueError, 'unsupported_model'):
            providers.program_request('claude-alias', 'prompt', {}, 10)
        _, first = providers.program_request(MODEL, 'prompt', {}, 10)
        first['output_config']['format']['schema']['required'].clear()
        _, second = providers.program_request(MODEL, 'prompt', {}, 10)
        self.assertEqual(second['output_config']['format']['schema']['required'], ['note', 'code'])

    def test_thinking_is_retained_but_only_final_text_is_executable(self):
        original = response(content=[{'type': 'thinking', 'thinking': 'Synthetic fixture summary', 'signature': 'synthetic'},
            {'type': 'redacted_thinking', 'data': 'synthetic'}, *response()['content']])
        before = copy.deepcopy(original)
        choice, _ = providers.parse_program_response(MODEL, original)
        self.assertEqual(choice, CHOICE)
        self.assertEqual(original, before)

    def test_refusal_truncation_tool_use_and_wrong_model_never_execute(self):
        bad = [response(stop_reason='refusal'), response(stop_reason='max_tokens'),
            response(stop_reason='pause_turn'), response(stop_reason='tool_use'),
            response(stop_reason='stop_sequence', stop_sequence='stop'),
            response(stop_details={'type': 'refusal', 'category': 'synthetic'}),
            response(model='claude-sonnet-5'), response(role='user'), response(type='error'),
            response(content=response()['content'] * 2),
            response(content=[{'type': 'tool_use', 'name': 'unrequested'}, *response()['content']]),
            response(content=[{'type': 'thinking'}, *response()['content']]),
            response(usage={'input_tokens': 100, 'output_tokens': -1}),
            response(usage={'input_tokens': 100, 'output_tokens': 20, 'cache_read_input_tokens': True})]
        for value in bad:
            with self.subTest(value=value):
                self.assertIsNone(providers.parse_program_response(MODEL, value)[0])

    def test_note_code_json_must_be_exact_without_repair(self):
        invalid = ['```json\n' + json.dumps(CHOICE) + '\n```',
            '{"note":"ok","code":"return;","code":"return 1;"}',
            '{"note":null,"code":"return;"}', '{"note":"ok","code":""}',
            '{"note":"ok","code":"return;","extra":true}', '[]', 'null',
            json.dumps({'note': 'n' * 2001, 'code': 'return;'}),
            json.dumps({'note': 'ok', 'code': 'a' * 12001})]
        for text in invalid:
            with self.subTest(text=text[:100]):
                self.assertIsNone(providers.parse_program_response(MODEL, response(content=[{'type': 'text', 'text': text}]))[0])
                native = {'id': 'synthetic', 'model': providers.OPENAI_MODELS[0], 'status': 'completed',
                    'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}
                self.assertIsNone(providers.parse_program_response(providers.OPENAI_MODELS[0], native)[0])


class NativeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.h = NativeHarness(self.temp.name)

    def verify(self, result):
        return verify_result(result, self.h.root, protocol=self.h.p, model=self.h.model)

    def persist_trace(self, result):
        result['adaptiveTrace'] = self.h.save('adaptive.json', result['adaptive'])

    def test_native_cycles_reconstruct_request_and_reverify_raw_usage(self):
        trace = self.h.run()['trace']
        self.assertEqual(trace['status'], 'completed')
        self.assertEqual(trace['counters']['actual_total_tokens'], 264)
        checked = self.verify(self.h.result())
        self.assertEqual(checked['counters']['actual_input_tokens'], 224)
        self.assertIsNone(checked['input_intervals'])
        for cycle in trace['cycles']:
            raw = json.loads((self.h.root / cycle['response']['path']).read_text())
            self.assertNotIn('metadata', raw)
            self.assertEqual(cycle['provider_exchange']['response_id'], raw['id'])
            self.assertEqual(cycle['provider_exchange']['identity_binding'], 'local-request-response')

    def test_missing_or_forged_exchange_binding_is_rejected(self):
        self.h.run(); original = self.h.result()
        for edit in (lambda c: c.pop('provider_exchange'),
                     lambda c: c['provider_exchange'].update(endpoint='https://example.invalid'),
                     lambda c: c['provider_exchange'].update(request_sha256='0' * 64)):
            result = copy.deepcopy(original); edit(result['adaptive']['cycles'][0]); self.persist_trace(result)
            with self.assertRaises(EvidenceError):
                self.verify(result)

    def test_request_tamper_fails_even_after_rehashing_raw_artifacts_and_receipt(self):
        self.h.run(); result = self.h.result(); cycle = result['adaptive']['cycles'][0]
        body = json.loads((self.h.root / cycle['request']['path']).read_text())
        raw_response = json.loads((self.h.root / cycle['response']['path']).read_text())
        body['output_config']['effort'] = 'high'
        cycle['request'] = self.h.save(cycle['request']['path'], body)
        cycle['provider_exchange'] = providers.exchange_receipt(MODEL, body, raw_response, RUN, 0)
        self.persist_trace(result)
        with self.assertRaises(EvidenceError):
            self.verify(result)

    def test_normalized_usage_cannot_replace_raw_provider_accounting(self):
        self.h.run(); result = self.h.result(); cycle = result['adaptive']['cycles'][0]
        cycle['usage'].update(input_tokens=100, total_tokens=120)
        self.persist_trace(result)
        with self.assertRaises(EvidenceError):
            self.verify(result)

    def test_actual_token_overrun_stops_before_execution(self):
        for usage in ({'input_tokens': 100, 'output_tokens': 3001},
                      {'input_tokens': 100, 'output_tokens': 20, 'cache_read_input_tokens': 120000}):
            with self.subTest(usage=usage), tempfile.TemporaryDirectory() as folder:
                h = NativeHarness(folder, calls=1)
                h.response_edit = lambda r: r | {'usage': usage}
                trace = h.run()['trace']
                self.assertEqual(trace['status'], 'failed')
                self.assertEqual(trace['reason'], 'adaptive_actual_token_limit_exceeded')
                self.assertEqual(h.programs, [])
                self.assertEqual(len(h.api_calls), 1)

    def test_duplicate_provider_response_id_stops_without_second_execution(self):
        self.h.response_edit = lambda r: r | {'id': 'msg_duplicate'}
        trace = self.h.run()['trace']
        self.assertEqual(trace['reason'], 'adaptive_api_response_identity_invalid')
        self.assertEqual(len(self.h.programs), 1)

    def test_uncertain_transport_does_not_retry_or_leak_error_text(self):
        called = []
        def failed(*args):
            called.append(args)
            raise TimeoutError('synthetic private diagnostic')
        value = self.h.run(request_api=failed)
        self.assertEqual(len(called), 1)
        self.assertEqual(value['trace']['cycles'][0]['api_outcome'], 'uncertain')
        self.assertNotIn('synthetic private diagnostic', json.dumps(value))
        self.assertEqual(self.h.programs, [])


class ProviderCredentialTests(unittest.TestCase):
    def test_credentials_are_selected_by_provider_without_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first, second = root / 'openai.test-key', root / 'anthropic.test-key'
            for path in (first, second):
                path.write_text('synthetic-test-credential'); path.chmod(0o600)
            bridge = FullClientBridge(root / 'runs', first, provider_key_files={'anthropic': second})
            self.assertEqual(bridge._api_key_file(providers.OPENAI_MODELS[0]), first)
            self.assertEqual(bridge._api_key_file(MODEL), second)
            legacy = FullClientBridge(root / 'legacy', first)
            self.assertIsNone(legacy._api_key_file(MODEL))
            with self.assertRaisesRegex(ControlError, 'api_key_not_configured'):
                legacy.start('api', MODEL)

    def test_native_bridge_keeps_exact_bodies_and_program_without_credential(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); key = root / 'native.test-key'
            key.write_text('synthetic-test-credential'); key.chmod(0o600)
            bridge = FullClientBridge(root / 'runs', provider_key_files={'anthropic': key})
            observation = {'ready': True, 'character': {'x': 0, 'y': 0, 'hp': 100, 'maxHp': 100,
                'mp': 10, 'maxMp': 20, 'exp': 10, 'level': 180, 'mapId': 1, 'alive': True}, 'monsters': []}
            bridge.frame({'client': 'synthetic', 'ageMs': 0, 'renderAgeMs': 0, 'observation': observation})
            with patch('full_client_bridge.threading.Thread'):
                run = bridge.start('api', MODEL)
            with patch('full_client_bridge.bounded_request', return_value=response()) as request, \
                 patch.object(bridge, 'request', return_value=observation), patch.object(bridge, '_wait_for_capture'), \
                 patch('full_client_bridge.execute_program', return_value={
                    'reason': 'program_complete', 'actions': 0, 'steps': []}) as execute:
                bridge._run(run)
            self.assertEqual(bridge.run['status'], 'completed')
            request.assert_called_once()
            self.assertEqual(request.call_args.args[0], providers.ENDPOINTS['anthropic'])
            self.assertEqual(request.call_args.args[2], 'synthetic-test-credential')
            out = bridge.output / run['id']
            body = json.loads((out / 'api-request-body.json').read_text())
            self.assertEqual(body, request.call_args.args[1])
            self.assertEqual(json.loads((out / 'api-response.json').read_text()), response())
            self.assertEqual((out / 'program.js').read_text(), CHOICE['code'])
            self.assertEqual(execute.call_args.args[0], CHOICE['code'])
            result = json.loads((out / 'result.json').read_text())
            self.assertEqual(result['api']['provider_exchange'],
                providers.exchange_receipt(MODEL, body, response(), run['id']))
            for path in out.iterdir():
                if path.is_file():
                    self.assertNotIn('synthetic-test-credential', path.read_text())


class InputIntervalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.h=NativeHarness(self.temp.name)
        self.h.p['input_timeline_policy']={'id':'relay-input-interval-v1'}
        def timed(execution):
            start=round((self.h.now-self.h.program_seconds)*1000)
            execution['steps'][0]['result']['input_timing']={'basis':'relay_request_ack_v1',
                'requested_ms':start,'acknowledged_ms':start+100}
            return execution
        self.h.execution_edit=timed

    def verify(self,result):
        return verify_result(result,self.h.root,protocol=self.h.p,model=MODEL)

    def test_intervals_are_bound_to_frozen_policy_execution_and_first_input(self):
        self.h.run();checked=self.verify(self.h.result())
        self.assertEqual(checked['input_intervals'],[
            {'cycle_index':0,'rpc_id':1,'keys':['ATTACK'],'duration_ms':100,
             'requested_ms':10000,'acknowledged_ms':10100},
            {'cycle_index':1,'rpc_id':1,'keys':['ATTACK'],'duration_ms':100,
             'requested_ms':40000,'acknowledged_ms':40100}])

    def test_missing_wrong_basis_short_or_outside_intervals_are_rejected(self):
        self.h.run();original=self.h.result()
        for mutate in (lambda r:r.pop('input_timing'),
                lambda r:r['input_timing'].update(basis='native_keydown'),
                lambda r:r['input_timing'].update(requested_ms=True),
                lambda r:r['input_timing'].update(requested_ms=39998),
                lambda r:r['input_timing'].update(acknowledged_ms=40098),
                lambda r:r['input_timing'].update(acknowledged_ms=60002),
                lambda r:r['input_timing'].update(unbound=True)):
            result=copy.deepcopy(original);cycle=result['adaptive']['cycles'][1]
            mutate(cycle['execution']['steps'][0]['result'])
            cycle['execution_receipt']=self.h.save('cycles/001/execution.json',cycle['execution'])
            result['adaptiveTrace']=self.h.save('adaptive.json',result['adaptive'])
            with self.assertRaises(EvidenceError):self.verify(result)

    def test_legacy_policy_cannot_gain_unbound_input_timing(self):
        self.h.p.pop('input_timeline_policy')
        self.h.run()
        with self.assertRaises(EvidenceError):self.verify(self.h.result())


class ExpandedRpcBoundaryTests(unittest.TestCase):
    def test_new_slots_require_the_exact_frozen_adaptive_toolkit(self):
        from full_client_hero_toolkit import toolkit,profile,sdk_scenario
        policy={'id':'full-client-adaptive-pilot-v1','skill_toolkit':toolkit(),'profile':profile()}
        scenario={'adapter':'full-client'}|sdk_scenario(policy)
        message={'type':'rpc','id':1,'method':'pressKeys','args':[['SKILL_17'],100]}
        self.assertEqual(maple_agent.validate_rpc(message,scenario)[1]['keys'],['SKILL_17'])
        bad=[{'adapter':'full-client','protocol':'full-client-adaptive-pilot-v1'},
             scenario|{'protocol':'scripted-native-acceptance-v2'},
             scenario|{'skill_toolkit':toolkit()|{'level':181}}]
        for value in bad:
            with self.assertRaises(ValueError):maple_agent.validate_rpc(message,value)


if __name__ == '__main__':
    unittest.main()
