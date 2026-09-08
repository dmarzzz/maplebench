#!/usr/bin/env python3
"""Private Linux Cosmic trial backend. No live defaults or automatic API retry.

This module is deliberately deployable only by a trusted root runner. Services
remain their existing unprivileged users. Successful mocked phases are not a
claim that a live trial or a publication has been verified.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import resource
import shlex
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile

from full_client_collect import collect, DATABASE
from full_client_freeze import FreezeError, FREEZE_ERROR_CODES, HARD_LIMITS as FREEZE_HARD_LIMITS, verify_manifest
from full_client_docker import DockerBindingError, configured_command, validate_binding
from full_client_readiness import ReadinessError, observation_sha256, validate_policy
from full_client_score import (SOURCE, JSON_LIMIT, EvidenceError, parse_json, read_artifact_bytes,
                               open_verified_artifact, same_json, verify_trial_bundle)
from full_client_trial import (RELAY_ERROR_CODES, RUNTIME_ERROR_CODES, atomic_json,
                               private_directory, read_private_json, validate_spec)
import full_client_xp_windows as xp_windows

SHA = re.compile(r"[0-9a-f]{64}\Z")
RUN = re.compile(r"[0-9a-f]{32}\Z")
UNIT = re.compile(r"[A-Za-z0-9_.@-]+\.service\Z")
NATIVE_CLASS = "server/bots/MapleBenchPersistence.class"
XP_NATIVE_CLASS = "server/bots/MapleBenchXpLedger.class"
MAX_SQL = 64 * 1024 * 1024
MAX_VIDEO = 512 * 1024 * 1024
MAX_PROCESS_FDS = 4096
ENV_NAMES = ("MAPLEBENCH_TRIAL_ID", "MAPLEBENCH_SERVER_INSTANCE_ID",
             "MAPLEBENCH_PERSIST_CHARACTER_ID", "MAPLEBENCH_PERSIST_ACCOUNT_ID",
             "MAPLEBENCH_SAVE_JOURNAL")
# The navigation window includes capture tail and upload. These fixed scenario
# fields make cold-cache verification speed irrelevant to the scored session.
SETTLEMENT_POLICY = {"capture_tail_ms": 2000, "upload_after_program_ms": 5000,
                     "disconnect_after_program_ms": 5000, "logout_after_disconnect_ms": 5000}


class RuntimeErrorCode(ValueError):
    """Safe error codes; never echo subprocess output or private paths."""


def require(condition, code):
    if not condition:
        raise RuntimeErrorCode(code)


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def absolute(value):
    require(isinstance(value, str) and Path(value).is_absolute()
            and not any(c in value for c in "\x00\r\n%"), "invalid_config_path")
    path = Path(value)
    require(path.resolve() == path, "symlink_config_path")
    return path


def systemd_working_directory(value):
    # This directive consumes a scalar path, unlike ExecStart's quoted words.
    # Quoting it makes the leading quote part of the path; systemd rejects the
    # directive and stops parsing the remaining drop-in, including ExecStart.
    absolute(value)
    require(value == value.strip() and not any(ord(c) < 32 or c in '\\"' for c in value),
            "invalid_systemd_working_directory")
    return value


def ref_bytes(ref, maximum=JSON_LIMIT):
    path = absolute(ref["path"])
    require(SHA.fullmatch(ref.get("sha256", "")) is not None, "invalid_frozen_hash")
    return read_artifact_bytes(path.parent, {"path": path.name, "sha256": ref["sha256"]},
                               "frozen_input", maximum=maximum)


def save_bytes(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return {"path": path.name, "sha256": hashlib.sha256(raw).hexdigest()}


class Host:
    """Small synchronous, bounded host interface, injectable for failure tests."""
    def __init__(self):
        self.deadline = 0

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "operation_deadline")
        return remaining

    def now(self):
        return time.time_ns() // 1_000_000

    def sleep(self):
        time.sleep(min(.2, self.remaining()))

    def command(self, argv, *, data=None, maximum=JSON_LIMIT):
        # The child writes to a bounded regular file, avoiding unbounded pipe
        # buffering. The file-size rlimit applies only to this short command.
        def cap_output():
            resource.setrlimit(resource.RLIMIT_FSIZE, (maximum, maximum))
        with tempfile.TemporaryFile() as output:
            try:
                result = subprocess.run(argv, input=data, stdout=output, stderr=subprocess.DEVNULL,
                                        timeout=self.remaining(), check=False, preexec_fn=cap_output,
                                        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
            except subprocess.TimeoutExpired:
                raise RuntimeErrorCode("operation_deadline") from None
            require(result.returncode == 0, "host_command_failed")
            require(output.tell() < maximum, "host_output_limit")
            output.seek(0)
            return output.read(maximum)

    def unit(self, systemctl, unit):
        raw = self.command([systemctl, "show", unit, "--no-pager",
                            "--property=LoadState,ActiveState,SubState,MainPID,User,Group,"
                            "WorkingDirectory,InvocationID,ExecMainStartTimestampMonotonic,Environment,"
                            "DropInPaths,NeedDaemonReload"])
        return dict(line.split("=", 1) for line in raw.decode().splitlines() if "=" in line)

    def admin(self, path, request, *, lock_fds=()):
        raw = encoded(request)
        require(len(raw) <= 16384, "admin_request_limit")
        info = Path(path).lstat()
        require(stat.S_ISSOCK(info.st_mode) and not info.st_mode & 0o007,
                "private_admin_socket_required")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(min(10, self.remaining()))
            client.connect(path)
            if lock_fds:
                sent = client.sendmsg([raw], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", lock_fds))])
                if sent < len(raw):
                    client.sendall(raw[sent:])
            else:
                client.sendall(raw)
            output = bytearray()
            while not output.endswith(b"\n"):
                block = client.recv(min(65536, JSON_LIMIT + 1 - len(output)))
                require(block and len(output) + len(block) <= JSON_LIMIT, "admin_response_limit")
                output.extend(block)
        response = parse_json(output)
        if (isinstance(response, dict) and set(response) == {"ok", "error"} and response["ok"] is False
                and isinstance(response["error"], str) and response["error"] in RELAY_ERROR_CODES):
            raise RuntimeErrorCode(response["error"])
        require(isinstance(response, dict) and response.get("ok") is True and isinstance(response.get("result"), dict),
                "admin_operation_failed")
        return response["result"]

    def proc(self, pid, name):
        return self.proc_file(Path(f"/proc/{pid}/{name}"))

    def proc_file(self, path):
        self.remaining()
        with path.open("rb") as source:
            raw = source.read(JSON_LIMIT + 1)
        require(len(raw) <= JSON_LIMIT, "proc_output_limit")
        self.remaining()
        return raw

    def executable(self, pid):
        return str(Path(f"/proc/{pid}/exe").resolve(strict=True))

    def process_started_ms(self, pid):
        fields = self.proc(pid, "stat").decode().rsplit(")", 1)[1].split()
        started = int(fields[19]) / os.sysconf("SC_CLK_TCK")
        uptime = float(self.proc_file(Path("/proc/uptime")).split()[0])
        return self.now() - (uptime - started) * 1000

    def listening_ports(self, pid):
        inodes = set()
        with os.scandir(f"/proc/{pid}/fd") as entries:
            for count, item in enumerate(entries, 1):
                self.remaining()
                require(count <= MAX_PROCESS_FDS, "server_descriptor_limit")
                try:
                    match = re.fullmatch(r"socket:\[(\d+)\]", os.readlink(item.path))
                    if match:
                        inodes.add(match[1])
                except FileNotFoundError:
                    continue
        ports = set()
        for name in ("tcp", "tcp6"):
            for line in self.proc(pid, "net/" + name).decode().splitlines()[1:]:
                self.remaining()
                values = line.split()
                if len(values) > 9 and values[3] == "0A" and values[9] in inodes:
                    ports.add(int(values[1].rsplit(":", 1)[1], 16))
        return ports

    def locks(self):
        return self.proc_file(Path("/proc/locks")).decode()

    def queue_count(self, path):
        path = absolute(path)
        require(path.is_file(), "queue_database_missing")
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True,
                             timeout=min(5, self.remaining())) as database:
            database.set_progress_handler(lambda: int(time.monotonic() >= self.deadline), 1000)
            rows = database.execute("SELECT count(*) FROM trials WHERE status IN ('queued','running','rendering')").fetchall()
        require(len(rows) == 1 and type(rows[0][0]) is int and rows[0][0] >= 0, "invalid_queue_status")
        return rows[0][0]

    def snapshot(self, config, run_id):
        try:
            return collect(mysql_command=config["command"], database=config["database"],
                           defaults_file=config.get("defaults_file"), run_id=run_id,
                           character_id=config["character_id"], account_id=config["account_id"],
                           timeout=min(10, self.remaining()))
        except ValueError as error:
            if str(error) == "account_still_online":
                raise RuntimeErrorCode("account_still_online") from None
            raise


class CosmicRuntime:
    def __init__(self, config, host=None):
        self.config = config
        self.host = host or Host()
        require(type(config.get("schema_version")) is int and config["schema_version"] == 1,
                "unsupported_runtime_config")
        require(set(config["services"]) == {"world", "worker", "cosmic", "web"}
                and all(UNIT.fullmatch(x) for x in config["services"].values())
                and len(set(config["services"].values())) == 4, "invalid_services")
        for name in ("world_lock", "queue_lock", "queue_database", "attempt_root", "admin_socket", "relay_output_root",
                     "native_output_root", "dropin_root", "systemctl", "journalctl", "docker", "web_script"):
            absolute(config[name])
        require(config.get("docker_launcher") in (None, "/usr/bin/sudo"), "invalid_docker_command")
        require(config["dropin_root"] == "/run/systemd/system", "runtime_dropin_root_required")
        require(isinstance(config.get("game_ports"), list) and 1 <= len(config["game_ports"]) <= 16
                and len(set(config["game_ports"])) == len(config["game_ports"])
                and all(type(x) is int and 1 <= x <= 65535 for x in config["game_ports"]), "invalid_game_ports")
        db = config["mysql"]
        require(DATABASE.fullmatch(db["database"]) is not None, "invalid_database")
        require(all(type(db[k]) is int and 1 <= db[k] <= 2**31 - 1
                    for k in ("character_id", "account_id")), "invalid_character_identity")
        command = db["command"]
        require(isinstance(command, list) and len(command) == 1
                and absolute(command[0]).name in ("mysql", "mariadb"), "invalid_mysql_command")
        if db.get("defaults_file"):
            path = absolute(db["defaults_file"])
            require(path.is_file() and not path.stat().st_mode & 0o077,
                    "mysql_defaults_not_private")
        self.context = {}
        self.state = None

    def unit(self, name):
        value = self.host.unit(self.config["systemctl"], self.config["services"][name])
        require(value.get("LoadState") == "loaded", "existing_service_required")
        return value

    @staticmethod
    def stopped(unit):
        return unit.get("ActiveState") in ("inactive", "failed") and unit.get("MainPID") == "0"

    def sql(self, raw):
        db = self.config["mysql"]
        options = (["--defaults-extra-file=" + db["defaults_file"]] if db.get("defaults_file") else [])
        return self.host.command([*db["command"], *options, "--batch", "--raw", "--skip-column-names",
                                  "--connect-timeout=5", db["database"]], data=raw, maximum=65536)

    def account_state(self):
        db = self.config["mysql"]
        raw = self.sql(f"SELECT loggedin FROM accounts WHERE id={db['account_id']};\n".encode()).strip()
        require(raw in (b"0", b"1", b"2"), "account_state_unavailable")
        return int(raw)

    def admin(self, op, **values):
        fds = self.lock_fds() if op == "start" else ()
        if fds:
            values["lock_paths"] = self.context["lock_paths"]
        return self.host.admin(self.config["admin_socket"], {"op": op, **values}, lock_fds=fds)

    def lock_fds(self):
        """Use inherited descriptions, never reopen locks and pretend to own them."""
        result = []
        received = self.context.get("lock_fds", {})
        require(set(received) == {"world", "queue"}, "inherited_lock_descriptions_missing")
        for name, key in (("world", "world_lock"), ("queue", "queue_lock")):
            expected = Path(self.config[key]).stat()
            descriptor = received[name]
            require(type(descriptor) is int and descriptor > 2, "invalid_inherited_lock_description")
            current = os.fstat(descriptor)
            require(stat.S_ISREG(current.st_mode)
                    and (current.st_dev, current.st_ino) == (expected.st_dev, expected.st_ino),
                    "inherited_lock_description_mismatch")
            result.append(descriptor)
        require(result[0] != result[1], "distinct_inherited_locks_required")
        return result

    def load_pins(self):
        """Read only small immutable configuration; never inventory live assets."""
        self.scenario = parse_json(ref_bytes(self.config["scenario"]))
        duration = self.scenario.get("program_seconds")
        adaptive = self.scenario.get("protocol") == "full-client-adaptive-pilot-v1"
        require(type(duration) is int and duration in ((300,) if adaptive else (22, 60))
                and isinstance(self.scenario.get("id"), str) and 0 < len(self.scenario["id"]) <= 128
                and SHA.fullmatch(self.scenario.get("instructions_sha256", "")) is not None
                and same_json(self.scenario.get("reasoning"), {"effort": "low"}), "invalid_frozen_scenario")
        if adaptive:
            from full_client_adaptive import validate_protocol, prompt
            try:
                protocol = validate_protocol(self.scenario.get("adaptive_protocol"))
            except ValueError:
                raise RuntimeErrorCode("invalid_frozen_scenario") from None
            require(self.scenario["instructions_sha256"] == hashlib.sha256(prompt(protocol).encode()).hexdigest(),
                    "frozen_prompt_mismatch")
            trial = self.scenario["trial_budgets"]
            require(trial["max_api_requests"] == protocol["max_api_requests"]
                    and trial["max_actions"] == protocol["max_actions"]
                    and trial["max_output_tokens"] == protocol["max_api_requests"] * protocol["max_output_tokens"]
                    and trial["max_total_tokens"] == protocol["max_total_tokens"]
                    and trial["controller_seconds"] == 300 and trial["operation_seconds"] >= 335,
                    "bridge_budget_mismatch")
            expected_budgets = {"api_requests": protocol["max_api_requests"], "output_tokens": trial["max_output_tokens"],
                "total_tokens": protocol["max_total_tokens"], "program_ms": 300000, "run_ms": 335000,
                "actions": protocol["max_actions"], "sdk_requests": protocol["max_sdk_requests"]}
        else:
            require(self.scenario.get("protocol") is None and self.scenario.get("adaptive_protocol") is None,
                    "invalid_frozen_scenario")
            expected_budgets = {"api_requests": 1, "output_tokens": 3000,
                                "total_tokens": self.scenario["trial_budgets"]["max_total_tokens"],
                                "program_ms": duration * 1000, "run_ms": (duration + 63) * 1000,
                                "actions": 80 if duration == 22 else 240, "sdk_requests": 100 if duration == 22 else 600}
        require(same_json(self.scenario.get("budgets"), expected_budgets), "frozen_bridge_budgets_mismatch")
        require(same_json(self.scenario.get("settlement_policy"), SETTLEMENT_POLICY),
                "invalid_settlement_policy")
        self.baseline = parse_json(ref_bytes(self.config["baseline_snapshot"]))
        if adaptive:
            require(protocol["profile"]["level"] == self.baseline.get("character", {}).get("level"),
                    "baseline_identity_mismatch")
        self.readiness_policy()
        self.manifest = parse_json(ref_bytes(self.config["runtime_manifest"]))
        self.docker_binding()
        absolute(self.manifest["working_directory"])
        absolute(self.manifest["wz_path"])
        db = self.config["mysql"]
        require(self.baseline.get("account_logged_in") == 0 and all(
            self.baseline["character"].get(k) == db[k] for k in ("character_id", "account_id")),
            "baseline_identity_mismatch")
        self.xp_window_contract()

    def xp_window_contract(self):
        """Both private runtime and frozen scenario must explicitly opt in."""
        configured = self.config.get("xp_window_protocol")
        contract = getattr(self, "scenario", {}).get("xp_window_protocol")
        adaptive = getattr(self, "scenario", {}).get("adaptive_protocol")
        progression = adaptive.get("progression_policy") if isinstance(adaptive, dict) else None
        if configured is None:
            require(contract is None and progression is None, "xp_window_opt_in_required")
            return None
        require(configured == xp_windows.PROTOCOL
                and self.scenario.get("protocol") == "full-client-adaptive-pilot-v1",
                "unsupported_xp_window_protocol")
        try:
            return xp_windows.validate_contract(contract)
        except (EvidenceError, TypeError, KeyError):
            raise RuntimeErrorCode("invalid_xp_window_contract") from None

    def trial_protocol(self):
        return xp_windows.PROTOCOL if self.xp_window_contract() else self.scenario.get("protocol")

    def native_xp_environment(self, native):
        contract = self.xp_window_contract()
        if contract is None:
            return {}
        initial = self.state["initial"]["character"]
        require(same_json(initial, self.baseline["character"]), "restored_baseline_mismatch")
        norm = contract["normalization"]
        values = (str(native / "xp.jsonl"), str(initial["level"]), str(initial["exp"]),
                  *(str(norm[k][part]) for k in ("server_xp_multiplier", "simulation_speed_multiplier")
                    for part in ("numerator", "denominator")))
        return dict(zip(xp_windows.XP_ENV_NAMES, values))

    def frozen(self):
        """Full byte inventory; callers must keep this outside the online session."""
        require(self.account_state() == 0, "inventory_requires_offline_account")
        self.load_pins()
        manifest = self.manifest
        absolute(manifest["working_directory"])
        absolute(manifest["wz_path"])
        verify_manifest(manifest, docker_command=configured_command(self.docker_binding()),
                        docker_socket=self.config.get("docker_socket", "/var/run/docker.sock"),
                        limits={"timeout_seconds": min(FREEZE_HARD_LIMITS["timeout_seconds"],
                                                       max(1, int(self.host.remaining())))})
        jar = manifest["server_jar"]
        path = absolute(jar["path"])
        with open_verified_artifact(path.parent, {"path": path.name, "sha256": jar["sha256"]},
                                    "server_jar", maximum=512 * 1024 * 1024) as stream:
            with zipfile.ZipFile(stream) as archive:
                native_classes = {name for name in (NATIVE_CLASS, XP_NATIVE_CLASS) if name in archive.namelist()}
        require(NATIVE_CLASS in native_classes, "native_persistence_class_missing")
        if self.xp_window_contract():
            require(XP_NATIVE_CLASS in native_classes, "native_xp_ledger_class_missing")
        cosmic, web = self.unit("cosmic"), self.unit("web")
        require(pwd.getpwnam(cosmic.get("User", "")).pw_uid != 0
                and pwd.getpwnam(web.get("User", "")).pw_uid != 0
                and web.get("ActiveState") == "active", "unprivileged_services_required")
        self.web_identity(web)
        ref_bytes(self.config["java"], MAX_SQL)
        require(os.access(self.config["java"]["path"], os.X_OK), "java_executable_required")
        # Validate SQL bytes before considering the backend ready, never execute here.
        ref_bytes(self.config["baseline"], MAX_SQL)
        ref_bytes(self.config["orchestrator"])

    def docker_binding(self):
        """New trials require an execution binding; old manifests remain evidence only."""
        require(type(self.manifest.get("schema_version")) is int and self.manifest["schema_version"] == 2
                and self.manifest.get("docker_binding") is not None,
                "docker_binding_required")
        binding = validate_binding(self.manifest["docker_binding"], verify_files=False)
        command = (["/usr/bin/sudo", "-n"] if self.config.get("docker_launcher") else []) + [self.config["docker"]]
        require(configured_command(binding) == command
                and binding["socket_path"] == str(Path(self.config.get("docker_socket", "/var/run/docker.sock")).resolve()),
                "docker_binding_mismatch")
        return binding

    def readiness_policy(self):
        require(self.scenario.get('readiness_policy') is not None, 'readiness_policy_required')
        expected=self.baseline.get('character',{}).get('map_id')
        require(type(expected) is int, 'invalid_readiness_policy')
        try:
            return validate_policy(self.scenario['readiness_policy'], expected_map_id=expected)
        except ReadinessError as error:
            raise RuntimeErrorCode(str(error)) from None

    def online_identity(self):
        """Bounded process/UID/environment checks without scanning WZ/NX/JAR bytes."""
        web = self.unit("web")
        require(web.get("ActiveState") == "active", "unprivileged_services_required")
        self.web_identity(web, verify_bytes=False)

    def web_identity(self, unit, *, verify_bytes=True):
        """Bind frozen files to the actual serving process and its import roots."""
        manifest = self.manifest
        root = absolute(manifest["client_js"]["path"]).parent.parent
        require(Path(manifest["client_js"]["path"]) == root / "build/JourneyClient.js"
                and Path(manifest["client_wasm"]["path"]) == root / "build/JourneyClient.wasm",
                "served_client_build_paths_mismatch")
        script = absolute(self.config["web_script"])
        controls = script.parent.parent / "ui/full-client"
        # The executor reads the JavaScript dispatcher at each container launch;
        # pin it alongside imported modules, not just the Docker image.
        required = {script, *(script.parent / name for name in ("full_client_bridge.py", "full_client_native.py", "full_client_adaptive.py", "full_client_session.py", "full_client_capture.py", "full_client_docker.py", "full_client_readiness.py", "maple_agent.py", "agent-sandbox.mjs")),
                    controls / "controller.js", controls / "webcodecs-recorder.js", controls / "waiting.html",
                    *(root / "web" / name for name in ("index.html", "assets_server.py", "ws_proxy.py"))}
        extras = {ref["path"]: ref for ref in manifest.get("extra_files", [])}
        require(all(str(path) in extras for path in required), "serving_sources_not_frozen")
        asset_root = root / "assets"
        require(asset_root.is_dir() and not asset_root.is_symlink(), "client_asset_directory_required")
        asset_targets = set()
        for path in asset_root.iterdir():
            target = path.resolve(strict=True)
            require(path.suffix == ".nx" and target.is_file() and target.name == path.name,
                    "unexpected_client_asset_entry")
            require(str(target) in extras, "client_asset_target_not_frozen")
            asset_targets.add(str(target))
        require(asset_targets and asset_targets == {path for path in extras if Path(path).suffix == ".nx"},
                "client_asset_inventory_mismatch")
        if verify_bytes:
            ref_bytes(self.config["web_python"], MAX_SQL)
        pid = int(unit.get("MainPID", "0"))
        require(pid > 1, "web_process_missing")
        require(self.host.executable(pid) == self.config["web_python"]["path"], "web_interpreter_mismatch")
        argv = [arg.decode() for arg in self.host.proc(pid, "cmdline").split(b"\0") if arg]
        require(len(argv) in (2, 3) and Path(argv[0]).resolve() == Path(self.config["web_python"]["path"])
                and argv[-1] == str(script) and (len(argv) == 2 or argv[1] == "-u"), "web_entrypoint_mismatch")
        uid = pwd.getpwnam(unit.get("User", "")).pw_uid
        status = dict(line.split(":", 1) for line in self.host.proc(pid, "status").decode().splitlines() if ":" in line)
        require(uid != 0 and all(int(value) == uid for value in status["Uid"].split()), "web_uid_mismatch")
        env = dict(item.split(b"=", 1) for item in self.host.proc(pid, "environ").split(b"\0") if b"=" in item)
        expected = {"MAPLEBENCH_CLIENT_ROOT": str(root),
                    "MAPLEBENCH_CLIENT_OUTPUT": str(Path(self.config["relay_output_root"]).parent),
                    "MAPLEBENCH_ADMIN_SOCKET": self.config["admin_socket"],
                    "MAPLEBENCH_WORLD_LOCK_FILE": self.config["world_lock"],
                    "MAPLEBENCH_QUEUE_LOCK_FILE": self.config["queue_lock"]}
        require(Path(self.config["relay_output_root"]).name == "runs"
                and all(env.get(k.encode()) == value.encode() for k, value in expected.items()),
                "web_runtime_paths_mismatch")
        started = self.host.process_started_ms(pid)
        require(all(max(path.stat().st_mtime_ns, path.stat().st_ctime_ns) / 1_000_000 <= started
                    for path in required), "web_process_predates_frozen_sources")

    def ownership(self):
        """Check real kernel ancestry and both already-held flock inode identities."""
        c = self.context
        require(sys.platform.startswith("linux") and os.geteuid() == 0, "linux_root_runner_required")
        root, guard = c.get("lock_owner_pid"), c.get("guard_pid")
        require(type(root) is int and type(guard) is int and guard == os.getppid()
                and root > 1 and c.get("guard_parent_pid") == root, "guard_ancestry_mismatch")
        info = dict(line.split(":", 1) for line in self.host.proc(guard, "status").decode().splitlines() if ":" in line)
        require(int(info["PPid"].strip()) == root, "guard_ancestry_mismatch")
        script = self.config["orchestrator"]["path"].encode()
        for pid in (root, guard):
            args = self.host.proc(pid, "cmdline").split(b"\0")
            require(len(args) > 2 and args[1] == script, "orchestrator_identity_mismatch")
            if pid == guard:
                require(args[2] == b"_adapter_guard", "guard_identity_mismatch")
        ref_bytes(self.config["orchestrator"])
        require(c.get("lock_paths") == {"world": self.config["world_lock"],
                                       "queue": self.config["queue_lock"]}, "lock_paths_mismatch")
        entries = [line.split() for line in self.host.locks().splitlines()]
        identities = []
        for name in ("world_lock", "queue_lock"):
            path = absolute(self.config[name])
            st = path.lstat()
            require(stat.S_ISREG(st.st_mode), "invalid_lock_file")
            key = (os.major(st.st_dev), os.minor(st.st_dev), st.st_ino)
            identities.append(key)
            found = False
            for row in entries:
                if len(row) >= 8 and row[1:4] == ["FLOCK", "ADVISORY", "WRITE"] and row[4] == str(root):
                    fields = row[5].split(":")
                    found |= len(fields) == 3 and (int(fields[0], 16), int(fields[1], 16), int(fields[2])) == key
            require(found, "world_or_queue_lock_not_owned")
        require(identities[0] != identities[1], "distinct_locks_required")

    def quiet(self):
        require(self.stopped(self.unit("world")) and self.stopped(self.unit("worker")),
                "world_helper_or_worker_active")
        require(self.host.queue_count(self.config["queue_database"]) == 0, "queued_or_active_trials_exist")

    def persist(self):
        state = self.state
        if state.get("result", {}).get("protocol") == "full-client-adaptive-pilot-v1":
            # Keep the bounded control journal small; the immutable, separately
            # hashed aggregate file is loaded only when this attempt resumes.
            state = {k: v for k, v in state.items() if k != "result"}
            state["adaptive_result_ref"] = self.state["artifacts"]["result"]
        atomic_json(self.directory / "backend-state.json", state)

    def intent(self, operation):
        require(operation not in self.state["intents"], "operation_already_attempted")
        self.state["intents"].append(operation)
        self.persist()

    def artifact(self, name, value=None, raw=None):
        ref = save_bytes(self.directory / name, raw if raw is not None else encoded(value))
        return ref

    def event(self, name, timestamp):
        self.state["events"].append({"event": name, "at_ms": timestamp, **self.identity()})

    def identity(self):
        db = self.config["mysql"]
        return {"run_id": self.run_id, "server_instance_id": self.state["server_instance_id"],
                "character_id": db["character_id"], "account_id": db["account_id"]}

    def owned_server(self):
        self.owned_dropin()
        unit = self.unit("cosmic")
        require(unit.get("InvocationID") == self.state.get("invocation_id")
                and not self.stopped(unit), "server_instance_ownership_lost")
        self.validate_process(unit)
        return unit

    def owned_dropin(self):
        require(self.state.get("dropin"), "dropin_owner_missing")
        expected = self.trial_dropin_path()
        require(Path(self.state["dropin"]) == expected, "dropin_owner_path_mismatch")
        raw = self.read_stable(expected, 16384)
        require(hashlib.sha256(raw).hexdigest() == self.state["dropin_sha256"], "dropin_ownership_lost")

    def trial_dropin_path(self):
        return Path(self.config["dropin_root"]) / (self.config["services"]["cosmic"] + ".d") / "zz-maplebench-trial.conf"

    def trial_configuration_absent(self, unit):
        """A removed file does not prove systemd has discarded its cached values."""
        if (os.path.lexists(self.trial_dropin_path()) or unit.get("NeedDaemonReload") != "no"
                or not isinstance(unit.get("DropInPaths"), str)
                or not isinstance(unit.get("Environment"), str)):
            return False
        try:
            paths = shlex.split(unit["DropInPaths"])
            environment = shlex.split(unit["Environment"])
        except ValueError:
            return False
        return (not any(Path(path).name == "zz-maplebench-trial.conf" for path in paths)
                and not any(item.split("=", 1)[0] in (*ENV_NAMES, *xp_windows.XP_ENV_NAMES) for item in environment))

    def validate_process(self, unit):
        user = pwd.getpwnam(unit.get("User", ""))
        require(user.pw_uid != 0 and unit.get("User") == self.state["service_user"],
                "nonroot_service_user_required")
        pid = int(unit.get("MainPID", "0"))
        require(pid > 1, "server_process_missing")
        status = dict(line.split(":", 1) for line in self.host.proc(pid, "status").decode().splitlines() if ":" in line)
        require(all(int(uid) == user.pw_uid for uid in status["Uid"].split()), "server_uid_mismatch")
        argv = self.host.proc(pid, "cmdline").split(b"\0")
        jar = self.manifest["server_jar"]["path"].encode()
        require(argv[:6] == [self.config["java"]["path"].encode(), b"-Xmx1536m", b"-XX:ActiveProcessorCount=2",
                             ("-Dwz-path=" + self.manifest["wz_path"]).encode(), b"-jar", jar]
                and argv[6:] in ([], [b""]),
                "server_jar_command_mismatch")
        require(unit.get("WorkingDirectory") == self.manifest["working_directory"],
                "service_working_directory_mismatch")
        env = dict(item.split(b"=", 1) for item in self.host.proc(pid, "environ").split(b"\0") if b"=" in item)
        require(env.get(b"MAPLEBENCH_ENABLED") == b"false", "legacy_bot_adapter_must_be_disabled")
        require(all(env.get(k.encode()) == v.encode() for k, v in self.state["native_environment"].items()),
                "server_native_environment_mismatch")

    def wait_for(self, predicate):
        while True:
            self.ownership()
            self.quiet()
            value = predicate()
            if value:
                return value
            self.host.sleep()

    def status(self):
        if (self.context.get("recovery") and self.state) or self.account_state() != 0:
            # Recovery must reach ordinary disconnect before any large read.
            self.load_pins()
            if self.context.get("recovery"):
                self.ownership()
            self.online_identity()
        else:
            self.frozen()
        world, worker, cosmic = self.unit("world"), self.unit("worker"), self.unit("cosmic")
        admin = self.admin("status")
        session, bridge = admin.get("session", {}), admin.get("bridge", {})
        run = bridge.get("run") or {}
        initial_idle = run.get("id") is None and run.get("status") == "idle"
        idle = (session.get("artifactsSettled") is True
                and (not run or initial_idle or run.get("status") in ("completed", "failed", "timed_out", "cancelled"))
                and run.get("workerActive") is not True and run.get("leaseReleasePending") is not True
                and bridge.get("browserReleasePending") is not True)
        waiting = session.get("state") == "waiting" and session.get("fresh") is True and session.get("pinned") is True
        stopped = self.stopped(cosmic)
        conflict = not stopped
        if not stopped and self.state and self.state.get("dropin"):
            try:
                self.owned_dropin()
                self.validate_process(cosmic)
                conflict = (cosmic.get("InvocationID") == self.state.get("previous_invocation_id") or
                            (self.state.get("invocation_id") is not None
                             and cosmic.get("InvocationID") != self.state["invocation_id"]))
            except (RuntimeErrorCode, OSError, KeyError, ValueError):
                conflict = True
        queue = (self.stopped(world) and self.stopped(worker)
                 and self.host.queue_count(self.config["queue_database"]) == 0)
        offline = self.account_state() == 0
        return {"ready": queue and stopped and offline and idle and waiting and not conflict
                         and self.trial_configuration_absent(cosmic),
                "queue_idle": queue, "server_stopped": stopped, "account_offline": offline,
                "controller_idle": idle, "ownership_conflict": conflict}

    def restore_baseline(self):
        require(self.stopped(self.unit("cosmic")) and self.account_state() == 0,
                "restore_requires_stopped_offline")
        admin = self.admin("status")
        session = admin.get("session", {})
        require(session.get("state") == "waiting" and session.get("fresh") is True
                and session.get("pinned") is True and session.get("artifactsSettled") is True,
                "waiting_browser_required")
        self.intent("restore_baseline")
        for name in ("baseline", "baseline_snapshot", "scenario", "runtime_manifest"):
            raw = ref_bytes(self.config[name], MAX_SQL if name == "baseline" else JSON_LIMIT)
            self.state["artifacts"][name] = self.artifact(name + (".sql" if name == "baseline" else ".json"), raw=raw)
        self.persist()
        self.ownership()
        require(self.stopped(self.unit("cosmic")) and self.account_state() == 0,
                "restore_requires_stopped_offline")
        engines = self.sql(b"SELECT CONCAT(TABLE_NAME,':',ENGINE) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('accounts','characters','keymap') ORDER BY TABLE_NAME;\n")
        require(engines.strip().splitlines() == [b"accounts:InnoDB", b"characters:InnoDB", b"keymap:InnoDB"],
                "transactional_score_tables_required")
        self.sql(read_artifact_bytes(self.directory, self.state["artifacts"]["baseline"], "baseline", maximum=MAX_SQL))
        at = self.host.now()
        snapshot = self.host.snapshot(self.config["mysql"], self.run_id)
        require(same_json(snapshot["character"], self.baseline["character"])
                and same_json(snapshot["keymap"], self.baseline["keymap"]), "restored_baseline_mismatch")
        reset = {"run_id": self.run_id, "baseline_sha256": self.config["baseline"]["sha256"],
                 "world_lock_held": True, "queue_lock_held": True, "server_stopped": True,
                 "verified": True, "completed_at_ms": at}
        self.state["initial"] = snapshot
        self.state["reset"] = reset
        self.state["artifacts"]["initial_db"] = self.artifact("initial-db.json", snapshot)
        self.state["artifacts"]["reset"] = self.artifact("reset.json", reset)
        return {"reset_verified": True}

    def start_server(self):
        require(self.state.get("reset") and self.stopped(self.unit("cosmic")) and self.account_state() == 0,
                "fresh_reset_required")
        before = self.unit("cosmic")
        user = pwd.getpwnam(before.get("User", ""))
        require(user.pw_uid != 0, "nonroot_service_user_required")
        require(not any(name in before.get("Environment", "") for name in (*ENV_NAMES, *xp_windows.XP_ENV_NAMES)),
                "existing_trial_environment")
        native_root = absolute(self.config["native_output_root"])
        native_info = native_root.lstat()
        require(stat.S_ISDIR(native_info.st_mode) and (
            (native_info.st_uid == user.pw_uid and stat.S_IMODE(native_info.st_mode) == 0o700)
            or (native_info.st_uid == 0 and stat.S_IMODE(native_info.st_mode) == 0o711)),
            "native_root_service_traversal_required")
        native = native_root / self.run_id
        dropin_dir = Path(self.config["dropin_root"]) / (self.config["services"]["cosmic"] + ".d")
        require(not dropin_dir.is_symlink(), "symlink_dropin_directory")
        dropin = dropin_dir / "zz-maplebench-trial.conf"
        require(not dropin.exists() and not native.exists(), "existing_trial_owner")
        env = dict(zip(ENV_NAMES, (self.run_id, self.state["server_instance_id"],
                       str(self.config["mysql"]["character_id"]), str(self.config["mysql"]["account_id"]),
                       str(native / "save.jsonl"))))
        # The normal worker's service enables the legacy bot/SDK adapter. An
        # ordinary full-client trial must explicitly override that inherited mode.
        env["MAPLEBENCH_ENABLED"] = "false"
        env.update(self.native_xp_environment(native))
        text = "[Service]\n" + "".join('Environment="' + key + '=' + value.replace('\\', '\\\\').replace('"', '\\"') + '"\n'
                                       for key, value in env.items())
        text += "MemoryMax=2300M\nMemorySwapMax=0\nCPUQuota=200%\nRestart=no\nKillMode=control-group\nTimeoutStopSec=30\nRuntimeMaxSec=" + str(self.context["request"]["budgets"]["total_seconds"] + 120) + "\n"
        def quote(value):
            return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '$$') + '"'
        launch = [self.config["java"]["path"], "-Xmx1536m", "-XX:ActiveProcessorCount=2",
                  "-Dwz-path=" + self.manifest["wz_path"], "-jar", self.manifest["server_jar"]["path"]]
        text += "WorkingDirectory=" + systemd_working_directory(self.manifest["working_directory"]) + "\nExecStart=\nExecStart=" + " ".join(quote(x) for x in launch) + "\n"
        self.state.update(service_user=user.pw_name, native_directory=str(native), dropin=str(dropin),
                          dropin_sha256=hashlib.sha256(text.encode()).hexdigest(), native_environment=env,
                          previous_invocation_id=before.get("InvocationID"))
        self.intent("start_server")  # ownership durable before any external write/start
        native.mkdir(mode=0o700)
        os.chown(native, user.pw_uid, user.pw_gid)
        # Ancestors are operator-provided; the service must be able to traverse
        # them. It receives no access to the root-owned attempt evidence tree.
        dropin_dir.mkdir(mode=0o755, exist_ok=True)
        save_bytes(dropin, text.encode())
        self.host.command([self.config["systemctl"], "daemon-reload"])
        require(self.unit("cosmic").get("WorkingDirectory") == self.manifest["working_directory"],
                "service_working_directory_mismatch")
        self.state["server_start_requested_at_ms"] = self.host.now()
        self.persist()
        self.host.command([self.config["systemctl"], "start", self.config["services"]["cosmic"]])
        unit = self.unit("cosmic")
        require(unit.get("ActiveState") == "active" and unit.get("InvocationID")
                and unit["InvocationID"] != before.get("InvocationID"), "fresh_server_start_failed")
        self.state["invocation_id"] = unit["InvocationID"]
        self.persist()
        self.validate_process(unit)
        self.wait_for_server_ready()
        self.state["session"]["server_started_at_ms"] = self.state["server_start_requested_at_ms"]
        self.event("server_started", self.state["session"]["server_started_at_ms"])
        return {"server_instance_id": self.state["server_instance_id"], "invocation_id": unit["InvocationID"]}

    def server_ready(self):
        unit = self.owned_server()
        logs = self.host.command([self.config["journalctl"], "--no-pager", "--output=cat",
                                  "_SYSTEMD_INVOCATION_ID=" + self.state["invocation_id"]])
        require(b"MapleBench persistence journal failed" not in logs and b"Error saving chr" not in logs
                and b"MapleBench XP ledger failed" not in logs,
                "native_startup_or_save_failed")
        initialized = logs.count(b"MapleBench persistence journal initialized")
        xp_initialized = logs.count(b"MapleBench XP ledger initialized")
        xp_contract = self.xp_window_contract()
        online = logs.count(b"Cosmic is now online after ")
        require(initialized <= 1 and online <= 1 and xp_initialized <= (1 if xp_contract else 0),
                "native_startup_markers_ambiguous")
        ports_ready = set(self.config["game_ports"]) <= self.host.listening_ports(int(unit["MainPID"]))
        diagnostics = {"invocation_id": self.state["invocation_id"], "log_bytes": len(logs),
                       "journal_initializations": initialized, "online_markers": online,
                       "listeners_ready": ports_ready}
        if xp_contract:
            diagnostics["xp_journal_initializations"] = xp_initialized
        # Keep only safe counts for the exact owned instance. Persist changes so
        # a timeout remains inspectable without copying native log contents.
        if self.state.get("startup_readiness") != diagnostics:
            self.state["startup_readiness"] = diagnostics
            self.persist()
        ready = initialized == 1 and online == 1 and ports_ready
        if ready and xp_contract:
            require(xp_initialized == 1, "native_xp_initialization_missing")
            try:
                raw = self.read_stable(Path(self.state["native_directory"]) / "xp.jsonl", 65536)
                proof = xp_windows.verify_native_header(raw, identity=self.identity(),
                    initial={k:self.state["initial"]["character"][k] for k in ("level", "exp")}, contract=xp_contract)
                require(self.state["server_start_requested_at_ms"] <= proof["wall_ms"] <= self.host.now(),
                        "native_xp_header_invalid")
                require(self.state.get("xp_header", proof) == proof, "native_xp_header_invalid")
            except (EvidenceError, OSError, TypeError, KeyError):
                raise RuntimeErrorCode("native_xp_header_invalid") from None
            self.state["xp_header"] = proof
            self.persist()
        return ready

    def wait_for_server_ready(self):
        while True:
            self.ownership()
            self.quiet()
            if self.server_ready():
                return True
            try:
                self.host.sleep()
                self.host.remaining()
            except RuntimeErrorCode as error:
                if str(error) != "operation_deadline":
                    raise
                # Only classify a deadline after a complete observation. A
                # timeout inside the next ownership/log/socket probe retains
                # operation_deadline, even if a previous observation exists.
                diagnostic = self.state["startup_readiness"]
                if not diagnostic["log_bytes"]:
                    code = "native_log_unavailable"
                elif diagnostic["journal_initializations"] != 1:
                    code = "native_journal_initialization_missing"
                elif diagnostic["online_markers"] != 1:
                    code = "native_online_marker_missing"
                else:
                    code = "native_listener_unavailable"
                raise RuntimeErrorCode(code) from None

    def login(self):
        self.owned_server()
        require(self.server_ready(), "server_not_ready_for_ordinary_login")
        self.intent("login")
        self.admin("connect")
        def connected():
            self.owned_server()
            status = self.admin("status")
            return (status.get("session", {}).get("state") == "connected"
                    and status.get("session", {}).get("fresh") is True
                    and status.get("bridge", {}).get("fresh") is True and self.account_state() == 2)
        self.wait_for(connected)
        at = self.host.now()
        self.state["session"]["login_at_ms"] = at
        self.event("login", at)
        return {"ordinary_login": True, "login_at_ms": at}

    def run_controller(self):
        """One API attempt followed by ordinary logout, before artifact analysis.

        The runner's pending run_controller operation authorizes this complete
        operation. Each external action still has its own durable backend intent.
        A later disconnect phase only verifies the saved receipt; it never retries
        an uncertain navigation or replays a model request.
        """
        self.owned_server()
        require(self.state["session"].get("login_at_ms") and self.account_state() == 2,
                "ordinary_login_required")
        spec = self.context["request"]
        budgets = spec["budgets"]
        duration = self.scenario.get("program_seconds")
        adaptive = self.scenario.get("protocol") == "full-client-adaptive-pilot-v1"
        protocol = self.scenario.get("adaptive_protocol") if adaptive else None
        if adaptive:
            from full_client_adaptive import prompt as adaptive_prompt
            prompt = adaptive_prompt(protocol)
            require(spec.get("schema_version") == (3 if self.xp_window_contract() else 2)
                    and spec.get("protocol") == self.trial_protocol(),
                    "bridge_budget_mismatch")
        else:
            require(duration in (22, 60) and type(duration) is int, "unsupported_program_duration")
            require(budgets["controller_seconds"] >= duration + 2
                    and budgets["max_actions"] == (80 if duration == 22 else 240)
                    and budgets["max_output_tokens"] == 3000, "bridge_budget_mismatch")
            from full_client_bridge import PROMPT
            prompt = PROMPT.format(program_seconds=duration, action_limit=budgets["max_actions"],
                                  sdk_request_limit=100 if duration == 22 else 600)
        require(self.scenario.get("instructions_sha256") == hashlib.sha256(prompt.encode()).hexdigest()
                and self.scenario.get("reasoning") == {"effort": "low"}, "frozen_prompt_mismatch")
        readiness_policy=self.readiness_policy()
        self.intent("run_controller")
        try:
            self.admin("start", model=spec["model"], duration_seconds=duration,
                       run_id=self.run_id, request_id=self.run_id, total_token_limit=budgets["max_total_tokens"],
                       docker_image_id=self.manifest["docker_image_id"],
                       docker_binding=self.docker_binding(),
                       readiness_policy=readiness_policy,
                       **({"adaptive_protocol": protocol} if adaptive else {}),
                       trial_context={"scenario_fingerprint": spec["scenario_fingerprint"],
                                      "baseline_sha256": spec["baseline_sha256"]})
            terminal_seen = None
            def completed():
                nonlocal terminal_seen
                self.owned_server()
                self.online_identity()
                status = self.admin("status")
                run = status.get("bridge", {}).get("run") or {}
                require(run.get("id") == self.run_id, "controller_run_identity_lost")
                if run.get("status") in ("failed", "timed_out", "cancelled"):
                    raise RuntimeErrorCode("controller_run_failed")
                if run.get("status") == "completed":
                    now = self.host.now()
                    terminal_seen = now if terminal_seen is None else terminal_seen
                    require(now - terminal_seen <= SETTLEMENT_POLICY["upload_after_program_ms"],
                            "settlement_upload_timeout")
                return (status if run.get("status") == "completed" and run.get("workerActive") is False
                        and run.get("evidenceStatus") == "saved" and run.get("recordingStatus") == "saved"
                        and status.get("session", {}).get("artifactsSettled") is True else None)
            status = self.wait_for(completed)
            observed = self.host.now()
            self.state["upload_status"] = {"schema_version": 1, "source": "full_client_runtime_status",
                                            **self.identity(), "observed_at_ms": observed, "status": status}
            self.state["session"]["upload_observed_at_ms"] = observed
            # This persists the exact observed status with disconnect intent and
            # issues navigation before copying or verifying any controller file.
            self.request_ordinary_disconnect()
        except Exception:
            # Bounded ordinary disconnection is part of the authorized online
            # operation even when API outcome is uncertain. Never stop/reset the
            # server here; preserve the original failure and quarantine on return.
            if not self.state.get("ordinary_logout") and "disconnect" not in self.state["intents"]:
                try:
                    self.settle_owned_controller()
                    self.request_ordinary_disconnect()
                    self.preserve_failure_evidence()
                except Exception:
                    self.state["failure_disconnect_unconfirmed"] = True
                    self.persist()
            raise
        self.copy_controller_metadata()
        result = self.state["result"]
        if adaptive:
            return self.verify_adaptive_controller()
        api = result["api"]
        require(result.get("source") == "full-client-trial" and result["controller"]["id"] == self.run_id
                and result["controller"]["model"] == spec["model"] and api["model"] == spec["model"]
                and result["controller"].get("mode") == "api"
                and result["controller"].get("dockerImageId") == self.manifest["docker_image_id"]
                and result["controller"].get("status") == "completed"
                and api.get("status") == "completed", "controller_model_or_source_mismatch")
        require(same_json(result["controller"].get("dockerBinding"), self.docker_binding()),
                "docker_binding_mismatch")
        require(same_json(result.get("trialContext"), {"scenario_fingerprint": spec["scenario_fingerprint"],
                                                       "baseline_sha256": spec["baseline_sha256"]}),
                "controller_trial_context_mismatch")
        self.verify_api_result(prompt)
        started, timeline = result["timing"]["startedAtMs"], result["timeline"]
        for field, offset in (("api_started_at_ms", "api_started_ms"), ("api_ended_at_ms", "api_ended_ms"),
                              ("controller_started_at_ms", "program_started_ms"), ("controller_ended_at_ms", "program_ended_ms")):
            self.state["session"][field] = started + timeline[offset]
        require(started >= self.state["session"]["login_at_ms"] and result["timing"]["endedAtMs"] <= self.host.now(),
                "controller_host_clock_mismatch")
        self.validate_settlement()
        return {"status": "completed", "requested_model": spec["model"], "returned_model": api["model"],
                "api_requests": 1, "output_tokens": api["usage"]["output_tokens"],
                "total_tokens": api["usage"]["total_tokens"], "actions": result["program"]["actions"],
                "controller_ms": timeline["program_ended_ms"] - timeline["program_started_ms"],
                "recording_complete": True}

    def verify_adaptive_controller(self):
        from full_client_adaptive_evidence import verify_result
        from full_client_publish import _verify_readiness_policy
        result, spec = self.state["result"], self.context["request"]
        controller = result["controller"]
        require(controller.get("id") == self.run_id and controller.get("mode") == "api"
                and controller.get("dockerImageId") == self.manifest["docker_image_id"]
                and same_json(controller.get("dockerBinding"), self.docker_binding())
                and same_json(result.get("trialContext"), {"scenario_fingerprint": spec["scenario_fingerprint"],
                    "baseline_sha256": spec["baseline_sha256"]}), "controller_trial_context_mismatch")
        try:
            verified = verify_result(result, self.directory, protocol=self.scenario["adaptive_protocol"], model=spec["model"])
            _verify_readiness_policy({"result": result, "artifacts": self.state["artifacts"],
                "budgets": self.scenario["budgets"]}, self.directory, {"baseline": self.baseline}, self.scenario)
        except (EvidenceError, ValueError, KeyError, TypeError):
            raise RuntimeErrorCode("adaptive_evidence_mismatch") from None
        started, timeline = result["timing"]["startedAtMs"], result["timeline"]
        session = self.state["session"]
        for field, offset in (("api_started_at_ms", "api_started_ms"), ("api_ended_at_ms", "api_ended_ms"),
                              ("controller_started_at_ms", "program_started_ms"), ("controller_ended_at_ms", "program_ended_ms")):
            session[field] = started + timeline[offset]
        session.update(protocol=self.scenario["protocol"], api_intervals=verified["api_intervals"],
                       adaptive_trace_sha256=result["adaptiveTrace"]["sha256"])
        require(started >= session["login_at_ms"] and result["timing"]["endedAtMs"] <= self.host.now(),
                "controller_host_clock_mismatch")
        self.validate_settlement()
        usage = verified["counters"]
        return {"status": "completed", "protocol": self.trial_protocol(),
                "requested_model": spec["model"], "returned_model": spec["model"],
                "api_requests": usage["api_requests_started"], "output_tokens": usage["actual_output_tokens"],
                "total_tokens": usage["actual_total_tokens"], "actions": usage["actions"],
                "controller_ms": verified["wall_elapsed_ms"], "recording_complete": True}

    def verify_api_result(self, prompt):
        from full_client_publish import PROGRAM_FORMAT
        arts, result = self.state["artifacts"], self.state["result"]
        request = parse_json(read_artifact_bytes(self.directory, arts["api_request"], "api_request"))
        response = parse_json(read_artifact_bytes(self.directory, arts["api_response"], "api_response"))
        require(set(request) == {"model", "store", "reasoning", "instructions", "input",
                                 "max_output_tokens", "text", "metadata"}
                and request["model"] == self.context["request"]["model"] and request["store"] is False
                and request["reasoning"] == {"effort": "low"} and request["instructions"] == prompt
                and same_json(parse_json(request["input"]), {"observation": result["initial"]})
                and request["max_output_tokens"] == 3000
                and same_json(request["text"], {"format": PROGRAM_FORMAT})
                and request["metadata"].get("maplebench_run_id") == self.run_id, "actual_api_request_mismatch")
        readiness=parse_json(read_artifact_bytes(self.directory,arts['readiness'],'readiness'))
        require(same_json(readiness,result.get('readiness'))
                and arts['readiness']['sha256']==result.get('readinessSha256')
                and same_json(readiness.get('policy'),self.readiness_policy())
                and same_json(result['controller'].get('readinessPolicy'),readiness['policy'])
                and readiness.get('run_id')==self.run_id
                and readiness.get('initial_observation_sha256')==observation_sha256(result['initial']),
                'readiness_receipt_mismatch')
        require(all(same_json(response.get(k), result["api"].get(k)) for k in ("id", "status", "model", "usage"))
                and response.get("metadata", {}).get("maplebench_run_id") == self.run_id,
                "actual_api_response_mismatch")
        text = "".join(part["text"] for item in response["output"] if item.get("type") == "message"
                       for part in item["content"] if part.get("type") == "output_text")
        program = parse_json(text)
        require(set(program) == {"note", "code"} and isinstance(program["note"], str)
                and isinstance(program["code"], str) and 0 < len(program["code"]) <= 12000
                and len(program["note"]) <= 2000, "invalid_provider_program")
        raw = read_artifact_bytes(self.directory, arts["program"], "program", maximum=65536)
        require(raw == program["code"].encode() and arts["program"]["sha256"] == result["programSha256"],
                "executed_program_mismatch")

    def copy_controller_metadata(self):
        require(self.account_state() == 0 and self.state.get("ordinary_logout"),
                "controller_collection_requires_logout")
        source = absolute(self.config["relay_output_root"]) / self.run_id
        require(source.resolve() == source and source.is_dir(), "run_artifacts_missing")
        names = {"result": "result.json", "api_request": "api-request-body.json",
                 "api_response": "api-response.json", "program": "program.js", "recording": "recording.json",
                 "capture": "capture.json", "capture_ready": "capture-ready.json",
                 "capture_clock": "capture-clock.json", "capture_terminal": "capture-terminal.json",
                 "readiness":"readiness.json"}
        adaptive = self.scenario.get("protocol") == "full-client-adaptive-pilot-v1"
        if adaptive:
            for key in ("api_request", "api_response", "program"):
                names.pop(key)
        for key, filename in names.items():
            path = source / filename
            raw = self.read_stable(path, JSON_LIMIT)
            self.state["artifacts"][key] = self.artifact("controller-" + filename, raw=raw)
        self.state["result"] = parse_json(read_artifact_bytes(self.directory, self.state["artifacts"]["result"], "result"))
        if adaptive:
            from full_client_adaptive_evidence import references
            for ref in references(self.state["result"]):
                raw = read_artifact_bytes(source, ref, "adaptive_cycle", maximum=JSON_LIMIT)
                destination = self.directory / ref["path"]
                parent = self.directory
                for part in Path(ref["path"]).parts[:-1]:
                    parent = private_directory(parent / part, create=True)
                copied = save_bytes(destination, raw)
                require(copied["sha256"] == ref["sha256"], "adaptive_evidence_mismatch")
            self.state["artifacts"]["adaptive"] = self.state["result"]["adaptiveTrace"]
        recording = parse_json(read_artifact_bytes(self.directory, self.state["artifacts"]["recording"], "recording"))
        require(recording.get("status") == "completed" and SHA.fullmatch(recording.get("sha256", ""))
                and recording.get("overlay") == {"controller_id": self.run_id, "mode": "api",
                                                 "model": self.context["request"]["model"]},
                "recording_upload_receipt_missing")
        require(recording.get("capture_sha256") == self.state["artifacts"]["capture"]["sha256"],
                "capture_metadata_hash_mismatch")
        self.state["artifacts"]["upload_status"] = self.artifact("upload-status.json", self.state["upload_status"])

    def copy_run(self):
        """Large recording reads and probes run only after ordinary logout."""
        require(self.account_state() == 0 and self.state.get("ordinary_logout"),
                "controller_collection_requires_logout")
        source = absolute(self.config["relay_output_root"]) / self.run_id
        recording = parse_json(read_artifact_bytes(self.directory, self.state["artifacts"]["recording"], "recording"))
        path = source / "video.webm"
        with open_verified_artifact(source, {"path": path.name, "sha256": recording["sha256"]},
                                    "video", maximum=MAX_VIDEO) as stream:
            destination = self.directory / "video.webm"
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as out:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    out.write(block)
                out.flush()
                os.fsync(out.fileno())
        self.state["artifacts"]["video"] = {"path": "video.webm", "sha256": recording["sha256"]}
        from full_client_publish import _probe_video, verify_capture_bundle
        try:
            probe = _probe_video(self.directory / "video.webm", recording["sha256"],
                **({"maximum_ms": 335000} if getattr(self, "scenario", {}).get("protocol") == "full-client-adaptive-pilot-v1" else {})) | {"video_sha256": recording["sha256"]}
        except EvidenceError:
            raise RuntimeErrorCode("recording_probe_failed") from None
        from full_client_capture import verify_video_duration
        try:
            verify_video_duration(probe,recording,getattr(self,'scenario',{}).get('adaptive_protocol',{}).get('capture_duration_policy'))
        except (ValueError,TypeError):
            raise RuntimeErrorCode('recording_duration_mismatch') from None
        self.state["artifacts"]["video_probe"] = self.artifact("video-probe.json", probe)
        try:
            verify_capture_bundle({"result": self.state["result"], "video": recording,
                                   "artifacts": self.state["artifacts"]}, self.directory)
        except EvidenceError:
            raise RuntimeErrorCode("capture_verification_failed") from None

    @staticmethod
    def read_stable(path, maximum):
        require(path.resolve() == path, "artifact_symlink")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_size <= maximum, "artifact_size_limit")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
            current = path.stat()
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            require(len(raw) <= maximum and all(getattr(before, key) == getattr(after, key) == getattr(current, key)
                    for key in fields), "artifact_changed_during_collection")
            return raw

    def request_ordinary_disconnect(self):
        """One journaled ordinary navigation; never automatically reissue it."""
        self.owned_server()
        require("disconnect" not in self.state["intents"], "operation_already_attempted")
        requested = self.host.now()
        self.state["session"]["disconnect_requested_at_ms"] = requested
        self.intent("disconnect")
        def offline():
            self.owned_server()
            self.online_identity()
            session = self.admin("status").get("session", {})
            return (session.get("state") == "waiting" and session.get("fresh") is True
                    and session.get("artifactsSettled") is True and self.account_state() == 0)
        deadline = self.host.deadline
        self.host.deadline = min(deadline, time.monotonic() + SETTLEMENT_POLICY["logout_after_disconnect_ms"] / 1000)
        try:
            self.admin("disconnect")
            self.wait_for(offline)
        finally:
            self.host.deadline = deadline
        logged_out = self.host.now()
        require(0 <= logged_out - requested <= SETTLEMENT_POLICY["logout_after_disconnect_ms"],
                "settlement_logout_timeout")
        rows = [parse_json(row) for row in self.read_stable(Path(self.state["native_directory"]) / "save.jsonl", JSON_LIMIT).splitlines()]
        require(rows and all(row.get("kind") == "save_committed" and all(row.get(k) == v for k, v in self.identity().items())
                            for row in rows), "native_save_failure_or_identity_mismatch")
        selected = [row for row in rows if requested <= row.get("committed_at_ms", 0) <= logged_out]
        require(len(selected) == 1, "native_logout_commit_missing_or_ambiguous")
        self.state["session"]["logged_out_at_ms"] = logged_out
        self.state["committed_at_ms"] = selected[0]["committed_at_ms"]
        self.event("logged_out", logged_out)
        self.state["ordinary_logout"] = {"schema_version": 1, "source": "cosmic_ordinary_disconnect",
                                          **self.identity(), "disconnect_requested_at_ms": requested,
                                          "logged_out_at_ms": logged_out,
                                          "save_committed_at_ms": self.state["committed_at_ms"]}
        self.persist()
        return self.disconnect()

    def disconnect(self):
        """Verify a durable ordinary logout receipt; this phase never navigates."""
        self.owned_server()
        require(self.account_state() == 0 and self.state.get("ordinary_logout")
                and "disconnect" in self.state["intents"], "normal_committed_logout_required")
        expected = {"schema_version": 1, "source": "cosmic_ordinary_disconnect", **self.identity(),
                    "disconnect_requested_at_ms": self.state["session"]["disconnect_requested_at_ms"],
                    "logged_out_at_ms": self.state["session"]["logged_out_at_ms"],
                    "save_committed_at_ms": self.state["committed_at_ms"]}
        require(same_json(self.state["ordinary_logout"], expected), "ordinary_logout_receipt_mismatch")
        return {"normal_disconnect": True, "save_committed_at_ms": self.state["committed_at_ms"]}

    def validate_settlement(self):
        """Bind actual offline artifacts to the frozen, identical settlement policy."""
        require(same_json(self.scenario.get("settlement_policy"), SETTLEMENT_POLICY),
                "invalid_settlement_policy")
        result, session = self.state["result"], self.state["session"]
        program_end = result["timing"]["startedAtMs"] + result["timeline"]["program_ended_ms"]
        upload, requested, offline = (session[name] for name in
            ("upload_observed_at_ms", "disconnect_requested_at_ms", "logged_out_at_ms"))
        require(all(type(value) is int and 0 <= value <= 2**53 - 1
                    for value in (program_end, upload, requested, offline)), "invalid_settlement_timestamps")
        require(program_end <= upload <= requested
                and upload - program_end <= SETTLEMENT_POLICY["upload_after_program_ms"]
                and requested - program_end <= SETTLEMENT_POLICY["disconnect_after_program_ms"]
                and 0 <= offline - requested <= SETTLEMENT_POLICY["logout_after_disconnect_ms"],
                "settlement_interval_exceeded")
        observation = self.state["upload_status"]
        require(all(observation.get(key) == value for key, value in self.identity().items())
                and observation.get("schema_version") == 1 and observation.get("source") == "full_client_runtime_status"
                and observation.get("observed_at_ms") == upload, "settlement_status_mismatch")
        status = observation["status"]
        run = status.get("bridge", {}).get("run") or {}
        require(run.get("id") == self.run_id and run.get("status") == "completed"
                and run.get("workerActive") is False and run.get("evidenceStatus") == "saved"
                and run.get("recordingStatus") == "saved"
                and status.get("session", {}).get("artifactsSettled") is True, "settlement_status_mismatch")
        capture = parse_json(read_artifact_bytes(self.directory, self.state["artifacts"]["capture"], "capture"))
        clock = capture["clock"]
        times = (capture["end_wall_ms"], clock["server_received_ms"], clock["client_sent_ms"])
        require(all(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 2**53 - 1
                    for value in times), "invalid_settlement_timestamps")
        end_upper = times[0] + times[1] - times[2]
        require(end_upper <= program_end + SETTLEMENT_POLICY["capture_tail_ms"],
                "settlement_capture_tail_exceeded")

    def collect_final(self):
        self.owned_server()
        require(self.state.get("committed_at_ms") and self.account_state() == 0, "normal_committed_logout_required")
        self.intent("collect_final")
        self.disconnect()
        self.validate_settlement()
        self.copy_run()
        final = self.host.snapshot(self.config["mysql"], self.run_id)
        self.event("collection_completed", final["captured_at_ms"])
        arts = self.state["artifacts"]
        arts["final_db"] = self.artifact("final-db.json", final)
        arts["save"] = self.artifact("native-save.jsonl", raw=self.read_stable(
            Path(self.state["native_directory"]) / "save.jsonl", JSON_LIMIT))
        native = self.host.command([self.config["journalctl"], "--no-pager", "--output=cat",
                                   "_SYSTEMD_INVOCATION_ID=" + self.state["invocation_id"]])
        arts["native_log"] = self.artifact("native-log.txt", raw=native)
        arts["server_log"] = self.artifact("lifecycle.jsonl", raw=b"".join(encoded(row) for row in self.state["events"]))
        session = {**self.state["session"], "run_id": self.run_id,
                   "server_instance_id": self.state["server_instance_id"], "disconnect_kind": "normal",
                   "world_lock_held_throughout": True, "queue_lock_held_throughout": True,
                   "save": {"status": "confirmed", "run_id": self.run_id,
                            "server_instance_id": self.state["server_instance_id"],
                            "character_id": self.config["mysql"]["character_id"],
                            "committed_at_ms": self.state["committed_at_ms"],
                            "evidence_sha256": arts["save"]["sha256"], "logs_sha256": arts["server_log"]["sha256"],
                            "native_logs_sha256": arts["native_log"]["sha256"], "save_error_count": 0,
                            "log_checked_from_ms": self.state["session"]["server_started_at_ms"],
                            "log_checked_through_ms": final["captured_at_ms"]}}
        adaptive = self.scenario.get("protocol") == "full-client-adaptive-pilot-v1"
        evidence = {"schema_version": 2 if adaptive else 1, "source": SOURCE, "run_id": self.run_id,
                    "scenario_fingerprint": self.config["scenario"]["sha256"],
                    "baseline": {"sha256": self.config["baseline"]["sha256"],
                                 "character": self.baseline["character"], "keymap": self.baseline["keymap"]},
                    "reset": self.state["reset"], "session": session,
                    "initial": self.state["initial"] | {"evidence_sha256": arts["initial_db"]["sha256"]},
                    "final": final | {"evidence_sha256": arts["final_db"]["sha256"]}}
        if adaptive:
            evidence["protocol"] = self.scenario["protocol"]
        arts["session"] = self.artifact("session.json", session)
        windows = self.xp_window_contract()
        if windows is None:
            arts["persistence"] = self.artifact("persistence.json", evidence)
        self.ownership()
        self.owned_server()
        self.frozen()
        if windows:
            evidence, score = self.collect_xp_windows(windows)
        else:
            score = verify_trial_bundle(evidence, self.directory, arts)
        arts["score"] = self.artifact("score.json", score)
        self.write_publication_candidate(score, arts)
        return {"evidence": evidence, "artifacts": arts}

    def collect_xp_windows(self, contract):
        """Only after ordinary logout; missing evidence is recorded as unknown."""
        require(self.account_state() == 0 and self.state.get("ordinary_logout"),
                "normal_committed_logout_required")
        arts = self.state["artifacts"]
        status = {"schema_version":1, "protocol":xp_windows.PROTOCOL, "run_id":self.run_id,
                  "status":"unknown", "task_score":None, "publication_eligible":False}
        try:
            raw = self.read_stable(Path(self.state["native_directory"]) / "xp.jsonl", xp_windows.MAX_LEDGER_BYTES)
            arts["xp_ledger"] = self.artifact("native-xp.jsonl", raw=raw)
            require(self.state.get("xp_header", {}).get("sha256") == hashlib.sha256(raw.splitlines(keepends=True)[0]).hexdigest(),
                    "native_xp_header_invalid")
            names = {"native_save":"save", "baseline_sql":"baseline", "controller_result":"result"}
            refs = {name:arts[names.get(name,name)] for name in ("xp_ledger", "native_save", "native_log", "initial_db",
                "final_db", "session", "scenario", "controller_result", "baseline_sql", "baseline_snapshot", "reset", "server_log")}
            timing = self.state["result"]["adaptive"]["timing"]
            evidence = {"schema_version":1, "protocol":xp_windows.PROTOCOL, **self.identity(),
                "window":{"start_at_ms":timing["wall_started_at_ms"], "deadline_at_ms":timing["wall_deadline_at_ms"], "window_ms":15000},
                "normalization":contract["normalization"], "experience_table_sha256":contract["experience_table_sha256"],
                "baseline_sha256":self.config["baseline"]["sha256"], "scenario_fingerprint":self.config["scenario"]["sha256"],
                "artifacts":refs}
            arts["xp_manifest"] = self.artifact("xp-window-manifest.json", evidence)
            score = xp_windows.verify_trial_bundle(evidence, self.directory, arts)
            status.update(status="verified_native_windows", task_score=score["task_score"])
        except (EvidenceError, RuntimeErrorCode, OSError, ValueError, TypeError, KeyError, IndexError):
            status["reason"] = "missing_or_inconsistent_native_window_evidence"
            arts["xp_window_status"] = self.artifact("xp-window-status.json", status)
            self.state["xp_window_status"] = status
            self.persist()
            raise RuntimeErrorCode("xp_window_evidence_incomplete") from None
        arts["xp_window_status"] = self.artifact("xp-window-status.json", status)
        self.state["xp_window_status"] = status
        return evidence, score

    def write_publication_candidate(self, score, arts):
        recording = parse_json(read_artifact_bytes(self.directory, arts["recording"], "recording"))
        candidate = {"schema_version": 2, "run_kind": "ranked",
                     "candidate_status": "awaiting_exact_recording_review",
                     "result": self.state["result"], "timeline": self.state["result"]["timeline"],
                     "budgets": self.scenario["budgets"],
                     "scenario": {"id": self.scenario["id"], "fingerprint": self.config["scenario"]["sha256"],
                                  "reset_fingerprint": self.config["baseline"]["sha256"]},
                     "score": score, "video": recording | {"path": arts["video"]["path"], "reviewed": False},
                     "artifacts": dict(arts)}
        if self.scenario.get("protocol") == "full-client-adaptive-pilot-v1":
            candidate.update(schema_version=3, protocol=self.scenario["protocol"], run_kind="adaptive_pilot",
                candidate_status="awaiting_adaptive_publication_review", publication_eligible=False,
                authoritative_peak_xp_per_minute=None, authoritative_window_status="not_collected")
        if self.xp_window_contract():
            candidate.update(schema_version=4, protocol=xp_windows.PROTOCOL, run_kind="xp_window_pilot",
                candidate_status="awaiting_native_window_publication_acceptance", publication_eligible=False,
                authoritative_peak_xp_per_minute=score["peak_normalized_xp_per_minute"],
                authoritative_window_status="verified_native_windows")
        self.artifact("publication-candidate.json", candidate)

    def settle_owned_controller(self):
        status = self.admin("status")
        bridge, run = status.get("bridge", {}), status.get("bridge", {}).get("run") or {}
        if run.get("id") != self.run_id:
            require(run.get("workerActive") is not True
                    and run.get("status") not in ("requesting", "running")
                    and bridge.get("browserReleasePending") is not True,
                    "unowned_controller_cleanup_refused")
            return
        if run.get("workerActive") is True or run.get("status") in ("requesting", "running"):
            self.admin("cancel", run_id=self.run_id)
        def quiescent():
            current = self.admin("status")
            bridge = current.get("bridge", {})
            active = bridge.get("run") or {}
            require(active.get("id") == self.run_id, "controller_run_identity_lost")
            return (current if active.get("workerActive") is False
                    and active.get("status") not in ("requesting", "running")
                    and bridge.get("browserReleasePending") is False else None)
        status = self.wait_for(quiescent)
        run = status["bridge"]["run"]
        if run.get("status") != "completed" or run.get("recordingStatus") != "saved":
            # Persist the actual status before acknowledging failure. The bridge
            # retains all original files; copying them must wait until offline.
            if not self.state.get("failure_cleanup_status"):
                self.state["failure_cleanup_status"] = status
                self.persist()
            # cancel() sets an in-memory acknowledgment, but ordinary login
            # after restart also requires a durable release receipt.
            self.admin("release_failed_run", run_id=self.run_id)

    def preserve_failure_evidence(self):
        require(self.account_state() == 0, "controller_collection_requires_logout")
        if self.state.get("failure_cleanup_status") and not self.state.get("failure_evidence_preserved"):
            source = absolute(self.config["relay_output_root"]) / self.run_id
            for filename in ("controller.json", "failure.json", "api-request.json", "api-request-body.json",
                             "api-response.json", "result.json", "recording.json", "capture.json", "readiness.json", "cancel.json"):
                path = source / filename
                if path.exists():
                    self.artifact("failure-" + filename, raw=self.read_stable(path, JSON_LIMIT))
            self.artifact("failure-cleanup-status.json", self.state["failure_cleanup_status"])
            self.state["failure_evidence_preserved"] = True
            self.persist()

    def remove_trial_configuration(self):
        """Recover only a recorded owned removal; reloading cached state is idempotent.

        The checkpoint is durable before unlink. An explicit recovery may find
        the file absent while systemd still holds the old drop-in in memory, or
        may find that reload succeeded before its response/checkpoint was saved.
        Both cases repeat reload, never a server start or baseline operation.
        """
        path = self.trial_dropin_path()
        require(Path(self.state["dropin"]) == path, "dropin_owner_path_mismatch")
        owner = {"path": str(path), "sha256": self.state["dropin_sha256"]}
        checkpoint = self.state.get("configuration_cleanup")
        if checkpoint is not None:
            require(isinstance(checkpoint, dict) and set(checkpoint) == {"path", "sha256", "phase"}
                    and all(checkpoint.get(k) == v for k, v in owner.items())
                    and checkpoint.get("phase") in ("remove_pending", "removed", "reload_pending", "verified"),
                    "cleanup_checkpoint_invalid")
        self.state["clean"] = False
        if checkpoint and checkpoint["phase"] == "verified":
            require(self.trial_configuration_absent(self.unit("cosmic")), "cleanup_configuration_still_loaded")
            return
        if os.path.lexists(path):
            self.owned_dropin()
            self.state["configuration_cleanup"] = owner | {"phase": "remove_pending"}
            self.persist()
            path.unlink()
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            self.state["configuration_cleanup"]["phase"] = "removed"
            self.persist()
        elif checkpoint is None:
            # start_server can fail before creating its owned file. An absent
            # file without a removal checkpoint grants no right to reload an
            # unknown cached configuration.
            require(self.trial_configuration_absent(self.unit("cosmic")), "cleanup_dropin_removal_unowned")
            self.state["configuration_cleanup"] = owner | {"phase": "verified"}
            self.persist()
            return
        require(self.stopped(self.unit("cosmic")) and self.account_state() == 0,
                "cleanup_requires_stopped_offline")
        self.state["configuration_cleanup"]["phase"] = "reload_pending"
        self.persist()
        self.host.command([self.config["systemctl"], "daemon-reload"])
        require(self.trial_configuration_absent(self.unit("cosmic")), "cleanup_configuration_still_loaded")
        self.state["configuration_cleanup"]["phase"] = "verified"
        self.persist()

    def prepare_cleanup_wait(self):
        """Confirm ordinary waiting navigation within a separate finite window."""
        requested = self.host.now()
        self.state.setdefault("cleanup_wait_requests", []).append(requested)
        self.persist()
        deadline = self.host.deadline
        self.host.deadline = min(deadline, time.monotonic() + 15)
        try:
            self.admin("prepare_wait")
            def waiting():
                status = self.admin("status")
                session, bridge = status.get("session", {}), status.get("bridge", {})
                run = bridge.get("run") or {}
                initial = run.get("id") is None and run.get("status") == "idle"
                terminal = not run or initial or run.get("status") in ("completed", "failed", "timed_out", "cancelled")
                return (status if session.get("state") == "waiting" and session.get("fresh") is True
                        and session.get("pinned") is True and session.get("captureState") == "idle"
                        and session.get("artifactsSettled") is True and terminal
                        and run.get("workerActive") is not True and run.get("leaseReleasePending") is not True
                        and bridge.get("browserReleasePending") is not True else None)
            status = self.wait_for(waiting)
        finally:
            self.host.deadline = deadline
        self.state["cleanup_wait"] = {"requested_at_ms": requested, "verified_at_ms": self.host.now(),
                                      "session": status["session"]}
        self.persist()

    def cleanup(self):
        # No earlier clean receipt can survive an uncertain fresh cleanup.
        self.state["clean"] = False
        self.persist()
        # Recovery can encounter a start whose response was lost. Native env plus
        # the exact recorded drop-in is required before adopting that invocation.
        unit = self.unit("cosmic")
        if not self.stopped(unit):
            require(self.state.get("dropin"), "unowned_server_cleanup_refused")
            self.owned_dropin()
            self.validate_process(unit)
            require(unit.get("InvocationID") != self.state.get("previous_invocation_id"),
                    "unowned_server_cleanup_refused")
            if self.state.get("invocation_id"):
                require(unit.get("InvocationID") == self.state["invocation_id"], "server_instance_ownership_lost")
        self.settle_owned_controller()
        if not self.stopped(unit):
            # Explicit recovery may retry an uncertain navigation, but its own
            # intent is durable and it can never produce a valid trial receipt.
            self.state.setdefault("recovery_disconnect_requests", []).append(self.host.now())
            self.persist()
            self.admin("disconnect")
            self.wait_for(lambda: self.account_state() == 0)
            self.host.command([self.config["systemctl"], "stop", self.config["services"]["cosmic"]])
        require(self.stopped(self.unit("cosmic")) and self.account_state() == 0,
                "cleanup_requires_stopped_offline")
        self.preserve_failure_evidence()
        if self.state.get("dropin"):
            self.remove_trial_configuration()
        require(self.trial_configuration_absent(self.unit("cosmic")), "cleanup_configuration_still_loaded")
        self.prepare_cleanup_wait()
        require(self.stopped(self.unit("cosmic")) and self.account_state() == 0,
                "cleanup_requires_stopped_offline")
        require(self.trial_configuration_absent(self.unit("cosmic")), "cleanup_configuration_still_loaded")
        self.state["clean"] = True
        self.persist()
        return {"clean": True}

    def perform(self, operation, context, *, timeout_seconds):
        require(type(timeout_seconds) in (int, float) and 0 < timeout_seconds <= 1800, "invalid_timeout")
        require(operation in ("status", "restore_baseline", "start_server", "login", "run_controller",
                              "disconnect", "collect_final", "cleanup"), "unknown_operation")
        self.host.deadline = time.monotonic() + timeout_seconds
        self.context = context
        if context.get("attempt_id"):
            self.run_id = context["attempt_id"]
            require(RUN.fullmatch(self.run_id) is not None, "run_id_must_be_32_hex")
            root = private_directory(self.config["attempt_root"])
            self.directory = private_directory(context["attempt_dir"])
            require(self.directory == root / self.run_id, "attempt_directory_mismatch")
            state_file = self.directory / "backend-state.json"
            if state_file.exists():
                self.state = read_private_json(state_file)
                if self.state.get("adaptive_result_ref"):
                    self.state["result"] = parse_json(read_artifact_bytes(self.directory, self.state["adaptive_result_ref"], "result"))
                require(self.state.get("attempt_id") == self.run_id, "backend_owner_mismatch")
        if operation == "status":
            return self.status()
        self.ownership()
        self.quiet()
        spec = validate_spec(context["request"])
        require(spec["baseline_sha256"] == self.config["baseline"]["sha256"]
                and spec["scenario_fingerprint"] == self.config["scenario"]["sha256"], "frozen_spec_mismatch")
        if operation in ("run_controller", "disconnect", "cleanup"):
            self.load_pins()
            self.online_identity()
        else:
            self.frozen()
        require(same_json(self.scenario.get("trial_budgets"), spec["budgets"])
                and (spec.get("protocol") == self.trial_protocol()), "scenario_trial_budgets_mismatch")
        if self.state is None:
            if operation == "cleanup":
                status = self.status()
                require(status["ready"], "cleanup_without_owner_requires_ready")
                return {"attempt_id": self.run_id, "clean": True}
            require(operation == "restore_baseline", "backend_state_missing")
            self.state = {"schema_version": 1, "attempt_id": self.run_id,
                          "server_instance_id": uuid.uuid4().hex, "intents": [], "events": [],
                          "session": {}, "artifacts": {}, "publication_eligible": False}
            self.persist()
        if operation == "login":
            self.state["prelogin_frozen"] = {"scenario_sha256": self.config["scenario"]["sha256"],
                                             "manifest_sha256": self.config["runtime_manifest"]["sha256"],
                                             "checked_at_ms": self.host.now()}
            self.persist()
        elif operation == "run_controller":
            checkpoint = self.state.get("prelogin_frozen", {})
            require(checkpoint.get("scenario_sha256") == self.config["scenario"]["sha256"]
                    and checkpoint.get("manifest_sha256") == self.config["runtime_manifest"]["sha256"]
                    and type(checkpoint.get("checked_at_ms")) is int
                    and checkpoint["checked_at_ms"] <= self.state["session"].get("login_at_ms", -1),
                    "prelogin_inventory_required")
        result = getattr(self, operation)()
        self.ownership()
        self.quiet()
        if operation == "login":
            self.online_identity()
            self.owned_server()
        else:
            require(self.account_state() == 0, "inventory_requires_offline_account")
            self.frozen()
        self.persist()
        return {"attempt_id": self.run_id, **result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        require(os.geteuid() == 0 and sys.platform.startswith("linux"), "linux_root_runner_required")
        config = read_private_json(args.config)
        request = parse_json(sys.stdin.buffer.read(JSON_LIMIT + 1))
        require(isinstance(request, dict) and set(request) == {"operation", "context", "timeout_seconds"},
                "invalid_backend_request")
        result = CosmicRuntime(config).perform(request["operation"], request["context"],
                                               timeout_seconds=request["timeout_seconds"])
    except RuntimeErrorCode as error:
        print(json.dumps({"error": str(error) if str(error) in RUNTIME_ERROR_CODES else "runtime_operation_failed"}))
        return 1
    except (FreezeError, DockerBindingError) as error:
        print(json.dumps({"error": str(error) if str(error) in FREEZE_ERROR_CODES else "runtime_operation_failed"}))
        return 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error, subprocess.SubprocessError):
        print(json.dumps({"error": "runtime_operation_failed"}))
        return 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
