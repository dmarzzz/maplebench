# Operations admission and normal-service handoff

Current source commands acquire one shared operations gate before trial or
lifecycle world locks. It stays held between a finite group's child trials and
throughout restoration. `full_client_operations.py` composes the coordinator,
permanent closure, persisted-state handoff and existing normal lifecycle.

**This is a source contract, not a deployed acceptance claim.** No live operations
registry has been initialized. The existing protected runtime and historical
trial journals remain unchanged. A new protected release, pinned authority and
bounded end-to-end acceptance are required before live use.

## Gate and authority

Explicit `initialize_registry(existing_attempt_root)` creates only a private
`.operations/.gate.lock` beneath the existing canonical attempt root. It returns
the actual device/inode pin. Existing or partial registries are refused; setup
never creates an attempt root or world lock. Production requires root ownership,
directory mode 0700 and file mode 0600. Test owners must equal the effective user.

`OperationGate(root,pin).locked()` acquires that existing gate nonblockingly.

| Method | Required evidence | Result |
| --- | --- | --- |
| `begin(id,kind,authority)` | New ID, private authority, no pending/malformed claim | Create-only fsynced claim |
| `reconcile(claim)` | Exact existing claim and no other pending claim | Pending state or original terminal marker; no replay |
| `complete(receipt)` | Active claim and exact terminal evidence | Create-only fsynced terminal marker |
| `ensure_available()` | Unclaimed local lease; no pending/malformed claim | Read-only admission without consuming an ID |

`full_client_operation_admission.py` validates an authority with exact fields
`schema_version:1`, `operation_id`, `kind`, `gate`, `subject`, `source_files`.
The ID is 32 lowercase hexadecimal characters. Gate fields are the actual
`path`, `device`, `inode`, `uid`, `mode`. Source references use `{path,sha256}`
and include the actual gate, join, admission, entrypoint and required dependencies.

| Entry point | Exact subject fields |
| --- | --- |
| Trial | `type:"trial"`, `attempt_id`, `adapter_config`, `request`, `state_root`, `world_lock`, `queue_lock` |
| Standalone experiment | `type:"experiment"`, `plan`, `experiment_directory` |
| Standalone normal lifecycle | `type:"lifecycle"`, `config`, `handoff`, `lifecycle_id` |
| Composed operations | `schema_version:1`, `plan`, `experiment_directory`, `normal_config`, `historical_attempts`, `initial_snapshot`, `output_directory`, `restoration_operation_id`, `limits` |

Input references use `{path,sha256}`. Standalone trial/lifecycle operation IDs
equal their preallocated attempt/lifecycle IDs. A finite group's operation UUID
is separate from its human-readable experiment ID; the subject pins plan bytes.

Trial `run/recover`, experiment `run/resume/seal`, and lifecycle
`check/start/reconcile` require `--operation-authority` and
`--operation-authority-sha256`. Explicit recovery, resume, seal and reconciliation
also require `--operation-claim` and `--operation-claim-sha256`. Initial commands
refuse old claims. Lifecycle `check` holds the gate without writing a claim.
Read-only trial preflight, plan creation and reporting remain ungated.

Global flags precede the subcommand for trial/lifecycle; experiment flags follow
its subcommand. Earlier examples without these flags describe the older protected
release and are insufficient authority for current mutation. Commands never
initialize a missing registry. New rollout must freeze all updated entrypoints.

Completed standalone commands bind actual terminal evidence before closing
their claims. Experiments are sealed first. Lost completion replies are resolved
from actual completed bytes without replaying the trial or cleanup. Exceptions
and owner exit leave durable pending claims blocking unrelated work. Completed
IDs cannot be reused. Closing a lease closes only its own descriptor, never
another copy of the open description.

## Child admission

`full_client_operation_join.py` duplicates only a local pending lease. The parent
publishes a create-only envelope under its authority directory's
`.operation-dispatch/<operation_id>/`, then passes exactly that extra FD to the
trial CLI. Before world locks, the child independently binds its actual
request/config/plan, current coordinator submission, protected parent
script/interpreter, exact argv, direct parent PID/start ticks/boot and gate inode.

Linux `fdinfo` must prove the same exclusive FLOCK owner on both descriptions.
Reasserting the inherited lock and refusing an independently opened description
are both required; matching an inode alone is insufficient. Entry markers are
create-only, and uncertainty never authorizes repeating a dispatch. The parent
keeps its exported FD open through child completion. The bridge still receives
exactly the original **two** world/queue FDs; the operations FD stays outside it.

Envelope preparation follows the coordinator's fsynced submission intent and
precedes its final deadline recomputation. Its time counts against the original
budget. Only a synchronous known refusal before launcher entry can retire an
unlaunched ID. Missing evidence is not proof that no API call occurred.

## Finite group and restoration

The wrapper exposes create-only `run --authority ... --sha256 ...`, exact
`reconcile --journal ... --sha256 ...`, and read-only `report`. Its authority
predeclares every entry and reserves admission, experiment, handoff and
restoration time separately. Original wall and monotonic deadlines are retained;
there is no automatic extension or model retry.

After the group stops, every submitted attempt must be terminal and clean,
settled hashes unchanged, and unsubmitted/retired IDs absent. The coordinator is
sealed before restoration. Missing, corrupt, changed, or failed-without-recovery
outcomes leave admission pending. Reports retain partial, zero, negative and
no-op results.

`full_client_operations_handoff.py` requires actual lifecycle serialization and
the three existing world/queue/runner locks. It verifies the complete attempt
inventory, actual final persisted character/keymap, offline account, stopped
service invocations, current web process, fresh settled waiting browser, idle
queue, capacity, pinned sources/configuration and append-only native log. It
atomically publishes three private files: offline snapshot, handoff and preparation
evidence. It performs no service or database mutation and renews no deadline.

Expected state comes from the last actual persisted final artifact, preserving
earned XP and HP changes. A recovered last attempt without a final persisted
artifact requires separate restoration-only reconciliation; this version cannot
invent one. The initial snapshot is usable only when no trial launched and the
complete original inventory is unchanged.

Preparation's world locks close before the normal lifecycle starts, while the
operations gate remains held. Completion requires the same Cosmic through worker
startup, actual native descriptor/listener evidence, worker first-idle receipt
and final quiet checks. Only then may the outer claim complete. Reconciliation
never calls experiment run/resume or trial recover. Uncertain service intents
use the existing exact-instance observation path.

## Validation and release gates

The final combined serialized, memory- and CPU-capped runtime-host job passed
**222 tests** across gate, join, admission, handoff, coordinator, trial, normal
lifecycle, complete wrapper and root CLI integration. It included real Linux
FLOCK/parent-child/guard checks, synthetic two-entry restoration with zero and
negative scores, actual CLI dispatch into an unready status-only backend, lost
service-start/completion replies, and altered recovery journals. The root CLI
checks also prove the extra gate FD never reaches the guard/backend. All passed
in 22.140 seconds under 1,536 MiB, two CPUs and a 270-second hard job deadline.
These are synthetic tests: zero API calls and no live game/service changes.

Remaining work includes protected rollout, explicit setup/pause authority,
acceptance of the full finite group through restored normal service, and
restoration-only authority when an original deadline expires or recovered
persisted evidence is unavailable. Shared-host capacity and visual publication
review remain independent gates.

The gate checks receipt integrity; integrating callers prove terminal semantics.
A boolean alone cannot prove gameplay, saved XP or service restoration.
File/inventory/read-work bounds supplement hard process limits. Protected
ancestors and imported trusted libraries remain host assumptions; this is not
a sandbox against arbitrary root code. No timeout waiver, claim deletion,
lock takeover or arbitrary borrowed-FD bypass exists.
