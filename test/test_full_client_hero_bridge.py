"""Offline expanded native dispatch checks; no API, game, or Docker execution."""
import json
import sys
import time
from pathlib import Path
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from full_client_bridge import ControlError
from full_client_native import HERO_TOOLKIT_PROTOCOL,contract,program
from full_client_hero_toolkit import sdk_scenario
from full_client_session import SessionCoordinator
from maple_agent import validate_rpc
import test_full_client_native as native_fixtures


class HeroBridgeTests(unittest.TestCase):
    setUp=native_fixtures.NativeTests.setUp
    close_leases=native_fixtures.NativeTests.close_leases

    def start(self,duration=120,**changes):
        self.config=contract('hero','a'*64,protocol=HERO_TOOLKIT_PROTOCOL)
        with mock.patch('full_client_bridge.threading.Thread'):
            return self.bridge.start('script',None,duration,
                **(self.options|{'native_acceptance':self.config}|changes))

    def test_native_frozen_bounds_and_toolkit_survive_ui_and_recording_owner(self):
        run=self.start()
        self.assertEqual((run['programSeconds'],run['controllerSeconds'],
                          run['actionLimit'],run['sdkRequestLimit']),(120,120,128,600))
        self.assertEqual(run['nativeAcceptance'],self.config)
        self.assertEqual(self.bridge.status()['run']['nativeAcceptance'],self.config)
        self.assertEqual(self.bridge.recording_owner(run['id'])['nativeAcceptance'],self.config)
        self.assertFalse(run['publicationEligible'])

    def test_native_duration_and_toolkit_are_not_caller_budgets(self):
        for duration in (30,119,121,300):
            with self.subTest(duration=duration),self.assertRaisesRegex(ControlError,'native_acceptance_private_contract_required'):
                self.start(duration)
        native=contract('hero','a'*64,protocol=HERO_TOOLKIT_PROTOCOL)
        for changed in (native|{'max_actions':129},native|{'skill_toolkit':{}},native|{'wall_seconds':121}):
            with self.assertRaisesRegex(ControlError,'invalid_native_acceptance'):
                self.start(native_acceptance=changed)

    def test_each_expanded_slot_is_validated_in_both_executor_and_relay(self):
        self.start()
        def acknowledge(_):self.bridge.pending['ack']={'ok':True}
        with mock.patch.object(self.bridge.lock,'wait',side_effect=acknowledge):
            for skill in self.config['skill_toolkit']['skills']:
                keys=[skill['slot']]
                request={'type':'rpc','id':1,'method':'pressKeys','args':[keys,100]}
                self.assertEqual(validate_rpc(request,{'adapter':'full-client'}|sdk_scenario(self.config))[1]['keys'],keys)
                reply=self.bridge.request('/v1/action',{'type':'press_keys','keys':keys,'durationMs':100})
                self.assertTrue(reply['accepted'])
            with self.assertRaises(ValueError):
                self.bridge.request('/v1/action',{'type':'press_keys','keys':['SKILL_18'],'durationMs':100})
        with self.assertRaises(ValueError):
            validate_rpc({'type':'rpc','id':1,'method':'pressKeys','args':[['SKILL_17'],100]},
                {'adapter':'full-client','protocol':'scripted-native-acceptance-v2'})

    def test_worker_uses_120_seconds_and_full_toolkit_without_provider_io(self):
        run=self.start()
        def execute(code,scenario,base,**kwargs):
            self.assertEqual(code,program(self.config));self.assertEqual(scenario['protocol'],HERO_TOOLKIT_PROTOCOL)
            self.assertEqual(scenario['skill_toolkit'],self.config['skill_toolkit'])
            self.assertEqual((kwargs['program_seconds'],kwargs['max_actions'],kwargs['max_requests']),(120,128,600))
            step={'kind':'sdk','method':'pressKeys','args':[['SKILL_17'],100],
                  'result':{'accepted':True,'observation':self.observation}}
            kwargs['step_callback'](step)
            return {'reason':'program_complete','actions':1,'steps':[step]}
        with mock.patch.object(self.bridge,'_wait_for_capture'),\
             mock.patch.object(self.bridge,'request',return_value=self.observation),\
             mock.patch('full_client_bridge.execute_program',side_effect=execute),\
             mock.patch('full_client_bridge.model_decision',side_effect=AssertionError('no model')),\
             mock.patch('full_client_bridge.read_private_file',side_effect=AssertionError('no key')):
            self.bridge._run(run)
        result=json.loads((self.bridge.output/run['id']/'result.json').read_bytes())
        self.assertEqual(result['controller']['status'],'completed')
        self.assertEqual(result['nativeAcceptance'],self.config)
        self.assertEqual(result['model_api_requests'],0)
        self.assertIsNone(result['api']);self.assertFalse(result['publication_eligible'])

    def test_private_session_derives_duration_from_validated_contract(self):
        native=contract('hero','a'*64,protocol=HERO_TOOLKIT_PROTOCOL)
        coordinator=SessionCoordinator(self.bridge,{'world':str(self.root/'world'),'queue':str(self.root/'queue')})
        coordinator.owner='test';coordinator.page='game';coordinator.desired='game'
        coordinator.acknowledged=True;coordinator.last_seen=time.monotonic()
        request={'op':'start_native','run_id':'b'*32,'request_id':'b'*32,
                 'native_acceptance':native,'docker_image_id':self.options['docker_image_id'],
                 'docker_binding':self.options['docker_binding'],'lock_paths':coordinator.lock_paths}
        with mock.patch('full_client_session.validate_guard_descriptors'),\
             mock.patch.object(self.bridge,'start',return_value={}) as start:
            coordinator.dispatch(request,tuple(self.fds))
            self.assertEqual(start.call_args.args,('script',None,120))
            self.assertEqual(start.call_args.kwargs['native_acceptance'],native)
            with self.assertRaisesRegex(ControlError,'invalid_native_acceptance'):
                coordinator.dispatch(request|{'native_acceptance':native|{'wall_seconds':600}},tuple(self.fds))


if __name__=='__main__':unittest.main()
