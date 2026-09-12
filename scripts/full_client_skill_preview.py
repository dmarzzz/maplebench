"""One-request skill exploration in a full client; never a scored benchmark."""
import copy
import hashlib
import json
import re

from full_client_skill_toolkit import toolkit, profile, prompt_reference

PROTOCOL = 'full-client-skill-preview-v1'
SOURCE = 'full-client-skill-preview; unscored development'


def contract(class_id, baseline_sha256):
    if not isinstance(baseline_sha256, str) or re.fullmatch('[a-f0-9]{64}', baseline_sha256) is None:
        raise ValueError('invalid_skill_preview_baseline')
    kit = toolkit(class_id)
    return {'schema_version':1, 'id':PROTOCOL, 'baseline_sha256':baseline_sha256,
            'profile':profile(kit), 'skill_toolkit':kit,
            'program_seconds':60, 'api_timeout_seconds':50, 'run_seconds':123,
            'max_api_requests':1, 'max_output_tokens':3000, 'max_total_tokens':32000,
            'max_actions':240, 'max_sdk_requests':600,
            'purpose':'skill_exploration_unscored_development',
            'publication_eligible':False, 'score':None}


def validate_protocol(value):
    try:
        expected = contract(value['skill_toolkit']['class_id'], value['baseline_sha256'])
        if json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) != json.dumps(
                expected, sort_keys=True, separators=(',', ':'), allow_nan=False):
            raise ValueError()
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ValueError('invalid_skill_preview_protocol') from None
    return copy.deepcopy(expected)


def fingerprint(value):
    return hashlib.sha256(json.dumps(validate_protocol(value), sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def prompt(value):
    value = validate_protocol(value)
    title = value['profile']['class_name']
    specific = ('Try directional Teleport using SECONDARY_SKILL together with LEFT or RIGHT, '
                'then observe the actual before/after position. Explore Chain Lightning and '
                'different mapped spells such as Ice Strike, Thunder Spear and Blizzard when '
                'monsters and MP allow. Acknowledge collision or casting failures and adapt.\n'
                if value['skill_toolkit']['class_id'] == 'ice_lightning_arch_mage' else
                'Explore several mapped class skills when their resource and target requirements '
                'allow; observe the effects and adapt your movement and timing.\n')
    return f'''You control a level 180 {title} in a private MapleStory v83 full client.
This is a short, unscored development preview for skill exploration. It is not a
ranked trial or an equal-start model comparison. Discover how the mapped skills
behave while keeping the character alive; do not assume that input means success.
Write a JavaScript async function body using ONLY the frozen SDK. The harness
already wraps and invokes your code. Use top-level await. If you define a helper
function, explicitly await its call; a function declaration alone does nothing.
  sdk.observe(): current character {{x,y,hp,maxHp,mp,maxMp,exp,alive,mapId,level}}
    and nearby monsters [{{objectId,x,y}}]. Client XP is diagnostic only.
  sdk.pressKeys(keys, milliseconds): hold 1..3 named keys for 30..1500ms, then release.
    Basic keys: LEFT RIGHT UP DOWN JUMP ATTACK HP_POTION MP_POTION.
    The frozen reference below names the available skill keys.
  sdk.wait(milliseconds): wait 1..3000ms.
Coordinates increase rightward/downward. Use ordinary direction inputs, jump,
and the mapped native skills. Attacks generally need a nearby target in the
correct direction and platform. There is no target-by-ID action, moveTo, useSkill,
stat editing, reset, automatic combat, or resource refill. Observe inside loops.
{specific}Buff explicitly before combat where useful; allow casting time. Try varied skills
without repeatedly exhausting MP or overwriting useful buffs. Only actual native
animation, displacement, contact and saved resource evidence establish effects.
You have up to 60 seconds of PROGRAM execution after this single model response,
including at most 600 SDK calls and 240 pressKeys actions. The API wait is separate
and remains in the full recording; the world stays live during inference. Return
before the program deadline. No second model request or hidden helper policy will
continue the preview. Code runs in a bounded networkless container. Return JSON
{{note,code}} with a brief intention, not private reasoning.
''' + prompt_reference(value['skill_toolkit'])
