"""Shared production CLI admission before trial or lifecycle world locks.

The authority is a private, immutable JSON object with exact keys:
schema_version, operation_id, kind, gate, subject, source_files. Each integrating
command derives and validates its subject from its actual inputs. This module
checks private references, loaded source pins and the durable operations gate;
it does not infer terminal game/service semantics from a receipt's boolean.

Only an explicit same-claim reconciliation can enter a pending operation.
Completed claims return their original terminal reference without invoking the
operation again. Exceptions leave the claim pending. Library callers that own a
local admission may compose trusted runner/lifecycle objects in process; raw CLI
children must use full_client_operation_join before acquiring world locks.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import os
from pathlib import Path
import stat
import sys

import full_client_operation_gate as gate
import full_client_operation_join as join


class AdmissionError(gate.GateError):
    """Fixed failure codes only; never include private paths or input contents."""


def need(value, code):
    if not value:
        raise AdmissionError(code)


def private_ref(path, *, owner_uid=0):
    """Read actual bytes once, returning the parsed object and exact reference."""
    return gate.read_json(path, owner_uid, gate.Budget(), maximum=gate.MAX_REFERENCE)


def source_ref(path, *, owner_uid=0):
    path = gate.canonical(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_uid in (0, owner_uid)
             and before.st_nlink == 1 and not before.st_mode & 0o022
             and 0 < before.st_size <= join.MAX_SOURCE, "operation_source_unprotected")
        budget = gate.Budget()
        budget.reserve(before.st_size)
        digest, count = hashlib.sha256(), 0
        while count <= before.st_size:
            budget.check()
            block = os.read(fd, min(65536, before.st_size + 1 - count))
            if not block:
                break
            count += len(block)
            digest.update(block)
        need(count == before.st_size and gate.stamp(before) == gate.stamp(os.fstat(fd))
             == gate.stamp(path.lstat()), "operation_source_changed")
        return {"path": str(path), "sha256": digest.hexdigest()}
    finally:
        os.close(fd)


def validate_authority(authority_ref, expected_subject, kind, attempt_root, *,
                       owner_uid=0, required_sources=()):
    need(owner_uid == os.geteuid() and type(owner_uid) is int, "operation_owner_mismatch")
    budget = gate.Budget()
    value = gate.read_ref(authority_ref, owner_uid, budget)
    gate.fields(value, ("schema_version", "operation_id", "kind", "gate", "subject", "source_files"),
                "invalid_operation_authority")
    need(type(value["schema_version"]) is int and value["schema_version"] == 1
         and isinstance(value["operation_id"], str) and gate.ID.fullmatch(value["operation_id"])
         and value["kind"] == kind and kind in gate.KINDS
         and isinstance(value["subject"], dict) and isinstance(expected_subject, dict)
         and gate.encoded(value["subject"]) == gate.encoded(expected_subject), "operation_subject_mismatch")
    # Constructing a gate validates its derived namespace and pinned inode; it
    # never creates a registry or silently substitutes another path.
    gate.OperationGate(attempt_root, value["gate"], owner_uid=owner_uid)
    sources = value["source_files"]
    need(isinstance(sources, list) and 3 <= len(sources) <= 64, "operation_source_pins_required")
    paths = set()
    required = {str(Path(module.__file__).resolve()) for module in (gate, join)}
    required.add(str(Path(__file__).resolve()))
    required.update(str(Path(path).resolve()) for path in required_sources)
    for ref in sources:
        gate.reference(ref)
        need(ref["path"] not in paths, "operation_duplicate_source")
        paths.add(ref["path"])
        # Keep an aggregate bound in addition to the per-file verifier.
        budget.reserve(Path(ref["path"]).stat().st_size)
        need(source_ref(ref["path"], owner_uid=owner_uid) == ref, "operation_source_changed")
    need(required <= paths, "operation_source_pins_missing")
    return value


def private_child(parent, name, uid):
    """Create or verify only a deterministic private directory, then fsync parent."""
    gate.directory(parent, uid)
    path = parent / name
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    gate.directory(path, uid)
    fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return path


class Admission:
    def __init__(self, authority_ref, authority, lease, claim, completed, terminal, uid):
        self.authority_ref, self.authority = copy.deepcopy(authority_ref), copy.deepcopy(authority)
        self.lease, self.claim, self.completed, self.terminal = lease, claim, completed, terminal
        self.uid = uid

    def finish(self, evidence):
        """Caller has verified terminal semantics; bind evidence without replacing it."""
        need(not self.completed and self.claim is not None, "operation_already_completed")
        self.lease._check()
        need(self.lease._active == self.claim, "operation_active_claim_required")
        value = {"schema_version": 1, "operation_id": self.authority["operation_id"],
                 "claim_sha256": self.claim["sha256"], "status": "completed", "quiescent": True,
                 "evidence": copy.deepcopy(evidence)}
        # Validate before publishing anything. complete() independently verifies
        # the same receipt after publication and after its terminal marker write.
        need(isinstance(evidence, list) and 1 <= len(evidence) <= 16, "operation_evidence_required")
        paths, budget = set(), gate.Budget()
        for ref in evidence:
            gate.read_ref(ref, self.uid, budget)
            need(ref["path"] not in paths, "operation_duplicate_evidence")
            paths.add(ref["path"])
        base = private_child(Path(self.authority_ref["path"]).parent, ".operation-receipts", self.uid)
        directory = private_child(base, self.authority["operation_id"], self.uid)
        path = directory / "terminal-receipt.json"
        if os.path.lexists(path):
            previous, receipt = private_ref(path, owner_uid=self.uid)
            need(gate.encoded(previous) == gate.encoded(value), "operation_receipt_changed")
        else:
            receipt = gate.create_json(directory, path.name, value, self.uid)
        terminal = self.lease.complete(receipt)
        self.completed, self.terminal = True, terminal
        return terminal


@contextmanager
def admitted(authority_ref, expected_subject, kind, attempt_root, *, claim_ref=None,
             read_only=False, owner_uid=0, required_sources=()):
    value = validate_authority(authority_ref, expected_subject, kind, attempt_root,
                               owner_uid=owner_uid, required_sources=required_sources)
    with gate.OperationGate(attempt_root, value["gate"], owner_uid=owner_uid).locked() as lease:
        # Verify again under the lock before consuming an operation ID.
        need(validate_authority(authority_ref, expected_subject, kind, attempt_root,
                owner_uid=owner_uid, required_sources=required_sources) == value,
             "operation_authority_changed")
        terminal, completed, claim = None, False, None
        if read_only:
            need(claim_ref is None, "operation_check_cannot_reconcile")
            lease.ensure_available()
        elif claim_ref is None:
            claim = lease.begin(value["operation_id"], kind, authority_ref)
        else:
            row = lease.reconcile(claim_ref)
            saved = gate.read_ref(row["claim"], owner_uid, gate.Budget())
            need(saved["operation_id"] == value["operation_id"] and saved["kind"] == kind
                 and saved["authority"] == authority_ref, "operation_claim_mismatch")
            claim, completed, terminal = row["claim"], row["status"] == "completed", row["terminal"]
        yield Admission(authority_ref, value, lease, claim, completed, terminal, owner_uid)


def current_launch(source_files, *, executable_ref):
    """Attest the actual direct-script invocation, without a self-referential hash."""
    need(isinstance(sys.argv, list) and sys.argv and Path(sys.argv[0]).is_absolute(),
         "operation_direct_script_required")
    script = str(gate.canonical(sys.argv[0]))
    refs = [ref for ref in source_files if ref["path"] == script]
    need(len(refs) == 1, "operation_parent_source_missing")
    return {"executable": copy.deepcopy(executable_ref), "script": copy.deepcopy(refs[0]),
            "argv": [sys.executable, *sys.argv]}


def trial_dispatch(admission, plan_ref, parent_launch):
    """Return the coordinator hook; envelope publication is charged to its deadline."""
    @contextmanager
    def prepare(plan, entry, request_path):
        import full_client_experiment as experiment
        need(not admission.completed and admission.claim is not None, "operation_active_claim_required")
        admission.lease._check()
        need(admission.lease._active == admission.claim, "operation_active_claim_required")
        saved = gate.read_ref(plan_ref, admission.uid, gate.Budget())
        need(saved == plan, "operation_plan_changed")
        fixture = experiment.fixture_for(plan, entry)
        request, request_ref = private_ref(request_path, owner_uid=admission.uid)
        need(request == entry["spec"] and request_ref["sha256"] == entry["spec_sha256"],
             "operation_request_changed")
        binding = {"action": "trial_run", "attempt_id": entry["attempt_id"], "request": request_ref,
                   "adapter_config": fixture["adapter_config"], "state_root": plan["runner"]["state_root"],
                   "world_lock": plan["runner"]["world_lock"], "queue_lock": plan["runner"]["queue_lock"],
                   "plan": copy.deepcopy(plan_ref)}
        base = private_child(Path(admission.authority_ref["path"]).parent, ".operation-dispatch", admission.uid)
        directory = private_child(base, admission.authority["operation_id"], admission.uid)
        with join.prepare_join(admission.lease, directory, binding, parent_launch=parent_launch) as prepared:
            yield prepared
    return prepare


def add_arguments(parser, *, inherited=False):
    parser.add_argument("--operation-authority", type=Path)
    parser.add_argument("--operation-authority-sha256")
    parser.add_argument("--operation-claim", type=Path)
    parser.add_argument("--operation-claim-sha256")
    if inherited:
        parser.add_argument("--operation-envelope", type=Path)
        parser.add_argument("--operation-envelope-sha256")
        parser.add_argument("--operation-fd", type=int)
        parser.add_argument("--operation-recovery", type=Path)
        parser.add_argument("--operation-recovery-sha256")


def argument_refs(args, *, reconcile=False):
    need(args.operation_authority is not None and args.operation_authority_sha256 is not None,
         "operation_authority_required")
    authority = {"path": str(args.operation_authority), "sha256": args.operation_authority_sha256}
    need((args.operation_claim is None) == (args.operation_claim_sha256 is None), "operation_claim_hash_required")
    claim = ({"path": str(args.operation_claim), "sha256": args.operation_claim_sha256}
             if args.operation_claim is not None else None)
    need((claim is not None) == reconcile, "operation_exact_claim_required" if reconcile else "operation_initial_claim_forbidden")
    return authority, claim


def trial_subject(args, config_ref, request_ref):
    return {"type": "trial", "attempt_id": args.attempt_id, "adapter_config": config_ref,
            "request": request_ref, "state_root": str(gate.canonical(args.state_root)),
            "world_lock": str(gate.canonical(args.world_lock)), "queue_lock": str(gate.canonical(args.queue_lock))}


def recovery_descriptor(ref, plan_ref, plan, entry, directory, claim_ref, *, owner_uid=0, current=False):
    """Read an immutable cleanup request; the failed journal copy never changes."""
    import full_client_experiment as experiment
    value = gate.read_ref(ref, owner_uid, gate.Budget())
    gate.fields(value, ("schema_version", "kind", "attempt_id", "plan", "coordinator", "claim",
                       "journal", "failure", "request", "adapter_config", "timeout_seconds"),
                "operation_invalid_recovery")
    ident = entry["attempt_id"]
    need(type(value["schema_version"]) is int and value["schema_version"] == 1
         and value["kind"] == "finite_group_recovery" and value["attempt_id"] == ident
         and value["plan"] == plan_ref and value["claim"] == claim_ref
         and type(value["timeout_seconds"]) is int and 1 <= value["timeout_seconds"] <= 300,
         "operation_recovery_mismatch")
    need(ref["path"] == str(directory / "recoveries" / (ident + ".json"))
         and value["failure"]["path"] == str(directory / "recoveries" / (ident + ".failed-journal.json"))
         and value["journal"]["path"] == str(Path(plan["runner"]["state_root"]) / ident / "journal.json")
         and value["failure"]["sha256"] == value["journal"]["sha256"]
         and value["coordinator"]["path"] == str(directory / "coordinator.json")
         and value["request"]["path"] == str(directory / "requests" / (ident + ".json")),
         "operation_recovery_namespace")
    fixture = experiment.fixture_for(plan, entry)
    request = gate.read_ref(value["request"], owner_uid, gate.Budget())
    failed = gate.read_ref(value["failure"], owner_uid, gate.Budget())
    need(value["adapter_config"] == fixture["adapter_config"] and request == entry["spec"]
         and value["request"]["sha256"] == entry["spec_sha256"]
         and failed.get("attempt_id") == ident and failed.get("request") == request
         and failed.get("adapter_fingerprint") == fixture["adapter_fingerprint"]
         and failed.get("status") in ("failed", "interrupted")
         and failed.get("publication_eligible") is False, "operation_recovery_failure_mismatch")
    state = gate.read_ref(value["coordinator"], owner_uid, gate.Budget())
    experiment.validate_state(state, plan)
    need("closure" not in state and state["status"] in ("running", "stopped") and state["submissions"]
         and state["submissions"][-1]["attempt_id"] == ident and ident not in state["settled"]
         and "retirement" not in state["submissions"][-1], "operation_recovery_not_current")
    if current:
        need(gate.read_ref(value["journal"], owner_uid, gate.Budget()) == failed, "operation_recovery_journal_changed")
    return value


@contextmanager
def recovery_dispatch(admission, plan_ref, plan, entry, directory, recovery_ref, parent_launch):
    need(not admission.completed and admission.claim is not None, "operation_active_claim_required")
    admission.lease._check()
    need(admission.lease._active == admission.claim, "operation_active_claim_required")
    value = recovery_descriptor(recovery_ref, plan_ref, plan, entry, directory, admission.claim,
                                owner_uid=admission.uid, current=True)
    runner = plan["runner"]
    binding = {"action": "trial_recover", "attempt_id": entry["attempt_id"], "request": None,
               "adapter_config": value["adapter_config"], "recovery": recovery_ref, "plan": plan_ref,
               **{key: runner[key] for key in ("state_root", "world_lock", "queue_lock")}}
    base = private_child(Path(admission.authority_ref["path"]).parent, ".operation-dispatch", admission.uid)
    directory = private_child(base, admission.authority["operation_id"], admission.uid)
    with join.prepare_join(admission.lease, directory, binding, parent_launch=parent_launch) as prepared:
        yield prepared


@contextmanager
def inherited_trial(args, config_ref, request, request_ref, *, owner_uid=0):
    """Bind actual CLI inputs to the current coordinator submission before entry."""
    import full_client_experiment as experiment
    import full_client_trial as trial
    need(all(getattr(args, name) is None for name in ("operation_authority", "operation_authority_sha256",
         "operation_claim", "operation_claim_sha256")), "operation_admission_modes_conflict")
    need(args.operation_envelope is not None and args.operation_envelope_sha256 is not None
         and type(args.operation_fd) is int and args.operation_fd >= 3, "operation_join_arguments_required")
    envelope_ref = {"path": str(args.operation_envelope), "sha256": args.operation_envelope_sha256}
    # joined() owns/closes the inherited FD. Until its context is entered, close
    # our copy even if an earlier input check refuses admission.
    owns_fd = True
    try:
        envelope = gate.read_ref(envelope_ref, owner_uid, gate.Budget())
        claim = gate.read_ref(envelope["claim"], owner_uid, gate.Budget())
        authority = gate.read_ref(claim["authority"], owner_uid, gate.Budget())
        need(claim["kind"] == "finite_group" and args.command in ("run", "recover"), "operation_join_purpose_mismatch")
        subject = authority["subject"]
        authority = validate_authority(claim["authority"], subject, "finite_group", args.state_root,
            owner_uid=owner_uid, required_sources=(trial.__file__, experiment.__file__,
                                                  envelope["parent_launch"]["script"]["path"]))
        need(envelope["gate_pin"] == authority["gate"], "operation_gate_mismatch")
        plan_ref = subject["plan"]
        plan = experiment.validate_plan(gate.read_ref(plan_ref, owner_uid, gate.Budget()))
        matches = [entry for entry in plan["entries"] if entry["attempt_id"] == args.attempt_id]
        need(len(matches) == 1, "operation_entry_missing")
        entry = matches[0]
        fixture = experiment.fixture_for(plan, entry)
        expected = trial_subject(args, config_ref, request_ref)
        need(fixture["adapter_config"] == config_ref
             and all(expected[key] == plan["runner"][key] for key in ("state_root", "world_lock", "queue_lock"))
             and plan["runner"]["trial_script"] in authority["source_files"], "operation_entry_mismatch")
        directory = gate.canonical(subject["experiment_directory"])
        recovery = None
        if args.command == "run":
            need(getattr(args, "operation_recovery", None) is None and getattr(args, "operation_recovery_sha256", None) is None,
                 "operation_recovery_forbidden")
            need(entry["spec"] == request and request_ref["sha256"] == entry["spec_sha256"], "operation_entry_mismatch")
            need(request_ref["path"] == str(directory / "requests" / (args.attempt_id + ".json")),
                 "operation_request_outside_coordinator")
            state, _ = private_ref(directory / "coordinator.json", owner_uid=owner_uid)
            experiment.validate_state(state, plan)
            need(state["status"] == "running" and "closure" not in state and state["submissions"]
                 and state["submissions"][-1]["attempt_id"] == args.attempt_id
                 and state["submissions"][-1]["returncode"] is None
                 and "retirement" not in state["submissions"][-1]
                 and args.attempt_id not in state["settled"]
                 and state["events"][-1]["kind"] == "submission_intent", "operation_submission_not_current")
        else:
            need(request is None and request_ref is None and args.operation_recovery is not None
                 and args.operation_recovery_sha256 is not None, "operation_recovery_required")
            recovery_ref = {"path": str(args.operation_recovery), "sha256": args.operation_recovery_sha256}
            recovery = recovery_descriptor(recovery_ref, plan_ref, plan, entry, directory, envelope["claim"],
                                           owner_uid=owner_uid, current=True)
            need(args.timeout_seconds == recovery["timeout_seconds"], "operation_recovery_timeout_changed")
        binding = {"action": "trial_run" if recovery is None else "trial_recover", "attempt_id": args.attempt_id, "request": request_ref,
                   "adapter_config": config_ref, "state_root": expected["state_root"],
                   "world_lock": expected["world_lock"], "queue_lock": expected["queue_lock"], "plan": plan_ref}
        if recovery is not None:
            binding["recovery"] = recovery_ref
        owns_fd = False
        with join.joined(args.state_root, authority["gate"], envelope_ref, args.operation_fd, binding,
                         owner_uid=owner_uid) as result:
            yield result if recovery is None else {**result, "recovery": recovery}
    finally:
        if owns_fd:
            os.close(args.operation_fd)


def trial_terminal(runner, attempt_id, expected_request, *, owner_uid=0):
    """Verify actual terminal cleanup bytes; this performs no backend operation."""
    import full_client_trial as trial
    folder = Path(runner.root) / attempt_id
    journal, journal_ref = private_ref(folder / "journal.json", owner_uid=owner_uid)
    backend, backend_ref = private_ref(folder / "backend-state.json", owner_uid=owner_uid)
    receipts = journal.get("receipts", {})
    final = receipts.get("status", {})
    need(journal.get("attempt_id") == attempt_id and journal.get("status") in ("completed", "recovered")
         and journal.get("adapter_fingerprint") == runner.adapter.fingerprint
         and journal.get("request") == expected_request and journal.get("pending") is None
         and journal.get("phase") == "status" and journal.get("phase_status") == "returned"
         and receipts.get("cleanup") == {"attempt_id": attempt_id, "clean": True}
         and backend.get("attempt_id") == attempt_id and backend.get("clean") is True
         and isinstance(final, dict) and all(final.get(k) is True for k in trial.STATUS_FIELDS if k != "ownership_conflict")
         and final.get("ownership_conflict") is False, "operation_trial_not_terminal_clean")
    return [journal_ref, backend_ref]


def lifecycle_terminal(lifecycle, journal_ref, handoff_ref):
    """Reobserve a completed lifecycle; no world-lock acquisition or service start."""
    import full_client_lifecycle as normal
    with lifecycle.serialized():
        state = normal.read_ref(journal_ref, uid=lifecycle.owner_uid)
        handoff = lifecycle.load_handoff(handoff_ref)
        need(state.get("schema_version") == 1 and state.get("operation_id") == handoff["operation_id"]
             and state.get("config") == lifecycle.config_ref and state.get("handoff") == handoff_ref
             and state.get("status") == "completed" and state.get("phase") == "complete"
             and state.get("service_starts") == {"cosmic": 1, "worker": 1}
             and state.get("new_api_requests") == 0 and state.get("database_mutations") is False
             and state.get("automatic_retry") is False and state.get("cosmic_restarted") is False,
             "operation_lifecycle_not_completed")
        events = state.get("events")
        need(isinstance(events, list) and events and events[-1].get("phase") == "complete"
             and all(isinstance(event, dict) and type(event.get("sequence")) is int
                     and event["sequence"] == index for index, event in enumerate(events)),
             "operation_lifecycle_events_invalid")
        ready = state.get("native_ready")
        need(isinstance(ready, dict) and all(gate.integer(ready.get(key)) for key in
                ("device", "inode", "bytes", "offset", "fd", "observed_at_ms"))
             and ready["bytes"] > ready["offset"]
             and isinstance(ready.get("ports"), list)
             and set(lifecycle.config["native"]["ports"]) <= set(ready["ports"])
             and all(isinstance(ready.get(key), str) and gate.SHA.fullmatch(ready[key])
                     for key in ("log_sha256", "startup_sha256")), "operation_native_receipt_missing")
        for role in ("cosmic", "worker"):
            normal.instance(state[role])
            normal.object_fields(state[role + "_start"], ("intent_at_ms", "previous_invocation_id"))
            need(state[role + "_start"]["previous_invocation_id"] == handoff["stopped_invocations"][role],
                 "operation_lifecycle_start_changed")
        directory = lifecycle.root / state["operation_id"]
        need(journal_ref["path"] == str(directory / "journal.json"), "operation_lifecycle_journal_outside_root")
        lifecycle.state, lifecycle.directory, lifecycle.journal_sha = state, directory, journal_ref["sha256"]
        lifecycle.verify_files()
        lifecycle.same_cosmic()
        need(lifecycle.worker_idle() == state["first_idle"], "operation_lifecycle_idle_changed")
        # Recheck the existing append-only native descriptor/listener evidence;
        # worker_idle proves the same Cosmic before and after worker startup.
        lifecycle.host.native(state["cosmic"]["pid"], lifecycle.config["native"],
            state["preflight"]["native_boundary"], state["cosmic_start"]["intent_at_ms"])
        raw, info = normal.read_file(lifecycle.config["native"]["path"],
            maximum=lifecycle.config["native"]["max_bytes"], uid=lifecycle.config["services"]["cosmic"]["uid"], private=True)
        need((info.st_dev, info.st_ino) == (ready["device"], ready["inode"]) and len(raw) >= ready["bytes"]
             and hashlib.sha256(raw[:ready["bytes"]]).hexdigest() == ready["log_sha256"]
             and hashlib.sha256(raw[ready["offset"]:ready["bytes"]]).hexdigest() == ready["startup_sha256"],
             "operation_native_receipt_changed")
        lifecycle.quiet(worker_stopped=False)
        need(lifecycle.worker_idle() == state["first_idle"], "operation_lifecycle_idle_changed")
        normal.read_ref(journal_ref, uid=lifecycle.owner_uid)
        return [copy.deepcopy(journal_ref)]
