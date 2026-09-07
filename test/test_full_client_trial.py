"""Failure-injected local runner tests; no live server, browser, API, or database."""
import contextlib
import array
import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from full_client_trial import (CommandAdapter, PHASES, TrialError, TrialRunner, adapter_failure_code,
                               main, publish_attempt, validate_spec)


def spec():
    return {"schema_version": 1, "model": "synthetic-model",
            "scenario_fingerprint": "a" * 64, "baseline_sha256": "b" * 64,
            "budgets": {"total_seconds": 120, "operation_seconds": 30,
                        "controller_seconds": 10, "max_actions": 20, "max_api_requests": 1,
                        "max_output_tokens": 100, "max_total_tokens": 300}}


class FakeAdapter:
    def __init__(self, *, fail=None, crash=None, overrides=None):
        self.calls = []
        self.fail, self.crash = fail, crash
        self.overrides = overrides or {}

    def perform(self, operation, context, *, timeout_seconds):
        self.calls.append(operation)
        if "attempt_dir" in context:
            journal = json.loads((Path(context["attempt_dir"]) / "journal.json").read_text())
            assert journal["phase"] == operation
            assert journal["phase_status"] == "pending"
            assert journal["events"][-1]["kind"] == "operation_pending"
            assert journal["events"][-1]["operation"] == operation
            assert 0 < timeout_seconds <= journal["request"]["budgets"]["operation_seconds"]
            assert context["lock_owner_pid"] == os.getpid()
            for path in context["lock_paths"].values():
                with open(path, "r+b") as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        raise AssertionError("runner did not hold a required lock")
            if operation == "run_controller":
                assert journal["api_outcome"] == "uncertain"
                assert journal["charged_usage"] == {"api_requests": 1, "total_tokens": 300}
        if self.crash == operation:
            os._exit(71)
        if self.fail == operation:
            raise RuntimeError("private-password-marker")
        aid = context.get("attempt_id")
        if operation == "status":
            receipt = {"ready": True, "queue_idle": True, "server_stopped": True,
                       "account_offline": True, "controller_idle": True, "ownership_conflict": False}
        elif operation == "run_controller":
            receipt = {"attempt_id": aid, "status": "completed", "requested_model": "synthetic-model",
                       "returned_model": "synthetic-model", "api_requests": 1, "output_tokens": 30,
                       "total_tokens": 80, "actions": 4, "controller_ms": 8000,
                       "recording_complete": True}
        elif operation == "collect_final":
            receipt = {"attempt_id": aid, "evidence": {"run_id": aid,
                       "scenario_fingerprint": "a" * 64, "baseline": {"sha256": "b" * 64}},
                       "artifacts": {"synthetic": True}}
        else:
            receipt = {"attempt_id": aid, "clean": operation == "cleanup"}
        receipt.update(self.overrides.get(operation, {}))
        return receipt


def fake_verifier(evidence, artifact_root, artifacts):
    assert artifacts == {"synthetic": True}
    assert artifact_root.name == evidence["run_id"]
    return {"metrics": {"net_xp": 123}, "publication_eligible": False}


def crash_worker(directory, operation):
    root = Path(directory)
    runner = TrialRunner(root / "attempts", root / "world.lock", root / "queue.lock",
                         FakeAdapter(crash=operation), verify_bundle=fake_verifier)
    runner.run(spec(), "crashed")


def initialization_crash_worker(directory):
    import full_client_trial
    def before_publish(staging, destination):
        assert (staging / "journal.json").is_file()
        assert not destination.exists()
        os._exit(71)
    full_client_trial.publish_attempt = before_publish
    root = Path(directory)
    TrialRunner(root / "attempts", root / "world.lock", root / "queue.lock",
                FakeAdapter(), verify_bundle=fake_verifier).run(spec(), "never-started")


def backend_script(directory, name, code):
    path = Path(directory).resolve() / name
    path.write_text(code)
    path.chmod(0o600)
    return path


def orphan_worker(directory):
    root = Path(directory)
    # Grandchild deliberately closes all inherited lock descriptors and keeps
    # writing. A direct-child death signal alone does not terminate this worker.
    worker = backend_script(root, "worker.py", """import os,pathlib,sys,time
with pathlib.Path(sys.argv[1]).open('ab', buffering=0) as marker:
    while True:
        marker.write(b'x')
        os.fsync(marker.fileno())
        time.sleep(0.01)
""")
    backend = backend_script(root, "backend.py", """import json,os,pathlib,subprocess,sys,time
r=json.load(sys.stdin)
directory=pathlib.Path(r['context']['attempt_dir'])
worker=pathlib.Path(__file__).with_name('worker.py')
child=subprocess.Popen([sys.executable,str(worker),str(directory/'grandchild-marker')],close_fds=True)
(directory/'backend-pid.json').write_text(json.dumps({
    'pid':os.getpid(),'parent':os.getppid(),'child':child.pid,
    'guard':r['context']['guard_pid'],'owner':r['context']['lock_owner_pid']}))
time.sleep(60)
""")
    runner = TrialRunner(root / "attempts", root / "world.lock", root / "queue.lock",
                         CommandAdapter([sys.executable, str(backend)], [str(worker)]),
                         verify_bundle=fake_verifier)
    runner.run(spec(), "orphan-test")


class TrialRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        for name in ("world.lock", "queue.lock"):
            (self.base / name).touch(mode=0o600)

    def runner(self, adapter=None, **kwargs):
        return TrialRunner(self.base / "attempts", self.base / "world.lock", self.base / "queue.lock",
                           adapter or FakeAdapter(), verify_bundle=kwargs.pop("verify_bundle", fake_verifier),
                           **kwargs)

    def journal(self, aid="one"):
        return json.loads((self.base / "attempts" / aid / "journal.json").read_text())

    def test_success_intent_precedes_every_operation_and_proof_precedes_cleanup(self):
        adapter = FakeAdapter()
        result = self.runner(adapter).run(spec(), "one")
        self.assertEqual(adapter.calls, ["status", *PHASES, "status"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["charged_usage"], {"api_requests": 1, "total_tokens": 80})
        self.assertFalse(result["publication_eligible"])
        journal = self.journal()
        kinds = [event["kind"] for event in journal["events"]]
        self.assertLess(kinds.index("evidence_verified"), len(kinds) - 1)
        self.assertEqual(journal["score"]["metrics"], {"net_xp": 123})
        self.assertEqual((self.base / "attempts" / "one" / "journal.json").stat().st_mode & 0o777, 0o600)

    def test_failure_at_each_phase_quarantines_and_never_continues(self):
        for phase in ("status", *PHASES):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory(dir=self.base) as directory:
                base = Path(directory)
                for name in ("world", "queue"):
                    (base / name).touch(mode=0o600)
                adapter = FakeAdapter(fail=phase)
                runner = TrialRunner(base / "attempts", base / "world", base / "queue", adapter,
                                     verify_bundle=fake_verifier)
                with self.assertRaises(RuntimeError):
                    runner.run(spec(), "failed")
                state = json.loads((base / "attempts/failed/journal.json").read_text())
                self.assertEqual(state["status"], "failed")
                self.assertEqual(adapter.calls[-1], phase)
                self.assertNotIn("private-password-marker", json.dumps(state))
                calls = list(adapter.calls)
                with self.assertRaisesRegex(TrialError, "recovery_required"):
                    runner.run(spec(), "new-attempt")
                self.assertEqual(adapter.calls, calls)

    def test_existing_world_or_queue_lock_conflict_has_no_adapter_or_runner_state_effect(self):
        for name in ("world.lock", "queue.lock"):
            with self.subTest(name=name), (self.base / name).open("r+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                adapter = FakeAdapter()
                with self.assertRaisesRegex(TrialError, "lock_conflict"):
                    self.runner(adapter).run(spec(), "one")
                self.assertEqual(adapter.calls, [])
                self.assertFalse((self.base / "attempts").exists())

    def test_missing_existing_lock_is_not_created(self):
        (self.base / "world.lock").unlink()
        with self.assertRaises(FileNotFoundError):
            self.runner().run(spec(), "one")
        self.assertFalse((self.base / "world.lock").exists())

    def test_live_status_conflict_prevents_restore(self):
        for field, value in (("ready", False), ("queue_idle", False), ("server_stopped", False),
                             ("account_offline", False), ("controller_idle", False),
                             ("ownership_conflict", True)):
            with self.subTest(field=field):
                adapter = FakeAdapter(overrides={"status": {field: value}})
                runner = self.runner(adapter)
                with self.assertRaisesRegex(TrialError, "runtime_not_idle"):
                    runner.run(spec(), field)
                self.assertEqual(adapter.calls, ["status"])
                runner.adapter = FakeAdapter()
                runner.recover(field)

    def test_unknown_provider_outcome_keeps_full_reservation_and_recovery_never_replays(self):
        adapter = FakeAdapter(fail="run_controller")
        runner = self.runner(adapter)
        with self.assertRaises(RuntimeError):
            runner.run(spec(), "one")
        state = self.journal()
        self.assertEqual(state["api_outcome"], "uncertain")
        self.assertEqual(state["charged_usage"], {"api_requests": 1, "total_tokens": 300})
        clean = FakeAdapter()
        runner.adapter = clean
        result = runner.recover("one")
        self.assertEqual(clean.calls, ["status", "cleanup", "status"])
        self.assertEqual(result["status"], "recovered")
        self.assertEqual(result["charged_usage"], state["charged_usage"])
        with self.assertRaisesRegex(TrialError, "attempt_exists"):
            runner.run(spec(), "one")
        runner.run(spec(), "two")
        self.assertEqual(clean.calls.count("run_controller"), 1)

    def test_failed_recovery_stays_quarantined(self):
        runner = self.runner(FakeAdapter(fail="restore_baseline"))
        with self.assertRaises(RuntimeError):
            runner.run(spec(), "one")
        runner.adapter = FakeAdapter(fail="cleanup")
        with self.assertRaises(RuntimeError):
            runner.recover("one")
        self.assertEqual(self.journal()["status"], "failed")
        with self.assertRaisesRegex(TrialError, "recovery_required"):
            runner.run(spec(), "two")

    def test_real_process_crash_leaves_durable_pending_reset_or_api_and_no_replay(self):
        for operation in ("restore_baseline", "run_controller"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory(dir=self.base) as directory:
                base = Path(directory)
                for name in ("world.lock", "queue.lock"):
                    (base / name).touch(mode=0o600)
                code = ("import sys; sys.path.insert(0,sys.argv[1]); "
                        "from test_full_client_trial import crash_worker; crash_worker(sys.argv[2],sys.argv[3])")
                child = subprocess.run([sys.executable, "-c", code, str(Path(__file__).parent),
                                        str(base), operation], timeout=10, capture_output=True)
                self.assertEqual(child.returncode, 71, child.stderr.decode())
                state = json.loads((base / "attempts/crashed/journal.json").read_text())
                self.assertEqual(state["phase"], operation)
                self.assertEqual(state["phase_status"], "pending")
                self.assertEqual(state["status"], "running")
                adapter = FakeAdapter()
                runner = TrialRunner(base / "attempts", base / "world.lock", base / "queue.lock", adapter,
                                     verify_bundle=fake_verifier)
                with self.assertRaisesRegex(TrialError, "recovery_required"):
                    runner.run(spec(), "new")
                self.assertEqual(adapter.calls, [])
                runner.recover("crashed")
                self.assertEqual(adapter.calls, ["status", "cleanup", "status"])

    def test_crash_before_initial_publish_leaves_only_safe_hidden_staging(self):
        code = ("import sys; sys.path.insert(0,sys.argv[1]); from test_full_client_trial import "
                "initialization_crash_worker; initialization_crash_worker(sys.argv[2])")
        result = subprocess.run([sys.executable, "-c", code, str(Path(__file__).parent), str(self.base)],
                                timeout=10, capture_output=True)
        self.assertEqual(result.returncode, 71, result.stderr.decode())
        self.assertFalse((self.base / "attempts/never-started").exists())
        stages = list((self.base / "attempts").glob(".staging-*"))
        self.assertEqual(len(stages), 1)
        initial = json.loads((stages[0] / "journal.json").read_text())
        self.assertEqual([event["kind"] for event in initial["events"]], ["attempt_created"])
        self.assertEqual(initial["receipts"], {})
        adapter = FakeAdapter()
        # No visible attempt ID or backend intent existed, so no uncertain model
        # request is being retried when this unpublished ID is used normally.
        self.runner(adapter).run(spec(), "never-started")
        self.assertEqual(adapter.calls.count("run_controller"), 1)

    def test_atomic_publish_never_replaces_even_an_existing_empty_directory(self):
        staging, destination = self.base / "staging", self.base / "existing"
        staging.mkdir(mode=0o700)
        destination.mkdir(mode=0o700)
        original_inode = destination.stat().st_ino
        with self.assertRaisesRegex(TrialError, "attempt_exists"):
            publish_attempt(staging, destination)
        self.assertEqual(destination.stat().st_ino, original_inode)
        self.assertTrue(staging.is_dir())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux parent-death protection")
    def test_killed_runner_reaps_close_fds_grandchild_before_new_lock_owner_can_overlap(self):
        code = ("import sys; sys.path.insert(0,sys.argv[1]); "
                "from test_full_client_trial import orphan_worker; orphan_worker(sys.argv[2])")
        parent = subprocess.Popen([sys.executable, "-c", code, str(Path(__file__).parent), str(self.base)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: parent.kill() if parent.poll() is None else None)
        marker = self.base / "attempts/orphan-test/backend-pid.json"
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(marker.exists(), "backend did not become ready")
        # File creation and JSON write are separate operations in this fixture.
        while True:
            try:
                observed = json.loads(marker.read_text())
                break
            except ValueError:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
        self.assertEqual(observed["owner"], parent.pid)
        self.assertEqual(observed["parent"], observed["guard"])
        self.assertNotEqual(observed["guard"], parent.pid)
        writes = marker.with_name("grandchild-marker")
        while (not writes.exists() or writes.stat().st_size == 0) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(writes.exists() and writes.stat().st_size > 0, "grandchild did not begin its side effect")
        with (self.base / "world.lock").open("r+b") as lock:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            parent.kill()
            parent.wait(timeout=5)
            deadline = time.monotonic() + 5
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    self.assertLess(time.monotonic(), deadline, "orphan retained world lock indefinitely")
                    time.sleep(0.01)
            for pid in (observed["pid"], observed["child"]):
                process = Path(f"/proc/{pid}/stat")
                if process.exists():
                    try:
                        self.assertIn(process.read_text().split(") ", 1)[1][0], ("Z", "X"),
                                      "new lock owner overlaps an old live operation")
                    except FileNotFoundError:
                        pass
            size = writes.stat().st_size
            time.sleep(0.05)
            self.assertEqual(writes.stat().st_size, size, "old worker kept mutating after lock release")
        # The released kernel lock cannot bypass the durable quarantine.
        adapter = FakeAdapter()
        with self.assertRaisesRegex(TrialError, "recovery_required"):
            self.runner(adapter).run(spec(), "next")
        self.assertEqual(adapter.calls, [])

    def test_duplicate_attempt_and_corrupt_or_missing_journal_are_never_overwritten(self):
        runner = self.runner()
        runner.run(spec(), "one")
        original = (self.base / "attempts/one/journal.json").read_bytes()
        with self.assertRaisesRegex(TrialError, "attempt_exists"):
            runner.run(spec(), "one")
        self.assertEqual((self.base / "attempts/one/journal.json").read_bytes(), original)
        (self.base / "attempts/orphan").mkdir(mode=0o700)
        with self.assertRaises(FileNotFoundError):
            runner.run(spec(), "two")
        self.assertFalse((self.base / "attempts/two").exists())

    def test_bad_controller_attribution_usage_recording_or_attempt_fail_closed(self):
        cases = {"returned_model": "other-model", "requested_model": "other-model",
                 "api_requests": 2, "actions": 21, "output_tokens": 101, "total_tokens": 301,
                 "controller_ms": 10001, "status": "interrupted", "recording_complete": False,
                 "attempt_id": "wrong", "actions_bool": True}
        for key, value in cases.items():
            with self.subTest(field=key):
                field = "actions" if key == "actions_bool" else key
                runner = self.runner(FakeAdapter(overrides={"run_controller": {field: value}}))
                with self.assertRaises(TrialError):
                    runner.run(spec(), key)
                self.assertEqual(self.journal(key)["api_outcome"], "uncertain")
                runner.adapter = FakeAdapter()
                runner.recover(key)

    def test_evidence_verification_failure_cannot_complete(self):
        def reject(*_):
            raise ValueError("private-evidence-marker")
        runner = self.runner(verify_bundle=reject)
        with self.assertRaises(ValueError):
            runner.run(spec(), "one")
        self.assertEqual(self.journal()["status"], "failed")
        self.assertNotIn("cleanup", runner.adapter.calls)
        self.assertNotIn("private-evidence-marker", json.dumps(self.journal()))

    def test_monotonic_overrun_quarantines_without_next_operation(self):
        ticks = iter((0, 0, 0, 31, 31))
        runner = self.runner(monotonic=lambda: next(ticks))
        with self.assertRaisesRegex(TrialError, "operation_timeout"):
            runner.run(spec(), "one")
        self.assertEqual(runner.adapter.calls, ["status"])

    def test_preflight_is_read_only_and_reports_unready_without_locks(self):
        adapter = FakeAdapter(overrides={"status": {"ready": False, "server_stopped": False}})
        runner = self.runner(adapter)
        (self.base / "world.lock").unlink()
        result = runner.preflight()
        self.assertFalse(result["ready"])
        self.assertFalse(result["server_stopped"])
        self.assertEqual(adapter.calls, ["status"])
        self.assertFalse((self.base / "attempts").exists())

    def test_preflight_rejects_noninteger_or_unbounded_deadlines_before_adapter(self):
        adapter = FakeAdapter()
        runner = self.runner(adapter)
        for timeout in (0, -1, 121, True, 1.5, float("nan"), float("inf"), "30", None):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(TrialError, "invalid_preflight_timeout"):
                runner.preflight(timeout)
        self.assertEqual(adapter.calls, [])
        self.assertFalse((self.base / "attempts").exists())

    def test_preflight_default_and_explicit_bounds_reach_adapter(self):
        runner = self.runner()
        with patch.object(runner.adapter, "perform", wraps=runner.adapter.perform) as perform:
            runner.preflight()
            self.assertEqual(perform.call_args.kwargs["timeout_seconds"], 30)
            for timeout in (1, 120):
                runner.preflight(timeout)
                self.assertEqual(perform.call_args.kwargs["timeout_seconds"], timeout)

    def test_guard_passes_only_mapped_lock_descriptors_to_trusted_backend(self):
        backend = backend_script(self.base, "descriptor-check.py", """import json,os,stat,sys
request=json.load(sys.stdin)
context=request['context']
valid=True
for name,descriptor in context['lock_fds'].items():
    actual=os.fstat(descriptor)
    expected=os.stat(context['lock_paths'][name])
    valid=valid and (actual.st_dev,actual.st_ino)==(expected.st_dev,expected.st_ino)
extra_pipe=False
if os.path.isdir('/proc/self/fd'):
    for name in os.listdir('/proc/self/fd'):
        if int(name)>2:
            try:
                extra_pipe=extra_pipe or stat.S_ISFIFO(os.fstat(int(name)).st_mode)
            except OSError:
                pass
print(json.dumps({'valid':valid,'names':sorted(context['lock_fds']),
                  'parent_matches_guard':os.getppid()==context['guard_pid'],'extra_pipe':extra_pipe}))
""")
        adapter = CommandAdapter([sys.executable, str(backend)])
        runner = self.runner(adapter)
        with runner._locks():
            result = adapter.perform("status", runner._context(), timeout_seconds=5)
        self.assertEqual(result, {"valid": True, "names": ["queue", "world"],
                                  "parent_matches_guard": True, "extra_pipe": False})

    def test_scm_rights_bridge_copy_keeps_both_locks_after_runner_normal_close(self):
        runner = self.runner()
        bridge_fds = []
        sender, receiver = socket.socketpair()
        try:
            with runner._locks():
                sender.sendmsg([b"L"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                        array.array("i", runner.lock_fds))])
                _, ancillary, flags, _ = receiver.recvmsg(1, socket.CMSG_SPACE(2 * array.array("i").itemsize))
                self.assertFalse(flags & socket.MSG_CTRUNC)
                for level, kind, raw in ancillary:
                    if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                        descriptors = array.array("i")
                        descriptors.frombytes(raw[:len(raw) - len(raw) % descriptors.itemsize])
                        bridge_fds.extend(descriptors)
                self.assertEqual(len(bridge_fds), 2)
            # Runner's normal cleanup has closed its own copies. A distinct
            # contender must still be excluded by the bridge's kernel lease.
            for name in ("world.lock", "queue.lock"):
                with (self.base / name).open("r+b") as contender:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            while bridge_fds:
                os.close(bridge_fds.pop())
            for name in ("world.lock", "queue.lock"):
                with (self.base / name).open("r+b") as contender:
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            sender.close()
            receiver.close()
            for descriptor in bridge_fds:
                os.close(descriptor)

    def test_cli_unready_preflight_has_nonzero_exit_and_safe_json(self):
        receipt = FakeAdapter().perform("status", {}, timeout_seconds=5)
        receipt["ready"] = False
        config = self.base / "adapter.json"
        backend = backend_script(self.base, "status.py", "print(" + repr(json.dumps(receipt)) + ")")
        config.write_text(json.dumps({"argv": [sys.executable, str(backend)], "dependencies": []}))
        config.chmod(0o600)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["--adapter-config", str(config), "--state-root", str(self.base / "attempts"),
                           "--world-lock", str(self.base / "world.lock"),
                           "--queue-lock", str(self.base / "queue.lock"), "preflight"])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(output.getvalue())["ready"], False)
        self.assertFalse((self.base / "attempts").exists())

    def test_cli_preflight_timeout_is_forwarded_and_invalid_bounds_fail_before_call(self):
        receipt = FakeAdapter().perform("status", {}, timeout_seconds=5)
        config = self.base / "adapter.json"
        backend = backend_script(self.base, "status.py", "# synthetic backend; mocked, never executed\n")
        config.write_text(json.dumps({"argv": [sys.executable, str(backend)], "dependencies": []}))
        config.chmod(0o600)
        arguments = ["--adapter-config", str(config), "--state-root", str(self.base / "attempts"),
                     "--world-lock", str(self.base / "world.lock"),
                     "--queue-lock", str(self.base / "queue.lock"), "preflight"]
        for options, timeout in (([], 30), (["--timeout-seconds", "120"], 120)):
            with self.subTest(options=options), patch.object(CommandAdapter, "perform", return_value=receipt) as perform, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(arguments + options), 0)
                self.assertEqual(perform.call_args.kwargs["timeout_seconds"], timeout)
        for timeout in ("0", "121", "-1"):
            output = io.StringIO()
            with self.subTest(timeout=timeout), patch.object(CommandAdapter, "perform") as perform, \
                    contextlib.redirect_stdout(output):
                self.assertEqual(main(arguments + ["--timeout-seconds", timeout]), 1)
                self.assertEqual(json.loads(output.getvalue())["code"], "invalid_preflight_timeout")
                perform.assert_not_called()
        self.assertFalse((self.base / "attempts").exists())

    def test_cli_and_private_journal_preserve_known_backend_failure_without_raw_output(self):
        backend = backend_script(self.base, "runtime-error.py", """import json,sys
request=json.load(sys.stdin)
operation=request['operation']
if operation=='status':
    print(json.dumps({'ready':True,'queue_idle':True,'server_stopped':True,
        'account_offline':True,'controller_idle':True,'ownership_conflict':False}))
elif operation=='start_server':
    sys.stderr.write('/private/runtime/private-credential-marker')
    print(json.dumps({'error':'server_jar_command_mismatch'}))
    sys.exit(1)
else:
    print(json.dumps({'attempt_id':request['context']['attempt_id']}))
""")
        config, request = self.base / "adapter.json", self.base / "request.json"
        config.write_text(json.dumps({"argv": [sys.executable, str(backend)], "dependencies": []}))
        request.write_text(json.dumps(spec()))
        config.chmod(0o600)
        request.chmod(0o600)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["--adapter-config", str(config), "--state-root", str(self.base / "attempts"),
                           "--world-lock", str(self.base / "world.lock"),
                           "--queue-lock", str(self.base / "queue.lock"), "run",
                           "--request", str(request), "--attempt-id", "one"])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue())["code"], "server_jar_command_mismatch")
        journal = self.journal()
        self.assertEqual(journal["failure_code"], "server_jar_command_mismatch")
        self.assertEqual(journal["phase"], "start_server")
        self.assertEqual(journal["status"], "failed")
        self.assertEqual(journal["events"][-1]["code"], "server_jar_command_mismatch")
        for text in (output.getvalue(), json.dumps(journal)):
            self.assertNotIn("private-credential-marker", text)
            self.assertNotIn("/private/runtime/", text)

    def test_strict_request_prevents_unbounded_or_repeated_calls(self):
        for field, value in (("max_api_requests", 2), ("max_actions", True),
                             ("operation_seconds", 301), ("total_seconds", 1801),
                             ("max_total_tokens", -1)):
            request = spec()
            request["budgets"][field] = value
            with self.subTest(field=field), self.assertRaises(TrialError):
                validate_spec(request)
        for aid in ("../escape", ".hidden", "slash/path"):
            with self.subTest(aid=aid), self.assertRaises(TrialError):
                self.runner().run(spec(), aid)


class CommandAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.serial = 0

    def adapter(self, code):
        self.serial += 1
        script = backend_script(self.temp.name, f"adapter-{self.serial}.py", code)
        return CommandAdapter([sys.executable, str(script)])

    def test_setuid_or_setgid_adapter_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory).resolve() / "adapter"
            executable.write_text("#!/bin/sh\nexit 0\n")
            for mode in (0o4755, 0o2755):
                executable.chmod(mode)
                with self.subTest(mode=mode), self.assertRaisesRegex(TrialError, "untrusted_adapter"):
                    CommandAdapter([str(executable)])

    def test_fixed_script_bytes_are_pinned_before_any_command(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory).resolve() / "adapter.py"
            script.write_text("print('{}')")
            script.chmod(0o600)
            adapter = CommandAdapter([sys.executable, str(script)])
            script.write_text("print('{\"changed\":true}')")
            with self.assertRaisesRegex(TrialError, "adapter_source_changed"):
                adapter.perform("status", {}, timeout_seconds=5)

    def test_direct_json_protocol_and_safe_errors(self):
        code = "import json,sys; r=json.load(sys.stdin); print(json.dumps({'seen':r['operation']}))"
        adapter = self.adapter(code)
        self.assertEqual(adapter.perform("status", {}, timeout_seconds=5), {"seen": "status"})
        bad = self.adapter("import sys; sys.stderr.write('private-marker');sys.exit(1)")
        with self.assertRaisesRegex(TrialError, "adapter_failed") as caught:
            bad.perform("status", {}, timeout_seconds=5)
        self.assertNotIn("private-marker", str(caught.exception))

    def test_known_error_protocol_is_exact_bounded_and_not_a_lexical_allowlist(self):
        for code in ('inventory_timeout','runtime_manifest_drift','docker_executable_changed',
                     'docker_binding_required','recorder_not_ready','client_busy_or_not_ready',
                     'cleanup_dropin_removal_unowned','cleanup_configuration_still_loaded',
                     'cleanup_checkpoint_invalid'):
            self.assertEqual(adapter_failure_code(json.dumps({'error':code}).encode()),code)
        known = b'{"error":"server_jar_command_mismatch"}'
        self.assertEqual(adapter_failure_code(known), "server_jar_command_mismatch")
        self.assertEqual(adapter_failure_code(known + b" " * (512 - len(known))),
                         "server_jar_command_mismatch")
        bad_outputs = (b"", b"not JSON /private/private-marker", b"\xff",
                       b'{"error":"private_marker_looks_like_a_code"}',
                       b'{"error":"/private/password-marker"}',
                       b'{"error":"server_jar_command_mismatch","detail":"private-marker"}',
                       b'{"error":"private-marker","error":"server_jar_command_mismatch"}',
                       b'{"error":"server_jar_command_mismatch"}\n{"error":"private-marker"}',
                       b'{"error":["server_jar_command_mismatch"]}', b'{"error":NaN}',
                       b'"server_jar_command_mismatch"',
                       known + b" " * (513 - len(known)),
                       b'{"error":"' + b"private-marker" * 100 + b'"}')
        for raw in bad_outputs:
            with self.subTest(length=len(raw)):
                self.assertEqual(adapter_failure_code(raw), "adapter_failed")

    def test_failed_command_with_oversized_error_envelope_keeps_generic_failure(self):
        raw = '{"error":"server_jar_command_mismatch"}' + " " * 512
        adapter = self.adapter("import sys; print(" + repr(raw) + ");sys.exit(1)")
        with self.assertRaisesRegex(TrialError, "^adapter_failed$"):
            adapter.perform("status", {}, timeout_seconds=5)

    def test_timeout_terminates_process_group(self):
        adapter = self.adapter("import time; time.sleep(60)")
        with self.assertRaisesRegex(TrialError, "operation_timeout"):
            adapter.perform("status", {}, timeout_seconds=0.05)

    def test_invalid_or_nonfinite_json_response_is_rejected(self):
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '[]'):
            with self.subTest(raw=raw):
                adapter = self.adapter("print(" + repr(raw) + ")")
                with self.assertRaises(TrialError):
                    adapter.perform("status", {}, timeout_seconds=5)

    def test_inline_relative_or_embedded_config_invocations_fail_closed(self):
        for args in (["-c", "print('{}')"], ["-m", "backend"], ["backend.py"],
                     ["--config=/private/runtime/config.json"]):
            with self.subTest(args=args), self.assertRaises(TrialError):
                CommandAdapter([sys.executable, *args])

    def test_mutating_command_without_held_lock_descriptors_is_rejected(self):
        adapter = self.adapter("raise RuntimeError('must not execute')")
        with self.assertRaisesRegex(TrialError, "operation_locks_required"):
            adapter.perform("restore_baseline", {}, timeout_seconds=5)

    def test_imported_dependency_bytes_are_pinned(self):
        script = backend_script(self.temp.name, "entry.py", "import helper; print('{}')")
        helper = backend_script(self.temp.name, "helper.py", "VERSION=1")
        adapter = CommandAdapter([sys.executable, str(script)], [str(helper)])
        helper.write_text("VERSION=2")
        with self.assertRaisesRegex(TrialError, "adapter_source_changed"):
            adapter.perform("status", {}, timeout_seconds=5)


if __name__ == "__main__":
    unittest.main()
