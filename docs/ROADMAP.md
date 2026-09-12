# MapleBench roadmap and release burn-down

Decision snapshot: September 12, 2026. Implementation, live qualification and
publication are separate gates. A checked source test is not a gameplay result.

## Goal

Build a reproducible benchmark of strategy discovery through the real client:
matched starting fixtures, useful class toolkits, a fixed wall-clock budget,
authoritative XP measurements, inspectable model programs and matching videos.
The evaluated system is model + harness + tools + knowledge + budgets.
See [research framing](RESEARCH_FRAMING.md) for the central question and limits.

The intended research task is 30 minutes, including inference. Its primary score
is the best normalized XP/min in a complete fixed 15-second native window.
Preserve signed net XP separately. Compare within a declared class/task/fixture;
collect repetitions and uncertainty before presenting a model ranking.

## Current evidence

The public site contains 12 completed five-minute, four-skill pilots across Hero,
Bowmaster and Ice/Lightning Arch Mage. Each class has Astra, Sol, Terra and Luna.
Hero saved XP is 18,250 / 18,250 / 18,250 / 23,000 respectively. All eight Bow/Mage
runs saved zero XP. Those are observations of limited fixtures, not proof of
canonical class behavior or a stable model ordering.

Night Lord's first API attempt failed an input-receipt deadline and was excluded.
The original group was permanently closed. Its four entries must never be reused.
A transport correction passed focused tests; complete fresh native qualification
has not been preserved and reviewed. All temporary cloud workers were deleted.

**The old 16-entry matrix is no longer a release objective.** Finish the benchmark
improvements first, use bounded development runs to validate them, then declare
fresh comparison runs. Historical results keep their original protocol and scores.

## Parallel implementation tracks

| Track | Scope | Acceptance evidence |
| --- | --- | --- |
| Class mechanics | Broader Hero, Bowmaster, Ice/Lightning and Night Lord skills; descriptions, ordinary keymaps, realistic finite resources; repair native routes | Exact definition parity, actual casts/movement/target effects, saved resource changes, reviewed recordings |
| Sustained interaction | Prompted model replanning, final execution slot, original deadline, explicit longer horizon | Controller + actual sandbox/capture acceptances; no hidden policy, no replay after uncertainty |
| Authoritative scoring | Native XP ledger, level transitions/death/cutoff, complete windows, normalization, strict publication | Production server instrumentation plus native gain/level/death/zero checks, ordinary save reconciliation, tamper refusal |
| Public evidence | Skill inputs, timing breakdown, XP curve, readable matrix, per-completion publication | Browser QA and anonymous media checks; unavailable evidence stays unknown |
| Operations | Repeatable isolated worker, pinned source/assets, independent expiry, backup and failure recovery | Finite deployment plan and receipts in agent-devops; interruption recovery and fresh-session reproduction |

Source changes are integrated on `codex/benchmark-v2`. The deployable version must
be frozen only after the tracks pass their combined checks. No new evaluated
comparison cohort should mix intermediate commits or development fixtures.

## Release burn-down

Verified foundations:

- [x] Actual model-authored programs control the rendered client.
- [x] Requested and returned model identity, inputs and recording bytes are checked.
- [x] Ordinary logout produces independently verified signed saved XP.
- [x] Twelve pilot results and recordings are publicly available.
- [x] Finite cloud workers can be provisioned and externally deleted.
- [x] Old uncertain attempts are closed without replaying model requests.

Source and presentation delivered for the next release:

- [x] Integrate the expanded skill policy through prompt, SDK, bridge, keymap,
  native client, fixture transform, receipt verifier and public projection:
  ten mapped skills each for Hero, Bowmaster and Ice/Lightning, eight for Night Lord.
- [x] Add offline asset-definition parity and fixture preparation, plus separate
  native gates for every skill and finite inventory save/restoration receipts.
- [x] Integrate urgent acknowledgements, final-slot scheduling and explicit
  30-minute controller, recorder, adapter and publication contracts.
- [x] Implement native XP ledger/window projection, signed save reconciliation,
  class/toolkit qualification and matching recording review before publication.
- [x] Deploy the dashboard presentation update to the root and cohort pages,
  preserving all 12 historical scores and recording bytes. Skill inputs and
  timing diagnostics are displayed when recorded; native curves require new
  accepted native-window results and are absent from the historical pilots.
- [x] Prepare create-once fresh worker services, initial database import,
  gate/lock/queue enrollment and a finite externally deleted worker plan in
  agent-devops. These helpers have source tests; no replacement worker is active.

Live acceptance still required before fresh model comparisons:

- [ ] Verify each selected skill against pinned game definitions and the actual
  runtime asset version. Explicitly identify unsupported skills and mechanics.
- [ ] Demonstrate all four classes' new inputs and server effects with labeled
  native development runs, including ammunition, MP, buffs and movement.
- [ ] Diagnose damage and kills in Bow/Mage fixtures; prove native defeat/XP.
  Acknowledged input or predicted damage numbers alone do not satisfy this gate.
- [ ] Verify urgent acknowledgements and final-slot scheduling in the actual
  client, including cancellation and uncertain input/model responses.
- [ ] Build the actual instrumented server and verify gain, level-up, death loss,
  idle coverage, ordinary save and strict timestamp cutoff from native evidence.
- [ ] Deliver accepted native-window scores to a public cohort with matching video.
- [ ] Publish the newly collected skill-use, timing and native XP-window evidence
  through the deployed dashboard. Presentation-only changes do not satisfy this.
- [ ] Qualify the explicitly versioned 30-minute controller/recorder/adapter and
  its memory, upload, lifecycle, publication and cleanup limits.
- [ ] Measure long recording sizes and provide adequate publication capacity.
  Individual long captures allow 600 MiB, but the current static site payload
  remains capped at 512 MiB; large multi-class cohorts need additional storage
  or a separately qualified encoding policy before they can be published.
- [ ] Run a bounded actual API integration check on the new frozen setup. Review
  attribution, skill actions, ledger, timing, video and ordinary restoration.
- [ ] Validate interruption containment and publication retry without gameplay
  replay; backup all evidence before external worker deletion.
- [ ] Publish source/reproducibility notes and agent-devops deployment receipts.

After the new version is accepted:

- [ ] Freeze new hunting fixtures for all four classes and task-specific limits.
- [ ] Declare a fresh four-model-by-four-class plan with new IDs and equal inputs.
- [ ] Publish every planned outcome, including valid zero/negative/no-op/death and
  distinct infrastructure-invalid outcomes, with each successful recording.
- [ ] Add and validate navigation/objective fixtures where the client supports
  them; do not infer these capabilities from hunting scores.
- [ ] Predeclare balanced order, repetitions, exclusions and precision goals.
  Run repeated comparisons and publish sample counts, spread and uncertainty.
- [ ] Freeze the suite before computing the equal-weight mean of
  `ln(1 + normalized peak XP/min)`. Missing evidence is not a zero score.
- [ ] A second operator/session reproduces a finite group and publication from
  documented configuration without editing code.

## Development run contract

Development checks are not evaluation samples. First verify source and native
mechanics without model calls. Then use a finite, predeclared API check with an
exact model, wall/request/token/action limits and fresh IDs. Stop and diagnose
uncertain inputs/API calls rather than replaying them. Backup evidence and
complete ordinary cleanup even after failure.

A changed skill toolkit, resource supply, prompt, scheduler, scorer or native
binary creates a new frozen setting. No older result is upgraded to that setting.
The site may receive presentation changes while its scores and recording bytes
remain unchanged.

## Scientific and implementation limits

The reconstructed client is not established as an exact official client.
Bowmaster Hurricane currently uses discrete attacks; continuous channeling is a
separate mechanic requiring proof. Synthetic starting HP/MP and limited skill
bindings constrain the historical pilots. New resource choices must be declared
and frozen, not called canonical merely because they suit a class.

A saved baseline does not fix live spawn positions or combat RNG. Native entity
identity/death events are needed to resolve the reported monster that remained
visible; this observation is still unresolved. A brief peak rate does not prove
sustained efficiency. Class differences and single samples do not support an
overall model winner.

RuneBench informs the SDK/task-matrix/replay experience and strategy-discovery
question. MapleBench's fixed complete windows, signed losses and class mechanics
remain an explicit independent protocol; see the pinned source discussion in
[class benchmark design](CLASS_BENCHMARK_DESIGN.md#runebench-reference).
