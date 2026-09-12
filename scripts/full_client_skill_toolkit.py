"""Frozen physical skill slots for a new class-training fixture.

Declarations describe implemented native routes, not live qualification. Actual
NX/XML parity, persisted bindings/resources and native effects remain required.
No function in this module connects to the game, modifies a DB or calls a model.
"""
import copy
import hashlib
import json

POLICY_ID = 'full-client-skill-toolkit-v1'
RECIPE_ID = 'full-client-training-v2'
NATIVE_PROTOCOL = 'scripted-native-toolkit-acceptance-v1'
SLOTS = {
    'PRIMARY_SKILL': ('KeyA', 30), 'SECONDARY_SKILL': ('KeyS', 31),
    'BUFF_1': ('KeyD', 32), 'BUFF_2': ('KeyF', 33),
    'SKILL_5': ('KeyG', 34), 'SKILL_6': ('KeyH', 35),
    'SKILL_7': ('KeyZ', 44), 'SKILL_8': ('KeyX', 45),
    'SKILL_9': ('KeyC', 46), 'SKILL_10': ('KeyV', 47),
}
BASE_KEYS = frozenset('LEFT RIGHT UP DOWN JUMP ATTACK HP_POTION MP_POTION'.split())


def _skill(skill_id, level, name, route, description):
    return dict(skill_id=skill_id, level=level, name=name, route=route,
                description=description, live_qualification='required')


# IDs are from the pinned Cosmic constants/skills source and Journey attack
# dispatch. Descriptions deliberately avoid unmeasured hit/damage/range claims.
_CLASSES = {
    'hero': dict(name='Hero', job=112, mp=6000, skills=[
        _skill(1121008, 30, 'Brandish', 'attack', 'Two-handed sword attack; face monsters on your platform.'),
        _skill(1111002, 30, 'Combo Attack', 'buff', 'Activate before combat; ordinary hits build combo orbs.'),
        _skill(1101004, 20, 'Sword Booster', 'buff', 'Weapon speed buff; consumes HP and MP.'),
        _skill(1121000, 20, 'Maple Warrior', 'buff', 'Temporarily increases base stats.'),
        _skill(1121006, 30, 'Rush', 'attack_movement', 'Attack and approach a contacted monster; no target means no rush.'),
        _skill(1111005, 30, 'Sword Coma', 'attack', 'Area finisher that spends accumulated combo orbs; build orbs first.'),
        _skill(1111003, 30, 'Sword Panic', 'attack', 'Focused finisher that spends accumulated combo orbs; build orbs first.'),
        _skill(1121002, 30, 'Power Stance', 'buff', 'Temporarily resists knockback; does not prevent damage.'),
        _skill(1101006, 20, 'Rage', 'buff', 'Weapon attack buff with a defense tradeoff.'),
        _skill(1101007, 30, 'Power Guard', 'buff', 'Defensive contact-damage buff; still manage HP.'),
    ], passives=[(1100000,20),(1120003,30)], unsupported=[
        'Monster Magnet requires a target-selection packet absent from the physical client.',
        'Guardian requires a shield; this fixture uses a two-handed sword.',
    ]),
    'bowmaster': dict(name='Bowmaster', job=312, mp=6000, skills=[
        _skill(3121004, 30, 'Hurricane', 'attack', 'Ranged bow attack; this port uses discrete casts, not authentic continuous channeling.'),
        _skill(3111004, 30, 'Arrow Rain', 'attack', 'Area bow attack for nearby groups.'),
        _skill(3101004, 20, 'Soul Arrow : Bow', 'buff', 'Allows bow attacks without consuming physical arrows while active.'),
        _skill(3121002, 30, 'Sharp Eyes', 'buff', 'Critical attack buff; cast before sustained combat.'),
        _skill(3111006, 30, 'Strafe', 'attack', 'Focused multi-arrow attack; face the target and manage distance.'),
        _skill(3101005, 30, 'Arrow Bomb', 'attack', 'Ranged attack with a native stun effect on eligible monsters.'),
        _skill(3101002, 20, 'Bow Booster', 'buff', 'Weapon speed buff; consumes HP and MP.'),
        _skill(3121000, 20, 'Maple Warrior', 'buff', 'Temporarily increases base stats.'),
        _skill(3121007, 30, 'Hamstring', 'buff', 'Attacks can slow eligible monsters while this buff is active.'),
        _skill(3111003, 30, 'Inferno', 'attack', 'Fire-element bow attack for grouped monsters.'),
    ], passives=[(3100000,20),(3120005,30),(3000001,20),(3000002,8)], unsupported=[
        'Hurricane continuous channeling is not implemented; repeated physical inputs remain discrete casts.',
        'Puppet, Silver Hawk and Phoenix need native summon AI/packet qualification and are excluded.',
    ]),
    'ice_lightning_arch_mage': dict(name='Ice/Lightning Arch Mage', job=222, mp=16000, skills=[
        _skill(2221006, 30, 'Chain Lightning', 'attack', 'Lightning attack; choose targets and platform alignment from observations.'),
        _skill(2201002, 20, 'Teleport', 'movement', 'Pair with a direction for collision-aware native teleport movement.'),
        _skill(2001002, 20, 'Magic Guard', 'buff', 'Redirects part of incoming damage to MP; maintain both resources.'),
        _skill(2211005, 20, 'Spell Booster', 'buff', 'Casting-speed buff; consumes HP and MP.'),
        _skill(2211002, 30, 'Ice Strike', 'attack', 'Nearby area ice attack; eligible monsters can freeze.'),
        _skill(2211003, 30, 'Thunder Spear', 'attack', 'Focused lightning spell.'),
        _skill(2221007, 30, 'Blizzard', 'attack', 'Wide ice attack with a large MP cost; amplification increases consumption.'),
        _skill(2201001, 20, 'Meditation', 'buff', 'Temporarily increases magic attack.'),
        _skill(2221000, 20, 'Maple Warrior', 'buff', 'Temporarily increases base stats.'),
        _skill(2001003, 20, 'Magic Armor', 'buff', 'Temporary defense buff; does not replace Magic Guard.'),
    ], passives=[(2200000,20),(2210001,30)], unsupported=[
        'Ifrit summon attack AI/packets are not qualified and the summon is excluded.',
        'Big Bang charge/release semantics are not implemented and it is excluded.',
    ]),
    'night_lord': dict(name='Night Lord', job=412, mp=6000, skills=[
        _skill(4121007, 30, 'Triple Throw', 'attack', 'Ranged claw attack; consumes real throwing stars.'),
        _skill(4111005, 30, 'Avenger', 'attack', 'Ranged multi-target star attack; consumes real throwing stars.'),
        _skill(4101003, 20, 'Claw Booster', 'buff', 'Weapon speed buff; consumes HP and MP.'),
        _skill(4101004, 20, 'Haste', 'buff', 'Increases ordinary walk speed and jump height.'),
        _skill(4101005, 30, 'Drain', 'attack', 'Star attack that restores HP from actual damage; misses do not heal.'),
        _skill(4001344, 20, 'Lucky Seven', 'attack', 'Lower-job two-star attack; keep targets in front and preserve ammunition.'),
        _skill(4121000, 20, 'Maple Warrior', 'buff', 'Temporarily increases base stats.'),
        _skill(4111001, 20, 'Meso Up', 'buff', 'Increases meso drops; it does not directly increase this XP score.'),
    ], passives=[(4000000,3),(4000001,8),(4100000,20),(4100001,30)], unsupported=[
        'Flash Jump has an empty native movement branch; asset-defined displacement and physics support must be implemented before binding it.',
        'Shadow Partner hit duplication is not implemented or qualified; no summoning rocks are supplied.',
        'Shadow Stars ammunition exemption is not implemented in this client; finite physical stars are required.',
        'Ninja Ambush and Shadow Web need separate native effect/packet qualification and are excluded.',
    ]),
}


def toolkit(class_id):
    """Return a new value; callers cannot mutate the canonical policy."""
    if class_id not in _CLASSES:
        raise ValueError('invalid_skill_toolkit_class')
    cls = _CLASSES[class_id]
    skills = []
    for slot, skill in zip(SLOTS, cls['skills']):
        code, scancode = SLOTS[slot]
        skills.append(dict(copy.deepcopy(skill), slot=slot, code=code, key=scancode, key_type=1))
    return {'schema_version':1, 'id':POLICY_ID, 'class_id':class_id,
        'fixture_id':class_id.replace('_','-')+'-toolkit-v1', 'class_name':cls['name'],
        'job':cls['job'], 'level':180, 'skills':skills,
        'passives':[{'skill_id':sid,'level':level} for sid,level in cls['passives']],
        'resources':{'hp':12000, 'max_hp':12000, 'mp':cls['mp'], 'max_mp':cls['mp'],
            'potion':{'item_id':2000005, 'quantity':100, 'keys':['HP_POTION','MP_POTION'],
                      'description':'Both potion keys consume the same finite Power Elixir supply, restoring HP and MP.'},
            'ammunition':({'item_id':2060000,'stacks':4,'quantity_per_stack':2000} if class_id=='bowmaster'
                else {'item_id':2070006,'stacks':23,'quantity_per_stack':800} if class_id=='night_lord' else None),
            'runtime_refill':False},
        'qualification':'source_implemented_live_qualification_required',
        'unsupported':copy.deepcopy(cls['unsupported'])}


def profile(value):
    value = validate_toolkit(value)
    return {'id':value['fixture_id'],'class_name':value['class_name'],'level':value['level'],
            'skill_keys':{s['slot']:s['name'] for s in value['skills']}}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def validate_toolkit(value, expected_profile=None):
    try:
        expected = toolkit(value['class_id'])
        if fingerprint(value) != fingerprint(expected):
            raise ValueError('invalid_skill_toolkit')
        if expected_profile is not None:
            p = {'id':expected['fixture_id'],'class_name':expected['class_name'],'level':expected['level'],
                 'skill_keys':{s['slot']:s['name'] for s in expected['skills']}}
            if fingerprint(expected_profile) != fingerprint(p):
                raise ValueError('skill_toolkit_profile_mismatch')
    except (KeyError,TypeError,OverflowError,RecursionError):
        raise ValueError('invalid_skill_toolkit') from None
    return expected


def allowed_keys(value):
    value = validate_toolkit(value)
    return BASE_KEYS | {skill['slot'] for skill in value['skills']}


def sdk_scenario(protocol):
    """Preserve the existing outer envelope while binding extra input authority."""
    out = {'protocol':protocol['id']}
    if 'skill_toolkit' in protocol:
        out['skill_toolkit'] = validate_toolkit(protocol['skill_toolkit'],protocol['profile'])
    return out


def prompt_reference(value):
    value = validate_toolkit(value)
    lines = ['Frozen expanded skill toolkit (new training fixture; native qualification is a separate gate):']
    resources = value['resources']
    lines.append(f"Starting resources: HP {resources['hp']}/{resources['max_hp']}, MP {resources['mp']}/{resources['max_mp']}; "
                 f"{resources['potion']['quantity']} shared Power Elixirs.")
    ammo = resources['ammunition']
    if ammo:
        lines.append(f"Starting ammunition: {ammo['stacks']} stacks of {ammo['quantity_per_stack']} "
                     f"{'Ilbi throwing stars' if value['class_id']=='night_lord' else 'ordinary bow arrows'} "
                     f"({ammo['stacks'] * ammo['quantity_per_stack']} total).")
    else:
        lines.append('This fixture has no ammunition supply or ammunition requirement.')
    for skill in value['skills']:
        lines.append(f"  {skill['slot']} ({skill['code'][3:]}): {skill['name']} level {skill['level']} — {skill['description']}")
    lines += ['Both HP_POTION and MP_POTION consume the same finite Power Elixir supply.',
              'A key acknowledgement proves input delivery, not a cast, hit, buff or resource consumption.',
              'Unmapped skill slots are unavailable. No automatic refill or alternate skill dispatch exists.']
    lines += ['Unavailable: '+item for item in value['unsupported']]
    return '\n'.join(lines)+'\n'
