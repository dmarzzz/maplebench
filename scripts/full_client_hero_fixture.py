#!/usr/bin/env python3
"""Expand a private accepted Hero-180 SQL baseline without touching a DB.

Only the `skills` and `keymap` INSERT bodies are rewritten.  Account fields,
character state, equipment, inventory, schema, and every other byte remain
unchanged.  Output is a private candidate; this script cannot qualify a live
fixture or prove that any skill works in the native client.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from full_client_hero_toolkit import (expected_keymap, expected_skills,
                                      fingerprint, profile, toolkit)

MAX_SQL = 64 * 1024 * 1024
TOKEN = re.compile(r"NULL|-?[0-9]+|'(?:\\.|[^'\\])*'")


def require(value, code):
    if not value:
        raise ValueError(code)


def table(text, name):
    ddl = re.findall(r'^CREATE TABLE `'+name+r'` \(\n(.*?)^\) ENGINE=', text,
                     re.M | re.S)
    inserts = list(re.finditer(r'^INSERT INTO `'+name+r'` VALUES (.*);$', text,
                               re.M))
    require(len(ddl) == len(inserts) == 1, 'one_table_insert_required')
    columns = re.findall(r'^  `([A-Za-z0-9_]+)` ', ddl[0], re.M)
    require(columns and len(columns) == len(set(columns)),
            'unique_table_columns_required')
    value = inserts[0][1]
    rows, at = [], 0
    while at < len(value):
        require(value[at] == '(', 'row_open_required')
        at += 1
        tokens = []
        while True:
            match = TOKEN.match(value, at)
            require(match is not None, 'unsupported_sql_literal')
            tokens.append(match[0])
            at = match.end()
            require(at < len(value) and value[at] in ',)',
                    'literal_delimiter_required')
            delimiter = value[at]
            at += 1
            if delimiter == ')':
                break
        require(len(tokens) == len(columns), 'table_columns_changed')
        rows.append(dict(zip(columns, tokens)))
        require(len(rows) <= 10000, 'fixture_row_limit')
        if at < len(value):
            require(value[at] == ',', 'row_delimiter_required')
            at += 1
    require(rows, 'nonempty_fixture_table_required')
    return columns, rows, inserts[0].span(1)


def replace(text, name, rows):
    columns, _, (start, end) = table(text, name)
    require(rows and all(set(row) == set(columns) for row in rows),
            'fixture_columns_changed')
    values = ','.join('('+','.join(str(row[column]) for column in columns)+')'
                      for row in rows)
    return text[:start] + values + text[end:]


def transform(raw):
    """Return `(sql_bytes, expected)` for the exact expanded Hero profile."""
    require(type(raw) is bytes and 0 < len(raw) <= MAX_SQL,
            'fixture_sql_limit')
    try:
        text = raw.decode('utf8')
    except UnicodeError as error:
        raise ValueError('fixture_utf8_required') from error
    names = ('accounts', 'characters', 'skills', 'keymap', 'inventoryitems')
    parsed = {name: table(text, name) for name in names}
    accounts = parsed['accounts'][1]
    characters = parsed['characters'][1]
    require(len(accounts) == len(characters) == 1
            and set(('id', 'loggedin')) <= set(accounts[0])
            and accounts[0]['loggedin'] == '0', 'single_offline_fixture_required')
    character = characters[0]
    required_character = {'id', 'accountid', 'job', 'level', 'map'}
    require(required_character <= set(character)
            and character['accountid'] == accounts[0]['id']
            and character['id'].isdigit()
            and character['job'] == '112' and character['level'] == '180'
            and character['map'] == '240040511',
            'accepted_hero_180_baseline_required')
    character_id = character['id']
    for name in ('skills', 'keymap', 'inventoryitems'):
        require('characterid' in parsed[name][0]
                and all(row['characterid'] == character_id
                        for row in parsed[name][1]),
                'other_character_rows_refused')
    equipment = [row for row in parsed['inventoryitems'][1]
                 if row.get('inventorytype') == '-1'
                 and row.get('position') == '-11']
    require(len(equipment) == 1 and equipment[0].get('itemid', '').isdigit()
            and int(equipment[0]['itemid']) // 10000 == 140,
            'two_handed_sword_fixture_required')

    skill_columns, old_skills, _ = parsed['skills']
    require(set(skill_columns) == {'id', 'skillid', 'characterid', 'skilllevel',
                                   'masterlevel', 'expiration'},
            'skill_schema_changed')
    wanted_skills = expected_skills(toolkit())
    existing_skills = sorted([[int(row['skillid']), int(row['skilllevel'])]
                              for row in old_skills])
    if existing_skills == wanted_skills:
        skills = copy.deepcopy(old_skills)
    else:
        start = max(int(row['id']) for row in old_skills) + 1
        skills = []
        for index, (skill_id, level) in enumerate(wanted_skills):
            values = {'id': start + index, 'skillid': skill_id,
                      'characterid': int(character_id), 'skilllevel': level,
                      'masterlevel': level if skill_id // 10000 == 112 else 0,
                      'expiration': -1}
            skills.append({column: str(values[column]) for column in skill_columns})

    key_columns, old_keys, _ = parsed['keymap']
    require(set(key_columns) == {'id', 'characterid', 'key', 'type', 'action'},
            'keymap_schema_changed')
    selected = expected_keymap(toolkit())
    selected_codes = {row[0] for row in selected}
    existing_selected = sorted([[int(row['key']), int(row['type']),
                                 int(row['action'])] for row in old_keys
                                if int(row['key']) in selected_codes])
    if existing_selected == selected:
        keys = copy.deepcopy(old_keys)
    else:
        keys = [copy.deepcopy(row) for row in old_keys
                if int(row['key']) not in selected_codes]
        start = max(int(row['id']) for row in old_keys) + 1
        for index, (key, kind, action) in enumerate(selected):
            values = {'id': start + index, 'characterid': int(character_id),
                      'key': key, 'type': kind, 'action': action}
            keys.append({column: str(values[column]) for column in key_columns})
    require(len({row['key'] for row in keys}) == len(keys),
            'duplicate_fixture_key')

    transformed = replace(replace(text, 'skills', skills), 'keymap', keys)
    # Mask the two approved INSERT bodies and compare all other bytes exactly.
    before, after = text, transformed
    for name in ('skills', 'keymap'):
        for which in ('before', 'after'):
            value = before if which == 'before' else after
            _, _, (left, right) = table(value, name)
            value = value[:left] + '(0)' + value[right:]
            if which == 'before':
                before = value
            else:
                after = value
    require(before == after, 'unrelated_fixture_sql_changed')
    policy = toolkit()
    expected = {
        'schema_version': 1,
        'status': 'offline_candidate_not_live_qualified',
        'profile': profile(policy),
        'toolkit_sha256': fingerprint(policy),
        'job': 112,
        'level': 180,
        'map_id': 240040511,
        'skills': expected_skills(policy),
        'selected_keymap': selected,
        'preserved_key_count': len(keys) - len(selected),
        'equipment_replaced': False,
        'api_calls': 0,
        'database_connections': 0,
        'runtime_mutations': 0,
    }
    return transformed.encode(), expected


def read_private(path, digest):
    require(isinstance(digest, str)
            and re.fullmatch('[a-f0-9]{64}', digest), 'input_hash_required')
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path,
            'canonical_input_required')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and not info.st_mode & 0o077,
                'private_input_required')
        raw = source.read(MAX_SQL + 1)
    require(len(raw) <= MAX_SQL and hashlib.sha256(raw).hexdigest() == digest,
            'input_hash_changed')
    return raw


def write_private(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw = read_private(args.source, args.source_sha256)
        sql, expected = transform(raw)
        output = args.output_directory
        require(output.is_absolute() and output.parent.resolve(strict=True) == output.parent
                and not os.path.lexists(output), 'new_private_output_required')
        output.mkdir(mode=0o700)
        expected_raw = (json.dumps(expected, sort_keys=True, separators=(',', ':'),
                                   allow_nan=False)+'\n').encode()
        refs = {'database.sql': write_private(output/'database.sql', sql),
                'expected-fixture.json': write_private(output/'expected-fixture.json',
                                                       expected_raw)}
        descriptor = os.open(output, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        print(json.dumps({'status': 'offline_hero_fixture_preparation_failed'}))
        return 1
    print(json.dumps({'status': expected['status'], 'artifacts': refs,
                      'runtime_mutations': 0}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
