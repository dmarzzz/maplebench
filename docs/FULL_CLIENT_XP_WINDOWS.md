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
The frozen adaptive pilot also rejects later-cycle level changes; supporting
adaptation across level-ups requires its own controller revision. The ledger
arithmetic is tested across those transitions without claiming a live adaptive
level-up run occurred.

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
The current runtime collector does not yet enable these new settings or produce
this manifest automatically. Wire collection only in a new pinned trial protocol
after native acceptance; do not reinterpret an old pilot's score.

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
