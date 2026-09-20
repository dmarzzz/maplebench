"""Synthetic clock/sanitizer and real dashboard-function checks; no gameplay."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_replay import project_timeline,validate_timeline
from full_client_catalog import safe_public


class ReplayTests(unittest.TestCase):
    def fixture(self):
        result={'timeline':{'adaptive_started_ms':100},'adaptive':{'cycles':[
            {'index':0,'api_outcome':'confirmed','timing':{'api_started_ms':0,'api_ended_ms':900}}]}}
        recording={'start_ms':-50,'end_ms':300200,'duration_ms':300250,'timing_uncertainty_ms':7,
            'timing_method':'browser_monotonic_duration_with_measured_clock_offset',
            'capture_duration_policy':{'id':'post-render-encoded-frame-v1'},'first_frame_offset_ms':40}
        checked={'input_intervals':[{'cycle_index':0,'rpc_id':1,'keys':['RIGHT','PRIMARY_SKILL'],
            'duration_ms':500,'requested_ms':920,'acknowledged_ms':1430}]}
        return result,recording,checked

    def test_all_clocks_map_to_first_encoded_frame_and_drop_private_fields(self):
        value=project_timeline(*self.fixture())
        self.assertEqual(value['api_intervals'],[[110,1010,0]])
        self.assertEqual(value['input_intervals'],[[1030,1540,0,['RIGHT','PRIMARY_SKILL'],500]])
        self.assertEqual(value['duration_ms'],300210)
        self.assertNotIn('rpc_id',json.dumps(value));safe_public({'recording':{'timeline':value}})

    def test_old_input_timing_is_unknown_not_an_empty_observed_set(self):
        result,recording,checked=self.fixture();checked={}
        self.assertIsNone(project_timeline(result,recording,checked)['input_intervals'])
        checked['input_intervals']=[]
        self.assertEqual(project_timeline(result,recording,checked)['input_intervals'],[])

    def test_unbound_and_uncertain_clocks_produce_no_timeline(self):
        result,recording,checked=self.fixture()
        for changes in ({'timing_uncertainty_ms':101},{'start_ms':200},
                        {'first_frame_offset_ms':500},{'timing_method':'assumed'}):
            self.assertIsNone(project_timeline(result,recording|changes,checked))

    def test_timeline_rejects_private_extensions_unknown_keys_and_unbounded_rows(self):
        original=project_timeline(*self.fixture())
        mutations=[lambda v:v.update(prompt='private'),
            lambda v:v['input_intervals'][0][3].append('DELETE'),
            lambda v:v['input_intervals'][0].__setitem__(1,400000),
            lambda v:v['api_intervals'].append([100,200,1]),
            lambda v:v.__setitem__('input_intervals',v['input_intervals']*2401)]
        for mutate in mutations:
            value=copy.deepcopy(original);mutate(value)
            with self.assertRaises(ValueError):validate_timeline(value)
            with self.assertRaises(ValueError):safe_public({'recording':{'timeline':value}})

    @unittest.skipUnless(shutil.which('node'),'Node required for dashboard checks')
    def test_actual_ui_boundary_state_and_invalid_data(self):
        source=(Path(__file__).resolve().parents[1]/'ui/full-client-dashboard/dashboard.js').read_text()
        code=source[source.index('  const replayControls='):source.index('  function updateReplayTimeline(')]
        value=project_timeline(*self.fixture())
        code="const assert=require('node:assert/strict');\n"+code+'\nconst value='+json.dumps(value)+";\n"+r'''
assert.ok(checkedReplayTimeline(value));
assert.equal(replayEventState(value,110).api[2],0);
assert.equal(replayEventState(value,1010).api,undefined);
assert.deepEqual(replayEventState(value,1030).input[3],['RIGHT','PRIMARY_SKILL']);
assert.equal(replayEventState(value,1540).input,undefined);
const invalid=structuredClone(value);invalid.input_intervals[0][3]=['BAD'];
assert.equal(checkedReplayTimeline(invalid),null);
assert.equal(checkedReplayTimeline(null),null);
'''
        result=subprocess.run([shutil.which('node'),'--max-old-space-size=64','-e',code],
            text=True,capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
