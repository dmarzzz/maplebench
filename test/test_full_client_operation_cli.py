"""Root/Linux CLI admission against actual parsers, flocks and child processes.

Run only in a root-owned isolated source copy under the serialized test cgroup.
Every runtime path is a private temporary fixture. The only executable backend
records initial status entry and returns unready; it cannot call services, SQL,
Docker, browsers or a provider. No test substitutes a successful API outcome.
"""
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import full_client_experiment as experiment
import full_client_lifecycle as lifecycle
import full_client_operation_admission as admission
import full_client_operation_gate as gate
import full_client_operation_join as join
import full_client_trial as trial
import test_full_client_lifecycle as lifecycle_fixture

ATTEMPT, OPERATION, COMPETITOR = "2" * 32, "4" * 32, "9" * 32
ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"}


def ref(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write_json(path, value):
    path.write_bytes(gate.encoded(value))
    path.chmod(0o600)
    return ref(path)


BACKEND = r'''
import json, os, stat, sys
from pathlib import Path
assert sys.argv[1] == '--config' and len(sys.argv) == 3
config = json.loads(Path(sys.argv[2]).read_bytes())
raw = sys.stdin.buffer.read(65537)
assert len(raw) <= 65536
request = json.loads(raw)
assert request['operation'] == 'status', 'only initial status is implemented'
context = request['context']
assert set(context['lock_fds']) == {'world', 'queue'}
def inventory(pid):
    values = []
    with os.scandir('/proc/' + str(pid) + '/fd') as entries:
        for index, entry in enumerate(entries):
            assert index < 256
            info = Path(entry.path).stat()
            values.append((int(entry.name), info.st_dev, info.st_ino, stat.S_ISREG(info.st_mode)))
    return values
def count(rows, path):
    info = Path(path).stat()
    return sum((dev, ino) == (info.st_dev, info.st_ino) for _, dev, ino, _ in rows)
own = inventory(os.getpid())
guard = inventory(context['guard_pid'])
runner = inventory(context['guard_parent_pid'])
locks = context['lock_fds']
for name, fd in locks.items():
    info, pinned = os.fstat(fd), Path(context['lock_paths'][name]).stat()
    assert (info.st_dev, info.st_ino) == (pinned.st_dev, pinned.st_ino)
record = {'operation': request['operation'], 'attempt_id': context['attempt_id'],
    'new_api_requests': 0, 'received_lock_names': sorted(locks), 'received_lock_fds': locks,
    'backend_gate_fds': count(own, config['gate_path']),
    'guard_gate_fds': count(guard, config['gate_path']),
    'trial_gate_fds': count(runner, config['gate_path']),
    'backend_regular_extra_fds': sorted(fd for fd, _, _, regular in own if fd >= 3 and regular),
    'backend_world_fds': count(own, context['lock_paths']['world']),
    'backend_queue_fds': count(own, context['lock_paths']['queue'])}
target = Path(config['test_marker'])
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, 'wb') as stream:
    stream.write(json.dumps(record, sort_keys=True).encode() + b'\n')
    stream.flush(); os.fsync(stream.fileno())
status = {key: key != 'ownership_conflict' for key in config['status_fields']}
status['ready'] = False
print(json.dumps(status), flush=True)
'''


PARENT = r'''
from contextlib import contextmanager
import copy, json, os, subprocess, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_bytes())
sys.path.insert(0, data['scripts'])
import full_client_experiment as experiment
import full_client_operation_admission as admission
import full_client_operation_gate as gate
def save(path, value):
    path.write_bytes(gate.encoded(value)); path.chmod(0o600)
plan = experiment.validate_plan(gate.read_ref(data['plan'], 0, gate.Budget()))
subject = {'type': 'experiment', 'plan': data['plan'], 'experiment_directory': data['directory']}
sources = (experiment.__file__, experiment.trial.__file__, experiment.scoring.__file__,
           experiment.docker.__file__, experiment.readiness.__file__, __file__)
children = []
try:
    with admission.admitted(data['authority'], subject, 'finite_group', plan['runner']['state_root'],
                            required_sources=sources) as operation:
        launch = admission.current_launch(operation.authority['source_files'], executable_ref=plan['runner']['python'])
        original = admission.trial_dispatch(operation, data['plan'], launch)
        @contextmanager
        def hook(plan, entry, request_path):
            with original(plan, entry, request_path) as dispatch:
                mode = data['mode']
                if mode == 'envelope':
                    dispatch = {'envelope': dict(dispatch['envelope'], sha256='0' * 64),
                                'pass_fds': dispatch['pass_fds']}
                elif mode == 'claim':
                    value = gate.read_ref(operation.claim, 0, gate.Budget())
                    value['created_at_ms'] += 1
                    save(Path(operation.claim['path']), value)
                elif mode == 'plan':
                    value = copy.deepcopy(plan); value['experiment_id'] = 'changed-current-plan'
                    save(Path(data['plan']['path']), value)
                elif mode == 'request':
                    value = copy.deepcopy(entry['spec']); value['model'] = 'gpt-5.6-sol'
                    save(request_path, value)
                elif mode == 'submission':
                    path = Path(data['directory']) / 'coordinator.json'
                    value = json.loads(path.read_bytes()); value['status'] = 'stopped'
                    save(path, value)
                yield dispatch
        def launcher(plan, entry, request_path, timeout_seconds, *, operation_join):
            fixture = experiment.fixture_for(plan, entry)
            runner = plan['runner']
            if data['mode'] == 'request_path':
                alternate = Path(data['directory']).parent / 'copied-request.json'
                alternate.write_bytes(request_path.read_bytes()); alternate.chmod(0o600)
                request_path = alternate
            fd, = operation_join['pass_fds']
            argv = [runner['python']['path'], runner['trial_script']['path'], '--adapter-config',
                fixture['adapter_config']['path'], '--state-root', runner['state_root'],
                '--world-lock', runner['world_lock'], '--queue-lock', runner['queue_lock'],
                '--operation-envelope', operation_join['envelope']['path'], '--operation-envelope-sha256',
                operation_join['envelope']['sha256'], '--operation-fd', str(fd), 'run',
                '--request', str(request_path), '--attempt-id', entry['attempt_id']]
            result = subprocess.run(argv, pass_fds=(fd,), close_fds=True, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=min(15, timeout_seconds), cwd='/',
                env={'PATH':'/usr/bin:/bin', 'LC_ALL':'C', 'PYTHONDONTWRITEBYTECODE':'1'})
            children.append({'returncode': result.returncode, 'result': json.loads(result.stdout)})
            return result.returncode
        coordinator = experiment.Experiment(plan, data['directory'], entry_admission=hook, launcher=launcher)
        coordinator.run()
except (experiment.ExperimentError, gate.GateError) as error:
    print(json.dumps({'code': str(error), 'children': children}), flush=True)
else:
    raise AssertionError('unready fixture unexpectedly completed')
'''


@unittest.skipUnless(sys.platform == "linux" and os.geteuid() == 0,
                     "requires the dedicated root-owned Linux source fixture")
class OperationCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.root.chmod(0o700)
        self.attempts = self.root / "attempts"
        self.attempts.mkdir(mode=0o700)
        self.pin = gate.initialize_registry(self.attempts)
        self.python = Path(sys.executable).resolve()
        self.marker = self.root / "backend-entered.json"
        self.backend = self.root / "status-backend.py"
        self.backend.write_text(BACKEND); self.backend.chmod(0o600)
        self.driver = self.root / "parent.py"
        self.driver.write_text(PARENT); self.driver.chmod(0o600)
        self.world, self.queue = self.root / "world.lock", self.root / "queue.lock"
        for path in (self.world, self.queue):
            path.touch(mode=0o600)
        self.budgets = {"total_seconds": 120, "operation_seconds": 10, "controller_seconds": 24,
                        "max_actions": 80, "max_api_requests": 1, "max_output_tokens": 3000,
                        "max_total_tokens": 30000}
        runner = {"python": ref(self.python), "trial_script": ref(Path(trial.__file__).resolve()),
                  "dependencies": [ref(Path(module.__file__).resolve()) for module in
                                   (experiment, experiment.scoring, experiment.docker, experiment.readiness)],
                  "state_root": str(self.attempts), "world_lock": str(self.world), "queue_lock": str(self.queue)}
        scenario = write_json(self.root / "scenario.json", {"id": "synthetic-cli-status-only",
            "trial_budgets": self.budgets, "readiness_policy": {"schema_version": 1, "expected_map_id": 240040511,
                "min_monsters": 1, "min_samples": 3, "min_span_ms": 1000, "timeout_ms": 10000}})
        baseline_path = self.root / "baseline.sql"
        baseline_path.write_bytes(b"synthetic fixture bytes; never executed as SQL\n"); baseline_path.chmod(0o600)
        baseline = ref(baseline_path)
        snapshot = write_json(self.root / "baseline-snapshot.json", {"character": {"map_id": 240040511}})
        runtime = write_json(self.root / "runtime.json", {"schema_version": 2, "docker_image_id": "sha256:" + "a" * 64,
            "docker_binding": {"schema_version": 1, "executable": {"path": "/usr/bin/docker", "sha256": "b" * 64},
                               "launcher": None, "socket_path": "/var/run/docker.sock"}})
        backend_config = write_json(self.root / "backend-config.json", {"scenario": scenario, "baseline": baseline,
            "baseline_snapshot": snapshot, "runtime_manifest": runtime, "orchestrator": runner["trial_script"],
            "attempt_root": str(self.attempts), "world_lock": str(self.world), "queue_lock": str(self.queue),
            "test_marker": str(self.marker), "gate_path": self.pin["path"], "status_fields": list(trial.STATUS_FIELDS)})
        self.adapter = write_json(self.root / "adapter.json", {"argv": [str(self.python), str(self.backend),
            "--config", backend_config["path"]], "dependencies": []})
        config = {"schema_version": 1, "experiment_id": "synthetic-cli-group", "models": ["gpt-6-astra"],
                  "repetitions": 1, "fixtures": [{"id": "synthetic", "scenario": scenario, "baseline": baseline,
                    "runtime_manifest": runtime, "adapter_config": self.adapter, "budgets": self.budgets}],
                  "runner": runner, "aggregate_limits": {"api_requests": 1, "total_tokens": 30000, "wall_seconds": 125}}
        self.plan = experiment.build_plan(config, id_factory=lambda: ATTEMPT)
        self.plan_ref = write_json(self.root / "plan.json", self.plan)
        self.request = write_json(self.root / "request.json", self.plan["entries"][0]["spec"])
        self.directory = self.root / "experiment"
        self.modules = (gate, join, admission, trial, experiment, experiment.scoring,
                        experiment.docker, experiment.readiness, lifecycle)
        self.sources = [ref(Path(module.__file__).resolve()) for module in self.modules]
        self.sources.append(ref(self.driver))
        for source in self.sources:
            info = Path(source["path"]).stat()
            self.assertEqual(info.st_uid, 0, "run these tests from the isolated root-owned source copy")
            self.assertFalse(info.st_mode & 0o022, "test source must be protected before freezing authority")

    def authority(self, *, kind="standalone_trial", operation_id=ATTEMPT, subject=None, name="authority.json"):
        if subject is None:
            subject = {"type": "trial", "attempt_id": ATTEMPT, "adapter_config": self.adapter,
                       "request": self.request, "state_root": str(self.attempts),
                       "world_lock": str(self.world), "queue_lock": str(self.queue)}
        return write_json(self.root / name, {"schema_version": 1, "operation_id": operation_id, "kind": kind,
            "gate": self.pin, "subject": subject, "source_files": self.sources})

    def group_authority(self):
        return self.authority(kind="finite_group", operation_id=OPERATION,
            subject={"type": "experiment", "plan": self.plan_ref, "experiment_directory": str(self.directory)},
            name="group-authority.json")

    def run_cli(self, script, args, *, timeout=30):
        result = subprocess.run([str(self.python), str(Path(script).resolve()), *map(str, args)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
            timeout=timeout, cwd="/", env=ENV)
        self.assertLessEqual(len(result.stdout), 65536)
        self.assertLessEqual(len(result.stderr), 65536)
        return result.returncode, json.loads(result.stdout)

    def trial_args(self, authority=None, *, command="run", request=None, claim=None):
        args = ["--adapter-config", self.adapter["path"], "--state-root", self.attempts,
                "--world-lock", self.world, "--queue-lock", self.queue]
        if authority:
            args += ["--operation-authority", authority["path"], "--operation-authority-sha256", authority["sha256"]]
        if claim:
            args += ["--operation-claim", claim["path"], "--operation-claim-sha256", claim["sha256"]]
        args += [command, "--attempt-id", ATTEMPT]
        if command == "run":
            args += ["--request", (request or self.request)["path"]]
        return args

    @contextmanager
    def world_busy(self, path=None):
        fd = os.open(path or self.world, os.O_RDWR | os.O_NOFOLLOW)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def assert_no_trial_entry(self):
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.attempts / ATTEMPT).exists())
        self.assertFalse((self.attempts / ".runner.lock").exists())
        self.assertFalse(list(self.root.glob(".operation-dispatch/*/*.entered.json")))

    def test_trial_missing_authority_refuses_before_world_lock_or_backend(self):
        with self.world_busy():
            code, result = self.run_cli(trial.__file__, self.trial_args())
        self.assertEqual((code, result["code"]), (1, "operation_authority_required"))
        self.assert_no_trial_entry()
        self.assertFalse((self.attempts / ".operations" / ATTEMPT).exists())

    def test_standalone_admission_reaches_only_unready_status_and_preserves_private_failure(self):
        authority = self.authority()
        code, result = self.run_cli(trial.__file__, self.trial_args(authority))
        self.assertEqual((code, result["code"]), (1, "runtime_not_idle"))
        self.assert_unready_artifacts()
        self.assertFalse((self.attempts / ".operations" / ATTEMPT / "terminal.json").exists())

    def assert_unready_artifacts(self):
        marker = json.loads(self.marker.read_bytes())
        self.assertEqual(marker["operation"], "status")
        self.assertEqual(marker["new_api_requests"], 0)
        self.assertEqual(marker["received_lock_names"], ["queue", "world"])
        self.assertEqual(marker["backend_regular_extra_fds"], sorted(marker["received_lock_fds"].values()))
        self.assertEqual((marker["backend_world_fds"], marker["backend_queue_fds"]), (1, 1))
        self.assertEqual((marker["trial_gate_fds"], marker["guard_gate_fds"], marker["backend_gate_fds"]), (1, 0, 0))
        path = self.attempts / ATTEMPT / "journal.json"
        journal = json.loads(path.read_bytes())
        self.assertEqual(journal["status"], "failed")
        self.assertEqual(journal["failure_code"], "runtime_not_idle")
        self.assertEqual(journal["api_outcome"], "not_started")
        self.assertEqual(journal["charged_usage"], {"api_requests": 0, "total_tokens": 0})
        self.assertEqual(list(journal["receipts"]), ["status"])
        self.assertFalse(journal["publication_eligible"])
        self.assertNotIn("run_controller", [e.get("operation") for e in journal["events"]])
        for private in (path, self.marker):
            self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)
            self.assertEqual(private.stat().st_uid, 0)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_wrong_source_hash_refuses_before_world_lock(self):
        authority = self.authority()
        value = json.loads(Path(authority["path"]).read_bytes())
        value["source_files"][0]["sha256"] = "0" * 64
        authority = write_json(Path(authority["path"]), value)
        with self.world_busy():
            code, result = self.run_cli(trial.__file__, self.trial_args(authority))
        self.assertEqual((code, result["code"]), (1, "operation_source_changed"))
        self.assert_no_trial_entry()

    def test_request_subject_mismatch_refuses_before_world_lock(self):
        authority = self.authority()
        spec = copy.deepcopy(self.plan["entries"][0]["spec"]); spec["model"] = "gpt-5.6-sol"
        changed = write_json(self.root / "different-request.json", spec)
        with self.world_busy():
            code, result = self.run_cli(trial.__file__, self.trial_args(authority, request=changed))
        self.assertEqual((code, result["code"]), (1, "operation_subject_mismatch"))
        self.assert_no_trial_entry()

    def test_wrong_recovery_claim_hash_refuses_before_world_lock_or_loading_trial(self):
        authority = self.authority()
        with gate.OperationGate(self.attempts, self.pin).locked() as lease:
            claim = lease.begin(ATTEMPT, "standalone_trial", authority)
        with self.world_busy():
            code, result = self.run_cli(trial.__file__, self.trial_args(authority, command="recover",
                                                   claim=dict(claim, sha256="0" * 64)))
        self.assertEqual((code, result["code"]), (1, "claim_reference_changed"))
        self.assert_no_trial_entry()

    def test_real_experiment_cli_hook_and_trial_join_reach_status_with_no_gate_fd_in_guard_backend(self):
        authority = self.group_authority()
        args = ["run", "--plan", self.plan_ref["path"], "--directory", self.directory,
                "--operation-authority", authority["path"], "--operation-authority-sha256", authority["sha256"]]
        code, result = self.run_cli(experiment.__file__, args, timeout=40)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "blocked")
        self.assert_unready_artifacts()
        entries = list(self.root.glob(".operation-dispatch/*/*.entered.json"))
        self.assertEqual(len(entries), 1)
        entry = json.loads(entries[0].read_bytes())
        self.assertEqual(entry["binding"]["attempt_id"], ATTEMPT)
        self.assertEqual(entry["binding"]["plan"], self.plan_ref)
        self.assertNotEqual(OPERATION, self.plan["experiment_id"])
        coordinator = json.loads((self.directory / "coordinator.json").read_bytes())
        self.assertEqual(coordinator["status"], "stopped")
        self.assertEqual(len(coordinator["submissions"]), 1)
        self.assertEqual(coordinator["submissions"][0]["returncode"], 1)
        self.assertFalse((self.attempts / ".operations" / OPERATION / "terminal.json").exists())

    def inherited_rejection(self, mode, expected_code):
        authority = self.group_authority()
        payload = write_json(self.root / "parent-input.json", {"scripts": str(SCRIPTS), "plan": self.plan_ref,
            "directory": str(self.directory), "authority": authority, "mode": mode})
        with self.world_busy():
            code, result = self.run_cli(self.driver, [payload["path"]])
        self.assertEqual(code, 0, result)
        self.assertEqual(len(result["children"]), 1, result)
        child = result["children"][0]
        self.assertEqual((child["returncode"], child["result"]["code"]), (1, expected_code), result)
        self.assert_no_trial_entry()
        state = json.loads((self.directory / "coordinator.json").read_bytes())
        self.assertEqual(len(state["submissions"]), 1)
        if mode == "submission":
            # The intentional on-disk drift must also stop the parent from
            # overwriting that journal with a guessed child-return receipt.
            self.assertEqual(result["code"], "coordinator_journal_changed")
            self.assertIsNone(state["submissions"][0]["returncode"])
            self.assertEqual(state["events"][-1]["kind"], "submission_intent")
        else:
            self.assertEqual(state["submissions"][0]["returncode"], 1)

    def test_inherited_wrong_envelope_hash_refuses_before_world_lock(self):
        self.inherited_rejection("envelope", "reference_changed")

    def test_inherited_changed_parent_claim_refuses_before_world_lock(self):
        self.inherited_rejection("claim", "reference_changed")

    def test_inherited_changed_current_plan_refuses_before_world_lock(self):
        self.inherited_rejection("plan", "reference_changed")

    def test_inherited_changed_request_refuses_before_world_lock(self):
        self.inherited_rejection("request", "operation_entry_mismatch")

    def test_inherited_noncurrent_submission_refuses_before_world_lock(self):
        self.inherited_rejection("submission", "operation_submission_not_current")

    def test_inherited_correct_request_bytes_outside_coordinator_refuse_before_world_lock(self):
        self.inherited_rejection("request_path", "operation_request_outside_coordinator")

    def test_competing_gate_blocks_experiment_cli_before_world_lock_or_coordinator_creation(self):
        authority = self.group_authority()
        args = ["run", "--plan", self.plan_ref["path"], "--directory", self.directory,
                "--operation-authority", authority["path"], "--operation-authority-sha256", authority["sha256"]]
        competitor = self.authority(kind="finite_group", operation_id=COMPETITOR,
            subject={"type": "offline_competitor"}, name="competitor.json")
        with gate.OperationGate(self.attempts, self.pin).locked() as lease, self.world_busy():
            lease.begin(COMPETITOR, "finite_group", competitor)
            code, result = self.run_cli(experiment.__file__, args)
        self.assertEqual((code, result["code"]), (1, "operation_busy"))
        self.assert_no_trial_entry()
        self.assertFalse(self.directory.exists())

    def lifecycle_contention(self, command, *, pending=False):
        fixture = lifecycle_fixture.LifecycleTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()  # Builds only private files and a FakeHost; no lifecycle method runs.
        attempts = Path(fixture.config["attempt_root"])
        pin = gate.initialize_registry(attempts)
        subject = {"type": "lifecycle", "config": fixture.config_ref, "handoff": fixture.request_ref,
                   "lifecycle_id": fixture.request["operation_id"]}
        authority = write_json(fixture.root / "operation-authority.json", {"schema_version": 1,
            "operation_id": fixture.request["operation_id"], "kind": "standalone_lifecycle", "gate": pin,
            "subject": subject, "source_files": self.sources})
        args = ["--config", fixture.config_ref["path"], "--operation-authority", authority["path"],
                "--operation-authority-sha256", authority["sha256"], command, "--request",
                fixture.request_ref["path"], "--sha256", fixture.request_ref["sha256"]]
        competing = write_json(fixture.root / "competing.json", {"kind": "offline_competing_operation"})
        control = gate.OperationGate(attempts, pin)
        if pending:
            with control.locked() as lease:
                lease.begin(COMPETITOR, "finite_group", competing)
            with self.world_busy(Path(fixture.config["locks"]["world"]["path"])):
                code, result = self.run_cli(lifecycle.__file__, args)
        else:
            with control.locked() as lease, self.world_busy(Path(fixture.config["locks"]["world"]["path"])):
                lease.begin(COMPETITOR, "finite_group", competing)
                code, result = self.run_cli(lifecycle.__file__, args)
        self.assertEqual((code, result["error"]), (1, "pending_operation" if pending else "operation_busy"))
        self.assertFalse((Path(fixture.config["state_root"]) / ".lifecycle.lock").exists())
        self.assertFalse((Path(fixture.config["state_root"]) / fixture.request["operation_id"]).exists())
        self.assertEqual(fixture.host.started, [])

    def test_competing_gate_blocks_lifecycle_check_before_world_locks(self):
        self.lifecycle_contention("check")

    def test_competing_gate_blocks_lifecycle_start_before_world_locks(self):
        self.lifecycle_contention("start")

    def test_unresolved_released_operation_blocks_lifecycle_check_before_world_locks(self):
        self.lifecycle_contention("check", pending=True)


if __name__ == "__main__":
    unittest.main()
