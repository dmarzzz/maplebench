"""Owned, read-only USE inventory receipts for opt-in native toolkits.

SQL reads require the existing native maintenance owner. Logical item/slot
identity survives ordinary saves, which regenerate inventory row IDs. Neither
an input acknowledgement nor inventory depletion establishes a hit or XP.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from full_client_skill_toolkit import NATIVE_PROTOCOL, fingerprint, validate_toolkit
from full_client_toolkit_fixture import table
from full_client_score import parse_json, same_json

MAX_BYTES = 32768
PHASES = ('before_login', 'after_logout', 'after_restore')
ARTIFACTS = frozenset('inventory_' + phase for phase in PHASES)


class InventoryError(ValueError):
    pass


def need(value, code):
    if not value:
        raise InventoryError('native_inventory_' + code)


def identity(value):
    return type(value) is int and 1 <= value < 2**31


def sql(character_id, account_id):
    need(identity(character_id) and identity(account_id), 'identity_invalid')
    return f"""SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('kind','character','character_id',c.id,'account_id',c.accountid,'job',c.job,'level',c.level,'account_logged_in',a.loggedin,
'transactional_tables',(SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('accounts','characters','inventoryitems') AND ENGINE='InnoDB'))
FROM characters c JOIN accounts a ON a.id=c.accountid WHERE c.id={character_id} AND c.accountid={account_id};
SELECT JSON_OBJECT('kind','use','inventoryitemid',inventoryitemid,'itemid',itemid,'position',position,'quantity',quantity)
FROM inventoryitems WHERE characterid={character_id} AND type=1 AND inventorytype=2 ORDER BY position,inventoryitemid LIMIT 257;
COMMIT;
""".encode()


def parse(raw, *, native, run_id, server_instance_id, phase, character_id, account_id,
          runtime_manifest_sha256, captured_at_ms):
    from full_client_native import validate_contract
    native = validate_contract(native)
    need(native['id'] == NATIVE_PROTOCOL, 'toolkit_owner_required')
    policy = native['skill_toolkit']
    need(isinstance(raw, bytes) and 0 < len(raw) < MAX_BYTES, 'output_bound')
    need(identity(character_id) and identity(account_id), 'identity_invalid')
    need(all(isinstance(v, str) and re.fullmatch('[a-f0-9]{32}', v)
             for v in (run_id, server_instance_id)) and phase in PHASES, 'request_invalid')
    need(isinstance(runtime_manifest_sha256, str) and re.fullmatch('[a-f0-9]{64}', runtime_manifest_sha256), 'pins_missing')
    need(type(captured_at_ms) is int and 0 < captured_at_ms < 2**53, 'clock_invalid')
    try:
        rows = [parse_json(line) for line in raw.splitlines() if line.strip()]
    except (ValueError, UnicodeError):
        raise InventoryError('native_inventory_json_invalid') from None
    need(1 <= len(rows) <= 257 and all(type(row) is dict for row in rows), 'row_bound')
    header, items = rows[0], rows[1:]
    need(set(header) == {'kind', 'character_id', 'account_id', 'job', 'level',
                         'account_logged_in', 'transactional_tables'} and header['kind'] == 'character'
         and all(type(header[k]) is int for k in header if k != 'kind'), 'header_invalid')
    need(header['character_id'] == character_id and header['account_id'] == account_id
         and header['job'] == policy['job'] and header['level'] == policy['level'], 'class_identity_changed')
    need(header['account_logged_in'] == 0 and header['transactional_tables'] == 3, 'offline_transaction_required')
    for row in items:
        need(set(row) == {'kind', 'inventoryitemid', 'itemid', 'position', 'quantity'}
             and row['kind'] == 'use' and all(type(row[k]) is int for k in row if k != 'kind'), 'item_row_invalid')
        need(identity(row['inventoryitemid']) and row['itemid'] // 1000000 == 2
             and 1 <= row['position'] <= 256 and 1 <= row['quantity'] <= 32767, 'item_range_invalid')
    need(len({r['position'] for r in items}) == len(items)
         and len({r['inventoryitemid'] for r in items}) == len(items), 'duplicate_slot_or_row')
    need(items == sorted(items, key=lambda r: (r['position'], r['inventoryitemid'])), 'order_invalid')
    return {'schema_version': 1, 'source': 'ordinary_offline_use_inventory',
        'native_acceptance_id': run_id, 'server_instance_id': server_instance_id,
        'protocol': NATIVE_PROTOCOL, 'class_id': native['class_id'], 'toolkit_sha256': fingerprint(policy),
        'model': None, 'api_calls': 0, 'phase': phase, 'captured_at_ms': captured_at_ms,
        'baseline_sha256': native['baseline_sha256'], 'runtime_manifest_sha256': runtime_manifest_sha256,
        'character': header, 'use_inventory': items, 'class_accepted': False}


def expected(native, baseline_sql, *, character_id, account_id):
    """Read exact frozen SQL rows; never execute them or expose account data."""
    from full_client_native import validate_contract
    native = validate_contract(native)
    need(native['id'] == NATIVE_PROTOCOL and identity(character_id) and identity(account_id), 'toolkit_owner_required')
    policy = validate_toolkit(native['skill_toolkit'])
    need(isinstance(baseline_sql, bytes) and len(baseline_sql) <= 64 * 1024**2
         and hashlib.sha256(baseline_sql).hexdigest() == native['baseline_sha256'], 'baseline_hash_changed')
    text = baseline_sql.decode('utf8')
    chars = table(text, 'characters')[1]; accounts = table(text, 'accounts')[1]
    need(len(chars) == len(accounts) == 1 and accounts[0]['loggedin'] == '0'
         and int(accounts[0]['id']) == account_id and int(chars[0]['id']) == character_id
         and int(chars[0]['accountid']) == account_id and int(chars[0]['job']) == policy['job']
         and int(chars[0]['level']) == policy['level'], 'baseline_identity_changed')
    rows = table(text, 'inventoryitems')[1]
    need(all(int(row['characterid']) == character_id for row in rows), 'baseline_other_character')
    items = [{'kind': 'use', **{key: int(row[key]) for key in ('inventoryitemid', 'itemid', 'position', 'quantity')}}
             for row in rows if row['inventorytype'] == '2' and row['type'] == '1']
    need(len(items) == sum(row['inventorytype'] == '2' for row in rows), 'baseline_inventory_type_changed')
    items.sort(key=lambda r: (r['position'], r['inventoryitemid']))
    need(1 <= len(items) <= 24 and len({r['position'] for r in items}) == len(items)
         and len({r['inventoryitemid'] for r in items}) == len(items)
         and all(identity(r['inventoryitemid']) and 1 <= r['position'] <= 24 for r in items), 'baseline_slots_invalid')
    potion = policy['resources']['potion']; ammo = policy['resources']['ammunition']
    allowed = {potion['item_id']} | ({ammo['item_id']} if ammo else set())
    need(all(r['itemid'] in allowed and r['quantity'] > 0 for r in items), 'baseline_unexpected_consumable')
    potions = [r for r in items if r['itemid'] == potion['item_id']]
    need(sum(r['quantity'] for r in potions) == potion['quantity']
         and all(r['quantity'] <= 100 for r in potions), 'baseline_potion_supply_changed')
    if ammo:
        stacks = [r for r in items if r['itemid'] == ammo['item_id']]
        need(len(stacks) == ammo['stacks'] and all(r['quantity'] == ammo['quantity_per_stack'] for r in stacks),
             'baseline_ammunition_supply_changed')
    return items


def check_snapshot(value, *, native, identity, phase, runtime_manifest_sha256):
    need(type(value) is dict, 'snapshot_required')
    raw = b'\n'.join(json.dumps(row).encode() for row in [value.get('character'), *value.get('use_inventory', [])])
    checked = parse(raw, native=native, run_id=identity['run_id'], server_instance_id=identity['server_instance_id'],
        phase=phase, character_id=identity['character_id'], account_id=identity['account_id'],
        runtime_manifest_sha256=runtime_manifest_sha256, captured_at_ms=value.get('captured_at_ms'))
    need(same_json(checked, value), 'snapshot_binding_changed')
    return checked


def verify_restored(value, *, native, baseline_sql, identity, runtime_manifest_sha256):
    """Cleanup proof remains independent of positive gameplay consumption."""
    check_snapshot(value, native=native, identity=identity, phase='after_restore', runtime_manifest_sha256=runtime_manifest_sha256)
    wanted = expected(native, baseline_sql, character_id=identity['character_id'], account_id=identity['account_id'])
    need(value['use_inventory'] == wanted, 'baseline_restore_changed')
    return {'inventory_restored': True, 'class_accepted': False}


def verify_triplet(before, after, restored, *, native, baseline_sql, identity, runtime_manifest_sha256, session, reset, final_db):
    for phase, value in zip(PHASES, (before, after, restored)):
        check_snapshot(value, native=native, identity=identity, phase=phase, runtime_manifest_sha256=runtime_manifest_sha256)
    wanted = expected(native, baseline_sql, character_id=identity['character_id'], account_id=identity['account_id'])
    need(before['use_inventory'] == wanted == restored['use_inventory'], 'baseline_restore_changed')
    need(reset['completed_at_ms'] <= before['captured_at_ms'] <= session['server_started_at_ms']
         and session['logged_out_at_ms'] <= after['captured_at_ms'] <= final_db['captured_at_ms']
         and after['captured_at_ms'] <= restored['captured_at_ms'], 'phase_timing_changed')
    starts = {(row['position'], row['itemid']): row['quantity'] for row in wanted}
    ends = {(row['position'], row['itemid']): row['quantity'] for row in after['use_inventory']}
    need(set(ends) <= set(starts) and all(qty <= starts[key] for key, qty in ends.items()), 'supply_increased_or_moved')
    policy = native['skill_toolkit']; potion = policy['resources']['potion']; ammo = policy['resources']['ammunition']
    consumed = lambda item: sum(qty - ends.get(key, 0) for key, qty in starts.items() if key[1] == item)
    potions = consumed(potion['item_id'])
    need(potions > 0, 'positive_potion_consumption_required')
    ammunition = consumed(ammo['item_id']) if ammo else None
    if native['class_id'] == 'night_lord':
        need(ammunition > 0, 'positive_star_consumption_required')
    # Soul Arrow makes zero physical arrow consumption valid; its native buff
    # effect is qualified separately. Counts never stand in for observed hits.
    return {'protocol': 'native-toolkit-resource-proof-v1', 'toolkit_sha256': fingerprint(policy),
        'potions_consumed': potions, 'ammunition_consumed': ammunition, 'inventory_restored': True,
        'native_attack_count': None, 'class_accepted': False, 'model_score': None}


def collect_owned(backend, phase):
    """Use existing held-lock authority for one bounded, consistent SQL read."""
    from full_client_native import validate_contract
    native = validate_contract(backend.native)
    need(native['id'] == NATIVE_PROTOCOL and phase in PHASES, 'toolkit_owner_required')
    need(native['baseline_sha256'] == backend.config['baseline']['sha256'], 'baseline_hash_changed')
    backend.safe_boundary()
    reset = backend.state.get('reset', {})
    if phase != 'after_restore':
        need(reset.get('run_id') == backend.run_id and reset.get('baseline_sha256') == native['baseline_sha256']
             and reset.get('verified') is True, 'restored_start_required')
    else:
        need('restore_baseline' in backend.state['intents'] and backend.stopped(backend.unit('cosmic')),
             'restore_inspection_required')
    if phase == 'after_logout':
        backend.disconnect()  # Existing read-only verifier of the ordinary saved logout.
    config = backend.config['mysql']; command = config.get('command'); database = config.get('database')
    need(command == ['/usr/bin/mysql'] and isinstance(database, str)
         and re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}', database), 'trusted_mysql_required')
    defaults = Path(config['defaults_file'])
    need(defaults.is_absolute() and defaults.resolve(strict=True) == defaults, 'private_defaults_required')
    info = defaults.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid in (0, os.geteuid())
         and stat.S_IMODE(info.st_mode) == 0o600, 'private_defaults_required')
    request = sql(config['character_id'], config['account_id'])
    backend.safe_boundary()
    original = backend.host.deadline; backend.host.deadline = min(original, time.monotonic() + 5)
    try:
        raw = backend.host.command([*command, '--defaults-extra-file=' + str(defaults), '--batch', '--raw',
            '--skip-column-names', '--connect-timeout=3', database], data=request, maximum=MAX_BYTES)
    finally:
        backend.host.deadline = original
    backend.safe_boundary()
    current = defaults.lstat()
    need(all(getattr(info, k) == getattr(current, k) for k in
             ('st_dev', 'st_ino', 'st_size', 'st_mode', 'st_uid', 'st_nlink', 'st_mtime_ns', 'st_ctime_ns')), 'defaults_changed')
    return parse(raw, native=native, run_id=backend.run_id, server_instance_id=backend.identity()['server_instance_id'],
        phase=phase, character_id=config['character_id'], account_id=config['account_id'],
        runtime_manifest_sha256=backend.config['runtime_manifest']['sha256'], captured_at_ms=backend.host.now())
