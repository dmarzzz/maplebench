"""Frozen, zero-model native recipes for private capture/fixture acceptance."""
import hashlib
import json
import re

from full_client_capture import CAPTURE_DURATION_POLICY, ENCODED_FRAME_POLICY, validate_duration_policy

PROTOCOL = 'scripted-native-acceptance-v1'
NATIVE_V2_PROTOCOL = 'scripted-native-acceptance-v2'
PROFILES = {
    'hero': {'id':'hero-180','class_name':'Hero','level':180,
             'skill_keys':{'PRIMARY_SKILL':'Brandish','SECONDARY_SKILL':'Combo Attack','BUFF_1':'Booster','BUFF_2':'Maple Warrior'}},
    'bowmaster': {'id':'bowmaster-v1','class_name':'Bowmaster','level':180,
                  'skill_keys':{'PRIMARY_SKILL':'Hurricane','SECONDARY_SKILL':'Arrow Rain','BUFF_1':'Soul Arrow : Bow','BUFF_2':'Sharp Eyes'}},
    'ice_lightning_arch_mage': {'id':'ice-lightning-v1','class_name':'Ice/Lightning Arch Mage','level':180,
                              'skill_keys':{'PRIMARY_SKILL':'Chain Lightning','SECONDARY_SKILL':'Teleport','BUFF_1':'Magic Guard','BUFF_2':'Spell Booster'}},
}

def contract(class_id, baseline_sha256, *, protocol=NATIVE_V2_PROTOCOL):
    if protocol not in (PROTOCOL,NATIVE_V2_PROTOCOL) or class_id not in PROFILES or not isinstance(baseline_sha256,str) or not re.fullmatch('[a-f0-9]{64}',baseline_sha256):
        raise ValueError('invalid_native_fixture')
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

def fingerprint(value):
    return hashlib.sha256((json.dumps(validate_contract(value),sort_keys=True,separators=(',',':'))+'\n').encode()).hexdigest()
