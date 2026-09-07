"""Finite, predeclared full-client experiments around the unchanged trial CLI.

Creating a plan and reporting are offline operations. Only explicit run/resume
launches trials. Submitted IDs are never replayed, including absent journals.
Only a synchronous refusal before launcher entry can explicitly retire an ID;
missing journals without that durable receipt remain unresolved.
Private plans/journals are trusted operator inputs, not authenticated evidence.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import statistics
import subprocess
import sys
import tempfile
import time
import uuid

import full_client_trial as trial
import full_client_score as scoring
import full_client_docker as docker
import full_client_readiness as readiness

MODELS = ("gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
SHA = re.compile(r"[a-f0-9]{64}\Z")
RUN = re.compile(r"[a-f0-9]{32}\Z")
SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
MAX_JSON = 4 * 1024**2
# Match the concrete backend's manifest ref_bytes/JSON_LIMIT and MAX_SQL.
# Planning must reject files that the runtime cannot consume before submission.
MAX_MANIFEST = scoring.JSON_LIMIT
MAX_BASELINE = 64 * 1024**2
MAX_ENTRIES = 200
LAUNCH_GRACE_SECONDS = 5
POLICY = {"failure": "stop", "resume": "explicit_future_unsubmitted_only", "retries": 0,
          "launch_grace_seconds": LAUNCH_GRACE_SECONDS}
TERMINAL = {"completed", "recovered"}
STATUSES = TERMINAL | {"running", "failed", "interrupted", "recovering"}
UNLAUNCHED = "retired_unlaunched"
PRELAUNCH_REFUSALS = {"insufficient_time_for_full_trial"}


class ExperimentError(RuntimeError):
    """Only fixed codes written in this module may be exposed by its CLI."""


def require(condition, code):
    if not condition:
        raise ExperimentError(code)


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def encoded(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    except (TypeError, ValueError, RecursionError) as error:
        raise ExperimentError("invalid_json") from error
    require(len(raw) <= MAX_JSON, "json_limit")
    return raw


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def decode(raw, *, maximum=MAX_JSON):
    require(len(raw) <= maximum, "json_limit")
    try:
        value = scoring.parse_json(raw)
    except (scoring.EvidenceError, TypeError) as error:
        raise ExperimentError("invalid_json") from error
    require(isinstance(value, dict), "invalid_json_object")
    return value


def absolute(value):
    require(isinstance(value, str) and 0 < len(value) <= 4096 and "\0" not in value,
            "invalid_path")
    path = Path(value)
    require(path.is_absolute() and ".." not in path.parts and str(path) == value, "invalid_path")
    require(path.resolve() == path, "symlink_path")
    return path


def stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode, info.st_uid)


def read_file(path, *, maximum=MAX_JSON, expected=None, private=False, keep=True):
    """Bounded stable descriptor read; hash exactly the consumed bytes."""
    path = absolute(str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum, "file_limit")
        require(before.st_uid in (0, os.geteuid()) and not before.st_mode & (0o077 if private else 0o022),
                "unprotected_input")
        h, size, chunks = hashlib.sha256(), 0, []
        while True:
            block = os.read(fd, min(1024**2, maximum + 1 - size))
            if not block:
                break
            size += len(block)
            require(size <= maximum, "file_limit")
            h.update(block)
            if keep:
                chunks.append(block)
        require(stamp(before) == stamp(os.fstat(fd)) == stamp(path.stat(follow_symlinks=False)),
                "input_changed")
        actual = h.hexdigest()
        require(expected is None or actual == expected, "input_hash_mismatch")
        return (b"".join(chunks) if keep else None), actual
    finally:
        os.close(fd)


def reference(value):
    require(isinstance(value, dict) and set(value) == {"path", "sha256"}
            and isinstance(value["sha256"], str) and SHA.fullmatch(value["sha256"]), "invalid_reference")
    absolute(value["path"])
    return value


def pin(path):
    return {"path": str(absolute(str(path))), "sha256": read_file(path, maximum=64 * 1024**2, keep=False)[1]}


def read_ref(ref, *, maximum=MAX_JSON, private=False, keep=True):
    reference(ref)
    return read_file(ref["path"], maximum=maximum, expected=ref["sha256"], private=private, keep=keep)[0]


def private_directory(path, *, create=False):
    path = absolute(str(path))
    if create and not path.exists():
        require(path.parent.is_dir(), "parent_directory_required")
        path.mkdir(mode=0o700)
        sync_directory(path.parent)
    info = path.stat(follow_symlinks=False)
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and not info.st_mode & 0o077,
            "private_directory_required")
    return path


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json(path, value, *, create=False):
    path = absolute(str(path))
    private_directory(path.parent)
    raw = encoded(value)
    fd, temporary = tempfile.mkstemp(prefix=".experiment-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if create:
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError as error:
                raise ExperimentError("file_already_exists") from error
        else:
            require(path.is_file() and not path.is_symlink(), "journal_missing")
            os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def validate_runner(value):
    require(isinstance(value, dict) and set(value) == {
        "python", "trial_script", "dependencies", "state_root", "world_lock", "queue_lock"}, "invalid_runner")
    for key in ("python", "trial_script"):
        reference(value[key])
    require(value["trial_script"]["path"] == str(Path(trial.__file__).resolve()), "runner_import_mismatch")
    required = {str(Path(__file__).resolve()), str(Path(scoring.__file__).resolve()),
                str(Path(docker.__file__).resolve()), str(Path(readiness.__file__).resolve())}
    deps = value["dependencies"]
    require(isinstance(deps, list) and 2 <= len(deps) <= 32, "invalid_runner_dependencies")
    for ref in deps:
        reference(ref)
    require(len({ref["path"] for ref in deps}) == len(deps)
            and required <= {ref["path"] for ref in deps}, "runner_dependencies_missing")
    paths = [absolute(value[k]) for k in ("state_root", "world_lock", "queue_lock")]
    require(len(set(paths)) == 3, "runner_paths_must_differ")


def validated_spec(model, fixture):
    spec = {"schema_version": 1, "model": model, "scenario_fingerprint": fixture["scenario"]["sha256"],
            "baseline_sha256": fixture["baseline"]["sha256"], "budgets": copy.deepcopy(fixture["budgets"])}
    try:
        trial.validate_spec(spec)
    except trial.TrialError as error:
        raise ExperimentError("invalid_trial_spec") from error
    return spec


def fixture_inputs(fixture, runner):
    """No host commands, services, asset inventory, database or model access."""
    scenario = decode(read_ref(fixture["scenario"]))
    require(scoring.same_json(scenario.get("trial_budgets"), fixture["budgets"]), "fixture_budget_mismatch")
    read_ref(fixture["baseline"], maximum=MAX_BASELINE, keep=False)
    runtime = decode(read_ref(fixture["runtime_manifest"], maximum=MAX_MANIFEST), maximum=MAX_MANIFEST)
    require(type(runtime.get("schema_version")) is int and runtime["schema_version"] == 2
            and isinstance(runtime.get("docker_image_id"), str)
            and re.fullmatch(r"sha256:[a-f0-9]{64}", runtime["docker_image_id"]), "invalid_runtime_manifest")
    try:
        docker.validate_binding(runtime.get("docker_binding"), verify_files=False)
    except (ValueError, OSError) as error:
        raise ExperimentError("invalid_docker_binding") from error
    adapter = decode(read_ref(fixture["adapter_config"], private=True))
    require(set(adapter) == {"argv", "dependencies"}, "invalid_adapter_config")
    argv = adapter["argv"]
    require(isinstance(argv, list) and len(argv) == 4 and argv[2] == "--config", "invalid_backend_argv")
    config = decode(read_file(absolute(argv[3]), private=True)[0])
    require(all(scoring.same_json(config.get(key), fixture[key]) for key in ("scenario", "baseline", "runtime_manifest"))
            and config.get("attempt_root") == runner["state_root"]
            and config.get("world_lock") == runner["world_lock"]
            and config.get("queue_lock") == runner["queue_lock"]
            and scoring.same_json(config.get("orchestrator"), runner["trial_script"]), "backend_fixture_mismatch")
    reference(config.get("baseline_snapshot"))
    baseline_snapshot = decode(read_ref(config["baseline_snapshot"], private=True))
    require(isinstance(baseline_snapshot.get("character"), dict), "invalid_readiness_policy")
    expected_map = baseline_snapshot["character"].get("map_id")
    require(type(expected_map) is int, "invalid_readiness_policy")
    try:
        readiness.validate_policy(scenario.get("readiness_policy"), expected_map_id=expected_map)
    except readiness.ReadinessError as error:
        raise ExperimentError("invalid_readiness_policy") from error
    try:
        fingerprint = trial.CommandAdapter(argv, adapter["dependencies"]).fingerprint
    except (trial.TrialError, OSError, ValueError) as error:
        raise ExperimentError("adapter_pins_invalid") from error
    if "adapter_fingerprint" in fixture:
        require(fingerprint == fixture["adapter_fingerprint"], "adapter_changed")
    return fingerprint


def verify_inputs(plan):
    runner = plan["runner"]
    for ref in (runner["python"], runner["trial_script"], *runner["dependencies"]):
        read_ref(ref, maximum=64 * 1024**2, keep=False)
    require(os.access(runner["python"]["path"], os.X_OK), "python_not_executable")
    for fixture in plan["fixtures"]:
        fixture_inputs(fixture, runner)


def balance(models, repetitions, fixtures):
    counts = {fixture["id"]: {model: [0] * len(models) for model in models} for fixture in fixtures}
    for rep in range(repetitions):
        ordered = models[rep % len(models):] + models[:rep % len(models)]
        for fixture in fixtures:
            for position, model in enumerate(ordered):
                counts[fixture["id"]][model][position] += 1
    return {"method": "cyclic_model_rotation_within_each_fixture",
            "exact_position_balance": repetitions % len(models) == 0,
            "position_counts": counts, "combat_randomness": "uncontrolled"}


def validate_plan(plan):
    require(isinstance(plan, dict) and set(plan) == {"schema_version", "experiment_id", "models", "repetitions",
        "fixtures", "runner", "entries", "aggregate_limits", "policy", "balance"}, "invalid_plan_fields")
    require(type(plan["schema_version"]) is int and plan["schema_version"] == 1, "unsupported_plan")
    require(isinstance(plan["experiment_id"], str) and SLUG.fullmatch(plan["experiment_id"]), "invalid_experiment_id")
    models, reps, fixtures = plan["models"], plan["repetitions"], plan["fixtures"]
    require(isinstance(models, list) and 1 <= len(models) <= len(MODELS)
            and all(isinstance(m, str) and m in MODELS for m in models)
            and len(set(models)) == len(models), "invalid_models")
    require(integer(reps, 1, 50) and isinstance(fixtures, list) and 1 <= len(fixtures) <= 16
            and len(models) * reps * len(fixtures) <= MAX_ENTRIES, "plan_size_limit")
    validate_runner(plan["runner"])
    ids = []
    for fixture in fixtures:
        require(isinstance(fixture, dict) and set(fixture) == {"id", "scenario", "baseline", "runtime_manifest",
                "budgets", "adapter_config", "adapter_fingerprint"}, "invalid_fixture")
        require(isinstance(fixture["id"], str) and SLUG.fullmatch(fixture["id"]), "invalid_fixture_id")
        ids.append(fixture["id"])
        for key in ("scenario", "baseline", "runtime_manifest", "adapter_config"):
            reference(fixture[key])
        require(isinstance(fixture["adapter_fingerprint"], str) and SHA.fullmatch(fixture["adapter_fingerprint"]),
                "invalid_adapter_fingerprint")
        validated_spec(models[0], fixture)
    require(len(set(ids)) == len(ids), "duplicate_fixture")
    expected_order = []
    for rep in range(reps):
        ordered = models[rep % len(models):] + models[:rep % len(models)]
        for fixture in fixtures:
            expected_order.extend((fixture, rep + 1, model) for model in ordered)
    entries = plan["entries"]
    require(isinstance(entries, list) and len(entries) == len(expected_order), "entry_count_mismatch")
    attempts, sums = set(), {"api_requests": 0, "total_tokens": 0, "wall_seconds": 0}
    for ordinal, (entry, (fixture, rep, model)) in enumerate(zip(entries, expected_order)):
        require(isinstance(entry, dict) and set(entry) == {"ordinal", "fixture_id", "repetition", "model",
                "attempt_id", "spec", "spec_sha256"}, "invalid_entry")
        require(type(entry["ordinal"]) is int and entry["ordinal"] == ordinal
                and type(entry["repetition"]) is int and entry["repetition"] == rep
                and entry["fixture_id"] == fixture["id"] and entry["model"] == model, "entry_order_mismatch")
        require(isinstance(entry["attempt_id"], str) and RUN.fullmatch(entry["attempt_id"])
                and entry["attempt_id"] not in attempts, "invalid_or_duplicate_attempt")
        attempts.add(entry["attempt_id"])
        require(scoring.same_json(entry["spec"], validated_spec(model, fixture))
                and entry["spec_sha256"] == digest(entry["spec"]), "spec_binding_mismatch")
        for name, field in (("api_requests", "max_api_requests"), ("total_tokens", "max_total_tokens"),
                            ("wall_seconds", "total_seconds")):
            sums[name] += entry["spec"]["budgets"][field]
        sums["wall_seconds"] += LAUNCH_GRACE_SECONDS
    limits = plan["aggregate_limits"]
    require(isinstance(limits, dict) and set(limits) == set(sums), "invalid_aggregate_limits")
    caps = {"api_requests": MAX_ENTRIES, "total_tokens": MAX_ENTRIES * 1000000, "wall_seconds": 604800}
    require(all(integer(limits[name], sums[name], caps[name]) for name in sums), "aggregate_budget_insufficient")
    require(scoring.same_json(plan["policy"], POLICY), "unsupported_resume_policy")
    require(scoring.same_json(plan["balance"], balance(models, reps, fixtures)), "balance_claim_mismatch")
    return plan


def build_plan(config, *, id_factory=lambda: uuid.uuid4().hex):
    require(isinstance(config, dict) and set(config) == {"schema_version", "experiment_id", "models", "repetitions",
            "fixtures", "runner", "aggregate_limits"}, "invalid_configuration")
    plan = copy.deepcopy(config)
    validate_runner(plan["runner"])
    require(isinstance(plan["fixtures"], list) and 1 <= len(plan["fixtures"]) <= 16, "plan_size_limit")
    for fixture in plan["fixtures"]:
        require(isinstance(fixture, dict) and set(fixture) == {"id", "scenario", "baseline", "runtime_manifest",
                "budgets", "adapter_config"}, "invalid_fixture")
        fixture["adapter_fingerprint"] = fixture_inputs(fixture, plan["runner"])
    models, reps = plan["models"], plan["repetitions"]
    require(isinstance(models, list) and models and all(isinstance(m, str) and m in MODELS for m in models)
            and integer(reps, 1, 50) and len(models) * reps * len(plan["fixtures"]) <= MAX_ENTRIES,
            "plan_size_limit")
    plan.update(entries=[], policy=copy.deepcopy(POLICY), balance=balance(models, reps, plan["fixtures"]))
    for rep in range(reps):
        ordered = models[rep % len(models):] + models[:rep % len(models)]
        for fixture in plan["fixtures"]:
            for model in ordered:
                spec = validated_spec(model, fixture)
                plan["entries"].append({"ordinal": len(plan["entries"]), "fixture_id": fixture["id"],
                    "repetition": rep + 1, "model": model, "attempt_id": id_factory(),
                    "spec": spec, "spec_sha256": digest(spec)})
    validate_plan(plan)
    verify_inputs(plan)
    return plan


def fixture_for(plan, entry):
    return next(f for f in plan["fixtures"] if f["id"] == entry["fixture_id"])


def inspect_attempt(plan, entry):
    folder = absolute(plan["runner"]["state_root"]) / entry["attempt_id"]
    if not os.path.lexists(folder):
        return {"status": "missing", "terminal_clean": False}
    private_directory(folder)
    raw, journal_sha = read_file(folder / "journal.json", private=True)
    journal = decode(raw)
    require(isinstance(journal, dict), "invalid_attempt_journal")
    fixture = fixture_for(plan, entry)
    require(journal.get("schema_version") == 1 and journal.get("attempt_id") == entry["attempt_id"]
            and journal.get("status") in STATUSES and scoring.same_json(journal.get("request"), entry["spec"])
            and journal.get("adapter_fingerprint") == fixture["adapter_fingerprint"], "attempt_identity_mismatch")
    events = journal.get("events")
    require(isinstance(events, list) and events and len(events) <= 10000
            and all(isinstance(e, dict) and type(e.get("sequence")) is int and e["sequence"] == i
                    for i, e in enumerate(events)), "invalid_attempt_journal")
    result = {"status": journal["status"], "terminal_clean": False, "journal_sha256": journal_sha,
              "journal": journal, "folder": folder}
    usage = journal.get("charged_usage")
    require(isinstance(usage, dict) and set(usage) == {"api_requests", "total_tokens"}
            and all(integer(v, 0, 2**63-1) for v in usage.values()), "invalid_attempt_usage")
    result["usage"] = usage
    if journal["status"] in TERMINAL:
        raw, backend_sha = read_file(folder / "backend-state.json", private=True)
        backend = decode(raw)
        receipts = journal.get("receipts")
        require(isinstance(backend, dict) and isinstance(receipts, dict), "invalid_attempt_receipts")
        final = receipts.get("status")
        require(isinstance(final, dict), "invalid_attempt_receipts")
        require(journal.get("phase") == "status" and journal.get("phase_status") == "returned"
                and receipts.get("cleanup") == {"attempt_id": entry["attempt_id"], "clean": True}
                and backend.get("attempt_id") == entry["attempt_id"] and backend.get("clean") is True
                and all(final.get(k) is True for k in trial.STATUS_FIELDS if k != "ownership_conflict")
                and final.get("ownership_conflict") is False, "attempt_cleanup_unverified")
        result.update(terminal_clean=True, backend_sha256=backend_sha)
    return result


def launch_trial(plan, entry, request_path, timeout_seconds):
    """Production launcher: leave the runner's independent lock-retaining guard alone."""
    require(sys.platform.startswith("linux") and os.geteuid() == 0, "linux_root_required")
    runner, fixture = plan["runner"], fixture_for(plan, entry)
    parent_pid = os.getpid()
    end = time.monotonic() + timeout_seconds
    # Load libc before fork. The coordinator CLI is single-threaded; the child
    # sets its death signal before exec and checks the fork/prctl parent race.
    libc = ctypes.CDLL(None, use_errno=True)
    def parent_death_signal():
        if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0 or os.getppid() != parent_pid:
            os._exit(125)
    argv = [runner["python"]["path"], runner["trial_script"]["path"],
            "--adapter-config", fixture["adapter_config"]["path"], "--state-root", runner["state_root"],
            "--world-lock", runner["world_lock"], "--queue-lock", runner["queue_lock"],
            "run", "--request", str(request_path), "--attempt-id", entry["attempt_id"]]
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True, cwd="/", preexec_fn=parent_death_signal,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"})
    try:
        return process.wait(timeout=max(0, end - time.monotonic()))
    except BaseException:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()  # Only this runner PID, never the guard/bridge.
                process.wait(timeout=2)
        raise


class Experiment:
    def __init__(self, plan, directory, *, launcher=launch_trial, inspector=inspect_attempt,
                 verify=verify_inputs, wall_time=time.time, monotonic=time.monotonic):
        self.plan = validate_plan(copy.deepcopy(plan))
        self.directory = absolute(str(directory))
        self.launcher, self.inspector, self.verify = launcher, inspector, verify
        self.wall_time, self.monotonic = wall_time, monotonic
        self.state = None
        self.state_sha = None

    @contextmanager
    def locked(self):
        private_directory(self.directory, create=True)
        path = self.directory / ".experiment.lock"
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and not info.st_mode & 0o077,
                    "invalid_experiment_lock")
            require(stamp(info) == stamp(path.stat(follow_symlinks=False)), "experiment_lock_changed")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ExperimentError("experiment_already_running") from error
            yield
        finally:
            os.close(fd)

    def now(self):
        value = round(self.wall_time() * 1000)
        require(integer(value, 1, 2**53-1) and (self.state is None or value >= self.state["updated_at_ms"]),
                "clock_moved_backwards")
        return value

    def persist(self, event, *, create=False):
        path = self.directory / "coordinator.json"
        if self.state_sha is not None:
            require(read_file(path, private=True)[1] == self.state_sha, "coordinator_journal_changed")
        self.state["updated_at_ms"] = self.now()
        self.state["events"].append({"sequence": len(self.state["events"]), "at_ms": self.state["updated_at_ms"], "kind": event})
        write_json(path, self.state, create=create)
        self.state_sha = digest(self.state)

    def load(self):
        raw, self.state_sha = read_file(self.directory / "coordinator.json", private=True)
        self.state = validate_state(decode(raw), self.plan)

    def reconcile(self):
        charged = {"api_requests": 0, "total_tokens": 0, "wall_seconds": 0}
        for submission in self.state["submissions"]:
            entry = self.plan["entries"][submission["ordinal"]]
            observed = self.inspector(self.plan, entry)
            for key in charged:
                charged[key] += max(submission["reservation"][key], observed.get("usage", {}).get(key, 0))
            if "retirement" in submission:
                # Keep the full reservation consumed and require continued
                # absence. A later directory cannot be adopted as this ID.
                require(observed["status"] == "missing" and not os.path.lexists(
                    Path(self.plan["runner"]["state_root"]) / entry["attempt_id"]), "retired_attempt_appeared")
                continue
            require(observed["terminal_clean"], "submitted_attempt_unresolved")
            settled = {"status": observed["status"], "journal_sha256": observed["journal_sha256"],
                       "backend_sha256": observed["backend_sha256"]}
            previous = self.state["settled"].get(entry["attempt_id"])
            require(previous is None or scoring.same_json(previous, settled), "settled_attempt_changed")
            self.state["settled"][entry["attempt_id"]] = settled
        require(all(charged[k] <= self.plan["aggregate_limits"][k] for k in charged), "aggregate_usage_exceeded")
        return charged

    def run(self, *, resume=False):
        with self.locked():
            path = self.directory / "coordinator.json"
            if resume:
                require(path.exists(), "experiment_not_started")
                self.load()
                self.now()
            else:
                require(not os.path.lexists(path), "explicit_resume_required")
                started = self.now()
                self.state = {"schema_version": 1, "experiment_id": self.plan["experiment_id"],
                    "plan_sha256": digest(self.plan), "started_at_ms": started, "updated_at_ms": started,
                    "deadline_at_ms": started + self.plan["aggregate_limits"]["wall_seconds"] * 1000,
                    "status": "running", "submissions": [], "settled": {}, "events": []}
                self.persist("experiment_started", create=True)
            try:
                self.reconcile()
                self.state["status"] = "running"
                self.persist("explicit_resume" if resume else "execution_admitted")
                requests = private_directory(self.directory / "requests", create=True)
                # A persisted wall deadline includes all pauses. Monotonic time
                # prevents a within-invocation backwards clock from extending it.
                remaining = (self.state["deadline_at_ms"] - self.now()) / 1000
                end = self.monotonic() + max(0, remaining)
                for entry in self.plan["entries"][len(self.state["submissions"]):]:
                    require(self.now() < self.state["deadline_at_ms"] and self.monotonic() < end,
                            "experiment_deadline_exceeded")
                    self.verify(self.plan)
                    require(not os.path.lexists(Path(self.plan["runner"]["state_root"]) / entry["attempt_id"]),
                            "unsubmitted_attempt_already_exists")
                    request_path = requests / (entry["attempt_id"] + ".json")
                    if request_path.exists():
                        require(read_file(request_path, private=True)[1] == entry["spec_sha256"], "request_file_changed")
                    else:
                        write_json(request_path, entry["spec"], create=True)
                    reservation = {"api_requests": entry["spec"]["budgets"]["max_api_requests"],
                        "total_tokens": entry["spec"]["budgets"]["max_total_tokens"],
                        "wall_seconds": entry["spec"]["budgets"]["total_seconds"] + LAUNCH_GRACE_SECONDS}
                    charged = self.reconcile()
                    require(all(charged[k] + reservation[k] <= self.plan["aggregate_limits"][k]
                                for k in charged), "aggregate_budget_exhausted")
                    timeout = min(reservation["wall_seconds"], end - self.monotonic(),
                                  (self.state["deadline_at_ms"] - self.now()) / 1000)
                    require(timeout >= entry["spec"]["budgets"]["total_seconds"] + 1,
                            "insufficient_time_for_full_trial")
                    self.state["submissions"].append({"ordinal": entry["ordinal"], "attempt_id": entry["attempt_id"],
                        "submitted_at_ms": self.now(), "reservation": reservation, "returncode": None})
                    self.persist("submission_intent")  # No child may exist before this fsync.
                    timeout = min(reservation["wall_seconds"], end - self.monotonic(),
                                  (self.state["deadline_at_ms"] - self.now()) / 1000)
                    if timeout < entry["spec"]["budgets"]["total_seconds"] + 1:
                        # This branch is reached only in the invocation that
                        # fsynced the intent, before calling the launcher. Do
                        # not infer this outcome on resume or catch exceptions
                        # from inside the launcher, even with the same code.
                        require(not os.path.lexists(Path(self.plan["runner"]["state_root"]) / entry["attempt_id"]),
                                "unlaunched_attempt_appeared")
                        self.state["submissions"][-1]["retirement"] = {
                            "status": UNLAUNCHED, "reason": "insufficient_time_for_full_trial",
                            "launcher_invoked": False, "actual_usage": {"api_requests": 0, "total_tokens": 0},
                            "intent_sequence": self.state["events"][-1]["sequence"]}
                        self.persist("submission_retired_unlaunched")
                        raise ExperimentError("insufficient_time_for_full_trial")
                    returncode = self.launcher(self.plan, entry, request_path, timeout)
                    require(type(returncode) is int, "invalid_child_result")
                    self.state["submissions"][-1]["returncode"] = returncode
                    self.persist("child_returned")
                    require(self.now() <= self.state["deadline_at_ms"] and self.monotonic() <= end,
                            "experiment_deadline_exceeded")
                    self.reconcile()
                    require(returncode == 0, "child_failed")
                    self.persist("attempt_settled")
                self.state["status"] = "completed"
                self.persist("experiment_completed")
                return self.summary()
            except BaseException:
                self.state["status"] = "stopped"
                self.persist("operator_attention_required")
                raise

    def summary(self):
        return {"schema_version": 1, "experiment_id": self.plan["experiment_id"], "status": self.state["status"],
                "planned": len(self.plan["entries"]), "submitted": len(self.state["submissions"]),
                "settled": len(self.state["settled"]),
                "retired_unlaunched": sum("retirement" in item for item in self.state["submissions"]), "ranked": False}


def validate_state(state, plan):
    require(isinstance(state, dict) and set(state) == {"schema_version", "experiment_id", "plan_sha256",
        "started_at_ms", "updated_at_ms", "deadline_at_ms", "status", "submissions", "settled", "events"},
        "invalid_coordinator_journal")
    require(type(state["schema_version"]) is int and state["schema_version"] == 1
            and state["experiment_id"] == plan["experiment_id"] and state["plan_sha256"] == digest(plan)
            and state["status"] in {"running", "stopped", "completed"}, "coordinator_identity_mismatch")
    require(integer(state["started_at_ms"], 1, 2**53-1)
            and integer(state["updated_at_ms"], state["started_at_ms"], 2**53-1)
            and state["deadline_at_ms"] == state["started_at_ms"] + plan["aggregate_limits"]["wall_seconds"] * 1000,
            "coordinator_deadline_mismatch")
    submissions, settled, events = state["submissions"], state["settled"], state["events"]
    require(isinstance(submissions, list) and len(submissions) <= len(plan["entries"])
            and isinstance(settled, dict) and isinstance(events, list) and 1 <= len(events) <= 2000,
            "invalid_coordinator_journal")
    for i, item in enumerate(submissions):
        entry = plan["entries"][i]
        expected = {"api_requests": entry["spec"]["budgets"]["max_api_requests"],
                    "total_tokens": entry["spec"]["budgets"]["max_total_tokens"],
                    "wall_seconds": entry["spec"]["budgets"]["total_seconds"] + LAUNCH_GRACE_SECONDS}
        fields = {"ordinal", "attempt_id", "submitted_at_ms", "reservation", "returncode"}
        require(isinstance(item, dict) and (set(item) == fields or set(item) == fields | {"retirement"})
                and type(item["ordinal"]) is int and item["ordinal"] == i and item["attempt_id"] == entry["attempt_id"]
                and scoring.same_json(item["reservation"], expected)
                and integer(item["submitted_at_ms"], state["started_at_ms"], state["updated_at_ms"])
                and (item["returncode"] is None or integer(item["returncode"], -255, 255)), "invalid_submission_journal")
        if "retirement" in item:
            retired = item["retirement"]
            require(isinstance(retired, dict) and set(retired) == {
                    "status", "reason", "launcher_invoked", "actual_usage", "intent_sequence"}
                    and retired["status"] == UNLAUNCHED and isinstance(retired["reason"], str)
                    and retired["reason"] in PRELAUNCH_REFUSALS and retired["launcher_invoked"] is False
                    and scoring.same_json(retired["actual_usage"], {"api_requests": 0, "total_tokens": 0})
                    and integer(retired["intent_sequence"], 0, len(events) - 2)
                    and item["returncode"] is None and item["attempt_id"] not in settled,
                    "invalid_unlaunched_retirement")
    require(set(settled) <= {item["attempt_id"] for item in submissions}, "invalid_settlement_journal")
    for value in settled.values():
        require(isinstance(value, dict) and set(value) == {"status", "journal_sha256", "backend_sha256"}
                and value["status"] in TERMINAL and all(isinstance(value[k], str) and SHA.fullmatch(value[k])
                for k in ("journal_sha256", "backend_sha256")), "invalid_settlement_journal")
    previous = state["started_at_ms"]
    for i, event in enumerate(events):
        require(isinstance(event, dict) and set(event) == {"sequence", "at_ms", "kind"}
                and type(event["sequence"]) is int and event["sequence"] == i
                and integer(event["at_ms"], previous, state["updated_at_ms"])
                and event["kind"] in {"experiment_started", "execution_admitted", "explicit_resume", "submission_intent",
                                     "submission_retired_unlaunched", "child_returned", "attempt_settled",
                                     "operator_attention_required", "experiment_completed"},
                "invalid_coordinator_events")
        previous = event["at_ms"]
    intents = [event for event in events if event["kind"] == "submission_intent"]
    require(len(intents) == len(submissions)
            and all(item["submitted_at_ms"] <= event["at_ms"]
                    for item, event in zip(submissions, intents)), "submission_intent_mismatch")
    retirement_sequences = set()
    for index, (item, intent) in enumerate(zip(submissions, intents)):
        if "retirement" in item:
            sequence = item["retirement"]["intent_sequence"]
            require(sequence == intent["sequence"] and events[sequence + 1]["kind"] == "submission_retired_unlaunched",
                    "retirement_intent_mismatch")
            end = intents[index + 1]["sequence"] if index + 1 < len(intents) else len(events)
            require(not any(event["kind"] in {"child_returned", "attempt_settled"}
                            for event in events[sequence + 2:end]), "retirement_launch_event_conflict")
            retirement_sequences.add(sequence + 1)
    require(retirement_sequences == {event["sequence"] for event in events
                                    if event["kind"] == "submission_retired_unlaunched"}, "retirement_event_mismatch")
    require(state["status"] != "completed" or len(settled) + len(retirement_sequences) == len(plan["entries"]),
            "incomplete_completed_experiment")
    return state


def verified_metrics(plan, entry, observed):
    """Reverify actual persisted artifacts; never trust a journal score flag."""
    journal, folder = observed["journal"], observed["folder"]
    require(isinstance(journal, dict), "invalid_attempt_journal")
    require(journal["status"] == "completed" and observed["terminal_clean"], "score_requires_completion")
    receipts = journal.get("receipts")
    require(isinstance(receipts, dict), "invalid_attempt_receipts")
    collected = receipts.get("collect_final")
    require(isinstance(collected, dict), "invalid_attempt_receipts")
    refs = collected.get("artifacts")
    require(isinstance(refs, dict), "missing_score_artifacts")
    def artifact(name):
        value = scoring.parse_json(scoring.read_artifact_bytes(folder, refs.get(name), name,
            maximum=MAX_MANIFEST if name == "runtime_manifest" else scoring.JSON_LIMIT))
        require(isinstance(value, dict), "invalid_score_artifact")
        return value
    fixture = fixture_for(plan, entry)
    require(all(isinstance(refs.get(name), dict) and refs[name].get("sha256") == fixture[name]["sha256"]
                for name in ("scenario", "baseline", "runtime_manifest")), "score_fixture_mismatch")
    evidence = artifact("persistence")
    require(scoring.same_json(evidence, collected.get("evidence")), "persistence_receipt_mismatch")
    recomputed = scoring.verify_trial_bundle(evidence, folder, refs)
    saved, result, runtime = artifact("score"), artifact("result"), artifact("runtime_manifest")
    request, response = artifact("api_request"), artifact("api_response")
    controller, api, program = result.get("controller"), result.get("api"), result.get("program")
    request_metadata, response_metadata = request.get("metadata"), response.get("metadata")
    require(all(isinstance(value, dict) for value in
                (controller, api, program, request_metadata, response_metadata)), "invalid_score_envelope")
    context = {"scenario_fingerprint": entry["spec"]["scenario_fingerprint"], "baseline_sha256": entry["spec"]["baseline_sha256"]}
    require(scoring.same_json(saved, recomputed) and scoring.same_json(journal.get("score"), recomputed)
            and recomputed.get("run_id") == entry["attempt_id"]
            and recomputed.get("scenario_fingerprint") == context["scenario_fingerprint"]
            and recomputed.get("baseline_sha256") == context["baseline_sha256"]
            and result.get("source") == "full-client-trial" and controller.get("id") == entry["attempt_id"]
            and controller.get("status") == "completed" and controller.get("mode") == "api"
            and scoring.same_json(result.get("trialContext"), context) and scoring.same_json(controller.get("trialContext"), context)
            and all(value == entry["model"] for value in (controller.get("model"), controller.get("returnedModel"),
                    api.get("model"), request.get("model"), response.get("model")))
            and api.get("status") == response.get("status") == "completed"
            and isinstance(api.get("id"), str) and api["id"] == response.get("id")
            and isinstance(api.get("usage"), dict) and scoring.same_json(api["usage"], response.get("usage"))
            and request_metadata.get("maplebench_run_id") == entry["attempt_id"]
            and response_metadata.get("maplebench_run_id") == entry["attempt_id"]
            and controller.get("dockerImageId") == runtime.get("docker_image_id"), "score_model_or_receipt_mismatch")
    if runtime.get("schema_version") == 2:
        binding = docker.validate_binding(runtime.get("docker_binding"), verify_files=False)
        require(scoring.same_json(controller.get("dockerBinding"), binding), "score_docker_binding_mismatch")
    actions = program.get("actions")
    value = recomputed.get("metrics", {}).get("net_xp")
    require(type(value) is int and -(2**63) <= value < 2**63, "invalid_score_metrics")
    steps = program.get("steps")
    presses = [step for step in steps if isinstance(step, dict) and step.get("method") == "pressKeys"] if isinstance(steps, list) else []
    execution_verified = (integer(actions, 0, entry["spec"]["budgets"]["max_actions"])
        and isinstance(steps, list) and all(isinstance(step, dict) and step.get("kind") != "sdk_error" for step in steps)
        and all(step.get("kind") == "sdk" and isinstance(step.get("result"), dict)
                and step["result"].get("accepted") is True for step in presses)
        and len(presses) == actions and type(controller.get("actions")) is int and controller["actions"] == actions
        and type(program.get("actionAttempts")) is int and program["actionAttempts"] == actions
        and program.get("error") is None)
    return {"net_xp": value, "actions": actions if execution_verified else None,
            "no_op": actions == 0 if execution_verified else None,
            "execution_verification": "complete_action_receipts" if execution_verified else "unavailable",
            "alive_at_logout": recomputed["alive_at_logout"], "session_ms": recomputed["timing"]["session_ms"]}


def report(plan, directory, *, inspector=inspect_attempt, metrics=verified_metrics):
    validate_plan(plan)
    directory = absolute(str(directory))
    state_path = directory / "coordinator.json"
    state = validate_state(decode(read_file(state_path, private=True)[0]), plan) if state_path.exists() else None
    submissions = {s["attempt_id"]: s for s in state["submissions"]} if state else {}
    rows = []
    for entry in plan["entries"]:
        row = {key: entry[key] for key in ("ordinal", "fixture_id", "repetition", "model", "attempt_id")}
        row.update(status="unsubmitted", runner_status=None, metrics=None, score_verification="unavailable")
        try:
            observed = inspector(plan, entry)
            if entry["attempt_id"] not in submissions:
                require(observed["status"] == "missing", "unowned_attempt")
            elif "retirement" in submissions[entry["attempt_id"]]:
                require(observed["status"] == "missing" and not os.path.lexists(
                    Path(plan["runner"]["state_root"]) / entry["attempt_id"]), "retired_attempt_appeared")
                row.update(status=UNLAUNCHED, retirement=copy.deepcopy(submissions[entry["attempt_id"]]["retirement"]),
                           score_verification="not_applicable_unlaunched")
            else:
                row["runner_status"] = observed["status"] if observed["status"] in STATUSES else None
                row["status"] = observed["status"] if observed["status"] in STATUSES else "submitted_unresolved"
                previous = state["settled"].get(entry["attempt_id"])
                if previous:
                    require(scoring.same_json(previous, {"status": observed["status"],
                            "journal_sha256": observed.get("journal_sha256"),
                            "backend_sha256": observed.get("backend_sha256")}), "settled_attempt_changed")
                if observed["status"] == "completed":
                    row["metrics"] = metrics(plan, entry, observed)
                    row["score_verification"] = "verified_persisted_artifacts"
        except (ExperimentError, scoring.EvidenceError, OSError, ValueError, TypeError, KeyError):
            row.update(status="invalid_receipts", metrics=None, score_verification="invalid")
        rows.append(row)
    groups = []
    for fixture in plan["fixtures"]:
        for model in plan["models"]:
            members = [r for r in rows if r["fixture_id"] == fixture["id"] and r["model"] == model]
            valid = [r["metrics"] for r in members if r["metrics"] is not None]
            values = [m["net_xp"] for m in valid]
            counts = {status: sum(r["status"] == status for r in members) for status in sorted({r["status"] for r in members})}
            groups.append({"fixture_id": fixture["id"], "model": model, "planned_n": len(members),
                "verified_n": len(values), "outcome_counts": counts,
                "verified_fraction_of_plan": len(values) / len(members),
                "no_op_count": sum(m["no_op"] is True for m in valid),
                "execution_verified_n": sum(m.get("execution_verification") == "complete_action_receipts" for m in valid),
                "net_xp": {"mean": statistics.mean(values) if values else None,
                           "median": statistics.median(values) if values else None,
                           "minimum": min(values) if values else None, "maximum": max(values) if values else None,
                           "sample_standard_deviation": statistics.stdev(values) if len(values) > 1 else None},
                "uncertainty": {"confidence_interval": None, "reason": "descriptive_samples_no_independence_guarantee"},
                "population": "completed_attempts_with_verified_persistence", "ranked": False})
    return {"schema_version": 1, "experiment_id": plan["experiment_id"], "plan_sha256": digest(plan),
        "scope": "entire_declared_attempt_set", "planned": len(rows), "submitted": len(submissions),
        "retired_unlaunched": sum("retirement" in item for item in submissions.values()),
        "experiment_status": state["status"] if state else "not_started", "balance": plan["balance"],
        "publication_status": "not_evaluated", "ranked": False, "attempts": rows, "groups": groups}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("plan", help="Offline: validate inputs and write a new immutable private plan")
    create.add_argument("--config", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    for name in ("run", "resume", "report"):
        command = commands.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--directory", type=Path, required=True)
        if name == "report":
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            plan = build_plan(decode(read_file(args.config, private=True)[0]))
            write_json(args.output, plan, create=True)
            result = {"status": "plan_created", "plan_sha256": digest(plan), "entries": len(plan["entries"]), "ranked": False}
        else:
            plan = validate_plan(decode(read_file(args.plan, private=True)[0]))
            if args.command == "report":
                value = report(plan, args.directory)
                write_json(args.output, value, create=True)
                result = {"status": "report_created", "planned": value["planned"], "ranked": False}
            else:
                require(sys.platform.startswith("linux") and os.geteuid() == 0, "linux_root_required")
                result = Experiment(plan, args.directory).run(resume=args.command == "resume")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({"status": "blocked", "code": str(error) if isinstance(error, ExperimentError)
                          else "experiment_failed", "ranked": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
