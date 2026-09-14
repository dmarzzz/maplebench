# MapleBench: next simulation suite

Design version: `skill-suite-v1-draft-2026-09-14`.

Execution tracking: [progress summary](plans/skill-suite-v1-progress.md) and
[per-entry progress](plans/skill-suite-v1-progress.json). The executing agent
follows [progress update instructions](plans/AGENTS.md) and records verified
outcomes without rewriting this design or its schedules.

**Deliverable:** a controlled model × task matrix, supported by independently
verified task outcomes and complete attempt accounting. This is a proposed
experiment specification, not a record of completed experiments or a runnable
runtime configuration. No new model calls are authorized or launched by this
document. The schedule is exact; native fixture bindings and scorer acceptance
must be completed before it can become an executable frozen plan.

## 1. The decision

Build two separate result matrices:

1. **Skill tasks:** platforming, native Teleport, potion use, buff upkeep,
   navigation and recovery. Cells show successful trials / evaluable trials,
   evidence coverage, and uncertainty. These are new evaluations.
2. **Training:** classes as fixtures, scored by a separately versioned native
   XP protocol. Keep the existing five-minute saved-net-XP pilots as historical
   results. Do not infer skill grades or peak rates from their recordings.

The first model batch is **96 trials**: four model configurations × three
concrete tasks × two fixture variants × four repetitions. It is a development
pilot, with eight trials per cell. It diagnoses the task contracts and harness;
it is not the final comparative cohort.

After qualifying all six tasks, freeze a **576-trial comparative cohort**:
four models × six tasks × three variants × eight repetitions. This provides
24 attempts per model/task cell, distributed equally across the three variants.
Do not pool the development pilot into that cohort. A changed prompt, fixture,
SDK, scorer or deadline creates a new version.

The proposed models are the exact identifiers already represented in the public
catalog: `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`.
Recheck availability before freezing requests. Record both requested and returned
model identity; substitution creates a new model configuration. Keep the same
low reasoning setting, prompt scaffolding, information, memory policy and caps
where supported. An unsupported setting must be declared and separated; do not
silently normalize it away.

## 2. What exists, and what still needs implementation

This assessment is based on the reviewed local source and the public pilot
snapshot, not a fresh inspection of live worker state.

| Component | Existing support | Required for this plan |
| --- | --- | --- |
| Normal game inputs | `observe`, `pressKeys`, `wait`; bounded JavaScript; host RPC | Retain this boundary and validate the task-specific allowed key set |
| Adaptive control | Versioned 300-second controller; optional 1,800-second successor | Add a separate 120-second skill-task contract; no change to old protocol IDs |
| Observations | Character state and nearby monster positions | Versioned task descriptor, relevant geometry/portal information, inventory counts and buff status |
| Persistence | Normal logout, baseline and final DB checks | Keep as independent evidence; endpoint XP is not a movement/buff verifier |
| Native XP | Ledger, fixed-window scoring, level-transition and publication code | Require evidence of acceptance for the exact deployed build and fixture |
| Skill telemetry | Physical bindings and unscored previews | Native item/buff/transition/skill-effect evidence and a task scorer; key receipts alone are insufficient |
| Experiment execution | Finite local runner; operator-managed worker assignment | Freeze a cross-worker assignment manifest and reconcile every planned entry |
| Public matrix | Verified XP by class; unscored skill previews | New skill result schema and UI, keeping success/failure/unknown/unrun distinct |

The source declares that Night Lord Flash Jump is unsupported, and Bowmaster
Hurricane is discrete rather than canonical continuous channeling. Do not make
either the basis of a supposedly canonical movement/attack task. Native Teleport
has a declared route but still requires fixture-specific qualification. Both
potion keys currently consume the same Power Elixir supply; never describe them
as independent HP and MP inventories.

Source anchors: [adaptive controller](../scripts/full_client_adaptive.py),
[ordinary replanning baseline](../scripts/full_client_baseline.py),
[toolkit declarations](../scripts/full_client_skill_toolkit.py),
[unscored preview contract](../scripts/full_client_skill_preview.py),
[native XP delivery](FULL_CLIENT_NATIVE_XP_DELIVERY.md).

## 3. Exact first sequence

| Order | Work | Entries | Advance only when |
| --- | --- | ---: | --- |
| 1 | Inventory the intended three workers; bind source/JAR/client/SDK/scorer hashes and private runtime configuration | 3 inventories | Matching software, isolated worlds, clean baseline restore and sufficient measured resources |
| 2 | Implement task observations, native event collection and offline verifiers for platforming, Teleport and potion use | 3 contracts | Positive, negative, boundary and tampering tests pass |
| 3 | Bind three native fixture variants for each initial task; run two positive and two negative control traces per variant | 36 zero-model traces | Every positive satisfies the criterion; every negative is rejected for the intended reason; original evidence retained |
| 4 | Freeze the first model pilot and all IDs before dispatch | 96 model trials | The exact plan has no unresolved fixture/scorer bindings |
| 5 | Review all pilot outcomes and a model-balanced sample of recordings | All 96 records | Publish the complete diagnostic cohort; document any contract defects before changing them |
| 6 | Implement and qualify buff upkeep, navigation and recovery using the same native control recipe | 36 additional zero-model traces | Full task evidence, complete coverage and ordinary restore verified |
| 7 | Freeze a fresh comparative suite | 576 model trials | All six contracts and all three variants per task are accepted; budget reservation and storage preflight pass |
| 8 | Run a separate native-XP training qualification, then evaluate whether to launch a longer training cohort | Separate plan below | Exact native build, normalization, capture and per-class toolkit accepted |

Negative controls are deliberate native test programs, not failed model trials.
Their zero scores do not enter a model row. All qualification entries have their
own identities and manifests. The first 96-trial schedule uses variants 1 and 2;
variant 3 is qualified before model exposure and reserved for the larger suite.
The final suite remains a new evaluation cohort even if no pilot defect is found.

## 4. Common task contract

**Experimental unit.** One fresh agent session on one named task/variant, with a
restored offline database, fresh controller state and no cross-trial memory.
Repeated episodes are not independent samples of model weights; they measure
run-to-run performance under these fixed agent configurations and task variants.

**Task descriptor.** Every model receives the same goal, deadline, success
criterion, allowed keys and task-relevant information. Movement tasks include
the relevant local foothold geometry and target region; navigation includes the
same map/portal adjacency information. Resource tasks expose the corresponding
inventory and buff state. These are new versioned observations, not claims about
the current SDK. Scoring remains based on separately collected native evidence.

**Scope.** Use a level-180 Ice/Lightning fixture for the first six capability
tasks to reduce class variation. Each task has a restricted, explicitly frozen
toolkit and starting inventory. It is a new fixture: the current canonical full
toolkit validator must not be weakened to admit arbitrary changes. Canonical
skill levels and item semantics come from the pinned native runtime. Different
variants change the declared start/goal or resource quantity, not the prompt’s
amount of guidance.

**Clock.** The skill-task clock starts immediately before the first model request,
after readiness passes. Inference, execution, observation and gameplay waits all
consume the same wall budget. Events must occur within `[start, deadline)`.
Post-deadline settlement verifies persistence but cannot turn a late outcome
into an on-time success. A success may end a short task after the required dwell
interval and immutable terminal evidence are captured. Buff upkeep always needs
coverage through its full deadline.

| Limit | Three short tasks | Three extended tasks |
| --- | ---: | ---: |
| Wall budget | 120 s | 300 s |
| Provider requests | At most 4 | At most 12 |
| Output tokens per response | 3,000 | 3,000 |
| Aggregate reserved/actual token ceiling | 96,000 | 240,000 |
| Ordinary program bound | 10 s | 20 s |
| Attempted input actions | 600 | 1,600 |
| SDK requests | 2,000 | 6,000 |
| Provider timeout | At most 30 s | At most 50 s |
| Final control/settlement reserve | 5 s | 5 s |

These are proposed ceilings, not existing accepted 120-second runtime settings.
They are maxima, not target spend. Token reservation must use the actual request
envelope and conservative existing accounting; it cannot be inferred from
reported token usage alone.

**Request admission for the new skill protocol.** Permit a model call only with
at least 15 seconds remaining. Clamp its timeout to the smaller of the declared
provider timeout and `remaining_seconds - 10`; reserve at least five seconds for
control plus five for closeout. After inference, clamp the ordinary program to
`deadline - 5 - now`. Do not submit an input RPC unless its full three-second
ACK bound fits. Once admission or a confirmed aggregate cap closes, only passive
observation continues. Freeze this policy under a new skill protocol ID; it is
deliberately different from the old pilot’s 75-second admission reserve.

**Prompt policy.** A response is an async JavaScript function body, run once
without repair or replay. Feedback includes fresh observed state, remaining
budgets and the last two programs with their last five SDK receipts. Use the
same fixed documentation. No human hints, candidate search, auxiliary model,
hidden combat policy or retrospective rewrite of a generated no-op.

## 5. Task specifications

The six IDs below are stable design identities. Native map IDs, coordinates,
footholds, portal IDs, asset hashes and selected skill durations are binding
inputs, not facts we can infer from a gameplay screenshot. They must be filled
by the deterministic fixture binding procedure in section 6 before launch.

### S1 · `platforming-v1` · 120 seconds

- **Question:** Can the agent use position feedback and ordinary movement to
  reach and settle on a target platform?
- **Start:** Full HP/MP; safe map, no monsters, no active movement buffs. A fixed
  start foothold, facing and position. Only LEFT, RIGHT, UP, DOWN and JUMP inputs.
- **Variants:** V1 one rightward jump; V2 one leftward jump; V3 two linked jumps.
  Target regions lie inside their footholds with a 16-pixel edge margin. The
  native oracle must reach each target within 20 seconds without a movement skill.
- **Goal supplied to model:** Target map/foothold and target region, relevant
  local geometry, normal movement bindings and the one-second landing requirement.
- **Success:** Valid movement trace, alive, target map and target zone reached,
  with a grounded/foothold-consistent position continuously for 1,000 ms before
  the deadline. Use at least 10 Hz verified position coverage; reject gaps above
  250 ms during the dwell interval. Never treat a single passing frame as landing.
- **Controls:** Two independent successful native traces; a no-op trace; a trace
  that enters the zone in flight but does not satisfy the landing dwell.
- **Diagnostics:** First arrival, stable completion time, falls and path length
  only if the required event coverage exists. They do not change the binary score.

### S2 · `native-teleport-v1` · 120 seconds

- **Question:** Can the agent execute a directional native movement skill and
  stop at a specified destination?
- **Start:** Full resources, no monsters/buffs; native Teleport bound to its
  declared key. Starting region and target region fixed. Normal movement and
  the Teleport key are allowed; attacks and other mobility skills are disabled.
- **Variants:** V1 rightward Teleport, V2 leftward Teleport, V3 a two-cast route.
  Use the pinned skill’s real distance and collision behavior. Do not invent a
  gap, force a position change, or require an impossible canonical behavior.
- **Success:** At least one accepted native Teleport execution (two for V3),
  linked to the ordinary skill path, legal displacement and native MP cost,
  followed by 1,000 ms stable presence in the target region while alive. For V3,
  retain the ordered intermediate region as a required milestone.
- **Evidence:** Skill execution/commit identity, server-accepted movement,
  resource transactions and continuous arrival coverage. Model-written state,
  a key ACK or a visible animation is not the scorer input.
- **Controls:** Two successful native traces; walking-only arrival (must fail);
  a Teleport request with insufficient MP (must not count as a completed cast).

### S3 · `potion-use-v1` · 120 seconds

- **Question:** Can the agent detect low MP and consume a finite resource?
- **Start:** Safe map, no monsters, full HP, no active buffs; MP at 10%, 15% or
  20% of the pinned maximum for V1/V2/V3. Exactly one Power Elixir (item 2000005).
  Both potion keys access that same item. Movement and potion inputs are allowed;
  offensive skills, trading, refills and other recovery routes are excluded.
- **Success:** The native item-use path consumes exactly one supplied potion,
  inventory decreases from one to zero, and the linked MP restoration reaches
  at least 80% of maximum before the deadline, while alive.
- **Evidence:** Item transaction, inventory before/after and attributed resource
  change. Passive regeneration is separately identified; reaching the threshold
  without item consumption cannot pass.
- **Controls:** Two successful traces using the qualified potion binding; a
  passive wait; a request in the deliberately empty-inventory control fixture.
- **Diagnostics:** Time to potion use, redundant requests and remaining MP.
  Do not claim potion-management strategy from this one-item task.

### S4 · `buff-upkeep-v1` · 300 seconds

- **Question:** Can the agent activate and renew a useful timed state?
- **Start:** Safe map, full HP/MP, exactly one named native buff available, absent
  initially. No automatic refresh, outside help or resource refills. Supply a
  fixed sufficient potion budget, also visible to the model.
- **Binding:** Select a genuine native skill/level whose duration is 60–120 s,
  freeze that value, and expose it in the task descriptor. Do not shorten the
  server duration artificially. If none qualifies, the task remains blocked
  rather than becoming a five-minute test satisfied by one ten-minute buff.
- **Variants:** Three fixed initial resource supplies, each sufficient for the
  oracle to maintain the buff; freeze exact counts before model runs.
- **Success:** Buff active for at least 90% of `[start + 15 s, deadline)`, alive
  throughout, and at least one actual renewal after the first application. The
  15-second initial grace is included in the wall budget, not extra time.
- **Evidence:** Native apply, refresh, cancellation and expiration events with
  complete ledger coverage. Compute the union of active intervals clipped to
  the scoring interval; overlapping renewals must not double-count uptime.
- **Controls:** Two sustained-renewal traces; no cast; one cast then no renewal.
  Remove an expire event from a copied ledger to verify corruption is unknown,
  not a passing uptime score.

### S5 · `portal-navigation-v1` · 300 seconds

- **Question:** Can the agent follow a short map/portal route using ordinary inputs?
- **Start:** Full resources in a safe source map. Provide the same route graph,
  portal names/positions and destination to each model. No Return Scroll,
  teleport item, administrative warp or class movement shortcut.
- **Variants:** Three two-transition routes of the same declared length. Each
  uses distinct portal identities; each native oracle completes within 45 s.
- **Success:** The ordered two required portal transitions, followed by alive
  presence in the destination region for 1,000 ms, all within the deadline.
- **Evidence:** Native transition events binding from-map, portal, to-map,
  character and trial, plus final region coverage. Being on the destination map
  after an unrelated warp does not satisfy the ordered route.
- **Controls:** Two correct traces; stop in the intermediate map; reach an
  incorrect destination. Score route completion, not XP.

### S6 · `return-to-hunt-v1` · 300 seconds

- **Question:** Can the agent restore resources, navigate and resume progress
  from a matched setback state?
- **Start:** An offline fixture representing a return-to-town setback: 30% HP,
  15% MP, three Power Elixirs, fixed gear and a declared two-portal hunting route.
  No death is injected during the run; the current runner stops on death.
- **Variants:** Three prequalified return routes and hunting spawn fixtures.
  Starting resource ratios and supplies are identical across models per variant.
- **Success:** Consume a supplied potion through the ordinary item path, traverse
  the required route, and receive a positive native gameplay XP transaction on
  the hunting map before the deadline while still alive. All milestones required.
- **Evidence:** Resource transaction, ordered map transitions, native XP ledger
  and final alive state, bound to the same trial. Administrative awards, restored
  XP, a client HUD delta or a stale earlier XP event cannot satisfy the criterion.
- **Controls:** Two complete traces; recover resources but stay in town; reach
  the hunting map without a positive XP event. A native control with zero XP is
  a failed qualification, not proof that the model task is impossible.
- **Limit:** This measures recovery from a prescribed initial setback, not
  adaptation to a surprise death, respawn handling or multiagent cooperation.

## 6. Fixture binding and readiness

Before freezing a live plan, produce a private manifest for every task/variant:
runtime/source hashes, baseline SQL hash, class/job/level, equipment and inventory
hashes, map/foothold/portal identities, spawn/facing, target region, skill IDs and
levels, native cost/duration values, allowed keys, observation schema, prompt
hash, scorer hash, readiness rule and exact budgets.

Select geometry before observing model outcomes. Enumerate eligible candidates
from the pinned runtime in map-ID/foothold-ID/portal-ID order, apply the declared
constraints, then use the first qualifying candidate for each variant. Preserve
the candidate list and rejection reasons privately. If constraints cannot be
satisfied, revise the design version before any comparative model run. A human
must not quietly move the target after seeing a model fail.

Asset files, baseline SQL, raw geometry exports, hostnames, credentials and
personal/account identifiers stay outside Git and the public site. The public
plan contains semantic task descriptions and hashes of accepted bindings. The
current JSON intentionally has null bindings; the runner must reject them.

Readiness is task-specific. Safe movement/resource tasks require fresh character,
map, resource and terrain state, rather than a monster that should not exist.
Hunting requires a populated qualified scene. Require at least three increasing
post-render samples spanning one second, valid character/expected map and the
task-specific conditions. Keep the existing freshness bound of 1,500 ms and a
10-second readiness deadline. Bind the exact initial model observation and the
separate initial native state. Record first-scene differences; restored input
hashes do not establish identical combat RNG or monster positions.

## 7. Outcome accounting and scoring

Every planned entry ends in exactly one public accounting state:

| State | Condition | Cell treatment |
| --- | --- | --- |
| Success | Complete trustworthy evidence satisfies every task criterion | Add one success and one evaluable trial |
| Gameplay failure | Complete evidence; deadline, death, no-op, wrong destination or unsuccessful strategy | Add zero successes and one evaluable trial |
| Invalid / infrastructure | Missing/corrupt evidence, wrong model/fixture, stale coverage, failed restore, unresolved input or provider receipt | Separate invalid count; never silently zero or success |
| Not started | No submitted execution for the frozen entry | Unrun count; never inferred from a missing journal after submission |
| In progress | Admitted run not yet terminal | Explicit state; never provisional score |

Primary cell: `k / n_evaluable` and `n_evaluable / N_planned` coverage. Display
the invalid count alongside it. A model with poor evidence coverage cannot look
equally reliable merely because its few valid runs succeeded. Also report the
conservative confirmed-success yield `k / N_submitted` as a separate operational
metric; explain that this includes unverified submissions and is not a pure
gameplay success probability. Do not combine the two denominators.

For partial coverage, report bounds on success among submitted trials:
`k / N_submitted` through `(k + n_invalid) / N_submitted`. Unknowns remain unknown;
the upper bound is a sensitivity bound, not an imputed outcome. An unfinished
cohort has no final estimate.

Task outcome is primary. Time-to-success is secondary, measured from the same
wall-clock start. Report completion counts first and successful-trial latency
distributions second. Do not rank models on success-only speed, which can reward
fast rare successes. Include failed tasks as deadline-censored observations when
plotting completion-over-time curves; infrastructure failures need their own
coverage trace, not an assumed completion time.

No score based on screenshots, model self-assessment, code mentioning a skill,
button counts or a reviewer’s impression. Native control/visual review qualifies
the implementation; an offline deterministic scorer evaluates model episodes.
Store native event IDs and the exact predicate that established each outcome.

## 8. Replication, assignment and statistical reporting

The companion schedule fixes task, variant, repetition, model, admission order
and intended worker lane. Each four-model block rotates the model order, with
four repetitions in the development pilot and eight in the comparative suite.
Every model occupies every admission position equally often within a variant.
Admission position is a scheduling slot, not a claim that overlapping runs have
the same wall-clock start or equivalent game randomness.

Assume three qualified worker lanes, A/B/C, for planning. A lane contains a whole
isolated world and runs one trial at a time. Worker assignment is
`(variant_index + repetition_index + model_index) mod 3`. Across the final three
variants × eight repetitions, each model/task has exactly eight assignments to
each lane. In the two-variant pilot, lane counts differ by at most one. Rebind
the plan if the accepted worker count is different; do not pretend a lane exists.

Within a block, admit up to three trials in the frozen order, subject to each
lane being free. Wait for all four to close before the next block. Record actual
start/end times, worker identity/hash, provider time, resource pressure and
failure phases. Balance assignment without claiming an implemented automatic
fleet scheduler; the existing operator can dispatch an immutable manifest until
an independently tested dispatcher is available.

No deterministic game seed is currently established. The paired unit is the
same task/variant/repetition block under separately reset worlds, not identical
random events. Any future seed must state which random sources it controls.

For the final n=24 cell, publish a 95% Wilson interval as a descriptive binomial
summary, with all three variant breakdowns. At 12/24 the interval is approximately
31.4%–68.6%; at 24/24 its lower endpoint is about 86.2%. These are broad intervals,
not evidence that 24 runs guarantee a precise ranking. Mixed task variants can
violate identical-probability assumptions; retain per-variant rates and use a
variant-stratified bootstrap for model differences, resampling whole matched
repetition blocks rather than individual model outcomes. With only three variants,
this quantifies episode variation conditional on this suite, not broad task
generalization.

Use 10,000 bootstrap resamples and analysis seed `20260914`. Within each variant,
resample eight repetition blocks with replacement, keeping the model outcomes
together; average the three variant rates with equal weights. Preserve complete
paired blocks for comparative estimates; list the blocks excluded for invalid
evidence and show conservative sensitivity bounds. Do not replace missing paired
outcomes with zero. Before formal claims across the six model pairs × six tasks,
use exact paired McNemar tests on the discordant binary outcomes in complete
blocks, subject to the independent-episode assumption, and apply Holm correction
across the 36 tests. Exploratory intervals remain descriptive. No significance
claim is required for the first public release.

Do not stop a cell after a favorable streak. Run the fixed attempt set, except
for operational aborts. A pilot-discovered defect stops the affected cohort;
repair and use a new version. Do not selectively rerun poor gameplay. A later
precision study is a new declared cohort, not an invisible extension chosen to
reach significance.

## 9. Matrix presentation

- Stable model rows; six labelled task columns grouped as **Control**,
  **Resources**, and **Planning**. Use small game-like symbols with readable labels.
- Planned tasks: dashed empty squares and “Unrun”; no decorative success values.
- Skill results: `k/n` in a square, absolute success-rate color fixed to 0–100%,
  with sample count, Wilson interval, invalid count and coverage in the drilldown.
- XP pilots: exact signed XP; neutral zero, warm negative values, green gain;
  color relative within the same fixture only. Do not apply skill percentages.
- Partial/invalid evidence: a visible distinct state and coverage count. A measured
  `0/24` must look different from `—` and from `?`.
- Selected cell: task goal and version, model/configuration, complete attempt list,
  per-variant outcomes, timing distribution, coverage and original recordings.
- No combined winner across binary skill success and XP/min. No “intelligence”
  percentage. If a future suite score is needed, freeze task weights and failure
  handling under a new version before collecting the comparative cohort.

The website now separates historical class pilots from the six proposed skill
columns. The latter describe these contracts; they do not claim the new SDK,
telemetry or scoring adapters are implemented.

**Fit the plan to the actual reporting limits.** The current finite planner caps
a plan at 200 attempts and 16 fixtures; `full_client_research.summarize` accepts
at most 100 raw rows. The existing cohort publisher also assumes a four-entry
model cohort. A 576-row upload cannot be passed through these paths unchanged.
Create six immutable comparative task shards of 96 attempts each, with three
variants per shard; retain one suite manifest binding all six shard hashes and
the complete 576-entry denominator. The development pilot can use three task
shards of 32 attempts. Implement a versioned skill publication adapter with
preaggregated matrix cells, per-task attempt pages/data and a complete manifest.
Do not drop rows, broaden a legacy protocol implicitly, or use a UI-only filter
as evidence of complete experiment accounting.

## 10. Separate training track

First qualify the real native XP path for Hero, Bowmaster and Ice/Lightning,
including positive gain, level transition and death-loss cases on the exact
native build. Treat class/toolkit acceptance separately; one class’s successful
trace cannot qualify another’s bindings. Add Night Lord only under a separate
accepted fixture without promising Flash Jump or unsupported effects.

The next training qualification is **12 model trials**: four models × three
classes × one 300-second run, using `full-client-xp-windows-v1` and the exact
accepted toolkit/prompt/controller policy. These are qualification results,
unranked and not a repeated-trial comparison. Existing saved-XP pilots remain
unchanged and under their original protocol.

After that, a proposed 30-minute cohort is **96 runs**: four models × three
classes × eight repetitions, with `final-program-slot-1800-v1`, the explicit long
capture policy and 120 complete 15-second native windows per run. Use three
workers only after concurrency and capture capacity are accepted. This cohort
requires separate compute/API authorization; it is not launched by this plan.

For each complete window j, retain signed native XP change. Normalize rate by
the declared, independently checked XP and simulation-time multipliers:
`rate_j = delta_xp_j / elapsed_minutes_j / xp_multiplier / speed_multiplier`.
Do not borrow RuneBench’s numerical multiplier. Run score is
`max(0, max_j rate_j)` over complete eligible windows. Keep signed total net XP,
all windows, progression and losses separately. A brief peak is not sustained
efficiency. A late event at the exact deadline cannot enter the control metric.

For repeated training runs, the proposed primary cell statistic is the median
of per-run peak rates, with all eight values and a descriptive bootstrap interval.
Do not let the current reporting layer silently average a differently defined
quantity: this statistic needs an explicit versioned aggregation field. The
long-horizon suite is a future contract, not a reinterpretation of today’s mean
saved-XP cells. No log aggregate is used for this release.

## 11. Budgets and storage

These are control-time ceilings, excluding readiness, server start/restore,
logout, probing, upload and review. They are not elapsed-time promises or dollar
estimates. Peak memory and actual turnaround must be measured on qualified hosts.

| Phase | Trials | Control worker-hours | Ideal lower bound with 3 workers | Maximum provider calls |
| --- | ---: | ---: | ---: | ---: |
| Native qualification, first three tasks | 36 | 1.2 | 0.4 h | 0 |
| Initial skill pilot | 96 | 3.2 | 1.07 h | 384 |
| Native qualification, remaining tasks | 36 | 3.0 | 1.0 h | 0 |
| Six-task comparative cohort | 576 | 33.6 | 11.2 h | 4,608 |
| Five-minute training qualification | 12 | 1.0 | 0.33 h | 144 |
| Future 30-minute training cohort | 96 | 48.0 | 16.0 h | 6,912 |

Reserve at most 9,216,000 tokens under the conservative aggregate ceiling for
the initial skill pilot; the full six-task cohort’s corresponding ceiling is
96,768,000. These reservation ceilings can greatly exceed actual billed usage.
Before any API launch, bind current provider pricing and an explicit dollar cap
to the actual per-model ceilings. No price or spend authorization is inferred here.

The static publication payload currently has a 512 MiB cap. Hundreds of original
recordings cannot be presumed to fit. For a capacity illustration only, 576
clips averaging 20 MiB consume 11.25 GiB before native evidence and replicas.
Measure actual bitrate/size on qualification traces. Select approved object
storage with immutable object hashes, retention and access controls before a
full rollout; this requires an explicit publication-path change and revalidation
of the current same-origin recording allowlist. Keep public sanitized manifests
separate from private raw receipts. Do not trim, omit or transcode evidence to
make an oversized cohort silently fit.

## 12. Required implementation and acceptance checks

1. **Task contract validator:** immutable IDs, exact fields, known controls,
   finite bounds, qualified fixture/scorer hashes and explicit clock policy.
   Reject null bindings, unsupported skills and mismatched toolkit/prompt versions.
2. **Observation adapter:** inventory, buff status and task geometry/portal
   descriptor. Validate freshness and schemas; keep private scorer internals and
   host credentials outside the agent’s sandbox.
3. **Native ledger:** ordered events, trial/character/world identity, monotonic
   timestamps, completeness envelope, item/buff/transition/effect transactions
   and linked state. Define movement trust explicitly: server-accepted client
   movement with geometry/physics validation is not a claim that Cosmic simulates
   all physics authoritatively. No unvalidated client coordinate can score a task.
4. **Task verifiers:** separate pure functions for the six predicates; consume
   checked event artifacts. Test no-op, exact deadline, insufficient resource,
   wrong skill, target fly-through, missed renewal, wrong portal, old XP event,
   counter reset, duplicate/missing/out-of-order records and corrupted hashes.
5. **Runtime closeout:** successful/failed gameplay can still finish cleanly;
   death is a valid task failure only with enough terminal evidence. Uncertain
   submissions are never replayed. Recovery reconciles the original attempt.
6. **Reporter:** complete planned set, correct denominators, protocol separation,
   null/zero/negative distinctions, per-variant breakdown and versioned aggregate.
7. **Publication:** no raw prompts, code, accounts, SQL or game assets; pin exact
   original recording hashes, eligibility checks and deployment receipt. A valid
   score and a failed recording publication remain separate facts.
8. **Worker parity:** match accepted software and fixture hashes; use native
   controls on every worker. Log resource limits and pressure. Shared machines
   still permit only one bounded build/test job at a time. Concurrency of actual
   simulations requires separate worlds and measured resource headroom.

### Fields that must be bound before execution

| Binding | Why it is currently unresolved | Acceptance artifact |
| --- | --- | --- |
| Exact live release and three worker inventories | This plan did not inspect or mutate runtime hosts | Signed/hash-bound inventory and clean readiness receipts |
| Maps, target zones, footholds and portals | Screenshots cannot qualify geometry or routes | Per-variant fixture manifest plus native positive/negative traces |
| Buff identity, skill level and duration | Renewal must actually be necessary in 300 seconds | Native definition and apply/expire/refresh evidence |
| Native item, movement, skill and transition ledger hooks | Existing XP-only and input receipts do not cover all predicates | Source hashes, fixture-bound native traces and deterministic verifier checks |
| 120-second task controller, scorer and publication schema | Current accepted durations are not this new task contract | New versioned admission/capture/closeout acceptance |
| Current model access and spend cap | Availability/pricing may change; this is planning only | Frozen requests, per-model reservations and authorized dollar limit |
| Original-video storage for hundreds of trials | Existing static site cap is insufficient at plausible sizes | Measured sizes and accepted storage/publication configuration |

## 13. Sources and design rationale

These references inform the design; they do not validate MapleBench’s runtime.

- [RuneBench task generator](https://github.com/MaxBittker/runebench/blob/main/generate-tasks.ts):
  concrete skill objectives and declared time budgets. MapleStory’s class axis
  is different from RuneScape’s independently trained skills.
- [RuneBench heatmap](https://github.com/MaxBittker/runebench/blob/main/app/components/Heatmap.js):
  compact model/skill cells and trajectory drilldown. MapleBench preserves
  missing evidence and signed XP separately instead of adopting its absent-data
  fallback or combining incompatible metrics.
- [Hafner, Crafter](https://danijar.com/project/crafter/): recognizable game
  achievements motivate understandable task columns with concrete outcomes.
- [Xie et al., OSWorld](https://arxiv.org/abs/2404.07972): task-specific execution
  evaluation motivates checking environmental outcomes rather than fluent plans.
- [Agarwal et al., statistical reliability in game-agent evaluation](https://arxiv.org/abs/2108.13264):
  motivates reporting variation and uncertainty instead of treating a small-sample
  point estimate as a reliable ranking. Our sample sizes and task criteria above
  are explicit design proposals, not values prescribed by that paper.
- Local sources: [research framing](RESEARCH_FRAMING.md),
  [finite experiment execution](FULL_CLIENT_EXPERIMENTS.md),
  [class benchmark design](CLASS_BENCHMARK_DESIGN.md),
  [native XP delivery](FULL_CLIENT_NATIVE_XP_DELIVERY.md),
  [long-horizon contract](FULL_CLIENT_LONG_HORIZON.md).

Companion artifacts: [machine-readable design](plans/skill-suite-v1.json) and
[all proposed model entries](plans/skill-suite-v1-schedule.csv), and
[native control entries](plans/skill-suite-v1-native-checks.csv). They contain no
live credentials, executable host configuration or fabricated result values.
