# Native XP-window acceptance envelope

`native-xp-ledger-acceptance-v1` is a separate zero-model acceptance protocol.
The read-only verifier in `full_client_native_xp_acceptance.py` does not launch a
world, grant locks, restore a database, or accept adaptive API evidence. The
existing adaptive window verifier remains unchanged.

The frozen scenario binds the ordinary finite native recipe, baseline hash,
experience-table hash and normalization. The original native `result.json` and exact program bytes are mandatory hashed
artifacts. Completed terminal state, native contract, null model/API/trial context,
accepted SDK steps and counters, program fingerprint and measured wall interval
are checked directly. Normalized control values are derived from those originals
and must match exactly; a standalone normalized success claim is insufficient.
The executor must separately prove its single submission intent. Control must make zero
API calls, use no model, and finish within the recipe's 30-second bound. The
session remains owned for a separate fixed 300-second interval. At most 301
compact status samples cover that interval with a monotonic clock, bounded gaps,
matching native identities and fresh rendering. The passive collector schedules
against the original absolute monotonic deadline and never retries uncertain
reads or writes. It accepts no control/action callback.

The accounting origin is the durable sample immediately before submission.
The original control evidence permits at most **five seconds to start**, followed
by at most **30 seconds of program execution**. Runtime samples therefore require
an inactive, completed controller by origin plus 35 seconds. Final verification
uses the actual recorded program start to tighten that deadline to start plus
30 seconds, and rejects an idle claim during the recorded program interval.
The pre-submission sample is exempt from that last check because it precedes the
run, even if both events share a millisecond timestamp. Completion is allowed
before the maximum duration; no extra inputs or waits are required.

This corrects a sampler/verifier mismatch that previously rejected valid delayed
starts at origin plus 30 seconds. It adds no control time: the five-second start
allowance and 30-second execution bound were already required by the original
control verifier. The 300-second accounting deadline, 45-second capture ceiling,
outer operation deadline, cleanup reserve and native recipe bytes stay fixed.
This source correction is not an acceptance claim for historical evidence.

The envelope independently checks the baseline/reset, offline initial/final
snapshots, ordinary logout chronology, persistence journal, native XP hash chain,
phase log and complete terminal save. It then calls the existing signed native
window scorer. At least one positive transaction inside the fixed interval is
required for the XP-hook acceptance result. Complete zero windows produce an
explicit insufficient-transaction result; missing coverage is rejected. Later
transactions remain part of persisted reconciliation but cannot prove the
in-window hook or improve its window score.

Returned windows are diagnostic. The result remains ineligible for publication
and requires separate visual acceptance; it does not claim level-up or loss-hook
coverage merely because those arithmetic unit tests passed.

## Executor library

`full_client_native_xp_runtime.NativeXpRuntime` implements the runtime phases for
this separate maintenance protocol. It accepts an operator-supplied ownership
checker and provides no dispatch CLI. `execute_owned` starts one finite native
recipe, collects the fixed 301-sample interval, performs ordinary logout, verifies
the original control/save/ledger evidence, stops its owned server and restores
the declared baseline. Model dispatch and publication entry points are refused.

The original native recording remains at most **45 seconds**, with at most
30 seconds of scripted control. Once control and upload settle, the executor
copies that recording while the character remains connected for the rest of the
300-second interval. Subsequent callbacks only read owned runtime status. It
does not manufacture a five-minute video or adaptive model cycles. After logout,
the normal read-only video probe and frozen capture-policy verifier check the
short recording. The XP result requires the separately verified 20 native
windows, exact ledger header observed at server startup, ordinary save and
offline database reconciliation. A complete zero-transaction interval remains
insufficient evidence for the positive XP hook.

The outer operation has a 900-second cap and reserves 180 seconds for cleanup.
Wrapper preflight consumes that original deadline. Executor entry requires at
least 720 seconds still available; it never creates a replacement 900-second
window. After inventory, enough foreground time for bounded startup, login,
300-second observation and 45-second collection must remain before any restore.
The same 345-second foreground check runs immediately before native submission.
Startup has a 90-second cap and login a 60-second cap. The owned transient game
service has an 840-second limit; the normal model runtime limit is unchanged.
No cap extends an infrastructure lease. Every phase remains subject to the
operator's earlier absolute deadline. Coverage uses the original monotonic
origin; slow sampling, copy/upload delay, stale rendering or an uncertain write
fails the interval instead of moving that origin.

Submission, ordinary logout and each SQL restore have durable intents. An
uncertain native submission cannot be issued again. An uncertain initial SQL
restore has no verified reset proof, so cleanup may only inspect the baseline,
not execute that SQL again. A final restore whose reply is lost likewise permits
inspection only. A failed preflight leaves its failure artifact and unclosed
state; it cannot authorize a cleanup mutation. Cleanup or ownership failure
cannot produce a clean completion receipt.

## Operator integration boundary

The library is a tested foundation, **not an executable acceptance plan**. Before
calling it, a separately reviewed private wrapper must:

- Pin the new source closure, immutable candidate JAR, runtime manifest, private
  baseline and current service identities. The runtime and scenario must both
  explicitly opt into `native-xp-ledger-acceptance-v1`; the runtime additionally
  declares `xp_window_protocol` and `native_xp_candidate_jar: {path, sha256}`.
  The candidate reference must equal the manifest's server JAR, and every module
  in `FROZEN_MODULES` must have its current bytes in the manifest. Normal frozen
  checks still require the native persistence and XP classes in the JAR.
- Reconcile the preceding admission claim as terminal, ensure admission is
  available, and hold the existing operation/world/queue/runner locks throughout.
  The injected checker must raise on lost lock, current service or ownership
  identity; it must not merely return a boolean. Scan other native operations
  under these locks and refuse any unclosed or mismatched prior operation.
- Choose a fresh native ID and server-instance ID, with private `attempt_root`
  and `api_attempt_root` that are separate and not nested. The API attempt tree
  never receives a native journal. The fresh native directory must contain only
  the initial `backend-state.json`; the same ID must not exist in relay or native
  output. Keep the outer intent/configuration beside this directory, not in it.
- Bind a hashed native input document with exactly `schema_version: 1`,
  `protocol`, `run_id`, `attempt_root`, `api_attempt_root` and `config_sha256`.
  The configuration digest uses `full_client_runtime.encoded(config)` (sorted,
  compact JSON plus a newline). Put that document reference in both the initial
  state and context as `native_input_reference`. Context also supplies
  `maintenance_protocol`, `attempt_id`, `attempt_dir`, the real inherited
  world/queue `lock_fds` and their `lock_paths`; it carries **no API request**.
- Initialize empty `intents`, `events`, `session` and `artifacts`, with
  `maintenance_protocol`, `attempt_id`, `server_instance_id`, `clean: false` and
  `publication_eligible: false`. Provide at least 900 seconds before the actual
  fixed lease expiry, with an external hard timeout and resource limits.
- Preserve any failure and implement separately reviewed cleanup-only recovery
  for an interrupted operation. There is no recipe replay/resume entry point.
  Independently verify the final restored snapshot and capture playback before
  recording visual acceptance. Never publish this diagnostic as a model run.

Existing private plans with unresolved pins remain nonexecutable. No live JAR,
native fixture, pilot ID, runtime receipt or model protocol changes merely by
integrating this library. Synthetic tests prove the executor's failure behavior
and receipt integration; they do not prove actual native XP production or
capture reliability.
