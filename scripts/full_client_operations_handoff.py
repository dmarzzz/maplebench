"""Prepare a private normal-lifecycle handoff after a finite group settles.

The caller owns the outer operation gate, lifecycle serialization, and all
three existing world/queue/runner locks. This function acquires none, renews no
deadline, and never starts, stops, resets, logs in, or recovers anything. Its
mandatory expected snapshot is caller-selected persisted evidence; missing
post-recovery evidence requires explicit reconciliation by that caller.

An absent destination directory is atomically published with three create-only
files. Failed/uncertain publication is inspected, never automatically replayed.
Hidden staging directories contain only observations, not service intents.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
import stat
import tempfile

import full_client_lifecycle as native


def _private_directory(path, uid):
    path = native.absolute(str(path))
    info = path.lstat()
    native.require(stat.S_ISDIR(info.st_mode) and info.st_uid == uid
                   and stat.S_IMODE(info.st_mode) == 0o700, "handoff_private_directory_required")
    return info


def _held_locks(lifecycle):
    """Inspect actual descriptors and kernel owners, not a caller assertion."""
    host = lifecycle.host
    host.remaining()
    _private_directory(lifecycle.root, lifecycle.owner_uid)
    native.require(type(lifecycle.serial_fd) is int and lifecycle.serial_fd >= 0,
                   "handoff_serialization_required")
    path = native.absolute(str(lifecycle.root / ".lifecycle.lock"))
    info = os.fstat(lifecycle.serial_fd)
    native.require(stat.S_ISREG(info.st_mode) and info.st_uid == lifecycle.owner_uid
                   and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
                   and native.stable(info) == native.stable(path.lstat())
                   and host.lock_owners({"device": info.st_dev, "inode": info.st_ino}) == [os.getpid()],
                   "handoff_serialization_not_owned")
    native.require(len(lifecycle.world_fds) == 3 and len(set(lifecycle.world_fds)) == 3
                   and lifecycle.serial_fd not in lifecycle.world_fds, "handoff_world_locks_required")
    lifecycle.verify_world_locks()
    return {"owner_pid": os.getpid(), "serialization": {
                "path": str(path), "device": info.st_dev, "inode": info.st_ino},
            "world": copy.deepcopy(lifecycle.config["locks"])}


def _stopped(lifecycle):
    lifecycle.host.remaining()
    lifecycle.settings()
    result = {}
    for role in ("cosmic", "worker", "world"):
        unit = lifecycle.unit(role)
        invocation = unit.get("InvocationID")
        native.require(lifecycle.stopped(unit) and isinstance(invocation, str)
                       and native.ID.fullmatch(invocation), "handoff_stopped_instance_required")
        result[role] = invocation
    return result


def _browser(lifecycle, web):
    host, config = lifecycle.host, lifecycle.config
    host.remaining()
    status = host.browser(config["admin_socket"], web["pid"], config["services"]["web"]["uid"])
    session, bridge = status.get("session", {}), status.get("bridge", {})
    run = bridge.get("run") or {}
    ident = run.get("id")
    native.require(ident is None or isinstance(ident, str) and native.ID.fullmatch(ident),
                   "handoff_browser_run_invalid")
    native.require(session.get("state") == session.get("desiredPage") == "waiting"
                   and session.get("captureState") == "idle"
                   and all(session.get(key) is True for key in ("fresh", "pinned", "artifactsSettled"))
                   and run.get("status") in ("idle", "completed", "failed", "timed_out", "cancelled")
                   and run.get("workerActive") is False and run.get("leaseReleasePending") is False
                   and bridge.get("browserReleasePending") is False and bridge.get("quarantinedRuns") == [],
                   "handoff_browser_not_settled")
    # Store only the measured fields used by this admission; no raw browser
    # payload, environment, provider response, or account configuration.
    return {"run_id": ident, "status": run["status"], "state": session["state"],
            "desired_page": session["desiredPage"], "capture_state": session["captureState"],
            "fresh": session["fresh"], "pinned": session["pinned"],
            "artifacts_settled": session["artifactsSettled"], "worker_active": run["workerActive"],
            "lease_release_pending": run["leaseReleasePending"],
            "browser_release_pending": bridge["browserReleasePending"], "quarantined_count": len(bridge["quarantinedRuns"]),
            "observed_at_ms": host.now()}


def _snapshot(lifecycle, operation_id, expected):
    lifecycle.host.remaining()
    value = lifecycle.host.snapshot(lifecycle.config, operation_id)
    native.require(type(value.get("schema_version")) is int and value["schema_version"] == 1
                   and value.get("source") == "cosmic_persisted_character"
                   and type(value.get("account_logged_in")) is int and value["account_logged_in"] == 0
                   and native.lifecycle_same_json(value.get("character"), expected["character"])
                   and native.lifecycle_same_json(value.get("keymap"), expected["keymap"]),
                   "handoff_offline_snapshot_changed")
    return value


def _native_boundary(lifecycle, previous=None):
    lifecycle.host.remaining()
    config = lifecycle.config
    raw, info = native.read_file(config["native"]["path"], maximum=config["native"]["max_bytes"],
        uid=config["services"]["cosmic"]["uid"], private=True)
    native.require(info.st_nlink == 1, "handoff_native_log_alias")
    if previous is not None:
        native.require((info.st_dev, info.st_ino) == (previous["device"], previous["inode"]),
                       "handoff_native_generation_changed")
        # No generation inference is permitted while the server is stopped.
        native.native_offset(info, raw, previous, 0)
    return {"device": info.st_dev, "inode": info.st_ino, "bytes": len(raw), "sha256": native.digest(raw)}


def _write_new(directory, name, value):
    raw = native.encoded(value)
    native.require(len(raw) <= native.JSON_LIMIT, "handoff_output_limit")
    fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return native.digest(raw)


def prepare_handoff(lifecycle, directory, operation_id, attempts, *, expected_snapshot_ref):
    """Return handoff/preparation/offline_snapshot refs without invoking lifecycle.

    ``directory`` must be absent under an existing owner-private parent. The
    caller must continue holding the outer operation gate and the lifecycle's
    actual serial/world descriptors throughout this call. ``attempts`` is the
    complete inventory, including historical terminal attempts, with the exact
    existing lifecycle ``{id, journal, backend}`` shape. The expected snapshot
    reference is mandatory and must describe the caller's trusted final state.

    The supplied lifecycle object and its deadline remain unchanged. A local
    shallow copy only holds temporary handoff validation state. The caller must
    inspect an existing destination after a lost publication reply; it is never
    treated as authority to restart, retry, or overwrite anything.
    """
    native.require(isinstance(lifecycle, native.NormalLifecycle), "handoff_lifecycle_required")
    host, config, uid = lifecycle.host, lifecycle.config, lifecycle.owner_uid
    host.remaining()
    native.require(type(uid) is int and uid == os.geteuid(), "handoff_owner_mismatch")
    native.require(isinstance(operation_id, str) and native.ID.fullmatch(operation_id), "invalid_handoff_operation")
    native.require(isinstance(attempts, list) and 1 <= len(attempts) <= 4096, "invalid_attempt_inventory")
    destination = native.absolute(str(directory))
    parent_info = _private_directory(destination.parent, uid)
    native.require(not destination.is_relative_to(lifecycle.root)
                   and not destination.is_relative_to(Path(config["attempt_root"])), "handoff_inventory_destination_forbidden")
    native.require(not os.path.lexists(destination), "handoff_destination_exists")
    native.require(not os.path.lexists(lifecycle.root / operation_id), "handoff_operation_already_exists")
    locks = _held_locks(lifecycle)
    probe = copy.copy(lifecycle)
    probe.verify_files()
    expected_ref = copy.deepcopy(native.ref(expected_snapshot_ref))
    boot = host.boot()
    native.require(isinstance(boot, str) and native.BOOT.fullmatch(boot), "handoff_boot_invalid")
    stopped = _stopped(probe)
    web = probe.process_identity("web")
    browser = _browser(probe, web)
    request = {"schema_version": 1, "operation_id": operation_id, "config_sha256": lifecycle.config_ref["sha256"],
               "boot_id": boot, "stopped_invocations": stopped, "web_instance": web,
               "browser_run_id": browser["run_id"], "attempts": copy.deepcopy(attempts), "offline_snapshot": expected_ref}
    probe.request = request
    # Reuse the exact terminal-clean, complete-inventory and expected-snapshot
    # admission. This performs no lifecycle action and acquires no lock.
    probe.verify_handoff_evidence()
    initial_native = _native_boundary(probe)
    first_snapshot = _snapshot(probe, operation_id, probe.expected_snapshot)
    probe.quiet()
    probe.capacity()

    # Pinning may be substantial, so follow it with fresh current observations
    # before publishing. The outer deadline is never reset here.
    probe.verify_files()
    probe.verify_handoff_evidence()
    final_snapshot = _snapshot(probe, operation_id, probe.expected_snapshot)
    native.require(native.lifecycle_same_json(first_snapshot["character"], final_snapshot["character"])
                   and native.lifecycle_same_json(first_snapshot["keymap"], final_snapshot["keymap"]),
                   "handoff_snapshot_changed_during_preparation")
    native.require(_stopped(probe) == stopped and probe.process_identity("web") == web
                   and host.boot() == boot and _held_locks(lifecycle) == locks, "handoff_identity_changed")
    final_native = _native_boundary(probe, initial_native)
    browser = _browser(probe, web)
    native.require(browser["run_id"] == request["browser_run_id"], "handoff_browser_run_changed")
    probe.quiet()
    available = probe.capacity()

    snapshot_ref = {"path": str(destination / "offline-snapshot.json"), "sha256": native.digest(native.encoded(final_snapshot))}
    handoff = dict(request, offline_snapshot=snapshot_ref)
    handoff_ref = {"path": str(destination / "handoff.json"), "sha256": native.digest(native.encoded(handoff))}
    preparation = {"schema_version": 1, "kind": "full_client_operations_handoff", "operation_id": operation_id,
        "config": copy.deepcopy(lifecycle.config_ref), "expected_snapshot": expected_ref,
        "handoff": handoff_ref, "offline_snapshot": snapshot_ref, "prepared_at_ms": host.now(),
        "observation": {"boot_id": boot, "stopped_invocations": stopped, "web_instance": web,
                        "browser": browser, "locks": locks, "available_bytes": available,
                        "native_boundary_before": initial_native, "native_boundary": final_native},
        "lifecycle_invoked": False, "services_changed": False, "database_changed": False,
        "automatic_retry": False}
    host.remaining()
    staging = Path(tempfile.mkdtemp(prefix=".operations-handoff-" + operation_id + "-", dir=destination.parent))
    # Each fixed name is new in this private staging directory. Preserve a
    # failed staging directory for inspection; never reuse partial files.
    for name, value in (("offline-snapshot.json", final_snapshot), ("handoff.json", handoff),
                        ("preparation.json", preparation)):
        host.remaining()
        _write_new(staging, name, value)
    native.sync_directory(staging)
    native.require(native.stable(_private_directory(destination.parent, uid))[:5] == native.stable(parent_info)[:5],
                   "handoff_parent_changed")
    _held_locks(lifecycle)
    probe.verify_files()
    probe.verify_handoff_evidence()
    probe.quiet()
    native.require(_stopped(probe) == stopped and probe.process_identity("web") == web
                   and host.boot() == boot and _native_boundary(probe, final_native) == final_native,
                   "handoff_changed_before_publication")
    probe.capacity()
    host.remaining()
    native.publish_attempt(staging, destination)  # Atomic no-replace, parent fsync.
    return {"handoff": handoff_ref,
            "preparation": {"path": str(destination / "preparation.json"), "sha256": native.digest(native.encoded(preparation))},
            "offline_snapshot": snapshot_ref}
