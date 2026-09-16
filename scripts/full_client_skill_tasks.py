"""Immutable executable contracts for the new skill-task suite.

This module does not activate the draft design, qualify a fixture, or launch a
model. Hashes bind operator-verified artifacts; hashes alone are not evidence
of native correctness. The original training/native/preview protocols are
independent and unchanged.
"""
import copy
import hashlib
import json
import math
import re

PROTOCOL = 'full-client-skill-tasks-v1'
DESIGN_ID = 'skill-suite-v1-draft-2026-09-14'
BINDING_PROTOCOL = 'native-skill-task-binding-v1'
OBSERVATION_PROTOCOL = 'full-client-skill-task-observation-v1'
LEDGER_SOURCE = 'cosmic_native_skill_ledger'
TASK_IDS = ('platforming-v1', 'native-teleport-v1', 'potion-use-v1')
RESERVED_TASK_IDS = ('buff-upkeep-v1', 'portal-navigation-v1', 'return-to-hunt-v1')
CLASS_ID = 'ice_lightning_arch_mage'
MOVEMENT_KEYS = ['LEFT', 'RIGHT', 'UP', 'DOWN', 'JUMP']
SOFTWARE_FIELDS = {'source_commit', 'client_js_sha256', 'client_wasm_sha256',
                   'server_jar_sha256', 'sdk_sha256', 'ledger_source_sha256',
                   'scorer_sha256', 'observation_schema_sha256'}
SHORT_LIMITS = {
    'wall_seconds':120, 'max_api_requests':4, 'max_output_tokens':3000,
    'aggregate_token_ceiling':96000, 'program_seconds':10,
    'max_actions':600, 'max_sdk_requests':2000, 'request_timeout_seconds':30,
    'minimum_request_admission_seconds':15, 'request_closeout_reserve_seconds':10,
    'settlement_seconds':5, 'input_ack_bound_ms':3000,
}
CLOCK_POLICY = {
    'id':'skill-task-wall-clock-v1',
    'origin':'immediately_before_first_model_request_after_readiness',
    'event_interval':'start_inclusive_deadline_exclusive',
    'inference_counts':True, 'post_deadline_settlement_can_score':False,
    'native_wall_clock_drift_ms':25,
}
READINESS = {
    'id':'skill-task-readiness-v1', 'deadline_ms':10000,
    'minimum_post_render_samples':3, 'minimum_span_ms':1000,
    'maximum_age_ms':1500, 'expected_monsters':0,
    'require_geometry':True, 'require_resources':True,
}


def require(value, reason):
    if not value:
        raise ValueError('skill_tasks: '+reason)


def integer(value, low=0, high=2**53-1):
    return type(value) is int and low <= value <= high


def digest(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha256(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _geometry(value):
    require(type(value) is dict and set(value) == {'map_id','footholds'}, 'invalid_geometry')
    require(integer(value['map_id'], 1, 2**31-1), 'invalid_map')
    rows=value['footholds']
    require(type(rows) is list and 1 <= len(rows) <= 4096, 'foothold_count')
    for row in rows:
        require(type(row) is dict and set(row) == {'id','x1','y1','x2','y2'}
                and integer(row['id'],1,65535)
                and all(integer(row[k],-32768,32767) for k in ('x1','y1','x2','y2')),
                'invalid_foothold')
    require([r['id'] for r in rows] == sorted({r['id'] for r in rows}), 'footholds_not_unique_sorted')
    return {r['id']:r for r in rows}


def ground_y(foothold, x):
    require(foothold['x1'] != foothold['x2'], 'vertical_foothold_not_ground')
    return foothold['y1']+(x-foothold['x1'])*(foothold['y2']-foothold['y1'])/(foothold['x2']-foothold['x1'])


def _region(value, geometry, *, margin):
    require(type(value) is dict and set(value) == {'map_id','foothold_id','x_min','x_max','y_min','y_max'}, 'invalid_region')
    require(value['map_id'] == geometry['map_id']
            and all(integer(value[k],-32768,32767) for k in ('x_min','x_max','y_min','y_max'))
            and value['x_min'] < value['x_max'] and value['y_min'] <= value['y_max'], 'invalid_region_bounds')
    footholds={r['id']:r for r in geometry['footholds']}
    require(integer(value['foothold_id'],1,65535) and value['foothold_id'] in footholds, 'region_foothold_missing')
    fh=footholds[value['foothold_id']]
    lo,hi=sorted((fh['x1'],fh['x2']))
    require(lo+margin <= value['x_min'] < value['x_max'] <= hi-margin, 'region_edge_margin')
    require(all(value['y_min'] <= ground_y(fh,x) <= value['y_max'] for x in (value['x_min'],value['x_max'])),
            'region_does_not_contain_ground')


def validate_binding(value, task_id, variant, *, control='positive'):
    fields={'schema_version','id','task_id','variant','class_id','level','baseline_sha256',
            'equipment_sha256','inventory_sha256','keymap_sha256','native_definitions_sha256',
            'geometry_sha256','software','geometry','initial','target','milestones','teleport'}
    require(type(value) is dict and set(value) == fields and value['schema_version'] == 1
            and type(value['schema_version']) is int and value['id'] == BINDING_PROTOCOL,
            'unbound_or_invalid_fixture')
    require(value['task_id'] == task_id and type(value['variant']) is int and value['variant'] == variant
            and value['class_id'] == CLASS_ID and type(value['level']) is int and value['level'] == 180,
            'fixture_identity_mismatch')
    for key in ('baseline_sha256','equipment_sha256','inventory_sha256','keymap_sha256',
                'native_definitions_sha256','geometry_sha256'):
        require(digest(value[key]), 'missing_fixture_hash')
    software=value['software']
    require(type(software) is dict and set(software) == SOFTWARE_FIELDS, 'software_bindings_required')
    require(type(software['source_commit']) is str and re.fullmatch('[a-f0-9]{40}',software['source_commit']), 'source_commit_required')
    require(all(digest(v) for k,v in software.items() if k != 'source_commit'), 'software_hash_required')
    footholds=_geometry(value['geometry'])
    require(sha256(value['geometry']) == value['geometry_sha256'], 'geometry_hash_mismatch')
    initial=value['initial']
    require(type(initial) is dict and set(initial) == {'map_id','x','y','foothold_id','facing',
            'hp','max_hp','mp','max_mp','power_elixirs','active_buffs','monster_count'}, 'invalid_initial_state')
    require(initial['map_id'] == value['geometry']['map_id'] and initial['facing'] in ('left','right')
            and all(integer(initial[k],-32768,32767) for k in ('x','y'))
            and integer(initial['foothold_id'],1,65535) and initial['foothold_id'] in footholds,
            'initial_position_unbound')
    fh=footholds[initial['foothold_id']]
    require(min(fh['x1'],fh['x2']) <= initial['x'] <= max(fh['x1'],fh['x2'])
            and abs(initial['y']-ground_y(fh,initial['x'])) <= 1, 'initial_ground_mismatch')
    require(integer(initial['max_hp'],1,30000) and type(initial['hp']) is int and initial['hp'] == initial['max_hp']
            and integer(initial['max_mp'],1,30000) and integer(initial['mp'],0,initial['max_mp'])
            and integer(initial['power_elixirs'],0,1)
            and initial['active_buffs'] == [] and type(initial['active_buffs']) is list
            and type(initial['monster_count']) is int and initial['monster_count'] == 0, 'initial_resources_or_scene')
    require(type(value['milestones']) is list, 'milestones_required')
    if task_id == 'potion-use-v1':
        require(initial['mp'] == initial['max_mp']*(variant+1)//20,
                'potion_initial_mp_fraction')
        require(initial['power_elixirs'] == (0 if control == 'empty-inventory' else 1)
                and value['target'] is None and value['milestones'] == [] and value['teleport'] is None,
                'potion_fixture_scope')
    else:
        require(initial['power_elixirs'] == 0, 'movement_fixture_has_potions')
        _region(value['target'], value['geometry'], margin=16)
        require(not (value['target']['x_min'] <= initial['x'] <= value['target']['x_max']
                     and value['target']['y_min'] <= initial['y'] <= value['target']['y_max']), 'goal_already_satisfied')
        require(len(value['milestones']) == (1 if variant == 3 else 0), 'variant_milestones_changed')
        for region in value['milestones']:
            _region(region,value['geometry'],margin=16)
            require(region != value['target'], 'intermediate_equals_target')
        if variant in (1,2):
            require((value['target']['x_min'] > initial['x']) if variant == 1
                    else (value['target']['x_max'] < initial['x']), 'variant_direction_changed')
        if task_id == 'platforming-v1':
            require(initial['mp'] == initial['max_mp'] and value['teleport'] is None, 'platforming_fixture_scope')
        else:
            skill=value['teleport']
            require(type(skill) is dict and set(skill) == {'skill_id','level','slot','mp_cost','distance_px','definitions_sha256'},
                    'teleport_definition_required')
            require(type(skill['skill_id']) is int and skill['skill_id'] == 2201002
                    and type(skill['level']) is int and skill['level'] == 20 and skill['slot'] == 'SECONDARY_SKILL'
                    and integer(skill['mp_cost'],1,initial['max_mp']) and integer(skill['distance_px'],1,1000)
                    and digest(skill['definitions_sha256']), 'teleport_definition_changed')
            require(initial['mp'] < skill['mp_cost'] if control == 'insufficient-mp'
                    else initial['mp'] == initial['max_mp'], 'teleport_initial_resource_mismatch')
    return copy.deepcopy(value)


def contract(task_id, variant, binding, *, purpose='native-control', control='positive', qualification_sha256=None):
    require(task_id in TASK_IDS, 'task_not_implemented')
    require(integer(variant,1,3), 'invalid_variant')
    require(purpose in ('native-control','model-development','model-comparative'), 'invalid_purpose')
    controls={'platforming-v1':{'positive','no-op','fly-through'},
              'native-teleport-v1':{'positive','walking-only','insufficient-mp'},
              'potion-use-v1':{'positive','passive-wait','empty-inventory'}}
    require(control in controls[task_id], 'invalid_control')
    if purpose != 'native-control':
        require(control == 'positive' and digest(qualification_sha256), 'model_qualification_binding_required')
    else:
        require(qualification_sha256 is None, 'native_control_cannot_claim_qualification')
    binding=validate_binding(binding,task_id,variant,control=control)
    allowed=MOVEMENT_KEYS+(['SECONDARY_SKILL'] if task_id == 'native-teleport-v1'
                           else ['HP_POTION','MP_POTION'] if task_id == 'potion-use-v1' else [])
    predicate={'id':task_id+'-predicate-v1','alive_required':True}
    if task_id in ('platforming-v1','native-teleport-v1'):
        predicate.update(stable_presence_ms=1000,minimum_position_hz=10,maximum_position_gap_ms=250,
                         grounded_required=True,foothold_tolerance_px=1,
                         movement_trust='ordinary_server_accepted_client_movement_with_separate_geometry_and_physics_validation')
    if task_id == 'native-teleport-v1':
        predicate.update(minimum_accepted_teleports=2 if variant == 3 else 1,
                         require_linked_native_mp_cost=True,require_linked_accepted_displacement=True)
    if task_id == 'potion-use-v1':
        predicate.update(item_id=2000005,items_consumed=1,minimum_mp_numerator=4,minimum_mp_denominator=5,
                         resource_attribution='same_native_item_use_transaction',shared_potion_keys=True)
    limits=dict(SHORT_LIMITS)
    if purpose == 'native-control':limits['max_api_requests']=0
    return {'schema_version':1,'id':PROTOCOL,'design_id':DESIGN_ID,'task_id':task_id,'variant':variant,
            'purpose':purpose,'control':control,'class_id':CLASS_ID,'level':180,
            'binding':binding,'binding_sha256':sha256(binding),'qualification_sha256':qualification_sha256,
            'observation_protocol':OBSERVATION_PROTOCOL,'allowed_keys':allowed,'predicate':predicate,
            'limits':limits,'clock':dict(CLOCK_POLICY),'readiness':dict(READINESS)}


def validate_contract(value):
    try:
        require(type(value) is dict, 'invalid_contract')
        expected=contract(value['task_id'],value['variant'],value['binding'],purpose=value['purpose'],
                          control=value['control'],qualification_sha256=value['qualification_sha256'])
        require(canonical(value) == canonical(expected), 'contract_changed')
    except (KeyError,TypeError,OverflowError):
        raise ValueError('skill_tasks: invalid_contract') from None
    return expected


def fingerprint(value):
    return sha256(validate_contract(value))


def allowed_keys(value):
    return list(validate_contract(value)['allowed_keys'])


def sdk_scenario(value):
    """Protocol-specific RPC boundary; never a generic arbitrary-key override."""
    value=validate_contract(value)
    return {'adapter':'full-client','protocol':PROTOCOL,'skill_task':value}


def descriptor(value):
    value=validate_contract(value);binding=value['binding'];initial=binding['initial']
    goals={
        'platforming-v1':'Reach the target platform and remain grounded inside its region for one continuous second.',
        'native-teleport-v1':'Use directional native Teleport along the declared route, then remain grounded in the target region for one continuous second.',
        'potion-use-v1':'Consume the one shared Power Elixir to restore MP to at least80% of maximum while alive.',
    }
    return {'schema_version':1,'id':OBSERVATION_PROTOCOL,'task_id':value['task_id'],'variant':value['variant'],
            'goal':goals[value['task_id']],'wall_seconds':120,'inference_counts':True,
            'allowed_keys':value['allowed_keys'],'geometry':binding['geometry'],
            'target':binding['target'],'milestones':binding['milestones'],
            'initial_resources':{k:initial[k] for k in ('hp','max_hp','mp','max_mp','power_elixirs')},
            'potion':{'item_id':2000005,'keys':['HP_POTION','MP_POTION'],'shared_inventory':True}
                      if value['task_id']=='potion-use-v1' else None,
            'teleport':{k:binding['teleport'][k] for k in ('skill_id','level','slot','mp_cost','distance_px')}
                       if binding['teleport'] else None,
            'criterion':{k:v for k,v in value['predicate'].items()
                         if k not in ('id','movement_trust','resource_attribution')}}


def request_admission(value, remaining_ms):
    """Pure deadline clamp; caller additionally reserves actual token budgets."""
    value=validate_contract(value)
    require(type(remaining_ms) in (int,float) and math.isfinite(remaining_ms), 'invalid_remaining_time')
    admitted=value['purpose']!='native-control' and remaining_ms >= 15000
    return {'admitted':admitted,'timeout_ms':min(30000,remaining_ms-10000) if admitted else None,
            'program_limit_ms':max(0,min(10000,remaining_ms-5000))}


def input_fits(value, remaining_ms):
    validate_contract(value)
    require(type(remaining_ms) in (int,float) and math.isfinite(remaining_ms), 'invalid_remaining_time')
    # The complete ACK bound must fit before the five-second settlement reserve.
    return remaining_ms >= 8000
