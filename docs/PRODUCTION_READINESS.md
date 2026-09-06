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
| Exact attribution | Requested/returned model, complete safe API bodies, exact executed program, frozen prompt/observation, budget and timing cross-checks. |
| Complete recording | Saved bytes and capture identity match the attempt; verified media covers the full controller interval; visual review binds the exact video hash. |
| Operational recovery | Read-only health distinguishes an expired world from a working web server; a deliberate failed attempt can recover without another API call or unrelated service changes. |

An eligible single trial is still not a statistically meaningful model ranking.
Comparisons require the same versioned scenario and baseline, balanced order,
repetitions, uncertainty reporting, and visible failed attempts. Combat RNG is
not claimed to be deterministic.

## Components

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
- `scripts/full_client_health.py`: read-only service/process, lock, memory,
  remaining lease, relay freshness, and recording/evidence checks. Run on the
  Linux runtime host using private host configuration. This checks the leased
  integration preview. Production attempts use the durable runner's preflight
  and the runtime backend's continuous ownership checks instead.
- `scripts/full_client_freeze.py`: read-only inventory and drift verification
  for existing server/client builds, configuration, scripts, WZ and sandbox
  image. It does not create a database baseline or copy game assets.

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

Production acceptance remains pending until the concrete backend and browser
lifecycle complete that real end-to-end verification. Do not infer acceptance
from documentation, synthetic receipts, successful compilation, or a previous
integration demo.
