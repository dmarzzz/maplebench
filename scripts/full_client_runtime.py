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
import os
from pathlib import Path
import pwd
import re
import resource
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
from full_client_freeze import verify_manifest
from full_client_score import (SOURCE, JSON_LIMIT, parse_json, read_artifact_bytes,
                               open_verified_artifact, same_json, verify_trial_bundle)
from full_client_trial import atomic_json, private_directory, read_private_json, validate_spec

SHA = re.compile(r"[0-9a-f]{64}\Z")
RUN = re.compile(r"[0-9a-f]{32}\Z")
UNIT = re.compile(r"[A-Za-z0-9_.@-]+\.service\Z")
NATIVE_CLASS = "server/bots/MapleBenchPersistence.class"
MAX_SQL = 64 * 1024 * 1024
MAX_VIDEO = 512 * 1024 * 1024
ENV_NAMES = ("MAPLEBENCH_TRIAL_ID", "MAPLEBENCH_SERVER_INSTANCE_ID",
             "MAPLEBENCH_PERSIST_CHARACTER_ID", "MAPLEBENCH_PERSIST_ACCOUNT_ID",
             "MAPLEBENCH_SAVE_JOURNAL")


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
            result = subprocess.run(argv, input=data, stdout=output, stderr=subprocess.DEVNULL,
                                    timeout=self.remaining(), check=False, preexec_fn=cap_output,
                                    env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
            require(result.returncode == 0, "host_command_failed")
            require(output.tell() < maximum, "host_output_limit")
            output.seek(0)
            return output.read(maximum)

    def unit(self, systemctl, unit):
        raw = self.command([systemctl, "show", unit, "--no-pager",
                            "--property=LoadState,ActiveState,SubState,MainPID,User,Group,"
                            "WorkingDirectory,InvocationID,ExecMainStartTimestampMonotonic,Environment"])
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
        require(response.get("ok") is True and isinstance(response.get("result"), dict),
                "admin_operation_failed")
        return response["result"]

    def proc(self, pid, name):
        return Path(f"/proc/{pid}/{name}").read_bytes()

    def executable(self, pid):
        return str(Path(f"/proc/{pid}/exe").resolve(strict=True))

    def process_started_ms(self, pid):
        fields = self.proc(pid, "stat").decode().rsplit(")", 1)[1].split()
        started = int(fields[19]) / os.sysconf("SC_CLK_TCK")
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        return self.now() - (uptime - started) * 1000

    def listening_ports(self, pid):
        inodes = set()
        for item in Path(f"/proc/{pid}/fd").iterdir():
            try:
                match = re.fullmatch(r"socket:\[(\d+)\]", os.readlink(item))
                if match:
                    inodes.add(match[1])
            except FileNotFoundError:
                continue
        ports = set()
        for name in ("tcp", "tcp6"):
            for line in self.proc(pid, "net/" + name).decode().splitlines()[1:]:
                values = line.split()
                if len(values) > 9 and values[3] == "0A" and values[9] in inodes:
                    ports.add(int(values[1].rsplit(":", 1)[1], 16))
        return ports

    def locks(self):
        return Path("/proc/locks").read_text()

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
        return collect(mysql_command=config["command"], database=config["database"],
                       defaults_file=config.get("defaults_file"), run_id=run_id,
                       character_id=config["character_id"], account_id=config["account_id"],
                       timeout=min(10, self.remaining()))


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

    def frozen(self):
        self.scenario = parse_json(ref_bytes(self.config["scenario"]))
        duration = self.scenario.get("program_seconds")
        require(type(duration) is int and duration in (22, 60)
                and isinstance(self.scenario.get("id"), str) and 0 < len(self.scenario["id"]) <= 128
                and SHA.fullmatch(self.scenario.get("instructions_sha256", "")) is not None
                and same_json(self.scenario.get("reasoning"), {"effort": "low"}), "invalid_frozen_scenario")
        expected_budgets = {"api_requests": 1, "output_tokens": 3000,
                            "total_tokens": self.scenario["trial_budgets"]["max_total_tokens"],
                            "program_ms": duration * 1000, "run_ms": (duration + 53) * 1000,
                            "actions": 80 if duration == 22 else 240, "sdk_requests": 100 if duration == 22 else 600}
        require(same_json(self.scenario.get("budgets"), expected_budgets), "frozen_bridge_budgets_mismatch")
        self.baseline = parse_json(ref_bytes(self.config["baseline_snapshot"]))
        manifest = parse_json(ref_bytes(self.config["runtime_manifest"]))
        absolute(manifest["working_directory"])
        absolute(manifest["wz_path"])
        verify_manifest(manifest, docker_command=[self.config["docker"]],
                        limits={"timeout_seconds": max(1, int(self.host.remaining()))})
        jar = manifest["server_jar"]
        path = absolute(jar["path"])
        with open_verified_artifact(path.parent, {"path": path.name, "sha256": jar["sha256"]},
                                    "server_jar", maximum=512 * 1024 * 1024) as stream:
            with zipfile.ZipFile(stream) as archive:
                require(NATIVE_CLASS in archive.namelist(), "native_persistence_class_missing")
        self.manifest = manifest
        cosmic, web = self.unit("cosmic"), self.unit("web")
        require(pwd.getpwnam(cosmic.get("User", "")).pw_uid != 0
                and pwd.getpwnam(web.get("User", "")).pw_uid != 0
                and web.get("ActiveState") == "active", "unprivileged_services_required")
        self.web_identity(web)
        ref_bytes(self.config["java"], MAX_SQL)
        require(os.access(self.config["java"]["path"], os.X_OK), "java_executable_required")
        db = self.config["mysql"]
        require(self.baseline.get("account_logged_in") == 0 and all(
            self.baseline["character"].get(k) == db[k] for k in ("character_id", "account_id")),
            "baseline_identity_mismatch")
        # Validate SQL bytes before considering the backend ready, never execute here.
        ref_bytes(self.config["baseline"], MAX_SQL)
        ref_bytes(self.config["orchestrator"])

    def web_identity(self, unit):
        """Bind frozen files to the actual serving process and its import roots."""
        manifest = self.manifest
        root = absolute(manifest["client_js"]["path"]).parent.parent
        require(Path(manifest["client_js"]["path"]) == root / "build/JourneyClient.js"
                and Path(manifest["client_wasm"]["path"]) == root / "build/JourneyClient.wasm",
                "served_client_build_paths_mismatch")
        script = absolute(self.config["web_script"])
        controls = script.parent.parent / "ui/full-client"
        required = {script, *(script.parent / name for name in ("full_client_bridge.py", "full_client_session.py", "full_client_capture.py", "maple_agent.py")),
                    controls / "controller.js", controls / "waiting.html",
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
        atomic_json(self.directory / "backend-state.json", self.state)

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
        expected = Path(self.config["dropin_root"]) / (self.config["services"]["cosmic"] + ".d") / "90-maplebench-trial.conf"
        require(Path(self.state["dropin"]) == expected, "dropin_owner_path_mismatch")
        raw = self.read_stable(expected, 16384)
        require(hashlib.sha256(raw).hexdigest() == self.state["dropin_sha256"], "dropin_ownership_lost")

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
        self.frozen()
        world, worker, cosmic = self.unit("world"), self.unit("worker"), self.unit("cosmic")
        admin = self.admin("status")
        session, bridge = admin.get("session", {}), admin.get("bridge", {})
        idle = session.get("artifactsSettled") is True and (not bridge.get("run") or
            bridge["run"].get("status") in ("completed", "failed", "timed_out", "cancelled"))
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
        return {"ready": queue and stopped and offline and idle and waiting and not conflict,
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
        require(not any(name in before.get("Environment", "") for name in ENV_NAMES),
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
        dropin = dropin_dir / "90-maplebench-trial.conf"
        require(not dropin.exists() and not native.exists(), "existing_trial_owner")
        env = dict(zip(ENV_NAMES, (self.run_id, self.state["server_instance_id"],
                       str(self.config["mysql"]["character_id"]), str(self.config["mysql"]["account_id"]),
                       str(native / "save.jsonl"))))
        # The normal worker's service enables the legacy bot/SDK adapter. An
        # ordinary full-client trial must explicitly override that inherited mode.
        env["MAPLEBENCH_ENABLED"] = "false"
        text = "[Service]\n" + "".join('Environment="' + key + '=' + value.replace('\\', '\\\\').replace('"', '\\"') + '"\n'
                                       for key, value in env.items())
        text += "MemoryMax=2300M\nMemorySwapMax=0\nCPUQuota=200%\nRestart=no\nKillMode=control-group\nTimeoutStopSec=30\nRuntimeMaxSec=" + str(self.context["request"]["budgets"]["total_seconds"] + 120) + "\n"
        def quote(value):
            return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '$$') + '"'
        launch = [self.config["java"]["path"], "-Xmx1536m", "-XX:ActiveProcessorCount=2",
                  "-Dwz-path=" + self.manifest["wz_path"], "-jar", self.manifest["server_jar"]["path"]]
        text += "WorkingDirectory=" + quote(self.manifest["working_directory"]) + "\nExecStart=\nExecStart=" + " ".join(quote(x) for x in launch) + "\n"
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
        self.state["server_start_requested_at_ms"] = self.host.now()
        self.persist()
        self.host.command([self.config["systemctl"], "start", self.config["services"]["cosmic"]])
        unit = self.unit("cosmic")
        require(unit.get("ActiveState") == "active" and unit.get("InvocationID")
                and unit["InvocationID"] != before.get("InvocationID"), "fresh_server_start_failed")
        self.state["invocation_id"] = unit["InvocationID"]
        self.persist()
        self.validate_process(unit)
        self.wait_for(self.server_ready)
        self.state["session"]["server_started_at_ms"] = self.state["server_start_requested_at_ms"]
        self.event("server_started", self.state["session"]["server_started_at_ms"])
        return {"server_instance_id": self.state["server_instance_id"], "invocation_id": unit["InvocationID"]}

    def server_ready(self):
        unit = self.owned_server()
        logs = self.host.command([self.config["journalctl"], "--no-pager", "--output=cat",
                                  "_SYSTEMD_INVOCATION_ID=" + self.state["invocation_id"]])
        require(b"MapleBench persistence journal failed" not in logs and b"Error saving chr" not in logs,
                "native_startup_or_save_failed")
        return (logs.count(b"MapleBench persistence journal initialized") == 1
                and logs.count(b"Cosmic is now online after ") == 1
                and set(self.config["game_ports"]) <= self.host.listening_ports(int(unit["MainPID"])))

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
        self.owned_server()
        require(self.state["session"].get("login_at_ms") and self.account_state() == 2,
                "ordinary_login_required")
        spec = self.context["request"]
        budgets = spec["budgets"]
        duration = self.scenario.get("program_seconds")
        require(duration in (22, 60) and type(duration) is int, "unsupported_program_duration")
        require(budgets["controller_seconds"] >= duration + 2
                and budgets["max_actions"] == (80 if duration == 22 else 240)
                and budgets["max_output_tokens"] == 3000, "bridge_budget_mismatch")
        from full_client_bridge import PROMPT
        prompt = PROMPT.format(program_seconds=duration, action_limit=budgets["max_actions"],
                              sdk_request_limit=100 if duration == 22 else 600)
        require(self.scenario.get("instructions_sha256") == hashlib.sha256(prompt.encode()).hexdigest()
                and self.scenario.get("reasoning") == {"effort": "low"}, "frozen_prompt_mismatch")
        self.intent("run_controller")
        self.admin("start", model=spec["model"], duration_seconds=duration,
                   run_id=self.run_id, request_id=self.run_id, total_token_limit=budgets["max_total_tokens"],
                   docker_image_id=self.manifest["docker_image_id"],
                   trial_context={"scenario_fingerprint": spec["scenario_fingerprint"],
                                  "baseline_sha256": spec["baseline_sha256"]})
        def completed():
            self.owned_server()
            status = self.admin("status")
            run = status.get("bridge", {}).get("run") or {}
            require(run.get("id") == self.run_id, "controller_run_identity_lost")
            if run.get("status") in ("failed", "timed_out", "cancelled"):
                raise RuntimeErrorCode("controller_run_failed")
            return (run.get("status") == "completed" and run.get("evidenceStatus") == "saved"
                    and run.get("recordingStatus") == "saved"
                    and status.get("session", {}).get("artifactsSettled") is True)
        self.wait_for(completed)
        self.copy_run()
        result = self.state["result"]
        api = result["api"]
        require(result.get("source") == "full-client-trial" and result["controller"]["id"] == self.run_id
                and result["controller"]["model"] == spec["model"] and api["model"] == spec["model"]
                and result["controller"].get("mode") == "api"
                and result["controller"].get("dockerImageId") == self.manifest["docker_image_id"]
                and result["controller"].get("status") == "completed"
                and api.get("status") == "completed", "controller_model_or_source_mismatch")
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
        return {"status": "completed", "requested_model": spec["model"], "returned_model": api["model"],
                "api_requests": 1, "output_tokens": api["usage"]["output_tokens"],
                "total_tokens": api["usage"]["total_tokens"], "actions": result["program"]["actions"],
                "controller_ms": timeline["program_ended_ms"] - timeline["program_started_ms"],
                "recording_complete": True}

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

    def copy_run(self):
        source = absolute(self.config["relay_output_root"]) / self.run_id
        require(source.resolve() == source and source.is_dir(), "run_artifacts_missing")
        names = {"result": "result.json", "api_request": "api-request-body.json",
                 "api_response": "api-response.json", "program": "program.js", "recording": "recording.json",
                 "capture": "capture.json", "capture_ready": "capture-ready.json",
                 "capture_clock": "capture-clock.json", "capture_terminal": "capture-terminal.json"}
        for key, filename in names.items():
            path = source / filename
            raw = self.read_stable(path, JSON_LIMIT)
            self.state["artifacts"][key] = self.artifact("controller-" + filename, raw=raw)
        self.state["result"] = parse_json(read_artifact_bytes(self.directory, self.state["artifacts"]["result"], "result"))
        recording = parse_json(read_artifact_bytes(self.directory, self.state["artifacts"]["recording"], "recording"))
        require(recording.get("status") == "completed" and SHA.fullmatch(recording.get("sha256", ""))
                and recording.get("overlay") == {"controller_id": self.run_id, "mode": "api",
                                                 "model": self.context["request"]["model"]},
                "recording_upload_receipt_missing")
        require(recording.get("capture_sha256") == self.state["artifacts"]["capture"]["sha256"],
                "capture_metadata_hash_mismatch")
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
        probe = _probe_video(self.directory / "video.webm", recording["sha256"]) | {"video_sha256": recording["sha256"]}
        self.state["artifacts"]["video_probe"] = self.artifact("video-probe.json", probe)
        verify_capture_bundle({"result": self.state["result"], "video": recording,
                               "artifacts": self.state["artifacts"]}, self.directory)

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

    def disconnect(self):
        self.owned_server()
        self.intent("disconnect")
        requested = self.host.now()
        self.state["session"]["disconnect_requested_at_ms"] = requested
        self.persist()
        self.admin("disconnect")
        def offline():
            self.owned_server()
            session = self.admin("status").get("session", {})
            return (session.get("state") == "waiting" and session.get("fresh") is True
                    and session.get("artifactsSettled") is True and self.account_state() == 0)
        self.wait_for(offline)
        logged_out = self.host.now()
        rows = [parse_json(row) for row in self.read_stable(Path(self.state["native_directory"]) / "save.jsonl", JSON_LIMIT).splitlines()]
        require(rows and all(row.get("kind") == "save_committed" and all(row.get(k) == v for k, v in self.identity().items())
                            for row in rows), "native_save_failure_or_identity_mismatch")
        selected = [row for row in rows if requested <= row.get("committed_at_ms", 0) <= logged_out]
        require(len(selected) == 1, "native_logout_commit_missing_or_ambiguous")
        self.state["session"]["logged_out_at_ms"] = logged_out
        self.state["committed_at_ms"] = selected[0]["committed_at_ms"]
        self.event("logged_out", logged_out)
        return {"normal_disconnect": True, "save_committed_at_ms": self.state["committed_at_ms"]}

    def collect_final(self):
        self.owned_server()
        require(self.state.get("committed_at_ms") and self.account_state() == 0, "normal_committed_logout_required")
        self.intent("collect_final")
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
        evidence = {"schema_version": 1, "source": SOURCE, "run_id": self.run_id,
                    "scenario_fingerprint": self.config["scenario"]["sha256"],
                    "baseline": {"sha256": self.config["baseline"]["sha256"],
                                 "character": self.baseline["character"], "keymap": self.baseline["keymap"]},
                    "reset": self.state["reset"], "session": session,
                    "initial": self.state["initial"] | {"evidence_sha256": arts["initial_db"]["sha256"]},
                    "final": final | {"evidence_sha256": arts["final_db"]["sha256"]}}
        arts["session"] = self.artifact("session.json", session)
        arts["persistence"] = self.artifact("persistence.json", evidence)
        self.ownership()
        self.owned_server()
        self.frozen()
        score = verify_trial_bundle(evidence, self.directory, arts)
        arts["score"] = self.artifact("score.json", score)
        self.write_publication_candidate(score, arts)
        return {"evidence": evidence, "artifacts": arts}

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
            # Preserve available failed evidence before acknowledging navigation.
            # release_failed_run retains original bridge files, including partial
            # recordings; no file removal or successful-run relabel occurs here.
            source = absolute(self.config["relay_output_root"]) / self.run_id
            if not self.state.get("failure_evidence_preserved"):
                for filename in ("controller.json", "failure.json", "api-request.json", "api-request-body.json",
                                 "api-response.json", "result.json", "recording.json", "capture.json", "cancel.json"):
                    path = source / filename
                    if path.exists():
                        self.artifact("failure-" + filename, raw=self.read_stable(path, JSON_LIMIT))
                self.artifact("failure-cleanup-status.json", status)
                self.state["failure_evidence_preserved"] = True
                self.persist()
            if run.get("failureAcknowledged") is not True:
                self.admin("release_failed_run", run_id=self.run_id)

    def cleanup(self):
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
            self.admin("disconnect")
            self.wait_for(lambda: self.account_state() == 0)
            self.host.command([self.config["systemctl"], "stop", self.config["services"]["cosmic"]])
        require(self.stopped(self.unit("cosmic")) and self.account_state() == 0,
                "cleanup_requires_stopped_offline")
        if self.state.get("dropin"):
            path = absolute(self.state["dropin"])
            if path.exists():
                raw = self.read_stable(path, 16384)
                require(hashlib.sha256(raw).hexdigest() == self.state["dropin_sha256"], "dropin_ownership_lost")
                path.unlink()
                self.host.command([self.config["systemctl"], "daemon-reload"])
        self.state["clean"] = True
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
                require(self.state.get("attempt_id") == self.run_id, "backend_owner_mismatch")
        if operation == "status":
            return self.status()
        self.ownership()
        self.quiet()
        spec = validate_spec(context["request"])
        require(spec["baseline_sha256"] == self.config["baseline"]["sha256"]
                and spec["scenario_fingerprint"] == self.config["scenario"]["sha256"], "frozen_spec_mismatch")
        self.frozen()
        require(same_json(self.scenario.get("trial_budgets"), spec["budgets"]), "scenario_trial_budgets_mismatch")
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
        result = getattr(self, operation)()
        self.ownership()
        self.quiet()
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
        print(json.dumps({"error": str(error)}))
        return 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error, subprocess.SubprocessError):
        print(json.dumps({"error": "runtime_operation_failed"}))
        return 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
