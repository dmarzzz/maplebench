"""Synthetic adaptive publication only; no provider, service, database or deploy."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import full_client_publication as publication
import full_client_adaptive_publication as projection
from full_client_adaptive import DEFAULT_PROTOCOL, PROTOCOL
from full_client_score import EvidenceError, score_trial, verify_trial_bundle
from full_client_publish import _measure_video_probe
from full_client_research import summarize
from full_client_capture import capture_receipt
import test_full_client_adaptive as adaptive_fixtures
from test_full_client_score import bundle_fixture, write_artifact


class AdaptivePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.attempts=self.root/'attempts';self.attempts.mkdir()
        self.output=self.root/'packages';self.output.mkdir()
        self.config=self.root/'config';self.config.mkdir()
        self.models=['gpt-6-astra','gpt-5.6-sol','gpt-5.6-terra','gpt-5.6-luna']
        self.ids=[str(i)*32 for i in range(1,5)]
        protocol=copy.deepcopy(DEFAULT_PROTOCOL);protocol['max_api_requests']=16
        budgets={'total_seconds':900,'operation_seconds':400,'controller_seconds':300,'max_actions':1600,
                 'max_api_requests':16,'max_output_tokens':3000,'max_total_tokens':120000}
        self.scenario={'id':'synthetic-adaptive','protocol':PROTOCOL,'adaptive_protocol':protocol,'trial_budgets':budgets}
        self.scenario_path=self.config/'scenario.json';self.scenario_path.write_text(json.dumps(self.scenario,sort_keys=True))
        fixture={'id':'synthetic','scenario':{'sha256':hashlib.sha256(self.scenario_path.read_bytes()).hexdigest()},
            'baseline':{'sha256':hashlib.sha256(b'synthetic database baseline').hexdigest()},
            'runtime_manifest':{'sha256':hashlib.sha256(json.dumps({'schema_version':1},sort_keys=True).encode()).hexdigest()},
            'adapter_fingerprint':'9'*64,'budgets':budgets}
        entries=[]
        for i,(ident,model) in enumerate(zip(self.ids,self.models)):
            spec={'schema_version':2,'protocol':PROTOCOL,'model':model,'scenario_fingerprint':fixture['scenario']['sha256'],
                  'baseline_sha256':fixture['baseline']['sha256'],'budgets':budgets}
            entries.append({'ordinal':i,'attempt_id':ident,'model':model,'repetition':1,'fixture_id':'synthetic',
                            'spec':spec,'spec_sha256':publication.digest(publication.encoded(spec))})
        self.plan={'schema_version':1,'repetitions':1,'models':self.models,'fixtures':[fixture],'entries':entries}
        self.path=self.config/'plan.json';self.path.write_bytes(publication.encoded(self.plan))
        self.plan_sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.profile={'protocol_id':PROTOCOL,'class_id':'hero','task_id':'sustained_hunting'}

    def tearDown(self):self.temp.cleanup()

    def attempt(self,index,xp=100):
        ident=self.ids[index];model=self.models[index];folder=self.attempts/ident;folder.mkdir()
        harness=adaptive_fixtures.Harness(folder);harness.p=copy.deepcopy(self.scenario['adaptive_protocol'])
        with patch.object(adaptive_fixtures,'RUN',ident),patch.object(adaptive_fixtures,'MODEL',model):
            harness.run();result=harness.result()
        evidence,refs=bundle_fixture(folder,self.scenario)
        for value in (evidence,evidence['initial'],evidence['final'],evidence['reset'],evidence['session'],evidence['session']['save']):
            value['run_id']=ident
        evidence.update(schema_version=2,protocol=PROTOCOL)
        evidence['reset']['completed_at_ms']=800000;evidence['initial']['captured_at_ms']=810000
        end=result['timing']['endedAtMs'];session=evidence['session']
        intervals=[{'index':c['index'],'started_at_ms':1000000+c['timing']['api_started_ms'],
                    'ended_at_ms':1000000+c['timing']['api_ended_ms']} for c in result['adaptive']['cycles'] if c['api_outcome']=='confirmed']
        session.update(protocol=PROTOCOL,server_started_at_ms=900000,login_at_ms=999800,
            controller_started_at_ms=1000000,controller_ended_at_ms=end,api_started_at_ms=intervals[0]['started_at_ms'],
            api_ended_at_ms=intervals[-1]['ended_at_ms'],api_intervals=intervals,
            adaptive_trace_sha256=result['adaptiveTrace']['sha256'],disconnect_requested_at_ms=end+10,logged_out_at_ms=end+100)
        evidence['final']['captured_at_ms']=end+200;evidence['final']['character']['exp']+=xp
        session['save'].update(committed_at_ms=end+50,log_checked_from_ms=900000,log_checked_through_ms=end+300)
        identity={'run_id':ident,'server_instance_id':session['server_instance_id'],'character_id':7,'account_id':9}
        receipt={'schema_version':1,'source':evidence['source'],'kind':'save_committed',**identity,'committed_at_ms':end+50}
        session['save']['evidence_sha256']=write_artifact(folder,refs,'save',(json.dumps(receipt)+'\n').encode(),raw=True)
        events=[{'event':event,'at_ms':at,**identity} for event,at in [('server_started',900000),('login',999800),
                ('logged_out',end+100),('collection_completed',end+200)]]
        session['save']['logs_sha256']=write_artifact(folder,refs,'server_log',''.join(json.dumps(v)+'\n' for v in events).encode(),raw=True)
        for name in ('initial','final'):
            raw={k:v for k,v in evidence[name].items() if k!='evidence_sha256'}
            evidence[name]['evidence_sha256']=write_artifact(folder,refs,name+'_db',raw)
        for name in ('reset','session'):write_artifact(folder,refs,name,evidence[name])
        write_artifact(folder,refs,'persistence',evidence)
        context={'scenario_fingerprint':evidence['scenario_fingerprint'],'baseline_sha256':evidence['baseline']['sha256']}
        result['trialContext']=context;result['controller'].update(mode='api',trialContext=context,dockerImageId='sha256:'+'f'*64)
        result['observedXpDelta']=999999;result['final']={'character':{'alive':True}}
        write_artifact(folder,refs,'result',result);write_artifact(folder,refs,'runtime_manifest',{'schema_version':1})
        video=b'SYNTHETIC VIDEO';(folder/'video.webm').write_bytes(video)
        refs['video']={'path':'video.webm','sha256':hashlib.sha256(video).hexdigest()}
        result['controller']['client']='synthetic-browser';write_artifact(folder,refs,'result',result)
        start=result['timing']['startedAtMs']
        clock={'id':'synthetic-clock','client_sent_ms':start,'server_received_ms':start,'server_sent_ms':start}
        ready={'runId':ident,'serverReceivedAtMs':start+20,'renderedFrames':1}
        terminal={'id':'f'*32,'serverIssuedAtMs':end+10}
        capture={'schema_version':1,'run_id':ident,'client_id':'synthetic-browser',
            'start_wall_ms':start,'end_wall_ms':end+100,'duration_ms':end+100-start,
            'first_frame_wall_ms':start+10,'last_frame_wall_ms':end+90,'rendered_frames':9000,'max_frame_gap_ms':34,
            'hidden':False,'errors':0,'relay_lost':False,'interrupted':False,
            'clock':clock|{'client_received_ms':start},'terminal_token':terminal['id']}
        for name,value in [('capture',capture),('capture_clock',clock),('capture_ready',ready),('capture_terminal',terminal)]:
            write_artifact(folder,refs,name,value)
        recording={'status':'completed','sha256':refs['video']['sha256'],'capture_sha256':refs['capture']['sha256'],
            'overlay':{'controller_id':ident,'mode':'api','model':model},
            **capture_receipt(capture,{'id':ident,'client':'synthetic-browser','startedAtMs':start,'protocol':PROTOCOL},ready,clock,terminal)}
        write_artifact(folder,refs,'recording',recording)
        score=verify_trial_bundle(evidence,folder,refs);write_artifact(folder,refs,'score',score)
        journal={'attempt_id':ident,'status':'completed','phase':'cleanup','request':self.plan['entries'][index]['spec'],
            'adapter_fingerprint':'9'*64,'score':score,'api_outcome':'confirmed',
            'events':[{'kind':'created','at_ms':799000},{'kind':'evidence_verified','at_ms':end+250}],
            'receipts':{'collect_final':{'artifacts':refs}}}
        (folder/'journal.json').write_text(json.dumps(journal))
        return folder,journal,result

    def prepare(self,**kwargs):
        with patch('full_client_publish._probe_video',return_value={'duration_ms':300200,'width':1024,'height':768,'frames':9000}):
            value=publication.prepare_package(self.path,self.plan_sha,self.attempts,self.output,
                adaptive_scenario=self.scenario_path,research_profile=self.profile,**kwargs)
        return value,json.loads((Path(value['site'])/'results.json').read_text())

    def test_full_wall_run_uses_native_xp_and_all_cycles_and_keeps_planned_models(self):
        self.attempt(0,xp=-50);value,snapshot=self.prepare();row=snapshot['attempts'][0]
        self.assertEqual(row['persisted_xp'],-50);self.assertEqual(row['diagnostic_xp'],999999)
        self.assertEqual(row['score_verification'],projection.VERIFIED)
        self.assertEqual(row['adaptive']['wall_elapsed_ms'],300000)
        self.assertEqual(len(row['adaptive']['cycles']),10)
        self.assertEqual(row['api_usage']['total_tokens'],1200)
        self.assertIsNone(row['adaptive']['authoritative_peak_xp_per_minute'])
        self.assertEqual([r['status'] for r in snapshot['attempts']],['completed','not_started','not_started','not_started'])
        self.assertNotIn('synthetic database baseline',json.dumps(snapshot));self.assertNotIn('recent_programs',json.dumps(snapshot))
        self.assertFalse(value['cohort_complete'])
        self.assertEqual(snapshot['research_matrix']['models'][0]['cells'][0]['mean'],-50)

    def test_corrupt_earlier_cycle_cannot_be_replaced_by_last_cycle(self):
        folder,_,result=self.attempt(0)
        (folder/result['adaptive']['cycles'][0]['response']['path']).write_text('{}')
        _,snapshot=self.prepare();row=snapshot['attempts'][0]
        self.assertIsNone(row['persisted_xp']);self.assertIsNone(row['recording']);self.assertEqual(row['status'],'unavailable')

    def test_native_save_corruption_does_not_get_a_score_from_client_xp(self):
        folder,journal,_=self.attempt(0)
        (folder/journal['receipts']['collect_final']['artifacts']['save']['path']).write_text('{}')
        _,snapshot=self.prepare();self.assertIsNone(snapshot['attempts'][0]['persisted_xp'])

    def test_bad_recording_preserves_whole_run_score_and_blocks_archive_replacement(self):
        folder,_,_=self.attempt(0);(folder/'video.webm').write_bytes(b'corrupt')
        _,snapshot=self.prepare();self.assertEqual(snapshot['attempts'][0]['persisted_xp'],100)
        self.assertIsNone(snapshot['attempts'][0]['recording'])
        with self.assertRaisesRegex(ValueError,'four_verified_recordings'):self.prepare(replace_archive=True)

    def test_explicit_profile_must_match_frozen_class(self):
        self.profile['class_id']='bowmaster'
        with self.assertRaisesRegex(ValueError,'adaptive_public_class_mismatch'):self.prepare()

    def test_complete_four_model_group_keeps_signed_results_and_is_idempotent(self):
        for index,xp in enumerate((0,-50,100,9000)):self.attempt(index,xp)
        value,snapshot=self.prepare(replace_archive=True)
        repeated,_=self.prepare(replace_archive=True)
        self.assertEqual(value['content_sha256'],repeated['content_sha256'])
        self.assertTrue(value['cohort_complete']);self.assertEqual(value['target_path'],'/')
        self.assertEqual([row['persisted_xp'] for row in snapshot['attempts']],[0,-50,100,9000])
        self.assertEqual(len(snapshot['comparisons']),1)

    def test_legacy_entrypoint_refuses_adaptive_plan(self):
        with self.assertRaisesRegex(ValueError,'legacy_specs_required'):
            publication.prepare_package(self.path,self.plan_sha,self.attempts,self.output)

    def test_dangling_attempt_link_is_unknown_not_an_unstarted_model(self):
        (self.attempts/self.ids[0]).symlink_to(self.root/'missing')
        _,snapshot=self.prepare()
        self.assertEqual(snapshot['attempts'][0]['status'],'unavailable')

    def test_late_first_input_cue_preserves_full_timeline_and_rejects_noop(self):
        result={'timeline':{'program_started_ms':100,'program_ended_ms':300100,
            'first_input_started_ms':280100,'first_input_acked_ms':280250}}
        recording={'start_ms':0,'end_ms':300200,'duration_ms':300200,'timing_uncertainty_ms':9,
                   'timing_method':'browser_monotonic_duration_with_measured_clock_offset'}
        self.assertEqual(projection.playback_cue(result,recording,1)['start_ms'],279850)
        self.assertIsNone(projection.playback_cue(result,recording,0))
        recording['timing_uncertainty_ms']=101
        self.assertIsNone(projection.playback_cue(result,recording,1))

    def test_five_minute_probe_envelope_is_explicit_and_bounded(self):
        probe={'streams':[{'width':1024,'height':768,'nb_read_frames':'300'}],
            'format':{},'packets':[{'pts_time':str(i),'duration_time':'1','flags':'__'} for i in range(300)]}
        with self.assertRaises(EvidenceError):_measure_video_probe(probe)
        self.assertEqual(_measure_video_probe(probe,maximum_ms=335000)['duration_ms'],300000)
        with self.assertRaises(EvidenceError):_measure_video_probe(probe,maximum_ms=999999)

    def test_large_video_hashing_is_streamed_and_legacy_cap_stays_smaller(self):
        path=self.root/'video.webm'
        with path.open('wb') as out:
            for _ in range(33):out.write(b'x'*1024**2)
        expected=hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
        with self.assertRaisesRegex(ValueError,'publication_file_limit'):
            publication.stable_fingerprint(path,publication.MAX_VIDEO)
        value=publication.stable_fingerprint(path,publication.MAX_ADAPTIVE_VIDEO)
        self.assertEqual(value,{'bytes':33*1024**2,'sha256':expected})
        path.unlink();path.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError,'publication_symlink'):
            publication.stable_fingerprint(path,publication.MAX_ADAPTIVE_VIDEO)


if __name__=='__main__':unittest.main()
