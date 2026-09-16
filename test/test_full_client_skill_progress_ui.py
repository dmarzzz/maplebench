"""Production UI functions against public projection bytes; no browser/runtime."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import full_client_skill_progress as progress
from test_full_client_matrix_ui import TASKS
from test_full_client_redesign import DOM, PRESENTATION_HELPERS, PROTOCOL_HELPERS, function


@unittest.skipUnless(shutil.which('node'), 'Node is required')
class SkillProgressUITests(unittest.TestCase):
    def fixture(self):
        plan = progress.load_plan()
        report = {'schema_version': 1, 'design_id': progress.DESIGN, 'status': 'qualification_pending',
            'last_updated_at_utc': None, 'reporting_note': '', 'execution_manifests': [],
            'phase_counts': progress.phase_counts(plan, {}), 'entries': {}, 'blockers': [], 'next_action': ''}
        return progress.project(report, plan)

    def run_js(self, checks):
        projection = self.fixture()
        code = "const assert=require('node:assert/strict'); const crypto=require('node:crypto').webcrypto;\n"
        code += PROTOCOL_HELPERS + DOM + PRESENTATION_HELPERS + TASKS + function('cell')
        code += "let researchIdentity='',researchView='skill',researchButtons=[],closed=false;\n"
        code += 'const fixture=' + json.dumps(projection['manifest']) + ';\n'
        code += 'const shards=' + json.dumps({name: raw.decode() for name, raw in projection['shards'].items()}) + ';\n'
        code += '(async()=>{' + checks + '})().catch(e=>{console.error(e);process.exitCode=1});'
        result = subprocess.run([shutil.which('node'), '--max-old-space-size=96', '-'],
            input=code, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_true_projection_renders_separate_matrix_without_historical_results(self):
        self.run_js(r"""
assert.ok(validSkillManifest(fixture));skillManifest=fixture;
$('skill-matrix-phase').value='skill-comparative';renderSkillMatrix();
assert.equal(researchButtons.length,24);assert.match(researchButtons[0].textContent,/0\/24 coverage/);
assert.match($('matrix-inspector').textContent,/24 unreported/);
assert.equal(researchIdentity,'');assert.equal(snapshot,undefined);
$('skill-matrix-phase').value='skill-development';renderSkillMatrix();
assert.match(researchButtons[0].textContent,/0\/8 coverage/);
assert.match(researchButtons[3].textContent,/Not scheduled/);
const forged=structuredClone(fixture);forged.experiments[0].path='https://private.test/secret';
assert.equal(validSkillManifest(forged),false);
""")

    def test_root_mount_hash_verification_and_tampering_refusal_use_actual_loader(self):
        self.run_js(r"""
skillManifest=fixture;$('skill-progress-experiment').value='12';
$('skill-progress-model').value='gpt-5.6-sol';$('skill-progress-filter').value='all';
const experiment=fixture.experiments.find(e=>e.experiment_number===12);let requested;
fetch=async path=>{requested=path;return new Response(shards[experiment.path]);};
await loadSkillExperiment();assert.equal(requested,'/'+experiment.path);
assert.equal($('skill-trial-rows').children.length,24);
assert.match($('skill-trial-rows').children[0].textContent,/T0362/);
assert.match($('skill-trial-rows').children[0].textContent,/max_output_tokens/);
assert.match($('skill-trial-rows').children[0].textContent,/Execution config unverified/);
skillCache.clear();fetch=async()=>new Response(shards[experiment.path].replace('gpt-5.6-sol','gpt-6-astra'));
await loadSkillExperiment();assert.equal($('skill-trial-rows').children.length,0);
assert.match($('skill-trials-state').textContent,/failed its content-hash check/);
""")

    def test_native_pass_failure_invalid_and_unreported_have_honest_labels(self):
        self.run_js(r"""
assert.equal(skillStatusLabel({reported:false,status:'not_started'}),'Unreported');
assert.equal(skillStatusLabel({reported:true,kind:'native_control',status:'success',outcome:'passed'}),'Native check passed');
assert.equal(skillStatusLabel({reported:true,kind:'model_trial',status:'gameplay_failure'}),'Gameplay failure');
assert.equal(skillStatusLabel({reported:true,kind:'model_trial',status:'invalid'}),'Invalid');
assert.equal(skillStatusLabel({reported:true,kind:'model_trial',status:'in_progress'}),'In progress');
""")


if __name__ == '__main__': unittest.main()
