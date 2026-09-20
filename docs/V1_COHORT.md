# v1 cohort: a repeated cross-provider Hero pilot

Status: **release requirements, revised 2026-09-20**. Implementation and native
core-ten qualification are complete; the scored cohort has not started.
See V1_STATUS.md for evidence and handoff state. This document is not a result receipt.
It supersedes the earlier four-OpenAI-model, no-knowledge plan.

## Frozen evaluated system

| Element | Release requirement |
| --- | --- |
| Fixture | Hero level 180, map `240040511`, two-handed sword |
| Protocol | `full-client-adaptive-pilot-v1`, 300-second controller wall budget |
| Capture | Full-horizon reserve and `post-render-encoded-frame-v1` |
| Models | `gpt-6-astra`, `gpt-5.6-sol`, `claude-opus-5`, `claude-sonnet-5` |
| Repetitions | Four per model: 16 predeclared attempts |
| Model budget | At most 12 requests, 3,000 output tokens per request, 500,000 total tokens per attempt |
| Program budget | At most 20 seconds per generated program; all inference and program time share the 300-second clock |
| Order | ABCD, BCDA, CDAB, DABC; each model occupies each position once |
| Score | Signed persisted session net XP, persistence schema 2 |
| Knowledge | Frozen `hero-180-map-240040511-v1` pack in every model's prompt |
| Controls | Frozen `full-client-hero-toolkit-v1`, 17 available invocable skills; core ten independently effect-qualified |
| Observation | Structured client state; models generate JavaScript using the narrow SDK |
| Replay | Original client video, held-key HUD, model-call timeline and timed input receipts |

Each model receives the same gameplay instructions, knowledge bytes, observation schema,
action limits and wall budget. Native provider APIs have different envelopes and
reasoning controls; record those exact settings. This evaluates the declared
model-plus-scaffold configurations, not isolated model intelligence. It is not a
vision-only benchmark. Model-list authentication establishes availability, not
successful generation or gameplay.

Token admission uses the existing conservative byte-based reservation policy,
without recycling unused reservations; actual provider usage is capped separately.
The larger declared envelope accommodates the full knowledge prompt across
adaptive cycles. It is a ceiling, not a target spend. If a budget closes early,
the remaining wall interval is observation-only and is visible in the evidence.

The knowledge pack is a declared versioned axis. Its manifest, content, combined
prompt and runtime files are hash-bound. Historical no-knowledge runs remain
separate. The level-150 `hero-cave` pack is not applicable to this fixture.

## Skill breadth and qualification

The 17 input slots expose Brandish, Combo Attack, Sword Booster, Maple Warrior,
Rush, Sword Coma, Sword Panic, Power Stance, Rage, Power Guard, Enrage, Hero's
Will, Shout, Armor Crash, Iron Body, Power Strike and Slash Blast. Eight declared
passives are learned at frozen, skill-point-compatible levels. The character
uses a two-handed sword: axe and shield skills have no compatible equipment
effect in this fixture; the one learned Axe Mastery point is explicitly inert.
Monster Magnet lacks the physical client's target-selection route.
Beginner skills are not allocated in this fixture. Exact levels and exclusions
are part of the published knowledge/toolkit declaration.

Native release qualification verifies all 17 bindings and all 25 learned rows,
then exercises a separately identified core ten: Brandish, Combo Attack, Sword
Booster, Maple Warrior, Rush, Sword Coma, Sword Panic, Power Stance, Rage and
Power Guard. It requires native cast/effect/resource evidence and combo
prerequisites, followed by ordinary logout and exact baseline restoration.
A key acknowledgment alone is not a successful effect check. The seven added
controls remain available to agents, but their effects are not qualified by
this core run. Conditional mechanics, skill balance and passive-effect ratios
are not certified. This distinction must remain visible with the results.

The 852-entry cross-class suite is a broader research inventory. v1 establishes
this declared two-handed-sword Hero fixture, not coverage of every class or
all situational mechanics. The core qualification receipt is separately
hash-bound to the scored fixture's baseline and runtime, including exact
client/server binaries. Instrumentation is enabled for qualification only.
No model receives a hidden autonomous combat policy.

## Freeze and runtime acceptance

Build the knowledge-enabled candidate only after the native fixture is ready:

```sh
python3 scripts/full_client_scenario_freeze.py hash \
  --knowledge-pack hero-180-map-240040511-v1
python3 scripts/full_client_scenario_freeze.py build \
  --id hero-180-v1-cross-provider-knowledge-v1 --expected-map-id 240040511 \
  --knowledge-pack hero-180-map-240040511-v1 \
  --output <private>/scenario-hero-180-v1.json
python3 scripts/full_client_scenario_freeze.py check <private>/scenario-hero-180-v1.json
```

Recompute hashes rather than copying a historical prompt hash. Re-pin all seven
inputs: runtime inventory; backend scenario reference; plan fixture and budgets;
runner dependencies; adapter fingerprint; serving process started after the frozen
sources; and fresh experiment/attempt identities. Knowledge files, provider
adapters, expanded controls and the recording HUD are part of the new freeze.

Use one native amd64 worker with pinned Chrome, matching client/server binaries,
and the existing guarded database reset. Establish fresh scene readiness, native
skill qualification, recorded/decoded frames, ordinary logout, authoritative
persistence and exact restoration before scored attempts. Check XP headroom:
level transitions are not silently scored by the current net-XP adapter.

Historical packages require their historical verifier/source revision. Current
verification regenerates expected protocol inputs; an old package is not
necessarily accepted by today's verifier merely because its hashes are intact.

## Reporting and operational gate

Publish every planned attempt and its disposition. Per attempt report signed
net XP, alive at logout, controller/API/session clocks, cycle and token counts,
receipt status and available recording. Session net XP includes the bounded
logout tail; it is not an exact-at-300-seconds XP snapshot.

Per model show all eligible samples, n/planned n, mean, median, minimum, maximum,
sample standard deviation and eligible fraction. Four observations support only
a small descriptive pilot; no confidence interval or ranking claim is made.
Valid zero, negative, death, no-op and model-program-error outcomes remain in the
sample set when their native evidence is valid. Do not retry or exclude them
because the score looks poor. Missing evidence and infrastructure failures retain
null scores and remain in attempted/planned denominators.

Report attempted, verified-score and verified-recording counts per four-attempt
group, with failure causes. Release operations require three consecutive clean
groups without ad hoc repair between models. A repair changes the candidate and
requires a new declared freeze/cohort; retain the interrupted cohort separately.
This gate is observed operational evidence, not an SLA or a guarantee of future
reliability. The full 16-attempt denominator remains visible.

## Replay semantics

The video burns in the actual held browser keys at rendered frames. The public
JSON timeline aligns model request intervals and input request-to-acknowledgment
intervals to the recording's media clock, including the first encoded-frame
offset and measured clock uncertainty. Delivery intervals are not exact native
keydown/cast/hit timing. Old clips without timed input receipts show timing as
unavailable. Public exports contain bounded control names/times and hashes, not
raw model responses, programs, credentials or private database rows.

## Limits of this release

No peak XP/min, damage, gross XP, kill count or survival-throughout is inferred
from two persistence snapshots. No general provider superiority or class-wide
ranking follows from one fixture and four repetitions. Game RNG is uncontrolled;
order balance and exact reset do not make runs deterministic. Private trusted
host receipts and hashes establish consistency, not cryptographic proof against
a dishonest runtime. Game assets remain outside the repository.

The release UI follows the illustrated MapleStory-inspired design, with light
content panels and a recorded-input/model-call timeline. Longer horizons, other
classes and broader task suites remain follow-up work.
