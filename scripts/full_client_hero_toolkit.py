"""Frozen expanded Hero controls for the Hero-180 knowledge cohort.

This is a scoped extraction of the Hero declaration introduced by repository
commit 470dd8de24cc3ba1253268060198ecb992cf9d37. It is intended input
authority, not evidence that a skill cast, hit, buff, movement effect, or
resource change succeeded natively.
"""
import copy
import hashlib
import json

POLICY_ID = 'full-client-hero-toolkit-v1'
PHYSICAL_KEYS = {
    'PRIMARY_SKILL':('KeyA',30),'SECONDARY_SKILL':('KeyS',31),
    'BUFF_1':('KeyD',32),'BUFF_2':('KeyF',33),'SKILL_5':('KeyG',34),
    'SKILL_6':('KeyH',35),'SKILL_7':('KeyZ',44),'SKILL_8':('KeyX',45),
    'SKILL_9':('KeyC',46),'SKILL_10':('KeyV',47),
    'SKILL_11':('KeyB',48),'SKILL_12':('KeyN',49),
    'SKILL_13':('KeyM',50),'SKILL_14':('Comma',51),
    'SKILL_15':('Period',52),'SKILL_16':('Slash',53),
    'SKILL_17':('Semicolon',39),
}
SLOTS = {
    'PRIMARY_SKILL': ('Brandish',1121008,30,'attack',
        'Two-handed sword attack; face monsters on the same platform.'),
    'SECONDARY_SKILL': ('Combo Attack',1111002,30,'buff',
        'Activate before combat; only confirmed hits may be treated as orb-building evidence.'),
    'BUFF_1': ('Sword Booster',1101004,20,'buff',
        'Weapon-speed buff with HP and MP cost; verify the native buff and costs.'),
    'BUFF_2': ('Maple Warrior',1121000,20,'buff',
        'Base-stat buff; verify the exact native state change.'),
    'SKILL_5': ('Rush',1121006,30,'attack_movement',
        'Attack-movement skill; no target means no proven rush movement.'),
    'SKILL_6': ('Sword Coma',1111005,30,'attack',
        'Area finisher candidate; build and observe combo orbs before trying it.'),
    'SKILL_7': ('Sword Panic',1111003,30,'attack',
        'Focused finisher candidate; rebuild and observe combo orbs after another finisher.'),
    'SKILL_8': ('Power Stance',1121002,30,'buff',
        'Knockback-resistance buff; it does not promise damage prevention.'),
    'SKILL_9': ('Rage',1101006,20,'buff',
        'Weapon-attack buff with a defense tradeoff; verify exact native values.'),
    'SKILL_10': ('Power Guard',1101007,30,'buff',
        'Contact-damage defensive buff; continue to manage HP.'),
    'SKILL_11': ('Enrage',1121010,8,'buff',
        'Single-target damage buff; availability is exposed but its effect is not qualified by the core native receipt.'),
    'SKILL_12': ("Hero's Will",1121011,5,'buff',
        'Status-clearing skill; availability is exposed but requires a qualifying status to prove an effect.'),
    'SKILL_13': ('Shout',1111008,30,'attack',
        'Area attack; availability is exposed without a stun-probability claim.'),
    'SKILL_14': ('Armor Crash',1111007,20,'buff',
        'Monster-buff cancellation skill; availability is exposed but requires a suitable monster state to prove an effect.'),
    'SKILL_15': ('Iron Body',1001003,6,'buff',
        'Defense buff from the Warrior lineage; availability is exposed but outside the core native receipt.'),
    'SKILL_16': ('Power Strike',1001004,20,'attack',
        'Single-target Warrior attack; availability is exposed but outside the core native receipt.'),
    'SKILL_17': ('Slash Blast',1001005,20,'attack',
        'Multi-target Warrior attack; availability is exposed but outside the core native receipt.'),
}
CORE_SKILL_IDS = (1121008,1111002,1101004,1121000,1121006,
                  1111005,1111003,1121002,1101006,1101007)
BASE_KEYS = frozenset('LEFT RIGHT UP DOWN JUMP ATTACK HP_POTION MP_POTION'.split())


def toolkit():
    skills=[]
    for slot,(name,skill_id,level,route,description) in SLOTS.items():
        code,key=PHYSICAL_KEYS[slot]
        skills.append({'slot':slot,'name':name,'skill_id':skill_id,'level':level,
                       'route':route,'description':description,'code':code,'key':key,'key_type':1,
                       'release_qualification':'planned' if skill_id in CORE_SKILL_IDS
                           else 'available_unqualified'})
    return {'schema_version':1,'id':POLICY_ID,'fixture_id':'hero-180-expanded-v1',
            'class_name':'Hero','job':112,'level':180,'skills':skills,
            'scope':{'coverage':'full_2h_sword_hero_active_toolkit',
                     'catalog_completeness':'not_full_v83_hero_lineage'},
            'passives':[{'skill_id':1100000,'name':'Sword Mastery','level':20},
                        {'skill_id':1120003,'name':'Advanced Combo','level':30},
                        {'skill_id':1120004,'name':'Achilles','level':30},
                        {'skill_id':1100002,'name':'Final Attack: Sword','level':30},
                        {'skill_id':1000000,'name':'Improved HP Recovery','level':5},
                        {'skill_id':1000001,'name':'Improved Max HP Increase','level':10},
                        {'skill_id':1110000,'name':'Improved MP Recovery','level':11},
                        {'skill_id':1100001,'name':'Axe Mastery','level':1,
                         'equipment_applicability':'inactive_with_two_handed_sword'}],
            'native_qualification_skill_ids':list(CORE_SKILL_IDS),
            'unsupported':[
                'Monster Magnet is unavailable: its target-selection packet is absent from the physical client route.',
                'Guardian is unavailable: the fixture uses a two-handed sword and no shield.',
                'Axe Mastery has one otherwise-unused second-job point but is inactive with the fixed two-handed sword; Axe Booster, axe Panic, axe Coma, and other axe or shield variants are unavailable.',
                'Beginner allocation-dependent skills are not learned by the accepted fixture; movement, jump, basic attack, and consumable controls remain separate.'
            ],'qualification':'source_declared_native_release_required'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
        allow_nan=False).encode()).hexdigest()


def profile(value=None):
    value=validate_toolkit(toolkit() if value is None else value)
    return {'id':value['fixture_id'],'class_name':value['class_name'],'level':value['level'],
            'skill_keys':{skill['slot']:skill['name'] for skill in value['skills']}}


def validate_toolkit(value,expected_profile=None):
    try:
        expected=toolkit()
        if fingerprint(value)!=fingerprint(expected):
            raise ValueError('invalid_hero_skill_toolkit')
        if expected_profile is not None and fingerprint(expected_profile)!=fingerprint(profile(expected)):
            raise ValueError('hero_skill_toolkit_profile_mismatch')
    except (KeyError,TypeError,ValueError,OverflowError,RecursionError):
        raise ValueError('invalid_hero_skill_toolkit') from None
    return copy.deepcopy(expected)


def allowed_keys(value):
    return BASE_KEYS | {skill['slot'] for skill in validate_toolkit(value)['skills']}


def expected_keymap(value):
    """Exact ordinary DB keymap rows as [key, type, skill_id], sorted by key."""
    rows=[[skill['key'],skill['key_type'],skill['skill_id']]
          for skill in validate_toolkit(value)['skills']]
    return sorted(rows)


def expected_skills(value):
    """Exact learned invocable and passive rows as [skill_id, level]."""
    value=validate_toolkit(value)
    return sorted([[skill['skill_id'],skill['level']]
                   for skill in value['skills']+value['passives']])


def native_qualification_skills(value):
    """Return the exact core ten covered by the separate native receipt."""
    value = validate_toolkit(value)
    selected = set(value['native_qualification_skill_ids'])
    return [skill for skill in value['skills'] if skill['skill_id'] in selected]


def sdk_scenario(protocol):
    out={'protocol':protocol['id']}
    if 'skill_toolkit' in protocol:
        out['skill_toolkit']=validate_toolkit(protocol['skill_toolkit'],protocol['profile'])
    return out


def prompt_reference(value):
    value=validate_toolkit(value)
    lines=['Frozen 17-slot two-handed-sword Hero toolkit (core native receipt covers only the ten planned entries):']
    for skill in value['skills']:
        lines.append('  %s: %s level %d — %s' %
            (skill['slot'],skill['name'],skill['level'],skill['description']))
    lines += ['Learned passives have no input slots: Sword Mastery 20; Advanced Combo 30; Achilles 30; Final Attack: Sword 30; Improved HP Recovery 5; Improved Max HP Increase 10; Improved MP Recovery 11; Axe Mastery 1 (inactive with the equipped sword).',
              'The declared levels use 61 first-job SP, 121 second-job SP, 151 third-job SP, and 183 fourth-job SP.',
              'A key acknowledgement proves input delivery, not a cast, hit, buff, movement effect, combo change, or resource consumption.',
              'Unmapped skill slots are unavailable.']
    lines += ['Unavailable: '+item for item in value['unsupported']]
    return '\n'.join(lines)+'\n'
