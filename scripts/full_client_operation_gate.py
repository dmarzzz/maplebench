"""Private operations exclusion used by admitted production entrypoints.

Explicit setup: initialize_registry(existing_attempt_root) -> gate inode pin.
Use OperationGate(attempt_root, pin).locked() as lease, then:
  begin(id, kind, authority_ref) -> immutable claim ref
  reconcile(exact_claim_ref) -> pending/completed status (never guesses owner death)
  complete(terminal_receipt_ref) -> immutable terminal marker ref

IDs are 32 lowercase hex characters; kind is finite_group, standalone_trial or
standalone_lifecycle. References are {path: canonical absolute path, sha256: hex}.
Authority is an actual caller-validated private JSON object. Terminal receipt:
  {schema_version: 1, operation_id: id, claim_sha256: hex, status: "completed",
   quiescent: true, evidence: [private_json_ref, ...]}
References require owner-only files and parent directories with modes 0600/0700.
The evidence list has 1..16 unique files. "completed" describes this operation's
reconciliation, not trial success. A failed trial can settle only when the
trusted caller proves quiescence in its evidence. There is no automatic timeout
retirement. A completed reconciliation returns its original terminal marker;
it does not authorize re-executing an operation or replacing its ID.

The terminal receipt must name the operation and claim hash, attest quiescence,
and reference actual private JSON evidence. This module checks integrity, NOT
service/renderer/score semantics; a trusted integrating caller must verify those.
No borrowed-FD admission, pending override, deletion or ownership takeover API
exists here. Closing a lease never unlocks another copy of its open description.
An unfinished/malformed claim survives process death and blocks other work.

Registry: <attempt_root>/.operations/{.gate.lock,<32hex>/claim.json,terminal.json}.
Setup creates only this registry, never the supplied attempt root or its parents.
Defaults require root; an explicit owner_uid must equal the effective user.
Limits: 256 claims, 64 KiB claims/markers, 4 MiB referenced JSON, 32 MiB total
reads and 10 seconds of checked work per API call. The caller must additionally
bound wall time/CPU/memory; filesystem syscalls are not forcibly interrupted.
Protected ancestors above the supplied root and reference parents remain a host
assumption; this component does not inventory the host filesystem.
Integrators must pin the same attempt root and gate inode, acquire before their
own world locks, and separately verify operation authority and evidence semantics.
Only full_client_operation_join may use export_active() for verified child
admission. A raw descriptor alone never authorizes a child operation.
Native OSError failures remain exceptions; callers must not expose their raw text.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import fcntl
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import stat
import time
import uuid

ID = re.compile(r"[0-9a-f]{32}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
KINDS = {"finite_group", "standalone_trial", "standalone_lifecycle"}
MAX_CLAIMS = 256
MAX_RECORD = 64 * 1024
MAX_REFERENCE = 4 * 1024 * 1024
MAX_READ_BYTES = 32 * 1024 * 1024
WORK_SECONDS = 10
_LEASE_TOKEN = object()
__all__ = ["GateError", "OperationGate", "initialize_registry"]


class GateError(ValueError):
    """Only fixed codes, never raw file contents or operating-system errors."""


def require(value, code):
    if not value:
        raise GateError(code)


def fields(value, names, code="invalid_record"):
    require(isinstance(value, dict) and set(value) == set(names), code)


def integer(value, minimum=0):
    return type(value) is int and minimum <= value <= 2**53 - 1


def canonical(value):
    require(isinstance(value, (str, Path)), "invalid_path")
    raw = str(value)
    path = Path(raw)
    require(path.is_absolute() and str(path) == raw and ".." not in path.parts
            and not any(ord(c) < 32 for c in raw), "invalid_path")
    require(path.resolve(strict=True) == path, "symlink_path")
    return path


def stamp(info):
    return tuple(getattr(info, key) for key in ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid",
                                              "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"))


def directory(path, uid):
    path = canonical(path)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == uid
            and stat.S_IMODE(info.st_mode) == 0o700, "private_directory_required")
    return (info.st_dev, info.st_ino)


def encoded(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    except (TypeError, ValueError, RecursionError) as error:
        raise GateError("invalid_json") from error
    require(len(raw) <= MAX_RECORD, "record_size_limit")
    return raw


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    def invalid(_):
        raise GateError("nonfinite_json")
    def number(raw):
        value = float(raw)
        require(math.isfinite(value), "nonfinite_json")
        return value
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid, parse_float=number)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, GateError):
            raise
        raise GateError("invalid_json") from error
    require(isinstance(value, dict), "json_object_required")
    return value


def reference(value):
    fields(value, ("path", "sha256"), "invalid_reference")
    require(isinstance(value["path"], str) and isinstance(value["sha256"], str)
            and SHA.fullmatch(value["sha256"]), "invalid_reference")
    canonical(value["path"])
    return value


def ref_for(path, raw):
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def now():
    value = time.time_ns() // 1_000_000
    require(integer(value, 1), "invalid_clock")
    return value


class Budget:
    def __init__(self):
        self.deadline = time.monotonic() + WORK_SECONDS
        self.remaining = MAX_READ_BYTES

    def check(self):
        require(time.monotonic() <= self.deadline, "gate_work_deadline")

    def reserve(self, size):
        self.check()
        self.remaining -= size
        require(self.remaining >= 0, "gate_read_budget")


def read_json(path, uid, budget, *, expected=None, maximum=MAX_RECORD):
    budget.check()
    path = canonical(path)
    parent_identity = directory(path.parent, uid)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == uid and before.st_nlink == 1
                and stat.S_IMODE(before.st_mode) == 0o600, "private_file_required")
        require(0 < before.st_size <= maximum, "file_size_limit")
        budget.reserve(before.st_size)
        data = bytearray()
        while len(data) <= before.st_size:
            budget.check()
            block = os.read(fd, min(65536, before.st_size + 1 - len(data)))
            if not block:
                break
            data.extend(block)
        require(len(data) == before.st_size and stamp(before) == stamp(os.fstat(fd)) == stamp(path.lstat()),
                "file_changed")
        require(directory(path.parent, uid) == parent_identity, "directory_changed")
        raw = bytes(data)
        ref = ref_for(path, raw)
        require(expected is None or ref["sha256"] == expected, "reference_changed")
        return decode(raw), ref
    finally:
        os.close(fd)


def read_ref(ref, uid, budget):
    reference(ref)
    return read_json(ref["path"], uid, budget, expected=ref["sha256"], maximum=MAX_REFERENCE)[0]


def create_json(parent, name, value, uid):
    """Publish complete bytes without replacing a destination; anchor writes to a directory FD."""
    identity = directory(parent, uid)
    raw = encoded(value)
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = ".writing-" + uuid.uuid4().hex
    try:
        require((os.fstat(parent_fd).st_dev, os.fstat(parent_fd).st_ino) == identity, "directory_changed")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
            os.unlink(temporary, dir_fd=parent_fd)
            os.fsync(parent_fd)
            require(directory(parent, uid) == identity, "directory_changed")
        finally:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        return ref_for(parent / name, raw)
    finally:
        os.close(parent_fd)


def initialize_registry(attempt_root, *, owner_uid=0):
    """Explicit create-once setup; an existing or partial registry is refused."""
    require(integer(owner_uid) and os.geteuid() == owner_uid, "operator_uid_mismatch")
    root = canonical(attempt_root)
    directory(root, owner_uid)
    registry = root / ".operations"
    require(not os.path.lexists(registry), "registry_exists")
    registry.mkdir(mode=0o700)
    parent_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    fd = os.open(registry / ".gate.lock", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fsync(fd)
        info = os.fstat(fd)
        pin = {"path": str(registry / ".gate.lock"), "device": info.st_dev, "inode": info.st_ino,
               "uid": owner_uid, "mode": 0o600}
    finally:
        os.close(fd)
    parent_fd = os.open(registry, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    OperationGate(root, pin, owner_uid=owner_uid)  # Verify setup before returning its real inode pin.
    return pin


class OperationGate:
    def __init__(self, attempt_root, gate_pin, *, owner_uid=0):
        require(integer(owner_uid) and os.geteuid() == owner_uid, "operator_uid_mismatch")
        self.uid = owner_uid
        self.root = canonical(attempt_root)
        self.registry = self.root / ".operations"
        self.root_identity = directory(self.root, self.uid)
        self.registry_identity = directory(self.registry, self.uid)
        fields(gate_pin, ("path", "device", "inode", "uid", "mode"), "invalid_gate_pin")
        require(gate_pin["path"] == str(self.registry / ".gate.lock")
                and all(integer(gate_pin[k]) for k in ("device", "inode", "uid", "mode"))
                and gate_pin["inode"] > 0 and gate_pin["uid"] == self.uid and gate_pin["mode"] == 0o600,
                "invalid_gate_pin")
        self.pin = copy.deepcopy(gate_pin)
        self.check()

    def check(self, fd=None):
        require(os.geteuid() == self.uid, "operator_uid_mismatch")
        require(directory(self.root, self.uid) == self.root_identity
                and directory(self.registry, self.uid) == self.registry_identity, "directory_changed")
        path = canonical(self.pin["path"])
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == 0
                and (info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode))
                == tuple(self.pin[k] for k in ("device", "inode", "uid", "mode")), "gate_pin_changed")
        if fd is not None:
            require(stamp(info) == stamp(os.fstat(fd)), "gate_description_changed")

    @contextmanager
    def locked(self):
        self.check()
        fd = os.open(self.pin["path"], os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
        lease = None
        try:
            self.check(fd)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise GateError("operation_busy") from error
            self.check(fd)
            lease = _Lease(self, fd, _LEASE_TOKEN)
            yield lease
        finally:
            if lease is not None:
                lease._closed = True
            os.close(fd)  # Never LOCK_UN: dup/SCM copies share this description.


class _Lease:
    """Created by locked(); no API accepts an externally supplied descriptor."""
    def __init__(self, gate, fd, token):
        require(token is _LEASE_TOKEN, "lease_factory_required")
        self.gate, self._fd, self._closed = gate, fd, False
        self._pid = os.getpid()
        self._active = None

    def _check(self):
        require(not self._closed and os.getpid() == self._pid, "lease_not_local_active")
        self.gate.check(self._fd)

    def ensure_available(self):
        """Read-only admission check on this local lease; never creates a claim."""
        self._check()
        require(self._active is None, "lease_already_claimed")
        rows = self._scan(Budget())
        require(all(row["status"] == "completed" for row in rows.values()), "pending_operation")

    @contextmanager
    def export_active(self):
        """Duplicate only this process's live pending claim; never join an input FD.

        The caller owns no returned descriptor beyond this context. Exiting
        closes only the duplicate and neither completes nor abandons the claim.
        Child admission must use the independently verified join protocol.
        """
        self._check()
        require(self._active is not None, "active_claim_required")
        rows = self._scan(Budget())
        operation_id = Path(self._active["path"]).parent.name
        row = rows.get(operation_id)
        require(row is not None and row["claim"] == self._active and row["status"] == "pending",
                "active_claim_changed")
        require(all(name == operation_id or value["status"] == "completed"
                    for name, value in rows.items()), "other_pending_operation")
        fd = os.dup(self._fd)
        try:
            self._check()
            self.gate.check(fd)
            yield {"fd": fd, "attempt_root": str(self.gate.root), "gate_pin": copy.deepcopy(self.gate.pin),
                   "claim": copy.deepcopy(self._active), "authority": copy.deepcopy(row["value"]["authority"]),
                   "owner_uid": self.gate.uid}
        finally:
            os.close(fd)

    def _scan(self, budget):
        self._check()
        rows = {}
        with os.scandir(self.gate.registry) as entries:
            for index, entry in enumerate(itertools.islice(entries, MAX_CLAIMS + 2)):
                budget.check()
                require(index <= MAX_CLAIMS, "claim_inventory_limit")
                if entry.name == ".gate.lock":
                    continue
                require(ID.fullmatch(entry.name), "unknown_registry_entry")
                folder = self.gate.registry / entry.name
                directory(folder, self.gate.uid)
                with os.scandir(folder) as children:
                    names = [child.name for child in itertools.islice(children, 3)]
                require(set(names) in ({"claim.json"}, {"claim.json", "terminal.json"}), "malformed_claim_directory")
                claim, claim_ref = read_json(folder / "claim.json", self.gate.uid, budget)
                fields(claim, ("schema_version", "operation_id", "kind", "authority", "created_at_ms", "owner"))
                fields(claim["owner"], ("pid", "uid"))
                require(type(claim["schema_version"]) is int and claim["schema_version"] == 1
                        and claim["operation_id"] == entry.name and isinstance(claim["kind"], str)
                        and claim["kind"] in KINDS
                        and integer(claim["created_at_ms"], 1) and integer(claim["owner"]["pid"], 1)
                        and claim["owner"]["uid"] == self.gate.uid and type(claim["owner"]["uid"]) is int,
                        "invalid_claim")
                read_ref(claim["authority"], self.gate.uid, budget)
                row = {"claim": claim_ref, "status": "pending", "terminal": None, "value": claim}
                if "terminal.json" in names:
                    terminal, terminal_ref = read_json(folder / "terminal.json", self.gate.uid, budget)
                    fields(terminal, ("schema_version", "operation_id", "claim_sha256", "completed_at_ms", "receipt"))
                    require(type(terminal["schema_version"]) is int and terminal["schema_version"] == 1
                            and terminal["operation_id"] == entry.name and terminal["claim_sha256"] == claim_ref["sha256"]
                            and integer(terminal["completed_at_ms"], claim["created_at_ms"]), "invalid_terminal")
                    self._receipt(terminal["receipt"], claim_ref, entry.name, budget)
                    row.update(status="completed", terminal=terminal_ref)
                rows[entry.name] = row
        self._check()
        return rows

    def _receipt(self, receipt_ref, claim_ref, operation_id, budget):
        receipt = read_ref(receipt_ref, self.gate.uid, budget)
        fields(receipt, ("schema_version", "operation_id", "claim_sha256", "status", "quiescent", "evidence"))
        require(type(receipt["schema_version"]) is int and receipt["schema_version"] == 1
                and receipt["operation_id"] == operation_id and receipt["claim_sha256"] == claim_ref["sha256"]
                and receipt["status"] == "completed" and receipt["quiescent"] is True
                and isinstance(receipt["evidence"], list) and 1 <= len(receipt["evidence"]) <= 16,
                "invalid_terminal_receipt")
        paths = set()
        for ref in receipt["evidence"]:
            reference(ref)
            require(ref["path"] not in paths, "duplicate_terminal_evidence")
            paths.add(ref["path"])
            read_ref(ref, self.gate.uid, budget)

    def begin(self, operation_id, kind, authority_ref):
        self._check()
        require(self._active is None, "lease_already_claimed")
        require(isinstance(operation_id, str) and ID.fullmatch(operation_id)
                and isinstance(kind, str) and kind in KINDS, "invalid_operation")
        budget = Budget()
        rows = self._scan(budget)
        require(all(row["status"] == "completed" for row in rows.values()), "pending_operation")
        require(operation_id not in rows, "operation_exists")
        require(len(rows) < MAX_CLAIMS, "claim_inventory_limit")
        read_ref(authority_ref, self.gate.uid, budget)
        claim = {"schema_version": 1, "operation_id": operation_id, "kind": kind,
                 "authority": copy.deepcopy(authority_ref), "created_at_ms": now(),
                 "owner": {"pid": os.getpid(), "uid": self.gate.uid}}
        self._check()
        folder = self.gate.registry / operation_id
        folder.mkdir(mode=0o700)
        parent_fd = os.open(self.gate.registry, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        claim_ref = create_json(folder, "claim.json", claim, self.gate.uid)
        read_json(claim_ref["path"], self.gate.uid, budget, expected=claim_ref["sha256"])
        read_ref(authority_ref, self.gate.uid, budget)
        self._check()
        budget.check()
        self._active = copy.deepcopy(claim_ref)
        return claim_ref

    def reconcile(self, claim_ref):
        self._check()
        require(self._active is None, "lease_already_claimed")
        reference(claim_ref)
        path = Path(claim_ref["path"])
        require(path.name == "claim.json" and path.parent.parent == self.gate.registry
                and ID.fullmatch(path.parent.name), "claim_outside_registry")
        rows = self._scan(Budget())
        row = rows.get(path.parent.name)
        require(row is not None and row["claim"] == claim_ref, "claim_reference_changed")
        require(all(name == path.parent.name or value["status"] == "completed"
                    for name, value in rows.items()), "other_pending_operation")
        if row["status"] == "pending":
            self._active = copy.deepcopy(claim_ref)
        return copy.deepcopy({key: row[key] for key in ("claim", "status", "terminal")})

    def complete(self, terminal_receipt_ref):
        self._check()
        require(self._active is not None, "active_claim_required")
        budget = Budget()
        rows = self._scan(budget)
        operation_id = Path(self._active["path"]).parent.name
        row = rows.get(operation_id)
        require(row is not None and row["claim"] == self._active and row["status"] == "pending", "active_claim_changed")
        require(all(name == operation_id or value["status"] == "completed"
                    for name, value in rows.items()), "other_pending_operation")
        self._receipt(terminal_receipt_ref, self._active, operation_id, budget)
        completed = now()
        require(completed >= row["value"]["created_at_ms"], "clock_moved_backwards")
        marker = {"schema_version": 1, "operation_id": operation_id, "claim_sha256": self._active["sha256"],
                  "completed_at_ms": completed, "receipt": copy.deepcopy(terminal_receipt_ref)}
        self._check()
        ref = create_json(self.gate.registry / operation_id, "terminal.json", marker, self.gate.uid)
        read_json(self._active["path"], self.gate.uid, budget, expected=self._active["sha256"])
        read_json(ref["path"], self.gate.uid, budget, expected=ref["sha256"])
        self._receipt(terminal_receipt_ref, self._active, operation_id, budget)
        self._check()
        budget.check()
        self._active = None
        return ref
