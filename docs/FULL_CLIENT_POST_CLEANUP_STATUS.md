# Status-only reconciliation after successful cleanup

`full-client-post-cleanup-status-v1` is an explicit operator protocol for one
narrow failure: the original recovery child completed cleanup, returned a clean
backend receipt, then failed its final status check solely because `ready` was
false. It is not another recovery child, an API retry, a baseline restore, or a
way to accept an unsuccessful model attempt.

The operator in `scripts/full_client_post_cleanup_status.py` is separately pinned
and executed from new reviewed source. It imports the original authority-pinned
trial, operation, experiment and runtime modules. Existing source files, frozen
requests, recovery descriptors and terminal validators are not edited.

## Required private configuration

Supply a mode0600 canonical JSON file, pinned by its SHA256, with exactly:

- `schema_version`:1 and `kind`: `full-client-post-cleanup-status-v1`.
- `authority`, `claim`: the original finite-group authority and pending claim.
- `recovery`: the existing immutable one-child recovery descriptor.
- `coordinator`: the exact current unchanged coordinator journal.
- `journal`: the current failed post-cleanup trial journal.
- `backend`: the exact clean backend-state artifact.
- `runtime`: the original runtime configuration referenced by the original adapter.
- `original_source`: the canonical original scripts directory.
- `implementation`: the exact new operator script path and SHA256.
- `waiting_transition`: the exact fresh waiting transition independently prepared
  by the operator through the ordinary browser path.
- `timeout_seconds`: an integer from1 through120 for the read-only observation.

All fields described as references are exact `{path,sha256}` objects. Do not put
this configuration, runtime paths, account state or evidence into Git. Invoke the
script directly with `--config` and `--config-sha256` under the existing bounded
Linux/root operator environment. Preparing the configuration performs no runtime
action; execution is a distinct explicitly authorized operator step.

## Preconditions and observations

The operator reacquires the original operation claim, coordinator lock, existing
world/queue locks and runner lock, in that order. It does not replace locks or
create a new claim. The current attempt must remain the last submitted unresolved
entry; prior submissions must be terminal-clean and future attempts absent.

The failed recovery must append exactly this suffix to its preserved original
failed journal: recovery started; status pending/returned; cleanup
pending/returned; status pending/returned; recovery required with
`runtime_not_idle` at the returned status phase. The returned status must have
all normal conditions true except `ready:false`, with `ownership_conflict:false`.
The backend must be clean, without a pending operation; any recorded owned
configuration removal must have reached its verified checkpoint. Request,
attribution/accounting fields, earlier receipts and event history must match.

The new read-only operational predicate uses original small-pin/process-identity
and status helpers. It verifies stopped world/worker/Cosmic services, an empty
queue, offline account, and absence of both the exact on-disk trial drop-in and
systemd's cached trial settings. The existing browser must be on the requested
waiting transition with fresh/pinned/settled state and idle capture. Only an idle
bridge or this attempt's terminal bridge is accepted, with no worker, pending
leases, release or corrupt-run quarantine.

It never calls a runtime mutation method, patches a method, fabricates guard
ancestry, launches another trial/recovery child or issues game input. The original
recovery CLI cannot provide this path: its guard ancestry belongs to the original
trial process, and it would attempt cleanup again. Conversely, the ordinary
preflight rehashes the full old inventory, which can be stale after an OS package
update. This operator explicitly records `inventory_revalidated:false`. Fresh
source/runtime freezing remains a prerequisite for future trials.

## Evidence and failure handling

Before observing runtime, preserve the current failed journal byte-for-byte as
`<attempt>.status-failed-journal.json` beside the original recovery descriptor.
The original `<attempt>.failed-journal.json` remains unchanged too. Save an
immutable `<attempt>.status-proof.json` binding the operator configuration,
preimage, clean backend, original recovery descriptor and actual observation.

Only after the original strict status validator accepts the observed booleans,
and pinned inputs still match, atomically append a
`post_cleanup_status_reconciled` event and set the attempt to `recovered`.
The new event is explicitly unscored, with zero new API and cleanup calls.
Preserve the prior failure code, entire history, request, original API outcome,
charged usage and publication-ineligible flag. Only the current status receipt,
terminal status and appended event change. Backend and coordinator bytes do not.

The unchanged original terminal validator must accept the resulting journal and
clean backend before writing `<attempt>.status-complete.json`. A lost write reply
is recognized from the exact proposed saved journal/proof; it never repeats
cleanup. If a proof was saved before the journal write, another explicit invocation
may perform only a fresh read-only observation before applying it. Proof schema,
status, transition and timestamps are validated before either retry branch.

The original `recover-entry` can subsequently acknowledge saved terminal evidence
without dispatching another child. The group claim stays pending until its ordinary
resume/seal path closes it. This protocol does not perform that closeout, add a
score, publish the attempt, forgive uncertain API usage or authorize future runs.

Synthetic tests use real local gate/coordinator/world/queue/runner flocks and the
unchanged terminal validator. They cover failed readiness, changed accounting,
missing cleanup, dirty backend/configuration, hash changes, exact input/proof
schemas, changed waiting transitions and lost write replies. Native operator
execution and final group closeout still require separate verification.
