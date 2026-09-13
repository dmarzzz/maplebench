"""Exercise the actual manual toolbar and trusted-key listener without a browser."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_skill_toolkit import toolkit, profile


@unittest.skipUnless(shutil.which('node'),'Node is required for toolbar input regressions')
class ToolbarTests(unittest.TestCase):
    def run_toolbar(self,checks):
        source=(Path(__file__).resolve().parents[1]/'ui/full-client/controller.js').read_text()
        mappings=source[source.index('  const keyNames = '):source.index('  const held = ')]
        toolbar=source[source.index('  const hold = '):source.index("  window.addEventListener('blur'")]
        refresh=source[source.index('    updateManualSkills();',source.index('  function renderHeader()')):
                       source.index('    runButtons.forEach',source.index('  function renderHeader()'))]
        fixture=r'''
const assert=require('node:assert/strict');
const run={},manualGroup={children:[]},manualButtons=[],held=new Map(),physical=new Set();
const listeners={},events=[],keyEvents=[];let isBusy=false,manualChanges=0,renders=0;
const busy=()=>isBusy,manualMode=()=>{manualChanges++;},renderHeader=()=>{renders++;};
const game={focus(){events.push('focus');}},release=code=>{held.delete(code);keyEvents.push([code,'keyup']);};
const key=(code,type)=>keyEvents.push([code,type]),releaseAll=()=>{},setTimeout=()=>1;
const window={addEventListener(type,handler){listeners[type]=handler;}};
const element=(tag,cls,parent,text)=>{
 const node={tagName:tag.toUpperCase(),className:cls,textContent:text,hidden:false,disabled:false,
   handlers:{},addEventListener(type,handler){this.handlers[type]=handler;}};
 parent.children.push(node);return node;
};
const emit=(type,code,options={})=>{
 const e={isTrusted:true,code,target:game,prevented:0,stopped:0,
   preventDefault(){this.prevented++;},stopImmediatePropagation(){this.stopped++;},...options};
 listeners[type](e);return e;
};
'''
        script=fixture+mappings+toolbar+'\nconst refresh=()=>{'+refresh+'};\n'+checks
        result=subprocess.run([shutil.which('node'),'--max-old-space-size=64','-e',script],
                              capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_all_class_profiles_expose_only_their_declared_controls_and_preserve_legacy_four(self):
        profiles=[profile(toolkit(cls)) for cls in ('hero','bowmaster','ice_lightning_arch_mage','night_lord')]
        self.run_toolbar('const profiles='+json.dumps(profiles)+r''';
assert.deepEqual(skillButtons.filter(e=>!e.node.hidden).map(e=>e.node.textContent),
 ['Brandish (A)','Combo (S)','Booster (D)','Maple Warrior (F)']);
const originalNodes=skillButtons.map(e=>e.node),nodeCount=manualGroup.children.length;
for(const field of ['previewProtocol','nativeAcceptance','adaptiveProtocol']){
 for(const profile of profiles){
  run[field]={profile};refresh();
  const shown=skillButtons.filter(e=>!e.node.hidden);
  assert.equal(shown.length,Object.keys(profile.skill_keys).length);
  for(const entry of shown){const slot=skillNamesByCode[entry.code];
   assert.equal(entry.node.textContent,`${profile.skill_keys[slot]} (${entry.code.slice(3)})`);}
  assert.deepEqual(skillButtons.map(e=>e.node),originalNodes);
  assert.equal(manualGroup.children.length,nodeCount);
 }
 delete run[field];
}
const oldProfile={skill_keys:Object.fromEntries(Object.entries(profiles[2].skill_keys).slice(0,4))};
run.nativeAcceptance={profile:oldProfile};refresh();
assert.equal(skillButtons.filter(e=>!e.node.hidden).length,4);
delete run.nativeAcceptance;refresh();
assert.equal(skillButtons.filter(e=>!e.node.hidden).length,4);
assert.equal(skillButtons[1].node.textContent,'Combo (S)');
''')

    def test_mage_labels_and_button_dispatch_share_physical_keys_and_busy_guard(self):
        mage=profile(toolkit('ice_lightning_arch_mage'))
        self.run_toolbar('run.previewProtocol={profile:'+json.dumps(mage)+r'''};refresh();
assert.equal(skillButtons[1].node.textContent,'Teleport (S)');
assert.equal(skillButtons[9].node.textContent,'Magic Armor (V)');
skillButtons[1].node.handlers.click();skillButtons[9].node.handlers.click();
assert.ok(keyEvents.some(([code,type])=>code==='KeyS'&&type==='keydown'));
assert.ok(keyEvents.some(([code,type])=>code==='KeyV'&&type==='keydown'));
isBusy=true;refresh();assert.ok(manualButtons.every(node=>node.disabled));
const count=keyEvents.length;skillButtons[4].node.handlers.click();assert.equal(keyEvents.length,count);
isBusy=false;refresh();assert.ok(manualButtons.every(node=>!node.disabled));
''')

    def test_every_toolkit_physical_key_is_tracked_when_idle_and_blocked_while_busy(self):
        self.run_toolbar(r'''
for(const code of Object.keys(codes)){
 isBusy=false;
 const down=emit('keydown',code);assert.equal(down.prevented,0);assert.ok(physical.has(code));
 emit('keyup',code);assert.ok(!physical.has(code));
 isBusy=true;const changes=manualChanges;
 for(const type of ['keydown','keyup']){
  const e=emit(type,code);assert.equal(e.prevented,1);assert.equal(e.stopped,1);
  assert.equal(manualChanges,changes);assert.ok(!physical.has(code));
 }
 const sdk=emit('keydown',code,{isTrusted:false});assert.equal(sdk.prevented,0);assert.equal(sdk.stopped,0);
}
const unknown=emit('keydown','F5');assert.equal(unknown.prevented,0);assert.equal(unknown.stopped,0);
for(const tagName of ['BUTTON','SUMMARY','INPUT','SELECT','TEXTAREA']){
 const e=emit('keydown','Space',{target:{tagName}});
 assert.equal(e.prevented,0);assert.equal(e.stopped,1);
}
''')


if __name__=='__main__':unittest.main()
