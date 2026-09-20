"""Controller boundaries and budgets; optional real Docker isolation checks."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from docker_binding_fixture import local_binding
from full_client_docker import DockerBindingError

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


class ExecutorAcknowledgementTest(unittest.TestCase):
    """Drive the trusted executor protocol without launching a process."""
    def execute_messages(self, messages, endpoint=None, *, program_seconds=10,
                         max_actions=10, cancelled_wait=False, write=None, docker_binding=None,
                         construction_error=None, launch_error=None, cleanup_error=None,
                         validation_delay=0, cancel_after_validation=False, deadline_seconds=None):
        clock=[100.0]
        process=Mock()
        process.poll.return_value=None
        selector=Mock()
        selector.select.return_value=[(Mock(data='stdout',fileobj=process.stdout),1)]
        calls=[]
        def request(url,payload=None,timeout=None):
            calls.append((url,payload,timeout))
            return endpoint(url,payload,timeout,clock) if endpoint else {'accepted':True,'observation':OBS}
        def wait(delay):
            if not cancelled_wait: clock[0]+=delay
            return cancelled_wait
        event=Mock()
        event.is_set.return_value=False
        event.wait.side_effect=wait
        validate=agent.validate_rpc
        def validate_message(*args):
            value=validate(*args)
            clock[0]+=validation_delay
            if cancel_after_validation:event.is_set.return_value=True
            return value
        packets=b''.join(json.dumps(value).encode()+b'\n' for value in messages+[{'type':'done','ok':True}])
        original = agent.docker_command
        with patch.object(agent,'docker_command',side_effect=construction_error,
                          wraps=original if docker_binding else None,
                          **({} if docker_binding else {'return_value':['unused-test-command']})), \
             patch.object(agent.subprocess,'Popen',return_value=process,side_effect=launch_error) as launch, \
             patch.object(agent.subprocess,'run',side_effect=cleanup_error) as cleanup, \
             patch.object(agent.selectors,'DefaultSelector',return_value=selector), \
             patch.object(agent.os,'set_blocking'), patch.object(agent.os,'read',return_value=packets), \
             patch.object(agent,'_write_packet',side_effect=write), \
             patch.object(agent,'validate_rpc',side_effect=validate_message), \
             patch.object(agent.time,'monotonic',side_effect=lambda:clock[0]):
            try:
                result=agent.execute_program('await sdk.observe();',SCENARIO|{'adapter':'full-client'},
                    'http://127.0.0.1:8790',deadline=100+(program_seconds+2 if deadline_seconds is None else deadline_seconds),program_seconds=program_seconds,
                    max_actions=max_actions,request_fn=request,cancel_event=event,docker_binding=docker_binding)
            finally:
                self.launch_call, self.cleanup_call = launch.call_args, cleanup.call_args
        return result,calls,clock[0]

    def test_bound_execution_and_cleanup_use_same_invocation_despite_hostile_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            binding = local_binding(self, folder)
            def mutate(*_):
                os.environ['MAPLEBENCH_DOCKER_COMMAND'] = 'changed private-launcher'
                os.environ['DOCKER_HOST'] = 'tcp://changed.invalid'
                return {'accepted':True,'observation':OBS}
            with patch.dict(os.environ, {'PATH':'/private/bin','HOME':'/private/home',
                    'DOCKER_HOST':'tcp://private.invalid','DOCKER_CONTEXT':'private-context',
                    'DOCKER_CONFIG':'/private/config','MAPLEBENCH_DOCKER_COMMAND':'private-launcher'}):
                result, _, _ = self.execute_messages([rpc('observe',[])], mutate, docker_binding=binding)
            launch, cleanup = self.launch_call, self.cleanup_call
            prefix = launch.args[0][:launch.args[0].index('run')]
            self.assertEqual(prefix[0], binding['executable']['path'])
            self.assertEqual(prefix[-2:], ['--host','unix://' + binding['socket_path']])
            self.assertEqual(cleanup.args[0][:-3], prefix)
            self.assertEqual(cleanup.kwargs['env'], launch.kwargs['env'])
            self.assertEqual(set(launch.kwargs['env']), {'PATH','LC_ALL','HOME','DOCKER_CONFIG'})
            self.assertNotIn('private-', str((launch, cleanup)))
            self.assertEqual(result['reason'], 'program_complete')
            self.assertFalse(Path(launch.kwargs['env']['DOCKER_CONFIG']).exists())

    def test_bound_config_removed_on_construction_launch_and_cleanup_failure(self):
        for stage in ('construction','launch','cleanup','binding_cleanup'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder:
                binding = local_binding(self, folder)
                original = agent.bound_invocation
                configs=[]
                from contextlib import contextmanager
                @contextmanager
                def track(value):
                    with original(value) as invocation:
                        configs.append(Path(invocation[1]['DOCKER_CONFIG']))
                        yield invocation
                def mutate(*_):
                    Path(binding['executable']['path']).write_bytes(b'changed after launch')
                    return {'accepted':True,'observation':OBS}
                with patch.object(agent,'bound_invocation',track):
                    if stage == 'construction':
                        with self.assertRaisesRegex(ValueError,'synthetic construction'):
                            self.execute_messages([],docker_binding=binding,construction_error=ValueError('synthetic construction'))
                    else:
                        result, _, _ = self.execute_messages([rpc('observe',[])],
                            mutate if stage=='binding_cleanup' else None, docker_binding=binding,
                            launch_error=OSError('private launch') if stage=='launch' else None,
                            cleanup_error=OSError('private cleanup') if stage=='cleanup' else None)
                        self.assertNotIn('private launch',str(result))
                        if stage=='binding_cleanup':
                            self.assertEqual(result['reason'],'infrastructure_error')
                            self.assertEqual(result['error'],'docker_executable_changed')
                            self.assertIsNone(self.cleanup_call)
                self.assertEqual(len(configs),1)
                self.assertFalse(configs[0].exists())

    def test_endpoint_timeout_at_program_end_is_uncertain_not_a_clean_timeout(self):
        for method,args in [('attack',[42]),('pressKeys',[['LEFT'],100]),('observe',[])]:
            def timeout(url,payload,remaining,clock):
                clock[0]=110
                raise TimeoutError('private endpoint details must not be saved')
            with self.subTest(method=method):
                result,calls,_=self.execute_messages([rpc(method,args)],timeout)
                self.assertEqual(result['reason'],'infrastructure_error')
                self.assertEqual(result['error'],'endpoint_timeout')
                self.assertEqual(result['actions'],0)
                self.assertEqual(result['actionAttempts'],0 if method=='observe' else 1)
                self.assertEqual(len(calls),1)
                self.assertEqual(result['steps'][0]['kind'],'sdk_error')
                self.assertEqual(result['steps'][0]['outcome'],'unavailable' if method=='observe' else 'uncertain')
                self.assertNotIn('private endpoint',json.dumps(result))

    def test_acknowledged_action_is_preserved_when_return_to_sandbox_times_out(self):
        def timeout_reply(pipe,packet,end):
            if packet.get('id'): raise TimeoutError('Sandbox reply timed out')
        result,calls,_=self.execute_messages([rpc('attack',[42])],write=timeout_reply)
        self.assertEqual(result['actions'],1)
        self.assertEqual(result['actionAttempts'],1)
        self.assertEqual(len(result['steps']),1)
        self.assertTrue(result['steps'][0]['result']['accepted'])
        self.assertEqual(len(calls),1)

    def test_rejected_requests_consume_attempt_budget_without_counting_as_actions(self):
        result,calls,_=self.execute_messages([rpc('attack',[42],i) for i in (1,2,3)],
            lambda *_:{'accepted':False,'observation':OBS},max_actions=2)
        self.assertEqual(result['reason'],'action_limit')
        self.assertEqual(result['actions'],0)
        self.assertEqual(result['actionAttempts'],2)
        self.assertEqual(len(calls),2)
        self.assertEqual(len(result['steps']),2)

    def test_hold_and_ack_reserve_must_fit_or_tail_is_passive_and_cancellable(self):
        for cancelled in (False,True):
            with self.subTest(cancelled=cancelled):
                result,calls,ended=self.execute_messages([rpc('pressKeys',[['LEFT'],1500])],
                    program_seconds=1.9,cancelled_wait=cancelled)
                self.assertEqual(result['reason'],'replaced' if cancelled else 'time_limit')
                self.assertEqual(result['actions'],0)
                self.assertEqual(result['actionAttempts'],0)
                self.assertEqual(result['steps'],[])
                self.assertEqual(calls,[])
                self.assertEqual(ended,100 if cancelled else 101.9)

    def test_short_keyboard_endpoint_budget_never_dispatches_or_records_uncertainty(self):
        for remaining in (0.7,2.999):
            for cancelled in (False,True):
                with self.subTest(remaining=remaining,cancelled=cancelled):
                    result,calls,ended=self.execute_messages([rpc('pressKeys',[['LEFT'],60])],
                        program_seconds=remaining,cancelled_wait=cancelled)
                    self.assertEqual(result['reason'],'replaced' if cancelled else 'time_limit')
                    self.assertEqual((result['actions'],result['actionAttempts'],result['rpcRequests']),(0,0,1))
                    self.assertEqual(result['steps'],[])
                    self.assertEqual(calls,[])
                    self.assertEqual(ended,100 if cancelled else 100+remaining)

    def test_full_keyboard_endpoint_budget_preserves_hold_and_timeout(self):
        for remaining in (3,3.001):
            for hold in (60,1500):
                with self.subTest(remaining=remaining,hold=hold):
                    result,calls,_=self.execute_messages([rpc('pressKeys',[['LEFT'],hold])],program_seconds=remaining)
                    self.assertEqual(result['reason'],'program_complete')
                    self.assertEqual((result['actions'],result['actionAttempts'],result['rpcRequests']),(1,1,1))
                    self.assertEqual(calls[0][1]['durationMs'],hold)
                    self.assertEqual(calls[0][2],3)

    def test_keyboard_admission_rechecks_clock_after_rpc_validation(self):
        result,calls,ended=self.execute_messages([rpc('pressKeys',[['LEFT'],60])],
            program_seconds=3.2,validation_delay=0.3)
        self.assertEqual(result['reason'],'time_limit')
        self.assertEqual((result['actions'],result['actionAttempts'],result['rpcRequests']),(0,0,1))
        self.assertEqual(result['steps'],[])
        self.assertEqual(calls,[])
        self.assertEqual(ended,103.2)

    def test_keyboard_admission_rechecks_cancellation_after_rpc_validation(self):
        result,calls,_=self.execute_messages([rpc('pressKeys',[['LEFT'],60])],cancel_after_validation=True)
        self.assertEqual(result['reason'],'replaced')
        self.assertEqual((result['actions'],result['actionAttempts'],result['rpcRequests']),(0,0,1))
        self.assertEqual(result['steps'],[])
        self.assertEqual(calls,[])

    def test_keyboard_passive_tail_respects_outer_deadline(self):
        result,calls,ended=self.execute_messages([rpc('pressKeys',[['LEFT'],60])],
            program_seconds=20,deadline_seconds=0.7)
        self.assertEqual(result['reason'],'time_limit')
        self.assertEqual(result['actionAttempts'],0)
        self.assertEqual(result['steps'],[])
        self.assertEqual(calls,[])
        self.assertEqual(ended,100.7)


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

    def test_rejected_attempt_budget_is_shared_across_programs(self):
        def rejected(code,scenario,base_url,**kwargs):
            self.assertEqual(kwargs['max_actions'],2-len(self.programs))
            self.programs.append(code)
            step={'kind':'sdk','method':'attack','args':[42],'result':{'accepted':False,'observation':OBS}}
            kwargs['step_callback'](step)
            return {'reason':'program_complete','actions':0,'actionAttempts':1,'error':None,'steps':[step]}
        result=self.run_controller(execute_fn=rejected,max_actions=2,max_calls=3)
        self.assertEqual(result['reason'],'action_limit')
        self.assertEqual(result['actions'],0)
        self.assertEqual(result['actionAttempts'],2)
        self.assertEqual(len(self.api_calls),2)
        self.assertEqual(len(self.programs),2)

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

    def test_async_body_and_explicit_invocation_execute_but_declaration_is_not_repaired(self):
        for code,expected in [('await sdk.observe();',1),
                ('async function run() { await sdk.observe(); }\nawait run();',1),
                ('async function run() { await sdk.observe(); }',0)]:
            with self.subTest(code=code):
                result,calls=self.execute(code)
                self.assertEqual(result['reason'],'program_complete',result)
                self.assertEqual(len(calls),expected)
                self.assertEqual(len(result['steps']),expected)
                self.assertEqual(result['actions'],0)

    def test_frozen_local_sudo_binding_executes_existing_image_under_hostile_routing(self):
        if not sys.platform.startswith('linux') or not Path('/usr/bin/sudo').is_file():
            self.skipTest('Requires the vetted Linux sudo Docker runner')
        from full_client_docker import freeze_binding
        from full_client_freeze import inspect_image
        command=['/usr/bin/sudo','-n','/usr/bin/docker']
        binding=freeze_binding(command,'/var/run/docker.sock')
        image_id=inspect_image(command,'node:22.19.0-bookworm-slim',5,binding['socket_path'])
        with patch.dict(os.environ,{'DOCKER_HOST':'tcp://unused.invalid:2375','DOCKER_CONTEXT':'unused',
                'DOCKER_CONFIG':'/private/unused','HOME':'/private/unused','PATH':'/private/unused',
                'MAPLEBENCH_DOCKER_COMMAND':'unused-launcher','OPENAI_API_KEY':'must-stay-on-host'}):
            result,calls=self.execute('''
              if (process.env.OPENAI_API_KEY) throw new Error('Credential crossed boundary');
              await sdk.attack((await sdk.observe()).monsters[0].objectId);
            ''',docker_image=image_id,docker_binding=binding)
        self.assertEqual(result['reason'],'program_complete',result)
        self.assertEqual(result['actions'],1)
        self.assertEqual(len(calls),2)

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

    def test_full_client_deadline_preserves_uncertain_and_undispatched_actions(self):
        # Real Docker/SDK exchange, synthetic endpoint only: no game input or API.
        for mode in ('endpoint_timeout','insufficient_hold_time'):
            with self.subTest(mode=mode):
                calls=[]
                def endpoint(url,payload=None,timeout=None):
                    calls.append((url,payload))
                    time.sleep(timeout)
                    raise TimeoutError('private test endpoint detail')
                code=('await sdk.pressKeys(["LEFT"],100);' if mode=='endpoint_timeout' else
                      'await sdk.wait(1700); await sdk.pressKeys(["LEFT"],1500);')
                # The timeout case must admit a full three-second endpoint
                # interval after Docker startup; the other case must not.
                program_seconds=6 if mode=='endpoint_timeout' else 3
                start=time.monotonic()
                result=agent.execute_program(code,{'adapter':'full-client'},'http://127.0.0.1:8790',
                    deadline=start+program_seconds+2,program_seconds=program_seconds,request_fn=endpoint)
                self.assertLess(time.monotonic()-start,program_seconds+4)
                self.assertEqual(result['actions'],0)
                if mode=='endpoint_timeout':
                    self.assertEqual(result['reason'],'infrastructure_error',result)
                    self.assertEqual(result['actionAttempts'],1)
                    self.assertEqual(len(calls),1)
                    self.assertEqual(result['steps'][0]['outcome'],'uncertain')
                    self.assertNotIn('private test endpoint',json.dumps(result))
                else:
                    self.assertEqual(result['reason'],'time_limit',result)
                    self.assertEqual(result['actionAttempts'],0)
                    self.assertEqual(calls,[])
                    self.assertTrue(all(step['method']=='wait' for step in result['steps']))


if __name__ == '__main__':
    unittest.main()
