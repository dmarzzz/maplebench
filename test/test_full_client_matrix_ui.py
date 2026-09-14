"""Square-matrix evidence semantics; no API, runtime or generated scores."""
import shutil
import subprocess
import unittest

from test_full_client_redesign import (
    DOM, PRESENTATION_HELPERS, PROTOCOL_HELPERS, SOURCE, function,
)

TASKS = SOURCE[SOURCE.index('  const plannedSkillTasks='):SOURCE.index('  function matrixCellState(')]


@unittest.skipUnless(shutil.which('node'), 'Node is required')
class MatrixUITests(unittest.TestCase):
    def run_js(self, helpers, checks):
        code = "const assert=require('node:assert/strict');\n"
        code += PROTOCOL_HELPERS + DOM + PRESENTATION_HELPERS + TASKS
        code += "let researchIdentity='',researchView='class',researchSelection=null,researchButtons=[],played;\n"
        code += "const openReplay=(url,row)=>{played=row.id;};\n"
        code += ''.join(function(name) for name in helpers) + checks
        result = subprocess.run([shutil.which('node'), '--max-old-space-size=64', '-e', code],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_signed_zero_unknown_unrun_and_running_remain_distinct(self):
        self.run_js(['matrixCellState'], r"""
const value={attempt_ids:['run'],valid:1,mean:0};
assert.deepEqual(matrixCellState(value,100),{tone:'zero',text:'0',label:'1 scored run'});
assert.equal(matrixCellState({...value,mean:-500},100).tone,'loss');
assert.equal(matrixCellState({...value,mean:-500},100).text,'-500');
assert.equal(matrixCellState({...value,mean:100},100).tone,'high');
assert.equal(matrixCellState({...value,mean:null,valid:0,unknown:1},100).tone,'unknown');
assert.equal(matrixCellState({...value,mean:null,valid:0,attempted:0,not_started:1},100).tone,'unrun');
assert.equal(matrixCellState({...value,mean:null,valid:0,in_progress:1},100).label,'In progress');
assert.equal(matrixCellState(null,100).text,'—');
assert.equal(matrixCellState({...value,attempt_ids:[]},100).tone,'unrun');
""")

    def test_selected_cell_keeps_model_run_mapping_and_planned_tasks_have_no_scores(self):
        self.run_js(['cell','recording','matrixCellState','showMatrixCell','renderResearch'], r"""
const protocol={id:'full-client-adaptive-pilot-v1',label:'Pilot',score_key:'persisted_xp',metric:'Saved net XP',clock:'300 seconds',status:'Unranked'};
const columns=['hero','bowmaster','mage'].map(id=>({id,class_id:id,class_label:id,task_label:'Combat',protocol_id:protocol.id,fixture_fingerprint:'f'.repeat(64)}));
const make=(id,column,mean)=>({column_id:column,attempt_ids:[id],mean,valid:1,planned:1,attempted:1,failed:0,unknown:0,in_progress:0,not_started:0});
snapshot={attempts:[sample('a','gpt-6-astra',100),sample('b','gpt-6-astra',0),sample('c','gpt-6-astra',-50),sample('d','gpt-5.6-sol',40)],
 research_matrix:{schema_version:1,protocols:[protocol],columns,models:[
 {model:'gpt-6-astra',cells:[make('a','hero',100),make('b','bowmaster',0),make('c','mage',-50)]},
 {model:'gpt-5.6-sol',cells:[make('d','hero',40)]}]}};
$('research-protocol').value=protocol.id;
const frozen=JSON.stringify(snapshot);
renderResearch();assert.equal(researchButtons.length,6);
assert.match(researchButtons[1].textContent,/^0/);assert.match(researchButtons[2].textContent,/-50/);
researchButtons[3].emit('click');assert.match($('matrix-inspector').textContent,/GPT-5.6 Sol.*\+40 XP/);
const links=$('matrix-inspector').children.at(-1);links.children[0].emit('click');assert.equal(played,'d');
assert.equal(researchButtons.filter(b=>b.attrs['aria-pressed']==='true').length,1);
const retained=researchButtons;renderResearch();assert.equal(researchButtons,retained);
researchView='skill';renderResearch();assert.equal(researchButtons.length,12);
assert.ok(researchButtons.every(b=>b.textContent==='—Unrun'||b.textContent==='— Unrun'));
researchButtons[11].emit('click');assert.match($('matrix-inspector').textContent,/GPT-5.6 Sol.*Recovery/);
assert.match($('matrix-inspector').textContent,/no runs yet/);
assert.equal(JSON.stringify(snapshot),frozen);
researchView='class';renderResearch();assert.equal(researchButtons.length,6);
assert.equal(JSON.stringify(snapshot),frozen);
""")
