# Native XP windows, version 1

This implements a new, disabled-by-default native journal and offline scorer for
`full-client-xp-windows-v1`. It is preparation for the research design in
`RESEARCH_FRAMING.md`. It is not enabled in the current adaptive pilot, does not
change its persisted net-XP validator, and cannot upgrade historical recordings.
No existing result has authoritative window evidence merely because this code
is present. Every scorer result retains `publication_eligible: false`.

## Accounting boundary

The Cosmic overlay journals the settled outer `Character.gainExpInternal`
transaction. Recursive overflow grants, nested `levelUp`, and nested `setExp`
calls belong to that one transaction. XP is actual progression after clipping,
not the nominal grant passed to the method. Death penalties use the same signed
path. Zero transactions remain explicit. The journal records direct `setExp`,
`setLevel`, and standalone `levelUp` mutations, but this scorer refuses them.
An unsupported administrative progression edit must not become training XP.

For level `L`, progression is current XP plus the sum of the pinned native
thresholds for levels `1` through `L-1`. The header carries those 199 thresholds;
their canonical JSON-array SHA-256 is frozen in both the scenario and evidence
manifest. A level-up therefore preserves its earned XP, and a level-200 cap
counts only actual progression to the cap. Negative XP and decreasing levels
are invalid states for this native version. Death loss is preserved as a
negative change within the same level, including loss clamped at zero XP.

`gainExpInternal`, `levelUp`, `setExp`, `setLevel`, and the existing
`saveCharToDB` transaction share the character monitor. The ordinary save hook
runs immediately after the real SQL commit, using the same level and absolute
current XP that the pinned source binds in its UPDATE. The persistence receipt
and XP save receipt use one captured timestamp. A committed save must reconcile
with the complete sequence and the subsequent offline database snapshot.

## Fixed scoring windows

The clock starts with the adaptive controller's wall-clock budget, before its
first model call. Windows are fixed, non-overlapping, and half open:
`[start + 15000*k, start + 15000*(k+1))`. A transaction belongs to the window in
which the outer transaction settles. An event exactly at a boundary belongs to
the next window; an event exactly at the deadline is outside the control score.
There is no selection of a more favorable window alignment after the run.

For each complete window:

```
normalized XP/min = signed progression change * 60000 / 15000
                    / declared server XP multiplier
                    / declared simulation-speed multiplier
task score = max(0, all complete normalized window rates)
```

The result includes each signed window rate and the best rate discovered so far.
An incomplete final interval contributes to `control_window_net_xp` but cannot
set a peak. `persisted_net_xp` separately includes all signed changes from the
restored state through ordinary logout, including changes before the controller
starts or after its deadline. These totals intentionally can differ.

The server multiplier is checked against the actual world rate at every native
transaction and save. Both multiplier declarations are positive bounded rational
pairs. Simulation speed is a frozen scenario declaration, not something this
journal measures; acceptance must verify the configured speed. The ordinary
real-time runtime uses `1/1`. There is no reference-policy denominator.

The arithmetic supports horizons up to 30 minutes (120 complete windows), but
the full bundle verifier currently accepts only the implemented 300-second
adaptive controller (20 windows). A 30-minute controller, native runtime
acceptance, and an accepted publication adapter remain separate requirements.
The original adaptive controller can finish early when its call/token/action
limit is exhausted. Such a result cannot satisfy this full-300-second window
contract. A newly frozen controller may explicitly enable
`full-horizon-reserve-v1`: confirmed budget exhaustion then keeps the world under
passive observation through the deadline, with no extra gameplay inputs. This
declared policy does not upgrade older evidence; death or infrastructure failure
can still end the interval early and prevent full coverage.
The default adaptive pilot still rejects later-cycle level changes. A newly
frozen native-window variant may add this exact `adaptive_protocol` field:

```json
"progression_policy": {
  "id": "native-xp-level-progression-v1",
  "xp_window_protocol": "full-client-xp-windows-v1",
  "maximum_level": 200
}
```

This requires the full-horizon policy and the existing explicit native-window
runtime/scenario opt-in. The initial observed level must exactly match the frozen
profile; subsequent observations may use levels from that initial level through
200. It performs no stat/skill allocation, healing or restoration. The exact
prompt and scenario hash change, and this variant needs fresh source/runtime and
baseline acceptance. Current pilots and their receipts are not reinterpreted.

Aggregate verification refuses this policy without hashed native-ledger context.
The native bundle verifies the ordinary session, offline DB states, reset, save
and native logs, then supplies that context to the adaptive verifier. It rechecks
the ledger's chain, actual progression, frozen XP table, multipliers and terminal
coverage. Every observed level must be supported by native transitions within
the corresponding observation or enclosing SDK program interval, with the
existing 1500ms render freshness and 25ms native clock allowance. Intermediate
levels in a native overflow transaction may occur within that interval. Legacy
adaptive publication cannot supply this context and remains ineligible for this
variant; a dedicated native-window publisher is still required.

Synthetic end-to-end tests cover level180→181, level200 cap, stale/future client
level claims, missing or unrelated ledgers, and death without full coverage.
They do not claim that a live adaptive level-up run has occurred.

## Journal and failure behavior

The native file is created once with mode `0600`; reusing a path or traversing a
symlink ancestor is refused. The header, each transaction, and each save receipt
are appended and fsynced. Records contain the run, server instance, synthetic
character/account IDs, contiguous sequence, wall timestamp, elapsed monotonic
nanoseconds, and the SHA-256 of the exact previous newline-terminated record.
The header's previous hash is 64 zeroes. The file is capped at 64 MiB and 100,000
records. No player names, passwords, API credentials, or chat are recorded.

Backward clocks, more than 25 ms wall/monotonic drift, changed world rates,
unobserved state changes, and write/fsync failures invalidate the journal. The
server emits a fixed failure marker and stops issuing XP evidence; gameplay and
an already committed SQL transaction are not rolled back. The scorer requires
the native initialization markers and rejects any journal/save failure marker.
Its log-review receipt must cover server start through final collection.

Complete zero windows require continuous native instrumentation from a matching
baseline header through a matching terminal save after the deadline. Missing,
truncated, out-of-order, unsupported, or unreconciled evidence is unknown, never
an imputed zero. Hash chains detect changed/missing bytes; they are not signatures
and do not authenticate a collector. A trusted launcher must pin the native JAR,
source, runtime, fixture, and configuration, keep both normal locks, and collect
the actual files. This offline calculator cannot prove those operator actions
from arbitrary self-authored JSON.

## Enabling a future trusted trial

Build the overlay through the existing pinned Cosmic bootstrap. It instruments
the four progression methods, upgrades the ordinary SQL-commit receipt, and
initializes the ledger before the server accepts logins. Reapplying the bootstrap
is idempotent. Existing event-sink telemetry and the legacy receipt remain
available under their original contracts.

The launcher must provide the existing identity/persistence settings plus all
seven new settings, or none:

| Setting | Value supplied by the trusted launcher |
| --- | --- |
| `MAPLEBENCH_XP_JOURNAL` | New absolute path in the private attempt directory |
| `MAPLEBENCH_XP_BASELINE_LEVEL` | Verified restored level |
| `MAPLEBENCH_XP_BASELINE_EXP` | Verified restored current XP |
| `MAPLEBENCH_XP_SERVER_NUMERATOR` | Frozen server multiplier numerator |
| `MAPLEBENCH_XP_SERVER_DENOMINATOR` | Frozen server multiplier denominator |
| `MAPLEBENCH_XP_SIMULATION_NUMERATOR` | Frozen simulation-speed numerator |
| `MAPLEBENCH_XP_SIMULATION_DENOMINATOR` | Frozen simulation-speed denominator |

The existing settings are `MAPLEBENCH_TRIAL_ID`,
`MAPLEBENCH_SERVER_INSTANCE_ID`, `MAPLEBENCH_PERSIST_CHARACTER_ID`,
`MAPLEBENCH_PERSIST_ACCOUNT_ID`, and the ordinary `MAPLEBENCH_SAVE_JOURNAL`.
The XP protocol requires 32-character lowercase hexadecimal run and instance
IDs. No environment values or host-specific paths belong in source control.

Freeze the following additional scenario object before dispatch:

```json
{
  "xp_window_protocol": {
    "id": "full-client-xp-windows-v1",
    "window_ms": 15000,
    "wall_seconds": 300,
    "experience_table_sha256": "<accepted native threshold-array SHA-256>",
    "normalization": {
      "server_xp_multiplier": {"numerator": 1, "denominator": 1},
      "simulation_speed_multiplier": {"numerator": 1, "denominator": 1}
    }
  }
}
```

`full_client_xp_windows.verify_bundle(manifest, artifact_root)` requires exact
top-level fields: `schema_version: 1`, `protocol`, the four identity fields,
`window`, `normalization`, `experience_table_sha256`, `baseline_sha256`,
`scenario_fingerprint`, and `artifacts`. `window` contains only `start_at_ms`,
`deadline_at_ms`, and `window_ms`. Artifact references use the existing bounded
relative-path/bytes/SHA-256 format. Required artifact names are:

```
xp_ledger native_save native_log initial_db final_db session scenario
controller_result baseline_sql baseline_snapshot reset server_log
```

The verifier checks the frozen reset/baseline and keymap, complete adaptive
cycle evidence, exact controller interval, ordinary logout, positive native
save receipt, reviewed logs, all file hashes, and final progression. It does not
substitute a last-cycle receipt for the full adaptive trace. Existing recorder
proof and native-runtime admission still belong to the trial/publication adapter.
The runtime collector supports these settings only when its private configuration
contains `"xp_window_protocol": "full-client-xp-windows-v1"` and the frozen
scenario contains the matching object above. Either declaration without the
other fails closed. A window trial uses request `schema_version: 3` and
`protocol: "full-client-xp-windows-v1"`, with the same 300-second controller and
bounded adaptive budgets as schema 2. The scenario's controller `protocol`
remains `full-client-adaptive-pilot-v1`; controller identity and scoring identity
are deliberately distinct. Older requests cannot launch the new scoring mode.

Offline inventory requires both native journal classes in the pinned JAR.
The launcher writes all seven XP values into its existing owned drop-in from
the verified initial snapshot and frozen declarations. Before ordinary login,
readiness requires the native initialization marker and a fresh journal that
contains only the expected header, identity, baseline, multipliers, and table.
Its header hash is saved and checked again at final collection. A legacy
configuration refuses unexpected XP initialization or leftover XP settings.

After ordinary logout and the normal recording checks, the collector copies
`native-xp.jsonl`, writes `xp-window-manifest.json`, and invokes the strict
window verifier. The trial runner independently rereads and verifies those
same bytes before allowing terminal cleanup/completion. It writes a separate
`xp-window-status.json`: valid coverage is `verified_native_windows`; missing
or inconsistent coverage has `status: "unknown"` and `task_score: null`, then
fails/quarantines the attempt without replaying the API. No zero score or
legacy persistence fallback is emitted on that path. Publication candidates
use schema 4, `xp_window_pilot`, and the new protocol; publication still requires
an accepted adapter and is never granted by the collector.

Pin the new `full_client_xp_windows.py` with all existing runtime, trial, scorer,
adaptive-evidence, and capture dependencies. `CommandAdapter` includes it in
its automatic source fingerprint. The ordinary standalone trial runner supports
schema 3. The finite experiment builder also accepts an explicitly selected
`full-client-xp-windows-v1` fixture, only with its matching native configuration,
pinned scorer, complete window contract, and frozen full-horizon controller
policy. Planning validates the complete adaptive contract and matching trial/API
caps before admission, including malformed-object rejection. It emits schema-3 requests; it never infers a scoring upgrade from an
existing adaptive fixture. The public adaptive gallery still needs a separate
accepted window adapter before such a cohort can be published. Do not relabel
an existing plan or reinterpret an old pilot's score.

An offline diagnostic invocation is:

```
python3 scripts/full_client_xp_windows.py <private-manifest.json> --artifact-root <private-run-directory>
```

On invalid evidence it returns a nonzero status and a sanitized `score: null`.
`aggregate_task_scores` supplies only the mathematical equal-weight mean of
`ln(1 + task_score)`; it rejects missing/nonfinite/negative entries. Freezing a
complete task roster and repetition/failure rules is the experiment adapter's
responsibility, not an inference this helper makes from available scores.

## Validation

Targeted Java tests cover level-up/death arithmetic, cap clipping, nested
transactions, complete save receipts, file permissions, reuse and symlink
refusal, world-rate/state/clock failures, and fsync failures. They compile with
the patched pinned native Character methods, alongside existing persistence
tests. Python fixtures cover fixed boundaries, deadline exclusion, signed
losses, normalization, zero/missing windows, 30-minute arithmetic, tampering,
ordinary-save reconciliation, and the full synthetic adaptive evidence bundle.
These are synthetic tests, not model runs or native runtime acceptance.

## Native acceptance before deployment

This is an ordered acceptance plan, not an instruction to modify an active
pilot. Finish the current group first. Use an independently frozen candidate,
new native JAR and baseline fingerprints, and the existing world/queue locks.
Do not mix either the source/JAR or the score protocol within a cohort.

1. Build the pinned Cosmic source plus this overlay in an isolated directory.
   Run the two journal test classes under the shared serial lock, fresh-memory
   check, 2300 MiB total cap, 768 MiB Maven heap, one 1024 MiB test fork, two CPUs,
   and five-minute deadline. Verify repeated bootstrap application does not
   change the patched source. Freeze the exact built JAR and runtime inventory.
2. With Cosmic stopped, queue empty and both normal locks owned, prepare an
   explicitly synthetic acceptance fixture. Keep credentials generated on the
   host. Freeze a new SQL hash, native threshold-array hash, and scenario for
   each materially different initial state. In addition to an ordinary fixture,
   use one just below a level threshold and one susceptible to a real death
   penalty. Administrative XP commands do not substitute for these cases.
3. Start the candidate once through the owned launcher. Check that all seven
   XP values match the frozen fixture, both journal files are new mode-0600
   regular files, both initialization markers occur exactly once, and the
   recorded header matches the accepted table and baseline before login.
   Missing initialization, a changed table, or an already-used file must stop
   before ordinary login and before any model request.
4. Log in normally and use real native inputs for an explicitly labeled
   **native acceptance smoke test**. Observe a real monster defeat and its
   signed XP event. In the near-threshold fixture, defeat a monster to cross
   the level boundary; verify one settled outer progression change, without
   counting its nested level-up twice. In the death fixture, verify the actual
   penalty and zero clamp. A surviving idle interval must also have complete
   zero coverage. These tests do not need API calls and are not model trials.
5. Disconnect normally, confirm the native SQL commit, then collect offline
   initial/final rows, both native journals, and complete invocation logs.
   Recompute every signed transaction and reconcile final progression using
   the frozen table. Confirm native timestamps are ordered and align with the
   declared start/deadline; boundary and cutoff arithmetic remains separately
   covered by deterministic tests. Preserve actual native event timing rather
   than pretending a smoke-test action landed on an exact millisecond.
6. Against copies of this evidence, remove a transaction/footer, change the
   table or multiplier, and truncate the reviewed log envelope. Each must
   become unknown. Test missing/read-only/reused output locations in isolated
   startup checks; never damage an active trial's journal to simulate failure.
   Confirm cleanup removes the owned drop-in and cached XP settings while
   retaining evidence and the ordinary account-offline state.
7. Only after the native evidence is accepted, freeze a fresh schema-3 request
   and run one bounded 300-second API pilot. Check exact model attribution,
   all controller cycles, capture/first-input evidence, twenty complete native
   windows, independent runner re-verification, ordinary logout, and terminal
   cleanup. No second API attempt is automatically queued after failure.
   Record accepted evidence references before extending experiment planning
   or public publication to the new protocol.
