"""Offline lifecycle boundaries: actual files/flocks; never invoke host services."""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import full_client_lifecycle as lifecycle


BOOT = "11111111-1111-1111-1111-111111111111"


def write_json(path, value):
    path.write_bytes(lifecycle.encoded(value)); path.chmod(0o600)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def file_ref(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class FakeHost:
    def __init__(self, config, snapshot, request):
        self.config, self.expected, self.request = config, snapshot, request
        self.deadline = 0; self.guard_fds = []; self.command_seconds = 0
        self.clock = 100000; self.started = []; self.crash_after = None
        self.memory_bytes = 16 * 1024**3; self.worker_receipt_mutation = None
        self.identities = {"web": request["web_instance"]}
        self.engine = None

    def now(self):
        self.clock += 1
        return self.clock

    def remaining(self, cap=None):
        return min(60, cap) if cap else 60

    def boot(self): return BOOT
    def memory(self): return self.memory_bytes
    def queue(self, path): return 0
    def snapshot(self, config, run_id): return copy.deepcopy(self.expected)

    def unit(self, systemctl, unit):
        if unit == self.config["services"]["world"]:
            return {"LoadState": "loaded", "ActiveState": "inactive", "MainPID": "0", "InvocationID": "f" * 32}
        role = next(key for key in ("cosmic", "worker", "web") if self.config["services"][key]["unit"] == unit)
        service = self.config["services"][role]
        identity = self.identities.get(role)
        value = dict(service["properties"], LoadState="loaded", NeedDaemonReload="no", DropInPaths="",
            Environment=" ".join(shlex.quote(key + "=" + val) for key, val in service["environment"].items()),
            ExecStart="{ path=" + service["argv"][0] + " ; argv[]=" + shlex.join(service["argv"]) +
                      " ; ignore_errors=no ; pid=0 ; }")
        value.update(ActiveState="active" if identity else "inactive", SubState="running" if identity else "dead",
                     MainPID=str(identity["pid"]) if identity else "0",
                     InvocationID=identity["invocation_id"] if identity else self.request["stopped_invocations"][role])
        return value

    def process(self, pid):
        role = next(role for role, identity in self.identities.items() if identity["pid"] == pid)
        service = self.config["services"][role]
        return {"start_ticks": self.identities[role]["start_ticks"], "argv": [v.encode() for v in service["argv"]],
                "executable": service["executable"]["path"], "cwd": service["properties"]["WorkingDirectory"],
                "uids": [service["uid"]] * 4, "environment": {k.encode(): v.encode() for k, v in service["environment"].items()},
                "children": []}

    def lock_owners(self, pin):
        if "worker" in self.identities:
            return [] if pin == self.config["locks"]["runner"] else [self.identities["worker"]["pid"]]
        return [os.getpid()] if self.engine and self.engine.world_fds else []

    def browser(self, *args):
        return {"session": {"state": "waiting", "desiredPage": "waiting", "captureState": "idle",
                            "fresh": True, "pinned": True, "artifactsSettled": True},
                "bridge": {"run": {"id": self.request["browser_run_id"], "status": "completed",
                                    "workerActive": False, "leaseReleasePending": False},
                           "browserReleasePending": False, "quarantinedRuns": []}}

    def native(self, *args):
        return {"log_sha256": "a" * 64, "startup_sha256": "b" * 64, "ports": [7575, 8484], "observed_at_ms": self.now()}

    def command(self, argv):
        self.assert_start(argv)
        role = next(key for key in ("cosmic", "worker") if self.config["services"][key]["unit"] == argv[-1])
        stored = json.loads((self.engine.directory / "journal.json").read_text())
        assert stored["phase"] == role + "_start_pending"
        assert stored["service_starts"][role] == 1
        assert len(self.guard_fds) == (4 if role == "cosmic" else 1)
        self.started.append(role)
        self.identities[role] = {"pid": 101 if role == "cosmic" else 202,
                                "start_ticks": "101" if role == "cosmic" else "202",
                                "invocation_id": ("1" if role == "cosmic" else "2") * 32}
        if role == "worker":
            worker = self.config["services"]["worker"]
            receipt = {"schema_version": 1, "kind": "normal_worker_first_idle", "boot_id": BOOT,
                "worker": self.identities["worker"], "cosmic_before": self.identities["cosmic"],
                "cosmic_after": self.identities["cosmic"], "worker_source_sha256": worker["files"][0]["sha256"],
                "locks": {key: {name: self.config["locks"][key][name] for name in ("path", "device", "inode")}
                          for key in ("world", "queue")}, "queue_pending": 0, "trials_claimed": 0, "observed_at_ms": self.now()}
            if self.worker_receipt_mutation:
                self.worker_receipt_mutation(receipt)
            path = Path(self.config["worker_receipt_directory"]) / ("2" * 32 + ".json")
            write_json(path, receipt)
            if os.geteuid() == 0:
                os.chown(path, worker["uid"], -1)
        if self.crash_after == role:
            raise SystemExit("synthetic lost start response")
        return b""

    def assert_start(self, argv):
        assert argv[:4] == [self.config["commands"]["systemctl"]["path"], "--job-mode=fail", "start", argv[-1]]


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.uid = os.geteuid() or 1
        for name in ("state", "attempts", "receipts", "work"):
            (self.root / name).mkdir(mode=0o700)
        if os.geteuid() == 0:
            os.chown(self.root / "receipts", self.uid, -1)
        executable = self.root / "fixed-executable"; executable.write_bytes(b"never executed"); executable.chmod(0o700)
        worker_source = self.root / "worker.py"; worker_source.write_bytes(b"frozen worker source"); worker_source.chmod(0o600)
        native = self.root / "native.log"; native.write_bytes(b"previous log\n"); native.chmod(0o600)
        if os.geteuid() == 0:
            os.chown(native, self.uid, -1)
        locks = {}
        for name in ("world", "queue", "runner"):
            path = self.root / (name + ".lock"); path.touch(mode=0o600); info = path.stat()
            locks[name] = {"path": str(path), "device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid, "mode": 0o600}
        services = {"world": "world.service"}
        for role in ("cosmic", "worker", "web"):
            props = {name: "fixed" for name in lifecycle.CONFIG_PROPERTIES}; props["WorkingDirectory"] = str(self.root / "work")
            services[role] = {"unit": "maplebench-cosmic.service" if role == "cosmic" else role + ".service", "uid": self.uid,
                "argv": [str(executable), str(worker_source)], "executable": file_ref(executable), "properties": props,
                "dropins": [], "environment": {"MAPLEBENCH_LIFECYCLE_RECEIPT_DIR": str(self.root / "receipts")} if role == "worker" else {},
                "files": [file_ref(worker_source)]}
        sources = [file_ref(Path(module.__file__).resolve()) for module in
                   (lifecycle, lifecycle.full_client_trial, lifecycle.full_client_collect, lifecycle.full_client_score)]
        self.config = {"schema_version": 1, "state_root": str(self.root / "state"), "locks": locks, "services": services,
            "source_files": sources, "commands": {name: file_ref(executable) for name in ("mysql", "systemctl")},
            "mysql": {"database": "synthetic", "defaults_file": None, "character_id": 10, "account_id": 20},
            "queue_database": str(self.root / "queue.sqlite3"), "attempt_root": str(self.root / "attempts"),
            "admin_socket": str(self.root / "admin.sock"), "worker_receipt_directory": str(self.root / "receipts"),
            "native": {"path": str(native), "ports": [7575, 8484], "max_fds": 4096, "max_bytes": 1024 * 1024,
                       "online_marker": "Cosmic is now online after ", "error_markers": ["Error saving chr", "MapleBench persistence journal failed", "ERROR", "Exception"]},
            "min_available_bytes": 8 * 1024**3,
            "limits": {"total_seconds": 120, "command_seconds": 15, "ready_seconds": 60, "idle_seconds": 15,
                       "memory_bytes": 256 * 1024**2, "cpu_seconds": 60, "cpus": 2}}
        self.config_ref = write_json(self.root / "config.json", self.config)
        attempt = self.root / "attempts" / ("a" * 32); attempt.mkdir(mode=0o700)
        journal = write_json(attempt / "journal.json", {"attempt_id": "a" * 32, "status": "completed", "phase_status": "returned",
            "receipts": {"cleanup": {"attempt_id": "a" * 32, "clean": True}}})
        backend = write_json(attempt / "backend-state.json", {"attempt_id": "a" * 32, "clean": True})
        self.snapshot = {"schema_version": 1, "source": "cosmic_persisted_character", "account_logged_in": 0,
                         "character": {"character_id": 10, "account_id": 20, "exp": 9000}, "keymap": [[29, 5, 52], [57, 5, 53]]}
        self.request = {"schema_version": 1, "operation_id": "b" * 32, "config_sha256": self.config_ref["sha256"], "boot_id": BOOT,
            "stopped_invocations": {"cosmic": "d" * 32, "worker": "e" * 32, "world": "f" * 32},
            "web_instance": {"pid": 303, "start_ticks": "303", "invocation_id": "c" * 32}, "browser_run_id": "a" * 32,
            "attempts": [{"id": "a" * 32, "journal": journal, "backend": backend}],
            "offline_snapshot": write_json(self.root / "snapshot.json", self.snapshot)}
        self.request_ref = write_json(self.root / "handoff.json", self.request)
        self.host = FakeHost(self.config, self.snapshot, self.request)
        self.engine = self.fresh_engine()

    def fresh_engine(self):
        engine = lifecycle.NormalLifecycle(self.config, self.config_ref, self.host, owner_uid=os.geteuid())
        self.host.engine = engine
        return engine

    def journal_ref(self):
        return file_ref(self.root / "state" / ("b" * 32) / "journal.json")

    def observation(self, role):
        return write_json(self.root / (role + "-observation.json"), {"schema_version": 1, "operation_id": "b" * 32,
            "boot_id": BOOT, "role": role, "instance": self.host.identities[role]})

    def test_check_reads_real_refs_and_locks_without_intent_or_service_start(self):
        result = self.engine.start(self.request_ref, check_only=True)
        self.assertTrue(result["ready"]); self.assertEqual(self.host.started, [])
        self.assertFalse((self.root / "state" / ("b" * 32)).exists())

    def test_start_has_durable_intents_closes_world_locks_and_verifies_worker_receipt(self):
        result = self.engine.start(self.request_ref)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.host.started, ["cosmic", "worker"])
        saved = json.loads(Path(self.journal_ref()["path"]).read_text())
        self.assertEqual(saved["service_starts"], {"cosmic": 1, "worker": 1})
        self.assertTrue(saved["first_idle"]["sha256"])
        self.assertEqual(saved["cosmic"], self.host.identities["cosmic"])

    def test_lost_cosmic_start_response_requires_explicit_observation_never_restarts(self):
        self.host.crash_after = "cosmic"
        with self.assertRaises(SystemExit): self.engine.start(self.request_ref)
        with self.assertRaisesRegex(lifecycle.LifecycleError, "uncertain_start_requires_observation"):
            self.fresh_engine().reconcile(self.journal_ref())
        self.assertEqual(self.host.started, ["cosmic"])
        self.host.crash_after = None
        result = self.fresh_engine().reconcile(self.journal_ref(), self.observation("cosmic"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.host.started, ["cosmic", "worker"])

    def test_lost_worker_start_response_only_observes_existing_worker(self):
        self.host.crash_after = "worker"
        with self.assertRaises(SystemExit): self.engine.start(self.request_ref)
        self.host.crash_after = None
        engine = self.fresh_engine()
        engine.acquire_world_locks = lambda: self.fail("must not acquire worker-owned world locks")
        result = engine.reconcile(self.journal_ref(), self.observation("worker"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.host.started, ["cosmic", "worker"])

    def test_capacity_refusal_occurs_before_any_journal_or_service_start(self):
        self.host.memory_bytes = 1024
        with self.assertRaisesRegex(lifecycle.LifecycleError, "capacity_insufficient"):
            self.engine.start(self.request_ref)
        self.assertEqual(self.host.started, [])
        self.assertFalse((self.root / "state" / ("b" * 32)).exists())

    def test_tampered_historical_receipt_blocks_start(self):
        Path(self.request["attempts"][0]["backend"]["path"]).write_bytes(b"{}")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "reference_changed"):
            self.engine.start(self.request_ref)
        self.assertEqual(self.host.started, [])

    def test_changed_cosmic_in_worker_receipt_preserves_failure_without_restart(self):
        self.host.worker_receipt_mutation = lambda r: r.update(cosmic_after=dict(r["cosmic_after"], pid=909))
        with self.assertRaisesRegex(lifecycle.LifecycleError, "worker_receipt_mismatch"):
            self.engine.start(self.request_ref)
        self.assertEqual(self.host.started, ["cosmic", "worker"])
        saved = json.loads(Path(self.journal_ref()["path"]).read_text())
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["failure"]["code"], "worker_receipt_mismatch")

    def test_real_locks_are_close_only_and_lifecycle_lock_survives_handoff(self):
        self.engine.begin_deadline()
        with self.engine.serialized():
            self.engine.acquire_world_locks()
            duplicate = os.dup(self.engine.world_fds[0])
            try:
                self.engine.close_world_locks()
                with open(self.config["locks"]["world"]["path"], "r+") as rival:
                    with self.assertRaises(BlockingIOError): fcntl.flock(rival, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with open(self.root / "state" / ".lifecycle.lock", "r+") as rival:
                    with self.assertRaises(BlockingIOError): fcntl.flock(rival, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally: os.close(duplicate)
        with open(self.config["locks"]["world"]["path"], "r+") as rival:
            fcntl.flock(rival, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_config_rejects_unsupported_target_missing_hook_and_unbounded_native_scan(self):
        for mutate in (lambda c: c["services"]["cosmic"].update(unit="another.service"),
                       lambda c: c["services"]["worker"].update(environment={}),
                       lambda c: c["native"].update(max_fds=65536)):
            value = copy.deepcopy(self.config); mutate(value)
            with self.assertRaises(lifecycle.LifecycleError): lifecycle.validate_config(value)


class NativeBoundaryTests(unittest.TestCase):
    def test_rewritten_or_truncated_same_inode_cannot_reuse_old_online_marker(self):
        raw = b"Cosmic is now online after old\n"
        boundary = {"device": 1, "inode": 2, "bytes": len(raw), "sha256": lifecycle.digest(raw)}
        info = SimpleNamespace(st_dev=1, st_ino=2, st_mtime_ns=5000000, st_ctime_ns=5000000)
        for changed in (raw[:-1], raw.replace(b"old", b"NEW")):
            with self.assertRaisesRegex(lifecycle.LifecycleError, "native_boundary_ambiguous"):
                lifecycle.native_offset(info, changed, boundary, 4)
        self.assertEqual(lifecycle.native_offset(info, raw + b"fresh", boundary, 4), len(raw))

    def test_new_inode_requires_birth_time_not_only_rename_ctime(self):
        boundary = {"device": 1, "inode": 2, "bytes": 0, "sha256": lifecycle.digest(b"")}
        info = SimpleNamespace(st_dev=1, st_ino=3, st_mtime_ns=5000000, st_ctime_ns=5000000)
        for born in (None, 3):
            with self.assertRaisesRegex(lifecycle.LifecycleError, "native_fresh_inode_provenance_missing"):
                lifecycle.native_offset(info, b"old marker", boundary, 4, born)
        self.assertEqual(lifecycle.native_offset(info, b"fresh", boundary, 4, 4), 0)

    def test_kernel_read_has_hard_size_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized"; path.write_bytes(b"x" * 33)
            host = lifecycle.Host(); host.deadline = time.monotonic() + 5
            with self.assertRaisesRegex(lifecycle.LifecycleError, "kernel_observation_limit"):
                host.kernel_read(path, 32)

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux proc descriptors")
    def test_native_uses_real_owned_log_and_listener_and_refuses_closed_listener(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.log"
            path.write_bytes(b"previous log\n")
            info = path.stat()
            boundary = {"device": info.st_dev, "inode": info.st_ino, "bytes": info.st_size,
                        "sha256": lifecycle.digest(path.read_bytes())}
            host = lifecycle.Host(); host.deadline = time.monotonic() + 10
            with path.open("ab") as log, socket.socket() as listener:
                listener.bind(("127.0.0.1", 0)); listener.listen(1)
                port = listener.getsockname()[1]
                log.write(b"Cosmic is now online after 1 ms.\n"); log.flush(); os.fsync(log.fileno())
                config = {"path": str(path), "max_fds": 4096, "max_bytes": 65536, "ports": [port],
                          "online_marker": "Cosmic is now online after ", "error_markers": ["ERROR"]}
                receipt = host.native(os.getpid(), config, boundary, 0)
                self.assertIn(port, receipt["ports"])
                self.assertEqual(receipt["offset"], boundary["bytes"])
                self.assertEqual(receipt["log_sha256"], lifecycle.digest(path.read_bytes()))
                with self.assertRaisesRegex(lifecycle.LifecycleError, "native_fd_limit"):
                    host.native(os.getpid(), config | {"max_fds": 1}, boundary, 0)
                listener.close()
                with self.assertRaisesRegex(lifecycle.LifecycleError, "native_ports_missing"):
                    host.native(os.getpid(), config, boundary, 0)
            with self.assertRaisesRegex(lifecycle.LifecycleError, "native_fd_not_owned"):
                host.native(os.getpid(), config, boundary, 0)


class GuardTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux") and
                         (os.geteuid() == 0 or resource.getrlimit(resource.RLIMIT_CPU)[1] == resource.RLIM_INFINITY),
                         "requires Linux and permission to retain an uncapped guard")
    def test_killed_operator_cannot_release_serialization_before_grandchild_ends(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / "serial.lock"; lock.touch(mode=0o600)
            ready = root / "ready.json"; marker = root / "late-mutation"
            child_script = root / "child.py"
            child_script.write_text("import json,os,subprocess,sys,time\nfrom pathlib import Path\n"
                "child=subprocess.Popen([sys.executable,'-c',\"import time;from pathlib import Path;time.sleep(3);Path(\"+repr(sys.argv[2])+\").write_text('unsafe')\"],close_fds=True)\n"
                "Path(sys.argv[1]).write_text(json.dumps({'child':os.getpid(),'grandchild':child.pid,'guard':os.getppid()}))\n"
                "time.sleep(20)\n")
            # Avoid shadowing Python's stdlib operator module during startup.
            script = root / "lifecycle-driver.py"
            script.write_text("import resource,sys,time\nfrom pathlib import Path\n"
                "sys.path.insert(0," + repr(str(Path(lifecycle.__file__).parent)) + ")\n"
                "from full_client_lifecycle import Host\nfrom full_client_trial import existing_lock\n"
                "soft,hard=resource.getrlimit(resource.RLIMIT_CPU);resource.setrlimit(resource.RLIMIT_CPU,(2,hard))\n"
                "with existing_lock(sys.argv[1]) as fd:\n"
                " host=Host();host.deadline=time.monotonic()+15;host.command_seconds=15;host.guard_fds=[fd]\n"
                " host.command([sys.executable,sys.argv[2],sys.argv[3],sys.argv[4]])\n")
            parent = subprocess.Popen([sys.executable, str(script), str(lock), str(child_script), str(ready), str(marker)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            identities = {}
            try:
                end = time.monotonic() + 10
                while not ready.exists() and parent.poll() is None and time.monotonic() < end:
                    time.sleep(.02)
                self.assertTrue(ready.exists(), "guard failed before test command became ready")
                identities = json.loads(ready.read_text())
                def cpu_limit(pid):
                    row = next(line for line in Path(f"/proc/{pid}/limits").read_text().splitlines()
                               if line.lower().startswith("max cpu time"))
                    return row.split()[3:5]
                self.assertEqual(cpu_limit(identities["guard"]), ["unlimited", "unlimited"])
                self.assertEqual(cpu_limit(identities["child"])[0], "2")
                with lock.open("r+") as rival:
                    with self.assertRaises(BlockingIOError): fcntl.flock(rival, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    parent.kill(); parent.wait(timeout=5)
                    end = time.monotonic() + 10
                    while True:
                        try:
                            fcntl.flock(rival, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            break
                        except BlockingIOError:
                            self.assertLess(time.monotonic(), end, "guard retained lock after test children should be reaped")
                            time.sleep(.02)
                    for key in ("child", "grandchild"):
                        with self.assertRaises(ProcessLookupError): os.kill(identities[key], 0)
                    self.assertFalse(marker.exists())
            finally:
                if parent.poll() is None:
                    parent.kill()
                parent.wait(timeout=5)
                for key in ("grandchild", "child", "guard"):
                    if key in identities:
                        try: os.kill(identities[key], signal.SIGTERM if key == "guard" else signal.SIGKILL)
                        except ProcessLookupError: pass


if __name__ == "__main__":
    unittest.main()
