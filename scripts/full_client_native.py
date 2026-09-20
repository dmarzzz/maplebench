"""Frozen, zero-model native recipes for private capture/fixture acceptance."""
import hashlib
import json
import re

from full_client_capture import CAPTURE_DURATION_POLICY, ENCODED_FRAME_POLICY, validate_duration_policy
from full_client_hero_toolkit import (profile as hero_profile,
                                      toolkit as hero_toolkit,
                                      native_qualification_skills,
                                      validate_toolkit as validate_hero_toolkit)

PROTOCOL = 'scripted-native-acceptance-v1'
NATIVE_V2_PROTOCOL = 'scripted-native-acceptance-v2'
HERO_TOOLKIT_PROTOCOL = 'scripted-native-hero-toolkit-v1'
PROFILES = {
    'hero': {'id':'hero-180','class_name':'Hero','level':180,
             'skill_keys':{'PRIMARY_SKILL':'Brandish','SECONDARY_SKILL':'Combo Attack','BUFF_1':'Booster','BUFF_2':'Maple Warrior'}},
    'bowmaster': {'id':'bowmaster-v1','class_name':'Bowmaster','level':180,
                  'skill_keys':{'PRIMARY_SKILL':'Hurricane','SECONDARY_SKILL':'Arrow Rain','BUFF_1':'Soul Arrow : Bow','BUFF_2':'Sharp Eyes'}},
    'ice_lightning_arch_mage': {'id':'ice-lightning-v1','class_name':'Ice/Lightning Arch Mage','level':180,
                              'skill_keys':{'PRIMARY_SKILL':'Chain Lightning','SECONDARY_SKILL':'Teleport','BUFF_1':'Magic Guard','BUFF_2':'Spell Booster'}},
}

def contract(class_id, baseline_sha256, *, protocol=NATIVE_V2_PROTOCOL):
    if protocol not in (PROTOCOL,NATIVE_V2_PROTOCOL,HERO_TOOLKIT_PROTOCOL) or class_id not in PROFILES or not isinstance(baseline_sha256,str) or not re.fullmatch('[a-f0-9]{64}',baseline_sha256):
        raise ValueError('invalid_native_fixture')
    if protocol==HERO_TOOLKIT_PROTOCOL:
        if class_id!='hero':raise ValueError('invalid_native_fixture')
        policy=hero_toolkit()
        return {'id':protocol,'class_id':'hero','profile':hero_profile(policy),
                'skill_toolkit':policy,'baseline_sha256':baseline_sha256,
                'qualification_skill_ids':[skill['skill_id'] for skill in
                                           native_qualification_skills(policy)],
                'wall_seconds':120,'max_actions':128,'max_sdk_requests':600,
                'capture_max_ms':125000,'capture_duration_policy':dict(ENCODED_FRAME_POLICY)}
    return {'id':protocol,'class_id':class_id,'profile':json.loads(json.dumps(PROFILES[class_id])),
            'baseline_sha256':baseline_sha256,'wall_seconds':30,'max_actions':12,'max_sdk_requests':100,
            'capture_max_ms':45000,'capture_duration_policy':dict(CAPTURE_DURATION_POLICY if protocol==PROTOCOL else ENCODED_FRAME_POLICY)}

def validate_contract(value):
    if not isinstance(value,dict):raise ValueError('invalid_native_acceptance')
    expected=contract(value.get('class_id'),value.get('baseline_sha256'),protocol=value.get('id'))
    if json.dumps(value,sort_keys=True,allow_nan=False)!=json.dumps(expected,sort_keys=True):
        raise ValueError('invalid_native_acceptance')
    if value['id']==HERO_TOOLKIT_PROTOCOL:
        validate_hero_toolkit(value['skill_toolkit'],value['profile'])
    validate_duration_policy(value['capture_duration_policy'])
    return expected

def _legacy_program(value):
    value=validate_contract(value);class_id=value['class_id']
    # These are finite physical key inputs. No arbitrary user program or game API
    # is accepted. Bow attacks require the ordinary Soul Arrow buff first.
    keys=([('SECONDARY_SKILL',100),('BUFF_1',150),('BUFF_2',150)] if class_id=='hero'
          else [('BUFF_1',150),('BUFF_2',150)])
    keys += [('JUMP',150),('ATTACK',600),('PRIMARY_SKILL',1200)]
    if class_id!='hero':keys.append(('SECONDARY_SKILL',150 if class_id=='ice_lightning_arch_mage' else 600))
    code="""// Scripted native acceptance; no model and no ranked result.
const first=await sdk.observe();
const nearby=first.monsters.filter(m=>Math.abs(m.y-first.character.y)<65)
  .sort((a,b)=>Math.abs(a.x-first.character.x)-Math.abs(b.x-first.character.x));
if(nearby.length){const dx=nearby[0].x-first.character.x;
  await sdk.pressKeys([dx<0?'LEFT':'RIGHT'],Math.abs(dx)>140?500:30);}
"""
    for key,duration in keys:
        code+=f"await sdk.observe();\nawait sdk.pressKeys(['{key}'],{duration});\nawait sdk.wait(500);\nawait sdk.observe();\n"
    # Keep a short passive tail for end-frame and native-effect inspection.
    code+='await sdk.wait(1500);\nawait sdk.observe();\n'
    return code

def program(value):
    value=validate_contract(value);class_id=value['class_id']
    if value['id']==HERO_TOOLKIT_PROTOCOL:return _hero_toolkit_program(value)
    if value['id']==PROTOCOL:return _legacy_program(value)
    # These are finite physical key inputs. No arbitrary user program or game API
    # is accepted. Bow attacks require the ordinary Soul Arrow buff first.
    code="""// Scripted native acceptance; no model and no ranked result.
// Check the jump before any skill animation can hold the character in place.
await sdk.wait(1000);
await sdk.observe();
await sdk.pressKeys(['JUMP'],300);
await sdk.observe();
await sdk.wait(1100);
await sdk.observe();
"""
    buffs=([('SECONDARY_SKILL',300),('BUFF_1',300),('BUFF_2',300)] if class_id=='hero'
           else [('BUFF_1',300),('BUFF_2',300)])
    for key,duration in buffs:
        code+=f"await sdk.pressKeys(['{key}'],{duration});\nawait sdk.observe();\nawait sdk.wait(1100);\nawait sdk.observe();\n"
    code+="""// Height proximity is observable; no foothold or position edits are used.
// Re-observe after each bounded step, including a short facing step in range.
for(let step=0;step<4;step++){
  const scene=await sdk.observe();
  const nearby=scene.monsters.filter(m=>Math.abs(m.y-scene.character.y)<=45)
    .sort((a,b)=>Math.abs(a.x-scene.character.x)-Math.abs(b.x-scene.character.x));
  if(!nearby.length)break;
  const dx=nearby[0].x-scene.character.x, inRange=Math.abs(dx)<=110;
  const hold=inRange?30:Math.min(1500,Math.max(300,Math.round(Math.abs(dx)*5)));
  await sdk.pressKeys([dx<0?'LEFT':'RIGHT'],hold);
  await sdk.observe();
  if(inRange)break;
  await sdk.wait(150);
}
"""
    keys=[('ATTACK',600),('PRIMARY_SKILL',1200)]
    if class_id!='hero':keys.append(('SECONDARY_SKILL',300 if class_id=='ice_lightning_arch_mage' else 600))
    for key,duration in keys:
        code+=f"await sdk.observe();\nawait sdk.pressKeys(['{key}'],{duration});\nawait sdk.wait(1100);\nawait sdk.observe();\n"
    # Keep a short passive tail for end-frame and native-effect inspection.
    code+='await sdk.wait(1500);\nawait sdk.observe();\n'
    return code


def _hero_toolkit_program(value):
    """Finite input opportunities; native events decide every skill result."""
    validate_contract(value)
    selected=set(value['qualification_skill_ids'])
    buffs=[skill['slot'] for skill in value['skill_toolkit']['skills']
           if skill['skill_id'] in selected
           if skill['route']=='buff']
    return """// Hero toolkit qualification candidate; no model, ranking, or game-state edits.
// Relay acknowledgements establish delivery only. Native casts/effects decide qualification.
const end=Date.now()+112000;
let actions=0;
const room=()=>Date.now()<end&&actions<120;
async function input(keys,ms){
  if(!room())return false;
  const ack=await sdk.pressKeys(keys,ms);actions++;
  if(ack.accepted!==true)throw new Error('hero_toolkit_input_not_accepted');
  return true;
}
async function probe(keys,ms=100,settle=1600){
  if(!room())return false;
  const before=await sdk.observe();
  if(before.character.alive===false)return false;
  if(!await input(keys,ms))return false;
  await sdk.observe();
  await sdk.wait(settle);
  await sdk.observe();
  return true;
}
async function settleOnCombatFloor(){
  const origin=await sdk.observe();
  if(origin.character.alive===false)return null;
  // The accepted Hero fixture starts on a small ledge. Two bounded ordinary
  // right inputs descend to the broad lower platform seen in fixture capture.
  for(let step=0;step<2;step++){
    if(!await input(['RIGHT'],250))return null;
    await sdk.wait(200);
  }
  for(let sample=0;sample<12&&room();sample++){
    const first=await sdk.observe();
    if(first.character.alive===false)return null;
    await sdk.wait(350);
    const second=await sdk.observe();
    if(second.character.alive===false)return null;
    const refreshed=second.ageMs<350&&second.renderAgeMs<350;
    const landed=refreshed&&second.character.y>=origin.character.y+180&&
      Math.abs(second.character.x-first.character.x)<=4&&
      Math.abs(second.character.y-first.character.y)<=4;
    const targetAvailable=second.monsters.some(m=>
      Math.abs(m.y-second.character.y)<=50);
    if(landed&&targetAvailable)return second.character.y;
    await sdk.wait(250);
  }
  return null;
}
let repositionActions=0;
async function targetDirection(combatFloorY){
  // Only reposition on the confirmed broad lower platform. The global cap
  // prevents an observed moving target from turning this into an open chase.
  let unavailablePolls=0;
  let recoveryPolls=0;
  let recoverySample=null;
  let recovering=false;
  for(let step=0;step<36&&room();step++){
    const scene=await sdk.observe();
    if(scene.character.alive===false)return null;
    if(scene.ageMs>=350||scene.renderAgeMs>=350){
      if(recovering){
        if(++recoveryPolls>=12)return null;
      }else if(++unavailablePolls>=4)return null;
      await sdk.wait(150);continue;
    }
    if(Math.abs(scene.character.y-combatFloorY)>50){
      // Contact can briefly lift the Hero from the sloped lower platform.
      // Do not send another input until fresh observations prove a landing.
      recovering=true;recoverySample=null;unavailablePolls=0;
      if(++recoveryPolls>=12)return null;
      await sdk.wait(350);continue;
    }
    if(recovering){
      // A second fresh sample after a full 350 ms refresh interval keeps one
      // cached grounded frame from being treated as a stable landing.
      const stable=recoverySample!==null&&
        Math.abs(scene.character.x-recoverySample.x)<=4&&
        Math.abs(scene.character.y-recoverySample.y)<=4;
      if(!stable){
        recoverySample={x:scene.character.x,y:scene.character.y};
        if(++recoveryPolls>=12)return null;
        await sdk.wait(350);continue;
      }
      recovering=false;recoverySample=null;recoveryPolls=0;
    }
    const near=scene.monsters.filter(m=>Math.abs(m.y-scene.character.y)<=50)
      .sort((a,b)=>Math.abs(a.x-scene.character.x)-Math.abs(b.x-scene.character.x));
    if(!near.length){
      if(++unavailablePolls>=4)return null;
      await sdk.wait(250);continue;
    }
    unavailablePolls=0;
    const target=near[0];
    const dx=target.x-scene.character.x;
    const distance=Math.abs(dx);
    // Every authored two-handed-sword bucket-10 stance covers target centers
    // from 47 through 92 px on the facing side. Approach or back off into a
    // narrower band, allowing for an observed target moving 80 px/s against
    // the Hero's roughly 350 px/s ground speed. Then combine direction and
    // skill in one physical input.
    if(distance>82){
      if(repositionActions>=48)return null;
      const duration=Math.max(30,Math.min(250,
        Math.round((distance-70)/.27)));
      if(!await input([dx<0?'LEFT':'RIGHT'],duration))return null;
      repositionActions++;
      await sdk.wait(80);
      continue;
    }
    if(distance<58){
      if(repositionActions>=48)return null;
      const duration=Math.max(30,Math.min(250,
        Math.round((70-distance)/.27)));
      if(!await input([dx<0?'RIGHT':'LEFT'],duration))return null;
      repositionActions++;
      await sdk.wait(80);
      continue;
    }
    return dx<0?'LEFT':'RIGHT';
  }
  return null;
}
// 1200 ms exceeds the pinned client's source-derived core melee animation
// maximum (848 ms including an unboosted scheduling phase). Native events,
// rather than this wait, still decide whether an effect occurred.
async function cast(key,combatFloorY,hold=100,settle=1200){
  if(!room())return false;
  const direction=await targetDirection(combatFloorY);
  if(direction===null||!await input([direction,key],hold))return false;
  await sdk.observe();
  await sdk.wait(settle);
  await sdk.observe();
  return true;
}
await sdk.wait(1000);
for(const key of __BUFFS__)await probe([key]);
const combatFloorY=await settleOnCombatFloor();
// Combo is active before damage opportunities. Actual server hits must build orbs.
if(combatFloorY!==null){
  for(let sequence=0;sequence<2;sequence++){
    for(let hit=0;hit<2;hit++)await cast('PRIMARY_SKILL',combatFloorY);
    await cast('SKILL_6',combatFloorY);
    // Rebuild after Coma because a successful finisher consumes observed orbs.
    for(let hit=0;hit<2;hit++)await cast('PRIMARY_SKILL',combatFloorY);
    await cast('SKILL_7',combatFloorY);
  }
  // Rush does not consume Combo, and running it last preserves finisher setup.
  for(let attempt=0;attempt<2;attempt++)await cast('SKILL_5',combatFloorY);
}
await sdk.wait(2000);
await sdk.observe();
""".replace('__BUFFS__',json.dumps(buffs,separators=(',',':')))

def fingerprint(value):
    return hashlib.sha256((json.dumps(validate_contract(value),sort_keys=True,separators=(',',':'))+'\n').encode()).hexdigest()
