"""Synthetic dashboard receipts only; no live gameplay or publication claims."""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import socket
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from full_client_dashboard import build_snapshot, recording_url, write_snapshot, read_admin_status, main, playback_cue
from full_client_score import score_trial
from test_full_client_score import fixture


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()
        self.attempts=self.root/'attempts'; self.attempts.mkdir()
        self.relay=self.root/'relay'; self.relay.mkdir()

    def tearDown(self): self.temp.cleanup()

    def write(self,path,value):
        raw=json.dumps(value,sort_keys=True).encode(); path.write_bytes(raw)
        return {'path':path.name,'sha256':hashlib.sha256(raw).hexdigest()}

    def execution(self,result,acknowledged=4,attempts=4,*,legacy=False):
        observation={'ready':True,'source':'full-client','ageMs':12,'renderAgeMs':8,
                     'character':{'alive':True,'exp':1000,'level':180}}
        result['initial']=copy.deepcopy(observation)
        result['final']=copy.deepcopy(observation)|{'character':result.get('final',{}).get('character',{'alive':True})}
        result['controller'].update(actions=attempts if legacy else acknowledged,sdkRequestLimit=100,actionLimit=80)
        result['program']={'reason':'program_complete','error':None,
            'actions':attempts if legacy else acknowledged,
            'steps':[{'kind':'sdk','method':'pressKeys','args':[['ATTACK'],100],
                      'result':{'accepted':True,'error':None,'observation':copy.deepcopy(observation)}}
                     for _ in range(acknowledged)],'logs':[]}
        if not legacy: result['program']['actionAttempts']=attempts

    def save_result(self,folder,journal,result):
        journal['receipts']['collect_final']['artifacts']['result']=self.write(folder/'result.json',result)
        self.write(folder/'journal.json',journal)

    def attempt(self,run_id,model='gpt-6-astra',xp=100,status='completed',runtime='f'*64):
        folder=self.attempts/run_id; folder.mkdir()
        evidence=fixture()
        evidence['run_id']=run_id
        for key in ('reset','initial','final','session'): evidence[key]['run_id']=run_id
        evidence['session']['save']['run_id']=run_id
        evidence['final']['character']['exp']+=xp
        if xp<0: evidence['final']['character']['hp']=0
        context={'scenario_fingerprint':'a'*64,'baseline_sha256':'b'*64}
        score=score_trial(evidence)|{'artifacts_verified':True}
        result={'source':'full-client-trial','trialContext':context,
            'controller':{'id':run_id,'status':'completed','mode':'api','model':model,'returnedModel':model,
                'trialContext':context,'dockerImageId':'sha256:'+'c'*64,'actions':4},
            'api':{'model':model,'status':'completed'},'observedXpDelta':max(xp,0),
            'final':{'character':{'alive':xp>=0}},'timing':{'apiLatencyMs':800,'elapsedMs':6000,'endedAtMs':7000},
            'timeline':{'status':'completed'}}
        self.execution(result)
        request={'model':model,'metadata':{'maplebench_run_id':run_id}}
        response={'model':model,'status':'completed','metadata':{'maplebench_run_id':run_id}}
        recording={'path':'video.webm','sha256':'d'*64,'status':'completed','reviewed':False,
            'overlay':{'controller_id':run_id,'mode':'api','model':model}}
        refs={name:self.write(folder/(name+'.json'),value) for name,value in
            [('persistence',evidence),('score',score),('result',result),('api_request',request),('api_response',response),('recording',recording)]}
        # The exporter trusts the completed runner's baseline/runtime verification;
        # these large artifacts are deliberately not reread on every UI refresh.
        refs.update(baseline={'path':'private.sql','sha256':'b'*64},scenario={'path':'scenario.json','sha256':'a'*64},
            runtime_manifest={'path':'runtime.json','sha256':runtime},video={'path':'video.webm','sha256':'d'*64})
        journal={'attempt_id':run_id,'status':status,'phase':'cleanup','publication_eligible':True,
            'request':{'model':model,**context,'budgets':{'total_seconds':90,'operation_seconds':60,
                'controller_seconds':24,'max_actions':80,'max_api_requests':1,'max_output_tokens':3000,'max_total_tokens':30000}},
            'score':score,'events':[{'kind':'attempt_created','at_ms':1000},{'kind':'evidence_verified','at_ms':8200}],
            'receipts':{'collect_final':{'artifacts':refs}},'password':'private-password-marker',
            'host_path':'/private/secret-host/runtime','private_account_id':999}
        self.write(folder/'journal.json',journal)
        return folder,journal,result

    def snapshot(self,**kwargs): return build_snapshot(self.attempts,self.relay,now_ms=10000,**kwargs)

    def test_playback_maps_verified_timeline_to_untrimmed_video(self):
        folder,journal,result=self.attempt('1'*32)
        result['timeline'].update(program_started_ms=1400,program_ended_ms=5500)
        self.save_result(folder,journal,result)
        recording=json.loads((folder/'recording.json').read_text())
        recording.update(start_ms=100,end_ms=6100,duration_ms=6000,interrupted=False,
            post_render_capture=True,timing_uncertainty_ms=9,
            timing_method='browser_monotonic_duration_with_measured_clock_offset')
        journal['receipts']['collect_final']['artifacts']['recording']=self.write(folder/'recording.json',recording)
        self.write(folder/'journal.json',journal)
        approved={'1'*32:{'url':'/recordings/'+'1'*32+'.webm','sha256':'d'*64}}
        row=self.snapshot(recording_map=approved)['attempts'][0]
        self.assertEqual(row['recording']['playback'],{'start_ms':1050,'basis':'program_start','timing_uncertainty_ms':9})
        result['timeline'].update(first_input_started_ms=1700,first_input_acked_ms=1900)
        self.save_result(folder,journal,result)
        row=self.snapshot(recording_map=approved)['attempts'][0]
        self.assertEqual(row['recording']['playback']['start_ms'],1350)
        self.assertEqual(row['recording']['playback']['basis'],'first_acknowledged_input')
        self.assertEqual(row['persisted_xp'],100);self.assertFalse(row['ranked'])
        # Unhashed edits cannot supply a playback cue even when a video is linked.
        result['timeline']['first_input_started_ms']=1800
        self.write(folder/'result.json',result)
        row=self.snapshot(recording_map=approved)['attempts'][0]
        self.assertNotIn('playback',row['recording'] or {})

    def test_playback_refuses_noops_incomplete_receipts_and_invalid_capture_timing(self):
        result={'timeline':{'program_started_ms':1400,'program_ended_ms':5500}}
        recording={'start_ms':100,'end_ms':6100,'duration_ms':6000,'interrupted':False,
            'post_render_capture':True,'timing_uncertainty_ms':9,
            'timing_method':'browser_monotonic_duration_with_measured_clock_offset'}
        actions={'actions':4,'action_verification':'receipts_rechecked'}
        for changes in ({'actions':0},{'actions':None},{'action_verification':'receipts_incomplete'}):
            self.assertIsNone(playback_cue(result,recording,actions|changes))
        for changes in ({'interrupted':True},{'post_render_capture':False},{'start_ms':1500},
                        {'end_ms':5400},{'duration_ms':3000},{'timing_uncertainty_ms':101},
                        {'timing_uncertainty_ms':True},{'timing_method':'unavailable'}):
            self.assertIsNone(playback_cue(result,recording|changes,actions))
        for changes in ({'first_input_started_ms':1700},
                        {'first_input_started_ms':True,'first_input_acked_ms':1900},
                        {'first_input_started_ms':1399,'first_input_acked_ms':1900},
                        {'first_input_started_ms':1700,'first_input_acked_ms':1600},
                        {'first_input_started_ms':1700,'first_input_acked_ms':5501}):
            self.assertIsNone(playback_cue({'timeline':result['timeline']|changes},recording,actions))

    def publication(self,folder,journal,result,*,ready=True,reasons=None,version='abcdef1',at=9000):
        """Synthetic private validator receipt; the dashboard never runs a gate."""
        refs=copy.deepcopy(journal['receipts']['collect_final']['artifacts'])
        recording=json.loads((folder/refs['recording']['path']).read_bytes())
        refs['video_review']=self.write(folder/'video-review.json',{
            'run_id':journal['attempt_id'],'video_sha256':recording['sha256'],'reviewed':True,
            'post_render_capture':True,'overlay':recording['overlay'],'reviewed_at_ms':8500})
        reviewed={'schema_version':2,'run_kind':'ranked','result':copy.deepcopy(result),'score':journal['score'],
            'timeline':result['timeline'],'video':recording|{'reviewed':True},'artifacts':refs}
        reference=self.write(folder/'publication-reviewed.json',reviewed)
        verdict={'schema_version':1,'run_id':journal['attempt_id'],'validator_source_commit':version,
            'validator_sha256':'e'*64,'reviewed_manifest_sha256':reference['sha256'],'validated_at_ms':at,
            'verdict':{'ready':ready,'reasons':([] if ready else ['result.program.actions: count must match the complete input receipt list.']) if reasons is None else reasons},
            'externally_published':False,'private_marker':'/private/validator-secret'}
        path=folder/f'publication-verdict-{version}.json';self.write(path,verdict)
        return path,verdict,reviewed

    def test_legacy_attempt_counter_does_not_mislabel_missing_acknowledgment_or_erase_xp(self):
        folder,journal,result=self.attempt('1'*32,model='gpt-5.6-terra',xp=4500)
        self.execution(result,acknowledged=34,attempts=35,legacy=True)
        result['program']['reason']='time_limit'
        self.save_result(folder,journal,result)
        self.publication(folder,journal,result,ready=False)
        row=self.snapshot()['attempts'][0]
        self.assertEqual(row['reported_actions'],35)
        self.assertEqual(row['action_attempts'],35)
        self.assertEqual(row['acknowledged_actions'],34);self.assertEqual(row['actions'],34)
        self.assertEqual(row['action_verification'],'receipts_incomplete');self.assertIsNone(row['no_op'])
        self.assertEqual(row['persisted_xp'],4500)
        self.assertEqual(row['publication_evidence'],{'status':'blocked','reason_code':'receipts_incomplete'})
        self.assertIsNotNone(row['comparison_group'])
        self.assertFalse(row['ranked']);self.assertFalse(row['publication_eligible'])

    def test_legacy_completed_zero_inputs_and_separate_current_acceptance_are_explicit(self):
        for run_id,name in (('1'*32,'gpt-5.6-sol'),('2'*32,'gpt-5.6-luna')):
            folder,journal,result=self.attempt(run_id,model=name,xp=0)
            self.execution(result,acknowledged=0,attempts=0,legacy=True)
            self.save_result(folder,journal,result)
        folder,journal,result=self.attempt('3'*32,xp=9500,runtime='e'*64)
        self.execution(result,acknowledged=29,attempts=29)
        self.save_result(folder,journal,result)
        value=self.snapshot();rows={row['id']:row for row in value['attempts']}
        for run_id in ('1'*32,'2'*32):
            row=rows[run_id]
            self.assertEqual(row['persisted_xp'],0)
            self.assertEqual(row['action_attempts'],0);self.assertEqual(row['acknowledged_actions'],0)
            self.assertIs(row['no_op'],True);self.assertEqual(row['action_verification'],'receipts_rechecked')
            self.assertEqual(row['sdk_calls'],0)
        acceptance=rows['3'*32]
        self.assertEqual(acceptance['persisted_xp'],9500)
        self.assertEqual(acceptance['action_attempts'],29);self.assertEqual(acceptance['acknowledged_actions'],29)
        self.assertIs(acceptance['no_op'],False)
        self.assertNotEqual(acceptance['comparison_group'],rows['1'*32]['comparison_group'])
        self.assertEqual(len(value['comparisons']),2)
        self.assertTrue(all(row['ranked'] is False and row['publication_eligible'] is False for row in rows.values()))

    def test_invalid_receipts_only_count_the_valid_subset_without_changing_persisted_score(self):
        changes=[lambda p:p['steps'][0]['result'].update(accepted=False),
                 lambda p:p['steps'][0].update(kind='sdk_error'),
                 lambda p:p['steps'][0].update(args=[['LEFT','RIGHT'],100]),
                 lambda p:p['steps'][0]['result']['observation'].update(renderAgeMs=1500),
                 lambda p:p['steps'][0]['result'].update(error='/private/action-error'),
                 lambda p:p['steps'][0].update(method='private_method'),
                 lambda p:p['steps'][0].update(args=[['ATTACK'],True])]
        for index,change in enumerate(changes):
            with self.subTest(index=index):
                folder,journal,result=self.attempt(f'{index+1:032x}',xp=-600)
                change(result['program']);self.save_result(folder,journal,result)
        for row in self.snapshot()['attempts']:
            self.assertEqual(row['acknowledged_actions'],3)
            self.assertEqual(row['action_attempts'],4)
            self.assertEqual(row['action_verification'],'receipts_incomplete');self.assertIsNone(row['no_op'])
            self.assertEqual(row['persisted_xp'],-600)
            self.assertNotIn('/private/action-error',json.dumps(row));self.assertNotIn('private_method',json.dumps(row))

    def test_zero_counter_alone_does_not_prove_noop(self):
        changes=[lambda r:r['program'].pop('steps'),
                 lambda r:r['program'].update(error='/private/program-error'),
                 lambda r:r['program'].update(steps=[{'kind':'rejected_rpc','error':'private-input'}]),
                 lambda r:r['initial'].update(ready=False),
                 lambda r:r['final'].update(renderAgeMs=2**500),
                 lambda r:r['program'].update(reason='program_error'),
                 lambda r:r['controller'].update(actions=1),
                 lambda r:r['program'].update(actionAttempts=None)]
        for index,change in enumerate(changes):
            folder,journal,result=self.attempt(f'{index+1:032x}',xp=0)
            self.execution(result,acknowledged=0,attempts=0)
            change(result);self.save_result(folder,journal,result)
        for row in self.snapshot()['attempts']:
            self.assertIsNone(row['no_op']);self.assertEqual(row['action_verification'],'receipts_incomplete')
            self.assertEqual(row['persisted_xp'],0)
            self.assertNotIn('private-input',json.dumps(row));self.assertNotIn('/private/program-error',json.dumps(row))

    def test_action_receipt_and_counter_limits_fail_closed(self):
        changes=[lambda r:r['program'].update(steps=None),
                 lambda r:r['controller'].update(sdkRequestLimit=3),
                 lambda r:r['program'].update(steps=r['program']['steps']*26),
                 lambda r:r['program'].update(actionAttempts=10001),
                 lambda r:r['program'].update(actionAttempts=True),
                 lambda r:r['program'].update(actionAttempts=3)]
        for index,change in enumerate(changes):
            folder,journal,result=self.attempt(f'{index+1:032x}')
            change(result);self.save_result(folder,journal,result)
        rows={row['id']:row for row in self.snapshot()['attempts']}
        for index in range(len(changes)):
            row=rows[f'{index+1:032x}']
            self.assertIsNone(row['no_op']);self.assertEqual(row['action_verification'],'receipts_incomplete')
            self.assertEqual(row['persisted_xp'],100)
            if index<3: self.assertIsNone(row['acknowledged_actions'])
            else: self.assertIsNone(row['action_attempts'])

    def test_zero_input_observe_and_completed_wait_receipts_allow_noop(self):
        folder,journal,result=self.attempt('1'*32,xp=-600)
        self.execution(result,acknowledged=0,attempts=0)
        result['program']['steps']=[{'kind':'sdk','method':'observe','args':[],
            'result':copy.deepcopy(result['initial'])},
            {'kind':'sdk','method':'wait','args':[100],'result':{'waitedMs':100}}]
        self.save_result(folder,journal,result)
        row=self.snapshot()['attempts'][0]
        self.assertIs(row['no_op'],True);self.assertEqual(row['persisted_xp'],-600)
        self.assertEqual(row['sdk_calls'],2)
        result['program']['steps'][-1]['result']['waitedMs']=50
        self.save_result(folder,journal,result)
        self.assertIsNone(self.snapshot()['attempts'][0]['no_op'])
        result['program']['reason']='time_limit';self.save_result(folder,journal,result)
        self.assertIs(self.snapshot()['attempts'][0]['no_op'],True)

    def test_live_counter_cannot_replace_hashed_terminal_acknowledgments(self):
        run_id='1'*32;_,_,result=self.attempt(run_id)
        live={'bridge':{'fresh':True,'run':result['controller']|{'actions':99}}}
        row=self.snapshot(live_status=live)['attempts'][0]
        self.assertEqual(row['reported_actions'],99)
        self.assertEqual(row['acknowledged_actions'],4);self.assertEqual(row['action_attempts'],4)
        self.assertEqual(row['action_verification'],'receipts_rechecked')

    def test_unhashed_relay_result_never_confirms_actions_or_noop(self):
        run_id='1'*32;folder,journal,result=self.attempt(run_id,xp=0)
        self.execution(result,acknowledged=0,attempts=0)
        # Keep the original journal hash so the edited private result is invalid.
        self.write(folder/'result.json',result)
        relay=self.relay/run_id;relay.mkdir();self.write(relay/'result.json',result)
        row=self.snapshot()['attempts'][0]
        self.assertEqual(row['reported_actions'],0)
        self.assertIsNone(row['acknowledged_actions']);self.assertIsNone(row['action_attempts'])
        self.assertIsNone(row['no_op']);self.assertEqual(row['action_verification'],'unverified')

    def test_publication_status_is_separate_from_verified_score_and_never_grants_ranking(self):
        for index,status in enumerate(('passed','blocked','awaiting_review'),1):
            folder,journal,result=self.attempt(str(index)*32,xp=4500)
            if status!='awaiting_review': self.publication(folder,journal,result,ready=status=='passed')
        rows={row['id']:row for row in self.snapshot()['attempts']}
        for index,status in enumerate(('passed','blocked','awaiting_review'),1):
            row=rows[str(index)*32]
            self.assertEqual(row['publication_evidence'],{'status':status,'reason_code':'receipts_incomplete' if status=='blocked' else None})
            self.assertEqual(row['persisted_xp'],4500)
            self.assertFalse(row['ranked']);self.assertFalse(row['publication_eligible'])
        raw=json.dumps(rows)
        for private in ('/private/validator-secret','validator_sha256','reviewed_manifest_sha256','abcdef1',
                        'result.program.actions','publication-reviewed.json'):
            self.assertNotIn(private,raw)

    def test_versioned_verdict_uses_latest_timestamp_and_never_falls_back_from_invalid_latest(self):
        folder,journal,result=self.attempt('1'*32)
        self.publication(folder,journal,result,version='abcdef1',at=9000)
        path,latest,_=self.publication(folder,journal,result,ready=False,version='1234567',at=9500)
        # Filename order is not chronology, and a newer failed check supersedes a pass.
        row=self.snapshot()['attempts'][0]
        self.assertEqual(row['publication_evidence'],{'status':'blocked','reason_code':'receipts_incomplete'})
        latest['reviewed_manifest_sha256']='0'*64;self.write(path,latest)
        row=self.snapshot()['attempts'][0]
        self.assertEqual(row['publication_evidence'],{'status':'blocked','reason_code':'evidence_unavailable'})
        self.assertEqual(row['persisted_xp'],100)

    def test_unknown_verdict_reasons_are_not_exported(self):
        folder,journal,result=self.attempt('1'*32)
        self.publication(folder,journal,result,ready=False,reasons=['private password marker /private/unsafe'])
        row=self.snapshot()['attempts'][0]
        self.assertEqual(row['publication_evidence'],{'status':'blocked','reason_code':'details_unavailable'})
        self.assertNotIn('private password',json.dumps(row));self.assertNotIn('/private/unsafe',json.dumps(row))

    def test_bad_verdict_metadata_blocks_publication_status_without_erasing_persisted_score(self):
        changes=[lambda v:v.update(run_id='2'*32),lambda v:v.update(schema_version=True),
                 lambda v:v.update(validator_source_commit='7654321'),lambda v:v.update(validator_sha256=None),
                 lambda v:v.update(validated_at_ms=10001),lambda v:v.update(validated_at_ms=True),
                 lambda v:v.update(externally_published=True),lambda v:v['verdict'].update(ready='true'),
                 lambda v:v['verdict'].update(reasons=['unexpected pass reason'])]
        for index,change in enumerate(changes):
            folder,journal,result=self.attempt(f'{index+1:032x}')
            path,verdict,_=self.publication(folder,journal,result)
            change(verdict);self.write(path,verdict)
        for row in self.snapshot()['attempts']:
            self.assertEqual(row['publication_evidence'],{'status':'blocked','reason_code':'evidence_unavailable'})
            self.assertEqual(row['persisted_xp'],100)

    def test_reviewed_manifest_cannot_relabel_other_result_score_recording_or_frozen_refs(self):
        changes=[lambda m:m['result']['controller'].update(model='gpt-5.6-sol'),
                 lambda m:m['score']['metrics'].update(net_xp=99999),lambda m:m['video'].update(reviewed=False),
                 lambda m:m['video'].update(sha256='f'*64),lambda m:m['video'].update(path='other.webm'),
                 lambda m:m['artifacts']['runtime_manifest'].update(sha256='1'*64),
                 lambda m:m['timeline'].update(status='failed')]
        for index,change in enumerate(changes):
            folder,journal,result=self.attempt(f'{index+1:032x}')
            path,verdict,reviewed=self.publication(folder,journal,result)
            change(reviewed)
            verdict['reviewed_manifest_sha256']=self.write(folder/'publication-reviewed.json',reviewed)['sha256']
            self.write(path,verdict)
        for row in self.snapshot()['attempts']:
            self.assertEqual(row['publication_evidence'],{'status':'blocked','reason_code':'evidence_unavailable'})
            self.assertEqual(row['persisted_xp'],100)

    def test_hashed_visual_review_cannot_be_omitted_or_attest_another_recording(self):
        for index,change in enumerate((lambda review:review.update(video_sha256='0'*64),
                                       lambda review:review.update(post_render_capture=False),
                                       lambda review:review.update(reviewed_at_ms=9500))):
            folder,journal,result=self.attempt(f'{index+1:032x}')
            path,verdict,reviewed=self.publication(folder,journal,result)
            review=json.loads((folder/'video-review.json').read_bytes());change(review)
            reviewed['artifacts']['video_review']=self.write(folder/'video-review.json',review)
            verdict['reviewed_manifest_sha256']=self.write(folder/'publication-reviewed.json',reviewed)['sha256']
            self.write(path,verdict)
        folder,journal,result=self.attempt('4'*32)
        self.publication(folder,journal,result)
        (folder/'video-review.json').unlink()
        for row in self.snapshot()['attempts']:
            self.assertEqual(row['publication_evidence']['status'],'blocked')
            self.assertEqual(row['persisted_xp'],100)

    def test_verdict_discovery_and_reads_are_bounded_and_symlink_safe(self):
        for index,mode in enumerate(('many','oversized','symlink','manifest_symlink','ambiguous')):
            folder,journal,result=self.attempt(f'{index+1:032x}')
            path,verdict,_=self.publication(folder,journal,result)
            if mode=='many':
                for number in range(16):
                    version=f'{number:07x}';self.write(folder/f'publication-verdict-{version}.json',verdict|{'validator_source_commit':version})
            elif mode=='oversized': path.write_bytes(b' '*(64*1024+1))
            elif mode=='symlink':
                target=self.root/'private-verdict.json';path.replace(target);path.symlink_to(target)
            elif mode=='manifest_symlink':
                manifest=folder/'publication-reviewed.json';target=self.root/'private-reviewed.json'
                manifest.replace(target);manifest.symlink_to(target)
            else: self.write(folder/'publication-verdict-1234567.json',verdict|{'validator_source_commit':'1234567'})
        for row in self.snapshot()['attempts']:
            self.assertEqual(row['publication_evidence'],{'status':'blocked','reason_code':'evidence_unavailable'})
            self.assertEqual(row['persisted_xp'],100)

    def test_failed_trial_cannot_gain_publication_status_from_a_sidecar(self):
        folder,journal,result=self.attempt('1'*32,status='failed')
        self.publication(folder,journal,result)
        row=self.snapshot()['attempts'][0]
        self.assertIsNone(row['publication_evidence']);self.assertIsNone(row['persisted_xp'])

    def test_two_exact_models_with_equal_inputs_compare_and_negative_xp_is_preserved(self):
        self.attempt('1'*32,xp=-600)
        self.attempt('2'*32,model='gpt-5.6-sol',xp=0)
        value=self.snapshot()
        self.assertEqual(len(value['comparisons']),1)
        self.assertTrue(value['comparisons'][0]['ready'])
        rows={row['id']:row for row in value['attempts']}
        self.assertEqual(rows['1'*32]['persisted_xp'],-600)
        self.assertFalse(rows['1'*32]['alive_at_logout'])
        self.assertEqual(rows['2'*32]['persisted_xp'],0)
        self.assertEqual(rows['1'*32]['diagnostic_xp'],0)
        self.assertTrue(all(row['attribution']=='exact' and not row['ranked'] and not row['publication_eligible'] for row in rows.values()))
        self.assertEqual(rows['1'*32]['score_verification'],'runner_verified_receipts_rechecked')
        raw=json.dumps(value)
        for private in ('private-password-marker','/private/secret-host','private_account_id','character_id','account_id','private.sql'):
            self.assertNotIn(private,raw)

    def test_runtime_or_budget_difference_prevents_cross_group_comparison(self):
        self.attempt('1'*32)
        self.attempt('2'*32,model='gpt-5.6-sol',runtime='e'*64)
        folder,journal,_=self.attempt('3'*32,model='gpt-5.6-terra')
        journal['request']['budgets']['max_actions']=240;self.write(folder/'journal.json',journal)
        value=self.snapshot()
        self.assertEqual(len(value['comparisons']),3)
        self.assertTrue(all(not group['ready'] for group in value['comparisons']))

    def test_false_flags_and_integration_sources_do_not_promote_unverified_scores(self):
        for index,change in enumerate(('missing_event','integration','failed','hash_mismatch')):
            run_id=f'{index+1:032x}'
            folder,journal,result=self.attempt(run_id)
            if change=='missing_event': journal['events']=[]
            elif change=='failed': journal['status']='failed'
            elif change=='integration':
                result['source']='client telemetry; unscored integration run'
                journal['receipts']['collect_final']['artifacts']['result']=self.write(folder/'result.json',result)
            else: (folder/'score.json').write_text('{}')
            self.write(folder/'journal.json',journal)
        value=self.snapshot()
        self.assertTrue(all(row['persisted_xp'] is None and row['comparison_group'] is None and not row['ranked'] for row in value['attempts']))
        self.assertEqual(value['comparisons'],[])

    def test_failed_pre_api_attempt_remains_visible_without_leaking_unknown_error_text(self):
        folder,journal,_=self.attempt('1'*32,status='failed')
        journal.update(phase='start_server',failure_code='host_command_failed')
        self.write(folder/'journal.json',journal)
        row=self.snapshot()['attempts'][0]
        self.assertEqual(row['phase'],'start_server');self.assertEqual(row['failure_code'],'host_command_failed')
        self.assertIsNone(row['persisted_xp'])
        for code in ('inventory_timeout','runtime_manifest_drift','docker_executable_changed',
                     'docker_binding_required','recorder_not_ready','client_busy_or_not_ready'):
            journal['failure_code']=code; self.write(folder/'journal.json',journal)
            self.assertEqual(self.snapshot()['attempts'][0]['failure_code'],code)
        journal['failure_code']='private-password-marker';self.write(folder/'journal.json',journal)
        self.assertEqual(self.snapshot()['attempts'][0]['failure_code'],'details_unavailable')

    def test_exact_returned_model_mismatch_is_visible_and_never_compared(self):
        folder,journal,result=self.attempt('1'*32)
        result['controller']['returnedModel']='gpt-5.6-sol';result['api']['model']='gpt-5.6-sol'
        journal['receipts']['collect_final']['artifacts']['result']=self.write(folder/'result.json',result)
        self.write(folder/'journal.json',journal)
        row=self.snapshot()['attempts'][0]
        self.assertEqual(row['returned_model'],'gpt-5.6-sol');self.assertEqual(row['attribution'],'mismatch')
        self.assertIsNone(row['persisted_xp']);self.assertIsNone(row['comparison_group'])

    def test_live_actions_and_diagnostic_xp_require_matching_fresh_run(self):
        run_id='1'*32;folder,journal,_=self.attempt(run_id,status='running')
        journal.update(phase='run_controller',receipts={});self.write(folder/'journal.json',journal)
        relay=self.relay/run_id;relay.mkdir()
        self.write(relay/'api-request-body.json',{'input':json.dumps({'observation':{'character':{'exp':1000,'level':180}}})})
        live={'bridge':{'fresh':True,'run':{'id':run_id,'status':'running','mode':'api','model':'gpt-6-astra','returnedModel':'gpt-6-astra','actions':12}},
            'observation':{'ready':True,'ageMs':0,'renderAgeMs':0,'character':{'exp':1123,'level':180,'alive':True,'account_id':'private'}}}
        row=self.snapshot(live_status=live)['attempts'][0]
        self.assertEqual(row['reported_actions'],12);self.assertEqual(row['diagnostic_xp'],123)
        self.assertIsNone(row['actions']);self.assertIsNone(row['acknowledged_actions'])
        self.assertIsNone(row['no_op']);self.assertEqual(row['action_verification'],'unverified')
        self.assertIsNone(row['persisted_xp']);self.assertTrue(row['alive_at_last_observation'])
        live['observation']['renderAgeMs']=2000
        self.assertIsNone(self.snapshot(live_status=live)['attempts'][0]['diagnostic_xp'])
        live['bridge']['run']['id']='2'*32
        self.assertIsNone(self.snapshot(live_status=live)['attempts'][0]['actions'])
        self.assertIsNone(self.snapshot(live_status=live)['attempts'][0]['reported_actions'])

    def test_completed_api_with_failed_trial_retains_diagnostics_and_recording_only(self):
        run_id='1'*32;folder,journal,result=self.attempt(run_id,status='recovered')
        journal.update(phase='cleanup',failure_code='runtime_operation_failed',api_outcome='uncertain',
            charged_usage={'api_requests':1,'total_tokens':30000},receipts={})
        journal['events'].append({'kind':'recovery_required','phase':'run_controller','at_ms':8300})
        self.write(folder/'journal.json',journal)
        result['controller']['actions']=34;result['observedXpDelta']=42
        relay=self.relay/run_id;relay.mkdir()
        self.write(relay/'controller.json',result['controller']);self.write(relay/'result.json',result)
        self.write(relay/'recording.json',{'status':'completed','sha256':'d'*64,
            'overlay':{'controller_id':run_id,'mode':'api','model':'gpt-6-astra'}})
        row=self.snapshot(recording_path_prefix='/full-client-benchmark/recordings/',recording_map={run_id:{
            'sha256':'d'*64,'url':'/full-client-benchmark/recordings/'+run_id+'.webm'}})['attempts'][0]
        self.assertEqual(row['status'],'recovered');self.assertEqual(row['failure_phase'],'run_controller')
        self.assertEqual(row['phase_states'],{'run_controller':'failed'})
        self.assertEqual(row['reported_actions'],34);self.assertEqual(row['diagnostic_xp'],42)
        self.assertIsNone(row['actions']);self.assertIsNone(row['acknowledged_actions'])
        self.assertIsNone(row['no_op']);self.assertEqual(row['action_verification'],'unverified')
        self.assertEqual(row['returned_model'],'gpt-6-astra');self.assertTrue(row['api_response_saved'])
        self.assertEqual(row['api_outcome'],'uncertain');self.assertEqual(row['charged_usage']['total_tokens'],30000)
        self.assertIsNotNone(row['recording']);self.assertIsNone(row['persisted_xp']);self.assertIsNone(row['comparison_group'])

    def test_recordings_need_explicit_safe_url_and_exact_saved_digest(self):
        self.attempt('1'*32)
        good={'1'*32:{'sha256':'d'*64,'url':'/recordings/run.webm'}}
        self.assertEqual(self.snapshot(recording_map=good)['attempts'][0]['recording']['url'],'/recordings/run.webm')
        for url in ('file:///private/video.webm','/Users/person/video.webm','//evil.example/recordings/a.webm',
                'http://127.0.0.1:8843/demo-session','https://evil.example/recordings/a.webm',
                '/recordings/../demo-session.webm','/recordings/%2e%2e/a.webm','/recordings/a.webm?token=private'):
            with self.subTest(url=url): self.assertIsNone(recording_url(url))
        good['1'*32]['sha256']='a'*64
        self.assertIsNone(self.snapshot(recording_map=good)['attempts'][0]['recording'])
        self.assertEqual(recording_url('http://127.0.0.1:8843/recordings/a.webm'),'http://127.0.0.1:8843/recordings/a.webm')
        nested='/full-client-benchmark/recordings/a.webm'
        self.assertIsNone(recording_url(nested))
        self.assertEqual(recording_url(nested,'/full-client-benchmark/recordings/'),nested)

    def test_corrupt_duplicate_key_and_symlink_evidence_fail_closed(self):
        folder,journal,_=self.attempt('1'*32)
        (folder/'journal.json').write_text('{"attempt_id":"x","attempt_id":"y"}')
        row=self.snapshot()['attempts'][0]
        self.assertEqual(row['status'],'unavailable');self.assertEqual(row['failure_code'],'evidence_unavailable')
        self.write(folder/'journal.json',journal)
        original=folder/'score.json';target=self.root/'private-score.json';original.replace(target);original.symlink_to(target)
        self.assertIsNone(self.snapshot()['attempts'][0]['persisted_xp'])
        (self.attempts/('2'*32)).symlink_to(folder,target_is_directory=True)
        self.assertEqual(len(self.snapshot()['attempts']),1)

    def test_limit_is_bounded_and_live_attempt_is_kept_visible(self):
        self.attempt('1'*32,status='running');self.attempt('2'*32)
        value=self.snapshot(limit=1,live_status={'run':{'id':'1'*32}})
        self.assertTrue(value['truncated']);self.assertEqual(value['attempts'][0]['id'],'1'*32)
        for limit in (True,0,101):
            with self.assertRaises(ValueError): self.snapshot(limit=limit)

    def test_atomic_output_modes_and_cli_failure_never_echo_private_path(self):
        output=self.root/'results.json';value=self.snapshot()
        write_snapshot(output,value)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode),0o600)
        write_snapshot(output,value,public=True)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode),0o644)
        with mock.patch('builtins.print') as printed:
            self.assertEqual(main(['--attempt-root',str(self.root/'private-missing')]),1)
        self.assertNotIn('private-missing',str(printed.call_args))
        alias=self.root/'alias.json';alias.symlink_to(output)
        with self.assertRaises(ValueError): write_snapshot(alias,value)

    def test_private_socket_sends_only_status_and_rejects_public_modes(self):
        parent=self.root/'admin';parent.mkdir(mode=0o700)
        path=parent/'status.sock';requests=[];errors=[]
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
            server.bind(str(path));path.chmod(0o600);server.listen(1);server.settimeout(2)
            def respond():
                try:
                    connection,_=server.accept()
                    with connection:
                        connection.settimeout(2);requests.append(connection.recv(1024))
                        connection.sendall(b'{"ok":true,"result":{"bridge":{"fresh":true,"run":{"status":"idle"}}}}\n')
                except Exception as error: errors.append(type(error).__name__)
            worker=threading.Thread(target=respond,daemon=True);worker.start()
            response=read_admin_status(path)
            worker.join(2)
            self.assertEqual(errors,[]);self.assertEqual(requests,[b'{"op":"status"}\n'])
            self.assertTrue(response['result']['bridge']['fresh'])
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError,'untrusted_status_socket'): read_admin_status(path)
            path.chmod(0o600);parent.chmod(0o755)
            with self.assertRaisesRegex(ValueError,'untrusted_status_socket'): read_admin_status(path)

    def test_watch_is_finite_and_updates_sanitized_snapshot_after_socket_failure(self):
        clock=[0];output=self.root/'results.json';snapshot=self.snapshot()
        def sleep(seconds): clock[0]+=seconds
        with mock.patch('full_client_dashboard.time.monotonic',side_effect=lambda:clock[0]), \
             mock.patch('full_client_dashboard.time.sleep',side_effect=sleep), \
             mock.patch('full_client_dashboard.read_admin_status',side_effect=[{'ok':True,'result':{}},ValueError('private error')]) as status, \
             mock.patch('full_client_dashboard.build_snapshot',side_effect=lambda *args,**kwargs:copy.deepcopy(snapshot)), \
             mock.patch('full_client_dashboard.write_snapshot') as write:
            code=main(['--attempt-root',str(self.attempts),'--admin-socket',str(self.root/'socket'),
                '--watch-seconds','3','--output',str(output),'--public-output'])
        self.assertEqual(code,0);self.assertEqual(clock[0],3);self.assertEqual(status.call_count,2)
        self.assertEqual(write.call_count,2)
        self.assertTrue(write.call_args_list[0].args[1]['live_status_available'])
        self.assertFalse(write.call_args_list[1].args[1]['live_status_available'])
        self.assertTrue(write.call_args.kwargs['public'])
        self.assertNotIn('private error',str(write.call_args_list))
        for arguments in (['--watch-seconds','3601'],['--watch-seconds','-1'],['--watch-seconds','2']):
            with mock.patch('builtins.print'),mock.patch('full_client_dashboard.build_snapshot') as build:
                self.assertEqual(main(['--attempt-root',str(self.attempts)]+arguments),1)
                build.assert_not_called()


if __name__=='__main__': unittest.main()
