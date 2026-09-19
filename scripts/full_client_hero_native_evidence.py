"""Verify sealed native evidence for the expanded Hero-180 toolkit.

The producer observes ordinary Cosmic handlers. Relay acknowledgements and
client-rendered diagnostics are deliberately absent from the acceptance rules.
This verifier proves bounded accessibility of the ten declared skills; it does
not certify balance, stun chance, Stance probability, or Power Guard ratios.
"""
import hashlib
import re

from full_client_hero_toolkit import toolkit
from full_client_native import (HERO_TOOLKIT_PROTOCOL, fingerprint,
                                validate_contract)
from full_client_score import parse_json

TASK_ID = 'hero-180-toolkit-qualification-v1'
SOURCE = 'cosmic_native_skill_ledger'
VERIFIER_PROTOCOL = 'hero-180-native-skill-verifier-v1'
MAX_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 100000
ENVELOPE = {'schema_version','source','kind','run_id','server_instance_id',
            'character_id','account_id','task_id','binding_sha256',
            'runtime_sha256','sequence','event_id','elapsed_ns','wall_ms',
            'previous_sha256','data'}
EXPECTED = {'run_id','server_instance_id','character_id','account_id',
            'runtime_sha256','ledger_sha256','start_monotonic_ns',
            'start_wall_ms','duration_ns'}
ACTOR = {'job','level','map_id','hp','mp','max_hp','max_mp','x','y',
         'combo_orbs','active_buffs','stats','alive','online','snapshot_atomic'}
STATS = {'str','dex','weapon_attack','weapon_defense'}
SUMMARY = {'transaction_id','skill_id','skill_level','route','committed','map_id',
           'hp_before','hp_after','mp_before','mp_after','combo_orbs_before',
           'combo_orbs_after','position_before','position_after',
           'active_buffs_before','active_buffs_after','stats_before','stats_after',
           'resource_event_ids','damage_event_ids','endpoint_snapshots_atomic'}


class InvalidEvidence(ValueError):
    pass


class NotQualified(InvalidEvidence):
    pass


def require(value, code):
    if not value:
        raise InvalidEvidence(code)


def fields(value, names, code='hero_event_schema_mismatch'):
    require(type(value) is dict and set(value) == set(names), code)


def integer(value, low=0, high=2**53-1):
    return type(value) is int and low <= value <= high


def digest(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None


def identity(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{32}', value) is not None


def event_id(value):
    return type(value) is str and re.fullmatch(r'e[0-9]{8}', value) is not None


def _buffs(value):
    require(type(value) is list and len(value) <= 64, 'hero_buff_state_invalid')
    require(all(type(row) is list and len(row) == 2
                and integer(row[0], 1, 2**31-1)
                and integer(row[1], -32768, 32767) for row in value),
            'hero_buff_state_invalid')
    require(value == sorted(value) and len({row[0] for row in value}) == len(value),
            'hero_buff_state_invalid')
    return {row[0]: row[1] for row in value}


def _stats(value):
    fields(value, STATS, 'hero_stat_state_invalid')
    require(all(integer(item, 0, 2**31-1) for item in value.values()),
            'hero_stat_state_invalid')


def _position(value):
    fields(value, {'x','y'}, 'hero_position_invalid')
    require(all(integer(value[key], -32768, 32767) for key in ('x','y')),
            'hero_position_invalid')


def _actor(value, *, initial=False):
    fields(value, ACTOR, 'hero_actor_state_invalid')
    require(value['job'] == 112 and value['level'] == 180
            and value['map_id'] == 240040511
            and integer(value['max_hp'], 1, 30000)
            and integer(value['max_mp'], 1, 30000)
            and integer(value['hp'], 0, value['max_hp'])
            and integer(value['mp'], 0, value['max_mp'])
            and integer(value['x'], -32768, 32767)
            and integer(value['y'], -32768, 32767)
            and integer(value['combo_orbs'], 0, 10)
            and value['alive'] is (value['hp'] > 0)
            and value['online'] is True and value['snapshot_atomic'] is False,
            'hero_actor_state_invalid')
    buffs = _buffs(value['active_buffs'])
    _stats(value['stats'])
    if initial:
        require(not buffs and value['combo_orbs'] == 0,
                'hero_initial_state_not_clean')


def _parse(raw, contract, expected):
    fields(expected, EXPECTED, 'trusted_hero_context_missing')
    require(all(identity(expected[key]) for key in ('run_id','server_instance_id'))
            and all(integer(expected[key], 1, 2**31-1)
                    for key in ('character_id','account_id'))
            and all(digest(expected[key])
                    for key in ('runtime_sha256','ledger_sha256'))
            and integer(expected['start_monotonic_ns'], 0, 2**63-1)
            and integer(expected['start_wall_ms'], 1, 2**53-1)
            and expected['duration_ns'] == 120000000000,
            'trusted_hero_context_invalid')
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES
            and raw.endswith(b'\n'), 'hero_ledger_bytes_invalid')
    require(hashlib.sha256(raw).hexdigest() == expected['ledger_sha256'],
            'hero_ledger_hash_mismatch')
    lines = raw.splitlines(keepends=True)
    require(2 <= len(lines) <= MAX_EVENTS, 'hero_ledger_event_count')
    rows, previous, elapsed, wall = [], '0'*64, -1, -1
    binding = fingerprint(contract)
    for sequence, line in enumerate(lines):
        require(len(line) <= 65536 and line.endswith(b'\n'),
                'hero_ledger_line_invalid')
        try:
            row = parse_json(line)
        except (ValueError, UnicodeError):
            raise InvalidEvidence('hero_ledger_json_invalid') from None
        fields(row, ENVELOPE)
        require(row['schema_version'] == 1 and type(row['schema_version']) is int
                and row['source'] == SOURCE and row['task_id'] == TASK_ID
                and row['binding_sha256'] == binding,
                'hero_ledger_binding_mismatch')
        require(all(type(row[key]) is type(expected[key])
                    and row[key] == expected[key]
                    for key in ('run_id','server_instance_id','character_id',
                                'account_id','runtime_sha256')),
                'hero_ledger_identity_mismatch')
        require(row['sequence'] == sequence and type(row['sequence']) is int
                and row['event_id'] == f'e{sequence:08d}'
                and row['previous_sha256'] == previous,
                'hero_ledger_chain_mismatch')
        require(integer(row['elapsed_ns'], 0, 125000000000)
                and row['elapsed_ns'] >= elapsed
                and integer(row['wall_ms'], expected['start_wall_ms'], 2**53-1)
                and row['wall_ms'] >= wall
                and abs(row['wall_ms'] - expected['start_wall_ms']
                        - row['elapsed_ns']/1000000) <= 250,
                'hero_native_clock_invalid')
        require(type(row['kind']) is str and type(row['data']) is dict,
                'hero_event_schema_mismatch')
        previous = hashlib.sha256(line).hexdigest()
        elapsed, wall = row['elapsed_ns'], row['wall_ms']
        rows.append(row)
    header, terminal = rows[0], rows[-1]
    require(header['kind'] == 'header' and header['elapsed_ns'] == 0
            and terminal['kind'] == 'terminal', 'closed_hero_window_required')
    fields(header['data'], {'start_monotonic_ns','deadline_elapsed_ns',
            'movement_physics_validated','teleport_causal_link_supported',
            'coverage_source','initial','resource_coverage','inventory_coverage'},
           'hero_native_header_invalid')
    h = header['data']
    require(h['start_monotonic_ns'] == expected['start_monotonic_ns']
            and h['deadline_elapsed_ns'] == expected['duration_ns']
            and h['movement_physics_validated'] is False
            and h['teleport_causal_link_supported'] is False
            and h['coverage_source'] == 'ordinary_hero_skill_handlers'
            and h['resource_coverage'] == 'apply_hp_mp_change_only'
            and h['inventory_coverage'] == 'not_collected',
            'hero_native_header_invalid')
    _actor(h['initial'], initial=True)
    fields(terminal['data'], {'complete','event_count_before_terminal',
                              'qualification_claim','actor'},
           'hero_native_terminal_invalid')
    t = terminal['data']
    require(t['complete'] is True and t['qualification_claim'] is False
            and t['event_count_before_terminal'] == len(rows)-1,
            'hero_native_terminal_invalid')
    _actor(t['actor'])
    return rows


def _resource(data, initial):
    fields(data, {'transaction_id','hp_before','mp_before','hp_after','mp_after',
                  'max_hp','max_mp','route','native_stat_lock_held'})
    require(data['route'] == 'apply_hp_mp_change'
            and data['native_stat_lock_held'] is True
            and data['max_hp'] == initial['max_hp']
            and data['max_mp'] == initial['max_mp']
            and all(integer(data[key], 0, data['max_hp'])
                    for key in ('hp_before','hp_after'))
            and all(integer(data[key], 0, data['max_mp'])
                    for key in ('mp_before','mp_after')),
            'hero_resource_event_invalid')


def _damage(data):
    fields(data, {'transaction_id','skill_id','object_id','hp_before','hp_after',
                  'hp_loss','killed','route'})
    require(integer(data['skill_id'], 1, 2**31-1)
            and integer(data['object_id'], 1, 2**31-1)
            and integer(data['hp_before'], 0, 2**31-1)
            and integer(data['hp_after'], 0, data['hp_before'])
            and data['hp_loss'] == data['hp_before'] - data['hp_after']
            and type(data['hp_loss']) is int and type(data['killed']) is bool
            and data['killed'] is (data['hp_after'] == 0)
            and data['route'] == 'ordinary_monster_damage',
            'hero_damage_event_invalid')


def _summary(data, skill_levels):
    fields(data, SUMMARY)
    skill = data['skill_id']
    require(skill in skill_levels and data['skill_level'] == skill_levels[skill]
            and data['route'] in ('special_move_apply_to',
                                  'close_range_damage_handler')
            and type(data['committed']) is bool
            and data['map_id'] == 240040511
            and all(integer(data[key], 0, 30000) for key in
                    ('hp_before','hp_after','mp_before','mp_after'))
            and all(integer(data[key], 0, 10) for key in
                    ('combo_orbs_before','combo_orbs_after'))
            and type(data['resource_event_ids']) is list
            and type(data['damage_event_ids']) is list
            and all(event_id(item) for item in data['resource_event_ids']
                    + data['damage_event_ids'])
            and len(set(data['resource_event_ids'] + data['damage_event_ids']))
                    == len(data['resource_event_ids'] + data['damage_event_ids'])
            and data['endpoint_snapshots_atomic'] is False,
            'hero_skill_summary_invalid')
    _position(data['position_before'])
    _position(data['position_after'])
    _buffs(data['active_buffs_before'])
    _buffs(data['active_buffs_after'])
    _stats(data['stats_before'])
    _stats(data['stats_after'])


def _transactions(rows, skill_levels):
    by_id = {row['event_id']: row for row in rows}
    opened, closed = {}, []
    initial = rows[0]['data']['initial']
    for row in rows[1:-1]:
        kind, data = row['kind'], row['data']
        if kind == 'transaction_begin':
            fields(data, {'transaction_kind','subject_id','skill_level',
                          'parent_transaction_id'})
            require(data['transaction_kind'] == 'skill_apply'
                    and data['subject_id'] in skill_levels
                    and data['skill_level'] == skill_levels[data['subject_id']]
                    and data['parent_transaction_id'] == '' and not opened,
                    'hero_transaction_begin_invalid')
            opened[row['event_id']] = {'begin': row, 'resource': [],
                                       'damage': [], 'summary': []}
            continue
        transaction_id = data.get('transaction_id')
        require(event_id(transaction_id) and transaction_id in opened,
                'hero_transaction_reference_invalid')
        transaction = opened[transaction_id]
        if kind == 'resource_transaction':
            _resource(data, initial)
            transaction['resource'].append(row['event_id'])
        elif kind == 'monster_damage':
            _damage(data)
            require(data['skill_id'] == transaction['begin']['data']['subject_id'],
                    'hero_damage_skill_mismatch')
            transaction['damage'].append(row['event_id'])
        elif kind == 'skill_commit':
            _summary(data, skill_levels)
            require(data['skill_id'] == transaction['begin']['data']['subject_id']
                    and data['resource_event_ids'] == transaction['resource']
                    and data['damage_event_ids'] == transaction['damage']
                    and not transaction['summary'],
                    'hero_skill_children_mismatch')
            transaction['summary'].append(row['event_id'])
        elif kind == 'transaction_end':
            fields(data, {'transaction_id','committed'})
            require(type(data['committed']) is bool and len(transaction['summary']) == 1,
                    'hero_transaction_end_invalid')
            summary = by_id[transaction['summary'][0]]
            require(summary['data']['committed'] == data['committed']
                    and summary['sequence'] == row['sequence']-1,
                    'hero_transaction_close_mismatch')
            opened.pop(transaction_id)
            transaction['end'] = row
            transaction['summary_row'] = summary
            closed.append(transaction)
        else:
            raise InvalidEvidence('unsupported_hero_native_event')
    require(not opened, 'hero_transaction_unclosed')
    return closed, by_id


def _qualify(rows, contract):
    policy = contract['skill_toolkit']
    skill_levels = {skill['skill_id']: skill['level'] for skill in policy['skills']}
    transactions, by_id = _transactions(rows, skill_levels)
    accepted = []
    for transaction in transactions:
        summary = transaction['summary_row']
        data = summary['data']
        if data['committed']:
            accepted.append((summary, transaction))
    def has_mp_cost(data):
        return any(by_id[item]['data']['mp_after'] < by_id[item]['data']['mp_before']
                   for item in data['resource_event_ids'])
    combo_sequences = [row['sequence'] for row, _ in accepted
        if row['data']['skill_id'] == 1111002
        and row['data']['route'] == 'special_move_apply_to'
        and 1111002 in _buffs(row['data']['active_buffs_after'])
        and has_mp_cost(row['data'])]
    if not combo_sequences:
        raise NotQualified('hero_combo_cast_missing')
    combo_cast_sequence = min(combo_sequences)
    orb_build_sequences = sorted(row['sequence'] for row, _ in accepted
        if row['data']['skill_id'] == 1121008
        and row['data']['combo_orbs_after'] > row['data']['combo_orbs_before']
        and 1111002 in _buffs(row['data']['active_buffs_before'])
        and has_mp_cost(row['data'])
        and any(by_id[item]['data']['hp_loss'] > 0
                for item in row['data']['damage_event_ids'])
        and row['sequence'] > combo_cast_sequence)
    if not orb_build_sequences:
        raise NotQualified('hero_combo_build_missing')
    evidence = {}
    last_finisher_sequence = combo_cast_sequence
    selected = set(contract['qualification_skill_ids'])
    for skill in policy['skills']:
        if skill['skill_id'] not in selected:
            continue
        candidates = [(row, tx) for row, tx in accepted
                      if row['data']['skill_id'] == skill['skill_id']]
        if not candidates:
            raise NotQualified('hero_skill_effect_missing')
        chosen = None
        for row, transaction in candidates:
            data = row['data']
            buffs = _buffs(data['active_buffs_after'])
            resources = [by_id[item]['data'] for item in data['resource_event_ids']]
            if resources:
                require(resources[0]['hp_before'] == data['hp_before']
                        and resources[0]['mp_before'] == data['mp_before']
                        and resources[-1]['hp_after'] == data['hp_after']
                        and resources[-1]['mp_after'] == data['mp_after']
                        and all(left['hp_after'] == right['hp_before']
                                and left['mp_after'] == right['mp_before']
                                for left,right in zip(resources,resources[1:])),
                        'hero_resource_endpoints_mismatch')
            resource_cost = any(item['mp_after'] < item['mp_before']
                                for item in resources)
            if skill['route'] == 'buff':
                valid = (data['route'] == 'special_move_apply_to'
                         and skill['skill_id'] in buffs and resource_cost)
                if skill['skill_id'] == 1101004:
                    valid = valid and any(item['hp_after'] < item['hp_before']
                                          for item in resources)
                if skill['skill_id'] == 1121000:
                    valid = valid and (data['stats_after']['str'] > data['stats_before']['str']
                        or data['stats_after']['dex'] > data['stats_before']['dex'])
                if skill['skill_id'] == 1101006:
                    valid = valid and (data['stats_after']['weapon_attack']
                        > data['stats_before']['weapon_attack']
                        and data['stats_after']['weapon_defense']
                        < data['stats_before']['weapon_defense'])
            else:
                damages = [by_id[item]['data'] for item in data['damage_event_ids']]
                valid = (data['route'] == 'close_range_damage_handler'
                         and resource_cost and any(item['hp_loss'] > 0 for item in damages))
                if skill['skill_id'] in (1111005, 1111003):
                    valid = (valid and data['combo_orbs_before'] > 0
                             and data['combo_orbs_after'] < data['combo_orbs_before']
                             and 1111002 in _buffs(data['active_buffs_before'])
                             and any(last_finisher_sequence < sequence < row['sequence']
                                     for sequence in orb_build_sequences))
            if valid:
                chosen = (row, transaction)
                break
        if chosen is None:
            raise NotQualified('hero_skill_effect_missing')
        row, transaction = chosen
        evidence[str(skill['skill_id'])] = [transaction['begin']['event_id'],
            *row['data']['resource_event_ids'], *row['data']['damage_event_ids'],
            row['event_id'], transaction['end']['event_id']]
        if skill['skill_id'] in (1111005, 1111003):
            last_finisher_sequence = row['sequence']
    return evidence


def verify_events(raw_bytes, native_contract, expected):
    """Return a private receipt; the runtime must separately verify lifecycle."""
    receipt = {'schema_version':1,'protocol':VERIFIER_PROTOCOL,
        'native_protocol':HERO_TOOLKIT_PROTOCOL,'task_id':TASK_ID,
        'status':'invalid','reason_code':'invalid_contract','qualified_skills':[],
        'evidence':{},'publication_eligible':False,
        'runtime_lifecycle_verified':False}
    try:
        try:
            contract = validate_contract(native_contract)
        except (ValueError, TypeError):
            raise InvalidEvidence('invalid_contract') from None
        require(contract['id'] == HERO_TOOLKIT_PROTOCOL,
                'invalid_contract')
        receipt['evidence'] = {'contract_sha256': fingerprint(contract),
            'ledger_sha256': hashlib.sha256(raw_bytes).hexdigest()
                if type(raw_bytes) is bytes else None,
            'skill_event_ids': {}}
        rows = _parse(raw_bytes, contract, expected)
        skill_events = _qualify(rows, contract)
        receipt['evidence']['skill_event_ids'] = skill_events
        receipt['qualified_skills'] = sorted(int(skill) for skill in skill_events)
        receipt.update(status='success', reason_code='all_core_skills_qualified')
    except NotQualified as error:
        receipt.update(status='gameplay_failure', reason_code=str(error))
    except InvalidEvidence as error:
        receipt['reason_code'] = str(error)
    except (KeyError, TypeError, OverflowError, RecursionError):
        receipt['reason_code'] = 'hero_event_schema_mismatch'
    return receipt
