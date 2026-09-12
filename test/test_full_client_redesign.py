"""Focused source/DOM checks for the public redesign; no browser or runtime."""
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'ui/full-client-dashboard/dashboard.js').read_text()
HTML = (ROOT / 'ui/full-client-dashboard/index.html').read_text()
PROTOCOL_HELPERS = SOURCE[SOURCE.index('  const format='):SOURCE.index('  const badge=')]


def function(name):
    """Extract a production function using the dashboard's outer indentation."""
    declaration = re.search(r'^  function ' + re.escape(name) + r'\(', SOURCE, re.M)
    if declaration is None:
        raise AssertionError('Missing dashboard helper: ' + name)
    first_end = SOURCE.index('\n', declaration.start())
    if SOURCE[declaration.start():first_end].rstrip().endswith('}'):
        return SOURCE[declaration.start():first_end] + '\n'
    closing = re.search(r'^  }\s*$', SOURCE[first_end:], re.M)
    if closing is None:
        raise AssertionError('Missing boundary after dashboard helper: ' + name)
    return SOURCE[declaration.start():first_end + closing.end()] + '\n'


DOM = r"""
class Node {
 constructor(tag,text){
  this.tag=tag;this.children=[];this._text=text==null?'':String(text);this.dataset={};
  this.attrs={};this.events={};this.value='';this.pauseCount=0;this.sourceChanges=0;
  this.style={setProperty(name,value){this[name]=value}};
  const classes=new Set();this.classList={add:value=>classes.add(value),
   remove:value=>classes.delete(value),contains:value=>classes.has(value),
   toggle(value,on){on??=!classes.has(value);if(on)classes.add(value);else classes.delete(value);}};
 }
 get textContent(){return this._text+this.children.map(child=>child.textContent).join(' ')}
 set textContent(value){this._text=String(value);this.children=[]}
 get src(){return this._src} set src(value){this._src=value;this.sourceChanges++}
 append(...values){this.children.push(...values)}
 replaceChildren(...values){this._text='';this.children=values}
 setAttribute(name,value){this.attrs[name]=String(value)}
 getAttribute(name){return this.attrs[name]??null}
 addEventListener(event,callback){(this.events[event]??=[]).push(callback)}
 emit(event,value={}){for(const callback of this.events[event]||[])callback(value)}
 pause(){this.pauseCount++} play(){return Promise.resolve()} focus(){this.focused=true}
}
const nodes={},$=id=>nodes[id]??=new Node('div'),el=(tag,text)=>new Node(tag,text);
const document={hidden:false,events:{},querySelector:selector=>$(selector),querySelectorAll:()=>[],
 addEventListener(event,callback){(this.events[event]??=[]).push(callback)},
 emit(event,value={}){for(const callback of this.events[event]||[])callback(value)}};
const matchMedia=()=>({matches:true,events:{},
 addEventListener(event,callback){(this.events[event]??=[]).push(callback)},
 emit(event,value){for(const callback of this.events[event]||[])callback(value)}});
const location={href:'https://example.test/cohorts/current/',origin:'https://example.test'};
const labels={completed:'Completed',failed:'Failed',running:'In progress'};
let snapshot;
const sample=(id,exact='gpt-6-astra',score=0)=>({
 id,requested_model:exact,returned_model:exact,attribution:'exact',
 status:'completed',persisted_xp:score,acknowledged_actions:5,action_attempts:5,
 recording:{url:'./recordings/'+id+'.webm'},
 research:{protocol_id:'full-client-adaptive-pilot-v1'},
 adaptive:{class_profile:{class_name:'Hero'},wall_elapsed_ms:300000},
 timing:{controller_ms:300000,api_ms:64000},alive_at_logout:true
});
"""
PRESENTATION_HELPERS = SOURCE[SOURCE.index('\n  const node='):SOURCE.index('  function safeRecording(')]


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self.feed(HTML)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


@unittest.skipUnless(shutil.which('node'), 'Node is required for dashboard UI checks')
class RedesignEvidenceTests(unittest.TestCase):
    def run_js(self, helpers, checks, prelude=''):
        code = "const assert=require('node:assert/strict');\n" + PROTOCOL_HELPERS + prelude
        code += ''.join(function(name) for name in helpers) + checks
        result = subprocess.run([shutil.which('node'), '--max-old-space-size=64', '-e', code],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cues_use_verified_basis_and_protocol_bounds_without_api_fallback(self):
        self.run_js(['cue'], r"""
const row={timing:{api_ms:64000},recording:{}};
assert.equal(cue(row),null);assert.equal(cue(null),null);
for(const basis of ['program_start','first_acknowledged_input']){
 row.recording.playback={basis,start_ms:0};assert.equal(cue(row).start_ms,0);
 row.recording.playback.start_ms=2750;assert.equal(cue(row).start_ms,2750);
}
for(const start_ms of [-1,NaN,Infinity,'2750',true,125000]){
 row.recording.playback={basis:'program_start',start_ms};assert.equal(cue(row),null);
}
row.recording.playback={basis:'api_wait',start_ms:64000};assert.equal(cue(row),null);
row.recording.playback={basis:'first_acknowledged_input',start_ms:330000};
row.research={protocol_id:'full-client-adaptive-pilot-v1'};assert.ok(cue(row));
row.recording.playback.start_ms=335000;assert.equal(cue(row),null);
row.adaptive={wall_budget_ms:1800000,horizon_policy:{id:'final-program-slot-1800-v1'}};
row.recording.playback.start_ms=1800000;assert.ok(cue(row));
row.adaptive.horizon_policy.id='full-horizon-reserve-v1';assert.equal(cue(row),null);
""")

    def test_montage_retains_one_exact_model_slot_from_the_selected_group(self):
        self.run_js(['safeRecording','montageRows'], r"""
const models=['gpt-6-astra','gpt-5.6-sol','gpt-5.6-terra','gpt-5.6-luna'];
const astra=sample('a',models[0],-500),sol={...sample('s',models[1],0),no_op:true};
const terra={...sample('t',models[2],null),status:'failed'},luna=sample('l',models[3],50);
const unrelated=sample('outside',models[0],1000000);
const group={models:[models[3],models[0],models[1],models[0],models[2]],attempt_ids:['a','s','t','l']};
let picks=montageRows(group,[unrelated,sol,terra,luna,astra]);
assert.deepEqual(picks.map(p=>p.model),models);assert.equal(picks.length,4);
assert.equal(picks[0].row,astra);assert.equal(picks[1].row,sol);assert.equal(picks[2].row,terra);
assert.equal(picks[0].row.persisted_xp,-500);assert.equal(picks[1].row.persisted_xp,0);
for(const change of [r=>r.recording=null,r=>r.recording.url='https://outside.test/recordings/l.webm',
 r=>r.returned_model=models[0],r=>r.returned_model=null,r=>r.attribution='mismatch']){
 const unavailable=structuredClone(luna);change(unavailable);
 picks=montageRows(group,[unrelated,sol,terra,unavailable,astra]);
 assert.equal(picks.length,4);assert.deepEqual(picks[3],{model:models[3],row:null});
}
assert.deepEqual(montageRows(null,[]),[]);
""", DOM)

    def test_group_label_counts_distinct_models_and_uses_frozen_horizon(self):
        self.run_js(['groupLabel'], r"""
const row=sample('a');snapshot={attempts:[row]};
const group={id:'12345678abcdef',models:['gpt-6-astra','gpt-5.6-sol','gpt-6-astra'],attempt_ids:['a']};
assert.match(groupLabel(group),/Hero · 2 models · 5 min/);
row.adaptive.wall_budget_ms=1800000;row.adaptive.horizon_policy={id:'final-program-slot-1800-v1'};
assert.match(groupLabel(group),/30 min/);
row.adaptive.horizon_policy.id='unverified';assert.match(groupLabel(group),/5 min/);
""", DOM)

    def test_outcome_keeps_zero_negative_unknown_and_no_input_independent(self):
        self.run_js(['runOutcome'], r"""
assert.match(runOutcome({persisted_xp:0}),/zero net saved XP/);
assert.match(runOutcome({persisted_xp:-4500}),/-4,500 net XP.*including losses/);
assert.match(runOutcome({persisted_xp:9000}),/\+9,000 XP remained saved/);
for(const value of [null,undefined,NaN,'9000']){
 const text=runOutcome({persisted_xp:value,no_op:true});
 assert.match(text,/No verified saved XP score/);
 assert.doesNotMatch(text,/zero net|No XP gained|no net gain|remained saved/);
}
const passive=runOutcome({persisted_xp:9000,no_op:true});
assert.match(passive,/\+9,000 XP remained saved/);assert.match(passive,/No input actions/);
const failed=runOutcome({persisted_xp:-500,status:'failed'});assert.match(failed,/-500 net XP/);
""")

    def test_preview_seeks_to_cue_and_retains_full_opening_without_one(self):
        self.run_js(['safeRecording','cue','montageRows','groupLabel','dot','setPreviews','renderMontage'], r"""
const waiting=sample('a'),active=sample('s','gpt-5.6-sol',-500);
active.recording.playback={basis:'first_acknowledged_input',start_ms:2750};
snapshot={attempts:[waiting,active],comparisons:[{id:'group',models:[waiting.requested_model,active.requested_model],attempt_ids:['a','s']}]};
$('showcase-select').value='group';renderMontage();
const tiles=$('montage').children,first=tiles[0].children[0],second=tiles[1].children[0];
first.duration=second.duration=300;first.currentTime=second.currentTime=0;
first.emit('loadedmetadata');second.emit('loadedmetadata');
assert.equal(first.currentTime,0);assert.equal(second.currentTime,2.75);
assert.equal(first.getAttribute('aria-hidden'),'true');assert.equal(first.tabIndex,-1);
assert.match(tiles[1].getAttribute('aria-label'),/-500 saved XP/);
assert.equal(previewsPlaying,false);assert.equal($('montage-toggle').getAttribute('aria-pressed'),'false');
""", DOM + PRESENTATION_HELPERS)

    def test_comparison_places_negative_xp_left_of_zero_and_keeps_unknown_hidden(self):
        self.run_js(['groupLabel','dot','renderComparison'], r"""
const rows=[sample('negative','gpt-6-astra',-500),sample('zero','gpt-5.6-sol',0),
 sample('unknown','gpt-5.6-terra',null),sample('positive','gpt-5.6-luna',1000)];
snapshot={attempts:rows,comparisons:[{id:'group',models:rows.map(r=>r.requested_model),attempt_ids:rows.map(r=>r.id),ready:true}]};
$('comparison-select').value='group';renderComparison();
const charts=$('xp-chart').children,negative=charts[0].children[1],zero=charts[1].children[1];
assert.equal(negative.style['--zero'],'50%');assert.equal(negative.children[0].style.left,'25%');
assert.equal(negative.children[0].style.width,'25%');assert.ok(negative.children[0].classList.contains('negative'));
assert.equal(zero.children[0].style.left,'50%');assert.ok(zero.children[0].classList.contains('zero'));
assert.equal(charts[2].children[1].children[0].hidden,true);assert.equal(charts[2].children[2].textContent,'—');
assert.equal(charts[3].children[1].children[0].style.left,'50%');
assert.match($('comparison-rows').textContent,/300.0s wall/);
assert.match($('comparison-rows').textContent,/64.0s total model wait/);
assert.doesNotMatch($('comparison-rows').textContent,/300.0s play/);
""", DOM + PRESENTATION_HELPERS + r"""
const cell=(tr,text)=>{const n=node('td',text);tr.append(n);return n};
const scoreCell=(tr,r)=>cell(tr,xp(r.persisted_xp)),inputDetails=()=>{},publicationCell=()=>{};
const watch=()=>node('button','Watch'),adaptiveHold=()=>null;
""")

    def test_refresh_updates_evidence_without_restarting_the_same_video(self):
        self.run_js(['safeRecording','cue','groupLabel','runOutcome','publication','selectRun','renderRedesign'], r"""
let row=sample('a');snapshot={attempts:[row],comparisons:[],generated_at_ms:1000};
renderRedesign();const changes=runPlayer.sourceChanges,pauses=runPlayer.pauseCount;
runPlayer.currentTime=25;
row={...row,persisted_xp:100};snapshot={...snapshot,attempts:[row],generated_at_ms:2000};
renderRedesign();
assert.equal(runPlayer.sourceChanges,changes,'A new snapshot must not reload the selected recording');
assert.equal(runPlayer.pauseCount,pauses,'A new snapshot must not pause the selected recording');
assert.equal(runPlayer.currentTime,25);assert.match($('run-outcome').textContent,/\+100 XP/);
selectRun(sample('another'));assert.ok(runPlayer.sourceChanges>changes);
""", DOM + PRESENTATION_HELPERS + r"""
const renderModels=()=>{},renderRunOptions=()=>{},renderMontage=()=>{},renderComparison=()=>{};
const adaptiveHold=()=>null,adaptiveDetails=()=>null,nativeDetails=()=>null;
""")

    def test_keyboard_navigation_updates_focus_selection_and_panels(self):
        bindings = SOURCE[SOURCE.index('  for (const tab of architectureTabs) {',
                                      SOURCE.index('  function showArchitecture(') +
                                      len(function('showArchitecture'))):
                          SOURCE.index('  const worldSteps =')]
        self.run_js(['showArchitecture'], bindings + r"""
const [agent,fleet]=architectureTabs;
showArchitecture('fleet');assert.equal(fleet.getAttribute('aria-selected'),'true');
let prevented=0;
const press=(tab,key)=>tab.emit('keydown',{key,preventDefault(){prevented++}});
press(fleet,'Home');assert.equal(agent.getAttribute('aria-selected'),'true');
assert.equal(agent.tabIndex,0);assert.equal(fleet.tabIndex,-1);assert.ok(agent.focused);
assert.equal($('agent-panel').hidden,false);assert.equal($('fleet-panel').hidden,true);
press(agent,'ArrowLeft');assert.equal(fleet.getAttribute('aria-selected'),'true');
press(fleet,'ArrowRight');assert.equal(agent.getAttribute('aria-selected'),'true');
press(agent,'End');assert.equal(fleet.getAttribute('aria-selected'),'true');
press(fleet,'Escape');assert.equal(prevented,4);
""", DOM + r"""
const architectureTabs=['agent','fleet'].map(key=>{
 const tab=new Node('button');tab.dataset.architecture=key;
 tab.setAttribute('aria-controls',key+'-panel');return tab;
});
""")

    def test_reduced_motion_and_hidden_page_pause_previews(self):
        bindings = SOURCE[SOURCE.index("  $('montage-toggle').addEventListener"):
                          SOURCE.index('  const architectureTabs =')]
        self.run_js(['setPreviews'], bindings + r"""
setPreviews(true);assert.equal(previewsPlaying,true);
const beforeMotion=preview.pauseCount;
reducedMotion.emit('change',{matches:true});
assert.equal(previewsPlaying,false);assert.ok(preview.pauseCount>beforeMotion);
assert.equal($('montage-toggle').getAttribute('aria-pressed'),'false');
setPreviews(true);const beforeHidden=runPlayer.pauseCount;
document.hidden=true;document.emit('visibilitychange');
assert.equal(previewsPlaying,false);assert.ok(runPlayer.pauseCount>beforeHidden);
""", DOM + PRESENTATION_HELPERS + r"""
const preview=new Node('video');document.querySelectorAll=selector=>selector==='.montage video'?[preview]:[];
const renderHistory=()=>{},renderComparison=()=>{},renderMontage=()=>{};
""")

    def test_native_score_requires_every_qualification_field(self):
        self.run_js(['publication'], r"""
const verified = () => ({persisted_xp:0,
 score_verification:'native_window_runner_receipts_rechecked',
 publication_evidence:{status:'native_windows_checked'},
 native_xp:{status:'verified_native_windows',publication_eligible:true,
  publication_blocker:null,peak_normalized_xp_per_minute:123}});
const sample=verified();assert.equal(nativeScore(sample),sample.native_xp);
assert.equal(publication(sample).label,'Native XP windows checked');
for(const change of [
 r=>r.score_verification='adaptive_runner_verified_receipts_rechecked',
 r=>r.native_xp.status='pending',r=>r.native_xp.publication_eligible=false,
 r=>r.native_xp.publication_eligible='true',r=>delete r.native_xp.publication_eligible,
 r=>r.native_xp.publication_blocker='recording_unreviewed',
 r=>delete r.native_xp.publication_blocker,r=>r.native_xp=null]){
 const candidate=verified();change(candidate);assert.equal(nativeScore(candidate),null);
 assert.notEqual(publication(candidate).label,'Native XP windows checked');
}
// Publication eligibility and signed saved progress are separate facts.
const blocked=verified();blocked.persisted_xp=-250;blocked.native_xp.publication_eligible=false;
assert.equal(nativeScore(blocked),null);assert.equal(xp(blocked.persisted_xp),'-250');
assert.equal(xp(0),'0');assert.equal(xp(null),'—');assert.equal(xp(undefined),'—');
""")


class RedesignAccessibilityTests(unittest.TestCase):
    def setUp(self):
        self.elements = Elements().elements
        self.ids = {attrs['id']:(tag, attrs) for tag, attrs in self.elements if attrs.get('id')}

    def test_recording_controls_and_status_are_accessible(self):
        all_ids = [attrs['id'] for _, attrs in self.elements if attrs.get('id')]
        self.assertEqual(len(all_ids), len(set(all_ids)), 'Duplicate IDs break labels and controls')
        for video in ('run-video', 'replay-video'):
            tag, attrs = self.ids[video]
            self.assertEqual(tag, 'video')
            self.assertIn('controls', attrs)
            self.assertTrue(attrs.get('aria-label'))
        for status in ('player-status', 'replay-playback-status', 'connection'):
            self.assertEqual(self.ids[status][1].get('role'), 'status')
        for control in ('showcase-select', 'comparison-select', 'run-select', 'history-filter'):
            self.assertTrue(any(tag == 'label' and attrs.get('for') == control
                                for tag, attrs in self.elements), control)

    def test_architecture_tabs_expose_selection_and_panel_relationships(self):
        tabs = [(tag, attrs) for tag, attrs in self.elements if attrs.get('role') == 'tab']
        self.assertGreaterEqual(len(tabs), 2)
        self.assertEqual(sum(attrs.get('aria-selected') == 'true' for _, attrs in tabs), 1)
        for tag, attrs in tabs:
            self.assertEqual(tag, 'button')
            selected = attrs.get('aria-selected') == 'true'
            self.assertEqual(attrs.get('tabindex'), '0' if selected else '-1')
            panel = self.ids[attrs['aria-controls']][1]
            self.assertEqual(panel.get('role'), 'tabpanel')
            self.assertEqual(panel.get('aria-labelledby'), attrs['id'])
            self.assertEqual('hidden' in panel, not selected)


if __name__ == '__main__':
    unittest.main()
