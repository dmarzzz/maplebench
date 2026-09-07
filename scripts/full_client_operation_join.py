"""Verified Linux parent-to-trial admission; not a production entrypoint.

Parent: with prepare_join(local_active_lease, existing_dispatch_directory,
                         binding, parent_launch=launch) as dispatch:
  Popen(exact_trial_argv, pass_fds=dispatch['pass_fds'], close_fds=True)
Child: with joined(attempt_root, gate_pin, envelope_ref, inherited_fd,
                   expected_binding_from_actual_cli) as admission:
  # Only now may the caller acquire world locks or invoke the trial backend.

prepare_join yields {envelope: {path,sha256}, pass_fds: (one_fd,)}. joined
yields {entry: ref, envelope: ref, claim: ref, binding: dict}; it owns and closes
the supplied descriptor. Neither context completes the outer operation claim.
Never forward this FD in the bridge SCM_RIGHTS payload. No FD-only bypass exists.

Binding exact keys: action ('trial_run'/'trial_recover'), attempt_id (32 hex),
request (private JSON ref, null for recovery), adapter_config (private JSON ref),
state_root, world_lock, queue_lock (canonical existing paths), plan (private
JSON ref or null). state_root is the gate's attempt_root. launch exact keys:
executable, script (protected canonical file refs), argv (exact interpreter,
script, arguments). Parent must be the actual direct parent, with matching UID,
PID/start ticks/boot, declared argv and executable. No interpreter flags allowed.

Dispatch directory is derived from the immutable claim authority reference:
<authority parent>/.operation-dispatch/<operation_id>. The trusted parent creates
it privately first. Deterministic <action>-<attempt_id>.json and .entered.json
names are create-only. A mismatch before entry leaves that dispatch unconsumed;
an uncertain entry publication permanently requires exact reconciliation.

Kernel proof: exclusive FLOCK owner/device/inode in both actual fdinfo files,
before and after reasserting EX|NB on the inherited description, while an
independent open must fail EX|NB. On Linux flock is per open-file description:
https://man7.org/linux/man-pages/man2/flock.2.html . POSIX/OFD or missing kernel
evidence is refused. No kcmp/ptrace privilege fallback is used.

Default owner is root; offline fixtures may explicitly use owner_uid==geteuid().
Reads are bounded by the gate budget and per-file limits. Host ancestors and the
caller source/dependency closure remain trusted; this module is not a sandbox,
authority-policy validator, service restorer or substitute for runner leases.
Parent death after entry leaves the outer claim pending and the inherited flock
held until this child exits; later cleanup must reconcile, never replay dispatch.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
import sys

import full_client_operation_gate as gate

__all__ = ["JoinError", "prepare_join", "joined"]
BOOT = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
FLOCK = re.compile(r"lock:\s+\d+:\s+FLOCK\s+ADVISORY\s+WRITE\s+(\d+)\s+"
                   r"([0-9a-fA-F]+):([0-9a-fA-F]+):(\d+)\s+0\s+EOF\Z")
MAX_FDS = 256
MAX_SOURCE = 32 * 1024 * 1024


class JoinError(gate.GateError):
    """Fixed, credential-free protocol failure code."""


def need(value, code):
    if not value:
        raise JoinError(code)


def _same(left, right):
    """JSON identity must not equate booleans with integer pins."""
    return gate.encoded(left) == gate.encoded(right)


def _platform(uid):
    need(sys.platform == "linux", "join_linux_required")
    need(gate.integer(uid) and uid == os.geteuid(), "join_owner_mismatch")


def _kernel(path, maximum, budget):
    budget.check()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        raw = bytearray()
        while len(raw) <= maximum:
            budget.check()
            block = os.read(fd, min(65536, maximum + 1 - len(raw)))
            if not block:
                break
            raw.extend(block)
        need(len(raw) <= maximum, "join_kernel_read_limit")
        budget.reserve(len(raw))
        return bytes(raw)
    finally:
        os.close(fd)


def _protected(ref, uid, budget):
    gate.reference(ref)
    path = gate.canonical(ref["path"])
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_uid in {0, uid} and before.st_nlink == 1
             and not before.st_mode & 0o022 and 0 < before.st_size <= MAX_SOURCE,
             "join_source_not_protected")
        budget.reserve(before.st_size)
        digest, size = hashlib.sha256(), 0
        while size <= before.st_size:
            budget.check()
            block = os.read(fd, min(65536, before.st_size + 1 - size))
            if not block:
                break
            size += len(block)
            digest.update(block)
        need(size == before.st_size and gate.stamp(before) == gate.stamp(os.fstat(fd)) == gate.stamp(path.stat())
             and digest.hexdigest() == ref["sha256"], "join_source_changed")
    finally:
        os.close(fd)


def _launch(launch, uid, budget):
    gate.fields(launch, ("executable", "script", "argv"), "join_invalid_launch")
    argv = launch["argv"]
    need(isinstance(argv, list) and 2 <= len(argv) <= 64
         and all(isinstance(s, str) and s and len(s) <= 8192 and not any(ord(c) < 32 for c in s) for s in argv)
         and sum(len(s.encode()) + 1 for s in argv) <= 65536, "join_invalid_launch")
    for name in ("executable", "script"):
        _protected(launch[name], uid, budget)
    alias = Path(argv[0])
    need(alias.is_absolute() and str(alias) == argv[0] and ".." not in alias.parts
         and alias.resolve(strict=True) == Path(launch["executable"]["path"])
         and argv[1] == launch["script"]["path"], "join_launch_source_mismatch")


def _stat(pid, budget):
    raw = _kernel(Path("/proc") / str(pid) / "stat", 8192, budget)
    closing = raw.rfind(b") ")
    need(closing >= 0 and raw.startswith(str(pid).encode() + b" ("), "join_process_identity_unavailable")
    parts = raw[closing + 2:].split()
    need(len(parts) >= 20 and parts[0] not in {b"Z", b"X", b"x"}
         and parts[1].isdigit() and parts[19].isdigit() and int(parts[19]) > 0,
         "join_process_identity_unavailable")
    return parts[19].decode(), int(parts[1])


def _identity(pid, uid, budget, launch=None):
    need(gate.integer(pid, 2) and pid <= 2**31 - 1, "join_invalid_parent")
    proc = Path("/proc") / str(pid)
    first, parent_pid = _stat(pid, budget)
    status = _kernel(proc / "status", 65536, budget)
    ids = [line.split()[1:] for line in status.splitlines() if line.startswith(b"Uid:")]
    need(ids == [[str(uid).encode()] * 4], "join_process_owner_mismatch")
    boot = _kernel(Path("/proc/sys/kernel/random/boot_id"), 128, budget).decode("ascii").strip()
    need(BOOT.fullmatch(boot), "join_boot_unavailable")
    if launch is not None:
        raw = _kernel(proc / "cmdline", 65536, budget)
        need(raw == b"\0".join(s.encode() for s in launch["argv"]) + b"\0"
             and os.readlink(proc / "exe") == launch["executable"]["path"], "join_parent_launch_changed")
    need(_stat(pid, budget) == (first, parent_pid), "join_parent_changed")
    return {"pid": pid, "start_ticks": first, "boot_id": boot, "uid": uid}, parent_pid


def _resources(binding, attempt_root, uid, budget):
    gate.fields(binding, ("action", "attempt_id", "request", "adapter_config", "state_root",
                          "world_lock", "queue_lock", "plan"), "join_invalid_binding")
    need(binding["action"] in ("trial_run", "trial_recover")
         and isinstance(binding["attempt_id"], str) and gate.ID.fullmatch(binding["attempt_id"]),
         "join_invalid_binding")
    need(isinstance(binding["state_root"], str) and gate.canonical(binding["state_root"]) == attempt_root,
         "join_state_root_mismatch")
    root_device, root_inode = gate.directory(attempt_root, uid)
    if binding["action"] == "trial_run":
        gate.read_ref(binding["request"], uid, budget)
    else:
        need(binding["request"] is None, "join_recovery_request_forbidden")
    gate.read_ref(binding["adapter_config"], uid, budget)
    if binding["plan"] is not None:
        gate.read_ref(binding["plan"], uid, budget)
    locks = {}
    for name in ("world_lock", "queue_lock"):
        need(isinstance(binding[name], str), "join_invalid_lock_path")
        path = gate.canonical(binding[name])
        info = path.stat()
        need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "join_invalid_lock_path")
        locks[name] = {"path": str(path), "device": info.st_dev, "inode": info.st_ino,
                       "uid": info.st_uid, "mode": stat.S_IMODE(info.st_mode)}
    need(locks["world_lock"]["path"] != locks["queue_lock"]["path"]
         and (locks["world_lock"]["device"], locks["world_lock"]["inode"])
         != (locks["queue_lock"]["device"], locks["queue_lock"]["inode"]), "join_distinct_locks_required")
    operation_lock = (attempt_root / ".operations" / ".gate.lock").stat()
    need(all((value["device"], value["inode"]) != (operation_lock.st_dev, operation_lock.st_ino)
             for value in locks.values()), "join_distinct_locks_required")
    return {"state_root": {"device": root_device, "inode": root_inode}, **locks}


def _claim(control, ref, uid, budget):
    gate.reference(ref)
    path = Path(ref["path"])
    need(path.name == "claim.json" and path.parent.parent == control.registry
         and gate.ID.fullmatch(path.parent.name), "join_claim_outside_registry")
    gate.directory(path.parent, uid)
    with os.scandir(path.parent) as entries:
        names = []
        for entry in entries:
            need(len(names) < 2, "join_claim_not_pending")
            names.append(entry.name)
    need(names == ["claim.json"], "join_claim_not_pending")
    value = gate.read_ref(ref, uid, budget)
    gate.fields(value, ("schema_version", "operation_id", "kind", "authority", "created_at_ms", "owner"),
                "join_invalid_claim")
    gate.fields(value["owner"], ("pid", "uid"), "join_invalid_claim")
    need(type(value["schema_version"]) is int and value["schema_version"] == 1
         and value["operation_id"] == path.parent.name and isinstance(value["kind"], str)
         and value["kind"] in {"finite_group", "standalone_trial"}
         and gate.integer(value["created_at_ms"], 1) and gate.integer(value["owner"]["pid"], 2)
         and type(value["owner"]["uid"]) is int and value["owner"]["uid"] == uid, "join_invalid_claim")
    gate.read_ref(value["authority"], uid, budget)
    return value


def _dispatch_path(claim, supplied, uid):
    expected = Path(claim["authority"]["path"]).parent / ".operation-dispatch" / claim["operation_id"]
    path = gate.canonical(supplied)
    need(path == expected, "join_dispatch_directory_mismatch")
    gate.directory(path.parent, uid)
    identity = gate.directory(path, uid)
    return path, {"device": identity[0], "inode": identity[1]}


def _flock(pid, fd, pin, owner_pid, budget):
    proc = Path("/proc") / str(pid)
    info = (proc / "fd" / str(fd)).stat()
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == 0
         and (info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode))
         == tuple(pin[k] for k in ("device", "inode", "uid", "mode")), "join_gate_descriptor_changed")
    raw = _kernel(proc / "fdinfo" / str(fd), 8192, budget).decode("ascii")
    lines = [line for line in raw.splitlines() if line.startswith("lock:")]
    need(len(lines) == 1, "join_flock_proof_missing")
    match = FLOCK.fullmatch(lines[0])
    need(match is not None, "join_flock_proof_missing")
    proof = (int(match[1]), int(match[2], 16), int(match[3], 16), int(match[4]))
    need(proof == (owner_pid, os.major(pin["device"]), os.minor(pin["device"]), pin["inode"]),
         "join_flock_owner_mismatch")
    return proof


def _proof(control, fd, parent_pid, parent_fd, budget):
    control.check(fd)
    initial = _flock(parent_pid, parent_fd, control.pin, parent_pid, budget)
    need(_flock(os.getpid(), fd, control.pin, parent_pid, budget) == initial, "join_shared_description_missing")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise JoinError("join_shared_description_missing") from None
    need(_flock(parent_pid, parent_fd, control.pin, parent_pid, budget) == initial
         and _flock(os.getpid(), fd, control.pin, parent_pid, budget) == initial,
         "join_shared_description_changed")
    probe = os.open(control.pin["path"], os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        control.check(probe)
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise JoinError("join_exclusion_not_held")
    finally:
        os.close(probe)  # Close only, including an unexpected successful probe.
    need(_flock(parent_pid, parent_fd, control.pin, parent_pid, budget) == initial
         and _flock(os.getpid(), fd, control.pin, parent_pid, budget) == initial,
         "join_shared_description_changed")
    control.check(fd)


def _single_inherited(fd, pin, budget):
    found = []
    with os.scandir("/proc/self/fd") as entries:
        for index, entry in enumerate(entries):
            budget.check()
            need(index < MAX_FDS and entry.name.isdigit(), "join_fd_inventory_limit")
            try:
                info = os.fstat(int(entry.name))
            except OSError:
                raise JoinError("join_fd_inventory_changed") from None
            if (info.st_dev, info.st_ino) == (pin["device"], pin["inode"]):
                found.append(int(entry.name))
    need(found == [fd], "join_exactly_one_gate_fd_required")


@contextmanager
def prepare_join(lease, dispatch_directory, binding, *, parent_launch):
    """Publish one immutable dispatch while exporting a verified local lease."""
    need(type(lease) is gate._Lease, "join_local_lease_required")
    uid = lease.gate.uid
    _platform(uid)
    yielded = False
    try:
        with lease.export_active() as local:
            budget = gate.Budget()
            control, fd = lease.gate, local["fd"]
            _launch(parent_launch, uid, budget)
            parent, _ = _identity(os.getpid(), uid, budget, parent_launch)
            _proof(control, fd, parent["pid"], fd, budget)
            claim = _claim(control, local["claim"], uid, budget)
            path, path_pin = _dispatch_path(claim, dispatch_directory, uid)
            resources = _resources(binding, control.root, uid, budget)
            need((claim["kind"] == "finite_group") == (binding["plan"] is not None), "join_plan_kind_mismatch")
            stem = binding["action"] + "-" + binding["attempt_id"]
            need(not os.path.lexists(path / (stem + ".entered.json")), "join_dispatch_already_entered")
            value = {"schema_version": 1, "kind": "trial_operation_join", "claim": local["claim"],
                     "attempt_root": str(control.root), "gate_pin": copy.deepcopy(control.pin),
                     "parent": parent, "parent_fd": fd, "parent_launch": copy.deepcopy(parent_launch),
                     "binding": copy.deepcopy(binding), "resource_pins": resources,
                     "dispatch_directory": {"path": str(path), **path_pin}, "created_at_ms": gate.now()}
            ref = gate.create_json(path, stem + ".json", value, uid)
            need(gate.read_ref(ref, uid, budget) == value, "join_envelope_changed")
            lease._check()
            _launch(parent_launch, uid, budget)
            need(_identity(parent["pid"], uid, budget, parent_launch)[0] == parent, "join_parent_changed")
            _proof(control, fd, parent["pid"], fd, budget)
            budget.check()
            yielded = True
            yield {"envelope": ref, "pass_fds": (fd,)}
    except OSError:
        if yielded:
            raise
        raise JoinError("join_evidence_unavailable") from None


@contextmanager
def joined(attempt_root, gate_pin, envelope_ref, inherited_fd, expected_binding, *, owner_uid=0):
    """Own exactly the inherited descriptor; publish entry only after all checks.

    Caller-supplied expected_binding must be constructed from actual parsed CLI
    args and actual request/config/plan file hashes, never copied from envelope.
    """
    need(type(inherited_fd) is int and inherited_fd >= 3, "join_invalid_inherited_fd")
    fd = inherited_fd
    yielded = False
    try:
        _platform(owner_uid)
        control = gate.OperationGate(attempt_root, gate_pin, owner_uid=owner_uid)
        control.check(fd)
        os.set_inheritable(fd, False)
        budget = gate.Budget()
        _single_inherited(fd, gate_pin, budget)
        envelope = gate.read_ref(envelope_ref, owner_uid, budget)
        gate.fields(envelope, ("schema_version", "kind", "claim", "attempt_root", "gate_pin", "parent",
            "parent_fd", "parent_launch", "binding", "resource_pins", "dispatch_directory", "created_at_ms"),
            "join_invalid_envelope")
        need(type(envelope["schema_version"]) is int and envelope["schema_version"] == 1
             and envelope["kind"] == "trial_operation_join" and envelope["attempt_root"] == str(control.root)
             and _same(envelope["gate_pin"], gate_pin) and type(envelope["parent_fd"]) is int
             and envelope["parent_fd"] == fd and gate.integer(envelope["created_at_ms"], 1), "join_invalid_envelope")
        need(_same(envelope["binding"], expected_binding), "join_binding_mismatch")
        resources = _resources(expected_binding, control.root, owner_uid, budget)
        need(_same(resources, envelope["resource_pins"]), "join_resource_changed")
        gate.fields(envelope["parent"], ("pid", "start_ticks", "boot_id", "uid"), "join_invalid_parent")
        parent = envelope["parent"]
        need(type(parent["pid"]) is int and parent["pid"] == os.getppid(), "join_parent_not_direct")
        need(type(parent["uid"]) is int and parent["uid"] == owner_uid
             and isinstance(parent["start_ticks"], str) and parent["start_ticks"].isdigit()
             and isinstance(parent["boot_id"], str) and BOOT.fullmatch(parent["boot_id"]), "join_invalid_parent")
        _launch(envelope["parent_launch"], owner_uid, budget)
        need(_identity(parent["pid"], owner_uid, budget, envelope["parent_launch"])[0] == parent,
             "join_parent_changed")
        _proof(control, fd, parent["pid"], envelope["parent_fd"], budget)
        claim = _claim(control, envelope["claim"], owner_uid, budget)
        need((claim["kind"] == "finite_group") == (expected_binding["plan"] is not None), "join_plan_kind_mismatch")
        gate.fields(envelope["dispatch_directory"], ("path", "device", "inode"), "join_invalid_dispatch_directory")
        path, path_pin = _dispatch_path(claim, envelope["dispatch_directory"]["path"], owner_uid)
        need(_same(envelope["dispatch_directory"], {"path": str(path), **path_pin}), "join_dispatch_directory_changed")
        stem = expected_binding["action"] + "-" + expected_binding["attempt_id"]
        need(envelope_ref["path"] == str(path / (stem + ".json")), "join_envelope_path_mismatch")
        need(not os.path.lexists(path / (stem + ".entered.json")), "join_dispatch_already_entered")
        child, direct_parent = _identity(os.getpid(), owner_uid, budget)
        need(direct_parent == parent["pid"] and os.getppid() == parent["pid"], "join_parent_changed")
        # Repeat mutable admission checks immediately before durable entry.
        need(gate.read_ref(envelope_ref, owner_uid, budget) == envelope, "join_envelope_changed")
        need(_resources(expected_binding, control.root, owner_uid, budget) == resources, "join_resource_changed")
        _claim(control, envelope["claim"], owner_uid, budget)
        _launch(envelope["parent_launch"], owner_uid, budget)
        need(_identity(parent["pid"], owner_uid, budget, envelope["parent_launch"])[0] == parent,
             "join_parent_changed")
        _proof(control, fd, parent["pid"], envelope["parent_fd"], budget)
        entry = {"schema_version": 1, "kind": "trial_operation_entry", "envelope": copy.deepcopy(envelope_ref),
                 "claim": copy.deepcopy(envelope["claim"]), "binding": copy.deepcopy(expected_binding),
                 "parent": parent, "child": child, "entered_at_ms": gate.now()}
        entry_ref = gate.create_json(path, stem + ".entered.json", entry, owner_uid)
        need(gate.read_ref(entry_ref, owner_uid, budget) == entry, "join_entry_changed")
        need(gate.read_ref(envelope_ref, owner_uid, budget) == envelope, "join_envelope_changed")
        _claim(control, envelope["claim"], owner_uid, budget)
        need(_resources(expected_binding, control.root, owner_uid, budget) == resources, "join_resource_changed")
        need(_dispatch_path(claim, str(path), owner_uid)[1] == path_pin, "join_dispatch_directory_changed")
        need(_identity(parent["pid"], owner_uid, budget, envelope["parent_launch"])[0] == parent
             and os.getppid() == parent["pid"], "join_parent_changed")
        _proof(control, fd, parent["pid"], envelope["parent_fd"], budget)
        budget.check()
        yielded = True
        yield {"entry": entry_ref, "envelope": copy.deepcopy(envelope_ref),
               "claim": copy.deepcopy(envelope["claim"]), "binding": copy.deepcopy(expected_binding)}
    except OSError:
        if yielded:
            raise
        raise JoinError("join_evidence_unavailable") from None
    finally:
        try:
            os.close(fd)  # Own this inherited copy; never unlock the parent/other copies.
        except OSError:
            pass
