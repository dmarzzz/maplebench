"""Finite full-client group -> sealed evidence -> verified normal services.

The immutable ``finite_group`` authority subject has exactly: schema_version,
plan, experiment_directory, normal_config, historical_attempts, initial_snapshot,
output_directory, restoration_operation_id, limits. Limits contain admission,
handoff, restoration and total seconds, memory_bytes, cpu_seconds and cpus.
Total seconds equals admission + the plan's aggregate wall + handoff + restoration.

Only the operations gate is held during experiment execution. Existing lifecycle
serialization/world locks protect handoff preparation and are closed before the
normal lifecycle starts. Reconciliation never resumes a group or recovers a trial.
A recovered last attempt without a verified persisted final artifact remains an
external restoration-only reconciliation requirement. Deadlines never renew.

Private authorities/collector artifacts are trusted operator inputs, not signed
publication evidence. Reports cover every declared entry and remain unranked.
This module does not provision, pause services, rewrite trials, or grant recovery
time. Injectable factories are for offline tests; the defaults compose the real
coordinator, admission, handoff and native lifecycle implementations.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
from dataclasses import dataclass
import hashlib
import itertools
import os
from pathlib import Path
import re
import resource
import signal
import stat
import sys
import time

import full_client_experiment as experiment
import full_client_lifecycle as native
import full_client_operation_admission as access
import full_client_operations_handoff as handoff

PHASES = ("admitted", "experiment_running", "seal_intent", "group_sealed", "handoff_intent",
          "handoff_prepared", "restoration_intent", "normal_restoring", "normal_verified", "completed")
SUBJECT_FIELDS = {"schema_version", "plan", "experiment_directory", "normal_config", "historical_attempts",
                  "initial_snapshot", "output_directory", "restoration_operation_id", "limits"}
LIMIT_FIELDS = {"admission_seconds", "handoff_seconds", "restoration_seconds", "total_seconds",
                "memory_bytes", "cpu_seconds", "cpus"}
STATE_FIELDS = {"schema_version", "operation_id", "authority", "claim", "boot_id", "started_at_ms",
               "updated_at_ms", "deadline_at_ms", "started_monotonic_ns", "deadline_monotonic_ns",
               "phase", "status", "coordinator", "attempts", "expected_snapshot", "group_report",
               "handoff", "lifecycle", "normal_verification", "restoration_deadline_at_ms",
               "restoration_deadline_monotonic_ns", "failure", "events"}
REQUIRED_SOURCES = tuple(str(Path(module.__file__).resolve()) for module in
    (sys.modules[__name__], experiment, native, handoff, native.full_client_trial,
     native.full_client_collect, native.full_client_score, native.full_client_freeze,
     native.full_client_docker, experiment.readiness))


class OperationsError(ValueError):
    """Fixed codes only; never expose raw runtime data."""


def require(value, code):
    if not value:
        raise OperationsError(code)


def fields(value, expected, code):
    require(isinstance(value, dict) and set(value) == set(expected), code)


def integer(value, low, high=2**53 - 1):
    return type(value) is int and low <= value <= high


def read_ref(ref, uid=0):
    return access.gate.read_ref(ref, uid, access.gate.Budget())


def actual_ref(path, uid=0):
    return access.private_ref(path, owner_uid=uid)[1]


def write_new(path, value, uid):
    access.gate.directory(path.parent, uid)
    experiment.write_json(path, value, create=True)
    return actual_ref(path, uid)


def path(value):
    return native.absolute(value)


def snapshot(value, config):
    require(isinstance(value, dict) and type(value.get("schema_version")) is int and value["schema_version"] == 1
            and value.get("source") == "cosmic_persisted_character"
            and type(value.get("account_logged_in")) is int and value["account_logged_in"] == 0
            and isinstance(value.get("character"), dict) and isinstance(value.get("keymap"), list),
            "persisted_snapshot_invalid")
    for key in ("character_id", "account_id"):
        require(type(value["character"].get(key)) is int
                and value["character"][key] == config["mysql"][key], "persisted_snapshot_identity_changed")
    return value


def clean_attempt(row, attempt_root, uid):
    fields(row, ("id", "journal", "backend"), "invalid_attempt_reference")
    require(isinstance(row["id"], str) and native.ID.fullmatch(row["id"]), "invalid_attempt_reference")
    directory = path(attempt_root) / row["id"]
    require(row["journal"]["path"] == str(directory / "journal.json")
            and row["backend"]["path"] == str(directory / "backend-state.json"), "attempt_reference_outside_root")
    journal, backend = read_ref(row["journal"], uid), read_ref(row["backend"], uid)
    receipts = journal.get("receipts")
    require(isinstance(receipts, dict) and isinstance(receipts.get("status"), dict), "attempt_final_status_missing")
    final = receipts["status"]
    require(journal.get("attempt_id") == backend.get("attempt_id") == row["id"]
            and journal.get("status") in ("completed", "recovered") and journal.get("pending") is None
            and journal.get("phase") == "status" and journal.get("phase_status") == "returned"
            and receipts.get("cleanup") == {"attempt_id": row["id"], "clean": True} and backend.get("clean") is True
            and all(final.get(key) is True for key in native.full_client_trial.STATUS_FIELDS if key != "ownership_conflict")
            and final.get("ownership_conflict") is False, "attempt_not_terminal_clean")
    return journal, backend


def inventory(rows, attempt_root, uid):
    require(isinstance(rows, list) and 1 <= len(rows) <= 4096, "attempt_inventory_invalid")
    expected = set()
    for row in rows:
        clean_attempt(row, attempt_root, uid)
        require(row["id"] not in expected, "duplicate_attempt_reference")
        expected.add(row["id"])
    actual = set()
    with os.scandir(attempt_root) as entries:
        for index, entry in enumerate(itertools.islice(entries, 8193), 1):
            require(index <= 8192, "attempt_inventory_limit")
            if not entry.name.startswith("."):
                actual.add(entry.name)
    require(actual == expected, "attempt_inventory_changed")


def validate_subject(subject, uid=0):
    fields(subject, SUBJECT_FIELDS, "invalid_finite_group_subject")
    require(type(subject["schema_version"]) is int and subject["schema_version"] == 1,
            "invalid_finite_group_subject")
    plan = experiment.validate_plan(read_ref(subject["plan"], uid))
    config = native.validate_config(read_ref(subject["normal_config"], uid))
    require(subject["plan"]["sha256"] == experiment.digest(plan), "plan_byte_binding_changed")
    runner = plan["runner"]
    require(runner["state_root"] == config["attempt_root"]
            and all(runner[key + "_lock"] == config["locks"][key]["path"] for key in ("world", "queue"))
            and config["locks"]["runner"]["path"] == str(path(config["attempt_root"]) / ".runner.lock"),
            "normal_world_binding_changed")
    for pin in config["locks"].values():
        info = path(pin["path"]).lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and (info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode)) ==
                    (pin["device"], pin["inode"], pin["uid"], pin["mode"]), "normal_world_lock_identity_changed")
    for key in ("experiment_directory", "output_directory"):
        target = path(subject[key])
        access.gate.directory(target.parent, uid)
        require(not target.is_relative_to(path(config["attempt_root"]))
                and not target.is_relative_to(path(config["state_root"])), "operations_directory_outside_inventory_required")
    first, second = (path(subject[key]) for key in ("experiment_directory", "output_directory"))
    require(first != second and not first.is_relative_to(second) and not second.is_relative_to(first),
            "distinct_operations_directories_required")
    ident = subject["restoration_operation_id"]
    require(isinstance(ident, str) and native.ID.fullmatch(ident), "invalid_restoration_id")
    snapshot(read_ref(subject["initial_snapshot"], uid), config)
    rows = subject["historical_attempts"]
    require(isinstance(rows, list) and 1 <= len(rows) <= 128, "historical_inventory_limit")
    ids = set()
    for row in rows:
        clean_attempt(row, config["attempt_root"], uid)
        require(row["id"] not in ids, "duplicate_attempt_reference")
        ids.add(row["id"])
    require(not ids.intersection(entry["attempt_id"] for entry in plan["entries"]), "planned_attempt_is_historical")
    # Every fixture must restore the same service world and account. No commands
    # are executed: the existing adapter has a strict --config file contract.
    for fixture in plan["fixtures"]:
        adapter = read_ref(fixture["adapter_config"], uid)
        argv = adapter.get("argv")
        require(isinstance(argv, list) and len(argv) == 4 and argv[2] == "--config", "unsupported_backend_launch")
        backend, _ = access.private_ref(argv[3], owner_uid=uid)
        require(backend.get("attempt_root") == config["attempt_root"]
                and backend.get("admin_socket") == config["admin_socket"]
                and backend.get("queue_database") == config["queue_database"]
                and all(backend.get("services", {}).get(role) == (config["services"][role] if role == "world"
                        else config["services"][role]["unit"]) for role in ("cosmic", "worker", "world"))
                and all(backend.get("mysql", {}).get(key) == config["mysql"][key]
                        for key in ("database", "character_id", "account_id"))
                and all(backend.get(key + "_lock") == config["locks"][key]["path"] for key in ("world", "queue")),
                "fixture_restoration_world_mismatch")
    limits = subject["limits"]
    fields(limits, LIMIT_FIELDS, "invalid_operations_limits")
    for key, low, high in (("admission_seconds", 1, 120), ("handoff_seconds", 1, 120),
                          ("restoration_seconds", config["limits"]["total_seconds"], 1800),
                          ("memory_bytes", config["limits"]["memory_bytes"], 768 * 1024**2),
                          ("cpu_seconds", config["limits"]["cpu_seconds"], 3600),
                          ("cpus", config["limits"]["cpus"], 2)):
        require(integer(limits[key], low, high), "invalid_operations_limits")
    expected = sum(limits[key] for key in ("admission_seconds", "handoff_seconds", "restoration_seconds")) + plan["aggregate_limits"]["wall_seconds"]
    require(type(limits["total_seconds"]) is int and limits["total_seconds"] == expected, "outer_deadline_reserve_mismatch")
    return copy.deepcopy(subject), plan, config


class BoundLifecycle(native.NormalLifecycle):
    def __init__(self, *args, deadline, **kwargs):
        super().__init__(*args, **kwargs)
        self.operations_deadline = deadline

    def begin_deadline(self):
        remaining = self.operations_deadline()
        native.require(remaining > 0, "operations_deadline_exceeded")
        self.host.deadline = time.monotonic() + min(remaining, self.config["limits"]["total_seconds"])
        self.host.command_seconds = self.config["limits"]["command_seconds"]


def lifecycle_factory(config, ref, deadline, uid):
    return BoundLifecycle(config, ref, deadline=deadline, owner_uid=uid)


@dataclass
class Factories:
    lifecycle: object = lifecycle_factory
    admitted: object = access.admitted
    dispatch: object = access.trial_dispatch
    launch: object = access.current_launch
    handoff: object = handoff.prepare_handoff
    verify_inputs: object = experiment.verify_inputs
    inspector: object = experiment.inspect_attempt
    report: object = experiment.report
    experiment: object = experiment.Experiment


class Operations:
    def __init__(self, authority_ref, *, factories=None, owner_uid=0, wall=time.time, monotonic=time.monotonic,
                 boot=None):
        self.ref, self.uid = copy.deepcopy(authority_ref), owner_uid
        self.factories = factories or Factories()
        self.wall, self.monotonic = wall, monotonic
        self.boot = boot or (lambda: Path("/proc/sys/kernel/random/boot_id").read_text().strip())
        self.authority = read_ref(self.ref, owner_uid)
        self.subject, self.plan, self.config = validate_subject(self.authority.get("subject"), owner_uid)
        require(self.authority.get("kind") == "finite_group" and self.authority.get("operation_id") != self.subject["restoration_operation_id"],
                "finite_group_authority_required")
        self.directory = path(self.subject["output_directory"])
        self.journal_path = self.directory / "journal.json"
        self.state = self.state_ref = None
        self.stage_deadline = None

    def now(self):
        now = round(self.wall() * 1000)
        require(integer(now, 1) and (self.state is None or now >= self.state["updated_at_ms"]), "operations_clock_moved_backwards")
        return now

    def remaining(self):
        require(self.state is not None and self.boot() == self.state["boot_id"], "operations_boot_changed")
        left = min((self.state["deadline_at_ms"] - self.now()) / 1000,
                   self.state["deadline_monotonic_ns"] / 1e9 - self.monotonic())
        if self.stage_deadline is not None:
            left = min(left, self.stage_deadline - self.monotonic())
        require(left > 0, "operations_deadline_exceeded")
        return left

    def persist(self, phase, **values):
        require(phase in PHASES, "invalid_operations_phase")
        if self.state_ref is not None:
            read_ref(self.state_ref, self.uid)
        self.state.update(values, phase=phase, updated_at_ms=self.now())
        require(len(self.state["events"]) < 1000, "operations_event_limit")
        self.state["events"].append({"sequence": len(self.state["events"]), "at_ms": self.state["updated_at_ms"], "phase": phase})
        if self.state_ref is None:
            self.state_ref = write_new(self.journal_path, self.state, self.uid)
        else:
            native.atomic_json(self.journal_path, self.state)
            self.state_ref = actual_ref(self.journal_path, self.uid)
        require(read_ref(self.state_ref, self.uid) == self.state, "operations_journal_changed")

    def load(self, ref):
        require(ref["path"] == str(self.journal_path), "operations_journal_outside_directory")
        value = read_ref(ref, self.uid)
        fields(value, STATE_FIELDS, "invalid_operations_journal")
        require(type(value["schema_version"]) is int and value["schema_version"] == 1
                and isinstance(value["boot_id"], str) and native.BOOT.fullmatch(value["boot_id"])
                and value["operation_id"] == self.authority["operation_id"]
                and value["authority"] == self.ref and value["phase"] in PHASES
                and value["status"] in ("pending", "needs_reconciliation", "completed")
                and integer(value["started_at_ms"], 1) and integer(value["updated_at_ms"], value["started_at_ms"])
                and integer(value["deadline_at_ms"], value["started_at_ms"])
                and value["deadline_at_ms"] == value["started_at_ms"] + self.subject["limits"]["total_seconds"] * 1000
                and integer(value["started_monotonic_ns"], 0, 2**63 - 1)
                and integer(value["deadline_monotonic_ns"], value["started_monotonic_ns"], 2**63 - 1)
                and value["deadline_monotonic_ns"] == value["started_monotonic_ns"] + self.subject["limits"]["total_seconds"] * 10**9,
                "operations_identity_or_deadline_changed")
        events = value["events"]
        require(isinstance(events, list) and 1 <= len(events) <= 1000
                and all(isinstance(event, dict) and set(event) == {"sequence", "at_ms", "phase"}
                        and type(event["sequence"]) is int and event["sequence"] == index
                        and event["phase"] in PHASES and integer(event["at_ms"], value["started_at_ms"], value["updated_at_ms"])
                        for index, event in enumerate(events)), "operations_events_invalid")
        require(events[0]["phase"] == "admitted"
                and events[-1]["phase"] == value["phase"] and events[-1]["at_ms"] == value["updated_at_ms"]
                and all(previous["at_ms"] <= current["at_ms"]
                        and PHASES.index(previous["phase"]) <= PHASES.index(current["phase"])
                        for previous, current in zip(events, events[1:])), "operations_event_order_changed")
        require((value["status"] == "completed") == (value["phase"] == "completed"),
                "operations_terminal_state_changed")
        access.gate.reference(value["claim"])
        phase = PHASES.index(value["phase"])
        if phase >= PHASES.index("group_sealed"):
            for name in ("coordinator", "expected_snapshot", "group_report"):
                access.gate.reference(value[name])
            require(isinstance(value["attempts"], list) and value["attempts"], "operations_attempt_evidence_missing")
        if phase >= PHASES.index("handoff_prepared"):
            fields(value["handoff"], ("handoff", "preparation", "offline_snapshot"), "operations_handoff_evidence_missing")
            for reference_value in value["handoff"].values():access.gate.reference(reference_value)
        restoring = phase >= PHASES.index("restoration_intent")
        if restoring:
            intents = [event for event in events if event["phase"] == "restoration_intent"]
            require(intents and integer(value["restoration_deadline_at_ms"], value["started_at_ms"],
                    min(value["deadline_at_ms"], intents[0]["at_ms"] + self.subject["limits"]["restoration_seconds"] * 1000))
                    and integer(value["restoration_deadline_monotonic_ns"], value["started_monotonic_ns"],
                                value["deadline_monotonic_ns"]), "operations_restoration_deadline_changed")
        else:
            require(value["restoration_deadline_at_ms"] is None and value["restoration_deadline_monotonic_ns"] is None,
                    "operations_restoration_intent_missing")
        if phase >= PHASES.index("normal_verified"):
            access.gate.reference(value["lifecycle"]); access.gate.reference(value["normal_verification"])
        self.state, self.state_ref = value, copy.deepcopy(ref)

    def admission(self, claim=None):
        return self.factories.admitted(self.ref, self.subject, "finite_group", self.config["attempt_root"],
            claim_ref=claim, owner_uid=self.uid, required_sources=REQUIRED_SOURCES)

    def coordinator(self, admission=None):
        kwargs = {}
        if admission is not None:
            launch = self.factories.launch(self.authority["source_files"], executable_ref=self.plan["runner"]["python"])
            require(launch["script"]["path"] == str(Path(__file__).resolve()), "operations_parent_script_changed")
            kwargs["entry_admission"] = self.factories.dispatch(admission, self.subject["plan"], launch)
        return self.factories.experiment(self.plan, self.subject["experiment_directory"], **kwargs)

    def fail(self, error):
        if self.state is None or self.state_ref is None or self.state["status"] == "completed":
            return
        code = str(error) if isinstance(error, (OperationsError, experiment.ExperimentError, native.LifecycleError, access.AdmissionError)) else "operations_phase_failed"
        if not re.fullmatch(r"[a-z_]{1,100}", code):
            code = "operations_phase_failed"
        try:
            self.persist(self.state["phase"], status="needs_reconciliation", failure={"phase": self.state["phase"], "code": code})
        except (OSError, ValueError, RuntimeError):
            pass  # Never overwrite changed ownership or replace the original error.

    def run(self):
        require(not os.path.lexists(self.directory) and not os.path.lexists(self.subject["experiment_directory"])
                and not os.path.lexists(path(self.config["state_root"]) / self.subject["restoration_operation_id"]),
                "operations_create_only")
        started, mono = self.now(), round(self.monotonic() * 1e9)
        with self.admission() as admitted:
            require(not admitted.completed, "operations_already_completed")
            self.directory.mkdir(mode=0o700); native.sync_directory(self.directory.parent)
            total = self.subject["limits"]["total_seconds"]
            self.state = {"schema_version": 1, "operation_id": self.authority["operation_id"], "authority": self.ref,
                "claim": admitted.claim, "boot_id": self.boot(), "started_at_ms": started, "updated_at_ms": started,
                "deadline_at_ms": started + total * 1000, "started_monotonic_ns": mono,
                "deadline_monotonic_ns": mono + total * 10**9, "phase": "admitted", "status": "pending",
                "coordinator": None, "attempts": None, "expected_snapshot": None, "group_report": None,
                "handoff": None, "lifecycle": None, "normal_verification": None,
                "restoration_deadline_at_ms": None, "restoration_deadline_monotonic_ns": None,
                "failure": None, "events": []}
            self.persist("admitted")
            try:
                self.stage_deadline = mono / 1e9 + self.subject["limits"]["admission_seconds"]
                self.remaining(); inventory(self.subject["historical_attempts"], self.config["attempt_root"], self.uid)
                for entry in self.plan["entries"]:
                    require(not os.path.lexists(path(self.config["attempt_root"]) / entry["attempt_id"]), "planned_attempt_already_exists")
                self.factories.verify_inputs(self.plan); self.remaining()
                # Establish a usable restoration configuration before any
                # submission, without borrowing its world locks during the group.
                probe = self.factories.lifecycle(self.config, self.subject["normal_config"], self.remaining, self.uid)
                probe.begin_deadline(); probe.verify_files(); probe.settings(); probe.require_no_pending()
                for role in ("cosmic", "worker", "world"):
                    unit = probe.unit(role)
                    require(probe.stopped(unit) and isinstance(unit.get("InvocationID"), str)
                            and native.ID.fullmatch(unit["InvocationID"]), "initial_service_not_stopped")
                probe.process_identity("web"); probe.capacity()
                initial = snapshot(probe.host.snapshot(self.config, self.authority["operation_id"]), self.config)
                expected = read_ref(self.subject["initial_snapshot"], self.uid)
                require(native.lifecycle_same_json(initial["character"], expected["character"])
                        and native.lifecycle_same_json(initial["keymap"], expected["keymap"]), "initial_persisted_snapshot_changed")
                self.remaining()
                self.stage_deadline = None
                reserve = self.plan["aggregate_limits"]["wall_seconds"] + self.subject["limits"]["handoff_seconds"] + self.subject["limits"]["restoration_seconds"]
                require(self.remaining() >= reserve, "operations_full_reserve_missing")
                self.persist("experiment_running")
                try:
                    self.coordinator(admitted).run()
                except (experiment.ExperimentError, OSError, ValueError, RuntimeError):
                    # A failed child may still have completed its real cleanup.
                    # Only fresh terminal evidence below permits restoration.
                    pass
                return self.continue_clean(admitted)
            except BaseException as error:
                self.fail(error)
                raise

    def group_evidence(self):
        coordinator_path = path(self.subject["experiment_directory"]) / "coordinator.json"
        state, ref = access.private_ref(coordinator_path, owner_uid=self.uid)
        experiment.validate_state(state, self.plan)
        rows = copy.deepcopy(self.subject["historical_attempts"])
        last = None
        for submission in state["submissions"]:
            entry = self.plan["entries"][submission["ordinal"]]
            observed = self.factories.inspector(self.plan, entry)
            if "retirement" in submission:
                require(observed["status"] == "missing" and not os.path.lexists(path(self.config["attempt_root"]) / entry["attempt_id"]),
                        "retired_attempt_appeared")
                continue
            require(observed.get("terminal_clean") is True, "submitted_attempt_unresolved")
            folder = path(self.config["attempt_root"]) / entry["attempt_id"]
            row = {"id": entry["attempt_id"], "journal": {"path": str(folder / "journal.json"), "sha256": observed["journal_sha256"]},
                   "backend": {"path": str(folder / "backend-state.json"), "sha256": observed["backend_sha256"]}}
            settled = {"status": observed["status"], "journal_sha256": observed["journal_sha256"], "backend_sha256": observed["backend_sha256"]}
            previous = state["settled"].get(entry["attempt_id"])
            require(previous is None or previous == settled, "settled_attempt_changed")
            require("closure" not in state or previous == settled, "sealed_attempt_binding_missing")
            journal, _ = clean_attempt(row, self.config["attempt_root"], self.uid)
            rows.append(row); last = (entry, journal, folder)
        inventory(rows, self.config["attempt_root"], self.uid)
        expected = copy.deepcopy(self.subject["initial_snapshot"])
        if last is not None:
            entry, journal, folder = last
            collected = journal["receipts"].get("collect_final")
            require(isinstance(collected, dict) and isinstance(collected.get("artifacts"), dict), "final_persisted_snapshot_missing")
            artifacts = collected["artifacts"]
            evidence = collected.get("evidence")
            require(isinstance(evidence, dict), "final_persisted_snapshot_missing")
            recomputed = native.full_client_score.verify_trial_bundle(evidence, folder, artifacts)
            require(recomputed.get("run_id") == entry["attempt_id"]
                    and recomputed.get("scenario_fingerprint") == entry["spec"]["scenario_fingerprint"]
                    and recomputed.get("baseline_sha256") == entry["spec"]["baseline_sha256"], "final_persistence_binding_changed")
            raw = native.full_client_score.read_artifact_bytes(folder, artifacts.get("final_db"), "final_db", maximum=native.JSON_LIMIT)
            value = snapshot(native.full_client_score.parse_json(raw), self.config)
            require(value.get("run_id") == entry["attempt_id"], "final_snapshot_attempt_changed")
            expected = {"path": str(folder / artifacts["final_db"]["path"]), "sha256": hashlib.sha256(raw).hexdigest()}
        snapshot(read_ref(expected, self.uid), self.config)
        return state, ref, rows, expected

    def seal(self):
        state, ref, rows, expected = self.group_evidence()
        if "closure" not in state:
            self.persist("seal_intent", coordinator=ref, attempts=rows, expected_snapshot=expected)
            self.coordinator().seal(ref["sha256"])
            state, ref, rows, expected = self.group_evidence()
        require(state.get("schema_version") == 2 and state.get("closure", {}).get("policy") == "permanently_withdraw_future_entries",
                "group_not_sealed")
        if self.state["phase"] == "seal_intent":
            require(state["closure"]["previous_journal_sha256"] == self.state["coordinator"]["sha256"], "group_seal_parent_changed")
        report = self.factories.report(self.plan, self.subject["experiment_directory"])
        require(report.get("scope") == "entire_declared_attempt_set" and report.get("planned") == len(self.plan["entries"])
                and report.get("sealed") is True and report.get("ranked") is False, "complete_plan_report_required")
        report_path = self.directory / "group-report.json"
        if os.path.lexists(report_path):
            saved, report_ref = access.private_ref(report_path, owner_uid=self.uid)
            require(saved == report, "group_report_changed")
        else:
            report_ref = write_new(report_path, report, self.uid)
        self.persist("group_sealed", coordinator=ref, attempts=rows, expected_snapshot=expected, group_report=report_ref)

    def handoff_refs(self, life):
        destination = self.directory / "handoff"
        if not os.path.lexists(destination):
            return self.factories.handoff(life, destination, self.subject["restoration_operation_id"], self.state["attempts"],
                                         expected_snapshot_ref=self.state["expected_snapshot"])
        require({entry.name for entry in destination.iterdir()} == {"preparation.json", "handoff.json", "offline-snapshot.json"},
                "handoff_partial_or_unexpected_output")
        refs = {key: actual_ref(destination / filename, self.uid) for key, filename in
                (("preparation", "preparation.json"), ("handoff", "handoff.json"), ("offline_snapshot", "offline-snapshot.json"))}
        prep, request = read_ref(refs["preparation"], self.uid), read_ref(refs["handoff"], self.uid)
        require(prep.get("kind") == "full_client_operations_handoff" and prep.get("operation_id") == self.subject["restoration_operation_id"]
                and prep.get("config") == self.subject["normal_config"] and prep.get("expected_snapshot") == self.state["expected_snapshot"]
                and prep.get("handoff") == refs["handoff"] and prep.get("offline_snapshot") == refs["offline_snapshot"]
                and prep.get("lifecycle_invoked") is False and request.get("attempts") == self.state["attempts"]
                and request.get("offline_snapshot") == refs["offline_snapshot"]
                and request.get("operation_id") == self.subject["restoration_operation_id"], "handoff_evidence_changed")
        life.preflight(refs["handoff"])
        return refs

    def continue_clean(self, admitted, lifecycle_ref=None, observation_ref=None):
        self.remaining()
        if PHASES.index(self.state["phase"]) <= PHASES.index("seal_intent"):
            self.seal()
        else:
            require(self.group_evidence()[1] == self.state["coordinator"], "sealed_coordinator_changed")
        life = self.factories.lifecycle(self.config, self.subject["normal_config"], self.remaining, self.uid)
        if self.state["handoff"] is None:
            require(self.remaining() >= self.subject["limits"]["restoration_seconds"], "restoration_reserve_missing")
            self.stage_deadline = min(self.monotonic() + self.subject["limits"]["handoff_seconds"],
                                      self.monotonic() + self.remaining() - self.subject["limits"]["restoration_seconds"])
            life.begin_deadline(); self.persist("handoff_intent")
            with life.serialized():
                life.require_no_pending(); life.acquire_world_locks()
                refs = self.handoff_refs(life)
            require(not life.world_fds and life.serial_fd is None, "handoff_locks_not_released")
            self.stage_deadline = None
            self.persist("handoff_prepared", handoff=refs)
        if self.state["restoration_deadline_at_ms"] is None:
            self.remaining()
            self.persist("restoration_intent", restoration_deadline_at_ms=min(self.state["deadline_at_ms"], self.now() + self.subject["limits"]["restoration_seconds"] * 1000),
                restoration_deadline_monotonic_ns=min(self.state["deadline_monotonic_ns"], round(self.monotonic() * 1e9) + self.subject["limits"]["restoration_seconds"] * 10**9))
        self.stage_deadline = min(self.state["restoration_deadline_monotonic_ns"] / 1e9,
                                  self.monotonic() + (self.state["restoration_deadline_at_ms"] - self.now()) / 1000)
        self.remaining()
        target = path(self.config["state_root"]) / self.subject["restoration_operation_id"] / "journal.json"
        if os.path.lexists(target):
            current = actual_ref(target, self.uid); value = read_ref(current, self.uid)
            if value.get("status") != "completed":
                require(lifecycle_ref == current or self.state["lifecycle"] == current, "exact_lifecycle_reconciliation_required")
                self.persist("normal_restoring", lifecycle=current)
                life.reconcile(current, observation_ref)
        else:
            require(lifecycle_ref is None and observation_ref is None and self.state["lifecycle"] is None,
                    "lifecycle_receipt_missing")
            self.persist("normal_restoring")
            life.start(self.state["handoff"]["handoff"])
        verified = self.verify_normal(life, actual_ref(target, self.uid))
        verification_path = self.directory / "normal-verification.json"
        if os.path.lexists(verification_path):
            value, verification_ref = access.private_ref(verification_path, owner_uid=self.uid)
            require(value == verified, "normal_verification_changed")
        else:
            verification_ref = write_new(verification_path, verified, self.uid)
        self.persist("normal_verified", lifecycle=verified["lifecycle"], normal_verification=verification_ref)
        self.persist("completed", status="completed", failure=None)
        admitted.finish([self.state_ref, self.state["coordinator"], self.state["group_report"],
                         self.state["handoff"]["preparation"], self.state["lifecycle"], verification_ref])
        return self.summary()

    def verify_normal(self, life, ref):
        self.remaining()
        value = read_ref(ref, self.uid)
        require(value.get("operation_id") == self.subject["restoration_operation_id"]
                and value.get("status") == "completed" and value.get("phase") == "complete"
                and value.get("config") == self.subject["normal_config"] and value.get("handoff") == self.state["handoff"]["handoff"]
                and value.get("service_starts") == {"cosmic": 1, "worker": 1}
                and value.get("new_api_requests") == 0 and value.get("database_mutations") is False, "normal_lifecycle_not_complete")
        for role in ("cosmic", "worker"):
            native.instance(value.get(role))
            require(isinstance(value.get(role + "_start"), dict), "normal_service_intent_missing")
        ready = value.get("native_ready")
        require(isinstance(ready, dict) and all(integer(ready.get(key), 0) for key in ("device", "inode", "bytes", "offset", "fd", "observed_at_ms"))
                and ready["bytes"] > ready["offset"] and set(self.config["native"]["ports"]) <= set(ready.get("ports", []))
                and all(isinstance(ready.get(key), str) and native.HEX.fullmatch(ready[key]) for key in ("log_sha256", "startup_sha256")),
                "native_readiness_receipt_missing")
        events = value.get("events")
        require(isinstance(events, list) and events and len(events) <= 4096
                and all(isinstance(event, dict) and event.get("sequence") == index for index, event in enumerate(events))
                and all(sum(event.get("phase") == phase for event in events) == 1
                        for phase in ("cosmic_start_pending", "worker_start_pending", "complete")), "normal_service_events_invalid")
        life.begin_deadline()
        with life.serialized():
            life.state, life.journal_sha, life.directory = value, ref["sha256"], Path(ref["path"]).parent
            life.load_handoff(value["handoff"]); life.verify_files(); life.same_cosmic()
            require(life.worker_idle() == value.get("first_idle"), "normal_first_idle_changed")
            # Observe the actual current process-owned descriptor/listeners; a
            # journal boolean cannot substitute for native readiness.
            life.host.native(value["cosmic"]["pid"], self.config["native"], value["preflight"]["native_boundary"], value["cosmic_start"]["intent_at_ms"])
            raw, info = native.read_file(self.config["native"]["path"], uid=self.config["services"]["cosmic"]["uid"], private=True,
                                         maximum=self.config["native"]["max_bytes"])
            require((info.st_dev, info.st_ino) == (ready["device"], ready["inode"]) and len(raw) >= ready["bytes"]
                    and hashlib.sha256(raw[:ready["bytes"]]).hexdigest() == ready["log_sha256"]
                    and hashlib.sha256(raw[ready["offset"]:ready["bytes"]]).hexdigest() == ready["startup_sha256"], "native_receipt_bytes_changed")
            life.quiet(worker_stopped=False); require(life.worker_idle() == value["first_idle"], "normal_first_idle_changed")
        require(read_ref(ref, self.uid) == value, "normal_lifecycle_journal_changed")
        return {"schema_version": 1, "kind": "finite_group_normal_verified", "operation_id": self.authority["operation_id"],
                "lifecycle": ref, "handoff": value["handoff"], "cosmic": value["cosmic"], "worker": value["worker"],
                "first_idle": value["first_idle"], "native_ready": ready, "group_sealed": self.state["coordinator"],
                "normal_restored": True, "ranked": False}

    def reconcile(self, journal_ref, *, lifecycle_ref=None, observation_ref=None):
        self.load(journal_ref)
        with self.admission(self.state["claim"]) as admitted:
            if admitted.completed:
                require(self.state["status"] == "completed" and self.state["phase"] == "completed", "terminal_claim_state_mismatch")
                return self.summary()
            try:
                if self.state["status"] == "completed":
                    # The terminal marker may have been lost after the complete
                    # wrapper journal was fsynced. Keep those exact evidence
                    # bytes so Admission.finish's deterministic receipt can be
                    # reconciled; never rewrite completion or rerun lifecycle.
                    life = self.factories.lifecycle(self.config, self.subject["normal_config"], self.remaining, self.uid)
                    verified = self.verify_normal(life, self.state["lifecycle"])
                    require(read_ref(self.state["normal_verification"], self.uid) == verified, "normal_verification_changed")
                    admitted.finish([self.state_ref, self.state["coordinator"], self.state["group_report"],
                                     self.state["handoff"]["preparation"], self.state["lifecycle"], self.state["normal_verification"]])
                    return self.summary()
                return self.continue_clean(admitted, lifecycle_ref, observation_ref)
            except BaseException as error:
                self.fail(error)
                raise

    def summary(self):
        return {"schema_version": 1, "operation_id": self.authority["operation_id"], "status": self.state["status"],
                "phase": self.state["phase"], "journal": self.state_ref, "normal_restored": self.state["status"] == "completed",
                "group_report": self.state["group_report"], "lifecycle": self.state["lifecycle"], "ranked": False,
                "automatic_trial_recovery": False}


def report(journal_ref, *, owner_uid=0):
    value = read_ref(journal_ref, owner_uid)
    require(isinstance(value.get("authority"), dict), "invalid_operations_journal")
    wrapper = Operations(value["authority"], owner_uid=owner_uid)
    wrapper.load(journal_ref)
    summary = wrapper.summary()
    summary["group"] = experiment.report(wrapper.plan, wrapper.subject["experiment_directory"])
    summary["normal_status_scope"] = "stored_verified_receipt_not_current_health"
    if value["normal_verification"] is not None:
        verified = read_ref(value["normal_verification"], owner_uid)
        require(verified.get("lifecycle") == value["lifecycle"] and verified.get("operation_id") == value["operation_id"],
                "normal_verification_changed")
        read_ref(value["lifecycle"], owner_uid)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("run", "reconcile", "report"))
    parser.add_argument("--authority"); parser.add_argument("--journal"); parser.add_argument("--sha256", required=True)
    parser.add_argument("--lifecycle-journal"); parser.add_argument("--lifecycle-sha256")
    parser.add_argument("--instance-observation"); parser.add_argument("--instance-sha256")
    args = parser.parse_args(argv)
    if args.operation == "report":
        require(args.journal and not args.authority, "report_journal_required")
        return report({"path": args.journal, "sha256": args.sha256})
    require(sys.platform.startswith("linux") and os.geteuid() == 0, "linux_root_required")
    require((args.operation == "run" and args.authority and not args.journal)
            or (args.operation == "reconcile" and args.journal and not args.authority), "operations_reference_required")
    journal_ref = {"path": args.journal, "sha256": args.sha256} if args.journal else None
    authority_ref = read_ref(journal_ref)["authority"] if journal_ref else {"path": args.authority, "sha256": args.sha256}
    wrapper = Operations(authority_ref)
    limits = wrapper.subject["limits"]
    for kind, cap in ((resource.RLIMIT_AS, limits["memory_bytes"]), (resource.RLIMIT_CPU, limits["cpu_seconds"])):
        soft, hard = resource.getrlimit(kind)
        bound = min([cap, *(item for item in (soft, hard) if item != resource.RLIM_INFINITY)])
        resource.setrlimit(kind, (bound, bound))
    os.sched_setaffinity(0, set(sorted(os.sched_getaffinity(0))[:limits["cpus"]]))
    def expired(*_):
        raise OperationsError("operations_deadline_exceeded")
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(limits["total_seconds"])
    try:
        optional = []
        for filename, digest in ((args.lifecycle_journal, args.lifecycle_sha256), (args.instance_observation, args.instance_sha256)):
            require((filename is None) == (digest is None), "reconciliation_reference_hash_required")
            optional.append({"path": filename, "sha256": digest} if filename else None)
        if args.operation == "run":
            require(not any(optional), "initial_reconciliation_arguments_forbidden")
            return wrapper.run()
        return wrapper.reconcile(journal_ref, lifecycle_ref=optional[0], observation_ref=optional[1])
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    import json
    try:
        print(json.dumps(main(), sort_keys=True, allow_nan=False))
    except Exception as error:
        code = str(error) if isinstance(error, (OperationsError, access.AdmissionError, native.LifecycleError, experiment.ExperimentError)) else "operations_failed_review_required"
        if not re.fullmatch(r"[a-z_]{1,100}", code):
            code = "operations_failed_review_required"
        print(json.dumps({"status": "refused", "error": code, "automatic_retry": False}))
        raise SystemExit(1)
