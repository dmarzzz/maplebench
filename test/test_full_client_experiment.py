"""Offline failure-injected experiments; no model, browser, database or services."""
import contextlib
import copy
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import full_client_experiment as experiment
import full_client_score as scoring
from test_full_client_score import bundle_fixture, fixture as score_fixture, write_artifact


class Clock:
    def __init__(self):
        self.value = 1000000.0
    def __call__(self):
        return self.value


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.root.chmod(0o700)
        self.clock = Clock()
        self.calls = []
        self.observed = {}

    def write(self, name, value):
        path = self.root / name
        raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True).encode()
        path.write_bytes(raw)
        path.chmod(0o600)
        return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}

    def config(self, *, models=None, repetitions=1, fixtures=1):
        models = list(models or experiment.MODELS[:2])
        self.attempts = self.root / "attempts"
        self.attempts.mkdir(mode=0o700, exist_ok=True)
        for name in ("world.lock", "queue.lock"):
            (self.root / name).write_text("")
        runner = {"python": experiment.pin(Path(sys.executable).resolve()),
            "trial_script": experiment.pin(Path(experiment.trial.__file__).resolve()),
            "dependencies": [experiment.pin(Path(module.__file__).resolve())
                             for module in (experiment, scoring, experiment.docker, experiment.readiness)],
            "state_root": str(self.attempts), "world_lock": str(self.root / "world.lock"),
            "queue_lock": str(self.root / "queue.lock")}
        budgets = {"total_seconds": 120, "operation_seconds": 30, "controller_seconds": 24,
                   "max_actions": 80, "max_api_requests": 1, "max_output_tokens": 3000, "max_total_tokens": 30000}
        values = []
        for index in range(fixtures):
            name = f"fixture{index}"
            scenario = self.write(name + "-scenario.json", {"id": name, "trial_budgets": budgets,
                "readiness_policy": {"schema_version": 1, "expected_map_id": 240040511,
                    "min_monsters": 1, "min_samples": 3, "min_span_ms": 1000, "timeout_ms": 10000}})
            baseline = self.write(name + "-baseline.sql", b"synthetic database baseline")
            baseline_snapshot = self.write(name + "-baseline-snapshot.json", {"character": {"map_id": 240040511}})
            runtime = self.write(name + "-runtime.json", {"schema_version": 2,
                "docker_image_id": "sha256:" + "a" * 64,
                "docker_binding": {"schema_version": 1, "executable": {"path": "/usr/bin/docker", "sha256": "b" * 64},
                                   "launcher": None, "socket_path": "/var/run/docker.sock"}})
            backend = self.write(name + "-backend.py", b"raise RuntimeError('This fixture must never execute')\n")
            configuration = self.write(name + "-backend.json", {"baseline": baseline, "baseline_snapshot": baseline_snapshot, "scenario": scenario,
                "runtime_manifest": runtime, "orchestrator": runner["trial_script"], "attempt_root": str(self.attempts),
                "world_lock": runner["world_lock"], "queue_lock": runner["queue_lock"]})
            adapter = self.write(name + "-adapter.json", {"argv": [runner["python"]["path"], backend["path"],
                "--config", configuration["path"]], "dependencies": []})
            values.append({"id": name, "scenario": scenario, "baseline": baseline, "runtime_manifest": runtime,
                           "adapter_config": adapter, "budgets": copy.deepcopy(budgets)})
        count = len(models) * repetitions * fixtures
        return {"schema_version": 1, "experiment_id": "synthetic-experiment", "models": models,
                "repetitions": repetitions, "fixtures": values, "runner": runner,
                "aggregate_limits": {"api_requests": count, "total_tokens": count * 30000,
                                     "wall_seconds": count * 125}}

    def plan(self, **kwargs):
        ids = iter(f"{number:032x}" for number in range(1, 201))
        return experiment.build_plan(self.config(**kwargs), id_factory=lambda: next(ids))

    def inspect(self, plan, entry):
        return self.observed.get(entry["attempt_id"], {"status": "missing", "terminal_clean": False})

    def completed(self, entry, status="completed"):
        self.observed[entry["attempt_id"]] = {"status": status, "terminal_clean": True,
            "journal_sha256": "a" * 64, "backend_sha256": "b" * 64,
            "usage": {"api_requests": 1, "total_tokens": 100}}

    def launcher(self, plan, entry, request_path, timeout):
        state = json.loads((self.root / "experiment/coordinator.json").read_text())
        self.assertEqual(state["events"][-1]["kind"], "submission_intent")
        self.assertEqual(state["submissions"][-1]["attempt_id"], entry["attempt_id"])
        self.assertEqual(state["submissions"][-1]["reservation"]["total_tokens"], 30000)
        self.assertEqual(hashlib.sha256(request_path.read_bytes()).hexdigest(), entry["spec_sha256"])
        self.assertGreater(timeout, 0)
        self.assertGreaterEqual(timeout, 121)
        self.assertLessEqual(timeout, 125)
        self.calls.append(entry["attempt_id"])
        self.completed(entry)
        return 0

    def coordinator(self, plan, **kwargs):
        return experiment.Experiment(plan, self.root / "experiment", launcher=kwargs.get("launcher", self.launcher),
            inspector=self.inspect, verify=kwargs.get("verify", lambda _: None),
            wall_time=self.clock, monotonic=self.clock)

    def test_rotations_are_exact_within_each_fixture_and_input_unchanged(self):
        config = self.config(models=list(experiment.MODELS), repetitions=4, fixtures=2)
        original = copy.deepcopy(config)
        plan = experiment.build_plan(config)
        self.assertEqual(config, original)
        self.assertEqual(len(plan["entries"]), 32)
        self.assertTrue(plan["balance"]["exact_position_balance"])
        for positions in plan["balance"]["position_counts"].values():
            self.assertTrue(all(counts == [1, 1, 1, 1] for counts in positions.values()))
        self.assertEqual(len({e["attempt_id"] for e in plan["entries"]}), 32)

    def test_plan_refuses_missing_weakened_or_wrong_map_readiness_before_assigning_ids(self):
        for change in (lambda s:s.pop("readiness_policy"),
                       lambda s:s["readiness_policy"].update(min_monsters=0),
                       lambda s:s["readiness_policy"].update(expected_map_id=100000000)):
            config = self.config(models=["gpt-6-astra"])
            fixture = config["fixtures"][0]
            scenario = json.loads(Path(fixture["scenario"]["path"]).read_text())
            change(scenario)
            fixture["scenario"] = self.write("fixture0-scenario.json", scenario)
            backend = json.loads((self.root / "fixture0-backend.json").read_text())
            backend["scenario"] = fixture["scenario"]
            self.write("fixture0-backend.json", backend)
            ids = []
            with self.assertRaisesRegex(experiment.ExperimentError, "invalid_readiness_policy"):
                experiment.build_plan(config, id_factory=lambda: ids.append("called"))
            self.assertEqual(ids, [])
            self.assertEqual(list(self.attempts.iterdir()), [])

    def test_readiness_module_and_baseline_snapshot_must_be_pinned(self):
        config = self.config()
        config["runner"]["dependencies"] = [ref for ref in config["runner"]["dependencies"]
            if ref["path"] != str(Path(experiment.readiness.__file__).resolve())]
        with self.assertRaisesRegex(experiment.ExperimentError, "runner_dependencies_missing"):
            experiment.build_plan(config)
        config = self.config()
        (self.root / "fixture0-baseline-snapshot.json").write_text('{"character":{"map_id":0}}')
        with self.assertRaises(experiment.ExperimentError):
            experiment.build_plan(config)

    def test_five_repetitions_do_not_claim_exact_four_model_balance(self):
        plan = self.plan(models=list(experiment.MODELS), repetitions=5)
        self.assertFalse(plan["balance"]["exact_position_balance"])
        for counts in plan["balance"]["position_counts"]["fixture0"].values():
            self.assertEqual(sorted(counts), [1, 1, 1, 2])
        altered = copy.deepcopy(plan)
        altered["balance"]["exact_position_balance"] = True
        with self.assertRaisesRegex(experiment.ExperimentError, "balance_claim"):
            experiment.validate_plan(altered)

    def test_invalid_model_duplicate_id_order_spec_and_limits_are_rejected(self):
        plan = self.plan()
        mutations = [lambda p: p["models"].__setitem__(0, "astra-latest"),
            lambda p: p["entries"][1].__setitem__("attempt_id", p["entries"][0]["attempt_id"]),
            lambda p: p["entries"].reverse(),
            lambda p: p["entries"][0]["spec"]["budgets"].__setitem__("max_actions", 79),
            lambda p: p["aggregate_limits"].__setitem__("api_requests", 1),
            lambda p: p["aggregate_limits"].__setitem__("total_tokens", 59999),
            lambda p: p["aggregate_limits"].__setitem__("wall_seconds", 249),
            lambda p: p["policy"].__setitem__("retries", 1)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                changed = copy.deepcopy(plan)
                mutate(changed)
                with self.assertRaises(experiment.ExperimentError):
                    experiment.validate_plan(changed)

    def test_immutable_private_plan_rejects_overwrite_symlink_and_duplicate_json(self):
        plan = self.plan()
        path = self.root / "plan.json"
        experiment.write_json(path, plan, create=True)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(experiment.ExperimentError, "file_already_exists"):
            experiment.write_json(path, plan, create=True)
        link = self.root / "link.json"
        link.symlink_to(path)
        with self.assertRaisesRegex(experiment.ExperimentError, "symlink_path"):
            experiment.read_file(link)
        with self.assertRaisesRegex(experiment.ExperimentError, "invalid_json"):
            experiment.decode(b'{"a":1,"a":2}')

    def test_schema_one_or_malformed_docker_binding_is_refused_for_new_plan(self):
        for version, binding in ((1, None), (2, {"schema_version": 1}), (True, None)):
            with self.subTest(version=version):
                config = self.config()
                ref = config["fixtures"][0]["runtime_manifest"]
                value = json.loads(Path(ref["path"]).read_text())
                value.update(schema_version=version, docker_binding=binding)
                new_ref = self.write(Path(ref["path"]).name, value)
                config["fixtures"][0]["runtime_manifest"] = new_ref
                with self.assertRaises(experiment.ExperimentError):
                    experiment.build_plan(config)

    def test_fixture_source_and_backend_config_drift_fail_before_submission(self):
        plan = self.plan()
        Path(plan["fixtures"][0]["scenario"]["path"]).write_text("changed")
        coordinator = self.coordinator(plan, verify=experiment.verify_inputs)
        with self.assertRaisesRegex(experiment.ExperimentError, "input_hash_mismatch"):
            coordinator.run()
        self.assertEqual(self.calls, [])
        self.assertEqual(coordinator.state["submissions"], [])

    def test_sparse_oversize_inputs_match_backend_caps_and_reject_before_read(self):
        self.assertEqual(experiment.MAX_BASELINE, 64 * 1024**2)
        self.assertEqual(experiment.MAX_MANIFEST, scoring.JSON_LIMIT)
        original_read = os.read
        for name, maximum in (("baseline", experiment.MAX_BASELINE),
                              ("runtime_manifest", experiment.MAX_MANIFEST)):
            with self.subTest(artifact=name):
                config = self.config()
                path = Path(config["fixtures"][0][name]["path"])
                with path.open("wb") as stream:
                    stream.truncate(maximum + 1)
                target = path.stat()
                def checked_read(fd, size):
                    actual = os.fstat(fd)
                    self.assertNotEqual((actual.st_dev, actual.st_ino),
                                        (target.st_dev, target.st_ino),
                                        "oversized input was read before size rejection")
                    return original_read(fd, size)
                with patch.object(experiment.os, "read", side_effect=checked_read):
                    with self.assertRaisesRegex(experiment.ExperimentError, "file_limit"):
                        experiment.build_plan(config)

    def test_fsynced_intent_precedes_each_child_and_completed_ids_never_replay(self):
        plan = self.plan()
        coordinator = self.coordinator(plan)
        result = coordinator.run()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["submitted"], 2)
        self.assertFalse(result["ranked"])
        self.coordinator(plan).run(resume=True)
        self.assertEqual(self.calls, [e["attempt_id"] for e in plan["entries"]])
        with self.assertRaisesRegex(experiment.ExperimentError, "explicit_resume_required"):
            self.coordinator(plan).run()

    def test_crash_after_intent_with_missing_attempt_blocks_resume_without_replay(self):
        plan = self.plan()
        def crash(*args):
            self.calls.append(args[1]["attempt_id"])
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.coordinator(plan, launcher=crash).run()
        with self.assertRaisesRegex(experiment.ExperimentError, "submitted_attempt_unresolved"):
            self.coordinator(plan).run(resume=True)
        self.assertEqual(len(self.calls), 1)
        value = experiment.report(plan, self.root / "experiment", inspector=self.inspect)
        self.assertEqual([r["status"] for r in value["attempts"]], ["submitted_unresolved", "unsubmitted"])

    def test_failed_attempt_stops_and_explicit_recovery_allows_only_future_ids(self):
        plan = self.plan()
        first = plan["entries"][0]
        def fail(plan, entry, path, timeout):
            self.calls.append(entry["attempt_id"])
            self.observed[entry["attempt_id"]] = {"status": "failed", "terminal_clean": False}
            return 1
        with self.assertRaisesRegex(experiment.ExperimentError, "submitted_attempt_unresolved"):
            self.coordinator(plan, launcher=fail).run()
        with self.assertRaisesRegex(experiment.ExperimentError, "submitted_attempt_unresolved"):
            self.coordinator(plan).run(resume=True)
        self.completed(first, "recovered")
        self.coordinator(plan).run(resume=True)
        self.assertEqual(self.calls, [e["attempt_id"] for e in plan["entries"]])

    def test_deadline_includes_pause_and_is_never_renewed(self):
        plan = self.plan()
        def stop(plan, entry, path, timeout):
            self.completed(entry)
            return 1
        with self.assertRaisesRegex(experiment.ExperimentError, "child_failed"):
            self.coordinator(plan, launcher=stop).run()
        path = self.root / "experiment/coordinator.json"
        deadline = json.loads(path.read_text())["deadline_at_ms"]
        self.clock.value += 251
        with self.assertRaisesRegex(experiment.ExperimentError, "experiment_deadline_exceeded"):
            self.coordinator(plan).run(resume=True)
        self.assertEqual(json.loads(path.read_text())["deadline_at_ms"], deadline)
        self.assertEqual(len(json.loads(path.read_text())["submissions"]), 1)

    def test_backwards_clock_and_post_return_overrun_cannot_extend_budget(self):
        plan = self.plan()
        def late(plan, entry, path, timeout):
            self.completed(entry)
            self.clock.value += 251
            return 0
        with self.assertRaisesRegex(experiment.ExperimentError, "experiment_deadline_exceeded"):
            self.coordinator(plan, launcher=late).run()
        self.clock.value = 1
        with self.assertRaisesRegex(experiment.ExperimentError, "clock_moved_backwards"):
            self.coordinator(plan).run(resume=True)

    def test_resume_with_partial_trial_time_never_submits_next_id(self):
        plan = self.plan()
        def stop(plan, entry, path, timeout):
            self.completed(entry)
            return 1
        with self.assertRaisesRegex(experiment.ExperimentError, "child_failed"):
            self.coordinator(plan, launcher=stop).run()
        self.clock.value += 240  # Only ten seconds remain, versus a full 120-second trial.
        with self.assertRaisesRegex(experiment.ExperimentError, "insufficient_time_for_full_trial"):
            self.coordinator(plan).run(resume=True)
        state = json.loads((self.root / "experiment/coordinator.json").read_text())
        self.assertEqual(len(state["submissions"]), 1)

    def test_coordinator_lock_excludes_another_submission(self):
        plan = self.plan()
        coordinator = self.coordinator(plan)
        with coordinator.locked():
            with self.assertRaisesRegex(experiment.ExperimentError, "experiment_already_running"):
                self.coordinator(plan).run()
        self.assertEqual(self.calls, [])

    def test_existing_unsubmitted_id_and_changed_terminal_hash_refuse(self):
        plan = self.plan()
        (self.attempts / plan["entries"][0]["attempt_id"]).mkdir(mode=0o700)
        with self.assertRaisesRegex(experiment.ExperimentError, "unsubmitted_attempt_already_exists"):
            self.coordinator(plan).run()
        self.assertEqual(self.calls, [])
        (self.attempts / plan["entries"][0]["attempt_id"]).rmdir()
        self.coordinator(plan).run(resume=True)
        self.observed[plan["entries"][0]["attempt_id"]]["journal_sha256"] = "c" * 64
        with self.assertRaisesRegex(experiment.ExperimentError, "settled_attempt_changed"):
            self.coordinator(plan).run(resume=True)

    def test_report_full_plan_includes_negative_zero_noop_failed_and_missing(self):
        plan = self.plan(models=[experiment.MODELS[0]], repetitions=5)
        self.coordinator(plan).run()
        values = iter([{"net_xp": -50, "actions": 2, "no_op": False},
                       {"net_xp": 0, "actions": 0, "no_op": True},
                       {"net_xp": 100, "actions": 5, "no_op": False}])
        last = plan["entries"][4]["attempt_id"]
        self.observed.pop(last)
        failed = plan["entries"][3]["attempt_id"]
        self.observed[failed] = {"status": "failed", "terminal_clean": False}
        # A changed settled receipt is invalid, never silently omitted or zeroed.
        value = experiment.report(plan, self.root / "experiment", inspector=self.inspect, metrics=lambda *args: next(values))
        self.assertEqual(len(value["attempts"]), 5)
        group = value["groups"][0]
        self.assertEqual(group["verified_n"], 3)
        self.assertEqual(group["no_op_count"], 1)
        self.assertEqual(group["net_xp"]["mean"], 50 / 3)
        self.assertEqual(group["net_xp"]["minimum"], -50)
        self.assertEqual(group["outcome_counts"]["invalid_receipts"], 2)
        self.assertIsNone(group["uncertainty"]["confidence_interval"])
        self.assertFalse(value["ranked"])

    def actual_bundle(self, plan, entry, delta=0, actions=0):
        folder = self.attempts / entry["attempt_id"]
        folder.mkdir(mode=0o700)
        evidence = score_fixture()
        old = evidence["run_id"]
        def rename(value):
            if isinstance(value, dict):
                return {k: rename(v) for k, v in value.items()}
            if isinstance(value, list):
                return [rename(v) for v in value]
            return entry["attempt_id"] if value == old else value
        evidence = rename(evidence)
        evidence["final"]["character"]["exp"] += delta
        fixture = experiment.fixture_for(plan, entry)
        scenario = json.loads(Path(fixture["scenario"]["path"]).read_text())
        with patch("test_full_client_score.fixture", return_value=evidence):
            evidence, refs = bundle_fixture(folder, scenario)
        context = {"scenario_fingerprint": entry["spec"]["scenario_fingerprint"],
                   "baseline_sha256": entry["spec"]["baseline_sha256"]}
        runtime = json.loads(Path(fixture["runtime_manifest"]["path"]).read_text())
        write_artifact(folder, refs, "runtime_manifest", runtime)
        result = {"source": "full-client-trial", "trialContext": context,
            "controller": {"id": entry["attempt_id"], "status": "completed", "mode": "api",
                "model": entry["model"], "returnedModel": entry["model"], "trialContext": context,
                "dockerImageId": runtime["docker_image_id"], "dockerBinding": runtime["docker_binding"], "actions": actions},
            "api": {"id": "synthetic-response", "model": entry["model"], "status": "completed",
                    "usage": {"input_tokens": 60, "output_tokens": 40, "total_tokens": 100}},
            "program": {"actions": actions, "actionAttempts": actions, "error": None,
                "steps": [{"kind": "sdk", "method": "pressKeys", "result": {"accepted": True}} for _ in range(actions)]}}
        write_artifact(folder, refs, "result", result)
        for name in ("api_request", "api_response"):
            write_artifact(folder, refs, name, {"id": "synthetic-response", "model": entry["model"], "status": "completed",
                                              "usage": result["api"]["usage"],
                                              "metadata": {"maplebench_run_id": entry["attempt_id"]}})
        score = scoring.verify_trial_bundle(evidence, folder, refs)
        write_artifact(folder, refs, "score", score)
        journal = {"schema_version": 1, "attempt_id": entry["attempt_id"], "request": entry["spec"],
            "adapter_fingerprint": fixture["adapter_fingerprint"], "status": "completed", "phase": "status",
            "phase_status": "returned", "events": [{"sequence": 0, "kind": "evidence_verified"}],
            "charged_usage": {"api_requests": 1, "total_tokens": 100}, "score": score,
            "receipts": {"collect_final": {"evidence": evidence, "artifacts": refs},
                "cleanup": {"attempt_id": entry["attempt_id"], "clean": True},
                "status": {k: k != "ownership_conflict" for k in experiment.trial.STATUS_FIELDS}}}
        for name, value in (("journal", journal), ("backend-state", {"attempt_id": entry["attempt_id"], "clean": True})):
            (folder / (name + ".json")).write_bytes(experiment.encoded(value))
            (folder / (name + ".json")).chmod(0o600)
        return folder, refs, journal

    def test_real_persistence_artifacts_recompute_signed_score_and_detect_tamper(self):
        plan = self.plan(models=[experiment.MODELS[0]])
        entry = plan["entries"][0]
        folder, refs, journal = self.actual_bundle(plan, entry, delta=-100, actions=0)
        observed = experiment.inspect_attempt(plan, entry)
        metrics = experiment.verified_metrics(plan, entry, observed)
        self.assertEqual(metrics["net_xp"], -100)
        self.assertTrue(metrics["no_op"])
        (folder / refs["final_db"]["path"]).write_text("private-bad-evidence")
        with self.assertRaises(scoring.EvidenceError):
            experiment.verified_metrics(plan, entry, observed)

    def test_actual_bundle_wrong_runtime_or_returned_model_never_labels_verified(self):
        plan = self.plan(models=[experiment.MODELS[0]])
        entry = plan["entries"][0]
        folder, refs, journal = self.actual_bundle(plan, entry)
        observed = experiment.inspect_attempt(plan, entry)
        result = json.loads((folder / refs["result"]["path"]).read_text())
        result["controller"]["returnedModel"] = experiment.MODELS[1]
        write_artifact(folder, refs, "result", result)
        observed["journal"]["receipts"]["collect_final"]["artifacts"] = refs
        with self.assertRaisesRegex(experiment.ExperimentError, "score_model_or_receipt_mismatch"):
            experiment.verified_metrics(plan, entry, observed)
        refs["runtime_manifest"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(experiment.ExperimentError, "score_fixture_mismatch"):
            experiment.verified_metrics(plan, entry, observed)

    def test_counter_corruption_retains_persisted_xp_but_cannot_claim_a_noop(self):
        plan = self.plan(models=[experiment.MODELS[0]])
        entry = plan["entries"][0]
        folder, refs, _ = self.actual_bundle(plan, entry, delta=50)
        observed = experiment.inspect_attempt(plan, entry)
        result = json.loads((folder / refs["result"]["path"]).read_text())
        result["program"]["steps"] = [{"kind": "sdk_error", "method": "pressKeys", "outcome": "uncertain"}]
        write_artifact(folder, refs, "result", result)
        observed["journal"]["receipts"]["collect_final"]["artifacts"] = refs
        value = experiment.verified_metrics(plan, entry, observed)
        self.assertEqual(value["net_xp"], 50)
        self.assertIsNone(value["actions"])
        self.assertIsNone(value["no_op"])

    def test_actual_bundle_binds_provider_usage_and_docker_endpoint(self):
        plan = self.plan(models=[experiment.MODELS[0]])
        entry = plan["entries"][0]
        folder, refs, _ = self.actual_bundle(plan, entry)
        observed = experiment.inspect_attempt(plan, entry)
        result = json.loads((folder / refs["result"]["path"]).read_text())
        for change in ("docker", "usage"):
            altered = copy.deepcopy(result)
            if change == "docker":
                altered["controller"]["dockerBinding"]["socket_path"] = "/different/socket"
            else:
                altered["api"]["usage"]["total_tokens"] = 101
            write_artifact(folder, refs, "result", altered)
            observed["journal"]["receipts"]["collect_final"]["artifacts"] = refs
            with self.assertRaises(experiment.ExperimentError):
                experiment.verified_metrics(plan, entry, observed)

    def malformed_bundle_report(self, mutate):
        # Real hashes and persistence verification: only the affected attempt's
        # JSON shape is malformed, not an injected metrics implementation.
        self.root = Path(tempfile.mkdtemp(prefix="report-case-", dir=self.root)).resolve()
        plan = self.plan(models=[experiment.MODELS[0]], repetitions=4)
        def launch(plan, entry, request_path, timeout):
            if entry["ordinal"] == 2:
                raise RuntimeError("synthetic child did not publish an attempt")
            folder, refs, journal = self.actual_bundle(plan, entry, delta=-25 if entry["ordinal"] == 0 else 50)
            if entry["ordinal"] == 1:
                journal = mutate(folder, refs, journal)
                (folder / "journal.json").write_bytes(experiment.encoded(journal))
            return 0
        coordinator = experiment.Experiment(plan, self.root / "experiment", launcher=launch,
            verify=lambda _: None, wall_time=self.clock, monotonic=self.clock)
        with self.assertRaises((RuntimeError, experiment.ExperimentError)):
            coordinator.run()
        value = experiment.report(plan, self.root / "experiment")
        self.assertEqual(len(value["attempts"]), 4)
        self.assertEqual(value["attempts"][0]["status"], "completed")
        self.assertEqual(value["attempts"][0]["metrics"]["net_xp"], -25)
        self.assertTrue(value["attempts"][0]["metrics"]["no_op"])
        self.assertEqual(value["attempts"][1]["status"], "invalid_receipts")
        self.assertIsNone(value["attempts"][1]["metrics"])
        self.assertEqual(value["groups"][0]["planned_n"], 4)
        self.assertEqual(value["groups"][0]["verified_n"], 1)
        self.assertEqual(value["groups"][0]["net_xp"]["mean"], -25)
        self.assertFalse(value["ranked"])
        self.assertNotIn("private-report-content", json.dumps(value))
        return value

    def test_malformed_hashed_artifact_shapes_preserve_the_complete_report(self):
        cases = [(name, None) for name in ("persistence", "score", "result", "api_request", "api_response")]
        cases += [("result", field) for field in ("controller", "api", "program")]
        cases += [(name, "metadata") for name in ("api_request", "api_response")]
        for name, field in cases:
            with self.subTest(artifact=name, field=field):
                def mutate(folder, refs, journal):
                    value = ["private-report-content"]
                    if field is not None:
                        value = json.loads((folder / refs[name]["path"]).read_text())
                        value[field] = ["private-report-content"]
                    write_artifact(folder, refs, name, value)
                    return journal
                value = self.malformed_bundle_report(mutate)
                self.assertEqual([row["status"] for row in value["attempts"]],
                    ["completed", "invalid_receipts", "submitted_unresolved", "unsubmitted"])

    def test_malformed_terminal_journal_envelopes_preserve_other_attempts(self):
        for field in ("journal", "backend", "receipts", "status", "collect_final"):
            with self.subTest(field=field):
                def mutate(folder, refs, journal):
                    bad = ["private-report-content"]
                    if field == "journal":
                        return bad
                    if field == "backend":
                        (folder / "backend-state.json").write_bytes(experiment.encoded(bad))
                    elif field == "receipts":
                        journal["receipts"] = bad
                    else:
                        journal["receipts"][field] = bad
                    return journal
                self.malformed_bundle_report(mutate)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux production launcher")
    def test_actual_stdlib_child_gets_exact_argv_and_minimal_environment(self):
        plan = self.plan(models=[experiment.MODELS[0]])
        entry = plan["entries"][0]
        script = self.root / "child.py"
        script.write_text("import json,os,pathlib,sys\n"
            "root=pathlib.Path(sys.argv[sys.argv.index('--state-root')+1])\n"
            "(root/'child.json').write_text(json.dumps({'argv':sys.argv[1:],'env':dict(os.environ),'cwd':os.getcwd()}))\n")
        altered = copy.deepcopy(plan)
        altered["runner"]["trial_script"] = experiment.pin(script)
        request = self.root / "request.json"
        request.write_bytes(experiment.encoded(entry["spec"]))
        with patch.object(experiment.sys, "platform", "linux"), patch.object(experiment.os, "geteuid", return_value=0), \
                patch.dict(os.environ, {"EXPERIMENT_PRIVATE_MARKER": "must-not-inherit", "DOCKER_HOST": "invalid"}):
            result = experiment.launch_trial(altered, entry, request, 5)
        self.assertEqual(result, 0)
        child = json.loads((self.attempts / "child.json").read_text())
        self.assertEqual(child["argv"], ["--adapter-config", plan["fixtures"][0]["adapter_config"]["path"],
            "--state-root", str(self.attempts), "--world-lock", plan["runner"]["world_lock"],
            "--queue-lock", plan["runner"]["queue_lock"], "run", "--request", str(request),
            "--attempt-id", entry["attempt_id"]])
        self.assertNotIn("EXPERIMENT_PRIVATE_MARKER", child["env"])
        self.assertNotIn("DOCKER_HOST", child["env"])
        self.assertEqual(child["cwd"], "/")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux production launcher")
    def test_child_timeout_is_bounded_and_cli_does_not_echo_private_errors(self):
        plan = self.plan(models=[experiment.MODELS[0]])
        script = self.root / "sleep.py"
        script.write_text("import time\ntime.sleep(30)\n")
        altered = copy.deepcopy(plan)
        altered["runner"]["trial_script"] = experiment.pin(script)
        with patch.object(experiment.sys, "platform", "linux"), patch.object(experiment.os, "geteuid", return_value=0):
            with self.assertRaises(subprocess.TimeoutExpired):
                experiment.launch_trial(altered, plan["entries"][0], self.root / "unused.json", .1)
        path = self.root / "bad.json"
        path.write_text('{"private":"secret-marker",')
        path.chmod(0o600)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = experiment.main(["plan", "--config", str(path), "--output", str(self.root / "none.json")])
        self.assertEqual(status, 1)
        self.assertNotIn("secret-marker", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["code"], "invalid_json")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux parent-death signal")
    def test_killed_coordinator_cannot_leave_detached_runner_alive(self):
        plan = self.plan(models=[experiment.MODELS[0]])
        script = self.root / "child-wait.py"
        script.write_text("import os,pathlib,sys,time\n"
            "root=pathlib.Path(sys.argv[sys.argv.index('--state-root')+1])\n"
            "(root/'child-pid').write_text(str(os.getpid()))\n"
            "time.sleep(30)\n")
        plan["runner"]["trial_script"] = experiment.pin(script)
        plan_path = self.root / "synthetic-launch.json"
        plan_path.write_bytes(experiment.encoded(plan))
        parent_script = self.root / "parent.py"
        parent_script.write_text("import json,pathlib,sys\n"
            f"sys.path.insert(0,{str(Path(experiment.__file__).parent)!r})\n"
            "import full_client_experiment as e\n"
            "e.os.geteuid=lambda:0\n"
            "p=json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
            "e.launch_trial(p,p['entries'][0],pathlib.Path(sys.argv[1]),20)\n")
        parent = subprocess.Popen([str(Path(sys.executable).resolve()), str(parent_script), str(plan_path)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pid = None
        try:
            until = time.monotonic() + 5
            marker = self.attempts / "child-pid"
            while not marker.exists() and time.monotonic() < until:
                time.sleep(.02)
            self.assertTrue(marker.exists(), "synthetic child did not start")
            pid = int(marker.read_text())
            parent.kill()
            parent.wait(timeout=3)
            while time.monotonic() < until:
                proc = Path(f"/proc/{pid}/stat")
                try:
                    if not proc.exists() or proc.read_text().rsplit(")", 1)[1].split()[0] == "Z":
                        break
                except (FileNotFoundError, ProcessLookupError):
                    break
                time.sleep(.02)
            else:
                self.fail("synthetic runner survived parent death")
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=3)
            if pid is not None and Path(f"/proc/{pid}/stat").exists():
                try:
                    os.kill(pid, 15)
                except ProcessLookupError:
                    pass


if __name__ == "__main__":
    unittest.main()
