# Durable full-client attempt runner

`scripts/full_client_trial.py` coordinates one full-client trial through a
trusted host adapter. It supplies exclusive locks, a durable phase journal,
bounded operations, conservative API accounting, and explicit recovery. It does
not contain database credentials, choose a baseline, start a default world, or
provide a complete live browser lifecycle adapter. Synthetic tests establish
runner behavior only. A working demo and an offline score do not establish a
production-verified ranked trial path.

## Invocation and private configuration

All runtime paths must remain outside public source or inside ignored runtime
directories. The state root and attempt directories must be owned by the runner
user with mode 0700; JSON configuration and request files must be mode 0600.
Use canonical absolute paths without symlink components. The two lock files
must already exist: supply the same world and queue locks used by the existing
worker. The runner will never create replacement world/queue locks or stop a
competing owner to acquire them.

```sh
python3 scripts/full_client_trial.py \
  --adapter-config /private/runtime/adapter.json \
  --state-root /private/runtime/full-client-attempts \
  --world-lock /private/runtime/existing-world.lock \
  --queue-lock /private/runtime/existing-queue.lock \
  preflight
```

The paths above are placeholders, not runnable host configuration. `preflight`
only invokes adapter `status`; it does not acquire locks, create runner files,
or start a trial. False readiness is printed as false. The installed backend
must report missing lifecycle hooks or positive save evidence as not ready.
Ready preflight exits 0; not-ready preflight exits 2; runner/configuration
failures exit 1 with a safe code.
The read-only deadline defaults to 30 seconds. Use
`preflight --timeout-seconds 120` for a cold-cache inventory; only whole seconds
from 1 through 120 are accepted. This does not change any actual trial budget.

For a separately authorized trial, replace `preflight` with
`run --request /private/runtime/request.json`. A random attempt ID is generated,
or `--attempt-id` supplies an immutable operator ID. Reusing an attempt ID is
rejected even after success or recovery. There is no batch, automatic retry,
resume, or background-run mode.

Private `adapter.json` contains exactly `{"argv":["/absolute/trusted/executable",
"/absolute/backend.py","--config","/absolute/private-config.json"],
"dependencies":["/absolute/imported-backend-module.py"]}`. The executable must be owned by root or the runner
user and not writable by group or others. The operator must pin and protect any
script/config arguments and their parent directories too. **argv is host
configuration; never construct it from model output or a trial request.** The
runner executes it directly with no shell. Do not place credentials in argv;
the trusted backend reads private host credentials itself.
Setuid/setgid adapter executables are rejected. Relative script/config paths,
inline `-c`/`-m` invocation, `--config=/path` forms, and positional inline values
are rejected. Use separate flag/file arguments and put fixed settings in a
pinned file. File arguments must be existing absolute regular files; mutable
output directories arrive through the validated request/context instead.

`CommandAdapter` hashes the fixed argv, executable, existing absolute file
arguments, explicit imported-file dependencies, runner bootstrap, and scorer
source at construction. Supply every immutable imported backend/helper/config
file in `dependencies`; an empty list is valid only for a self-contained entry
point with no additional imports or configuration files. It records that
fingerprint in the attempt and verifies those bytes before every command.
Recovery requires the original fingerprint; a changed backend cannot silently
reinterpret a pending reset. Run from a protected frozen source snapshot, keep
configuration/baseline file references absolute, and do not edit source/config
mid-attempt. Changes to data inside a configured directory still require the
backend's explicit frozen-baseline/artifact verification.

The request contains exactly:

```json
{
  "schema_version": 1,
  "model": "gpt-6-astra",
  "scenario_fingerprint": "<64 lowercase hex characters>",
  "baseline_sha256": "<64 lowercase hex characters>",
  "budgets": {
    "total_seconds": 600,
    "operation_seconds": 120,
    "controller_seconds": 60,
    "max_actions": 200,
    "max_api_requests": 1,
    "max_output_tokens": 3000,
    "max_total_tokens": 12000
  }
}
```

Fingerprints above are placeholders, not real baseline evidence. Budgets require
strict integers and have hard upper bounds: 1800 seconds total, 300 seconds per
operation/controller, 10,000 actions, one API request, 32,000 output tokens, and
1,000,000 total tokens. The backend must enforce controller, action, and token
limits before expenditure; the runner independently rejects receipts exceeding
them. Provider-side uncertain usage is charged at the full reserved token and
request budget. These are per-attempt bounds, not an integrated queue-wide
spending ledger.

## Adapter contract

Python adapters implement
`perform(operation, context, *, timeout_seconds) -> dict`. The production
`CommandAdapter` sends a single JSON object on stdin:

```json
{"operation":"status","context":{"schema_version":1,"recovery":false},"timeout_seconds":30}
```

It expects exactly one finite JSON object on stdout. Duplicate keys, oversized
responses, failed exit status, timeouts, and malformed JSON fail closed. stderr
is not printed or copied into journals because command errors can expose
credentials. Backend responses must contain only safe evidence/identifiers;
raw credentials never belong in receipts. Exceptions are not evidence.

After lock acquisition, context also contains:

- `attempt_id`, `attempt_dir`, and the validated `request`.
- `receipts`, containing the responses already recorded for this attempt.
- `lock_owner_pid`, the live runner's PID.
- `lock_paths: {world: absolute_path, queue: absolute_path}`.
- `lock_fds: {world: integer, queue: integer}`, the inherited descriptors in the
  trusted backend (empty during unlocked preflight).
- `guard_pid` and `guard_parent_pid`, added by the operation supervisor.
- `recovery`, true only during explicit cleanup recovery.

The trusted Linux backend must independently verify the lock owner's identity
and exact configured lock inodes in `/proc/locks`. For `CommandAdapter`, its
direct parent's PID must equal `guard_pid`, the live guard's `/proc` parent
must equal `guard_parent_pid` and `lock_owner_pid`, and the frozen guard
executable/source identity must match the configured runner. Supplied booleans or arbitrary
lock paths are not permission to mutate a world. The backend must compare
`fstat` of both supplied descriptors with its configured lock inodes before
using them. The backend must check its
own configured paths, inactive worker/demo helper, queue state, server instance
ownership, and account/session state before each destructive operation. It must
not resume a paused external owner or alter a server it did not start.

| Operation | Required behavior and response |
| --- | --- |
| `status` | Read-only checks. Return booleans `ready`, `queue_idle`, `server_stopped`, `account_offline`, `controller_idle`, `ownership_conflict`. `ready` also checks backend prerequisites, including lifecycle hooks and save instrumentation. |
| `restore_baseline` | While holding both locks and with Cosmic stopped, verify the pinned baseline/scenario, restore, and collect initial offline evidence. Return `attempt_id` plus real restore/initial receipts. |
| `start_server` | Start only the configured fresh server for this attempt and record its unique instance ID. Return `attempt_id` plus start evidence. |
| `login` | Use ordinary single-client login and verify its character/session. Return `attempt_id` plus login evidence. |
| `run_controller` | Submit at most one API request, execute bounded control, and finish recording/upload. Return the fields below. No provider retries, fallback model, or request replay. |
| `disconnect` | Request ordinary logout/disconnect, wait for offline status and actual save completion. A server kill is not logout. Return `attempt_id` plus session/save evidence. |
| `collect_final` | Collect the final offline row, complete server/session log checks and artifacts. Return `{attempt_id,evidence,artifacts}` for `verify_trial_bundle`. |
| `cleanup` | Reconcile only this attempt's resources and leave no active server/controller/session. Return `{attempt_id,clean:true}` only after verification; never take over unrelated ownership. |

Every operation except `status` must return the exact `attempt_id`. A successful
`run_controller` response also requires:

```json
{
  "attempt_id": "the-current-attempt",
  "status": "completed",
  "requested_model": "gpt-6-astra",
  "returned_model": "gpt-6-astra",
  "api_requests": 1,
  "output_tokens": 800,
  "total_tokens": 2000,
  "actions": 77,
  "controller_ms": 59000,
  "recording_complete": true
}
```

These values are illustrative. Record actual usage and both model identities;
an unconfirmed response retains the full reservation. `collect_final.evidence`
uses [the persistence contract](FULL_CLIENT_TRIALS.md), while `artifacts` binds
the real baseline, scenario, snapshot exports, positive native save journal,
session log, reset evidence, and persistence JSON beneath this attempt's private
directory. The runner calls `full_client_score.verify_trial_bundle` before
cleanup/completion. Missing native save receipts cannot be synthesized from
offline status or absence of errors. Publication eligibility stays false.

Each command has a monotonic deadline no later than the remaining trial budget.
A separate supervisor inherits and retains both world-lock descriptors, starts
the backend in its own process group, and watches a liveness pipe whose only
writer is the runner. Runner death or timeout closes that pipe. The supervisor
then kills the backend group and, on Linux, adopts/reaps grandchildren using
`PR_SET_CHILD_SUBREAPER` before releasing the locks. This covers descendants
started with `close_fds=True`, rather than relying on a death signal that only
reaches the direct adapter. It also removes leftover group members after normal
backend completion. No Python `preexec_fn` runs in a forked threaded process.
The guard passes only those two descriptors to the trusted backend, retains
its own copies, and never passes the runner liveness descriptor. The backend
uses `close_fds=True` for subprocesses. Its only intentional descriptor transfer
is `SCM_RIGHTS` over the private local control socket to the trusted bridge, so
the bridge can retain world ownership for its controller's lifetime. Lock
descriptors must never reach the evaluated SDK or sandbox. Non-Linux
hosts lack the subreaper guarantee and are not the production runtime target.

Every participant releases only its own descriptor copies with `close`.
**Never call `flock(LOCK_UN)` on these shared descriptions**: that would revoke
the bridge's lease too. A bridge that retained `SCM_RIGHTS` copies must continue
excluding a new world owner after the runner and guard close their own copies,
until the bridge completes settlement and closes its lease descriptors.

The runner never SIGKILLs this supervisor. If a privileged descendant cannot
be killed, the supervisor retains ownership until the group has gone; the
runner reports `guard_cleanup_pending` after its bounded cleanup wait and
quarantines the attempt. This exceptional retained lock is an operator blocker,
not permission to take over ownership. Never kill the guard or remove its locks
to bypass that condition. The backend must not detach untracked workers into
other process groups or leak the runner liveness-pipe writer. Service processes
deliberately launched outside the operation group still need explicit attempt
ownership and recovery checks.

The backend must apply that deadline to its own subprocesses, database transactions,
service waits, HTTP calls, and recording transfers. It must never detach
untracked reset/controller workers. An API request may have reached its provider
even when its local process is killed. Declared server processes can outlive a
crash; ownership and recovery must account for them explicitly. In-process
adapters are intended for tests; a returned elapsed time is checked, but only
`CommandAdapter` supplies the external process timeout.

## Crash and recovery behavior

The runner acquires world, queue, and runner locks nonblocking. A world/queue
conflict fails before adapter calls or creating runner state. It holds both
world locks through final evidence verification and cleanup. An unknown,
corrupt, incomplete, or failed attempt blocks new attempts under the same state
root. Use one fixed protected state root per configured world; changing it to
evade quarantine is not recovery.

`<attempt_id>/journal.json` contains status, phase, receipts, reserved/confirmed
usage, and the complete ordered event history. Each update uses a mode-0600
temporary file, file fsync, atomic replacement, and directory fsync. The entire
`operation_pending` intent is durable **before** calling the adapter. A crash
after a side effect but before its response remains an uncertain pending phase.
Incomplete temporary files are not completion evidence. A journal or attempt
directory that cannot be read is preserved and blocks execution.

Initial creation first builds a private hidden staging directory containing the
complete fsynced initial journal, then atomically publishes it with a no-replace
rename and fsyncs its parent. An interrupted initializer therefore cannot leave
an empty visible attempt. Hidden `.staging-*` orphans contain no backend intent
and are ignored under the locks; their unpublished IDs have not started a trial.
Linux `renameat2(RENAME_NOREPLACE)` and macOS `renamex_np(RENAME_EXCL)` are used;
unsupported atomic-publish platforms fail closed. Existing IDs are never
overwritten, including empty directories created by older runner versions.

Before `run_controller`, the full API budget is charged and its outcome marked
uncertain. Actual usage replaces the reservation only after receipt validation.
An interruption never silently refunds API usage. The same attempt never sends
another model request, including after recovery.

On failure the runner records a safe error code and quarantines the attempt.
It does not automatically reset, kill the server, or resume the controller.
After inspecting ownership and pending work, explicit recovery uses:

```sh
# Supply the same private --adapter-config/--state-root/--world-lock/--queue-lock.
python3 scripts/full_client_trial.py [private options] recover \
  --attempt-id the-interrupted-attempt --timeout-seconds 120
```

Recovery acquires the same locks, journals its intent, checks queue/ownership,
invokes only cleanup, and verifies idle status. It never restores a baseline,
logs in, resumes gameplay, or calls the model. Cleanup failure preserves the
quarantine. Success marks the old attempt `recovered`, still invalid and with
its original API charge retained. A separately authorized new attempt needs a
new ID and starts from baseline restoration. Old or externally created visible
attempts without a complete journal need operator evidence reconciliation;
there is no automatic journal repair that could erase unknown side effects.

## Validation boundary

The read-only runtime freezer accepts a private `extra_files` list of absolute
file paths for the served index page, controller, waiting page, web wrapper,
and every explicitly configured imported source outside the scripts/WZ roots.
Its manifest always contains `extra_files` as a sorted list of `{path,sha256}`
references, including an empty list when none were requested. Verification
rebuilds these same pins and detects changed or missing bytes. File counts,
total bytes, and the inventory deadline are shared with all other inputs;
repeated paths within the extra list are rejected. Dependencies already in a
scanned tree are hashed once while retaining the explicit extra reference.

The freezer does not discover or execute imports. The runtime backend must
require its complete dependency list and bind the active web process, served
build paths, and wrapper to these exact pins before and after the trial. Pins
alone do not prove which code a process loaded. Existing manifests need to be
regenerated to include the required `extra_files` field.

`test/test_full_client_trial.py` uses synthetic adapters, real temporary-file
locks, process exits at reset/API boundaries, failed cleanup, deadlines,
attribution/usage errors, malformed responses, and Linux runner-kill/orphan-lock
verification. Run focused tests only under
the repository's shared-host resource limits, serialized with all other jobs.
These tests do not claim a live database restore, browser login/logout,
authoritative scored run, or production publication. Those remain release gates
until the concrete trusted backend completes and its actual evidence passes
the independent artifact verifier.
