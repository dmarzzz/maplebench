#!/usr/bin/env python3
"""Read-only Linux health, with separate legacy and normal-worker contracts.

Schema 1 (optional mode='leased-preview') preserves the original leased-world
checks. Schema 2 requires mode='normal-worker', the same four service names,
world_lock/queue_lock, queue_database, admin_socket, game_ports, base_url, and
processes for worker/web/cosmic. Each process binding contains exact executable,
argv, uid and working_directory. min_available_mib is optional. game_ports are
native Cosmic listeners; the base_url port must belong to the web process.

Normal health is an operational snapshot, not frozen-source verification or
authority to reset/start a trial. Durable-trial mode is deliberately unsupported:
the relay alone cannot prove account state or the runner's ownership context.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import math
import os
from pathlib import Path
import re
import resource
import socket
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

UNIT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}\Z")
PROPERTIES = ("ActiveState", "SubState", "MainPID", "Result",
              "ActiveEnterTimestampMonotonic", "RuntimeMaxUSec")
NORMAL_PROPERTIES = PROPERTIES + ("LoadState", "InvocationID", "NeedDaemonReload")
MAX_FDS = 4096
MAX_TABLE = 2 * 1024 * 1024
MAX_STATUS = 256 * 1024


class HealthError(ValueError):
    """Only fixed local codes, never host command output or private paths."""


def require(value, code):
    if not value:
        raise HealthError(code)


def absolute_path(value):
    return (isinstance(value, str) and 0 < len(value) <= 4096 and "\x00" not in value
            and Path(value).is_absolute() and ".." not in Path(value).parts)


def valid_ports(value):
    return (isinstance(value, list) and 0 < len(value) <= 16
            and all(type(p) is int and 1024 <= p <= 65535 for p in value)
            and len(set(value)) == len(value))


def finite_number(value):
    return type(value) in (int, float) and 0 <= value <= 2**53 - 1 and math.isfinite(value)


def validate_config(value):
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] not in (1, 2):
        raise ValueError("invalid_config")
    version = value["schema_version"]
    require(value.get("mode", "leased-preview" if version == 1 else None)
            == ("leased-preview" if version == 1 else "normal-worker"), "unsupported_health_mode")
    names = value.get("services", {})
    if not isinstance(names, dict) or set(names) != {"world", "web", "cosmic", "worker"} or any(
            not isinstance(v, str) or not UNIT.fullmatch(v) for v in names.values()):
        raise ValueError("invalid_services")
    if len(set(names.values())) != 4:
        raise ValueError("duplicate_services")
    for field in ("world_lock", "queue_lock"):
        if not isinstance(value.get(field), str) or not Path(value[field]).is_absolute():
            raise ValueError("invalid_lock_paths")
    if Path(value["world_lock"]).resolve() == Path(value["queue_lock"]).resolve():
        raise ValueError("duplicate_locks")
    ports = value.get("ports" if version == 1 else "game_ports")
    if not valid_ports(ports):
        raise ValueError("invalid_ports")
    parsed = urllib.parse.urlsplit(value.get("base_url", ""))
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or not parsed.port):
        raise ValueError("invalid_loopback_url")
    for name, default in (("min_available_mib", 1024), ("min_lease_seconds", 180)):
        item = value.get(name, default)
        if type(item) is not int or not 1 <= item <= 1_000_000:
            raise ValueError("invalid_health_threshold")
    if version == 2:
        required = {"schema_version", "mode", "services", "world_lock", "queue_lock", "queue_database",
                    "admin_socket", "game_ports", "base_url", "processes"}
        require(required <= set(value) <= required | {"min_available_mib"}, "invalid_normal_config_fields")
        require(all(absolute_path(value[name]) for name in
                    ("world_lock", "queue_lock", "queue_database", "admin_socket")), "invalid_normal_paths")
        require(parsed.port not in ports and 1024 <= parsed.port <= 65535, "invalid_web_port")
        require(parsed.hostname == "127.0.0.1", "normal_url_requires_numeric_loopback")
        processes = value["processes"]
        require(isinstance(processes, dict) and set(processes) == {"worker", "web", "cosmic"}, "invalid_process_bindings")
        for binding in processes.values():
            require(isinstance(binding, dict) and set(binding) == {"executable", "argv", "uid", "working_directory"}
                    and all(absolute_path(binding[key]) for key in ("executable", "working_directory"))
                    and type(binding["uid"]) is int and 0 <= binding["uid"] < 2**31
                    and isinstance(binding["argv"], list) and 0 < len(binding["argv"]) <= 128
                    and all(isinstance(arg, str) and 0 < len(arg) <= 4096 and "\x00" not in arg
                            for arg in binding["argv"]), "invalid_process_binding")
    return value


def duration_seconds(value):
    """Parse systemd's printed timespan, refusing unknown or unlimited leases."""
    if not isinstance(value, str) or value in {"infinity", "[not set]", ""}:
        return None
    units = {"us": .000001, "ms": .001, "s": 1, "min": 60, "h": 3600, "d": 86400}
    tokens = value.split()
    total = 0.0
    for token in tokens:
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(us|ms|s|min|h|d)", token)
        if not match:
            return None
        total += float(match[1]) * units[match[2]]
    return total if math.isfinite(total) else None


def assess(config, services, locks, ports, available_mib, now_boot_seconds, relay):
    """Pure readiness calculation shared by CLI and fault-injection tests."""
    require(type(config.get("schema_version")) is int and config["schema_version"] == 1
            and config.get("mode", "leased-preview") == "leased-preview",
            "legacy_assessment_requires_schema_one")
    problems = []
    for name in ("world", "web", "cosmic"):
        service = services.get(name, {})
        if (service.get("ActiveState") != "active" or service.get("SubState") != "running"
                or not str(service.get("MainPID", "")).isdigit() or int(service.get("MainPID", 0)) <= 0):
            problems.append(name + "_inactive")
    if services.get("worker", {}).get("ActiveState") != "inactive":
        problems.append("worker_not_paused")
    world = services.get("world", {})
    try:
        owner = int(world.get("MainPID", 0))
        started = int(world["ActiveEnterTimestampMonotonic"]) / 1_000_000
        lease = duration_seconds(world.get("RuntimeMaxUSec"))
        remaining = lease - (now_boot_seconds - started) if lease is not None and started > 0 else None
    except (KeyError, TypeError, ValueError):
        owner, remaining = 0, None
    lock_ok = owner > 0 and all(
        [int(row.get("pid", -1)) for row in locks if row.get("path") == config[field]] == [owner]
        for field in ("world_lock", "queue_lock"))
    if not lock_ok:
        problems.append("lock_ownership_mismatch")
    if not all(ports.get(str(p)) is True for p in config["ports"]):
        problems.append("listener_unavailable")
    if remaining is None or remaining < config.get("min_lease_seconds", 180):
        problems.append("lease_insufficient")
    if available_mib is None or available_mib < config.get("min_available_mib", 1024):
        problems.append("memory_insufficient")
    infrastructure_ready = not problems
    client_ready = (isinstance(relay, dict) and relay.get("fresh") is True
                    and isinstance(relay.get("run"), dict))
    controller_idle = client_ready and relay["run"].get("status") in {"idle", "completed", "failed"}
    artifacts_saved = (client_ready and (not relay["run"].get("id") or
                       (relay["run"].get("recordingStatus") == "saved"
                        and relay["run"].get("evidenceStatus") == "saved")))
    if not client_ready:
        problems.append("client_not_fresh")
    elif not controller_idle:
        problems.append("controller_busy")
    elif not artifacts_saved:
        problems.append("run_artifacts_incomplete")
    return {"schema_version": 1, "ready": not problems,
            "infrastructure_ready": infrastructure_ready, "client_ready": client_ready,
            "controller_idle": controller_idle, "artifacts_saved": artifacts_saved, "checks": problems,
            "lease_remaining_seconds": max(0, round(remaining)) if remaining is not None else None,
            "available_memory_mib": available_mib, "ports": ports,
            "services": {name: {key: state.get(key) for key in ("ActiveState", "SubState", "Result")}
                         for name, state in services.items()},
            "scope": "Readiness only; does not prove semantic inputs, scoring, or permission to reset."}


def _check_legacy(config):
    validate_config(config)
    services = {}
    for name, unit in config["services"].items():
        args = ["systemctl", "show", unit]
        for prop in PROPERTIES:
            args.extend(["-p", prop])
        raw = subprocess.check_output(args, text=True, timeout=5, stderr=subprocess.DEVNULL)
        services[name] = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    raw = subprocess.check_output(["lslocks", "--json", "-o", "PID,PATH"], timeout=5,
                                  stderr=subprocess.DEVNULL)
    locks = json.loads(raw).get("locks", [])
    ports = {}
    for port in config["ports"]:
        with socket.socket() as sock:
            sock.settimeout(.5)
            ports[str(port)] = sock.connect_ex(("127.0.0.1", port)) == 0
    available = next((int(line.split()[1]) // 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                      if line.startswith("MemAvailable:")), None)
    relay = None
    try:
        # No ambient proxy: a host health check must never send control metadata
        # to a configured external HTTP proxy or follow a remote redirect.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(config["base_url"].rstrip("/") + "/control/status", timeout=3) as response:
            raw = response.read(65537)
            if len(raw) <= 65536:
                relay = json.loads(raw)
    except (OSError, ValueError):
        pass
    # systemd activation timestamps use CLOCK_MONOTONIC, excluding suspend time.
    return assess(config, services, locks, ports, available, time.monotonic(), relay)


def read_limited(path, maximum):
    """Bound proc/config reads, including proc files whose reported size is zero."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), "invalid_probe_file")
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(maximum + 1)
        require(len(raw) <= maximum, "probe_read_limit")
        return raw
    finally:
        os.close(fd)


def parse_json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "duplicate_json_key")
            value[key] = item
        return value
    def nonfinite(_):
        raise ValueError("nonfinite_json")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def remaining(deadline, cap=3):
    left = deadline - time.monotonic()
    require(left > 0, "health_probe_timeout")
    return min(left, cap)


def unit_states(config, deadline):
    result = {}
    def limit_output():
        resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
    for role, unit in config["services"].items():
        with tempfile.TemporaryFile() as output:
            process = subprocess.run(["/usr/bin/systemctl", "show", unit, "--no-pager",
                "--property=" + ",".join(NORMAL_PROPERTIES)], stdout=output, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, timeout=remaining(deadline), check=False,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, preexec_fn=limit_output)
            require(process.returncode == 0 and output.tell() < 65536, "service_probe_failed")
            output.seek(0)
            result[role] = dict(line.split("=", 1) for line in output.read().decode().splitlines() if "=" in line)
    return result


def process_start(pid):
    raw = read_limited(Path(f"/proc/{pid}/stat"), 65536)
    require(int(raw.split(b"(", 1)[0]) == pid, "process_identity_changed")
    fields = raw.rsplit(b")", 1)[1].split()
    require(len(fields) > 19, "invalid_process_stat")
    return int(fields[19])


def process_identity(service, binding):
    pid = int(service.get("MainPID", 0))
    require(pid > 0, "process_unavailable")
    before = process_start(pid)
    root = Path(f"/proc/{pid}")
    raw = read_limited(root / "cmdline", 128 * 1024)
    require(raw.endswith(b"\0"), "invalid_process_arguments")
    argv = [item.decode() for item in raw[:-1].split(b"\0")]
    status = read_limited(root / "status", 65536).decode()
    uid_rows = [line.split()[1:] for line in status.splitlines() if line.startswith("Uid:")]
    require(len(uid_rows) == 1 and len(uid_rows[0]) == 4, "invalid_process_user")
    actual = {"pid": pid, "start_ticks": before,
              "executable": os.readlink(root / "exe"), "working_directory": os.readlink(root / "cwd"),
              "argv": argv, "uids": [int(value) for value in uid_rows[0]]}
    require(before == process_start(pid), "process_identity_changed")
    require(actual["executable"] == binding["executable"] and argv == binding["argv"]
            and actual["working_directory"] == binding["working_directory"]
            and actual["uids"] == [binding["uid"]] * 4, "process_binding_mismatch")
    return actual


def owned_listeners(pid):
    inodes = set()
    with os.scandir(f"/proc/{pid}/fd") as entries:
        for index, entry in enumerate(entries):
            require(index < MAX_FDS, "process_fd_limit")
            try:
                target = os.readlink(entry.path)
            except FileNotFoundError:
                continue  # A descriptor closed during an otherwise stable PID.
            match = re.fullmatch(r"socket:\[(\d+)\]", target)
            if match:
                inodes.add(match[1])
    ports = set()
    for name in ("tcp", "tcp6"):
        raw = read_limited(Path(f"/proc/{pid}/net/{name}"), MAX_TABLE).decode()
        for line in raw.splitlines()[1:]:
            fields = line.split()
            if len(fields) > 9 and fields[3] == "0A" and fields[9] in inodes:
                ports.add(int(fields[1].rsplit(":", 1)[1], 16))
    return ports


def lock_identities(config):
    identities = {}
    for role in ("world", "queue"):
        path = Path(config[role + "_lock"])
        require(path.resolve(strict=True) == path, "noncanonical_lock")
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode), "invalid_existing_lock")
        identities[role] = (os.major(info.st_dev), os.minor(info.st_dev), info.st_ino)
    require(len(set(identities.values())) == 2, "duplicate_lock_inodes")
    return identities


def kernel_lock_owners(raw, identities):
    owners = {name: [] for name in identities}
    for line in raw.decode().splitlines():
        fields = line.split()
        if len(fields) < 8 or fields[1] == "->":
            continue  # Waiting entries do not own a lock.
        try:
            device, minor, inode = fields[5].split(":")
            identity = (int(device, 16), int(minor, 16), int(inode))
        except (ValueError, IndexError):
            raise HealthError("invalid_kernel_lock_table") from None
        for name, expected in identities.items():
            if identity == expected:
                require(fields[1:4] == ["FLOCK", "ADVISORY", "WRITE"]
                        and fields[6:] == ["0", "EOF"], "unexpected_world_lock_kind")
                owners[name].append(int(fields[4]))
    return owners


def queue_pending(path, deadline):
    path = Path(path)
    require(path.resolve(strict=True) == path and stat.S_ISREG(path.lstat().st_mode), "invalid_queue_database")
    before = path.stat()
    # mode=ro never creates a missing database. query_only also disallows writes
    # through the connection; immutable=1 would incorrectly ignore a live WAL.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=remaining(deadline, 2))) as database:
        database.execute("PRAGMA query_only=ON")
        database.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        count = database.execute("SELECT count(*) FROM trials WHERE status IN ('queued','running','rendering')").fetchone()[0]
    after = path.stat()
    require((before.st_dev, before.st_ino) == (after.st_dev, after.st_ino), "queue_database_replaced")
    require(type(count) is int and count >= 0, "invalid_queue_count")
    return count


def public_status(base_url, deadline):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(base_url.rstrip("/") + "/control/status", timeout=remaining(deadline)) as response:
        raw = response.read(MAX_STATUS + 1)
    require(len(raw) <= MAX_STATUS, "web_status_limit")
    value = parse_json(raw)
    require(isinstance(value, dict), "invalid_web_status")
    return value


def admin_status(path, web_process, deadline):
    path = Path(path)
    require(path.parent.resolve(strict=True) == path.parent and len(os.fsencode(path)) <= 100,
            "invalid_admin_socket")
    before, parent = path.lstat(), path.parent.lstat()
    uid = web_process["uids"][0]
    require(stat.S_ISSOCK(before.st_mode) and stat.S_IMODE(before.st_mode) == 0o600
            and stat.S_ISDIR(parent.st_mode) and stat.S_IMODE(parent.st_mode) == 0o700
            and before.st_uid == parent.st_uid == uid, "untrusted_admin_socket")
    require(hasattr(socket, "SO_PEERCRED"), "admin_peer_identity_unavailable")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(remaining(deadline)); client.connect(str(path))
        peer_pid, peer_uid, _ = struct.unpack("3i", client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        require(peer_pid == web_process["pid"] and peer_uid == uid, "admin_peer_mismatch")
        client.sendall(b'{"op":"status"}\n')
        raw = bytearray()
        while not raw.endswith(b"\n"):
            client.settimeout(remaining(deadline))
            block = client.recv(min(65536, MAX_STATUS + 1 - len(raw)))
            require(block and len(raw) + len(block) <= MAX_STATUS, "admin_status_limit")
            raw.extend(block)
    after = path.lstat()
    require((before.st_dev, before.st_ino, before.st_uid, before.st_mode)
            == (after.st_dev, after.st_ino, after.st_uid, after.st_mode), "admin_socket_changed")
    value = parse_json(raw)
    require(isinstance(value, dict) and value.get("ok") is True and isinstance(value.get("result"), dict),
            "invalid_admin_status")
    return value["result"]


def assess_normal(config, services, processes, locks, ports, available_mib, queue_count, relay, admin, status_age_ms=0):
    """Schema 2 accepts only measured process/owner probes, never schema-1 leases."""
    require(type(config.get("schema_version")) is int and config["schema_version"] == 2
            and config.get("mode") == "normal-worker",
            "normal_assessment_requires_schema_two")
    problems = []
    for name in ("worker", "web", "cosmic"):
        service = services.get(name, {})
        pid = service.get("MainPID")
        valid_pid = isinstance(pid, str) and pid.isdigit() and 0 < int(pid) < 2**31
        if (service.get("LoadState") != "loaded" or service.get("ActiveState") != "active"
                or service.get("SubState") != "running" or service.get("NeedDaemonReload") != "no"
                or not re.fullmatch(r"[a-f0-9]{32}", str(service.get("InvocationID", "")))
                or not valid_pid or type(processes.get(name, {}).get("pid")) is not int
                or processes[name]["pid"] != int(pid)):
            problems.append(name + "_identity_unverified")
    world = services.get("world", {})
    if world.get("ActiveState") not in ("inactive", "failed") or world.get("MainPID") != "0":
        problems.append("legacy_world_not_stopped")
    owner = processes.get("worker", {}).get("pid")
    if type(owner) is not int or owner <= 0 or any(locks.get(role) != [owner] for role in ("world", "queue")):
        problems.append("worker_lock_ownership_mismatch")
    if not all(ports.get(str(port)) is True for port in config["game_ports"]):
        problems.append("native_listener_unowned")
    web_port = urllib.parse.urlsplit(config["base_url"]).port
    if ports.get(str(web_port)) is not True:
        problems.append("web_listener_unowned")
    if type(queue_count) is not int or queue_count != 0:
        problems.append("queue_not_idle")
    if type(available_mib) is not int or available_mib < config.get("min_available_mib", 1024):
        problems.append("memory_insufficient")
    if not isinstance(relay, dict):
        problems.append("web_status_unavailable")
    infrastructure_ready = not problems
    bridge = admin.get("bridge") if isinstance(admin, dict) else None
    session = admin.get("session") if isinstance(admin, dict) else None
    run = bridge.get("run") if isinstance(bridge, dict) else None
    if not all(isinstance(value, dict) for value in (bridge, session, run)):
        problems.append("private_quiescence_unavailable")
        bridge, session, run = {}, {}, {}
    quiescent = (run.get("status") in ("idle", "completed", "failed") and run.get("workerActive") is False
        and run.get("leaseReleasePending") is False and bridge.get("browserReleasePending") is False
        and bridge.get("quarantinedRuns") == [] and session.get("artifactsSettled") is True
        and session.get("captureState") == "idle")
    if not quiescent:
        problems.append("controller_quiescence_unproven")
    public_run = relay.get("run") if isinstance(relay, dict) else None
    if not isinstance(public_run, dict) or any(type(public_run.get(key)) is not type(run.get(key)) or public_run.get(key) != run.get(key)
            for key in ("id", "status", "workerActive", "leaseReleasePending")):
        problems.append("web_admin_state_mismatch")
    valid_age = finite_number(status_age_ms)
    session_fresh = (valid_age and session.get("fresh") is True and type(session.get("clientSeenMs")) is int
                     and 0 <= session["clientSeenMs"] + status_age_ms < 3000
                     and bridge.get("rendererConnected") is True)
    waiting = session_fresh and session.get("state") == "waiting"
    observation = admin.get("observation") if isinstance(admin, dict) else None
    connected = (session_fresh and session.get("state") == "connected" and bridge.get("fresh") is True
        and isinstance(observation, dict) and observation.get("ready") is True
        and all(finite_number(observation.get(key))
                and 0 <= observation[key] + status_age_ms < 1500 for key in ("ageMs", "renderAgeMs")))
    browser_state = "healthy_waiting" if waiting else "healthy_rendering" if connected else "stale_or_transitioning"
    if not (waiting or connected):
        problems.append("browser_stale_or_transitioning")
    return {"schema_version": 2, "mode": "normal-worker", "ready": not problems,
        "infrastructure_ready": infrastructure_ready, "controller_quiescent": quiescent,
        "browser_state": browser_state, "renderer_active": connected, "queue_idle": type(queue_count) is int and queue_count == 0,
        "available_memory_mib": available_mib, "checks": problems, "ports": ports,
        "services": {name: {key: value.get(key) for key in ("ActiveState", "SubState", "Result")}
                     for name, value in services.items()},
        "scope": "Operational normal-worker snapshot only; not frozen-source/publication verification or authorization to start/reset a trial.",
        "durable_trial_readiness": "unsupported_without_trusted_runner_account_and_ownership_context"}


def _check_normal(config):
    require(sys.platform.startswith("linux"), "linux_health_required")
    deadline = time.monotonic() + 25
    services = unit_states(config, deadline)
    processes = {role: process_identity(services[role], binding) for role, binding in config["processes"].items()}
    ids = lock_identities(config)
    locks = kernel_lock_owners(read_limited(Path("/proc/locks"), MAX_TABLE), ids)
    native_ports, web_ports = owned_listeners(processes["cosmic"]["pid"]), owned_listeners(processes["web"]["pid"])
    ports = {str(port): port in native_ports for port in config["game_ports"]}
    web_port = urllib.parse.urlsplit(config["base_url"]).port
    ports[str(web_port)] = web_port in web_ports
    available = next((int(line.split()[1]) // 1024 for line in
        read_limited(Path("/proc/meminfo"), 65536).decode().splitlines() if line.startswith("MemAvailable:")), None)
    count = queue_pending(config["queue_database"], deadline)
    # A PID, unit invocation or lock inode swap anywhere in the probe window
    # cannot yield a ready snapshot. Never acquire/unlock the live world locks.
    require(unit_states(config, deadline) == services, "service_identity_changed")
    require(all(process_identity(services[role], config["processes"][role]) == value
                for role, value in processes.items()), "process_identity_changed")
    require(lock_identities(config) == ids, "world_lock_identity_changed")
    require(kernel_lock_owners(read_limited(Path("/proc/locks"), MAX_TABLE), ids) == locks, "world_lock_owner_changed")
    relay = public_status(config["base_url"], deadline)
    requested_at = time.monotonic()
    admin = admin_status(config["admin_socket"], processes["web"], deadline)
    require(all(process_start(value["pid"]) == value["start_ticks"] for value in processes.values()), "process_identity_changed")
    require(queue_pending(config["queue_database"], deadline) == count, "queue_changed_during_probe")
    remaining(deadline)
    # Include the entire private status round trip and subsequent probe time;
    # a fresh boolean delivered too late is not a fresh browser observation.
    status_age_ms = math.ceil((time.monotonic() - requested_at) * 1000)
    return assess_normal(config, services, processes, locks, ports, available, count, relay, admin, status_age_ms)


def check(config):
    validate_config(config)
    return _check_legacy(config) if config["schema_version"] == 1 else _check_normal(config)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="Private host configuration JSON")
    args = parser.parse_args(argv)
    try:
        if args.config.stat().st_size > 65536:
            raise ValueError("oversized_config")
        result = check(parse_json(read_limited(args.config, 65536)))
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError,
            RecursionError, OverflowError, sqlite3.Error, subprocess.SubprocessError) as error:
        result = {"ready": False, "checks": [str(error) if isinstance(error, HealthError) else "health_probe_failed"]}
    print(json.dumps(result, allow_nan=False))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
