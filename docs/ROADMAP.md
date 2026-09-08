# MapleBench goal, roadmap and burn-down

Decision snapshot: September 8, 2026. This is the current product roadmap; older
implementation plans remain useful technical references. Checkboxes mean the
stated acceptance evidence exists, not merely that code or tests exist.

## Goal

Build a public, reproducible benchmark of coding agents playing through the
real game client, across representative MapleStory classes and objectives.
A reader should be able to understand the task, compare models under the same
declared conditions, inspect the score's evidence, and watch what actually
happened. An operator should be able to run a finite experiment and publish it
without repairing the environment between models.

The evaluated system is **model + agent harness + tools + knowledge + budgets**.
Agents receive a frozen SDK and observations, write programs, and control the
ordinary client. Video shows the actual client; this is not currently a
vision-only benchmark. No hidden grinding policy should make the strategic
decisions being attributed to the model. The client is a reconstruction connected
to the emulator; official-client fidelity is not established.

The first parallel deliverables are an isolated cloud worker and a clean
four-model showcase. The research product is a repeated model-by-task suite.
The first longer public pilot targets five minutes per model and class,
with finite predeclared cohorts. One short
run per model cannot establish the research product.

## Where we are

| Area | Demonstrated now | Remaining gap |
| --- | --- | --- |
| Gameplay | Actual rendered movement/combat and native inputs | Reliability across an entire unattended experiment |
| Scoring | Frozen offline reset, ordinary logout, committed save evidence and signed persisted XP | Fixed-horizon event cutoff, level transitions and richer metrics |
| Attribution | Exact requested/returned model, program, action receipts and video hashes | The same standard across a fresh complete group |
| Public experience | Vercel site and working replay with the opening API wait skipped | Automatic public updates, curated cohort page and clear phases |
| Comparison | Historical trials from Astra, Sol, Terra and Luna | Fresh complete group on the corrected contract; balanced repetitions |
| Agent behavior | Repeated model replanning and full five-minute observation horizons | More useful action time within a frozen budget; repeated completion |
| Task coverage | Accepted full-client Hero hunting fixture | Ranged, magic, navigation and progression fixtures |
| Operations | Finite coordinator, recovery and lifecycle components have tests and separate live acceptances | Repeated complete groups and composed restoration without ad hoc repair |

## Current five-minute pilot evidence

The public site now contains a protocol-separated Hero pilot alongside the
preserved historical archive. Astra `d5ae529a7b574f399a37e899472bb0a3`
completed the 300-second horizon with 98 acknowledged actions and **+18,250
persisted XP**. Sol `565e2442ed754420913490f54243f623` completed the same
horizon with 128 acknowledged actions and **+27,500 persisted XP**. Both were
alive at logout, and their hashed recordings are publicly playable from the
first acknowledged input. These are unranked pilot observations, not repeated
research estimates or native peak-XP scores.

Both controllers replanned repeatedly, then exhausted their conservative token
reservation allowance and observed without issuing inputs for the remainder.
The complete recording preserves those waits. The UI identifies observation-only
periods; a five-minute horizon does not mean five minutes of continuous action.

Terra `33da8a6c16bf468295844e76cf211c6b` failed final recording validation:
its decoded duration differed from the recorder callback interval by 117ms,
exceeding the frozen 100ms guard. It was recovered without another model request
and remains unscored. Luna `62f1ed7539904033812792ae39a26b97` executed ten
acknowledged actions before browser/display service restarts interrupted its
controller. Its outer API outcome remains conservatively uncertain. It has no
accepted score. The group therefore does not constitute four valid results.

The isolated worker passed scripted native acceptance before this cohort:
72 pixels of vertical jump displacement, physical attack, mapped skill MP
consumption, monster contact, and +4,500 XP verified again after ordinary logout.
That acceptance used no evaluated model. Rendering uses Chrome with SwiftShader
on four dedicated virtual CPUs; the short acceptance sample produced roughly
ten fresh rendered observations per second.

The replacement explicit-frame recording path is implemented and passes isolated
browser encode/decode tests, but has not passed loaded-game native acceptance.
Two successive checks hit an eight-frame encoder backlog after roughly 2.4
seconds, with 11 submitted frames and only three encoded outputs. Both checks
closed without a publishable recording and restored the baseline. Changing the
VP8 latency mode did not resolve that loaded-game failure. The next acceptance
must demonstrate the complete capture alongside jump, combat and ordinary save;
unit tests or encoder-only probes cannot close this gate. These checks used no
model API calls and cannot reclassify the failed Terra recording.
Bowmaster and Ice/Lightning fixtures are prepared; native acceptance and their
model cohorts remain pending. Native 15-second XP windows have an independently
built candidate, but are not deployed or represented as completed research runs.

## What RuneBench quality means here

RuneBench provides a useful model: agents use a TypeScript SDK and reference
material, face a matrix of tasks, and produce inspectable results. Its task
generator covers 16 skills at two horizons and four gold starting conditions.
The inspected schema varies skills rather than character classes. MapleBench
should translate that breadth into class mechanics and gameplay objectives.
[Task generator](https://github.com/MaxBittker/runebench/blob/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac/generate-tasks.ts)

RuneBench deliberately rewards peak XP rate to encourage exploration. Its own
discussion also identifies long inference/planning time and small samples as
limitations. We should borrow its task diversity, readable comparisons and
behavioral evidence while stating our own clock and sampling policy.
[Project methodology](https://maxbittker.github.io/runebench/)

Its verifier computes the highest positive rate between adjacent samples,
normally sampled every 15 seconds, with scaling specific to that environment.
We cannot derive that metric from two saved XP snapshots or transfer its scale
to MapleBench. Its heatmap's logarithmic aggregate also assumes nonnegative
rates; our signed net XP needs a different, explicitly chosen treatment.
[Verifier](https://github.com/MaxBittker/runebench/blob/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac/shared/check_skill_xp.ts),
[heatmap](https://github.com/MaxBittker/runebench/blob/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac/app/components/Heatmap.js)

This is a quality target for the experiment and reader experience, not a claim
that matching another benchmark's task count or visual design proves validity.

## Product and measurement decisions

1. **Keep the next showcase small.** Use the existing four exact models and
   one accepted fixture. Roll out the targeted reconnect fix without making
   every new orchestration feature a prerequisite to a supervised run.
2. **Make the longer protocol explicit.** Deliver a frozen five-minute pilot
   with bounded observation → model → program → feedback cycles. The intended
   research protocol is 30 minutes, as specified in [research framing](RESEARCH_FRAMING.md);
   pilot results must retain their shorter protocol label. Equal wall-clock
   budgets include inference and replanning. Freeze
   per-call and total token/request/action limits before execution.
3. **Separate viewing time from benchmark time.** Start replays near the first
   input when verified timestamps exist, with a clearly labeled full recording
   option. Show planning time and first-action latency. A seek never changes
   the trial's duration or score. A valid no-op cannot have an invented action cue.
4. **Keep interpretable scores.** Hunting starts with signed persisted net XP,
   survival at logout and declared wall duration. Add cumulative XP across level
   transitions and a timestamped native XP ledger before fixed-cutoff or peak-rate
   claims. Report peak sustained rate alongside net XP, not as a replacement for
   penalties. Objective tasks use verified completion and time to completion.
5. **Compare within fixtures.** Every model gets the same class build, supplies,
   prompt, tools, knowledge and budget for a given task. Start with per-fixture
   scores; do not average raw Hero and mage XP into a winner. The research
   aggregate uses equal-weight ln(1 + normalized peak XP/min) across a frozen
   suite after authoritative windows and declared multipliers are verified.
   It does not use a reference bot denominator.
6. **Publish the full declared cohort's outcomes.** Valid zero, negative, death
   and model-generated no-op outcomes count. Infrastructure-invalid and missing
   evidence remain distinct and appear in denominators. Failed evidence is not
   zero gameplay performance. Replacement attempts, if a frozen policy permits
   them, retain new IDs and the original failure record.

Identical database hashes do not prove identical live monster positions or RNG.
Readiness must establish a useful, reachable task scene. Record variation and
balance order; use paired seeds only after proving what the seed controls.
The reported monster that did not disappear remains an unresolved observation.
Kills must stay unknown until authoritative entity identities and death/despawn
events can be compared with the corresponding video timestamp.

## Burn-down

Already verified foundations:

- [x] Real client inputs visibly produce movement and combat.
- [x] A bounded actual model program runs through the isolated SDK.
- [x] Baseline restore and ordinary persistence produce independently checked signed XP.
- [x] A successful run has attributable, saved and inspected gameplay evidence.
- [x] A public Vercel page serves the verified Astra recording.

There are **20 remaining release deliverables** below, with four of 24 accepted.
These are acceptance
counts, not equal effort units or a percentage-complete estimate. Some supporting
code already exists. Track code-ready, live-accepted and published separately;
close each box only at the gate specified here.

### M1 — An isolated cloud experiment worker: 4/4

This milestone is implemented in parallel with M2. Infrastructure code, deployment
plans and deployment receipts belong in the private `agent-devops` repository;
MapleBench owns the benchmark runtime and evidence contract.

- [x] **M1.1 Review the reproducible infrastructure plan.** Isolated OpenTofu state,
  one dedicated-CPU DigitalOcean pilot, private control endpoints, a dedicated
  SSH key and a finite resource/billing plan. Record the change in a deployment PR.
  Accepted: [agent-devops PR #10](https://github.com/dmarzzz/agent-devops/pull/10),
  isolated six-resource plan, one 12-hour dedicated-CPU pilot and external
  receipt-bound destruction controller. Provisioning does not establish runtime readiness.
- [x] **M1.2 Deploy and configure the pilot.** Apply the reviewed isolated plan and
  configure the machine through Ansible. Import only the pinned private runtime
  artifacts required for its own world/database/browser; no shared live world.
  Accepted September 8: Ansible completed, all 24,296 imported files matched the
  pinned manifest, and an independent native world and sandboxed Chrome started.
  Deployment and sanitizer repairs are tracked in agent-devops PR #10.
- [x] **M1.3 Accept cloud rendering and evidence.** Prove fresh post-render frames,
  ordinary physical controls and saved gameplay on the cloud worker. Profile CPU,
  memory and frame timing; verify ordinary persistence before model comparisons.
  Accepted September 8: native controls and ordinary persistence passed before
  evaluation. Two subsequent five-minute API trials independently verified saved
  XP, action receipts, post-render recordings and normal cleanup. The software
  renderer's measured frame-rate limitation remains declared.
- [x] **M1.4 Hand off a bounded worker ready for trials.** Verify preflight, cleanup,
  artifact upload and explicit expiration/destruction handling. Record the actual
  deployment in agent-devops and provide a reproducible worker configuration.
  No fleet expansion occurs merely because the single-worker pilot is ready.
  Accepted September 8: the fresh protected release passed preflight and the full
  backend timeout check; Astra and Sol completed through the finite coordinator.
  Their private evidence and baselines were independently backed up. Both public
  recordings passed byte/range verification, and Sol's replay played in desktop
  and mobile browser views. The fixed expiration and external receipt-bound
  deletion controller remain unchanged; actual deletion has not happened yet.

Gate: one independent cloud worker can execute the accepted full-client protocol
and retain valid evidence without relying on the viewing laptop's renderer.
Its infrastructure and deployment status are inspectable in agent-devops.

### M2 — A shareable four-model showcase: 0/4

- [ ] **M2.1 Deploy the focused session fix.** A fresh protected release passes
  its focused regressions and live checks; stale game entry cannot reopen the
  owned waiting session. Actual controls, frames and current model label verify.
- [ ] **M2.2 Complete one new four-entry plan.** Astra, Sol, Terra and Luna each
  receive the frozen fixture and budgets. All four outcomes have complete
  evidence, and normal services are restored. Valid poor outcomes count; a
  runtime-invalid attempt cannot be silently replaced by a better clip.
- [ ] **M2.3 Verify all four replays.** Model, score, action timing, full recording
  and sampled visible gameplay agree. Label zero-action or incomplete evidence
  accurately; recording delivery itself is verified.
- [ ] **M2.4 Publish the clean cohort.** Put its four recordings on Vercel and
  remove the older test recordings from the current site's manifest/deployment.
  Keep old evidence privately. Show the new cohort's attempt accounting and
  stable links; anonymous playback and byte ranges work.

Gate: a reader can open one link, understand each of four actual outcomes, and
watch the matching run. It is labeled a preliminary showcase, with no ranking.

### M3 — Repeatable operation and visible progress: 0/4

- [ ] **M3.1 Prove repeated group completion.** Three consecutive four-model
  groups on one frozen release finish and restore normally without ad hoc
  repair between models. M2 may count as the first; valid zeros are acceptable.
- [ ] **M3.2 Prove failure containment.** A separately declared interruption
  demonstrates cleanup, honest unknown/failed evidence and safe handling of only
  future unsubmitted entries. No uncertain API request is replayed. Deploy the
  existing composed lifecycle only after its needed recovery cases pass.
- [ ] **M3.3 Publish after each completed run.** One idempotent, bounded pipeline
  projects checked evidence, uploads the clip and updates Vercel. Normal publication
  completes within 60 seconds of validated artifacts being ready; failures show
  a publishing state and a resumable publication job, without another model run.
- [ ] **M3.4 Expose operational state.** The site distinguishes queued, preparing,
  model planning, acting, saving, publishing, complete, invalid and stale. Measure
  phase durations and failed-attempt rate. A stale browser or expired service is
  detected; waiting is never presented as active gameplay.

Gate: a finite batch produces public results without a person shepherding every
transition. This short acceptance does not establish an availability SLA.

### M4 — Meaningful sustained agent evaluation: 0/4

- [ ] **M4.1 Freeze the adaptive full-client protocol.** Validate bounded replanning
  at five minutes before the intended 30-minute research task. Publish its exact start/deadline,
  inference/time/token budgets and executed-program trace. Confirm the model can
  respond to a changed situation, beyond one initial generated program.
- [ ] **M4.2 Make longer scores authoritative.** Validate native cumulative XP,
  level transitions and the horizon cutoff. Reconcile the timestamped native
  ledger with ordinary saved state. Exclude post-deadline gains by the frozen
  rule. Keep unsupported kills/deaths/resources unknown.
- [ ] **M4.3 Freeze the agent-facing contract.** Version SDK documentation and
  a small reference pack for the actual allowed controls/skills. Give every model
  the same information and execution semantics. Record exact model, effort,
  harness, prompt and knowledge identities; never repair generated code silently.
- [ ] **M4.4 Complete the first repeated pilot.** Four models × four repetitions
  on the accepted longer Hero task: 16 predeclared attempts with exact order
  balance. Report raw outcomes, spread, latency, usage and eligible fractions.
  Set the next sample size from observed variance and a declared precision
  target. This pilot alone does not establish a reliable ranking.

Gate: the task measures sustained adaptation, all planned attempts are accounted
for, and the measurements support an honest per-fixture comparison.

### M5 — Representative class and task coverage: 0/4

- [ ] **M5.1 Accept a ranged fixture.** Candidate: Bowmaster. Prove native ranged
  hits, positioning and resource/ammunition behavior from a frozen baseline.
- [ ] **M5.2 Accept a magic fixture.** Candidate: Ice/Lightning Arch Mage. Prove
  area effects, affected entities and mana use from a frozen baseline.
- [ ] **M5.3 Accept two task families across the three classes.** Sustained
  hunting and navigation/objective completion produce six initial fixtures.
  Calibrate difficulty and starting scenes with separately labeled human or
  scripted checks; avoid trivially solved or unreachable tasks.
- [ ] **M5.4 Freeze the v1 suite and sampling plan.** Define all fixture versions,
  model configurations, order, exclusions, budgets and reporting rules before
  collection. A four-repetition pilot across six fixtures and four models is
  96 trials; same-version M4 trials can count only when predeclared. This is a
  planning scale, not authorization for an unbounded batch or guaranteed precision.

If pilot outcomes are used to tune the task, prompt, tools or difficulty, freeze
a new version and collect fresh evaluation data. Such development runs cannot
be reused as untouched evaluation samples.

Gate: each column tests a distinct validated capability, and models are compared
within identical fixtures. Expand sample counts only through a declared plan.

### M6 — A credible public benchmark release: 0/4

- [ ] **M6.1 Collect and independently verify the declared suite.** Preserve
  valid poor results and all attempted-set denominators; investigate systematic
  evidence failures before drawing comparisons. Add justified uncertainty
  estimates instead of implying that one run determines a winner.
- [ ] **M6.2 Publish the research results UI.** Model × class/task matrix, per-cell
  sample count and spread, raw metrics, failure rates, runtime/usage and linked
  replays. Add score curves only when backed by the new native ledger.
- [ ] **M6.3 Publish reproducibility and methodology.** A versioned release,
  safe machine-readable results, documented protocol/scoring, fixture/build
  fingerprints, limitations and changelog let another configured operator
  reproduce a bounded group. Distribute no credentials or proprietary assets.
- [ ] **M6.4 Validate release operations.** From documented configuration, a second
  operator/session executes a finite group and publishes it without code edits.
  Verify monitoring, publication retry without gameplay replay, archival policy
  and site rollback. Confirm public playback and usable desktop/mobile views.

Gate: another person can understand, inspect and repeat the experiment. That is
the initial RuneBench-quality release target; a combined leaderboard score is
optional until normalization is defensible.

## Execution discipline and sequencing

The immediate dependency chain is **(M1 in parallel with M2) → M3 → M4 → M5 → M6**. Small independent
work, such as UI design or class reference preparation, can proceed in parallel.
Shared-host tests and gameplay remain serialized. Existing passing tests are
reused; new focused tests address actual changes or observed failures.

Do not start new framework work unless it clears the next acceptance gate.
Finish a working slice, deploy that exact slice, exercise it, then publish its
evidence. Code-ready is not live-accepted; local-gallery-ready is not public.
The operator roadmap should stop accumulating one-off release procedures once
the required group/lifecycle path is accepted.

The current user-directed M2 pilot uses four five-minute adaptive trials: at
most 12 API requests and 120,000 aggregate tokens per trial, or 48 requests and
480,000 tokens across the group. Model latency counts against each wall budget.
These are ceilings, not predicted usage. Further repetitions and class groups
require separate finite plans; they do not inherit an unlimited queue. Record actual cost and useful gameplay
per wall hour. Extra credits do not resolve browser or collection defects.

There is no defensible calendar completion date yet. Establish actual batch
throughput and interruption rate at M3, then estimate M4–M6 from measured
throughput and the declared experiment sizes. A four-model showcase is the next
delivery; the full benchmark is several independently verifiable releases away.

Defer party quests, support-class ranking, additional class families, cross-provider
expansion and training/RL integrations until this core suite works. Bishop and
party coordination need shared objective metrics rather than personal XP. Keep
the current four-model scope explicit: it does not establish cross-provider
performance. Preserve the [class/task design](CLASS_BENCHMARK_DESIGN.md) and
[party-quest proposal](MULTIAGENT_KPQ.md) as subsequent expansion plans.
