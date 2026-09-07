# Finite full-client experiments

`scripts/full_client_experiment.py` adds a declared experiment around the existing
single-attempt runner. Plan creation and reporting are offline. Only explicit
`run` or `resume` commands launch trials. This implementation has no live defaults,
does not deploy itself, and has not completed a live repeated-trial acceptance.
It does not alter historical v4/v5 scenarios or promote their evidence.

An experiment uses the ordinary full-client runtime: one rendered character,
offline baseline restoration, one provider request per attempt, normal logout,
native persistence evidence and explicit recovery. It never submits to the older
server-bot batch queue or starts/stops the normal worker. Operators must arrange
the existing runtime's prerequisites before execution.

## Scene readiness and the next protocol version

Matching frozen inputs proves the same declared baseline, source, assets and
budgets. It does not prove that the first model observation contained a populated
scene or that monster positions, spawn timing and combat RNG matched. Historical
inputs exposed a readiness gap: a fresh character/capture could qualify before
monsters appeared in the observation. This does not establish the cause of every
zero-XP or no-op result. Preserve those results and their original groups; do not
repair programs, replace observations, rerank runs or add retrospective checks to
their frozen scenarios.

The next scenario version adds `readiness_policy` with the following exact
contract. The shared validator is `scripts/full_client_readiness.py`; collection
and request gating live in the bridge/runtime, with independent publication
checks in `scripts/full_client_publish.py`. Automated coverage exercises readiness
failure and publication checks. Release `2a93db5` completed a separate live
single-entry acceptance; repeated-model acceptance remains outstanding. Its
complete-plan report independently recomputed +9,000 persisted XP and 25
acknowledged actions over the entire one-entry plan, with `ranked:false` and no
confidence interval. See [the acceptance record](FULL_CLIENT_ACCEPTANCE.md).

| Policy field | Required value |
| --- | --- |
| `schema_version` | `1` |
| `expected_map_id` | The persisted baseline character's map ID |
| `min_monsters` | `1` |
| `min_samples` | `3` |
| `min_span_ms` | `1000` |
| `timeout_ms` | `10000` |

Before the single provider request, capture must be ready and at least three
distinct, increasing post-render frame counters must span at least one second.
Every qualifying observation must show a living character with positive HP on
the expected map, at least one monster, and observation/render ages below
1,500 ms. Invalid state or a gap of at least 1,500 ms resets the window; a
regressing capture counter fails it. The last qualifying snapshot becomes the
exact provider input. Its freshness and the latest scene are checked again at
dispatch within the ten-second deadline. Failure prevents the API request; it
does not authorize a retry or substituted observation. This establishes a minimum
populated scene, not identical monster positions or guaranteed target reachability.

Freshness includes the browser-reported age, a conservative network-delay bound
from the existing capture-clock handshake, and time spent on the server. The
readiness receipt retains those measurements so publication can recompute the
effective ages. Missing or inconsistent clock evidence cannot qualify a future
trial. The historical capture-clock artifact format remains unchanged.

The collected `readiness.json` must bind the run, renderer, capture clock, sample
window, dispatch check and initial-observation hash to the result and actual API
input. Future scenarios freeze `budgets.run_ms=(program_seconds+63)*1000`: 85 seconds
for a 22-second program, or 123 seconds for a 60-second program. This adds only
the ten-second readiness allowance to the prior run envelope. The one-request
cap, 50-second API timeout, output/token/action limits and active program duration
remain unchanged. This envelope is separate from lifecycle and aggregate-plan
wall reservations.

Freeze the revised prompt as a new scenario/prompt version with its actual
`instructions_sha256`. It explicitly requests an async function **body**: the
harness already wraps and invokes it, so use top-level `await sdk.observe()` and
explicitly await any helper call. Returning only an outer function declaration
does not execute that function. The harness must not repair such output or hide
a resulting no-op. Historical prompt hashes and results remain unchanged.

## Private plan

The `plan` command reads a private JSON configuration with exactly these fields:

| Field | Value |
| --- | --- |
| `schema_version` | `1` |
| `experiment_id` | A stable identifier, 1–96 ASCII letters/digits/`_`/`.`/`-`, beginning with a letter or digit |
| `models` | An ordered unique list from `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` |
| `repetitions` | Integer 1–50 |
| `fixtures` | Ordered list of 1–16 fixtures described below |
| `runner` | Exact existing runner configuration described below |
| `aggregate_limits` | `{api_requests,total_tokens,wall_seconds}` covering the sum of **every planned maximum**, plus five seconds of launch grace per attempt in the wall reservation |

At most 200 attempts may be planned. Aggregate limits are capped at 200 API
requests, 200 million tokens and seven days. A limit is an upper bound, not a
request to consume it. Each attempt retains the existing runner's stricter
individual limits, including exactly one reserved provider request.
The five-second launch grace is frozen in the plan policy and does not extend
the individual trial's gameplay or API budget.

Each fixture has exactly `id`, `scenario`, `baseline`, `runtime_manifest`,
`adapter_config`, and `budgets`. The four file references have shape
`{path:canonical_absolute_path,sha256:lowercase_SHA256}`. `budgets` is the existing
trial specification's exact budget object. The scenario's `trial_budgets` must
match it. New plans require runtime manifest schema 2 with the validated frozen
Docker invocation, including its local socket and optional fixed sudo launcher.

Each adapter configuration is the existing private
`{argv:[python,backend,"--config",backend_config],dependencies:[...]}`. The
coordinator checks its actual `CommandAdapter.fingerprint` and cross-checks the
backend's scenario, baseline, runtime manifest, state root, locks and orchestrator
against this plan. It reads files; it does not run Docker inspection or a backend
phase during plan creation. Actual runtime validation remains the runner's job.

The runner object has exactly:

```json
{
  "python": {"path": "/absolute/python", "sha256": "..."},
  "trial_script": {"path": "/protected/scripts/full_client_trial.py", "sha256": "..."},
  "dependencies": [
    {"path": "/protected/scripts/full_client_experiment.py", "sha256": "..."},
    {"path": "/protected/scripts/full_client_score.py", "sha256": "..."},
    {"path": "/protected/scripts/full_client_docker.py", "sha256": "..."},
    {"path": "/protected/scripts/full_client_readiness.py", "sha256": "..."}
  ],
  "state_root": "/private/existing-attempts",
  "world_lock": "/private/existing-world.lock",
  "queue_lock": "/private/existing-queue.lock"
}
```

These are placeholders, not usable runtime configuration. Paths must be canonical
and files protected from other users' writes. The configured runner must be the
same file imported beside the coordinator. Pin other dependencies as needed;
the backend's own dependency list remains mandatory and independently checked.

Plan/config/journal JSON is limited to 4 MiB. Runtime-manifest artifacts have an
independent 16 MiB limit matching the concrete backend's JSON reader. Baseline
verification streams up to 64 MiB without retaining its contents, matching the
backend's SQL restore limit. Oversized inputs are rejected from their file size
before reading contents or submitting a trial. The coordinator does not broaden
what the runtime can consume. Model inputs, configuration and source files are
never copied into a public report.

Before assigning IDs, plan creation validates the readiness policy against the
backend's hash-bound baseline snapshot and requires the readiness module among
the pinned runner dependencies. A missing, weakened or wrong-map policy is
rejected before a plan can submit a trial.

Plan creation assigns every 32-hex attempt ID before execution and records each
exact spec and SHA-256 of its canonical JSON bytes (sorted keys, compact JSON,
ASCII escaping and a final newline). The plan hash uses that same encoding.
Model order rotates within **each fixture** across repetitions. Position counts
are included and revalidated; exact position balance is claimed only when the
number of repetitions is a multiple of the number of models. Five repetitions
across four models produces counts of one or two per position, not exact balance.
Rotation does not claim deterministic combat or balanced carryover effects.

The plan is created atomically, fsynced and never overwritten. Once execution
starts, its hash is bound into the coordinator journal. Model order, attempt IDs,
fixture hashes, budgets and failure policy cannot be changed on resume.

## Execution and recovery

```sh
# Offline, private, create-once output; parent directories must already exist.
python3 scripts/full_client_experiment.py plan \
  --config /private/experiment-config.json --output /private/experiment-plan.json

# Explicit live execution: Linux root, existing protected runtime only.
python3 scripts/full_client_experiment.py run \
  --plan /private/experiment-plan.json --directory /private/experiment-state

# Only after inspecting the stopped experiment and any required trial recovery.
python3 scripts/full_client_experiment.py resume \
  --plan /private/experiment-plan.json --directory /private/experiment-state

# Offline, independent report over every planned ID, with create-once output.
python3 scripts/full_client_experiment.py report \
  --plan /private/experiment-plan.json --directory /private/experiment-state \
  --output /private/experiment-report.json
```

Apply the repository's shared-host memory, CPU-affinity and wall limits to these
commands. No command provisions a service or selects another world/queue lock.
Only one coordinator may hold its private experiment lock. The trial CLI itself
continues acquiring the existing world, queue and runner locks; the coordinator
does not wrap them in a conflicting second lease.

Before spawning a trial, the coordinator creates and fsyncs the exact request,
then fsyncs a submission intent with the full API/token/wall reservation. The
child uses the existing CLI with the fixed ID, minimal environment and no
inherited coordinator descriptors. Its kernel ancestry stays compatible with
the runtime's `runner -> guard -> backend` checks. An explicit timeout and Linux
parent-death signal terminate only the runner PID. Its independent guard and
bridge retain their leases until their existing cleanup protocol releases them;
the coordinator never kills them or claims an uncertain API request was refunded.

Any failure stops the experiment. The coordinator does not run recovery itself.
An explicit resume first reads every submitted attempt. Missing, corrupt,
running, failed or interrupted attempts remain unresolved; an absent journal
after submission is **not** proof that no request happened. Only a completed or
explicitly recovered attempt with matching identity, clean backend, cleanup and
final quiet-status receipts permits advancing to future unsubmitted entries.
The exception is a durable `retired_unlaunched` receipt created by the same
invocation that refused admission after fsync, before entering the launcher.
An explicit resume can advance past that receipt while the attempt directory
remains absent. Missing evidence alone never creates this exception.
Already submitted IDs are never invoked again. Observed terminal receipt hashes
are pinned; subsequent changes refuse continuation. Recovered attempts remain
invalid and visible in the report.

All reservations remain charged against the experiment, even if a trial reports
lower actual usage. Reported overspend cannot disappear below a reservation.
The original wall deadline survives resume and includes paused time. A backwards
clock refuses execution; monotonic time also bounds each active invocation.
Admission requires the full trial time plus a one-second launch margin, checked
again after submission-intent fsync. A nearly expired experiment cannot start a
partial trial. A synchronous deadline refusal at the fsync boundary retires that
ID with zero actual API/token usage while retaining its full reservation and
declared position. A crash without the durable retirement receipt, or any
exception after launcher entry, leaves the ID unresolved. Neither case permits
replaying the ID. Quarantine cleanup and an already uncertain
provider call may outlast active execution while retaining the existing locks;
this does not authorize another request or another trial.
Budget exhaustion, an unknown owner or unresolved attempt is an operator stop,
never permission to reset state, take over locks or silently select another ID.

## Complete-plan report

Reports enumerate every planned entry in declared order, including unsubmitted,
retired before launch, unresolved, failed, recovered and invalid-evidence cases.
Retired entries have no XP or no-op metrics and remain outside scored samples.
There is no recent-row
limit and no selection of the best attempt. Invalid or missing XP stays unknown;
it does not become zero. A model-generated zero score or negative persisted XP
remains a numeric outcome.

Completed trials are scored again using `verify_trial_bundle`, reading and
hashing actual baseline, persistence, native and lifecycle artifacts. The report
also checks fixture hashes, exact requested/returned model, API identity/usage,
executed runtime image and the schema-2 Docker binding. A journal score or
`artifacts_verified` flag alone is insufficient. These checks establish
consistency inside a trusted runtime, not authentication of a malicious collector.
Required journal, receipt, result and provider JSON envelopes must be objects,
even when their file hashes match. A malformed envelope makes that attempt
`invalid_receipts`; the report still includes every other planned entry.

Action/no-op claims additionally require matching attempted, acknowledged and
controller action counts with complete accepted action receipts. If those
optional execution counters are absent or contradictory within valid envelopes,
signed persisted XP can remain reportable
while actions/no-op stay unknown. The report does not run publication validation
or infer that a video was reviewed.

Per-model/per-fixture groups report planned and verified sample sizes, every
outcome count, the verified fraction of the plan, no-op count, signed XP mean,
median, range and sample standard deviation. The population is explicitly
completed attempts with verified persistence. Failure fractions remain alongside
it; no across-class score or ordering is produced. With fewer than two verified
samples, standard deviation is unknown. Confidence intervals remain null because
this report does not establish independent samples or a calibrated sampling
model. Repeated observations alone are not a dependable model ranking.

All outputs remain `ranked:false`; publication is separately `not_evaluated`.
Keep raw plans, reports, receipts and runtime paths private. A future public
projection requires deliberate review rather than exposing this state directory.

## Acceptance

Focused tests cover exact and imperfect rotations per fixture, immutable plans,
changed hashes/configuration, reservation-before-submission, missing journals,
explicit recovery, no replay, persistent deadlines, lock conflicts, actual
stdlib subprocess argv/environment/timeouts/parent death, and recomputation from
synthetic persisted bundles with signed XP and corruption. They do not call an
API or run a database/game service. Run them only through the repository's
serialized, capped validation workflow.

Release `2a93db5` passed a frozen single-entry plan with a saved qualifying
pre-API window and reviewed publication evidence. Before repeated or unattended
use, freeze a finite plan, verify existing runtime prerequisites, exercise the
whole repeated plan and explicit-stop/resume path, inspect its recordings, and
independently validate its publication evidence. A live readiness-timeout case
must also demonstrate zero provider requests. Historical 22/60-second protocols
and evidence remain unchanged; a later source revision needs its own frozen
release and acceptance before deployment.
A ten-minute fixed-clock protocol, native XP cutoff ledger, other classes,
replanning and party objectives remain separate work.
