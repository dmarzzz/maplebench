"""Frozen, zero-model native recipes for private capture/fixture acceptance."""
import hashlib
import json
import re

from full_client_capture import CAPTURE_DURATION_POLICY, ENCODED_FRAME_POLICY, validate_duration_policy
from full_client_skill_toolkit import NATIVE_PROTOCOL as TOOLKIT_NATIVE_PROTOCOL, toolkit, profile as toolkit_profile

PROTOCOL = 'scripted-native-acceptance-v1'
NATIVE_V2_PROTOCOL = 'scripted-native-acceptance-v2'
NATIVE_V3_PROTOCOL = 'scripted-native-acceptance-v3'
NATIVE_V4_PROTOCOL = 'scripted-native-acceptance-v4'
PROFILES = {
    'hero': {'id':'hero-180','class_name':'Hero','level':180,
             'skill_keys':{'PRIMARY_SKILL':'Brandish','SECONDARY_SKILL':'Combo Attack','BUFF_1':'Booster','BUFF_2':'Maple Warrior'}},
    'bowmaster': {'id':'bowmaster-v1','class_name':'Bowmaster','level':180,
                  'skill_keys':{'PRIMARY_SKILL':'Hurricane','SECONDARY_SKILL':'Arrow Rain','BUFF_1':'Soul Arrow : Bow','BUFF_2':'Sharp Eyes'}},
    'ice_lightning_arch_mage': {'id':'ice-lightning-v1','class_name':'Ice/Lightning Arch Mage','level':180,
                              'skill_keys':{'PRIMARY_SKILL':'Chain Lightning','SECONDARY_SKILL':'Teleport','BUFF_1':'Magic Guard','BUFF_2':'Spell Booster'}},
    'night_lord': {'id':'night-lord-v1','class_name':'Night Lord','level':180,
                   'skill_keys':{'PRIMARY_SKILL':'Triple Throw','SECONDARY_SKILL':'Avenger','BUFF_1':'Claw Booster','BUFF_2':'Haste'}},
}

def contract(class_id, baseline_sha256, *, protocol=NATIVE_V2_PROTOCOL):
    if protocol not in (PROTOCOL,NATIVE_V2_PROTOCOL,NATIVE_V3_PROTOCOL,NATIVE_V4_PROTOCOL,TOOLKIT_NATIVE_PROTOCOL) or class_id not in PROFILES or not isinstance(baseline_sha256,str) or not re.fullmatch('[a-f0-9]{64}',baseline_sha256):
        raise ValueError('invalid_native_fixture')
    if protocol==TOOLKIT_NATIVE_PROTOCOL:
        policy=toolkit(class_id)
        return {'id':protocol,'class_id':class_id,'profile':toolkit_profile(policy),'skill_toolkit':policy,
            'baseline_sha256':baseline_sha256,'wall_seconds':60,'max_actions':32,'max_sdk_requests':180,
            'capture_max_ms':75000,'capture_duration_policy':dict(ENCODED_FRAME_POLICY)}
    # This new, scoped fixture has no historical v1/v2/v3 recipe. An explicit
    # v4 request binds its profile and source without changing prior fixtures.
    if class_id=='night_lord' and protocol!=NATIVE_V4_PROTOCOL:
        raise ValueError('night_lord_requires_native_v4')
    return {'id':protocol,'class_id':class_id,'profile':json.loads(json.dumps(PROFILES[class_id])),
            'baseline_sha256':baseline_sha256,'wall_seconds':30,'max_actions':12,'max_sdk_requests':100,
            'capture_max_ms':45000,'capture_duration_policy':dict(CAPTURE_DURATION_POLICY if protocol==PROTOCOL else ENCODED_FRAME_POLICY)}

def validate_contract(value):
    if not isinstance(value,dict):raise ValueError('invalid_native_acceptance')
    expected=contract(value.get('class_id'),value.get('baseline_sha256'),protocol=value.get('id'))
    if json.dumps(value,sort_keys=True,allow_nan=False)!=json.dumps(expected,sort_keys=True):
        raise ValueError('invalid_native_acceptance')
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
    if value['id']==TOOLKIT_NATIVE_PROTOCOL:return _toolkit_program(value)
    if value['id']==PROTOCOL:return _legacy_program(value)
    if value['id']==NATIVE_V3_PROTOCOL and class_id!='hero':return _targeted_program(value)
    if value['id']==NATIVE_V4_PROTOCOL and class_id!='hero':return _targeted_program(value,horizontal_limit=300)
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

def _targeted_program(value,*,horizontal_limit=110):
    # This is a distinct, explicitly requested recipe. V1/V2 bytes are retained.
    version='v4' if value['id']==NATIVE_V4_PROTOCOL else 'v3'
    code=f"""// Scripted native acceptance {version}; no model and no ranked result.
await sdk.wait(1000);
await sdk.observe();
await sdk.pressKeys(['JUMP'],300);
await sdk.observe();
await sdk.wait(1100);
await sdk.observe();
"""
    for key in ('BUFF_1','BUFF_2'):
        code+=f"await sdk.pressKeys(['{key}'],300);\nawait sdk.observe();\nawait sdk.wait(1100);\nawait sdk.observe();\n"
    code+="""// The native default attack rectangle spans y=-50..50 for these skills.
// This filters visible foot positions, not animation bounds; it is not hit proof.
const targets=(scene)=>scene.monsters.filter(m=>Math.abs(m.y-scene.character.y)<=50)
  .sort((a,b)=>Math.abs(a.x-scene.character.x)-Math.abs(b.x-scene.character.x));
let direction='RIGHT';
for(let step=0;step<4;step++){
  const scene=await sdk.observe(), nearby=targets(scene);
  if(!nearby.length)break;
  const dx=nearby[0].x-scene.character.x, inRange=Math.abs(dx)<=__PRIMARY_LIMIT__;
  direction=dx<0?'LEFT':'RIGHT';
  await sdk.pressKeys([direction],inRange?30:Math.min(1500,Math.max(300,Math.round(Math.abs(dx)*5))));
  const after=await sdk.observe(), current=targets(after);
  if(current.length&&Math.abs(current[0].x-after.character.x)<=__PRIMARY_LIMIT__)break;
  await sdk.wait(150);
}
// Recheck range and face immediately before casting, not before a basic-attack delay.
const aim=await sdk.observe(), nearby=targets(aim);
if(nearby.length&&Math.abs(nearby[0].x-aim.character.x)<=__PRIMARY_LIMIT__){
  direction=nearby[0].x<aim.character.x?'LEFT':'RIGHT';
  await sdk.pressKeys([direction],30);
  const faced=await sdk.observe(), current=targets(faced);
  if(current.some(m=>Math.abs(m.x-faced.character.x)<=__PRIMARY_LIMIT__&&(direction==='LEFT'?m.x<=faced.character.x:m.x>=faced.character.x))){
    await sdk.pressKeys(['PRIMARY_SKILL'],1200);
    await sdk.wait(1100);
    await sdk.observe();
    // One finite second cast; no retries, targeting loop or extra action allowance.
    await sdk.pressKeys(['PRIMARY_SKILL'],1200);
    await sdk.wait(1100);
    await sdk.observe();
  }
}
await sdk.observe();
await sdk.pressKeys(['ATTACK'],600);
await sdk.wait(1100);
await sdk.observe();
"""
    if value['class_id']=='ice_lightning_arch_mage':
        code+="""// A direction accompanies native Teleport; before/after observations retain displacement.
await sdk.observe();
await sdk.pressKeys([direction,'SECONDARY_SKILL'],300);
"""
    else:
        code+="await sdk.observe();\nawait sdk.pressKeys(['SECONDARY_SKILL'],600);\n"
    code+="await sdk.wait(1100);\nawait sdk.observe();\nawait sdk.wait(1500);\nawait sdk.observe();\n"
    return code.replace('__PRIMARY_LIMIT__',str(horizontal_limit))

def fingerprint(value):
    return hashlib.sha256((json.dumps(validate_contract(value),sort_keys=True,separators=(',',':'))+'\n').encode()).hexdigest()


def _toolkit_program(value):
    """Finite evidence recipe: no successful effect is inferred from a key ACK."""
    policy=value['skill_toolkit']
    code="// New toolkit native qualification candidate; no model or score.\n"
    if value['class_id']=='ice_lightning_arch_mage':
        # Isolate the movement skill before attack animations, buffs or combat.
        # Thirty milliseconds limits ordinary walking; paired observations and
        # the recording still need review for contact, collision and MP use.
        code+="""const teleportStart=await sdk.observe();
const teleportNearby=teleportStart.monsters.filter(m=>Math.abs(m.y-teleportStart.character.y)<=50)
  .sort((a,b)=>Math.abs(a.x-teleportStart.character.x)-Math.abs(b.x-teleportStart.character.x));
const teleportDirection=teleportNearby.length&&teleportNearby[0].x>=teleportStart.character.x?'LEFT':'RIGHT';
for(const direction of [teleportDirection,teleportDirection==='LEFT'?'RIGHT':'LEFT']){
  await sdk.observe();
  await sdk.pressKeys([direction,'SECONDARY_SKILL'],30);
  await sdk.observe();
  await sdk.wait(1100);
  await sdk.observe();
}
"""
    code+="""
await sdk.observe();
await sdk.pressKeys(['JUMP'],300);
await sdk.observe();
await sdk.wait(1100);
await sdk.observe();
"""
    # Include Combo before sword attacks and Soul Arrow before any bow attack.
    for skill in policy['skills']:
        if skill['route']=='buff':
            code+=f"await sdk.pressKeys(['{skill['slot']}'],300);\nawait sdk.wait(1100);\nawait sdk.observe();\n"
    code+="""let scene=await sdk.observe();
for(let i=0;i<4;i++){
  const near=scene.monsters.filter(m=>Math.abs(m.y-scene.character.y)<=50)
    .sort((a,b)=>Math.abs(a.x-scene.character.x)-Math.abs(b.x-scene.character.x));
  if(!near.length)break;
  const dx=near[0].x-scene.character.x;
  await sdk.pressKeys([dx<0?'LEFT':'RIGHT'],Math.abs(dx)>180?400:60);
  scene=await sdk.observe();
  if(Math.abs(dx)<=180)break;
}
"""
    # Three primary casts give Hero ordinary contact opportunities to build
    # orbs; this does not assert that contact or an orb increase occurred.
    for _ in range(3):
        code+="await sdk.pressKeys(['PRIMARY_SKILL'],600);\nawait sdk.wait(1100);\nawait sdk.observe();\n"
    code+="await sdk.pressKeys(['ATTACK'],600);\nawait sdk.wait(1100);\nawait sdk.observe();\n"
    for skill in sorted(policy['skills'],key=lambda skill:skill['route']=='movement'):
        if skill['slot']=='PRIMARY_SKILL' or skill['route']=='buff':continue
        if value['class_id']=='ice_lightning_arch_mage' and skill['route']=='movement':continue
        if skill['skill_id']==1111003:
            # Coma spent the previous orbs; give ordinary Brandish contact new
            # opportunities before Panic. Still require observed native orbs.
            for _ in range(3):
                code+="await sdk.pressKeys(['PRIMARY_SKILL'],600);\nawait sdk.wait(1100);\nawait sdk.observe();\n"
        keys=['RIGHT',skill['slot']] if skill['route']=='movement' else [skill['slot']]
        code+=f"await sdk.pressKeys({json.dumps(keys)},300);\nawait sdk.wait(1100);\nawait sdk.observe();\n"
    code+="await sdk.pressKeys(['MP_POTION'],100);\nawait sdk.wait(1500);\nawait sdk.observe();\n"
    return code
