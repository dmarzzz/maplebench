# Full-client production readiness

The production target is a reproducible, bounded full-client XP trial with
ordinary game inputs, a fresh frozen baseline, authoritative persisted net XP,
and independently inspectable evidence. Existing demo recordings remain
unranked. A passing unit suite does not promote those recordings to benchmark
results or establish a production deployment.

## Release criteria

| Criterion | Required proof |
| --- | --- |
| Exclusive world ownership | Existing world and queue locks held from restore through collection and cleanup; conflicting owners rejected before mutation. |
| Frozen inputs | Actual hashes of database baseline, server/client builds, configuration, scripts, WZ inputs, scenario, prompt, and local sandbox image. No implicit image pulls or mutable image tag execution. |
| Ordinary client lifecycle | One renderer navigates through waiting, normal login, bounded input, and normal disconnect; account identity and save completion independently checked. |
| Physical controls | Native gameplay Jump/Attack bindings; visible displacement and combat in the real client. A keyboard acknowledgement alone is insufficient. |
| Durable attempts | Fsynced intent before each side effect; no model request replay; process descendants cannot outlive released world locks; interrupted attempts retained and quarantined. |
| Resource and spending bounds | Monotonic total/operation/controller limits, bounded input and output, one reserved API request, conservative uncertain usage, bounded host workloads. |
| Authoritative score | Offline initial/final database snapshots, positive native post-commit receipt, clean complete native log, preserved death penalties, and explicit unsupported-level-transition rejection. |
| Bounded scoring interval | Full input inventories run before login and after logout. Recorded upload, disconnect and save timestamps satisfy the frozen settlement policy; file copying and video probing cannot extend the live session. |
| Exact attribution | Requested/returned model, complete safe API bodies, exact executed program, frozen prompt/observation, budget and timing cross-checks. |
| Complete recording | Saved bytes and capture identity match the attempt; verified media covers the full controller interval; visual review binds the exact video hash. |
| Operational recovery | Read-only health distinguishes an expired world from a working web server; a deliberate failed attempt can recover without another API call or unrelated service changes. |

An eligible single trial is still not a statistically meaningful model ranking.
Comparisons require the same versioned scenario and baseline, balanced order,
repetitions, uncertainty reporting, and visible failed attempts. Combat RNG is
not claimed to be deterministic.

The next coverage milestone is a [class and task suite](CLASS_BENCHMARK_DESIGN.md),
informed by RuneBench's task matrix. These candidate classes, long-horizon metrics
and party objectives remain a design; they are not claimed as running benchmarks.

## Components

- [Finite experiments](FULL_CLIENT_EXPERIMENTS.md): a frozen complete attempt set,
  per-fixture model order, aggregate budgets, explicit resume without replay, and
  reports that retain missing, failed, zero and negative outcomes. This new
  coordinator requires separate runtime acceptance before unattended use.
- [Durable runner](FULL_CLIENT_RUNNER.md): operation journal, existing locks,
  bounded command supervisor, conservative API accounting, and explicit recovery.
- [Linux runtime backend](FULL_CLIENT_RUNTIME.md): stopped-server baseline
  restore, pinned server launch, ordinary browser lifecycle, and real collection.
- [Persistence and publication](FULL_CLIENT_TRIALS.md): byte-verified evidence,
  net-XP calculation, native save receipts, and publication schema 2.
- [Full-client controls](FULL_CLIENT.md): real input, capture, live model labels,
  and integration-mode limitations.
- `scripts/full_client_collect.py`: minimal offline database export through a
  consistent read-only transaction. It cannot restore a database or certify a
  trial by itself.
- `scripts/full_client_health.py`: read-only health with explicit modes. Schema
  1 checks the leased integration preview. Schema 2 checks the normal worker's
  actual processes, owned listeners and lock inodes, empty queue, private relay
  quiescence and fresh waiting/rendering state. Run on Linux with private host
  configuration; see [operational health](FULL_CLIENT_HEALTH.md). Durable trials
  use the runner's preflight and runtime ownership checks, which also establish
  account and frozen-input evidence unavailable to the standalone health probe.
- `scripts/full_client_freeze.py`: read-only inventory and drift verification
  for existing server/client builds, configuration, scripts, WZ and sandbox
  image. It does not create a database baseline or copy game assets.
- [Live results dashboard](FULL_CLIENT_DASHBOARD.md): allowlisted results projection for the
  full-client dashboard. It rechecks completed runner receipts, keeps failures
  visible, separates diagnostic client XP from persisted XP, and groups only
  matching frozen inputs. The gallery serves the exported JSON and explicitly
  copied recordings; private attempt directories are never web roots.

## Native save receipts

The bootstrap overlay inserts a receipt after `Character.saveCharToDB` commits
the actual database transaction, and a failure marker in its exception handler.
The source hook is disabled unless the trusted server launcher supplies all of:

```text
MAPLEBENCH_TRIAL_ID
MAPLEBENCH_SERVER_INSTANCE_ID
MAPLEBENCH_PERSIST_CHARACTER_ID
MAPLEBENCH_PERSIST_ACCOUNT_ID
MAPLEBENCH_SAVE_JOURNAL
```

The server initializes a new mode-0600 journal before accepting logins. It
rejects incomplete configuration, symlink ancestors, and an existing journal.
Receipts contain only numeric identities, run/instance IDs, and timestamps.
The API program cannot supply these settings. A save receipt I/O failure leaves
the game transaction intact and invalidates benchmark evidence through the
captured native error marker. Both the journal and actual server stdout/stderr
are required; a synthetic clean log is not evidence.

Native receipts require a newly built server JAR. Source changes or a successful
standalone receipt test do not prove that the running server has that JAR.

## Validation and rollout

Use one isolated source snapshot and one capped build/test job at a time on the
shared runtime. The focused Python tests use synthetic adapters and actual
temporary locks/processes. The native receipt tests compile independently of
game assets:

```sh
python3 -m unittest discover -s test -p 'test_full_client*.py'
MAVEN_OPTS='-Xmx768m -XX:ActiveProcessorCount=2' \
  mvn -B -q -f test/persistence/pom.xml test
```

Apply the repository's hard memory and wall-time limits around these commands
on shared machines. CI runs these checks separately from real game trials;
tests never spend API credits or modify a live game database by default.

Before a release, perform one bounded real trial from a frozen offline baseline,
inspect its full recording, verify its persisted evidence bundle, and exercise
recovery using a separate failed attempt. Keep raw database dumps, credentials,
server logs, model outputs, recordings, and host configuration in private ignored
directories. Publish only deliberately reviewed evidence. Never expose the
control plane publicly to make deployment easier.

The concrete backend and browser completed four actual same-baseline trials on
September 6, 2026. Full private publication validation passed Astra, Sol and Luna;
Terra's persisted score passed but its incomplete final action receipt blocks
publication. The [acceptance record](FULL_CLIENT_ACCEPTANCE.md) preserves exact
run IDs, outcomes and limits. Historical integration demos remain unranked.

This proves controlled end-to-end operation, including two explicit recoveries.
It does not establish unattended production availability or a dependable ranking.
Repeated trials, balanced order, uncertainty reporting and longer operational
acceptance are still required. A publication failure cannot be repaired by
rewriting the original controller result.

Release `9dd7d98` deployed the deadline/receipt fixes and mandatory SDK dispatcher
pin. Its separate Astra acceptance completed with 29 acknowledged inputs,
+9,500 persisted net XP, ordinary committed logout, reviewed recording and a
passing full publication validation. The original four-model comparison is
unchanged. This early-finishing program did not exercise the live deadline-tail
boundary; focused tests cover that boundary.

Release `2a93db5` deployed a frozen local Docker execution binding, an explicit
finite experiment coordinator, populated post-render readiness checks and an
explicit async-body prompt. Its separate single-entry Astra acceptance passed:
25 acknowledged actions, +9,000 persisted net XP, ordinary logout, reviewed
recording and independently validated publication evidence. It does not
retroactively change the `9dd7d98` contract or any historical result. The deployment check found no
alternate Docker endpoint in those runs. Installed third-party Python package
bytes and all import roots remain a trusted-host assumption; the new Docker
binding does not close that separate reproducibility gap.

Shared-host capacity is still an operational release gate. Normal-service
restoration retains the original heap/cgroup settings and refuses when available
memory is below the reviewed admission threshold. A passing short trial does not
reserve capacity for continuous operation or demonstrate unattended recovery.

The original normal server and queue worker were restored after the separate
acceptance. Restoration exposed a false readiness timeout: `journalctl` returned
success with empty output while failing to map a journal file under an inherited
address-space limit. The server itself had started correctly. Recovery verified
the exact existing process, its own startup log and listening sockets, preserved
the failed restoration journal, and started only the original worker after
closing the existing locks. The old queue worker then restarted that healthy
server on its first empty-queue iteration. The source fix preserves an active
world when there is no batch override to remove, starts a stopped normal service,
and keeps restart/reload for actual batch cleanup. Release `2a93db5` deployed
that fix; its normal worker reached its first idle state without restarting the
restored server. The earlier restart remains in the operational evidence.
A successful command exit or HTTP response alone is
insufficient readiness evidence. An uncertain start must be reconciled against
the existing instance before another start is considered.

Restoration after the `2a93db5` acceptance also preserved an early readiness
verification failure. Its wrapper discarded the underlying refusal code, so the
original cause cannot be established. Independent checks subsequently proved
the same server instance ready. A worker-only finalizer exposed a concrete
1,024-descriptor inspection limit below the server's stable 1,566 descriptors,
mostly Netty selectors. Bounded streaming inspection with a 4,096-descriptor cap
passed, and only the worker was started. Neither recovery replayed an API call
or restarted the already-running server. These operational findings remain
relevant to longer unattended acceptance.

Real integration exposed two launch/evidence issues that synthetic phases did
not reveal: systemd requires an unquoted scalar WorkingDirectory, and Chrome
MediaRecorder WebM files can omit container duration metadata. Launch validation
must check the actual loaded command and working directory. Recording duration
must come from bounded inspection of the encoded media, with incomplete or
corrupt recordings rejected. A successful gameplay program remains an invalid
benchmark attempt if any subsequent evidence check fails.

The subsequent source hardening passed 355 focused Python tests in 30.116 seconds
on one capped runtime job, including a real local Docker invocation and actual
stdlib child-process timeout/parent-death checks. These checks do not spend model
API credits, reset a live database, or replace release acceptance. After
aligning plan admission with the backend's actual file-size limits, all 23
experiment tests passed again in 1.481 seconds. The subsequent readiness release
passed 375 focused tests, including real Docker execution, and both JavaScript
files passed Node 22 syntax checks before deployment. Its single-entry live
acceptance is recorded above; repeated trials and longer operational acceptance
remain outstanding.
