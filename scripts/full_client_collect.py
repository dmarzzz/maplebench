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


def snapshot_sql(character_id, account_id):
    for value in (character_id, account_id):
        if type(value) is not int or not 1 <= value <= 2**31 - 1:
            raise ValueError("invalid_identity")
    # One consistent read includes account status and the entire score row. No
    # account names, login details, character names, or arbitrary SQL are exposed.
    return f"""SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('character', JSON_OBJECT('character_id', c.id, 'account_id', c.accountid,
'level', c.level, 'exp', c.exp, 'hp', c.hp, 'mp', c.mp, 'max_hp', c.maxhp, 'max_mp', c.maxmp,
'map_id', c.map, 'spawn_point', c.spawnpoint, 'job', c.job), 'account_logged_in', a.loggedin)
FROM characters c JOIN accounts a ON a.id=c.accountid
WHERE c.id={character_id} AND c.accountid={account_id};
SELECT JSON_ARRAY(`key`, `type`, `action`) FROM keymap
WHERE characterid={character_id} AND `key` IN (29,57,85) ORDER BY `key`;
COMMIT;
"""


def parse_snapshot(raw, *, run_id, captured_at_ms, character_id, account_id):
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
    if (any(not isinstance(binding, list) or len(binding) != 3 or
            any(type(x) is not int for x in binding) for binding in bindings)
            or len({binding[0] for binding in bindings}) != len(bindings)):
        raise ValueError("invalid_keymap")
    keymap = {binding[0]: binding[1:] for binding in bindings}
    if keymap.get(29) != [5, 52] or keymap.get(57) != [5, 53]:
        raise ValueError("gameplay_keymap_invalid")
    if 85 in keymap and keymap[85] != [5, 52]:
        raise ValueError("gameplay_keymap_invalid")
    return {"schema_version": 1, "source": "cosmic_persisted_character", "run_id": run_id,
            "captured_at_ms": captured_at_ms, "account_logged_in": 0,
            "character": character, "keymap": bindings}


def collect(*, mysql_command, database, defaults_file, run_id, character_id, account_id, timeout=10):
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
                            input=snapshot_sql(character_id, account_id), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=timeout, check=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                                           "LC_ALL": "C"})
    return parse_snapshot(result.stdout, run_id=run_id, captured_at_ms=time.time_ns() // 1_000_000,
                          character_id=character_id, account_id=account_id)


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
                           account_id=config["account_id"], run_id=args.run_id)
        digest = save_snapshot(args.output, snapshot)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"collected": False, "reason": "offline_snapshot_failed"}))
        return 1
    print(json.dumps({"collected": True, "sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
