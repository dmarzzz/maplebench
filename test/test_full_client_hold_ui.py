"""Run the real dashboard functions against bounded DOM fixtures; no browser/API."""
from pathlib import Path
import shutil
import subprocess
import unittest


SOURCE = (Path(__file__).resolve().parents[1] / 'ui/full-client-dashboard/dashboard.js').read_text()


def function(name, following):
    return SOURCE[SOURCE.index('  function ' + name):SOURCE.index('  function ' + following)]


DOM = r"""
const assert=require('node:assert/strict');
class Node {
  constructor(tag,text){this.tag=tag;this.children=[];this._text=text==null?'':String(text);this.classList={add:()=>{}};this.dataset={};}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join(' ');}
  set textContent(value){this._text=String(value);this.children=[];}
  append(...values){this.children.push(...values);}
  replaceChildren(...values){this._text='';this.children=values;}
  replaceWith(value){nodes[this.id]=value;}
  focus(){this.focused=true;}
}
const nodes={},$=id=>nodes[id]||=Object.assign(new Node('div'),{id}),el=(tag,text)=>new Node(tag,text);
const seconds=value=>Number.isFinite(value)?`${(value/1000).toFixed(1)}s`:'—';
const format=value=>Number.isFinite(value)?value.toLocaleString('en-US'):'—';
const xp=value=>Number.isFinite(value)?`${value>0?'+':''}${format(value)}`:'—';
const alive=value=>value===true?'Alive':value===false?'Dead':'—';
const cell=(row,value)=>{const node=el('td',value);row.append(node);return node;};
const badge=status=>el('span',status);
const inputDetails=(node,row)=>node.textContent=`${row.acknowledged_actions} acknowledged`;
const recording=(node,row)=>node.append(el('button',`Watch ${row.id}`));
const publicationCell=()=>{};
const scoreCell=(tr,row)=>cell(tr,xp(row.persisted_xp));
const phases=[['run_controller','Play'],['collect_final','Verify XP'],['cleanup','Finish']];
let snapshot;
function row(model='gpt-6-astra',start=135106){return {
 id:'1234567890abcdef1234567890abcdef',requested_model:model,returned_model:model,
 status:'completed',phase:'cleanup',score_verification:'adaptive_runner_verified_receipts_rechecked',
 persisted_xp:18250,alive_at_logout:true,acknowledged_actions:98,
 research:{protocol_id:'full-client-adaptive-pilot-v1'},
 timing:{api_ms:64000,controller_ms:300000},
 recording:{url:'./recordings/1234567890abcdef1234567890abcdef.webm',playback:{basis:'first_acknowledged_input',start_ms:2750}},
 adaptive:{verification:'all_cycle_receipts_rechecked',wall_elapsed_ms:300000,
  horizon_policy:{id:'full-horizon-reserve-v1'},horizon_wait:{reason:'token_reservation_limit',started_ms:start,ended_ms:300000},
  counters:{api_responses_confirmed:6},full_wall_budget_used:true,end_reason:'wall_budget_reached',
  cycles:[{index:0,status:'confirmed',returned_model:model,timing:{api_started_ms:0,api_ended_ms:12000,program_started_ms:12000,program_ended_ms:20000},actions:16,action_attempts:16,usage:{total_tokens:2000}}]}
};}
"""


@unittest.skipUnless(shutil.which('node'), 'Node is required for dashboard UI checks')
class AdaptiveHoldUITests(unittest.TestCase):
    def run_js(self, functions, checks):
        code=DOM + ''.join(function(name, following) for name, following in functions) + checks
        result=subprocess.run([shutil.which('node'), '--max-old-space-size=64', '-e', code],
                              capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_previous_cohort_navigation_is_separate_and_bounded(self):
        self.run_js([('renderCatalog(', 'renderResearch(')], r"""
const document={createTextNode:text=>new Node('text',text)};
const active={url:'./cohorts/'+'a'.repeat(16)+'/',class_id:'hero',verified:1};
const prior={url:'./cohorts/'+'b'.repeat(16)+'/',class_id:'hero',verified:2};
snapshot={catalog:{schema_version:2,cohorts:[active],previous_cohorts:[prior]}};
renderCatalog();const nav=$('catalog-cohorts');assert.equal(nav.hidden,false);
assert.equal(nav.children.length,2);assert.match(nav.children[0].textContent,/Current cohorts/);
assert.match(nav.children[1].textContent,/Previous pilot cohorts/);
assert.match(nav.children[1].textContent,/excluded from the current matrix/);
assert.equal(nav.children[1].children[1].href,prior.url);
snapshot.catalog.previous_cohorts=[{...prior,url:'https://untrusted.example/'}];
renderCatalog();assert.equal(nav.children[1].children.length,1);
snapshot.catalog.previous_cohorts=Array(4).fill(prior);renderCatalog();assert.equal(nav.hidden,true);
snapshot.catalog={schema_version:1,cohorts:[active]};renderCatalog();assert.equal(nav.hidden,false);assert.equal(nav.children.length,1);
""")

    def test_actual_wait_durations_and_fail_closed_metadata(self):
        self.run_js([('adaptiveHold(', 'adaptiveDetails(')], r"""
let astra=row(),sol=row('gpt-5.6-sol',203573);
assert.equal(adaptiveHold(astra).brief,'164.9s observation only');
assert.equal(adaptiveHold(sol).brief,'96.4s observation only');
assert.match(adaptiveHold(astra).detail,/Token reservation limit reached at 135.1s/);
assert.match(adaptiveHold(astra).detail,/no new model requests or input actions/);
for(const reason of ['api_request_limit','action_limit','sdk_request_limit','request_window_closed']){
 const sample=row();sample.adaptive.horizon_wait.reason=reason;assert.ok(adaptiveHold(sample));
}
for(const change of [r=>r.adaptive.horizon_wait=null,r=>r.adaptive.horizon_wait.reason='unknown',
 r=>r.adaptive.verification='unverified',r=>r.research.protocol_id='legacy',r=>r.adaptive.horizon_policy=null,
 r=>r.adaptive.horizon_wait.started_ms=-1,r=>r.adaptive.horizon_wait.started_ms=300001,
 r=>r.adaptive.horizon_wait.ended_ms=100,r=>r.adaptive.horizon_wait.ended_ms=310000,
 r=>r.adaptive.horizon_wait.started_ms=NaN]){const sample=row();change(sample);assert.equal(adaptiveHold(sample),null);}
""")

    def test_details_separate_wall_hold_and_program_intervals(self):
        self.run_js([('adaptiveHold(', 'renderLive(')], r"""
const details=adaptiveDetails(row());
assert.match(details.children[0].textContent,/6 model responses · 300.0s wall · 164.9s observation only/);
assert.match(details.children[1].textContent,/135.1s–300.0s/);
assert.match(details.textContent,/Program interval/);
assert.match(details.textContent,/8.0s/);
assert.doesNotMatch(details.textContent,/135.1s (play|program|CPU)|300.0s play/);
const unknown=row();unknown.adaptive.verification='unverified';
assert.equal(adaptiveDetails(unknown).textContent,'Adaptive evidence not yet verified');
""")

    def test_public_featured_recording_and_operator_live_priority(self):
        self.run_js([('adaptiveHold(', 'renderCatalog(')], r"""
const completed=row(),running={...row('gpt-5.6-terra'),id:'b'.repeat(32),status:'running',phase:'run_controller',
 recording:null,adaptive:null,persisted_xp:null};
snapshot={source:'full_client_public_catalog',featured_run_id:completed.id,attempts:[running,completed]};
renderLive();
assert.equal($('live-model').textContent,'gpt-6-astra');
assert.equal($('live-xp').textContent,'+18,250');
assert.equal($('live-actions').textContent,'98 acknowledged');
assert.equal($('featured-recording').children.length,1);
assert.equal($('adaptive-evidence').children[0].tag,'p');
assert.match($('adaptive-evidence').children[0].textContent,/164.9s/);
assert.match($('live-description').textContent,/every planned model/);
snapshot.source='full_client_dashboard';renderLive();assert.equal($('live-model').textContent,'gpt-5.6-terra');
snapshot.source='full_client_public_catalog';completed.score_verification='unverified';
renderLive();assert.equal($('live-model').textContent,'gpt-5.6-terra');
""")

    def test_replay_keeps_first_input_cue_model_and_score(self):
        self.run_js([('adaptiveHold(', 'adaptiveDetails('),('openReplay(', 'playFrom(')], r"""
let replayFocus,replayRunId,replaySection,replayCue,replayStart;
const player={},replay={open:false,showModal(){this.open=true}},stopReplay=()=>{};
const replayVerification=r=>$('replay-verification').textContent=`${xp(r.persisted_xp)} persisted XP`;
const sample=row();openReplay(new URL('https://example.test/recordings/'+sample.id+'.webm'),sample,{closest:()=>null});
assert.equal(replayStart,2.75);assert.equal($('replay-agent').textContent,'First input');
assert.equal($('replay-title').textContent,'gpt-6-astra · 1234567890ab');
assert.equal($('replay-verification').textContent,'+18,250 persisted XP');
assert.match($('replay-timing').textContent,/Total model wait across all cycles: 64.0s/);
assert.match($('replay-timing').textContent,/Token reservation limit reached at 135.1s/);
assert.match($('replay-timing').textContent,/Observation only for 164.9s/);
assert.match($('replay-timing').textContent,/seeking changes playback only/);
assert.equal(replay.open,true);assert.equal($('replay-close').focused,true);
""")

    def test_comparison_timing_uses_wall_for_adaptive_and_preserves_legacy(self):
        self.run_js([('adaptiveHold(', 'adaptiveDetails('),('renderComparisons(', 'renderHistory(')], r"""
const adaptive=row(),legacy={...row(),id:'b'.repeat(32),research:null,adaptive:null,timing:{api_ms:13000,controller_ms:20000}};
snapshot={attempts:[adaptive,legacy],comparisons:[{id:'group',models:['gpt-6-astra'],attempt_ids:[adaptive.id,legacy.id]}]};
renderComparisons();const text=$('comparison-groups').textContent;
assert.match(text,/300.0s wall/);assert.match(text,/164.9s observation only/);
assert.match(text,/Token reservation limit reached/);assert.match(text,/20.0s play/);
assert.doesNotMatch(text,/300.0s play|135.1s play/);
""")

    def test_published_snapshot_is_not_reported_as_stale_live_stream(self):
        start=SOURCE.index('  function freshness(){');end=SOURCE.index('  async function refresh(){')
        code=DOM+SOURCE[start:end]+r"""
snapshot={source:'full_client_public_catalog',generated_at_ms:1000,live_status_available:false,attempts:[{status:'running'}]};
freshness();assert.equal($('connection').className,'');
assert.match($('connection').textContent,/Published results · refreshes every 10s · Snapshot /);
assert.ok($('connection').textContent.endsWith(new Date(1000).toLocaleString()));
assert.doesNotMatch($('connection').textContent,/stale|Live updates/);
snapshot.source='full_client_dashboard';freshness();
assert.match($('connection').textContent,/Live updates stale/);
"""
        result=subprocess.run([shutil.which('node'), '--max-old-space-size=64','-e',code],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__ == '__main__':
    unittest.main()
