from pathlib import Path
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_bridge import FullClientBridge, write_json
from maple_agent import validate_rpc, model_decision

class FullClientTests(unittest.TestCase):
    def observation(self):
        return {'ready':True,'character':{'x':0,'y':0,'hp':100,'maxHp':100,'mp':10,'maxMp':20,
                'exp':10,'level':180,'mapId':1,'alive':True},'monsters':[]}

    def frame(self, **changes):
        return {'client':'test','ageMs':0,'renderAgeMs':0,'observation':self.observation()} | changes

    def message(self,keys,duration):
        return {'type':'rpc','id':1,'method':'pressKeys','args':[keys,duration]}

    def test_keyboard_is_opt_in_and_bounded(self):
        with self.assertRaises(ValueError): validate_rpc(self.message(['LEFT'],100),{})
        for keys,ms in [(['LEFT','RIGHT'],100),(['ADMIN'],100),(['LEFT'],1501),(['JUMP'],True),(['LEFT','LEFT'],30)]:
            with self.assertRaises(ValueError): validate_rpc(self.message(keys,ms),{'adapter':'full-client'})
        _,action=validate_rpc(self.message(['RIGHT','JUMP'],250),{'adapter':'full-client'})
        self.assertEqual(action['type'],'press_keys')

    def test_input_requires_fresh_state_and_ack(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            with self.assertRaises(ValueError): bridge.request('/v1/observe')
            frame=self.frame()
            bridge.frame(frame)
            result=[]
            action={'type':'press_keys','keys':['LEFT'],'durationMs':100}
            worker=threading.Thread(target=lambda:result.append(bridge.request('/v1/action',action,timeout=1)))
            worker.start()
            end=time.monotonic()+0.5
            command=None
            while time.monotonic()<end and command is None:
                command=bridge.frame(frame)['command']
                time.sleep(0.001)
            self.assertIsNotNone(command)
            self.assertIsNone(bridge.frame(frame)['command'])
            self.assertEqual(result,[])
            time.sleep(0.1)
            bridge.frame(frame|{'ack':{'id':command['id'],'ok':True}})
            worker.join(1)
            self.assertTrue(result[0]['accepted'])
            self.assertIsNone(bridge.pending)
            bridge.frame(frame|{'renderAgeMs':2000})
            with self.assertRaises(ValueError): bridge.request('/v1/observe')

    def test_expired_commands_are_not_delivered_later(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            frame=self.frame()
            bridge.frame(frame)
            with self.assertRaises(TimeoutError):
                bridge.request('/v1/action',{'type':'press_keys','keys':['LEFT'],'durationMs':100},timeout=0.02)
            self.assertIsNone(bridge.frame(frame)['command'])

    def test_run_duration_is_exactly_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            for duration in (True, False, 22.0, 60.0, '60', None, 0, 21, 23, 59, 61, 3600):
                with self.subTest(duration=duration), self.assertRaisesRegex(ValueError,'Run duration'):
                    bridge.start('api','gpt-6-astra',duration)
            with self.assertRaisesRegex(ValueError,'Scripted smoke runs'):
                bridge.start('script',duration_seconds=60)
            self.assertEqual(bridge.run['status'],'idle')

    def test_default_and_demo_start_metadata_match_limits(self):
        for mode,duration,actions,requests in [('script',None,80,100),('api',None,80,100),('api',60,240,600)]:
            with self.subTest(mode=mode,duration=duration), tempfile.TemporaryDirectory() as folder:
                key_file=Path(folder)/'unused-test-key'
                key_file.touch(mode=0o600)
                bridge=FullClientBridge(folder,key_file)
                bridge.frame(self.frame())
                with mock.patch('full_client_bridge.threading.Thread') as worker:
                    arguments={} if duration is None else {'duration_seconds':duration}
                    run=bridge.start(mode,'gpt-6-astra' if mode=='api' else None,**arguments)
                self.assertEqual(run['programSeconds'],duration or 22)
                self.assertEqual(run['actionLimit'],actions)
                self.assertEqual(run['sdkRequestLimit'],requests)
                self.assertEqual(run['actions'],0)
                worker.return_value.start.assert_called_once_with()

    def test_api_executor_prompt_publication_and_live_progress_share_budgets(self):
        for duration,actions,requests in [(22,80,100),(60,240,600)]:
            with self.subTest(duration=duration), tempfile.TemporaryDirectory() as folder:
                key_file=Path(folder)/'unused-test-key'
                key_file.touch(mode=0o600)
                bridge=FullClientBridge(Path(folder)/'runs',key_file)
                observation=self.observation()
                bridge.frame({'client':'test','ageMs':0,'renderAgeMs':0,'observation':observation})
                with mock.patch('full_client_bridge.threading.Thread'):
                    run=bridge.start('api','gpt-6-astra',duration)
                accepted={'kind':'sdk','method':'pressKeys','args':[['RIGHT'],100],
                          'result':{'accepted':True,'observation':observation}}
                outcome={'reason':'program_complete','actions':1,'steps':[accepted]}

                def execute(code,scenario,url,**kwargs):
                    self.assertEqual(kwargs['program_seconds'],duration)
                    self.assertEqual(kwargs['deadline'],100+duration+2)
                    self.assertEqual(kwargs['max_actions'],actions)
                    self.assertEqual(kwargs['max_requests'],requests)
                    self.assertEqual(bridge.run['programStartedAtMs'],1200000)
                    progress=kwargs['step_callback']
                    progress({'method':'observe','result':observation})
                    progress({'method':'wait','result':{'waitedMs':100}})
                    progress(accepted|{'result':{'accepted':False}})
                    self.assertEqual(bridge.run['actions'],0)
                    progress(accepted)
                    self.assertEqual(bridge.run['actions'],1)
                    # A callback from an old run cannot update another run's UI.
                    bridge.run['id']='different-run'
                    progress(accepted)
                    self.assertEqual(bridge.run['actions'],1)
                    bridge.run['id']=run['id']
                    return outcome

                with mock.patch.object(bridge,'request',return_value=observation), \
                     mock.patch('full_client_bridge.time.monotonic',return_value=100), \
                     mock.patch('full_client_bridge.time.time',return_value=1200), \
                     mock.patch.object(bridge,'_wait_for_capture'), \
                     mock.patch('full_client_bridge.model_decision',return_value=({'note':'test','code':'return;'}, {'model':'gpt-6-astra'})) as decision, \
                     mock.patch('full_client_bridge.execute_program',side_effect=execute) as executor:
                    bridge._run(run)
                executor.assert_called_once()
                decision.assert_called_once()
                prompt=decision.call_args.args[1]
                self.assertIn(f'up to {duration} seconds',prompt)
                self.assertIn(f'{requests} SDK calls',prompt)
                self.assertIn(f'at most {actions} pressKeys actions',prompt)
                self.assertEqual(decision.call_args.kwargs['output_tokens'],3000)
                self.assertEqual(decision.call_args.kwargs['timeout'],50)
                self.assertTrue(callable(decision.call_args.kwargs['request_fn']))
                self.assertEqual(bridge.run['status'],'completed')
                self.assertEqual(bridge.run['actions'],1)
                publication=json.loads((bridge.output/run['id']/'publication.json').read_text())
                self.assertEqual(publication['budgets'],{'api_requests':1,'output_tokens':3000,
                    'total_tokens':None,'program_ms':duration*1000,'run_ms':(duration+53)*1000,
                    'actions':actions,'sdk_requests':requests})
                self.assertEqual(publication['result']['controller']['actions'],1)
                self.assertEqual(publication['result']['controller']['programSeconds'],duration)

    def test_active_owner_cannot_be_stolen_after_heartbeat_expiry(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            with mock.patch('full_client_bridge.time.monotonic',return_value=100):
                bridge.frame(self.frame())
            for status in ('requesting','running'):
                bridge.run={'status':status}
                with mock.patch('full_client_bridge.time.monotonic',return_value=110), self.assertRaisesRegex(ValueError,'already_connected'):
                    bridge.frame(self.frame(client='another-client'))
                self.assertEqual(bridge.client,'test')
            bridge.run={'status':'completed'}
            with mock.patch('full_client_bridge.time.monotonic',return_value=110):
                bridge.frame(self.frame(client='another-client'))
            self.assertEqual(bridge.client,'another-client')

    def test_reported_age_expires_and_observations_are_copied_and_sanitized(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            with mock.patch('full_client_bridge.time.monotonic',return_value=100):
                bridge.frame(self.frame(ageMs=1400,observation=self.observation()|{'untrusted':'discard'}))
                first=bridge.request('/v1/observe')
                self.assertNotIn('untrusted',first)
                first['character']['hp']=0
                self.assertEqual(bridge.request('/v1/observe')['character']['hp'],100)
            with mock.patch('full_client_bridge.time.monotonic',return_value=100.2):
                self.assertFalse(bridge.fresh())
                with self.assertRaisesRegex(ValueError,'stale'): bridge.request('/v1/observe')

    def test_invalid_frames_and_acknowledgements_do_not_renew_freshness(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            bad=[{'client':''},{'ageMs':True},{'ageMs':float('nan')},
                 {'observation':{'ready':True}}, {'ack':{'id':'a'*32,'ok':'true'}},
                 {'observation':self.observation()|{'monsters':[{'objectId':1,'x':float('inf'),'y':0}]}}]
            for changes in bad:
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    bridge.frame(self.frame(**changes))
                self.assertEqual(bridge.last_seen,0)

    def test_stale_frames_cannot_receive_or_acknowledge_actions(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            with mock.patch('full_client_bridge.time.monotonic',return_value=100):
                bridge.frame(self.frame())
                bridge.pending={'id':'a'*32,'keys':['RIGHT'],'durationMs':100,'deadline':102}
                self.assertIsNone(bridge.frame(self.frame(renderAgeMs=1500))['command'])
                self.assertNotIn('sent',bridge.pending)
                command=bridge.frame(self.frame())['command']
                self.assertIsNotNone(command)
            with mock.patch('full_client_bridge.time.monotonic',return_value=100.2):
                bridge.frame(self.frame(renderAgeMs=1500,ack={'id':'a'*32,'ok':True}))
            self.assertFalse(bridge.pending['ack']['ok'])

    def test_early_unsent_and_expired_acknowledgements_do_not_accept_input(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            with mock.patch('full_client_bridge.time.monotonic',return_value=100):
                bridge.frame(self.frame())
                bridge.pending={'id':'a'*32,'keys':['RIGHT'],'durationMs':100,'deadline':102}
                bridge.frame(self.frame(ack={'id':'a'*32,'ok':True}))
                self.assertNotIn('ack',bridge.pending)
                bridge.frame(self.frame(ack={'id':'a'*32,'ok':True}))
                self.assertFalse(bridge.pending.pop('ack')['ok'])
            with mock.patch('full_client_bridge.time.monotonic',return_value=103):
                bridge.frame(self.frame(ack={'id':'a'*32,'ok':True}))
                self.assertNotIn('ack',bridge.pending)

    def test_uncertain_api_result_is_journaled_and_never_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            key=Path(folder)/'unused-test-key'; key.touch(mode=0o600)
            bridge=FullClientBridge(Path(folder)/'runs',key)
            bridge.frame(self.frame())
            with mock.patch('full_client_bridge.threading.Thread'):
                run=bridge.start('api','gpt-6-astra')
            with mock.patch.object(bridge,'request',return_value=self.observation()), \
                 mock.patch('full_client_bridge.model_decision',wraps=model_decision) as decision, \
                 mock.patch('full_client_bridge.bounded_request',side_effect=TimeoutError('must not be persisted')), \
                 mock.patch('full_client_bridge.execute_program') as execute:
                bridge._run(run)
            decision.assert_called_once(); execute.assert_not_called()
            path=bridge.output/run['id']
            failure=(path/'failure.json').read_text()
            self.assertNotIn('must not be persisted',failure)
            self.assertEqual(json.loads(failure)['apiOutcome'],'uncertain')
            self.assertEqual(json.loads(failure)['phase'],'api_request')
            self.assertTrue((path/'api-request.json').is_file())
            self.assertEqual(bridge.run['status'],'failed')

    def test_restart_marks_interrupted_api_intent_without_relaunching(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/('a'*32); path.mkdir()
            write_json(path/'controller.json',{'id':'a'*32,'status':'requesting'})
            write_json(path/'api-request.json',{'status':'requesting'})
            with mock.patch('full_client_bridge.threading.Thread') as worker:
                FullClientBridge(folder)
            worker.assert_not_called()
            self.assertEqual(json.loads((path/'controller.json').read_text())['reason'],'process_restarted')
            self.assertEqual(json.loads((path/'failure.json').read_text())['apiOutcome'],'uncertain')

    def test_late_recording_is_bound_to_original_run_and_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(Path(folder)/'runs')
            bridge.frame(self.frame())
            with mock.patch('full_client_bridge.threading.Thread'):
                run=bridge.start('script',client='test')
            path=bridge.output/run['id']
            bridge.run={'id':'b'*32,'status':'completed'}
            temporary=Path(folder)/'upload.part'; temporary.write_bytes(b'first recording')
            receipt=bridge.attach_recording(run['id'],temporary,'a'*64,'test')
            self.assertEqual(receipt['overlay']['controller_id'],run['id'])
            self.assertEqual(receipt['overlay']['mode'],'script')
            self.assertEqual((path/'video.webm').read_bytes(),b'first recording')
            second=Path(folder)/'second.part'; second.write_bytes(b'different recording')
            with self.assertRaisesRegex(ValueError,'already_saved'):
                bridge.attach_recording(run['id'],second,'b'*64,'test')
            self.assertEqual((path/'video.webm').read_bytes(),b'first recording')
            with self.assertRaisesRegex(ValueError,'mismatch'):
                bridge.recording_owner(run['id'],'another-client')

    def test_recording_saved_before_program_finishes_survives_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(Path(folder)/'runs')
            bridge.frame(self.frame())
            with mock.patch('full_client_bridge.threading.Thread'):
                run=bridge.start('script')
            temporary=Path(folder)/'upload.part'; temporary.write_bytes(b'recording')
            bridge.attach_recording(run['id'],temporary,'a'*64)
            with mock.patch.object(bridge,'request',return_value=self.observation()), \
                 mock.patch.object(bridge,'_wait_for_capture'), \
                 mock.patch('full_client_bridge.execute_program',return_value={'reason':'program_complete','actions':0,'steps':[]}):
                bridge._run(run)
            manifest=json.loads((bridge.output/run['id']/'publication.json').read_text())
            self.assertEqual(manifest['video']['sha256'],'a'*64)
            self.assertEqual(bridge.run['evidenceStatus'],'saved')

    def test_failure_to_save_initial_evidence_does_not_start_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            bridge.frame(self.frame())
            with mock.patch('full_client_bridge.write_json',side_effect=OSError), \
                 mock.patch('full_client_bridge.threading.Thread') as worker, self.assertRaises(OSError):
                bridge.start('script')
            worker.assert_not_called()
            self.assertEqual(bridge.run['status'],'idle')

    def test_exact_api_bodies_are_preserved_without_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            key=Path(folder)/'unused-test-key'; key.touch(mode=0o600)
            bridge=FullClientBridge(Path(folder)/'runs',key)
            bridge.frame(self.frame())
            with mock.patch('full_client_bridge.threading.Thread'):
                run=bridge.start('api','gpt-6-astra')
            code='await sdk.observe();'
            response={'id':'test-response','model':'gpt-6-astra','status':'completed',
                'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2},
                'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'note':'test','code':code})}]}]}
            with mock.patch('full_client_bridge.bounded_request',return_value=response) as transport, \
                 mock.patch.object(bridge,'request',return_value=self.observation()), \
                 mock.patch.object(bridge,'_wait_for_capture'), \
                 mock.patch('full_client_bridge.execute_program',return_value={'reason':'program_complete','actions':0,'steps':[]}) as execute:
                bridge._run(run)
            transport.assert_called_once()
            path=bridge.output/run['id']
            self.assertEqual(json.loads((path/'api-response.json').read_text()),response)
            payload=json.loads((path/'api-request-body.json').read_text())
            self.assertEqual(payload,transport.call_args.args[1])
            self.assertNotIn('Authorization',payload)
            self.assertNotIn('api_key',payload)
            self.assertEqual(payload['metadata']['maplebench_run_id'],run['id'])
            self.assertEqual(execute.call_args.args[0],code)
            self.assertEqual(json.loads((path/'program.json').read_text())['code'],code)
            self.assertEqual((path/'program.js').read_bytes(),code.encode())

    def test_idempotent_request_returns_existing_status_without_starting_again(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            bridge.frame(self.frame())
            with mock.patch('full_client_bridge.threading.Thread') as worker:
                first=bridge.start('script',run_id='a'*32,request_id='b'*32)
                second=bridge.start('script',run_id='a'*32,request_id='b'*32)
                self.assertEqual(first['id'],second['id'])
                self.assertEqual(worker.call_count,1)
                bridge.run.update(status='failed',reason='program_error')
                bridge.fresh_until=0
                terminal=bridge.start('script',run_id='a'*32,request_id='b'*32)
                self.assertEqual(terminal['status'],'failed')
                self.assertEqual(worker.call_count,1)
                with self.assertRaisesRegex(ValueError,'conflict'):
                    bridge.start('script',run_id='c'*32,request_id='b'*32)
                with self.assertRaisesRegex(ValueError,'conflict'):
                    bridge.start('script',run_id='a'*32,request_id='c'*32)

    def test_interrupted_request_stays_at_most_once_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            bridge.frame(self.frame())
            with mock.patch('full_client_bridge.threading.Thread'):
                bridge.start('script',run_id='a'*32,request_id='b'*32)
            recovered=FullClientBridge(folder)
            with mock.patch('full_client_bridge.threading.Thread') as worker:
                result=recovered.start('script',run_id='a'*32,request_id='b'*32)
            worker.assert_not_called()
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['reason'],'process_restarted')

    def test_incomplete_intent_is_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            claims=Path(folder)/'requests'; claims.mkdir()
            (claims/('b'*32+'.json')).write_text('{')
            with mock.patch('full_client_bridge.threading.Thread') as worker, self.assertRaisesRegex(ValueError,'incomplete'):
                bridge.start('script',run_id='a'*32,request_id='b'*32)
            worker.assert_not_called()

    def test_prior_run_requires_saved_recording_or_explicit_failure_acknowledgment(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            bridge.frame(self.frame())
            with mock.patch('full_client_bridge.threading.Thread'):
                first=bridge.start('script')
                with mock.patch.object(bridge,'_wait_for_capture'), \
                     mock.patch('full_client_bridge.execute_program',return_value={'reason':'program_complete','actions':0,'steps':[]}):
                    bridge._run(first)
                self.assertEqual(bridge.run['status'],'completed')
                self.assertFalse(bridge.run['workerActive'])
                self.assertEqual(bridge.leases,{})
                bridge.frame(self.frame())
                with self.assertRaisesRegex(ValueError,'not_finalized'):
                    bridge.start('script')
                bridge.release_failed_run(first['id'])
                self.assertEqual(bridge.run['status'],'failed')
                self.assertEqual(bridge.run['recordingStatus'],'discarded')
                second=bridge.start('script')
            self.assertNotEqual(first['id'],second['id'])
            self.assertTrue((Path(folder)/first['id']/'release.json').is_file())

    def test_private_credentials_require_mode_0600_and_no_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            key=Path(folder)/'unused-test-key'; key.touch(mode=0o600)
            FullClientBridge(Path(folder)/'runs',key)
            key.chmod(0o644)
            with self.assertRaisesRegex(ValueError,'0600'):
                FullClientBridge(Path(folder)/'runs',key)
            key.chmod(0o600)
            alias=Path(folder)/'alias'; alias.symlink_to(key)
            with self.assertRaisesRegex(ValueError,'0600'):
                FullClientBridge(Path(folder)/'runs',alias)

    def test_token_cap_rejects_before_provider_call(self):
        with tempfile.TemporaryDirectory() as folder:
            key=Path(folder)/'unused-test-key'; key.touch(mode=0o600)
            bridge=FullClientBridge(Path(folder)/'runs',key)
            bridge.frame(self.frame())
            with mock.patch('full_client_bridge.threading.Thread'):
                run=bridge.start('api','gpt-6-astra',total_token_limit=3000)
            with mock.patch.object(bridge,'request',return_value=self.observation()), \
                 mock.patch('full_client_bridge.bounded_request') as provider, \
                 mock.patch('full_client_bridge.execute_program') as executor:
                bridge._run(run)
            provider.assert_not_called(); executor.assert_not_called()
            self.assertEqual(bridge.run['reason'],'api_token_budget_too_small')
            self.assertEqual(bridge.run['apiOutcome'],'not_started')
            intent=json.loads((bridge.output/run['id']/'api-request.json').read_text())
            self.assertGreater(intent['tokenUpperBound'],3000)
            self.assertEqual(intent['status'],'budget_rejected')

    def test_private_trial_context_and_docker_pin_reach_actual_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            key=Path(folder)/'unused-test-key'; key.touch(mode=0o600)
            bridge=FullClientBridge(Path(folder)/'runs',key)
            bridge.frame(self.frame())
            context={'scenario_fingerprint':'a'*64,'baseline_sha256':'b'*64}
            image_id='sha256:'+'c'*64
            with mock.patch('full_client_bridge.threading.Thread'), tempfile.TemporaryFile() as world, tempfile.TemporaryFile() as queue:
                run=bridge.start('api','gpt-6-astra',run_id='d'*32,request_id='d'*32,
                    total_token_limit=100000,trial_context=context,docker_image_id=image_id,
                    lease_fds=(world.fileno(),queue.fileno()))
            response={'id':'test-response','model':'gpt-6-astra','status':'completed',
                'metadata':{'maplebench_run_id':'d'*32},
                'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'note':'test','code':'return;'})}]}]}
            with mock.patch.object(bridge,'request',return_value=self.observation()), \
                 mock.patch('full_client_bridge.bounded_request',return_value=response), \
                 mock.patch.object(bridge,'_wait_for_capture'), \
                 mock.patch('full_client_bridge.execute_program',return_value={'reason':'program_complete','actions':0,'steps':[]}) as execute:
                bridge._run(run)
            self.assertEqual(execute.call_args.kwargs['docker_image'],image_id)
            result=json.loads((bridge.output/run['id']/'result.json').read_text())
            self.assertEqual(result['source'],'full-client-trial')
            self.assertEqual(result['trialContext'],context)
            self.assertEqual(result['controller']['dockerImageId'],image_id)
            self.assertLessEqual(result['controller']['apiTokenUpperBound'],100000)
            self.assertEqual(result['controller']['controllerSeconds'],24)

    def test_invalid_private_runtime_caps_never_start_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            for extra in ({'total_token_limit':True},{'total_token_limit':0},
                    {'docker_image_id':'node:latest'},{'trial_context':{}},
                    {'trial_context':{'scenario_fingerprint':'a'*64,'baseline_sha256':'b'*64}}):
                with self.subTest(extra=extra), mock.patch('full_client_bridge.threading.Thread') as worker, self.assertRaises(ValueError):
                    bridge.start('api','gpt-6-astra',**extra)
                worker.assert_not_called()

    def test_cancelled_identity_cannot_be_started_later(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder)
            cancelled=bridge.cancel('e'*32)
            self.assertEqual(cancelled['apiOutcome'],'not_started')
            with mock.patch('full_client_bridge.threading.Thread') as worker, self.assertRaisesRegex(ValueError,'run_cancelled'):
                bridge.start('script',run_id='e'*32,request_id='e'*32)
            worker.assert_not_called()

    def test_recorder_needs_started_post_render_frame_and_clock_ack_before_program(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder); bridge.frame(self.frame())
            with mock.patch('full_client_bridge.threading.Thread'):
                run=bridge.start('script')
            for capture in ({'runId':run['id'],'started':False,'renderedFrames':1,'interrupted':False},
                    {'runId':run['id'],'started':True,'renderedFrames':0,'interrupted':False},
                    {'runId':'b'*32,'started':True,'renderedFrames':1,'interrupted':False}):
                bridge.frame(self.frame(capture=capture,captureState='recording',clientSentAtMs=1000))
                with self.assertRaisesRegex(ValueError,'recorder_not_ready'):
                    bridge._wait_for_capture(run['id'],timeout=.001)
            frame=self.frame(capture={'runId':run['id'],'started':True,'renderedFrames':1,'interrupted':False},
                captureState='recording',clientSentAtMs=1000)
            response=bridge.frame(frame)
            with self.assertRaisesRegex(ValueError,'recorder_not_ready'):
                bridge._wait_for_capture(run['id'],timeout=.001)
            bridge.frame(frame|{'captureClockAck':response['clock']['id']})
            bridge._wait_for_capture(run['id'],timeout=.01)
            self.assertTrue((bridge.output/run['id']/'capture-ready.json').is_file())
            self.assertTrue((bridge.output/run['id']/'capture-clock.json').is_file())

    def test_missing_recorder_never_starts_executor(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder); bridge.frame(self.frame())
            with mock.patch('full_client_bridge.threading.Thread'):
                run=bridge.start('script')
            from full_client_bridge import ControlError
            with mock.patch.object(bridge,'_wait_for_capture',side_effect=ControlError('recorder_not_ready')), \
                 mock.patch('full_client_bridge.execute_program') as executor:
                bridge._run(run)
            executor.assert_not_called(); self.assertEqual(bridge.run['reason'],'recorder_not_ready')

    def test_capture_upload_preserves_measurements_and_rejects_changed_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(Path(folder)/'runs'); bridge.frame(self.frame())
            with mock.patch('full_client_bridge.threading.Thread'):
                run=bridge.start('script')
            root=bridge.output/run['id']
            origin=run['startedAtMs']
            clock={'id':'b'*32,'client_sent_ms':1000,'server_received_ms':origin+10,'server_sent_ms':origin+12}
            write_json(root/'capture-ready.json',{'runId':run['id'],'serverReceivedAtMs':origin+50,'renderedFrames':1})
            write_json(root/'capture-clock.json',clock)
            write_json(root/'capture-terminal.json',{'id':'c'*32,'serverIssuedAtMs':origin+200})
            capture={'schema_version':1,'run_id':run['id'],'client_id':'test',
                'start_wall_ms':1020,'end_wall_ms':1300,'duration_ms':280,
                'first_frame_wall_ms':1022,'last_frame_wall_ms':1298,'rendered_frames':15,
                'max_frame_gap_ms':20,'hidden':False,'errors':0,'relay_lost':False,'interrupted':False,
                'clock':clock|{'client_received_ms':1020},'terminal_token':'c'*32}
            temporary=Path(folder)/'recording.part'; temporary.write_bytes(b'actual upload bytes')
            receipt=bridge.attach_recording(run['id'],temporary,'d'*64,'test',capture)
            self.assertEqual(json.loads((root/'capture.json').read_text()),capture)
            self.assertEqual(receipt['duration_ms'],280); self.assertEqual(receipt['timing_uncertainty_ms'],9)
            self.assertFalse(receipt['interrupted']); self.assertFalse(receipt['reviewed'])
            with self.assertRaisesRegex(ValueError,'metadata_already_saved'):
                bridge.attach_recording(run['id'],temporary,'d'*64,'test',capture|{'rendered_frames':16})
            with self.assertRaisesRegex(ValueError,'recording_already_saved'):
                bridge.attach_recording(run['id'],temporary,'e'*64,'test',capture|{'rendered_frames':16})
            self.assertEqual(json.loads((root/'capture.json').read_text()),capture)

    def test_trial_cannot_spend_api_before_recorder_acknowledgement(self):
        with tempfile.TemporaryDirectory() as folder:
            key=Path(folder)/'unused-test-key'; key.touch(mode=0o600)
            bridge=FullClientBridge(Path(folder)/'runs',key); bridge.frame(self.frame())
            with mock.patch('full_client_bridge.threading.Thread'), tempfile.TemporaryFile() as world, tempfile.TemporaryFile() as queue:
                run=bridge.start('api','gpt-6-astra',run_id='d'*32,request_id='d'*32,
                    trial_context={'scenario_fingerprint':'a'*64,'baseline_sha256':'b'*64},
                    lease_fds=(world.fileno(),queue.fileno()))
            from full_client_bridge import ControlError
            with mock.patch.object(bridge,'_wait_for_capture',side_effect=ControlError('recorder_not_ready')), \
                 mock.patch('full_client_bridge.bounded_request') as provider:
                bridge._run(run)
            provider.assert_not_called()
            self.assertEqual(bridge.run['failurePhase'],'capture_prepare')
            self.assertEqual(bridge.run['apiOutcome'],'not_started')
            bridge.frame(self.frame(releaseAck=run['id']))

    def test_death_and_exhausted_action_budget_are_completed_not_filtered(self):
        for reason,actions,alive,expected in [('death',0,False,'completed'),('death',0,True,'failed'),
                ('action_limit',80,True,'completed'),('action_limit',79,True,'failed')]:
            with self.subTest(reason=reason,actions=actions,alive=alive), tempfile.TemporaryDirectory() as folder:
                bridge=FullClientBridge(folder); bridge.frame(self.frame())
                with mock.patch('full_client_bridge.threading.Thread'):
                    run=bridge.start('script')
                final=self.observation(); final['character']['alive']=alive
                final['character']['hp']=100 if alive else 0
                with mock.patch.object(bridge,'_wait_for_capture'), \
                     mock.patch.object(bridge,'request',return_value=final), \
                     mock.patch('full_client_bridge.execute_program',return_value={'reason':reason,'actions':actions,'steps':[]}):
                    bridge._run(run)
                self.assertEqual(bridge.run['status'],expected)

    def test_only_measured_normal_program_timeout_is_a_completed_time_limit(self):
        for reason,elapsed,error,expected in [('program_timeout',22,None,'completed'),
                ('program_timeout',10,None,'failed'),('program_timeout',22,'runtime failure','failed'),
                ('program_error',22,None,'failed')]:
            with self.subTest(reason=reason,elapsed=elapsed,error=error), tempfile.TemporaryDirectory() as folder:
                bridge=FullClientBridge(folder); bridge.frame(self.frame())
                with mock.patch('full_client_bridge.threading.Thread'):
                    run=bridge.start('script')
                clock=[100]
                def execute(*args,**kwargs):
                    clock[0]+=elapsed
                    return {'reason':reason,'error':error,'actions':0,'steps':[]}
                with mock.patch.object(bridge,'_wait_for_capture'), \
                     mock.patch.object(bridge,'request',return_value=self.observation()), \
                     mock.patch('full_client_bridge.time.monotonic',side_effect=lambda:clock[0]), \
                     mock.patch('full_client_bridge.execute_program',side_effect=execute):
                    bridge._run(run)
                self.assertEqual(bridge.run['status'],expected)
                self.assertEqual(bridge.run['reason'],'time_limit' if expected=='completed' else reason)

    def test_cancel_wakes_pending_input_and_positive_ack_cannot_revive_it(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=FullClientBridge(folder); bridge.frame(self.frame())
            with mock.patch('full_client_bridge.threading.Thread'):
                run=bridge.start('script')
            errors=[]
            def action():
                try: bridge.request('/v1/action',{'type':'press_keys','keys':['LEFT'],'durationMs':100},run_id=run['id'])
                except ValueError as error: errors.append(str(error))
            worker=threading.Thread(target=action); worker.start()
            deadline=time.monotonic()+1
            command=None
            while command is None and time.monotonic()<deadline:
                command=bridge.frame(self.frame())['command']; time.sleep(.001)
            self.assertIsNotNone(command)
            bridge.cancel(run['id']); worker.join(1)
            self.assertFalse(worker.is_alive()); self.assertEqual(errors,['run_cancelled'])
            response=bridge.frame(self.frame(ack={'id':command['id'],'ok':True}))
            self.assertIsNone(response['command']); self.assertEqual(response['releaseKeys'],{'runId':run['id']})
            self.assertTrue(bridge.status()['browserReleasePending'])
            bridge.frame(self.frame(releaseAck=run['id']))
            self.assertFalse(bridge.status()['browserReleasePending'])
            with self.assertRaisesRegex(ValueError,'run_cancelled'):
                bridge.request('/v1/action',{'type':'press_keys','keys':['LEFT'],'durationMs':100},run_id=run['id'])

    def test_cancel_during_api_holds_lease_until_late_receipt_and_never_executes(self):
        with tempfile.TemporaryDirectory() as folder:
            key=Path(folder)/'unused-test-key'; key.touch(mode=0o600)
            bridge=FullClientBridge(Path(folder)/'runs',key); bridge.frame(self.frame())
            with mock.patch('full_client_bridge.threading.Thread'), tempfile.TemporaryFile() as world, tempfile.TemporaryFile() as queue:
                run=bridge.start('api','gpt-6-astra',run_id='f'*32,request_id='f'*32,
                    trial_context={'scenario_fingerprint':'a'*64,'baseline_sha256':'b'*64},
                    lease_fds=(world.fileno(),queue.fileno()))
                retained=list(bridge.leases[run['id']])
                duplicate=bridge.start('api','gpt-6-astra',run_id='f'*32,request_id='f'*32,
                    trial_context={'scenario_fingerprint':'a'*64,'baseline_sha256':'b'*64},
                    lease_fds=(world.fileno(),queue.fileno()))
                self.assertEqual(duplicate['id'],run['id'])
                self.assertEqual(bridge.leases[run['id']],retained)
            entered=threading.Event(); finish=threading.Event()
            response={'id':'test-response','model':'gpt-6-astra','status':'completed',
                'metadata':{'maplebench_run_id':run['id']},
                'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'note':'test','code':'return;'})}]}]}
            def provider(*args):
                entered.set()
                if not finish.wait(2): raise TimeoutError()
                return response
            with mock.patch('full_client_bridge.bounded_request',side_effect=provider), \
                 mock.patch.object(bridge,'_wait_for_capture'), \
                 mock.patch('full_client_bridge.execute_program') as execute:
                worker=threading.Thread(target=bridge._run,args=(run,)); worker.start()
                try:
                    self.assertTrue(entered.wait(1))
                    receipt=bridge.cancel(run['id'])
                    self.assertTrue(receipt['workerActive']); self.assertEqual(receipt['apiOutcome'],'uncertain')
                    self.assertTrue((bridge.output/'cancellations'/(run['id']+'.json')).is_file())
                    for descriptor in retained: os.fstat(descriptor)
                    with self.assertRaisesRegex(ValueError,'busy'):
                        bridge.start('script')
                    with mock.patch('full_client_bridge.time.monotonic',return_value=time.monotonic()+5), \
                         self.assertRaisesRegex(ValueError,'already_connected'):
                        bridge.frame(self.frame(client='intruder'))
                finally:
                    finish.set(); worker.join(3)
            self.assertFalse(worker.is_alive()); execute.assert_not_called()
            self.assertEqual(bridge.run['reason'],'run_cancelled')
            self.assertEqual(bridge.run['apiOutcome'],'receipt_saved')
            self.assertFalse(bridge.run['workerActive'])
            self.assertFalse((bridge.output/run['id']/'result.json').exists())
            self.assertEqual(json.loads((bridge.output/run['id']/'api-response.json').read_text()),response)
            self.assertTrue(bridge.run['leaseReleasePending'])
            for descriptor in retained: os.fstat(descriptor)
            with self.assertRaisesRegex(ValueError,'busy'):
                bridge.start('script')
            bridge.frame(self.frame(releaseAck=run['id']))
            self.assertFalse(bridge.run['leaseReleasePending'])
            for descriptor in retained:
                with self.assertRaises(OSError): os.fstat(descriptor)

    def test_all_corrupt_attempts_block_start_until_each_exact_quarantine_is_acknowledged(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for run_id in ('a'*32,'b'*32):
                path=root/run_id; path.mkdir()
                (path/'controller.json').write_text('{private-corrupt-content')
            latest=root/('c'*32); latest.mkdir()
            write_json(latest/'controller.json',{'id':'c'*32,'status':'completed','evidenceStatus':'saved'})
            write_json(latest/'recording.json',{'status':'completed'})
            bridge=FullClientBridge(root)
            self.assertEqual(bridge.status()['quarantinedRuns'],['a'*32,'b'*32])
            self.assertEqual(bridge.run['id'],'c'*32)
            bridge.frame(self.frame())
            with self.assertRaisesRegex(ValueError,'corrupt_runs_require_acknowledgment'):
                bridge.start('script')
            for run_id in ('a'*32,'b'*32):
                self.assertNotIn('private-corrupt-content',(root/run_id/'failure.json').read_text())
                preserved=list((root/run_id).glob('controller-corrupt-*.bin'))
                self.assertEqual(len(preserved),1)
                self.assertEqual(preserved[0].read_text(),'{private-corrupt-content')
            bridge.release_failed_run('a'*32)
            recovered=FullClientBridge(root); recovered.frame(self.frame())
            self.assertEqual(recovered.status()['quarantinedRuns'],['b'*32])
            with self.assertRaisesRegex(ValueError,'corrupt_runs_require_acknowledgment'):
                recovered.start('script')
            recovered.release_failed_run('b'*32)
            with mock.patch('full_client_bridge.threading.Thread') as worker:
                recovered.start('script')
            worker.assert_called_once()

    def test_missing_controller_and_corruption_after_old_release_are_quarantined(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); path=root/('a'*32); path.mkdir()
            write_json(path/'release.json',{'runId':'a'*32,'reason':'operator_acknowledged_failure'})
            bridge=FullClientBridge(root)
            self.assertEqual(bridge.run['status'],'failed')
            self.assertEqual(bridge.run['reason'],'invalid_controller_evidence')
            self.assertEqual(bridge.status()['quarantinedRuns'],['a'*32])
            bridge.release_failed_run('a'*32)
            (path/'controller.json').write_text('new corruption')
            recovered=FullClientBridge(root)
            self.assertEqual(recovered.status()['quarantinedRuns'],['a'*32])

if __name__=='__main__': unittest.main()
