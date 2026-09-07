#!/usr/bin/env python3
"""Explicit, private normal-runtime restoration; separate from trial cleanup.

No machine defaults, reset, stop, restart, provisioning, API call, or automatic
start retry. A failed operation is reconciled against the existing instance.
check/start consume a hash-bound handoff; reconcile consumes an exact journal
hash. Missing worker-hook or ownership evidence is an unsupported prerequisite,
not permission to infer success. Configurations and outputs belong outside Git.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import ctypes
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import resource
import selectors
import shlex
import signal
import socket
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
import time

import full_client_collect
import full_client_score
import full_client_trial
from full_client_trial import atomic_json, existing_lock, publish_attempt, sync_directory

HEX = re.compile(r"[a-f0-9]{64}\Z")
ID = re.compile(r"[a-f0-9]{32}\Z")
BOOT = re.compile(r"[a-f0-9-]{36}\Z")
UNIT = re.compile(r"[A-Za-z0-9_.@-]+\.service\Z")
CONFIG_PROPERTIES = {"User", "Group", "WorkingDirectory", "MemoryMax", "MemorySwapMax",
                     "CPUQuotaPerSecUSec", "Restart", "KillMode", "RuntimeMaxUSec", "TimeoutStopUSec"}
PROPERTIES = sorted(CONFIG_PROPERTIES | {"LoadState", "ActiveState", "SubState", "MainPID", "InvocationID",
                    "ExecStart", "Environment", "DropInPaths", "NeedDaemonReload"})
TRIAL_ENV = ("MAPLEBENCH_TRIAL_ID", "MAPLEBENCH_SERVER_INSTANCE_ID", "MAPLEBENCH_PERSIST_CHARACTER_ID",
             "MAPLEBENCH_PERSIST_ACCOUNT_ID", "MAPLEBENCH_SAVE_JOURNAL")
JSON_LIMIT = 16 * 1024 * 1024


class LifecycleError(ValueError):
    """Fixed safe codes only; never include raw command/configuration content."""


def require(value, code):
    if not value:
        raise LifecycleError(code)


def object_fields(value, names, code="invalid_fields"):
    require(isinstance(value, dict) and set(value) == set(names), code)
    return value


def integer(value, low, high, code="invalid_integer"):
    require(type(value) is int and low <= value <= high, code)
    return value


def absolute(value):
    require(isinstance(value, str) and Path(value).is_absolute()
            and not any(ord(c) < 32 for c in value) and Path(value).resolve() == Path(value), "noncanonical_path")
    return Path(value)


def stable(info):
    return tuple(getattr(info, key) for key in ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid",
                                               "st_size", "st_mtime_ns", "st_ctime_ns"))


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def lifecycle_same_json(left, right):
    return encoded(left) == encoded(right)


def read_file(path, *, maximum=JSON_LIMIT, uid=None, private=False):
    path = absolute(str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_size <= maximum, "file_type_or_size")
        require(uid is None or before.st_uid == uid, "file_owner_changed")
        require(not before.st_mode & (0o077 if private else 0o022), "file_permissions_changed")
        raw = bytearray()
        while len(raw) <= maximum:
            block = os.read(fd, min(1024 * 1024, maximum + 1 - len(raw)))
            if not block:
                break
            raw.extend(block)
        require(len(raw) == before.st_size and stable(before) == stable(os.fstat(fd)) == stable(path.stat()),
                "file_changed_during_read")
        return bytes(raw), before
    finally:
        os.close(fd)


def ref(value):
    object_fields(value, ("path", "sha256"), "invalid_reference")
    absolute(value["path"])
    require(isinstance(value["sha256"], str) and HEX.fullmatch(value["sha256"]), "invalid_reference_hash")
    return value


def read_ref(value, *, uid=0, private=True, maximum=JSON_LIMIT):
    ref(value)
    raw, _ = read_file(value["path"], maximum=maximum, uid=uid, private=private)
    require(digest(raw) == value["sha256"], "reference_changed")
    return full_client_score.parse_json(raw)


def verify_file_pin(value, owners, maximum=128 * 1024 * 1024):
    """Stream service binaries without allocating their entire contents."""
    path = absolute(value["path"])
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_size <= maximum
                and before.st_uid in owners and not before.st_mode & 0o022, "frozen_service_file_changed")
        result = hashlib.sha256()
        size = 0
        while block := os.read(fd, 1024 * 1024):
            size += len(block)
            require(size <= maximum, "frozen_service_file_limit")
            result.update(block)
        require(size == before.st_size and stable(before) == stable(os.fstat(fd)) == stable(path.stat())
                and result.hexdigest() == value["sha256"], "frozen_service_file_changed")
        return size
    finally:
        os.close(fd)


def instance(value):
    object_fields(value, ("pid", "start_ticks", "invocation_id"), "invalid_instance")
    integer(value["pid"], 2, 2**31 - 1)
    require(isinstance(value["start_ticks"], str) and value["start_ticks"].isdigit()
            and int(value["start_ticks"]) > 0 and isinstance(value["invocation_id"], str)
            and ID.fullmatch(value["invocation_id"]), "invalid_instance")
    return value


def native_offset(info, raw, boundary, intent_at_ms, birth_at_ms=None):
    """Do not turn an overwritten old marker into evidence of a new startup."""
    if (info.st_dev, info.st_ino) == (boundary["device"], boundary["inode"]):
        require(len(raw) >= boundary["bytes"] and digest(raw[:boundary["bytes"]]) == boundary["sha256"],
                "native_boundary_ambiguous")
        return boundary["bytes"]
    # ctime alone changes on rename/chmod and cannot establish fresh contents.
    # Unsupported filesystems lacking kernel birth-time evidence fail closed.
    require(type(birth_at_ms) is int and birth_at_ms >= intent_at_ms
            and info.st_ctime_ns // 1_000_000 >= intent_at_ms
            and info.st_mtime_ns // 1_000_000 >= intent_at_ms, "native_fresh_inode_provenance_missing")
    return 0


def validate_config(config):
    object_fields(config, ("schema_version", "state_root", "locks", "services", "source_files", "commands",
        "mysql", "queue_database", "attempt_root", "admin_socket", "native", "min_available_bytes",
        "limits", "worker_receipt_directory"), "invalid_config")
    require(type(config["schema_version"]) is int and config["schema_version"] == 1, "invalid_schema")
    for name in ("state_root", "queue_database", "attempt_root", "admin_socket", "worker_receipt_directory"):
        absolute(config[name])
    object_fields(config["commands"], ("systemctl", "mysql"))
    for value in config["commands"].values():
        ref(value)
    object_fields(config["locks"], ("world", "queue", "runner"))
    identities = set()
    for pin in config["locks"].values():
        object_fields(pin, ("path", "device", "inode", "uid", "mode"), "invalid_lock_pin")
        absolute(pin["path"])
        for key in ("device", "inode", "uid", "mode"):
            integer(pin[key], 0, 2**63 - 1)
        require(pin["mode"] <= 0o777 and pin["inode"] > 0, "invalid_lock_pin")
        identities.add((pin["device"], pin["inode"]))
    require(len(identities) == 3 and len({v["path"] for v in config["locks"].values()}) == 3, "distinct_locks_required")
    object_fields(config["services"], ("world", "cosmic", "worker", "web"))
    require(isinstance(config["services"]["world"], str) and UNIT.fullmatch(config["services"]["world"]), "invalid_service")
    names = {config["services"]["world"]}
    for role in ("cosmic", "worker", "web"):
        service = config["services"][role]
        object_fields(service, ("unit", "uid", "argv", "executable", "properties", "dropins", "environment", "files"),
                      "invalid_service")
        require(isinstance(service["unit"], str) and UNIT.fullmatch(service["unit"]), "invalid_service")
        names.add(service["unit"])
        integer(service["uid"], 1, 2**31 - 1)
        ref(service["executable"])
        require(isinstance(service["argv"], list) and 2 <= len(service["argv"]) <= 64
                and all(isinstance(v, str) and v and not any(ord(c) < 32 for c in v) for v in service["argv"])
                and Path(service["argv"][0]).is_absolute(), "invalid_service_argv")
        object_fields(service["properties"], CONFIG_PROPERTIES, "invalid_service_properties")
        require(all(isinstance(v, str) for v in service["properties"].values()), "invalid_service_properties")
        absolute(service["properties"]["WorkingDirectory"])
        require(isinstance(service["dropins"], list) and len(service["dropins"]) <= 16
                and len(set(service["dropins"])) == len(service["dropins"]), "invalid_dropins")
        for path in service["dropins"]:
            absolute(path)
        require(isinstance(service["environment"], dict) and all(isinstance(k, str) and isinstance(v, str)
                and re.fullmatch("[A-Z0-9_]+", k) and not any(ord(c) < 32 for c in v)
                for k, v in service["environment"].items()), "invalid_environment")
        require(isinstance(service["files"], list) and 1 <= len(service["files"]) <= 128, "invalid_service_files")
        for value in service["files"]:
            ref(value)
    require(len(names) == 4, "distinct_services_required")
    worker = config["services"]["worker"]
    require(config["services"]["cosmic"]["unit"] == "maplebench-cosmic.service", "unsupported_worker_cosmic_target")
    require(worker["environment"].get("MAPLEBENCH_LIFECYCLE_RECEIPT_DIR") == config["worker_receipt_directory"]
            and worker["argv"][1] in {v["path"] for v in worker["files"]}, "worker_hook_not_configured")
    required_sources = {str(Path(module.__file__).resolve()) for module in
                        (sys.modules[__name__], full_client_trial, full_client_collect, full_client_score)}
    require(isinstance(config["source_files"], list) and 4 <= len(config["source_files"]) <= 32, "invalid_source_files")
    for value in config["source_files"]:
        ref(value)
    require(required_sources <= {v["path"] for v in config["source_files"]}, "lifecycle_source_pin_missing")
    mysql = object_fields(config["mysql"], ("database", "defaults_file", "character_id", "account_id"), "invalid_mysql")
    require(isinstance(mysql["database"], str) and full_client_collect.DATABASE.fullmatch(mysql["database"]), "invalid_mysql")
    if mysql["defaults_file"] is not None:
        ref(mysql["defaults_file"])
    for key in ("character_id", "account_id"):
        integer(mysql[key], 1, 2**31 - 1)
    native = object_fields(config["native"], ("path", "ports", "max_fds", "max_bytes", "online_marker", "error_markers"))
    absolute(native["path"])
    integer(native["max_fds"], 1024, 4096)
    integer(native["max_bytes"], 1024, 16 * 1024 * 1024)
    require(isinstance(native["ports"], list) and 1 <= len(native["ports"]) <= 16
            and len(set(native["ports"])) == len(native["ports"]), "invalid_ports")
    for port in native["ports"]:
        integer(port, 1, 65535)
    require(native["online_marker"] == "Cosmic is now online after "
            and set(native["error_markers"]) == {"Error saving chr", "MapleBench persistence journal failed", "ERROR", "Exception"},
            "unsupported_native_markers")
    integer(config["min_available_bytes"], 1024**3, 2**50)
    limits = object_fields(config["limits"], ("total_seconds", "command_seconds", "ready_seconds", "idle_seconds",
                                             "memory_bytes", "cpu_seconds", "cpus"), "invalid_limits")
    for key, low, high in (("total_seconds", 30, 300), ("command_seconds", 1, 30), ("ready_seconds", 1, 120),
                           ("idle_seconds", 1, 30), ("memory_bytes", 128 * 1024**2, 512 * 1024**2),
                           ("cpu_seconds", 1, 120), ("cpus", 1, 2)):
        integer(limits[key], low, high)
    require(limits["ready_seconds"] + limits["idle_seconds"] + limits["command_seconds"] <= limits["total_seconds"],
            "inconsistent_limits")
    return copy.deepcopy(config)


class Host:
    """Bounded host reads and fixed commands; no service mutation in probes."""
    def __init__(self):
        self.deadline = 0
        self.guard_fds = []
        self.command_seconds = 0

    def remaining(self, cap=None):
        left = self.deadline - time.monotonic()
        require(left > 0, "lifecycle_deadline")
        return min(left, cap) if cap is not None else left

    def now(self):
        return time.time_ns() // 1_000_000

    def boot(self):
        return self.kernel_read(Path("/proc/sys/kernel/random/boot_id"), 128).decode().strip()

    def kernel_read(self, path, maximum):
        self.remaining()
        with Path(path).open("rb") as stream:
            raw = bytearray()
            while len(raw) <= maximum:
                self.remaining()
                block = stream.read(min(65536, maximum + 1 - len(raw)))
                if not block:
                    break
                raw.extend(block)
        require(len(raw) <= maximum, "kernel_observation_limit")
        return bytes(raw)

    def birth_ms(self, fd):
        self.remaining()
        libc = ctypes.CDLL(None, use_errno=True)
        function = getattr(libc, "statx", None)
        if function is None:
            return None
        buffer = ctypes.create_string_buffer(256)
        function.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p)
        function.restype = ctypes.c_int
        if function(fd, b"", 0x1000, 0x800, buffer) != 0:  # AT_EMPTY_PATH, STATX_BTIME
            return None
        if not struct.unpack_from("=I", buffer.raw, 0)[0] & 0x800:
            return None
        seconds, nanos = struct.unpack_from("=qI", buffer.raw, 80)
        return seconds * 1000 + nanos // 1_000_000

    def command(self, argv, *, data=None):
        timeout = self.remaining(self.command_seconds)
        require(data is None or isinstance(data, bytes) and len(data) <= 65536, "host_input_limit")
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as incoming:
            if data:
                incoming.write(data)
            incoming.seek(0)
            alive_read, alive_write = os.pipe()
            args = [sys.executable, str(Path(__file__).resolve()), "_command_guard", str(os.getpid()),
                    str(alive_read), ",".join(map(str, self.guard_fds)), str(timeout),
                    *map(str, resource.getrlimit(resource.RLIMIT_CPU)), *argv]
            try:
                child = subprocess.Popen(args, stdin=incoming, stdout=output, stderr=subprocess.DEVNULL,
                    close_fds=True, pass_fds=(*self.guard_fds, alive_read), start_new_session=True)
            except BaseException:
                os.close(alive_write)
                raise
            finally:
                os.close(alive_read)
            try:
                result = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                raise LifecycleError("host_command_timeout") from None
            finally:
                os.close(alive_write)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    raise LifecycleError("host_guard_cleanup_pending") from None
            require(result == 0, "host_command_failed")
            require(output.tell() <= JSON_LIMIT, "host_output_limit")
            output.seek(0)
            return output.read(JSON_LIMIT + 1)

    def unit(self, systemctl, name):
        raw = self.command([systemctl, "show", name, "--no-pager", "--property=" + ",".join(PROPERTIES)])
        return dict(line.split("=", 1) for line in raw.decode().splitlines() if "=" in line)

    def process(self, pid):
        proc = Path("/proc") / str(pid)
        first = self.kernel_read(proc / "stat", 8192).decode().rsplit(")", 1)[1].split()[19]
        status = dict(line.split(":", 1) for line in self.kernel_read(proc / "status", 65536).decode().splitlines() if ":" in line)
        env = dict(part.split(b"=", 1) for part in self.kernel_read(proc / "environ", 262144).split(b"\0") if b"=" in part)
        result = {"start_ticks": first, "argv": self.kernel_read(proc / "cmdline", 65536).rstrip(b"\0").split(b"\0"),
                  "executable": str((proc / "exe").resolve(strict=True)), "cwd": str((proc / "cwd").resolve(strict=True)),
                  "uids": [int(v) for v in status["Uid"].split()], "environment": env,
                  "children": self.kernel_read(proc / "task" / str(pid) / "children", 65536).decode().split()}
        require(first == self.kernel_read(proc / "stat", 8192).decode().rsplit(")", 1)[1].split()[19], "process_reused")
        return result

    def lock_owners(self, pin):
        key = (os.major(pin["device"]), os.minor(pin["device"]), pin["inode"])
        owners = []
        for row in (line.split() for line in self.kernel_read(Path("/proc/locks"), 4 * 1024 * 1024).decode().splitlines()):
            self.remaining()
            if len(row) >= 8 and row[1:4] == ["FLOCK", "ADVISORY", "WRITE"]:
                identity = tuple(int(v, 16 if i < 2 else 10) for i, v in enumerate(row[5].split(":")))
                if identity == key:
                    owners.append(int(row[4]))
        return owners

    def memory(self):
        return int(next(line.split()[1] for line in self.kernel_read(Path("/proc/meminfo"), 65536).decode().splitlines()
                        if line.startswith("MemAvailable:"))) * 1024

    def queue(self, path):
        with contextlib.closing(sqlite3.connect(absolute(path).as_uri() + "?mode=ro", uri=True, timeout=self.remaining(3))) as db:
            db.execute("PRAGMA query_only=ON")
            db.set_progress_handler(lambda: int(time.monotonic() >= self.deadline), 1000)
            return db.execute("SELECT count(*) FROM trials WHERE status IN ('queued','running','rendering')").fetchone()[0]

    def snapshot(self, config, run_id):
        db = config["mysql"]
        # The collector executes one fixed read-only snapshot, never supplied SQL.
        options = ["--defaults-extra-file=" + db["defaults_file"]["path"]] if db["defaults_file"] else []
        raw = self.command([config["commands"]["mysql"]["path"], *options, "--batch", "--raw",
            "--skip-column-names", "--connect-timeout=5", db["database"]],
            data=full_client_collect.snapshot_sql(db["character_id"], db["account_id"]).encode())
        return full_client_collect.parse_snapshot(raw.decode(), run_id=run_id, captured_at_ms=self.now(),
            character_id=db["character_id"], account_id=db["account_id"])

    def browser(self, path, expected_pid, expected_uid):
        info = absolute(path).lstat()
        require(stat.S_ISSOCK(info.st_mode) and info.st_uid == expected_uid and stat.S_IMODE(info.st_mode) == 0o600,
                "browser_socket_changed")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
            stream.settimeout(self.remaining(3))
            stream.connect(path)
            peer = struct.unpack("3i", stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            require(peer[:2] == (expected_pid, expected_uid), "browser_peer_changed")
            stream.sendall(b'{"op":"status"}\n')
            raw = bytearray()
            while not raw.endswith(b"\n"):
                block = stream.recv(32768)
                require(block and len(raw) + len(block) <= 262144, "browser_status_limit")
                raw.extend(block)
        response = full_client_score.parse_json(raw)
        require(response.get("ok") is True and isinstance(response.get("result"), dict), "browser_status_failed")
        return response["result"]

    def native(self, pid, config, boundary, intent_at_ms):
        path = absolute(config["path"])
        st = path.stat()
        proc = Path("/proc") / str(pid)
        owned, sockets = [], set()
        with os.scandir(proc / "fd") as entries:
            for index, entry in enumerate(itertools.islice(entries, config["max_fds"] + 1), 1):
                self.remaining()
                require(index <= config["max_fds"], "native_fd_limit")
                try:
                    info = entry.stat(); target = os.readlink(entry.path)
                    if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == (st.st_dev, st.st_ino):
                        owned.append(entry.path)
                    match = re.fullmatch(r"socket:\[(\d+)\]", target)
                    if match:
                        sockets.add(match[1])
                except FileNotFoundError:
                    pass
        require(owned, "native_fd_not_owned")
        fd = os.open(owned[0], os.O_RDONLY)
        try:
            before = os.fstat(fd)
            require(before.st_size <= config["max_bytes"], "native_log_limit")
            raw = os.read(fd, config["max_bytes"] + 1)
            require(len(raw) == before.st_size and stable(before) == stable(os.fstat(fd)) == stable(path.stat()),
                    "native_log_changed")
            birth = self.birth_ms(fd) if (before.st_dev, before.st_ino) != (boundary["device"], boundary["inode"]) else None
        finally:
            os.close(fd)
        offset = native_offset(before, raw, boundary, intent_at_ms, birth)
        fresh = raw[offset:]
        require(before.st_mtime_ns // 1_000_000 >= intent_at_ms and fresh.count(config["online_marker"].encode()) == 1,
                "native_online_marker_missing")
        require(not any(value.encode() in fresh for value in config["error_markers"]), "native_startup_error")
        ports = set()
        for table in ("tcp", "tcp6"):
            for line in self.kernel_read(proc / "net" / table, 8 * 1024 * 1024).decode().splitlines()[1:]:
                self.remaining()
                values = line.split()
                if len(values) > 9 and values[3] == "0A" and values[9] in sockets:
                    ports.add(int(values[1].split(":")[-1], 16))
        require(set(config["ports"]) <= ports, "native_ports_missing")
        return {"log_sha256": digest(raw), "startup_sha256": digest(fresh), "offset": offset,
                "bytes": len(raw), "device": before.st_dev, "inode": before.st_ino,
                "fd": int(Path(owned[0]).name), "ports": sorted(ports), "observed_at_ms": self.now()}


class NormalLifecycle:
    def __init__(self, config, config_ref, host=None, *, owner_uid=0):
        self.config = validate_config(config)
        self.config_ref = ref(config_ref)
        self.host = host or Host()
        self.owner_uid = owner_uid  # Injection for ordinary-user offline tests; CLI always requires root.
        self.root = absolute(config["state_root"])
        self.state = None
        self.journal_sha = None
        self.serial_fd = None
        self.world_stack = None
        self.world_fds = []
        self.directory = None
        self.request = None
        self.last_readiness = None

    def begin_deadline(self):
        self.host.deadline = time.monotonic() + self.config["limits"]["total_seconds"]
        self.host.command_seconds = self.config["limits"]["command_seconds"]

    @contextlib.contextmanager
    def serialized(self):
        info = self.root.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == self.owner_uid and stat.S_IMODE(info.st_mode) == 0o700,
                "private_state_root_required")
        with existing_lock(self.root / ".lifecycle.lock", create=True) as fd:
            current = os.fstat(fd)
            require(current.st_uid == self.owner_uid and stat.S_IMODE(current.st_mode) == 0o600,
                    "lifecycle_lock_owner_changed")
            self.serial_fd = fd
            self.host.guard_fds = [fd]
            try:
                yield
            finally:
                self.close_world_locks()
                self.host.guard_fds = []
                self.serial_fd = None

    def acquire_world_locks(self):
        require(self.serial_fd is not None and self.world_stack is None, "lifecycle_serialization_required")
        self.world_stack = contextlib.ExitStack()
        try:
            for role in ("world", "queue", "runner"):
                pin = self.config["locks"][role]
                fd = self.world_stack.enter_context(existing_lock(pin["path"]))
                self.world_fds.append(fd)
                self.lock_pin(fd, pin)
            self.verify_world_locks()
            self.host.guard_fds = [self.serial_fd, *self.world_fds]
        except BaseException:
            self.close_world_locks()
            raise

    def lock_pin(self, fd, pin):
        info = os.fstat(fd)
        require((info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode)) ==
                (pin["device"], pin["inode"], pin["uid"], pin["mode"])
                and stable(info) == stable(absolute(pin["path"]).stat()), "lock_identity_changed")

    def verify_world_locks(self):
        require(len(self.world_fds) == 3, "world_locks_missing")
        for fd, role in zip(self.world_fds, ("world", "queue", "runner")):
            pin = self.config["locks"][role]
            self.lock_pin(fd, pin)
            require(self.host.lock_owners(pin) == [os.getpid()], "world_lock_owner_changed")

    def close_world_locks(self):
        if self.world_stack is not None:
            self.world_stack.close()  # Shared descriptions: never LOCK_UN.
        self.world_stack = None
        self.world_fds = []
        self.host.guard_fds = [self.serial_fd] if self.serial_fd is not None else []

    def unit(self, role):
        value = self.config["services"][role]
        return self.host.unit(self.config["commands"]["systemctl"]["path"], value if role == "world" else value["unit"])

    @staticmethod
    def stopped(unit):
        return unit.get("ActiveState") in ("inactive", "failed") and unit.get("MainPID") == "0"

    def require_stopped(self, role):
        unit = self.unit(role)
        require(self.stopped(unit) and unit.get("InvocationID") == self.request["stopped_invocations"][role],
                "stopped_instance_changed")

    def settings(self):
        for role in ("cosmic", "worker", "web"):
            expected = self.config["services"][role]
            unit = self.unit(role)
            require(unit.get("LoadState") == "loaded" and unit.get("NeedDaemonReload") == "no"
                    and all(unit.get(k) == v for k, v in expected["properties"].items()), "service_configuration_changed")
            try:
                paths = shlex.split(unit.get("DropInPaths", ""))
                environment = dict(value.split("=", 1) for value in shlex.split(unit.get("Environment", "")))
            except ValueError:
                raise LifecycleError("service_configuration_unreadable") from None
            require(sorted(paths) == sorted(expected["dropins"])
                    and all(environment.get(k) == v for k, v in expected["environment"].items()), "service_configuration_changed")
            require(role != "cosmic" or not any(key in environment for key in TRIAL_ENV), "trial_configuration_present")
            match = re.fullmatch(r"\{ path=([^;]+) ; argv\[\]=([^;]+) ; ignore_errors=no ; .* \}", unit.get("ExecStart", ""))
            require(match and match[1].strip() == expected["argv"][0]
                    and shlex.split(match[2]) == expected["argv"], "service_entrypoint_changed")

    def process_identity(self, role):
        service = self.config["services"][role]
        unit = self.unit(role)
        require(unit.get("ActiveState") == "active" and unit.get("SubState") == "running"
                and str(unit.get("MainPID", "")).isdigit(), "service_not_running")
        pid = int(unit["MainPID"])
        require(pid > 1, "service_not_running")
        proc = self.host.process(pid)
        require(proc["argv"] == [arg.encode() for arg in service["argv"]]
                and proc["executable"] == service["executable"]["path"]
                and proc["cwd"] == service["properties"]["WorkingDirectory"]
                and proc["uids"] == [service["uid"]] * 4, "process_identity_changed")
        require(all(proc["environment"].get(key.encode()) == value.encode()
                    for key, value in service["environment"].items()), "process_environment_changed")
        require(role != "cosmic" or not any(key.encode() in proc["environment"] for key in TRIAL_ENV),
                "trial_configuration_present")
        result = instance({"pid": pid, "start_ticks": proc["start_ticks"], "invocation_id": unit.get("InvocationID")})
        require(self.unit(role).get("InvocationID") == result["invocation_id"], "process_identity_changed")
        return result

    def same_cosmic(self):
        require(self.process_identity("cosmic") == self.state.get("cosmic"), "cosmic_instance_changed")

    def verify_files(self):
        require(read_ref(self.config_ref, uid=self.owner_uid) == self.config, "configuration_changed")
        refs = [(value, self.owner_uid) for value in self.config["source_files"] + list(self.config["commands"].values())]
        for service in (self.config["services"][key] for key in ("cosmic", "worker", "web")):
            refs += [(value, service["uid"]) for value in [service["executable"], *service["files"]]]
        total = 0
        for value, service_uid in refs:
            self.host.remaining()
            total += verify_file_pin(value, (0, self.owner_uid, service_uid))
            require(total <= 256 * 1024 * 1024, "frozen_service_file_limit")
        if self.config["mysql"]["defaults_file"]:
            raw, _ = read_file(self.config["mysql"]["defaults_file"]["path"], maximum=65536,
                               uid=self.owner_uid, private=True)
            require(digest(raw) == self.config["mysql"]["defaults_file"]["sha256"], "collector_configuration_changed")
        directory = absolute(self.config["worker_receipt_directory"]).stat()
        require(stat.S_ISDIR(directory.st_mode) and directory.st_uid == self.config["services"]["worker"]["uid"]
                and stat.S_IMODE(directory.st_mode) == 0o700, "worker_receipt_directory_changed")

    def load_handoff(self, value):
        handoff = read_ref(value, uid=self.owner_uid)
        object_fields(handoff, ("schema_version", "operation_id", "config_sha256", "boot_id", "stopped_invocations",
                                "web_instance", "browser_run_id", "attempts", "offline_snapshot"), "invalid_handoff")
        require(type(handoff["schema_version"]) is int and handoff["schema_version"] == 1
                and isinstance(handoff["operation_id"], str) and ID.fullmatch(handoff["operation_id"])
                and handoff["config_sha256"] == self.config_ref["sha256"] and BOOT.fullmatch(handoff["boot_id"]), "invalid_handoff")
        object_fields(handoff["stopped_invocations"], ("cosmic", "worker", "world"))
        require(all(isinstance(v, str) and ID.fullmatch(v) for v in handoff["stopped_invocations"].values()), "invalid_handoff")
        instance(handoff["web_instance"])
        require(handoff["browser_run_id"] is None or isinstance(handoff["browser_run_id"], str)
                and ID.fullmatch(handoff["browser_run_id"]), "invalid_browser_run")
        require(isinstance(handoff["attempts"], list) and 1 <= len(handoff["attempts"]) <= 4096, "invalid_attempt_inventory")
        self.request = handoff
        self.verify_handoff_evidence()
        return handoff

    def verify_handoff_evidence(self):
        require(self.host.boot() == self.request["boot_id"], "host_boot_changed")
        expected = set()
        for item in self.request["attempts"]:
            object_fields(item, ("id", "journal", "backend"), "invalid_attempt_reference")
            require(isinstance(item["id"], str) and ID.fullmatch(item["id"]) and item["id"] not in expected,
                    "invalid_attempt_reference")
            expected.add(item["id"])
            folder = Path(self.config["attempt_root"]) / item["id"]
            require(item["journal"]["path"] == str(folder / "journal.json")
                    and item["backend"]["path"] == str(folder / "backend-state.json"), "attempt_reference_outside_root")
            journal = read_ref(item["journal"], uid=self.owner_uid)
            backend = read_ref(item["backend"], uid=self.owner_uid)
            require(journal.get("attempt_id") == item["id"] and journal.get("status") in ("completed", "recovered")
                    and journal.get("pending") is None and journal.get("phase_status") == "returned"
                    and backend.get("attempt_id") == item["id"] and backend.get("clean") is True
                    and journal.get("receipts", {}).get("cleanup") == {"attempt_id": item["id"], "clean": True},
                    "attempt_not_terminal_clean")
        actual = set()
        with os.scandir(self.config["attempt_root"]) as entries:
            for index, entry in enumerate(itertools.islice(entries, 8193), 1):
                self.host.remaining()
                require(index <= 8192, "attempt_inventory_limit")
                if not entry.name.startswith("."):
                    actual.add(entry.name)
        require(actual == expected, "attempt_inventory_changed")
        snapshot = read_ref(self.request["offline_snapshot"], uid=self.owner_uid)
        require(type(snapshot.get("schema_version")) is int and snapshot["schema_version"] == 1
                and snapshot.get("source") == "cosmic_persisted_character"
                and type(snapshot.get("account_logged_in")) is int and snapshot["account_logged_in"] == 0
                and type(snapshot["character"]["character_id"]) is int and type(snapshot["character"]["account_id"]) is int
                and snapshot["character"]["character_id"] == self.config["mysql"]["character_id"]
                and snapshot["character"]["account_id"] == self.config["mysql"]["account_id"], "invalid_offline_snapshot")
        self.expected_snapshot = snapshot

    def capacity(self):
        available = self.host.memory()
        require(type(available) is int and available >= self.config["min_available_bytes"], "capacity_insufficient")
        return available

    def quiet(self, *, worker_stopped=True):
        self.settings()
        self.require_stopped("world")
        if worker_stopped:
            self.require_stopped("worker")
        require(self.host.queue(self.config["queue_database"]) == 0, "queue_not_idle")
        snapshot = self.host.snapshot(self.config, self.request["operation_id"])
        require(type(snapshot.get("account_logged_in")) is int and snapshot["account_logged_in"] == 0
                and lifecycle_same_json(snapshot.get("character"), self.expected_snapshot["character"])
                and lifecycle_same_json(snapshot.get("keymap"), self.expected_snapshot["keymap"]), "offline_snapshot_changed")
        web = self.process_identity("web")
        require(web == self.request["web_instance"], "web_instance_changed")
        status = self.host.browser(self.config["admin_socket"], web["pid"], self.config["services"]["web"]["uid"])
        session, bridge = status.get("session", {}), status.get("bridge", {})
        run = bridge.get("run") or {}
        require(session.get("state") == session.get("desiredPage") == "waiting"
                and session.get("captureState") == "idle"
                and all(session.get(key) is True for key in ("fresh", "pinned", "artifactsSettled"))
                and run.get("id") == self.request["browser_run_id"]
                and run.get("status") in ("idle", "completed", "failed", "timed_out", "cancelled")
                and run.get("workerActive") is False and run.get("leaseReleasePending") is False
                and bridge.get("browserReleasePending") is False and bridge.get("quarantinedRuns") == [], "browser_not_settled")
        return {"offline_snapshot_sha256": digest(encoded(snapshot)), "observed_at_ms": self.host.now()}

    def native_boundary(self):
        raw, info = read_file(self.config["native"]["path"], maximum=self.config["native"]["max_bytes"],
                              uid=self.config["services"]["cosmic"]["uid"])
        return {"device": info.st_dev, "inode": info.st_ino, "bytes": len(raw), "sha256": digest(raw)}

    def preflight(self, handoff_ref):
        self.load_handoff(handoff_ref)
        self.verify_files()
        self.verify_world_locks()
        quiet = self.quiet()
        self.require_stopped("cosmic")
        return {"quiet": quiet, "native_boundary": self.native_boundary(), "available_bytes": self.capacity()}

    def persist(self, phase, **fields):
        require(self.serial_fd is not None and self.state is not None, "lifecycle_serialization_required")
        path = self.directory / "journal.json"
        if self.journal_sha is not None:
            raw, _ = read_file(path, uid=self.owner_uid, private=True)
            require(digest(raw) == self.journal_sha, "journal_ownership_lost")
        self.state.update(fields, phase=phase, updated_at_ms=self.host.now())
        self.state["events"].append({"sequence": len(self.state["events"]), "phase": phase, "at_ms": self.host.now()})
        atomic_json(path, self.state)
        self.journal_sha = digest(read_file(path, uid=self.owner_uid, private=True)[0])

    def publish(self, handoff_ref, report):
        self.directory = self.root / self.request["operation_id"]
        require(not os.path.lexists(self.directory), "operation_exists")
        self.state = {"schema_version": 1, "operation_id": self.request["operation_id"], "config": self.config_ref,
            "handoff": ref(handoff_ref), "status": "pending", "phase": "validated", "events": [], "preflight": report,
            "service_starts": {"cosmic": 0, "worker": 0}, "automatic_retry": False, "new_api_requests": 0, "database_mutations": False}
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=self.root))
        self.state["events"].append({"sequence": 0, "phase": "validated", "at_ms": self.host.now()})
        atomic_json(staging / "journal.json", self.state)
        publish_attempt(staging, self.directory)
        self.journal_sha = digest(read_file(self.directory / "journal.json", uid=self.owner_uid, private=True)[0])

    def require_no_pending(self):
        count = 0
        with os.scandir(self.root) as entries:
            for index, entry in enumerate(itertools.islice(entries, 8193), 1):
                self.host.remaining()
                require(index <= 8192, "lifecycle_inventory_invalid")
                if entry.name.startswith("."):
                    continue
                count += 1
                require(count <= 4096 and ID.fullmatch(entry.name), "lifecycle_inventory_invalid")
                value = full_client_score.parse_json(read_file(Path(entry.path) / "journal.json", uid=self.owner_uid, private=True)[0])
                require(value.get("operation_id") == entry.name and value.get("status") == "completed", "reconciliation_required")

    def start_service(self, role):
        require(role in ("cosmic", "worker") and self.state["service_starts"][role] == 0, "service_start_replay_forbidden")
        self.require_stopped(role)
        if role == "cosmic":
            self.verify_world_locks()
        else:
            self.verify_world_locks()
            self.same_cosmic()
        self.state["service_starts"][role] = 1
        self.persist(role + "_start_pending", **{role + "_start": {"intent_at_ms": self.host.now(),
                     "previous_invocation_id": self.request["stopped_invocations"][role]}})
        if role == "worker":
            self.close_world_locks()
            require(not self.world_fds and self.serial_fd is not None, "worker_start_locks_not_closed")
            self.require_stopped("worker"); self.same_cosmic()
        self.host.command([self.config["commands"]["systemctl"]["path"], "--job-mode=fail", "start",
                           self.config["services"][role]["unit"]])
        observed = self.process_identity(role)
        require(observed["invocation_id"] != self.request["stopped_invocations"][role], "fresh_instance_missing")
        self.persist(role + "_observed", **{role: observed})

    def await_native(self):
        end = time.monotonic() + self.host.remaining(self.config["limits"]["ready_seconds"])
        retryable = {"native_fd_not_owned", "native_log_changed", "native_online_marker_missing", "native_ports_missing"}
        while True:
            self.verify_world_locks(); self.same_cosmic()
            try:
                receipt = self.host.native(self.state["cosmic"]["pid"], self.config["native"],
                    self.state["preflight"]["native_boundary"], self.state["cosmic_start"]["intent_at_ms"])
                self.same_cosmic()
                return receipt
            except LifecycleError as error:
                self.last_readiness = {"code": str(error), "at_ms": self.host.now()}
                if str(error) not in retryable or time.monotonic() >= end:
                    raise
                time.sleep(min(.2, self.host.remaining()))

    def worker_idle(self):
        self.same_cosmic()
        require(self.process_identity("worker") == self.state["worker"], "worker_instance_changed")
        require(not self.host.process(self.state["worker"]["pid"])["children"], "worker_child_active")
        for role in ("world", "queue", "runner"):
            pin = self.config["locks"][role]
            expected = [self.state["worker"]["pid"]] if role != "runner" else []
            require(self.host.lock_owners(pin) == expected, "worker_lock_owner_pending")
        require(self.host.queue(self.config["queue_database"]) == 0, "queue_not_idle")
        path = Path(self.config["worker_receipt_directory"]) / (self.state["worker"]["invocation_id"] + ".json")
        if not path.exists():
            raise LifecycleError("worker_receipt_pending")
        raw, _ = read_file(path, uid=self.config["services"]["worker"]["uid"], private=True, maximum=65536)
        receipt = full_client_score.parse_json(raw)
        object_fields(receipt, ("schema_version", "kind", "boot_id", "worker", "cosmic_before", "cosmic_after",
            "worker_source_sha256", "locks", "queue_pending", "trials_claimed", "observed_at_ms"), "worker_receipt_invalid")
        worker = self.config["services"]["worker"]
        source = next(item["sha256"] for item in worker["files"] if item["path"] == worker["argv"][1])
        locks = {key: {name: self.config["locks"][key][name] for name in ("path", "device", "inode")}
                 for key in ("world", "queue")}
        instance(receipt["worker"]); instance(receipt["cosmic_before"]); instance(receipt["cosmic_after"])
        require(type(receipt["schema_version"]) is int and receipt["schema_version"] == 1
                and receipt["kind"] == "normal_worker_first_idle"
                and receipt["boot_id"] == self.request["boot_id"] and receipt["worker"] == self.state["worker"]
                and receipt["cosmic_before"] == receipt["cosmic_after"] == self.state["cosmic"]
                and receipt["worker_source_sha256"] == source and lifecycle_same_json(receipt["locks"], locks)
                and type(receipt["queue_pending"]) is int and receipt["queue_pending"] == 0
                and type(receipt["trials_claimed"]) is int and receipt["trials_claimed"] == 0
                and type(receipt["observed_at_ms"]) is int
                and self.state["worker_start"]["intent_at_ms"] <= receipt["observed_at_ms"] <= self.host.now(),
                "worker_receipt_mismatch")
        self.same_cosmic()
        return {"path": str(path), "sha256": digest(raw)}

    def finish_worker(self):
        end = time.monotonic() + self.host.remaining(self.config["limits"]["idle_seconds"])
        while True:
            try:
                receipt = self.worker_idle()
                break
            except LifecycleError as error:
                if str(error) not in ("worker_child_active", "worker_lock_owner_pending", "worker_receipt_pending") or time.monotonic() >= end:
                    raise
                time.sleep(min(.1, self.host.remaining()))
        self.verify_handoff_evidence(); self.verify_files(); self.quiet(worker_stopped=False)
        require(self.worker_idle() == receipt, "worker_receipt_changed")
        self.persist("complete", status="completed", first_idle=receipt, cosmic_restarted=False)

    def continue_under_locks(self):
        self.verify_world_locks(); self.quiet()
        if "cosmic_start" not in self.state:
            self.require_stopped("cosmic"); self.capacity()
            self.state["preflight"]["native_boundary"] = self.native_boundary()
            self.start_service("cosmic")
        require("cosmic" in self.state, "uncertain_cosmic_start_requires_observation")
        self.same_cosmic()
        self.persist("cosmic_ready", native_ready=self.await_native())
        self.quiet(); self.same_cosmic(); self.capacity(); self.verify_world_locks()
        # Intent precedes the deliberate lock handoff. No surviving command guard
        # retains these three descriptions; only the lifecycle lock remains.
        self.start_service("worker")
        self.finish_worker()

    def failed(self, error):
        if self.state is not None and self.journal_sha is not None:
            code = str(error) if isinstance(error, LifecycleError) else "lifecycle_operation_failed"
            try:
                self.persist("operator_review_required", status="failed", failure={"code": code,
                    "interrupted_phase": self.state["phase"], "last_readiness": self.last_readiness})
            except Exception:
                pass  # Never replace another owner's journal or erase the original intent.

    def start(self, handoff_ref, *, check_only=False):
        self.begin_deadline()
        with self.serialized():
            self.require_no_pending(); self.acquire_world_locks()
            report = self.preflight(handoff_ref)
            if check_only:
                return {"ready": True, "operation_id": self.request["operation_id"], "available_bytes": report["available_bytes"]}
            self.publish(handoff_ref, report)
            try:
                self.continue_under_locks()
            except BaseException as error:
                self.failed(error)
                raise
            return self.summary()

    def adopt_observation(self, role, reference):
        require(reference is not None, "uncertain_start_requires_observation")
        value = read_ref(reference, uid=self.owner_uid)
        object_fields(value, ("schema_version", "operation_id", "boot_id", "role", "instance"), "invalid_instance_observation")
        require(type(value["schema_version"]) is int and value["schema_version"] == 1
                and value["operation_id"] == self.state["operation_id"]
                and value["boot_id"] == self.request["boot_id"] and value["role"] == role, "invalid_instance_observation")
        expected = instance(value["instance"])
        require(self.process_identity(role) == expected
                and expected["invocation_id"] != self.request["stopped_invocations"][role], "observed_instance_changed")
        self.persist(role + "_reconciled", **{role: expected, role + "_observation": ref(reference)})

    def reconcile(self, journal_ref, observation_ref=None):
        self.begin_deadline()
        with self.serialized():
            state = read_ref(journal_ref, uid=self.owner_uid)
            require(type(state.get("schema_version")) is int and state["schema_version"] == 1
                    and isinstance(state.get("operation_id"), str)
                    and ID.fullmatch(state["operation_id"]) and state.get("status") in ("pending", "failed")
                    and state.get("config") == self.config_ref, "invalid_reconciliation_journal")
            self.directory = self.root / state["operation_id"]
            require(journal_ref["path"] == str(self.directory / "journal.json"), "journal_outside_state_root")
            require(isinstance(state.get("events"), list) and state["events"]
                    and all(type(event.get("sequence")) is int and event["sequence"] == i
                            for i, event in enumerate(state["events"])), "invalid_journal_events")
            self.state = state; self.journal_sha = journal_ref["sha256"]
            self.load_handoff(state["handoff"])
            require(self.request["operation_id"] == state["operation_id"], "handoff_operation_changed")
            object_fields(state.get("service_starts"), ("cosmic", "worker"), "invalid_start_counters")
            for role in ("cosmic", "worker"):
                integer(state["service_starts"][role], 0, 1, "invalid_start_counters")
                require((role + "_start" in state) == bool(state["service_starts"][role]), "invalid_start_counters")
                if role + "_start" in state:
                    start = object_fields(state[role + "_start"], ("intent_at_ms", "previous_invocation_id"), "invalid_start_receipt")
                    integer(start["intent_at_ms"], 0, 2**53 - 1, "invalid_start_receipt")
                    require(start["previous_invocation_id"] == self.request["stopped_invocations"][role], "invalid_start_receipt")
                if role in state:
                    instance(state[role])
                    require(role + "_start" in state, "invalid_start_receipt")
            self.verify_files()
            try:
                if "worker_start" in state:
                    # Worker may already own the world locks; observation-only
                    # completion must never acquire/take over those descriptions.
                    require("cosmic" in state, "cosmic_identity_missing")
                    self.same_cosmic()
                    if "worker" not in state:
                        self.adopt_observation("worker", observation_ref)
                    self.finish_worker()
                else:
                    self.acquire_world_locks(); self.quiet()
                    if "cosmic_start" in state and "cosmic" not in state:
                        self.adopt_observation("cosmic", observation_ref)
                    self.continue_under_locks()
            except BaseException as error:
                self.failed(error)
                raise
            return self.summary()

    def summary(self):
        return {"operation_id": self.state["operation_id"], "status": self.state["status"], "phase": self.state["phase"],
                "journal": {"path": str(self.directory / "journal.json"), "sha256": self.journal_sha},
                "cosmic": self.state.get("cosmic"), "worker": self.state.get("worker"),
                "new_api_requests": 0, "database_mutations": False, "automatic_retry": False}


def command_guard(argv):
    """Retain inherited lifecycle/ownership locks until all command children end."""
    child = None
    try:
        parent, alive_fd = int(argv[0]), int(argv[1])
        descriptors = [int(value) for value in argv[2].split(",")] if argv[2] else []
        timeout = float(argv[3])
        cpu_limits = (int(argv[4]), int(argv[5]))
        require(0 < timeout <= 300 and len(descriptors) <= 4 and len(set(descriptors)) == len(descriptors)
                and all(value >= 3 and value != alive_fd for value in descriptors)
                and len(argv) >= 7 and Path(argv[6]).is_absolute(), "invalid_guard_request")
        if os.getppid() != parent:
            return 126
        require(sys.platform.startswith("linux"), "linux_required")
        # This retaining process must not die from inherited CPU exhaustion while
        # an unkillable descendant still owns a mutation. Failure to lift the cap
        # is a prerequisite refusal before any command launches.
        resource.setrlimit(resource.RLIMIT_CPU, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
        libc = ctypes.CDLL(None, use_errno=True)
        require(libc.prctl(36, 1, 0, 0, 0) == 0, "subreaper_unavailable")
        resource.setrlimit(resource.RLIMIT_FSIZE, (JSON_LIMIT + 1, JSON_LIMIT + 1))
        def interrupted(_signal, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(alive_fd, selectors.EVENT_READ)
            if os.getppid() != parent or selector.select(0):
                return 126
            child_argv = [sys.executable, str(Path(__file__).resolve()), "_command_exec",
                          *map(str, cpu_limits), *argv[6:]]
            child = subprocess.Popen(child_argv, stdin=sys.stdin.buffer, stdout=sys.stdout.buffer,
                stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "SYSTEMD_COLORS": "0"})
            while child.poll() is None:
                left = deadline - time.monotonic()
                if left <= 0 or os.getppid() != parent or selector.select(min(left, .05)):
                    return 124
            return child.returncode if child.returncode >= 0 else 125
    except (OSError, ValueError, IndexError, KeyboardInterrupt):
        return 126
    finally:
        if child is not None:
            full_client_trial._stop_backend_group(child)


def command_exec(argv):
    """Restore bounded command CPU limits outside the lock-retaining guard."""
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (int(argv[0]), int(argv[1])))
        require(len(argv) >= 3 and Path(argv[2]).is_absolute(), "invalid_guard_request")
        os.execv(argv[2], argv[2:])
    except (OSError, ValueError, IndexError):
        return 126


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "start"):
        command = commands.add_parser(name)
        command.add_argument("--request", type=Path, required=True)
        command.add_argument("--sha256", required=True, help="Expected immutable handoff hash")
    command = commands.add_parser("reconcile")
    command.add_argument("--journal", type=Path, required=True)
    command.add_argument("--sha256", required=True, help="Exact interrupted journal hash")
    command.add_argument("--observation", type=Path)
    command.add_argument("--observation-sha256")
    args = parser.parse_args(argv)
    try:
        require(sys.platform.startswith("linux") and os.geteuid() == 0, "linux_root_required")
        raw, _ = read_file(args.config, maximum=1024 * 1024, uid=0, private=True)
        config = validate_config(full_client_score.parse_json(raw))
        limits = config["limits"]
        resource.setrlimit(resource.RLIMIT_AS, (limits["memory_bytes"], limits["memory_bytes"]))
        resource.setrlimit(resource.RLIMIT_CPU, (limits["cpu_seconds"], limits["cpu_seconds"]))
        allowed = sorted(os.sched_getaffinity(0))
        os.sched_setaffinity(0, set(allowed[:limits["cpus"]]))
        signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(LifecycleError("lifecycle_deadline")))
        signal.alarm(limits["total_seconds"])
        lifecycle = NormalLifecycle(config, {"path": str(args.config), "sha256": digest(raw)})
        if args.command == "reconcile":
            require(bool(args.observation) == bool(args.observation_sha256), "observation_hash_required")
            observation = {"path": str(args.observation), "sha256": args.observation_sha256} if args.observation else None
            result = lifecycle.reconcile({"path": str(args.journal), "sha256": args.sha256}, observation)
        else:
            result = lifecycle.start({"path": str(args.request), "sha256": args.sha256}, check_only=args.command == "check")
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except LifecycleError as error:
        print(json.dumps({"ready": False, "error": str(error), "automatic_retry": False}))
        return 1
    except full_client_trial.TrialError as error:
        code = "lock_conflict" if str(error) == "lock_conflict" else "lifecycle_state_invalid"
        print(json.dumps({"ready": False, "error": code, "automatic_retry": False}))
        return 1
    except (OSError, ValueError, TypeError, KeyError, StopIteration, subprocess.SubprocessError):
        print(json.dumps({"ready": False, "error": "lifecycle_operation_failed", "automatic_retry": False}))
        return 1


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    raise SystemExit(command_guard(sys.argv[2:]) if mode == "_command_guard"
                     else command_exec(sys.argv[2:]) if mode == "_command_exec" else main())
