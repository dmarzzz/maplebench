# Production implementation audit

Audit date: September 7, 2026 UTC. Scope: durable full-client orchestration,
authoritative persisted scoring, inspectable evidence, operational safeguards,
focused validation, and explicit remaining release gates. The workspace is not
yet ready to claim unattended production operation.

## Requirement evidence

| Requirement | Current evidence | Scope and remaining work |
| --- | --- | --- |
| Architecture and trust boundaries | `ARCHITECTURE.md` maps the actual coordinator, runner/guard, runtime, single renderer, SDK container, database collection and publication path. | Private runtime configuration, administrator trust and third-party import identity are explicit boundaries. |
| Durable single attempts | `full_client_trial.py` journals phase intent, holds existing locks, supervises descendants, reserves uncertain API usage and recovers through cleanup only. `test_full_client_trial.py` exercises real process death, inherited locks, timeouts, interrupted publication and non-replay. | Existing server/service ownership remains independently checked by the runtime. |
| Finite multi-model orchestration | `full_client_experiment.py` freezes every ID, rotates model order, reserves the complete plan, journals before spawning, stops on failure and resumes only future unsubmitted entries. | Tests prove these mechanisms; live acceptance covers one entry. Repeated execution and stop/recovery/resume still need live acceptance. |
| Ordinary game lifecycle | `full_client_runtime.py`, session/bridge and controller code restore only while stopped/offline, log in normally, execute bounded keys, upload capture, then disconnect and verify save before collection. | Actual acceptance `a154c7a1b7fa4799ad884e89a07190be` completed this path with exact Astra attribution. |
| Authoritative score | `full_client_collect.py` and `full_client_score.py` verify offline numeric rows, frozen baseline identity, one matching native committed-save receipt and session ordering. | Signed zero/negative XP is retained; unsupported level transitions fail. Client XP remains diagnostic. |
| Trustworthy input and recording evidence | Frozen source/assets/image/dispatcher, exact API input/output/program, populated post-render readiness, input receipts, capture clocks, media probing and a separate visual-review receipt are verified by the publisher. | The accepted run had +9,000 persisted XP, 25/25 inputs and a reviewed 35.344-second recording. Sampled review does not prove every frame or a particular monster death. |
| Complete reporting | The report covers the entire plan, including missing, failed, recovered and invalid rows, with explicit denominators and no ranking or fabricated confidence interval. | The deployed single-entry report independently recomputed +9,000 XP and 25 inputs. Report aggregates verify persistence; publication/protocol acceptance is separate. |
| Interrupted trial cleanup | Removal/reload checkpoints now preserve an owned drop-in cleanup across process interruption. Clean/ready requires the effective systemd configuration to have lost its trial settings. | New regressions model manager-cached configuration independently of the file. This source change requires rollout acceptance. |
| Resource and ownership safeguards | Bounded trials, guarded subprocesses, existing world/queue locks, no lock takeover, frozen local Docker invocation and bounded evidence readers. | Shared-host capacity and longer service operation are not established by a short acceptance. See workspace gaps below. |
| Focused validation | 234 tests passed over runtime, runner, publisher, scorer, experiments and dashboard in one serialized, capped Linux job. | The immutable test snapshot covers the implementation fixes below. No API or live game/database operation was used by this test job. |

## Corrections from this audit

- Interrupted cleanup previously skipped `daemon-reload` if its drop-in had
  already been unlinked. The new durable removal/reload checkpoints verify the
  manager's actual `DropInPaths`, native environment and reload state before
  declaring the world clean.
- Hash-valid non-object evidence envelopes could abort a complete-plan report.
  Required object boundaries now reject the affected row while preserving all
  other declared rows. Optional absent or contradictory action counters can
  still leave persisted XP reportable while execution/no-op claims stay unknown.
- Publication previously checked acknowledged inputs without rejecting other
  contradictory recorded counters. Present attempted/controller action counts
  must now match the complete acknowledged input receipts; historical absence
  remains supported.

The new cases include interrupted reloads, a zero-exit reload that leaves cached
settings intact, changed ownership/checkpoints, fifteen malformed evidence
envelopes beside valid and missing attempts, and rehashed contradictory counters.
The test snapshot SHA256 is
`9b7009623f16c404988fc042f75e87220c12a5105f6902de7fe1995e0fbf081a`.
Tests completed in 9.467 seconds under a 768 MiB memory/address-space cap, no
swap, two CPUs and a 180-second wall limit. Runtime artifacts and host-specific
receipts remain private. The earlier deployed `2a93db5` release separately passed
375 focused tests and its recorded live acceptance.

## Remaining workspace implementation

These are local implementation gaps, not completed work or external approvals:

1. **Normal-service lifecycle:** the legacy worker's `restore_world()` can start
   or restart the normal service without the durable intent, exact-instance
   continuation, native readiness, capacity admission and structured first-idle
   proof used by the private recovery helpers. Move that supported lifecycle into
   a reusable explicit workspace command. Keep full-client trial cleanup stopped
   and do not let the legacy worker reinterpret trial ownership.
2. **Mode-aware health:** `full_client_health.py` checks the leased integration
   helper mode. Add explicit normal-worker and durable-trial modes, including
   actual process/lock ownership and controller/lease/browser-release quiescence.
   An active HTTP server or a terminal controller status alone is insufficient.
3. **Native startup diagnostics:** repository readiness still depends on
   `journalctl` under inherited resource limits. Empty successful output becomes
   a generic wait timeout. Preserve safe, specific missing-evidence diagnostics
   and a bounded native log acquisition contract tied to the exact instance.
   The private recovery's earlier inner failure was discarded and remains
   unproven; the later descriptor-limit failure was directly observed.

## External release gates

- Freeze, deploy and accept each changed source revision on the existing runtime;
  the latest live evidence remains bound to `2a93db5` and does not validate later
  implementation changes automatically.
- Run a declared finite repeated-model experiment with comparable populated
  starting conditions, balanced order, visible failures and reviewed recordings.
  Exercise explicit stop/recovery/resume, live readiness timeout with zero API
  requests, deadline boundaries and a longer operational window.
- Establish sufficient shared-host capacity and a supported renderer lifecycle
  before promising unattended availability. No benchmark run reserves continuous
  service capacity.
- Complete the separate class/task fixture acceptance described in
  `CLASS_BENCHMARK_DESIGN.md` before reporting class or party performance.
- Review intended public evidence, repository history and licensing before
  external publication. Keep game assets, private captures, database exports,
  credentials and the control plane private.

The goal remains active while the workspace implementation gaps above remain.
