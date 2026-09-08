"""Durable single-attempt full-client runner; no automatic retry or live defaults.

The trusted adapter owns host-specific operations. This runner owns existing
world/queue locks, durable intent records, deadlines, budgets, and quarantine.
Synthetic adapter tests do not establish a production-verified trial backend.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
import copy
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Protocol
import uuid

from full_client_score import verify_trial_bundle
from full_client_freeze import FREEZE_ERROR_CODES


ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_JSON = 4 * 1024 * 1024
PHASES = ("restore_baseline", "start_server", "login", "run_controller",
          "disconnect", "collect_final", "cleanup")
STATUS_FIELDS = ("ready", "queue_idle", "server_stopped", "account_offline",
                 "controller_idle", "ownership_conflict")
# Reviewed literal RuntimeErrorCode values from the trusted Cosmic backend.
# Never infer safety from a spelling pattern or load this list from adapter
# output/configuration: an unknown future code deliberately remains opaque.
MAX_ERROR_JSON = 512
# Only these reviewed relay failures may cross the private adapter and public
# dashboard boundary. A safe-looking identifier or exception type is not enough.
RELAY_ERROR_CODES = frozenset("""
invalid_run_identity client_state_stale run_owner_changed recorder_not_ready
client_busy_or_not_ready api_key_not_configured
invalid_input_acknowledgement client_already_connected unknown_recording_run
recording_client_mismatch recording_already_saved capture_metadata_already_saved
trial_capture_metadata_required run_intent_incomplete run_intent_conflict
run_cannot_be_released successful_run_cannot_be_discarded invalid_total_token_limit
invalid_docker_image_id invalid_trial_context trial_requires_matching_attempt_identity
corrupt_runs_require_acknowledgment trial_requires_guard_lock_descriptors client_owner_mismatch
previous_run_not_finalized run_intent_already_claimed api_request_limit api_token_budget_too_small
api_run_identity_mismatch api_invalid_program api_model_mismatch run_cancelled
trial_requires_two_configured_guard_locks invalid_guard_lock_path guard_lock_path_mismatch
guard_lock_descriptor_mismatch guard_descriptor_is_not_exclusively_locked trial_renderer_is_pinned
invalid_browser_session_state run_is_active browser_session_unavailable browser_must_be_waiting
trial_renderer_not_connected invalid_admin_request unexpected_guard_descriptors unknown_admin_operation
invalid_admin_ancillary_data too_many_guard_descriptors invalid_admin_request_size
invalid_docker_binding docker_binding_required docker_binding_mismatch docker_executable_changed
untrusted_docker_executable invalid_docker_socket invalid_docker_command docker_binding_unavailable
readiness_policy_required invalid_readiness_policy readiness_timeout readiness_state_changed
""".split())
RUNTIME_ERROR_CODES = frozenset("""
account_state_unavailable account_still_online actual_api_request_mismatch actual_api_response_mismatch
admin_operation_failed admin_request_limit admin_response_limit adaptive_evidence_mismatch
artifact_changed_during_collection artifact_size_limit artifact_symlink
attempt_directory_mismatch backend_owner_mismatch backend_state_missing
baseline_identity_mismatch bridge_budget_mismatch capture_metadata_hash_mismatch capture_verification_failed
cleanup_requires_stopped_offline cleanup_without_owner_requires_ready
cleanup_dropin_removal_unowned cleanup_configuration_still_loaded cleanup_checkpoint_invalid
client_asset_directory_required client_asset_inventory_mismatch client_asset_target_not_frozen
controller_collection_requires_logout controller_host_clock_mismatch controller_model_or_source_mismatch controller_run_failed
controller_run_identity_lost controller_trial_context_mismatch distinct_inherited_locks_required
distinct_locks_required dropin_owner_missing dropin_owner_path_mismatch dropin_ownership_lost
executed_program_mismatch existing_service_required existing_trial_environment existing_trial_owner
fresh_reset_required fresh_server_start_failed frozen_bridge_budgets_mismatch
frozen_prompt_mismatch frozen_spec_mismatch guard_ancestry_mismatch guard_identity_mismatch
host_command_failed host_output_limit inherited_lock_description_mismatch
inherited_lock_descriptions_missing invalid_backend_request invalid_character_identity
invalid_config_path invalid_database invalid_frozen_hash invalid_frozen_scenario invalid_game_ports
invalid_inherited_lock_description invalid_lock_file invalid_mysql_command invalid_provider_program
invalid_queue_status invalid_services invalid_settlement_policy invalid_settlement_timestamps
invalid_systemd_working_directory invalid_timeout inventory_requires_offline_account java_executable_required
legacy_bot_adapter_must_be_disabled linux_root_runner_required lock_paths_mismatch
mysql_defaults_not_private native_logout_commit_missing_or_ambiguous native_persistence_class_missing
native_root_service_traversal_required native_save_failure_or_identity_mismatch
native_startup_or_save_failed nonroot_service_user_required normal_committed_logout_required
native_startup_markers_ambiguous native_log_unavailable
native_journal_initialization_missing native_online_marker_missing native_listener_unavailable
proc_output_limit server_descriptor_limit
operation_already_attempted operation_deadline orchestrator_identity_mismatch ordinary_login_required
ordinary_logout_receipt_mismatch prelogin_inventory_required
private_admin_socket_required queue_database_missing queued_or_active_trials_exist
recording_duration_mismatch recording_probe_failed recording_upload_receipt_missing
readiness_policy_required invalid_readiness_policy readiness_receipt_mismatch
restore_requires_stopped_offline restored_baseline_mismatch
run_artifacts_missing run_id_must_be_32_hex runtime_dropin_root_required runtime_operation_failed
scenario_trial_budgets_mismatch served_client_build_paths_mismatch server_instance_ownership_lost
server_jar_command_mismatch server_native_environment_mismatch server_not_ready_for_ordinary_login
server_process_missing server_uid_mismatch service_working_directory_mismatch serving_sources_not_frozen
settlement_capture_tail_exceeded settlement_interval_exceeded settlement_logout_timeout
settlement_status_mismatch settlement_upload_timeout
symlink_config_path symlink_dropin_directory transactional_score_tables_required
unexpected_client_asset_entry unknown_operation unowned_controller_cleanup_refused
unowned_server_cleanup_refused unprivileged_services_required unsupported_program_duration
unsupported_runtime_config waiting_browser_required web_entrypoint_mismatch web_interpreter_mismatch
web_process_missing web_process_predates_frozen_sources web_runtime_paths_mismatch web_uid_mismatch
world_helper_or_worker_active world_or_queue_lock_not_owned
""".split()) | FREEZE_ERROR_CODES | RELAY_ERROR_CODES


class TrialError(RuntimeError):
    """A safe machine-readable failure code, never a raw adapter exception."""


class Adapter(Protocol):
    def perform(self, operation: str, context: dict, *, timeout_seconds: float) -> dict: ...


def require(value, code):
    if not value:
        raise TrialError(code)


def unique_object(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, "duplicate_json_key")
        out[key] = value
    return out


def decode(raw):
    require(len(raw) <= MAX_JSON, "json_too_large")
    try:
        return json.loads(raw, object_pairs_hook=unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(TrialError("nonfinite_json")))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise TrialError("invalid_json") from error


def adapter_failure_code(raw):
    """Preserve only the exact bounded backend error protocol, never its text."""
    if len(raw) > MAX_ERROR_JSON:
        return "adapter_failed"
    try:
        value = decode(raw)
    except (TrialError, TypeError):
        return "adapter_failed"
    if (isinstance(value, dict) and set(value) == {"error"}
            and isinstance(value["error"], str) and value["error"] in RUNTIME_ERROR_CODES):
        return value["error"]
    return "adapter_failed"


def encode(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError) as error:
        raise TrialError("invalid_json") from error
    require(len(raw) <= MAX_JSON, "json_too_large")
    return raw


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value):
    """The complete event history is replaced atomically and fsynced with its directory."""
    raw = encode(value)
    fd, name = tempfile.mkstemp(prefix=".journal-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def publish_attempt(staging, destination):
    """Atomically publish a complete initial journal without replacing any ID."""
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        result = rename(-100, os.fsencode(staging), -100, os.fsencode(destination), 1)  # RENAME_NOREPLACE
    elif sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        rename = libc.renamex_np
        rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        result = rename(os.fsencode(staging), os.fsencode(destination), 4)  # RENAME_EXCL
    else:
        raise TrialError("atomic_publish_unavailable")
    if result != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise TrialError("attempt_exists")
        raise TrialError("attempt_publish_failed")
    sync_directory(destination.parent)


def private_directory(path, *, create=False):
    path = Path(path).absolute()
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and not info.st_mode & 0o077, "private_directory_required")
    require(path.resolve() == path, "symlink_directory_forbidden")
    return path


def read_private_json(path, *, expected_sha256=None):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid in (0, os.geteuid())
                and not info.st_mode & 0o077, "private_file_required")
        raw = source.read(MAX_JSON + 1)
        require(expected_sha256 is None or isinstance(expected_sha256, str)
                and SHA.fullmatch(expected_sha256) and hashlib.sha256(raw).hexdigest() == expected_sha256,
                "recovery_journal_changed")
        return decode(raw)


def validate_spec(spec):
    require(isinstance(spec, dict), "invalid_spec")
    adaptive = spec.get("schema_version") == 2
    fields = {"schema_version", "model", "scenario_fingerprint", "baseline_sha256", "budgets"}
    require(set(spec) == fields | ({"protocol"} if adaptive else set()), "invalid_spec_fields")
    require(type(spec["schema_version"]) is int and spec["schema_version"] in (1, 2), "unsupported_schema")
    if adaptive:
        require(spec.get("protocol") == "full-client-adaptive-pilot-v1", "unsupported_protocol")
    require(isinstance(spec["model"], str) and ID.fullmatch(spec["model"]), "invalid_model")
    for name in ("scenario_fingerprint", "baseline_sha256"):
        require(isinstance(spec[name], str) and SHA.fullmatch(spec[name]), "invalid_" + name)
    bounds = {"total_seconds": (1, 1800), "operation_seconds": (335, 600) if adaptive else (1, 300),
              "controller_seconds": (1, 300), "max_actions": (1, 10000),
              "max_api_requests": (1, 16) if adaptive else (1, 1), "max_output_tokens": (1, 48000) if adaptive else (1, 32000),
              "max_total_tokens": (1, 1000000)}
    budgets = spec["budgets"]
    require(isinstance(budgets, dict) and set(budgets) == set(bounds), "invalid_budgets")
    for name, (low, high) in bounds.items():
        require(type(budgets[name]) is int and low <= budgets[name] <= high,
                "invalid_budget_" + name)
    require(budgets["controller_seconds"] <= budgets["total_seconds"]
            and budgets["max_output_tokens"] <= budgets["max_total_tokens"], "inconsistent_budgets")
    if adaptive:
        require(budgets["controller_seconds"] == 300 and budgets["total_seconds"] >= 600, "inconsistent_adaptive_budgets")
    return copy.deepcopy(spec)


@contextmanager
def existing_lock(path, *, create=False):
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    if create:
        flags |= os.O_CREAT
    fd = os.open(path, flags, 0o600)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), "invalid_lock_file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise TrialError("lock_conflict") from error
        yield fd
    finally:
        # SCM_RIGHTS/dup leases share this open file description. LOCK_UN here
        # would also revoke a trusted bridge's still-live copy; close only ours.
        os.close(fd)


class CommandAdapter:
    """Run a host-controlled executable directly; never interpret a shell string.

    argv is private operator configuration, never part of a model request. The
    executable and any script/config arguments must be pinned by the operator.
    Whole process groups are killed on timeout/interruption; provider outcome
    can still be uncertain. Raw stderr is discarded, not copied to a journal.
    """
    def __init__(self, argv, dependencies=None):
        require(isinstance(argv, list) and argv and all(isinstance(x, str) and "\0" not in x
                                                       for x in argv), "invalid_adapter_argv")
        executable = Path(argv[0])
        require(executable.is_absolute(), "absolute_adapter_required")
        info = executable.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid in (0, os.geteuid())
                and not info.st_mode & (0o022 | stat.S_ISUID | stat.S_ISGID)
                and os.access(executable, os.X_OK), "untrusted_adapter")
        self.argv = list(argv)
        dependencies = [] if dependencies is None else dependencies
        require(isinstance(dependencies, list) and all(isinstance(path, str) and Path(path).is_absolute()
                and Path(path).is_file() for path in dependencies), "invalid_adapter_dependencies")
        arguments = []
        for arg in argv[1:]:
            # Make executable/script/config resolution unambiguous. Fixed values
            # belong in a pinned config file, not inline Python/shell/module text.
            require(arg not in ("-c", "-m") and "=" not in arg, "ambiguous_adapter_invocation")
            if arg.startswith("-"):
                require(re.fullmatch(r"--?[A-Za-z][A-Za-z0-9-]*", arg), "ambiguous_adapter_invocation")
            else:
                path = Path(arg)
                require(path.is_absolute() and path.is_file(), "absolute_adapter_file_required")
                arguments.append(path)
        scorer = Path(sys.modules[verify_trial_bundle.__module__].__file__).resolve()
        self.pinned_files = sorted({str(path.absolute()) for path in
                                    (executable, Path(__file__), scorer,
                                     *arguments, *(Path(path) for path in dependencies))})
        self.fingerprint = self._fingerprint()

    def _fingerprint(self):
        files = {}
        for filename in self.pinned_files:
            path = Path(filename)
            info = path.stat()
            require(stat.S_ISREG(info.st_mode) and info.st_uid in (0, os.geteuid())
                    and not info.st_mode & 0o022, "untrusted_adapter_source")
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            files[filename] = {"resolved": str(path.resolve()), "sha256": digest.hexdigest()}
        return hashlib.sha256(encode({"argv": self.argv, "files": files})).hexdigest()

    def perform(self, operation, context, *, timeout_seconds):
        require(type(timeout_seconds) in (int, float) and 0 < timeout_seconds <= 1800,
                "invalid_operation_timeout")
        require(self._fingerprint() == self.fingerprint, "adapter_source_changed")
        context = copy.deepcopy(context)
        lock_fds = context.pop("_inherited_lock_fds", [])
        require(isinstance(lock_fds, list) and len(lock_fds) in (0, 2)
                and len(set(lock_fds)) == len(lock_fds)
                and all(type(fd) is int and fd >= 3 for fd in lock_fds),
                "invalid_inherited_locks")
        require(operation == "status" or len(lock_fds) == 2, "operation_locks_required")
        request = encode({"operation": operation, "context": context,
                          "timeout_seconds": timeout_seconds})
        # Stream only bounded stdout into memory; do not let a failed backend
        # fill either RAM or a temporary output file before its timeout.
        with tempfile.TemporaryFile() as incoming:
            incoming.write(request)
            incoming.seek(0)
            # A surviving supervisor retains locks if this runner is killed.
            # It owns/reaps the backend group; killing only the direct child
            # would leave close_fds grandchildren able to outlive world locks.
            alive_read, alive_write = os.pipe()
            bootstrap = [sys.executable, str(Path(__file__).resolve()), "_adapter_guard",
                         str(os.getpid()), str(alive_read), ",".join(str(fd) for fd in lock_fds) or "-",
                         *self.argv]
            try:
                child = subprocess.Popen(bootstrap, stdin=incoming, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, start_new_session=True,
                                         close_fds=True, pass_fds=(*lock_fds, alive_read))
            except BaseException:
                os.close(alive_write)
                raise
            finally:
                os.close(alive_read)
            deadline = time.monotonic() + timeout_seconds
            output = bytearray()
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(child.stdout, selectors.EVENT_READ)
                    while True:
                        left = deadline - time.monotonic()
                        require(left > 0, "operation_timeout")
                        require(selector.select(left), "operation_timeout")
                        chunk = os.read(child.stdout.fileno(), 65536)
                        if not chunk:
                            break
                        output.extend(chunk)
                        require(len(output) <= MAX_JSON, "json_too_large")
                child.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired as error:
                raise TrialError("operation_timeout") from error
            finally:
                # EOF asks the guard to terminate and reap its complete group.
                # Never SIGKILL the guard: it is the remaining lock owner after
                # runner death and may be waiting for a privileged descendant.
                os.close(alive_write)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired as error:
                    raise TrialError("guard_cleanup_pending") from error
                finally:
                    child.stdout.close()
            if child.returncode != 0:
                raise TrialError(adapter_failure_code(output))
            response = decode(output)
            require(isinstance(response, dict), "invalid_adapter_response")
            return response


class TrialRunner:
    def __init__(self, state_root, world_lock, queue_lock, adapter, *,
                 verify_bundle=verify_trial_bundle, monotonic=time.monotonic,
                 wall_time=time.time):
        self.root = Path(state_root).absolute()
        self.world_lock = Path(world_lock).absolute()
        self.queue_lock = Path(queue_lock).absolute()
        self.adapter = adapter
        self.verify_bundle = verify_bundle
        self.monotonic = monotonic
        self.wall_time = wall_time
        self.state = None
        self.deadline = None
        self.locked = False
        self.lock_fds = []

    def _context(self, *, recovery=False):
        context = {"schema_version": 1, "recovery": recovery}
        if self.state is not None:
            context.update(attempt_id=self.state["attempt_id"], request=self.state["request"],
                           attempt_dir=str(self.root / self.state["attempt_id"]),
                           adapter_fingerprint=self.state.get("adapter_fingerprint"),
                           receipts=copy.deepcopy(self.state["receipts"]))
        if self.locked:
            context.update(lock_owner_pid=os.getpid(),
                           lock_paths={"world": str(self.world_lock), "queue": str(self.queue_lock)},
                           _inherited_lock_fds=list(self.lock_fds))
        return context

    @contextmanager
    def _locks(self):
        # Existing world and queue ownership is established before creating any
        # runner directories or invoking an adapter, including status.
        with ExitStack() as stack:
            fds = [stack.enter_context(existing_lock(path))
                   for path in (self.world_lock, self.queue_lock)]
            require(len({(os.fstat(fd).st_dev, os.fstat(fd).st_ino) for fd in fds}) == 2,
                    "distinct_locks_required")
            private_directory(self.root, create=True)
            stack.enter_context(existing_lock(self.root / ".runner.lock", create=True))
            self.locked = True
            self.lock_fds = fds
            try:
                yield
            finally:
                self.locked = False
                self.lock_fds = []

    def _event(self, kind, **fields):
        event = {"sequence": len(self.state["events"]), "at_ms": int(self.wall_time() * 1000),
                 "kind": kind, **fields}
        self.state["events"].append(event)
        atomic_json(self.root / self.state["attempt_id"] / "journal.json", self.state)

    def _load(self, attempt_id, *, expected_sha256=None):
        require(isinstance(attempt_id, str) and ID.fullmatch(attempt_id), "invalid_attempt_id")
        private_directory(self.root / attempt_id)
        state = read_private_json(self.root / attempt_id / "journal.json", expected_sha256=expected_sha256)
        require(isinstance(state, dict) and type(state.get("schema_version")) is int
                and state.get("schema_version") == 1
                and state.get("attempt_id") == attempt_id
                and isinstance(state.get("events"), list) and state["events"]
                and isinstance(state.get("receipts"), dict), "invalid_journal")
        require(all(isinstance(e, dict) and e.get("sequence") == i
                    for i, e in enumerate(state["events"])), "invalid_journal")
        validate_spec(state.get("request"))
        return state

    def _require_no_unrecovered(self, proposed_id=None):
        import full_client_pre_runtime_abort as abort
        retired, certified_failed = abort.certified(self.root)
        require(proposed_id not in retired, "attempt_permanently_retired")
        for child in self.root.iterdir():
            if child.name.startswith("."):
                continue
            # Unknown/corrupt attempts are quarantines, never ignored.
            state = self._load(child.name)
            require(state.get("status") in ("completed", "recovered") or child.name in certified_failed, "recovery_required")

    def preflight(self, timeout_seconds=30):
        require(type(timeout_seconds) is int and 1 <= timeout_seconds <= 120,
                "invalid_preflight_timeout")
        status = self.adapter.perform("status", {"schema_version": 1, "recovery": False},
                                      timeout_seconds=timeout_seconds)
        return self._status(status, require_idle=False)

    def _status(self, status, *, require_idle):
        require(isinstance(status, dict) and all(type(status.get(k)) is bool for k in STATUS_FIELDS),
                "invalid_status")
        if require_idle:
            require(all(status[k] for k in STATUS_FIELDS if k != "ownership_conflict")
                    and not status["ownership_conflict"], "runtime_not_idle")
        return {k: status[k] for k in STATUS_FIELDS}

    def _call(self, operation, *, recovery=False):
        remaining = self.deadline - self.monotonic()
        require(remaining > 0, "trial_timeout")
        timeout = min(remaining, self.state["request"]["budgets"]["operation_seconds"])
        self.state["phase"] = operation
        self.state["phase_status"] = "pending"
        if operation == "run_controller":
            # Reserve before submitting anything; an absent response never refunds
            # uncertain provider usage and this attempt can never call it twice.
            require(self.state["api_outcome"] == "not_started", "api_replay_forbidden")
            self.state["api_outcome"] = "uncertain"
            self.state["charged_usage"] = {
                "api_requests": self.state["request"]["budgets"]["max_api_requests"],
                "total_tokens": self.state["request"]["budgets"]["max_total_tokens"]}
        self._event("operation_pending", operation=operation, timeout_seconds=timeout)
        started = self.monotonic()
        receipt = self.adapter.perform(operation, self._context(recovery=recovery), timeout_seconds=timeout)
        require(self.monotonic() - started <= timeout and self.monotonic() <= self.deadline,
                "operation_timeout")
        require(isinstance(receipt, dict), "invalid_adapter_response")
        encode(receipt)
        if operation != "status":
            require(receipt.get("attempt_id") == self.state["attempt_id"], "receipt_attempt_mismatch")
        self.state["receipts"][operation] = receipt
        self.state["phase_status"] = "returned"
        self._event("operation_returned", operation=operation)
        return receipt

    def _controller(self, receipt):
        spec, budgets = self.state["request"], self.state["request"]["budgets"]
        # Keep reported overspend even when an invalid receipt cannot confirm
        # the request's outcome. An exceeded reservation is never hidden.
        reported = {key: receipt[key] for key in ("api_requests", "total_tokens")
                    if type(receipt.get(key)) is int and 0 <= receipt[key] <= 2**63 - 1}
        for key, value in reported.items():
            self.state["charged_usage"][key] = max(self.state["charged_usage"][key], value)
        self._event("api_usage_reported", usage=reported)
        require(receipt.get("status") == "completed" and receipt.get("recording_complete") is True,
                "controller_incomplete")
        require(receipt.get("requested_model") == spec["model"]
                and receipt.get("returned_model") == spec["model"], "model_mismatch")
        for name, maximum in (("api_requests", budgets["max_api_requests"]),
                              ("output_tokens", budgets["max_output_tokens"]),
                              ("total_tokens", budgets["max_total_tokens"]),
                              ("actions", budgets["max_actions"]),
                              ("controller_ms", budgets["controller_seconds"] * 1000)):
            require(type(receipt.get(name)) is int and 0 <= receipt[name] <= maximum,
                    "usage_invalid_" + name)
        require((receipt["api_requests"] >= 1 if spec["schema_version"] == 2 else receipt["api_requests"] == 1)
                and (spec["schema_version"] == 1 or receipt.get("protocol") == spec["protocol"])
                and receipt["total_tokens"] >= receipt["output_tokens"],
                "usage_inconsistent")
        self.state["api_outcome"] = "confirmed"
        self.state["charged_usage"] = {k: receipt[k] for k in ("api_requests", "total_tokens")}
        self._event("api_usage_confirmed")

    def _quarantine(self, error):
        self.state["status"] = "interrupted" if not isinstance(error, Exception) else "failed"
        self.state["failure_code"] = str(error) if isinstance(error, TrialError) else "operation_failed"
        # Never include str(error) from adapters: it can contain credentials.
        self._event("recovery_required", phase=self.state["phase"], code=self.state["failure_code"])

    def run(self, spec, attempt_id=None):
        spec = validate_spec(spec)
        attempt_id = attempt_id or uuid.uuid4().hex
        require(isinstance(attempt_id, str) and ID.fullmatch(attempt_id), "invalid_attempt_id")
        with self._locks():
            self._require_no_unrecovered(attempt_id)
            attempt_dir = self.root / attempt_id
            require(not attempt_dir.exists() and not attempt_dir.is_symlink(), "attempt_exists")
            self.state = {"schema_version": 1, "attempt_id": attempt_id, "request": spec,
                          "adapter_fingerprint": getattr(self.adapter, "fingerprint", None),
                          "status": "running", "phase": "created", "phase_status": "complete",
                          "api_outcome": "not_started", "charged_usage": {"api_requests": 0, "total_tokens": 0},
                          "receipts": {}, "events": [], "publication_eligible": False}
            self.deadline = self.monotonic() + spec["budgets"]["total_seconds"]
            self.state["events"].append({"sequence": 0, "at_ms": int(self.wall_time() * 1000),
                                         "kind": "attempt_created"})
            staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=self.root))
            atomic_json(staging / "journal.json", self.state)
            # Hidden staging has no backend intent and is safe to ignore after a
            # crash. Once visible, every attempt already has a recoverable journal.
            publish_attempt(staging, attempt_dir)
            try:
                self._status(self._call("status"), require_idle=True)
                for operation in PHASES:
                    receipt = self._call(operation)
                    if operation == "run_controller":
                        self._controller(receipt)
                    elif operation == "collect_final":
                        evidence = receipt.get("evidence")
                        require(isinstance(evidence, dict) and evidence.get("run_id") == attempt_id,
                                "evidence_attempt_mismatch")
                        require(evidence.get("scenario_fingerprint") == spec["scenario_fingerprint"]
                                and isinstance(evidence.get("baseline"), dict)
                                and evidence["baseline"].get("sha256") == spec["baseline_sha256"],
                                "evidence_baseline_mismatch")
                        self.state["score"] = self.verify_bundle(evidence, attempt_dir, receipt.get("artifacts"))
                        self._event("evidence_verified")
                    elif operation == "cleanup":
                        require(receipt.get("clean") is True, "cleanup_unconfirmed")
                self._status(self._call("status"), require_idle=True)
                self.state["status"] = "completed"
                self._event("attempt_completed")
                return self.summary()
            except BaseException as error:
                self._quarantine(error)
                raise

    def recover(self, attempt_id, timeout_seconds=120, *, expected_journal_sha256=None):
        require(type(timeout_seconds) is int and 1 <= timeout_seconds <= 300, "invalid_recovery_timeout")
        with self._locks():
            self.state = self._load(attempt_id, expected_sha256=expected_journal_sha256)
            require(self.state.get("status") not in ("completed", "recovered"), "attempt_already_terminal")
            require(self.state.get("adapter_fingerprint") == getattr(self.adapter, "fingerprint", None),
                    "recovery_adapter_mismatch")
            self.deadline = self.monotonic() + timeout_seconds
            self.state["status"] = "recovering"
            self._event("recovery_started", interrupted_phase=self.state["phase"])
            try:
                status = self._status(self._call("status", recovery=True), require_idle=False)
                require(status["queue_idle"] and not status["ownership_conflict"], "recovery_conflict")
                receipt = self._call("cleanup", recovery=True)
                require(receipt.get("clean") is True, "cleanup_unconfirmed")
                self._status(self._call("status", recovery=True), require_idle=True)
                self.state["status"] = "recovered"
                self._event("attempt_recovered", outcome="invalid_no_retry")
                return self.summary()
            except BaseException as error:
                self._quarantine(error)
                raise

    def summary(self):
        return {key: self.state[key] for key in ("attempt_id", "status", "phase", "api_outcome",
                                                "charged_usage", "publication_eligible")}


def main(argv=None):
    import full_client_operation_admission as admission
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter-config", required=True, type=Path,
                        help="Private JSON {argv:[absolute executable, fixed file arguments],dependencies:[absolute files]}")
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--world-lock", required=True, type=Path)
    parser.add_argument("--queue-lock", required=True, type=Path)
    admission.add_arguments(parser, inherited=True)
    sub = parser.add_subparsers(dest="command", required=True)
    preflight = sub.add_parser("preflight", help="Read-only backend prerequisites/status; no locks or trial")
    preflight.add_argument("--timeout-seconds", type=int, default=30,
                          help="Read-only status deadline in whole seconds, 1–120 (default: 30)")
    run = sub.add_parser("run")
    run.add_argument("--request", required=True, type=Path)
    run.add_argument("--attempt-id")
    recover = sub.add_parser("recover")
    recover.add_argument("--attempt-id", required=True)
    recover.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args(argv)
    try:
        require((args.operation_recovery is None and args.operation_recovery_sha256 is None)
                or (args.command == "recover" and args.operation_envelope is not None),
                "operation_recovery_forbidden")
        config = read_private_json(args.adapter_config)
        require(isinstance(config, dict) and set(config) == {"argv", "dependencies"}, "invalid_adapter_config")
        runner = TrialRunner(args.state_root, args.world_lock, args.queue_lock,
                             CommandAdapter(config["argv"], config["dependencies"]))
        if args.command == "preflight":
            result = {"status": "preflight", **runner.preflight(args.timeout_seconds)}
        else:
            require(sys.platform.startswith("linux") and os.geteuid() == 0, "linux_root_required")
            require(isinstance(args.attempt_id, str) and ID.fullmatch(args.attempt_id), "explicit_attempt_id_required")
            actual_config, config_ref = admission.private_ref(args.adapter_config)
            require(actual_config == config, "adapter_config_changed")
            request, request_ref = (admission.private_ref(args.request) if args.command == "run" else (None, None))
            if any(value is not None for value in (args.operation_envelope, args.operation_envelope_sha256,
                                                    args.operation_fd)):
                with admission.inherited_trial(args, config_ref, request, request_ref) as joined:
                    # The join descriptor stays here; it is never forwarded to
                    # CommandAdapter or its two-descriptor world/queue bridge.
                    if args.command == "recover":
                        result = runner.recover(args.attempt_id, args.timeout_seconds,
                            expected_journal_sha256=joined["recovery"]["journal"]["sha256"])
                    else:
                        result = runner.run(request, args.attempt_id)
            else:
                authority_ref, claim_ref = admission.argument_refs(args, reconcile=args.command == "recover")
                authority = admission.gate.read_ref(authority_ref, 0, admission.gate.Budget())
                require(authority["operation_id"] == args.attempt_id, "operation_attempt_mismatch")
                if args.command == "recover":
                    request_ref = authority["subject"]["request"]
                    request = admission.gate.read_ref(request_ref, 0, admission.gate.Budget())
                subject = admission.trial_subject(args, config_ref, request_ref)
                with admission.admitted(authority_ref, subject, "standalone_trial", args.state_root,
                        claim_ref=claim_ref, required_sources=(__file__,)) as operation:
                    if operation.completed:
                        result = {"status": "operation_already_completed", "attempt_id": args.attempt_id,
                                  "terminal": operation.terminal, "new_api_requests": 0}
                    else:
                        if args.command == "run":
                            result = runner.run(request, args.attempt_id)
                        else:
                            saved = runner._load(args.attempt_id)
                            require(saved["request"] == request, "recovery_request_mismatch")
                            if saved["status"] in ("completed", "recovered"):
                                # Resolve a lost closeout reply without replaying
                                # either the trial or its cleanup operations.
                                runner.state = saved
                                result = runner.summary()
                            else:
                                result = runner.recover(args.attempt_id, args.timeout_seconds)
                        evidence = admission.trial_terminal(runner, args.attempt_id, request)
                        result["operation_terminal"] = operation.finish(evidence)
        print(json.dumps(result, sort_keys=True))
        return 2 if args.command == "preflight" and not result["ready"] else 0
    except (Exception, KeyboardInterrupt) as error:
        code = str(error) if isinstance(error, (TrialError, admission.gate.GateError)) else "runner_failed"
        print(json.dumps({"status": "blocked", "code": code, "publication_eligible": False}))
        return 1


def _stop_backend_group(child):
    """Keep inherited world locks until the entire backend group is gone.

    A privileged descendant that cannot be signalled is an operator blocker;
    do not exit/release locks while it can still mutate the world. The trusted
    backend must not detach untracked descendants into other process groups.
    """
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    while True:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass  # Retain locks and wait; never mistake EPERM for an empty group.
        child.poll()
        # Linux subreaper adopts killed backend grandchildren, including workers
        # started with close_fds=True. Reap their zombies before releasing locks.
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
                if pid == child.pid:
                    child.returncode = os.waitstatus_to_exitcode(status)
            except ChildProcessError:
                break
        try:
            os.killpg(child.pid, 0)
        except ProcessLookupError:
            if child.returncode is not None:
                return
        except PermissionError:
            pass
        time.sleep(0.02)


def adapter_guard(argv):
    """Private supervisor; ancestry/inode checks still authorize backend operations."""
    child = None
    try:
        parent = int(argv[0])
        alive_fd = int(argv[1])
        lock_fds = [] if argv[2] == "-" else [int(value) for value in argv[2].split(",")]
        require(len(lock_fds) in (0, 2) and len(set(lock_fds)) == len(lock_fds)
                and all(fd >= 3 and fd != alive_fd for fd in lock_fds), "invalid_guard_locks")
        if os.getppid() != parent:
            return 126
        if sys.platform.startswith("linux"):
            import ctypes
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
                return 126
        request = decode(sys.stdin.buffer.read(MAX_JSON + 1))
        require(isinstance(request, dict) and isinstance(request.get("context"), dict), "invalid_guard_request")
        timeout = request.get("timeout_seconds")
        require(type(timeout) in (int, float) and 0 < timeout <= 1800, "invalid_guard_timeout")
        request["context"].update(guard_pid=os.getpid(), guard_parent_pid=parent)
        request["context"]["lock_fds"] = dict(zip(("world", "queue"), lock_fds))
        deadline = time.monotonic() + timeout
        # The guard's own process group deliberately differs from the backend.
        # SIGTERM requests cleanup; SIGKILL of the guard is never a recovery step.
        def interrupted(_signum, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        with tempfile.TemporaryFile() as incoming, selectors.DefaultSelector() as selector:
            incoming.write(encode(request))
            incoming.seek(0)
            selector.register(alive_fd, selectors.EVENT_READ)
            if os.getppid() != parent or selector.select(0):
                return 126
            child = subprocess.Popen(argv[3:], stdin=incoming, stdout=sys.stdout.buffer,
                                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
                                     pass_fds=tuple(lock_fds))
            while child.poll() is None:
                left = deadline - time.monotonic()
                if left <= 0 or os.getppid() != parent or selector.select(min(left, 0.05)):
                    return 124
            return child.returncode if child.returncode >= 0 else 125
    except (OSError, ValueError, IndexError, TrialError, KeyboardInterrupt):
        return 126
    finally:
        if child is not None:
            _stop_backend_group(child)


if __name__ == "__main__":
    raise SystemExit(adapter_guard(sys.argv[2:]) if len(sys.argv) > 1 and sys.argv[1] == "_adapter_guard"
                     else main())
