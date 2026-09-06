"""Score trusted persistence evidence from a full-client trial; never client XP.

The offline calculator validates the contract in FULL_CLIENT_TRIALS.md;
verify_trial_bundle additionally reads, hashes, and cross-checks the actual
artifacts. Neither interface collects evidence, resets a world, authenticates
the collector, or grants ranked publication. Missing evidence fails closed.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat


SOURCE = "cosmic_persisted_character"
HASH = re.compile(r"[0-9a-f]{64}\Z")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
JSON_LIMIT = 16 * 1024 * 1024


class EvidenceError(ValueError):
    """A field is missing, inconsistent, or not supported by this score contract."""


class EvidenceFormatError(EvidenceError):
    """The input cannot be parsed as JSON, rather than failing its evidence contract."""


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def object_field(parent, name):
    value = parent.get(name)
    require(isinstance(value, dict), f"{name}: expected an object")
    return value


def integer(parent, name, minimum=0, maximum=2**63 - 1):
    value = parent.get(name)
    require(type(value) is int and minimum <= value <= maximum,
            f"{name}: expected a bounded integer")
    return value


def digest_field(parent, name):
    value = parent.get(name)
    require(isinstance(value, str) and HASH.fullmatch(value) is not None,
            f"{name}: expected a SHA-256 digest")
    return value


def identifier(parent, name):
    value = parent.get(name)
    require(isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None,
            f"{name}: expected an identifier")
    return value


def character(parent):
    row = object_field(parent, "character")
    integer(row, "character_id", 1)
    integer(row, "account_id", 1)
    integer(row, "level", 1, 200)
    integer(row, "exp", 0, 2**31 - 1)
    integer(row, "hp", 0, 30000)
    return row


def score_trial(evidence):
    """Return net XP only after complete reset, session, and save attestations.

    Digests bind supplied records; they are not independent proof of server truth.
    The trusted collector must verify its files and runtime before calling this.
    """
    require(isinstance(evidence, dict), "evidence: expected an object")
    require(type(evidence.get("schema_version")) is int and evidence["schema_version"] == 1,
            "schema_version: only persistence evidence version 1 is supported")
    require(evidence.get("source") == SOURCE, "source: persisted server evidence is required")
    run_id = identifier(evidence, "run_id")
    scenario = digest_field(evidence, "scenario_fingerprint")
    baseline = object_field(evidence, "baseline")
    baseline_hash = digest_field(baseline, "sha256")
    baseline_character = character(baseline)
    require(baseline_character["hp"] > 0, "baseline: character must start alive")

    reset = object_field(evidence, "reset")
    require(reset.get("run_id") == run_id, "reset.run_id: must match this trial")
    require(digest_field(reset, "baseline_sha256") == baseline_hash,
            "reset.baseline_sha256: applied baseline does not match frozen baseline")
    for field in ("world_lock_held", "queue_lock_held", "server_stopped", "verified"):
        require(reset.get(field) is True, f"reset.{field}: positive operator evidence is required")
    reset_at = integer(reset, "completed_at_ms")

    snapshots = []
    for name in ("initial", "final"):
        snapshot = object_field(evidence, name)
        require(snapshot.get("source") == SOURCE, f"{name}.source: client telemetry is ineligible")
        require(snapshot.get("run_id") == run_id, f"{name}.run_id: must match this trial")
        require(integer(snapshot, "account_logged_in", 0, 2) == 0,
                f"{name}.account_logged_in: database read requires an offline account")
        integer(snapshot, "captured_at_ms")
        digest_field(snapshot, "evidence_sha256")
        row = character(snapshot)
        for field in ("character_id", "account_id"):
            require(row[field] == baseline_character[field], f"{name}.{field}: wrong character/account")
        snapshots.append(snapshot)
    initial, final = snapshots
    require(initial["character"] == baseline_character,
            "initial.character: restored row does not match frozen baseline")
    require(final["character"]["level"] == initial["character"]["level"],
            "final.level: level transitions require a pinned experience table and are unsupported")

    session = object_field(evidence, "session")
    require(session.get("run_id") == run_id, "session.run_id: must match this trial")
    instance = identifier(session, "server_instance_id")
    require(session.get("disconnect_kind") == "normal",
            "session.disconnect_kind: require ordinary client disconnect, not a forced server stop")
    require(session.get("world_lock_held_throughout") is True
            and session.get("queue_lock_held_throughout") is True,
            "session: both world locks must remain held through final collection")
    names = ("server_started_at_ms", "login_at_ms", "api_started_at_ms", "api_ended_at_ms",
             "controller_started_at_ms", "controller_ended_at_ms", "disconnect_requested_at_ms",
             "logged_out_at_ms")
    times = [integer(session, name) for name in names]
    ordered = [reset_at, initial["captured_at_ms"], *times, final["captured_at_ms"]]
    require(ordered == sorted(ordered), "timeline: reset, session, logout, and snapshots must be ordered")
    require(times[0] < times[1] < times[-1], "session: require a fresh server and a nonempty login-to-logout interval")
    require(times[2] < times[3] and times[4] < times[5],
            "session: API and controller intervals must be nonempty")

    save = object_field(session, "save")
    require(save.get("status") == "confirmed", "save.status: offline status alone cannot prove a successful save")
    require(save.get("run_id") == run_id and save.get("server_instance_id") == instance,
            "save: receipt must belong to this run and server instance")
    require(integer(save, "character_id", 1) == baseline_character["character_id"],
            "save.character_id: receipt belongs to another character")
    committed_at = integer(save, "committed_at_ms")
    require(times[-2] <= committed_at <= times[-1], "save.committed_at_ms: require a save during normal logout")
    digest_field(save, "evidence_sha256")
    digest_field(save, "logs_sha256")
    require(integer(save, "log_checked_from_ms") <= times[0]
            and integer(save, "log_checked_through_ms") >= final["captured_at_ms"],
            "save: log review must cover the whole server session through final collection")
    require(integer(save, "save_error_count") == 0, "save.save_error_count: save errors invalidate persistence evidence")

    try:
        canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, OverflowError) as error:
        raise EvidenceError("evidence: must contain only finite JSON data") from error
    # Death penalties remain negative; kills and gross XP cannot be inferred.
    net_xp = final["character"]["exp"] - initial["character"]["exp"]
    return {
        "schema_version": 1, "source": SOURCE, "run_id": run_id,
        "scenario_fingerprint": scenario, "baseline_sha256": baseline_hash,
        "evidence_sha256": hashlib.sha256(canonical).hexdigest(),
        "metrics": {"net_xp": net_xp},
        "level": initial["character"]["level"],
        "final_hp": final["character"]["hp"], "alive_at_logout": final["character"]["hp"] > 0,
        "timing": {"session_ms": times[-1] - times[1],
                   "api_ms": times[3] - times[2], "controller_ms": times[5] - times[4],
                   "settlement_ms": times[-1] - times[5]},
        "publication_eligible": False,
    }


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise EvidenceError("evidence: duplicate JSON keys are invalid")
        value[key] = item
    return value


def parse_json(raw):
    """Parse private JSON without ambiguous duplicate keys or nonfinite values."""
    def invalid_constant(_value):
        raise EvidenceError("evidence: nonfinite JSON numbers are invalid")
    try:
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=invalid_constant)
    except EvidenceError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise EvidenceFormatError("evidence: invalid JSON") from error


def same_json(left, right):
    """Compare JSON values without Python equating booleans and integer IDs."""
    try:
        return json.dumps(left, sort_keys=True, separators=(",", ":"), allow_nan=False) == json.dumps(
            right, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        raise EvidenceError("evidence: must contain only finite JSON data") from error


@contextmanager
def open_verified_artifact(artifact_root, reference, label, maximum=4 * 1024**3):
    """Keep a verified regular file descriptor open through its consumer.

    File verification establishes consistency, not authorship. The caller must
    trust the collector and protect the bundle from concurrent modification.
    """
    require(isinstance(reference, dict), f"artifacts.{label}: missing file reference")
    relative = reference.get("path")
    require(isinstance(relative, str) and 0 < len(relative) <= 500
            and not any(c in relative for c in ("\\", ":", "\x00")),
            f"artifacts.{label}: require a relative artifact path")
    parts = relative.split("/")
    require(all(part not in ("", ".", "..") for part in parts),
            f"artifacts.{label}: unsafe artifact path")
    expected = digest_field(reference, "sha256")
    try:
        root = Path(artifact_root)
        require(root.is_dir() and not root.is_symlink(), "artifacts: require a regular bundle directory")
        path = root
        for part in parts:
            path = path / part
            require(not path.is_symlink(), f"artifacts.{label}: symlinks are ineligible")
        require(path.resolve().is_relative_to(root.resolve()), f"artifacts.{label}: path escapes bundle")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
                    f"artifacts.{label}: require a nonempty bounded regular file")
            digest = hashlib.sha256()
            count = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                count += len(chunk)
                require(count <= maximum, f"artifacts.{label}: file exceeds size limit")
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            stamp = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
            require(stamp(before) == stamp(after),
                    f"artifacts.{label}: file changed during verification")
            require(digest.hexdigest() == expected, f"artifacts.{label}: SHA-256 does not match file bytes")
            stream.seek(0)
            yield stream
            require(stamp(before) == stamp(os.fstat(stream.fileno())),
                    f"artifacts.{label}: file changed while evidence was consumed")
            require(stamp(before) == stamp(path.stat(follow_symlinks=False)),
                    f"artifacts.{label}: artifact path changed while evidence was consumed")
    except (OSError, TypeError, ValueError) as error:
        if isinstance(error, EvidenceError):
            raise
        raise EvidenceError(f"artifacts.{label}: cannot read artifact") from error


def verified_artifact(artifact_root, reference, label, maximum=4 * 1024**3):
    """Verify a file reference; consumers of bytes must use the reader below."""
    with open_verified_artifact(artifact_root, reference, label, maximum):
        return Path(artifact_root) / reference["path"]


def read_artifact_bytes(artifact_root, reference, label, maximum=JSON_LIMIT):
    with open_verified_artifact(artifact_root, reference, label, maximum) as stream:
        raw = stream.read(maximum + 1)
        require(len(raw) <= maximum and hashlib.sha256(raw).hexdigest() == reference["sha256"],
                f"artifacts.{label}: consumed bytes differ from the declared hash")
    return raw


def read_json_artifact(artifact_root, artifacts, name):
    return parse_json(read_artifact_bytes(artifact_root, artifacts.get(name), name))


def _jsonl(raw):
    rows = [parse_json(line) for line in raw.splitlines() if line.strip()]
    require(rows and all(isinstance(row, dict) for row in rows), "evidence: require JSONL event objects")
    return rows


def verify_trial_bundle(evidence, artifact_root, artifacts):
    """Recompute a score after verifying supplied private trial artifacts.

    This verifies bytes and their cross-record consistency. Native commit
    receipts and collector phase records remain inside the trusted-host boundary;
    JSON and hashes cannot authenticate a dishonest collector's claims.
    """
    score = score_trial(evidence)
    require(isinstance(artifacts, dict), "artifacts: require the complete evidence bundle")
    keymap = evidence["baseline"].get("keymap")
    require(isinstance(keymap, list) and all(isinstance(row, list) and len(row) == 3
            and all(type(value) is int and 0 <= value <= 2**31 - 1 for value in row) for row in keymap),
            "baseline.keymap: require numeric frozen key bindings")
    require(len({row[0] for row in keymap}) == len(keymap), "baseline.keymap: duplicate keys are invalid")
    bindings = {row[0]: row[1:] for row in keymap}
    require(bindings.get(29) == [5, 52] and bindings.get(57) == [5, 53],
            "baseline.keymap: Ctrl Attack and Space Jump require action type 5")
    for name, expected in (("baseline", evidence["baseline"]["sha256"]),
                           ("scenario", evidence["scenario_fingerprint"])):
        verified_artifact(artifact_root, artifacts.get(name), name)
        require(artifacts[name]["sha256"] == expected, f"artifacts.{name}: frozen input hash mismatch")
    require(same_json(read_json_artifact(artifact_root, artifacts, "persistence"), evidence),
            "artifacts.persistence: parsed evidence differs from supplied record")
    for name in ("reset", "session"):
        require(same_json(read_json_artifact(artifact_root, artifacts, name), evidence[name]),
                f"artifacts.{name}: receipt differs from persistence evidence")
    for name in ("initial", "final"):
        raw = read_json_artifact(artifact_root, artifacts, name + "_db")
        snapshot = evidence[name]
        require(artifacts[name + "_db"]["sha256"] == snapshot["evidence_sha256"],
                f"artifacts.{name}_db: raw database export hash mismatch")
        require(same_json(raw, {key: value for key, value in snapshot.items() if key != "evidence_sha256"}),
                f"artifacts.{name}_db: database export differs from scored row")
        require(raw.get("schema_version") == 1 and type(raw.get("schema_version")) is int
                and same_json(raw.get("keymap"), keymap),
                f"artifacts.{name}_db: key bindings differ from the frozen baseline")

    session, save = evidence["session"], evidence["session"]["save"]
    native_log = read_artifact_bytes(artifact_root, artifacts.get("native_log"), "native_log")
    require(artifacts["native_log"]["sha256"] == digest_field(save, "native_logs_sha256"),
            "artifacts.native_log: native server log hash mismatch")
    require(native_log.count(b"MapleBench persistence journal initialized") == 1,
            "native log: require one fresh enabled persistence journal initialization")
    require(b"MapleBench persistence journal failed" not in native_log
            and b"Error saving chr" not in native_log,
            "native log: journal I/O or character save failure invalidates the trial")
    save_bytes = read_artifact_bytes(artifact_root, artifacts.get("save"), "save")
    require(artifacts["save"]["sha256"] == save["evidence_sha256"], "artifacts.save: commit journal hash mismatch")
    records = _jsonl(save_bytes)
    identity = {"run_id": evidence["run_id"], "server_instance_id": session["server_instance_id"],
                "character_id": evidence["baseline"]["character"]["character_id"],
                "account_id": evidence["baseline"]["character"]["account_id"]}
    for row in records:
        require(type(row.get("schema_version")) is int and row["schema_version"] == 1
                and row.get("source") == SOURCE, "save journal: unsupported native receipt")
        require(all(type(row.get(key)) is type(value) and row.get(key) == value for key, value in identity.items()),
                "save journal: receipt belongs to another run, instance, or character")
        require(row.get("kind") in ("save_committed", "save_failed"), "save journal: unknown receipt kind")
        require(row["kind"] != "save_failed", "save journal: native save failed")
        timestamp = integer(row, "committed_at_ms")
        require(session["server_started_at_ms"] <= timestamp <= evidence["final"]["captured_at_ms"],
                "save journal: commit lies outside this collected server session")
    require([row["committed_at_ms"] for row in records] == sorted(row["committed_at_ms"] for row in records),
            "save journal: commit timestamps must be ordered")
    selected = [row for row in records if row.get("committed_at_ms") == save["committed_at_ms"]]
    require(len(selected) == 1, "save journal: require exactly one matching native logout commit")

    log_bytes = read_artifact_bytes(artifact_root, artifacts.get("server_log"), "server_log")
    require(artifacts["server_log"]["sha256"] == save["logs_sha256"], "artifacts.server_log: phase journal hash mismatch")
    events = _jsonl(log_bytes)
    for row in events:
        require(row.get("run_id") == identity["run_id"]
                and row.get("server_instance_id") == identity["server_instance_id"],
                "phase journal: event belongs to another run or server instance")
        integer(row, "at_ms")
        require(row.get("event") not in ("save_error", "save_failed", "server_failed"),
                "phase journal: server or save failure invalidates the trial")
    require([row["at_ms"] for row in events] == sorted(row["at_ms"] for row in events),
            "phase journal: event timestamps must be ordered")
    expected_events = {"server_started": session["server_started_at_ms"], "login": session["login_at_ms"],
                       "logged_out": session["logged_out_at_ms"],
                       "collection_completed": evidence["final"]["captured_at_ms"]}
    for event, timestamp in expected_events.items():
        matches = [row for row in events if row.get("event") == event]
        require(len(matches) == 1 and matches[0]["at_ms"] == timestamp,
                f"phase journal: require one matching {event} event")
        if event != "server_started":
            require(all(type(matches[0].get(key)) is int and matches[0].get(key) == identity[key]
                        for key in ("character_id", "account_id")),
                    f"phase journal: wrong character/account for {event}")
    return score | {"artifacts_verified": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args(argv)
    try:
        require(args.evidence.stat().st_size <= JSON_LIMIT, "evidence: JSON exceeds size limit")
        evidence = parse_json(args.evidence.read_bytes())
        result = score_trial(evidence)
    except EvidenceFormatError:
        print(json.dumps({"scored": False, "reason": "evidence: unreadable or invalid JSON"}))
        return 2
    except EvidenceError as error:
        print(json.dumps({"scored": False, "reason": str(error)}))
        return 1
    except (OSError, UnicodeError, ValueError, RecursionError):
        # Never echo input content or filesystem errors from private evidence.
        print(json.dumps({"scored": False, "reason": "evidence: unreadable or invalid JSON"}))
        return 2
    print(json.dumps({"scored": True, "score": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
