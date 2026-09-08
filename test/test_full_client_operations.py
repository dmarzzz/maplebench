"""Offline finite-group composition: real journals/locks, synthetic service host.

No process launcher, browser, database, model or host service is invoked. Existing
coordinator, gate, handoff and lifecycle code execute against protected temporary
files. Only model transport/scoring and the native host are injected boundaries.
"""
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import full_client_operations as operations
import full_client_experiment as experiment
import full_client_lifecycle as native
import test_full_client_experiment as plan_fixtures
import test_full_client_lifecycle as native_fixtures


class RecordingHost(native_fixtures.FakeHost):
    """Service replies are synthetic; log-prefix hashes are actual file bytes."""
    def command(self, argv):
        if argv[-1] == self.config["services"]["cosmic"]["unit"]:
            with Path(self.config["native"]["path"]).open("ab") as stream:
                stream.write(b"Cosmic is now online after 10 ms.\n")
        return super().command(argv)

    def native(self, pid, config, boundary, intent_at_ms):
        raw = Path(config["path"]).read_bytes(); info = Path(config["path"]).stat()
        return {"log_sha256": hashlib.sha256(raw).hexdigest(),
                "startup_sha256": hashlib.sha256(raw[boundary["bytes"]:]).hexdigest(),
                "offset": boundary["bytes"], "bytes": len(raw), "device": info.st_dev,
                "inode": info.st_ino, "fd": 12, "ports": config["ports"], "observed_at_ms": self.now()}


@unittest.skipUnless(sys.platform.startswith("linux"), "Uses actual Linux FLOCK behavior")
class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.native = native_fixtures.LifecycleTests(); self.native.setUp()
        self.addCleanup(self.native.doCleanups)
        self.builder = plan_fixtures.ExperimentTests(); self.builder.setUp()
        self.addCleanup(self.builder.doCleanups)
        self.root = self.native.root
        self.builder.root = self.root
        self.clock = plan_fixtures.Clock()
        self.config = copy.deepcopy(self.native.config)
        runner = self.root / "attempts/.runner.lock"; runner.touch(mode=0o600)
        info = runner.stat()
        self.config["locks"]["runner"] = {"path": str(runner), "device": info.st_dev,
            "inode": info.st_ino, "uid": info.st_uid, "mode": 0o600}
        self.config_ref = self.write(self.root / "normal-config.json", self.config)
        self.historical = copy.deepcopy(self.native.request["attempts"])
        old = json.loads(Path(self.historical[0]["journal"]["path"]).read_text())
        old.update(pending=None, phase="status")
        old["receipts"]["status"] = self.status()
        self.historical[0]["journal"] = self.write(Path(self.historical[0]["journal"]["path"]), old)
        config = self.builder.config(models=["gpt-6-astra", "gpt-5.6-sol"])
        for fixture in config["fixtures"]:
            adapter_path = Path(fixture["adapter_config"]["path"])
            adapter = json.loads(adapter_path.read_text())
            backend_path = Path(adapter["argv"][-1])
            backend = json.loads(backend_path.read_text())
            backend.update(admin_socket=self.config["admin_socket"], queue_database=self.config["queue_database"],
                mysql=self.config["mysql"], services={role: self.config["services"][role] if role == "world"
                    else self.config["services"][role]["unit"] for role in ("world", "cosmic", "worker")})
            self.write(backend_path, backend)
        ids = iter(["1" * 32, "2" * 32])
        self.plan = experiment.build_plan(config, id_factory=lambda: next(ids))
        self.plan_ref = self.write(self.root / "plan.json", self.plan)
        self.snapshot = copy.deepcopy(self.native.snapshot)
        self.snapshot.update(run_id="a" * 32, captured_at_ms=100000)
        self.snapshot_ref = self.write(self.root / "initial-db.json", self.snapshot)
        self.host = RecordingHost(self.config, self.snapshot, self.native.request)
        self.calls, self.starts = [], []
        self.fail_child = None; self.unresolved = False; self.crash_handoff = False
        self.fail_finish = False; self.omit_first_idle = False; self.last_engine = None
        self.freeze_after_submission = False
        self.pin = operations.access.gate.initialize_registry(self.config["attempt_root"], owner_uid=os.geteuid())
        sources = set(operations.REQUIRED_SOURCES)
        sources.update(str(Path(module.__file__).resolve()) for module in
                       (operations.access, operations.access.gate, operations.access.join))
        self.subject = {"schema_version": 1, "plan": self.plan_ref, "experiment_directory": str(self.root / "experiment"),
            "normal_config": self.config_ref, "historical_attempts": self.historical, "initial_snapshot": self.snapshot_ref,
            "output_directory": str(self.root / "operations"), "restoration_operation_id": "d" * 32,
            "limits": {"admission_seconds": 60, "handoff_seconds": 60, "restoration_seconds": 120,
                       "total_seconds": 490, "memory_bytes": 768 * 1024**2, "cpu_seconds": 120, "cpus": 2}}
        self.authority = {"schema_version": 1, "operation_id": "e" * 32, "kind": "finite_group", "gate": self.pin,
                          "subject": self.subject, "source_files": [operations.access.source_ref(name, owner_uid=os.geteuid()) for name in sorted(sources)]}
        self.authority_ref = self.write(self.root / "authority.json", self.authority)
        self.bundle_patch = patch.object(native.full_client_score, "verify_trial_bundle", side_effect=self.verify_bundle)
        self.bundle_patch.start(); self.addCleanup(self.bundle_patch.stop)

    def write(self, filename, value):
        return native_fixtures.write_json(filename, value)

    @staticmethod
    def status():
        return {key: key != "ownership_conflict" for key in native.full_client_trial.STATUS_FIELDS}

    def verify_bundle(self, evidence, folder, artifacts):
        self.assertEqual(evidence["run_id"], Path(folder).name)
        value = native.full_client_score.parse_json(native.full_client_score.read_artifact_bytes(folder, artifacts["final_db"], "final_db"))
        self.assertEqual(value["run_id"], evidence["run_id"])
        return {key: evidence[key] for key in ("run_id", "scenario_fingerprint", "baseline_sha256")}

    def gate_held(self):
        with open(self.pin["path"], "r") as stream:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def launcher(self, plan, entry, request_path, timeout, **kwargs):
        self.gate_held()
        stored = json.loads((self.root / "experiment/coordinator.json").read_text())
        self.assertEqual(stored["events"][-1]["kind"], "submission_intent")
        # The wrapper must never hold world descriptions while the child runs.
        for pin in self.config["locks"].values():
            with open(pin["path"], "r") as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.calls.append(entry["attempt_id"])
        if self.unresolved:
            raise OSError("synthetic private failure text")
        folder = Path(plan["runner"]["state_root"]) / entry["attempt_id"]
        folder.mkdir(mode=0o700)
        value = copy.deepcopy(self.snapshot)
        # Keep zero and negative outcomes visible; do not reset to initial XP.
        value["character"]["exp"] += 0 if len(self.calls) == 1 else -100
        value["run_id"] = entry["attempt_id"]
        ref = self.write(folder / "final-db.json", value)
        self.host.expected = value
        evidence = {"run_id": entry["attempt_id"], "scenario_fingerprint": entry["spec"]["scenario_fingerprint"],
                    "baseline_sha256": entry["spec"]["baseline_sha256"]}
        journal = {"schema_version": 1, "attempt_id": entry["attempt_id"], "status": "completed", "pending": None,
            "request": entry["spec"], "adapter_fingerprint": experiment.fixture_for(plan, entry)["adapter_fingerprint"],
            "events": [{"sequence": 0}], "charged_usage": {"api_requests": 1, "total_tokens": 100},
            "phase": "status", "phase_status": "returned", "receipts": {"status": self.status(),
            "cleanup": {"attempt_id": entry["attempt_id"], "clean": True},
            "collect_final": {"evidence": evidence, "artifacts": {"final_db": {"path": "final-db.json", "sha256": ref["sha256"]}}}}}
        self.write(folder / "journal.json", journal)
        self.write(folder / "backend-state.json", {"attempt_id": entry["attempt_id"], "clean": True})
        return 1 if self.fail_child == len(self.calls) else 0

    def experiment_factory(self, plan, directory, **kwargs):
        return experiment.Experiment(plan, directory, launcher=self.launcher, verify=lambda _: None,
            wall_time=self.clock, monotonic=self.clock, **kwargs)

    def life_factory(self, config, ref, deadline, uid):
        engine = operations.BoundLifecycle(config, ref, self.host, deadline=deadline, owner_uid=uid)
        self.host.engine = self.last_engine = engine
        original = engine.start
        def start(*args, **kwargs):
            self.gate_held(); self.assertEqual(engine.world_fds, []); self.assertIsNone(engine.serial_fd)
            state = json.loads((self.root / "operations/journal.json").read_text())
            self.assertEqual(state["phase"], "normal_restoring")
            self.starts.append("lifecycle")
            result = original(*args, **kwargs)
            if self.omit_first_idle:
                value = json.loads(Path(result["journal"]["path"]).read_text()); value.pop("first_idle")
                self.write(Path(result["journal"]["path"]), value)
            return result
        engine.start = start
        return engine

    def handoff(self, *args, **kwargs):
        self.gate_held()
        result = operations.handoff.prepare_handoff(*args, **kwargs)
        if self.crash_handoff:
            self.crash_handoff = False
            raise OSError("synthetic lost publication response")
        return result

    def group_report(self, plan, directory):
        def metrics(plan, entry, observed):
            folder = observed["folder"]
            value = json.loads((folder / "final-db.json").read_text())
            return {"net_xp": value["character"]["exp"] - self.snapshot["character"]["exp"],
                    "actions": 0, "no_op": True, "execution_verification": "complete_action_receipts",
                    "alive_at_logout": True, "session_ms": 1000}
        return experiment.report(plan, directory, metrics=metrics)

    @contextmanager
    def admission(self, *args, **kwargs):
        with operations.access.admitted(*args, **kwargs) as value:
            finish = value.finish
            def wrapped(evidence):
                if self.fail_finish:
                    self.fail_finish = False
                    raise OSError("synthetic lost terminal acknowledgement")
                return finish(evidence)
            value.finish = wrapped
            yield value

    def dispatch(self, *args):
        @contextmanager
        def prepare(plan, entry, request_path):
            self.gate_held()
            if self.freeze_after_submission:
                self.clock.value += 130
            yield None
        return prepare

    def wrapper(self):
        factories = operations.Factories(experiment=self.experiment_factory, lifecycle=self.life_factory,
            admitted=self.admission, handoff=self.handoff, report=self.group_report,
            verify_inputs=lambda _: None, dispatch=self.dispatch,
            launch=lambda sources, **_: {"script": next(ref for ref in sources if ref["path"] == str(Path(operations.__file__).resolve()))})
        return operations.Operations(self.authority_ref, factories=factories, owner_uid=os.geteuid(),
                                     wall=self.clock, monotonic=self.clock, boot=lambda: native_fixtures.BOOT)

    def journal(self):
        return operations.actual_ref(self.root / "operations/journal.json", os.geteuid())

    def test_two_entries_seal_then_restore_once_with_complete_negative_zero_report(self):
        result = self.wrapper().run()
        self.assertTrue(result["normal_restored"])
        self.assertEqual(self.calls, ["1" * 32, "2" * 32]); self.assertEqual(self.starts, ["lifecycle"])
        self.assertEqual(self.host.started, ["cosmic", "worker"])
        report = operations.read_ref(result["group_report"], os.geteuid())
        self.assertEqual([row["metrics"]["net_xp"] for row in report["attempts"]], [0, -100])
        self.assertFalse(report["ranked"])
        prepared = operations.read_ref(self.root_ref("operations/handoff/handoff.json"), os.geteuid())
        self.assertEqual(len(prepared["attempts"]), 3)
        self.assertEqual(operations.read_ref(prepared["offline_snapshot"], os.geteuid())["character"]["exp"], 8900)
        self.assertTrue(experiment.report(self.plan, self.root / "experiment")["sealed"])

    def root_ref(self, name):
        return operations.actual_ref(self.root / name, os.geteuid())

    def test_clean_child_failure_seals_future_entries_and_restores(self):
        self.fail_child = 1
        result = self.wrapper().run()
        self.assertTrue(result["normal_restored"]); self.assertEqual(len(self.calls), 1)
        report = operations.read_ref(result["group_report"], os.geteuid())
        self.assertEqual(report["attempts"][1]["status"], "unsubmitted")
        with self.assertRaisesRegex(experiment.ExperimentError, "experiment_sealed"):
            self.experiment_factory(self.plan, self.root / "experiment").run(resume=True)

    def test_missing_submitted_attempt_never_recovers_or_restores(self):
        self.unresolved = True
        with self.assertRaisesRegex(operations.OperationsError, "submitted_attempt_unresolved"):
            self.wrapper().run()
        ref = self.journal(); initial = operations.read_ref(ref, os.geteuid())
        with self.assertRaisesRegex(operations.OperationsError, "submitted_attempt_unresolved"):
            self.wrapper().reconcile(ref)
        self.assertEqual(len(self.calls), 1); self.assertEqual(self.starts, [])
        self.assertEqual(initial["status"], "needs_reconciliation")

    def test_handoff_lost_response_adopts_exact_files_without_repeating_preparation(self):
        self.crash_handoff = True
        with self.assertRaises(OSError):self.wrapper().run()
        ref = self.journal(); before = (self.root / "operations/handoff/handoff.json").read_bytes()
        result = self.wrapper().reconcile(ref)
        self.assertTrue(result["normal_restored"]); self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.starts, ["lifecycle"])
        self.assertEqual((self.root / "operations/handoff/handoff.json").read_bytes(), before)

    def test_lost_terminal_publication_preserves_completed_journal_and_no_second_start(self):
        self.fail_finish = True
        with self.assertRaises(OSError):self.wrapper().run()
        ref = self.journal(); raw = Path(ref["path"]).read_bytes()
        self.assertEqual(operations.read_ref(ref, os.geteuid())["status"], "completed")
        result = self.wrapper().reconcile(ref)
        self.assertTrue(result["normal_restored"])
        self.assertEqual(Path(ref["path"]).read_bytes(), raw)
        self.assertEqual(self.starts, ["lifecycle"])

    def test_original_deadline_is_not_renewed_on_reconcile(self):
        self.crash_handoff = True
        with self.assertRaises(OSError):self.wrapper().run()
        ref = self.journal(); value = operations.read_ref(ref, os.geteuid())
        self.clock.value += self.subject["limits"]["total_seconds"] + 1
        with self.assertRaisesRegex(operations.OperationsError, "operations_deadline_exceeded"):
            self.wrapper().reconcile(ref)
        self.assertEqual(self.starts, []); self.assertEqual(len(self.calls), 2)
        self.assertEqual(operations.read_ref(self.journal(), os.geteuid())["deadline_at_ms"], value["deadline_at_ms"])

    def test_lost_service_replies_require_exact_observation_and_never_repeat_start(self):
        # Each case has its own complete gate, finite plan and lifecycle state.
        for role in ("cosmic", "worker"):
            with self.subTest(role=role):
                case = OperationsTests()
                case.setUp()
                try:
                    case.host.crash_after = role
                    with self.assertRaises(SystemExit):case.wrapper().run()
                    outer = case.journal()
                    life_path = Path(case.config["state_root"]) / case.subject["restoration_operation_id"] / "journal.json"
                    lifecycle = operations.actual_ref(life_path, os.geteuid())
                    before_starts = list(case.host.started)
                    with self.assertRaisesRegex(operations.OperationsError, "exact_lifecycle_reconciliation_required"):
                        case.wrapper().reconcile(outer)
                    self.assertEqual(case.host.started, before_starts)
                    case.host.crash_after = None
                    observation = case.write(case.root / (role + "-observation.json"), {"schema_version": 1,
                        "operation_id": case.subject["restoration_operation_id"], "boot_id": native_fixtures.BOOT,
                        "role": role, "instance": case.host.identities[role]})
                    result = case.wrapper().reconcile(case.journal(), lifecycle_ref=lifecycle, observation_ref=observation)
                    self.assertTrue(result["normal_restored"])
                    self.assertEqual(case.host.started, ["cosmic", "worker"])
                    self.assertEqual(case.calls, ["1" * 32, "2" * 32])
                finally:
                    case.doCleanups()

    def test_completed_gate_lost_reply_returns_original_receipts_without_another_operation(self):
        real_finish = operations.access.Admission.finish
        def lost_reply(active, evidence):
            real_finish(active, evidence)
            raise OSError("synthetic lost reply after actual terminal publication")
        with patch.object(operations.access.Admission, "finish", lost_reply):
            with self.assertRaises(OSError):self.wrapper().run()
        ref = self.journal()
        before = Path(ref["path"]).read_bytes()
        result = self.wrapper().reconcile(ref)
        self.assertTrue(result["normal_restored"])
        self.assertEqual(Path(ref["path"]).read_bytes(), before)
        self.assertEqual(self.host.started, ["cosmic", "worker"])
        self.assertEqual(len(self.calls), 2)

    def test_fresh_hash_does_not_authorize_journal_phase_or_deadline_rewrite(self):
        self.crash_handoff = True
        with self.assertRaises(OSError):self.wrapper().run()
        ref = self.journal(); original = operations.read_ref(ref, os.geteuid())
        altered = copy.deepcopy(original)
        altered["events"][-1]["phase"] = "admitted"
        changed = self.write(Path(ref["path"]), altered)
        with self.assertRaisesRegex(operations.OperationsError, "operations_event_order_changed"):
            self.wrapper().reconcile(changed)
        altered = copy.deepcopy(original)
        altered["restoration_deadline_at_ms"] = altered["deadline_at_ms"] + 1
        changed = self.write(Path(ref["path"]), altered)
        with self.assertRaisesRegex(operations.OperationsError, "operations_restoration_intent_missing"):
            self.wrapper().reconcile(changed)
        self.assertEqual(self.starts, [])

    def test_exact_journal_hash_required_before_reconciliation(self):
        self.unresolved = True
        with self.assertRaises(operations.OperationsError):self.wrapper().run()
        ref = self.journal(); Path(ref["path"]).write_bytes(Path(ref["path"]).read_bytes() + b" ")
        with self.assertRaises(operations.access.gate.GateError):self.wrapper().reconcile(ref)
        self.assertEqual(self.starts, []); self.assertEqual(len(self.calls), 1)

    def test_missing_first_idle_never_marks_operation_completed(self):
        self.omit_first_idle = True
        with self.assertRaises(operations.OperationsError):self.wrapper().run()
        self.assertEqual(operations.read_ref(self.journal(), os.geteuid())["status"], "needs_reconciliation")
        self.assertEqual(self.host.started, ["cosmic", "worker"])

    def test_foreign_attempt_and_wrong_world_refuse_before_experiment(self):
        extra = self.root / "attempts" / ("f" * 32); extra.mkdir(mode=0o700)
        with self.assertRaisesRegex(operations.OperationsError, "attempt_inventory_changed"):
            self.wrapper().run()
        self.assertEqual(self.calls, []); self.assertEqual(self.starts, [])

    def test_fixture_account_mismatch_and_initial_snapshot_drift_refuse_before_dispatch(self):
        backend = self.root / "fixture0-backend.json"
        value = json.loads(backend.read_text()); value["mysql"]["account_id"] += 1
        self.write(backend, value)
        with self.assertRaisesRegex(operations.OperationsError, "fixture_restoration_world_mismatch"):
            self.wrapper()
        self.assertFalse((self.root / "operations").exists())
        value["mysql"]["account_id"] -= 1; self.write(backend, value)
        self.host.expected = copy.deepcopy(self.snapshot); self.host.expected["character"]["exp"] += 1
        with self.assertRaisesRegex(operations.OperationsError, "initial_persisted_snapshot_changed"):
            self.wrapper().run()
        self.assertEqual(self.calls, [])

    def test_replaced_world_lock_inode_refuses_before_claim(self):
        location = Path(self.config["locks"]["world"]["path"])
        replacement = location.with_suffix(".replacement"); replacement.touch(mode=0o600)
        os.replace(replacement, location)
        with self.assertRaisesRegex(operations.OperationsError, "normal_world_lock_identity_changed"):
            self.wrapper()
        self.assertFalse((self.root / "operations").exists())

    def test_unexecutable_aggregate_restoration_reserve_refuses_before_claim(self):
        self.authority["subject"]["limits"]["total_seconds"] -= 1
        self.authority_ref = self.write(self.root / "authority.json", self.authority)
        with self.assertRaisesRegex(operations.OperationsError, "outer_deadline_reserve_mismatch"):
            self.wrapper()
        self.assertFalse((self.root / "operations").exists())
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
