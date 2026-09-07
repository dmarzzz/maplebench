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
| Normal-worker health | Explicit schema-2 probes verify actual process bindings, owned listeners, worker-held lock inodes, queue and private relay quiescence; fresh waiting is distinct from rendering. | An operational snapshot, not trial authorization. Durable trials retain their trusted runner/account checks. Rollout acceptance remains outstanding. |
| First-idle restoration evidence | The opt-in worker hook records zero claimed trials, exact Cosmic/worker instances, source hash and held lock identities in a create-only receipt. | Replacement/unlocked descriptors fail; the lifecycle consumer must independently verify the receipt. |
| Explicit normal-service lifecycle | `full_client_lifecycle.py` validates a private handoff, journals start intent, proves exact native/worker instances and reconciles interrupted responses without replaying starts. | New offline tests include real process death/descendant cleanup; this command has not been deployed or accepted against the normal logger. |
| Startup diagnostics | Native log/marker/listener observations are retained for the owned invocation. Incomplete probes preserve their deadline; byte/FD/deadline bounds constrain process evidence reads. | No unrelated-log fallback or assertion about the earlier discarded inner failure. |
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

The subsequent operational core covers 213 focused cases across runtime,
runner, health, bridge/session, worker receipts, worker restoration and batch
queue tests. Its first capped Linux job ran 213 in 6.612 seconds with one error
in a new SQLite test wrapper's parameter name. After correcting that fixture,
all 20 health tests passed in 0.027 seconds in a separate serialized capped job;
the other 193 cases had already passed and their source/tests were unchanged.
The successful source snapshot SHA256 is
`95c38b508417ec82a26eb85dd6ff24caeef8be8b7cfe267d601a42f573d773b0`.
These jobs issued no API requests or live game/database mutations.

The new normal-service lifecycle passed all 14 focused Linux tests in 0.537
seconds. They include actual temporary files/flocks, an open native log and
owned listening socket, lost start-response reconciliation, and a killed
operator with a grandchild. The guard test confirms that its lock remains held
until both command descendants are reaped, with the guard's CPU limit exempted
and the command child's limit retained. An initial fixture named `operator.py`
shadowed Python's standard-library module; renaming the test driver fixed that
fixture before the successful run. The production lifecycle source did not
change between those two test jobs. The successful snapshot SHA256 is
`bfb90e3def7ef423da0269f53aa7a2734c8d98bde844791e86ff977a6683edbb`.
Tests used the same serialized 768 MiB/two-CPU/180-second job bounds and made no
live service, database or API calls.

## Remaining integration and operational work

Normal-worker health, first-idle receipts, invocation-bound startup diagnostics
and the explicit lifecycle command are implemented and covered above. The
standalone health tool refuses durable-trial mode because it lacks the trusted
runner/account context; that existing context remains authoritative.

The lifecycle still needs a reviewed private configuration and rollout
acceptance against the existing normal services. In particular, its native
log-generation contract refuses ambiguous reuse of an old online marker,
including a same-inode rewrite by the normal logger. Accept a provable new
generation or preserved append boundary before using this command for recovery.
Do not treat these source tests as permission to replay old private helpers or
as live restoration evidence. The legacy worker retains its existing batch
cleanup behavior; the new supported handoff requires the opt-in receipt and an
already-verified normal Cosmic instance.

The private recovery's earlier discarded inner error remains unproven; the
later descriptor-limit failure was directly observed. Neither source change
retroactively changes those historical receipts.

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

The production goal remains active through the required integration and live
acceptance work; these source tests alone do not establish production readiness.
