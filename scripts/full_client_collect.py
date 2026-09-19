#!/usr/bin/env python3
"""Export a minimal offline character snapshot through a read-only DB transaction.

This collector cannot restore a database or certify a completed trial. Its output
is one private evidence artifact; the runner still needs reset, session and native
save receipts. Credentials are read by mysql from a private defaults file, never
passed in argv, printed, or included in evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
DATABASE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")


def snapshot_sql(character_id, account_id, *, skill_toolkit=None):
    for value in (character_id, account_id):
        if type(value) is not int or not 1 <= value <= 2**31 - 1:
            raise ValueError("invalid_identity")
    # One consistent read includes account status and the entire score row. No
    # account names, login details, character names, or arbitrary SQL are exposed.
    key_ids = [29,57,85]
    skill_query = ''
    if skill_toolkit is not None:
        from full_client_hero_toolkit import expected_keymap, expected_skills
        key_ids = sorted(set(key_ids) | {row[0] for row in expected_keymap(skill_toolkit)})
        skill_ids = ','.join(str(row[0]) for row in expected_skills(skill_toolkit))
        skill_query = ("SELECT JSON_OBJECT('learned_skill', JSON_ARRAY(skillid, skilllevel)) FROM skills\n"
                       f"WHERE characterid={character_id} AND skillid IN ({skill_ids}) ORDER BY skillid;\n")
    key_filter = ','.join(str(key) for key in key_ids)
    return f"""SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('character', JSON_OBJECT('character_id', c.id, 'account_id', c.accountid,
'level', c.level, 'exp', c.exp, 'hp', c.hp, 'mp', c.mp, 'max_hp', c.maxhp, 'max_mp', c.maxmp,
'map_id', c.map, 'spawn_point', c.spawnpoint, 'job', c.job), 'account_logged_in', a.loggedin)
FROM characters c JOIN accounts a ON a.id=c.accountid
WHERE c.id={character_id} AND c.accountid={account_id};
SELECT JSON_ARRAY(`key`, `type`, `action`) FROM keymap
WHERE characterid={character_id} AND `key` IN ({key_filter}) ORDER BY `key`;
{skill_query}COMMIT;
"""


def parse_snapshot(raw, *, run_id, captured_at_ms, character_id, account_id, skill_toolkit=None):
    if not isinstance(run_id, str) or not IDENTIFIER.fullmatch(run_id):
        raise ValueError("invalid_run_id")
    if len(raw) > 16384:
        raise ValueError("oversized_database_response")
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if not rows or not isinstance(rows[0], dict):
        raise ValueError("character_not_found")
    row = rows[0]
    character = row.get("character", {})
    if not isinstance(character, dict) or any(type(value) is not int for value in character.values()):
        raise ValueError("invalid_character_row")
    required = {"character_id", "account_id", "level", "exp", "hp", "mp", "max_hp", "max_mp", "map_id", "spawn_point", "job"}
    if set(character) != required or character["character_id"] != character_id or character["account_id"] != account_id:
        raise ValueError("character_identity_mismatch")
    if type(row.get("account_logged_in")) is not int or row["account_logged_in"] != 0:
        raise ValueError("account_still_online")
    if not 1 <= character["level"] <= 200 or not 0 <= character["exp"] <= 2**31 - 1:
        raise ValueError("unsupported_progression")
    if any(not 0 <= character[key] <= 30000 for key in ("hp", "mp", "max_hp", "max_mp")):
        raise ValueError("invalid_vitals")
    bindings = rows[1:]
    skills = None
    if skill_toolkit is not None:
        from full_client_hero_toolkit import validate_toolkit
        skill_toolkit = validate_toolkit(skill_toolkit)
        bindings=[];skills=[];reading_skills=False
        for value in rows[1:]:
            if isinstance(value, dict) and set(value)=={'learned_skill'}:
                reading_skills=True;skills.append(value['learned_skill'])
            elif isinstance(value, list) and not reading_skills:
                bindings.append(value)
            else:
                raise ValueError('invalid_toolkit_snapshot')
    if (any(not isinstance(binding, list) or len(binding) != 3 or
            any(type(x) is not int for x in binding) for binding in bindings)
            or len({binding[0] for binding in bindings}) != len(bindings)):
        raise ValueError("invalid_keymap")
    keymap = {binding[0]: binding[1:] for binding in bindings}
    if keymap.get(29) != [5, 52] or keymap.get(57) != [5, 53]:
        raise ValueError("gameplay_keymap_invalid")
    if 85 in keymap and keymap[85] != [5, 52]:
        raise ValueError("gameplay_keymap_invalid")
    snapshot = {"schema_version": 1, "source": "cosmic_persisted_character", "run_id": run_id,
            "captured_at_ms": captured_at_ms, "account_logged_in": 0,
            "character": character, "keymap": bindings}
    if skill_toolkit is not None:
        snapshot.update(skill_toolkit_id=skill_toolkit['id'], learned_skills=skills)
        validate_toolkit_snapshot(snapshot, skill_toolkit)
    return snapshot


def validate_toolkit_snapshot(snapshot, skill_toolkit):
    """Bind every declared control/learned level to a read-only native DB row."""
    from full_client_hero_toolkit import expected_keymap, expected_skills, validate_toolkit
    skill_toolkit = validate_toolkit(skill_toolkit)
    keymap = snapshot.get('keymap')
    if (not isinstance(keymap, list) or any(not isinstance(row, list) or len(row)!=3
            or any(type(n) is not int for n in row) for row in keymap)
            or len({row[0] for row in keymap})!=len(keymap)):
        raise ValueError('invalid_toolkit_keymap')
    expected = {row[0]:row[1:] for row in expected_keymap(skill_toolkit)} | {29:[5,52],57:[5,53]}
    actual = {row[0]:row[1:] for row in keymap}
    if (not set(expected)<=set(actual)<=set(expected)|{85}
            or any(actual.get(key)!=binding for key,binding in expected.items())
            or 85 in actual and actual[85]!=[5,52]):
        raise ValueError('toolkit_keymap_mismatch')
    skills = snapshot.get('learned_skills')
    if (snapshot.get('skill_toolkit_id')!=skill_toolkit['id']
            or snapshot.get('character',{}).get('job')!=skill_toolkit['job']
            or not isinstance(skills,list) or any(not isinstance(row,list) or len(row)!=2
                or any(type(n) is not int for n in row) for row in skills)
            or skills!=expected_skills(skill_toolkit)):
        raise ValueError('toolkit_learned_skills_mismatch')
    return snapshot


def collect(*, mysql_command, database, defaults_file, run_id, character_id, account_id, timeout=10,
            skill_toolkit=None):
    if not isinstance(database, str) or not DATABASE.fullmatch(database):
        raise ValueError("invalid_database")
    if not isinstance(mysql_command, list) or not mysql_command or any(
            not isinstance(arg, str) or not arg or '\x00' in arg for arg in mysql_command):
        raise ValueError("invalid_mysql_command")
    command = mysql_command
    if len(command) == 3 and Path(command[0]).name == 'sudo' and command[1] == '-n':
        command = command[2:]
    if len(command) != 1 or Path(command[0]).name not in {'mysql', 'mariadb'}:
        raise ValueError("mysql_command_must_not_contain_credentials_or_extra_arguments")
    if not isinstance(run_id, str) or not IDENTIFIER.fullmatch(run_id):
        raise ValueError("invalid_run_id")
    # Only a trusted host config supplies this command; evaluated programs never
    # receive this collector or its defaults file. Reject a defaults symlink or a
    # file readable by other accounts before invoking mysql.
    credentials = []
    if defaults_file is not None:
        path = Path(defaults_file)
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError("mysql_defaults_not_private")
        credentials = ["--defaults-extra-file=" + str(path.resolve())]
    result = subprocess.run([*mysql_command, *credentials, "--batch", "--raw", "--skip-column-names",
                             "--connect-timeout=5", database],
                            input=snapshot_sql(character_id, account_id,skill_toolkit=skill_toolkit), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=timeout, check=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                                           "LC_ALL": "C"})
    return parse_snapshot(result.stdout, run_id=run_id, captured_at_ms=time.time_ns() // 1_000_000,
                          character_id=character_id, account_id=account_id,skill_toolkit=skill_toolkit)


def save_snapshot(path, snapshot):
    """Create once, fsync the private artifact, and return its byte hash."""
    data = (json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    path = Path(path)
    # No mkdir or replacement: the trusted runner owns the existing attempt dir.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return hashlib.sha256(data).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Private host configuration")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if (args.config.is_symlink() or args.config.stat().st_size > 65536
                or args.config.stat().st_mode & 0o077):
            raise ValueError("private_config_required")
        config = json.loads(args.config.read_text())
        snapshot = collect(mysql_command=config["mysql_command"], database=config["database"],
                           defaults_file=config.get("defaults_file"), character_id=config["character_id"],
                           account_id=config["account_id"], run_id=args.run_id,
                           skill_toolkit=config.get('skill_toolkit'))
        digest = save_snapshot(args.output, snapshot)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"collected": False, "reason": "offline_snapshot_failed"}))
        return 1
    print(json.dumps({"collected": True, "sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
