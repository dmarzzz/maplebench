#!/usr/bin/env python3
"""Read-only Linux full-client health check; HTTP success is not world readiness."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import socket
import subprocess
import time
import urllib.parse
import urllib.request

UNIT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}\Z")
PROPERTIES = ("ActiveState", "SubState", "MainPID", "Result",
              "ActiveEnterTimestampMonotonic", "RuntimeMaxUSec")


def validate_config(value):
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("invalid_config")
    names = value.get("services", {})
    if set(names) != {"world", "web", "cosmic", "worker"} or any(
            not isinstance(v, str) or not UNIT.fullmatch(v) for v in names.values()):
        raise ValueError("invalid_services")
    if len(set(names.values())) != 4:
        raise ValueError("duplicate_services")
    for field in ("world_lock", "queue_lock"):
        if not isinstance(value.get(field), str) or not Path(value[field]).is_absolute():
            raise ValueError("invalid_lock_paths")
    if Path(value["world_lock"]).resolve() == Path(value["queue_lock"]).resolve():
        raise ValueError("duplicate_locks")
    ports = value.get("ports")
    if not isinstance(ports, list) or not ports or len(ports) > 16 or any(
            type(p) is not int or not 1024 <= p <= 65535 for p in ports) or len(set(ports)) != len(ports):
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


def check(config):
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="Private host configuration JSON")
    args = parser.parse_args(argv)
    try:
        if args.config.stat().st_size > 65536:
            raise ValueError("oversized_config")
        result = check(json.loads(args.config.read_text()))
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        result = {"ready": False, "checks": ["health_probe_failed"]}
    print(json.dumps(result, allow_nan=False))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
