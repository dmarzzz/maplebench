"""Controller boundaries and budgets; optional real Docker isolation checks."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('maple_agent', Path(__file__).parents[1] / 'scripts/maple_agent.py')
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)

SCENARIO = {'id': 'test-fixture', 'objective': 'Defeat the fixture monster',
            'allowed_skills': [1001004], 'allowed_items': [2000000],
            'coordinate_bounds': {'min_x': -100, 'max_x': 200}}
OBS = {'nowMs': 1000, 'character': {'alive': True, 'hp': 500, 'position': {'x': 0, 'y': 334}},
       'monsters': [{'objectId': 42, 'alive': True, 'hp': 50, 'position': {'x': 100, 'y': 333}}]}


def rpc(method, args, request_id=1):
    return {'type': 'rpc', 'id': request_id, 'method': method, 'args': args}


class ProtocolBoundaryTest(unittest.TestCase):
    def test_preserves_model_target_and_skill(self):
        self.assertEqual(agent.validate_rpc(rpc('useSkill', [1001004, 42]), SCENARIO),
                         ('useSkill', {'type': 'use_skill', 'skillId': 1001004, 'targetId': 42}))
        self.assertEqual(agent.validate_rpc(rpc('moveTo', [150, 334]), SCENARIO),
                         ('moveTo', {'type': 'move_to', 'position': {'x': 150, 'y': 334}}))
        self.assertEqual(agent.validate_rpc(rpc('useItem', [2000000]), SCENARIO),
                         ('useItem', {'type': 'use_item', 'itemId': 2000000}))

    def test_self_buff_requires_both_scenario_allowlists_and_no_target(self):
        scenario = SCENARIO | {'allowed_skills':[1001004,1111002], 'self_buff_skills':[1111002]}
        self.assertEqual(agent.validate_rpc(rpc('useSkill',[1111002]),scenario),
                         ('useSkill',{'type':'use_skill','skillId':1111002}))
        for request, config in [(rpc('useSkill',[1001004]),scenario),
                                (rpc('useSkill',[1111002,42]),scenario),
                                (rpc('useSkill',[1111002]),SCENARIO | {'self_buff_skills':[1111002]})]:
            with self.assertRaises(ValueError): agent.validate_rpc(request,config)

    def test_privileged_actions_and_invalid_arguments_never_reach_server(self):
        invalid = [rpc('reset', []), rpc('add_exp', [100]), rpc('fetch', ['http://example.com']),
                   rpc('useSkill', [9999999, 42]), rpc('useItem', [2000001]),
                   rpc('moveTo', [201, 334]), rpc('moveTo', [0, 5001]), rpc('attack', [True]),
                   rpc('attack', [42.0]), rpc('attack', [-1]), rpc('attack', [2147483648]),
                   rpc('attack', [42, {'damage': 10000}]), rpc('wait', [0]), rpc('wait', [3001]),
                   rpc('observe', ['ignored']), rpc('observe', [], request_id=True),
                   rpc('observe', []) | {'url': '/admin'}, {'method': 'observe'}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                agent.validate_rpc(value, SCENARIO)

    def test_scenario_action_allowlist_and_default_no_skills_or_items(self):
        with self.assertRaises(ValueError):
            agent.validate_rpc(rpc('attack', [42]), SCENARIO | {'allowed_actions': ['move_to']})
        for value in (rpc('useSkill', [1001004, 42]), rpc('useItem', [2000000])):
            with self.assertRaises(ValueError):
                agent.validate_rpc(value, {})
        self.assertEqual(agent.validate_rpc(rpc('wait', [3000]), SCENARIO), ('wait', 3000))

    def test_game_endpoint_cannot_be_redirected_to_an_external_host_or_admin_path(self):
        self.assertEqual(agent.validate_base_url('http://127.0.0.1:8790/'), 'http://127.0.0.1:8790')
        for value in ['https://api.openai.com', 'http://example.com', 'http://user:password@localhost',
                      'http://localhost/admin', 'http://localhost?url=other', 'file:///tmp/file']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                agent.validate_base_url(value)

    def test_container_uses_external_deadline_and_has_no_credentials_or_host_mounts(self):
        with patch.dict(os.environ, {'MAPLEBENCH_DOCKER_COMMAND': 'sudo -n docker'}):
            command = agent.docker_command('node:22.19.0-bookworm-slim', 'test-container', 1.1)
        self.assertEqual(command[:3], ['sudo', '-n', 'docker'])
        for flag in ('--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
                     '--user=65534:65534', '--pids-limit=32', '--memory=256m', '--cpus=0.5', '--pull=never',
                     '--entrypoint=/usr/bin/timeout', '--signal=KILL'):
            self.assertIn(flag, command)
        for flag in ('--privileged', '-v', '--volume', '--mount', '-e', '--env-file'):
            # Node's '-e' supplies bootstrap code after the image, never Docker env.
            self.assertNotIn(flag, command[:command.index('node:22.19.0-bookworm-slim')])
        self.assertNotIn(str(Path(__file__).parents[1]), '\n'.join(command))


class ControllerBudgetTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.api_calls = []
        self.programs = []
        self.callback_values = []

    def request(self, url, payload=None, key=None, timeout=None):
        if url.endswith('/v1/observe'):
            return OBS
        self.assertEqual(url, 'https://api.openai.com/v1/responses')
        self.assertEqual(key, 'synthetic-test-key')
        self.api_calls.append(payload)
        return {'id': 'synthetic-response', 'model': payload['model'], 'status': 'completed',
                'usage': {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150},
                'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps({
                    'note': 'Attack the observed target', 'code': 'await sdk.attack(42);'})}]}]}

    def execute(self, code, scenario, base_url, **kwargs):
        self.programs.append(code)
        step = {'kind': 'sdk', 'method': 'attack', 'args': [42],
                'result': {'accepted': True, 'observation': OBS}}
        kwargs['step_callback'](step)
        return {'reason': 'program_complete', 'actions': 1, 'error': None, 'steps': [step], 'logs': []}

    def run_controller(self, **kwargs):
        defaults = {'max_calls': 2, 'max_total_tokens': 50000,
                    'request_fn': self.request, 'execute_fn': self.execute}
        return agent.run_agent(agent.MODELS[0], SCENARIO, 'http://127.0.0.1:8790',
                               'synthetic-test-key', self.directory.name, **(defaults | kwargs))

    def test_call_cap_usage_trace_and_private_configuration_exclusion(self):
        result = self.run_controller(on_decision=lambda value: self.callback_values.append(value))
        self.assertEqual(result['reason'], 'decision_limit')
        self.assertEqual(result['accountedTokens'], 300)
        self.assertTrue(result['usage_complete'])
        self.assertEqual(result['apiRequestsStarted'], 2)
        self.assertEqual(len(self.api_calls), 2)
        self.assertEqual(len(self.programs), 2)
        self.assertEqual(len(self.callback_values), 2)
        self.assertTrue(all(payload['store'] is False for payload in self.api_calls))
        self.assertTrue(all(payload['max_output_tokens'] == 1800 for payload in self.api_calls))
        artifacts = list(Path(self.directory.name).glob('*'))
        serialized = ''.join(path.read_text() for path in artifacts)
        self.assertNotIn('synthetic-test-key', serialized)
        steps = (Path(self.directory.name) / 'steps.jsonl').read_text().splitlines()
        self.assertEqual([json.loads(line)['turn'] for line in steps], [0, 1])

    def test_insufficient_tokens_makes_no_api_call(self):
        result = self.run_controller(max_total_tokens=1024)
        self.assertEqual(result['reason'], 'budget_limit')
        self.assertEqual(self.api_calls, [])

    def test_batch_budget_callback_stops_before_code_and_persists_usage(self):
        result = self.run_controller(on_decision=lambda _: False)
        self.assertEqual(result['reason'], 'budget_limit')
        self.assertEqual(result['accountedTokens'], 150)
        self.assertEqual(self.programs, [])
        decisions = json.loads((Path(self.directory.name) / 'decisions.json').read_text())
        self.assertEqual(decisions[0]['response']['usage']['total_tokens'], 150)

    def test_budget_exception_is_not_an_infrastructure_failure(self):
        def stop(_):
            raise agent.BudgetLimit()
        result = self.run_controller(on_decision=stop)
        self.assertEqual(result['reason'], 'budget_limit')
        self.assertIsNone(result['error'])

    def test_action_budget_and_terminal_observation(self):
        result = self.run_controller(max_actions=1)
        self.assertEqual(result['reason'], 'action_limit')
        self.assertEqual(len(self.api_calls), 1)
        self.api_calls.clear()
        result = self.run_controller(stop_when=lambda obs: True)
        self.assertEqual(result['reason'], 'completed')
        self.assertEqual(self.api_calls, [])

    def test_deadline_before_model_request(self):
        clock = [100.0]
        def slow_observation(*args, **kwargs):
            clock[0] += 2
            return OBS
        with patch.object(agent.time, 'monotonic', side_effect=lambda: clock[0]):
            result = self.run_controller(wall_seconds=1, request_fn=slow_observation)
        self.assertEqual(result['reason'], 'time_limit')
        self.assertEqual(self.api_calls, [])

    def test_http_child_timeout_does_not_expose_payload(self):
        # Exercise the kill-and-reap branch without an external network request.
        with patch.object(agent, 'HTTP_WORKER', 'import time; time.sleep(30)'):
            start = time.monotonic()
            with self.assertRaises(TimeoutError) as caught:
                agent.bounded_request('http://127.0.0.1:1', key='synthetic-test-key', timeout=0.15)
        self.assertLess(time.monotonic() - start, 2)
        self.assertNotIn('synthetic-test-key', str(caught.exception))

    def test_api_timeout_at_wall_deadline_keeps_unknown_usage_charged(self):
        clock = [100.0]
        def timeout_request(url, *args, **kwargs):
            if url.endswith('/v1/observe'):
                return OBS
            clock[0] += 2
            raise TimeoutError('Request deadline reached')
        with patch.object(agent.time, 'monotonic', side_effect=lambda: clock[0]):
            result = self.run_controller(wall_seconds=1, request_fn=timeout_request)
        self.assertEqual(result['reason'], 'time_limit')
        self.assertFalse(result['usage_complete'])
        self.assertEqual(result['apiRequestsStarted'], 1)
        self.assertEqual(result['apiUsage'], [])


@unittest.skipUnless(os.environ.get('MAPLEBENCH_TEST_DOCKER') == '1', 'Enable on the isolated remote runner')
class DockerIsolationTest(unittest.TestCase):
    def execute(self, code, **kwargs):
        calls = []
        def endpoint(url, payload=None, **_):
            calls.append((url, payload))
            return OBS if payload is None else {'accepted': True, 'observation': OBS}
        result = agent.execute_program(code, SCENARIO, 'http://127.0.0.1:8790',
                                       deadline=time.monotonic() + 10, program_seconds=3,
                                       request_fn=endpoint, **kwargs)
        return result, calls

    def test_sdk_round_trip_has_no_inherited_api_key(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'must-stay-on-host'}):
            result, calls = self.execute('''
              if (process.env.OPENAI_API_KEY) throw new Error('Credential crossed boundary');
              const o = await sdk.observe();
              await sdk.attack(o.monsters[0].objectId);
              await sdk.wait(10);
            ''')
        self.assertEqual(result['reason'], 'program_complete', result)
        self.assertEqual(result['actions'], 1)
        self.assertEqual(calls[-1][1], {'type': 'basic_attack', 'targetId': 42})

    def test_continuous_replanning_keeps_real_docker_program_acting(self):
        calls, actions = [], []
        def endpoint(url, payload=None, key=None, timeout=None):
            if url.endswith('/v1/observe'): return OBS
            if url.endswith('/v1/action'):
                actions.append(payload)
                return {'accepted': True, 'observation': OBS}
            calls.append(payload)
            if len(calls) == 2:
                before = len(actions); time.sleep(.25)
                self.assertGreater(len(actions), before, 'Real sandbox stopped during API planning')
            code = 'while(true){await sdk.attack(42);await sdk.wait(80);}' if len(calls)==1 else 'await sdk.attack(42);'
            return {'status':'completed','model':agent.MODELS[0],'usage':{'total_tokens':100},
                    'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'note':'control','code':code})}]}]}
        with tempfile.TemporaryDirectory() as out:
            r=agent.run_agent(agent.MODELS[0],SCENARIO,'http://127.0.0.1:8790','synthetic-test-key',out,
                              control_mode='continuous',replan_seconds=1,max_calls=2,max_actions=50,
                              wall_seconds=10,max_total_tokens=50000,request_fn=endpoint)
            self.assertEqual(r['reason'],'decision_limit',r)
            self.assertEqual(r['actions'],len(actions))
            ds=json.loads((Path(out)/'decisions.json').read_text())
            self.assertEqual(ds[0]['execution']['reason'],'replaced')
            self.assertEqual(ds[1]['execution']['reason'],'program_complete')

    def test_targetless_buff_round_trip(self):
        with patch.dict(SCENARIO, {'allowed_skills':[1111002], 'self_buff_skills':[1111002]}):
            result, calls = self.execute('await sdk.useSkill(1111002);')
        self.assertEqual(result['reason'], 'program_complete', result)
        self.assertEqual(calls[-1][1], {'type':'use_skill','skillId':1111002})

    def test_unapproved_skill_and_forged_privileged_request_are_rejected(self):
        result, calls = self.execute('await sdk.useSkill(9999999, 42);')
        self.assertEqual(result['reason'], 'program_error', result)
        self.assertEqual(calls, [])
        result, calls = self.execute('''
          process.stdout.write(JSON.stringify({type:'rpc',id:1,method:'reset',args:[]})+'\\n');
          await new Promise(resolve => setTimeout(resolve, 100));
        ''')
        self.assertTrue(any(step['kind'] == 'rejected_rpc' for step in result['steps']))
        self.assertEqual(calls, [])

    def test_infinite_loop_and_action_spam_are_bounded(self):
        start = time.monotonic()
        result, _ = self.execute('while (true) {}')
        self.assertIn(result['reason'], ('program_timeout', 'program_error'))
        self.assertLess(time.monotonic() - start, 8)
        result, calls = self.execute('for(let i=0;i<10;i++) await sdk.attack(42);', max_actions=2)
        self.assertEqual(result['reason'], 'action_limit', result)
        self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
