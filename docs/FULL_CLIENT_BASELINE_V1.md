# Permanent ordinary-replanning baseline v1

`full-client-adaptive-baseline-v1` is a new optional `baseline_policy` in the
existing adaptive envelope. It is the simple observe/act/replan condition from
[the experiment design](BASELINE_EXPERIMENT_DESIGN.md), not a skill showcase,
reflection agent, candidate search or a completed scientific comparison.

The standard horizon is **300 wall seconds**, including inference. This uses
the supported encoded five-minute runner. A 120-second debug run is not silently
accepted; the independent 1800-second research contract remains unchanged.
Short debugging and the eventual thirty-minute evaluation need their own labels.

## Frozen behavior

Prepare a policy with an explicitly supplied canonical toolkit:

```python
from full_client_baseline import protocol
from full_client_adaptive import prompt

adaptive_protocol = protocol(explicitly_selected_toolkit)
instructions = prompt(adaptive_protocol)
```

There is no default class, fixture or live-qualified roster. The constructor
validates the supplied toolkit and exact profile; it does not certify native
mechanics. Current toolkit declarations remain provisional until the separate
native effect/resource gates pass.

The objective is signed native net XP over the five-minute run while staying
alive. Client XP is diagnostic. This does not redefine the eventual thirty-minute
best-complete-15-second-window research metric, reconstruct peaks from endpoints,
or replace any native scoring/publication gate. No score or ranking is created by
this module. Successful key delivery is explicitly distinguished from an effect.

The preset has 20-second programs, at most 12 model requests, low reasoning
effort, 3000 output tokens per response, 240000 aggregate reserved/actual tokens,
1600 attempted actions and 6000 SDK requests. The existing full-horizon reserve
requires 75 seconds before another request: 50 inference + 20 execution + 5
settlement. When that reserve closes, the original controller observes passively
until the deadline. That visible idle interval is part of this permanent baseline,
not an automatic combat helper. Final-slot and long-horizon policies cannot be
substituted while keeping this identity.

Every request gets fresh state and at most two recent programs, their execution
outcomes and the last five SDK receipts per program. No separate critique pass,
candidate population, evaluator or cross-run memory is added. The existing runner
executes returned code unchanged and preserves its cancellation, uncertainty and
no-replay rules. The new prompt lists exact named controls, including expanded
slots, without exposing physical-letter aliases as SDK actions.

## Identity and admission

Freeze the complete adaptive object, prompt SHA, scenario/SQL/fixture fingerprints,
source dependencies, model settings and runtime manifest using ordinary admission.
The policy ID alone is not a comparison key. Different class/toolkit/resource/map
or baseline bytes remain different fixtures even if the agent policy is identical.
Do not retrofit the policy onto historical observations, prompts or recordings.
Changing the policy's prompt, history, cadence, controls or objective requires a
new policy version; keep this implementation and its historical results.

The module is consumed by `full_client_adaptive.validate_protocol` and `prompt`,
so normal execution and independent adaptive evidence rechecking use the same
prompt. Runtime web identity conditionally requires this module in the frozen
manifest and rejects a serving process older than its pinned source. Experiment
preparation requires its runner dependency before assigning an attempt ID.
Historical protocols without `baseline_policy` do not acquire this dependency.
This source change does not stage a worker or admit a trial.

Before live evaluation, qualify productive ordinary combat/XP/save/restore and a
no-input control on the same fixture, then freeze failure rules and repetitions.
The exact v1 preset omits the optional progression policy: a level change is
currently rejected at the next adaptive cycle. Do not silently add progression;
resolve that qualification constraint before admission or use a separately
versioned preset. Full skill fidelity and the actual class roster remain pending.

### Level progression: existing semantics and a proposed successor

The first adaptive observation must equal the frozen profile's initial level.
Without `progression_policy`, later request-boundary observations must still
equal it. A level-up during a program can therefore finish that program but stops
before the next model request with `adaptive_profile_level_mismatch`. A level-up
late in the final program or passive tail is not a loophole: ordinary adaptive
evidence checking requires the fixed level, and legacy persisted-XP scoring
rejects unequal initial/final levels.

The existing exact `NATIVE_PROGRESSION_POLICY` supports native progression from
the initial profile level through 200. Its independent verifier requires the
hash-bound native XP ledger and experience table, reconciles observed levels
against transaction times, and binds the ordinary saved final state. The runtime
requires both its explicit XP-window configuration and a validated scenario
contract. Experiment admission permits progression only under the schema-three
`full-client-xp-windows-v1` trial identity. Merely allowing level 181 in client
telemetry cannot qualify a score.

Recommended next version, **not implemented or admitted here**:
`full-client-adaptive-baseline-v2`, with the same 300-second/20-second/full-horizon
cadence and exact `NATIVE_PROGRESSION_POLICY` made mandatory. Freeze its changed
prompt and native-window scenario; require the instrumented JAR, experience
table/normalization pins, transaction coverage, ordinary save and native runtime
acceptance before use. Its signed cumulative native XP objective can use the
ledger across level transitions; do not subtract wrapped per-level XP values or
silently replace the objective with the peak-window metric. Preserve v1 as the
fixed-level historical condition. This recommendation does not alter either
version, extend the horizon, assign skill/stat points or reset resources.

The tests use stubbed providers and a simulated clock. They check real adaptive
request construction, normal bounded feedback, unchanged code, 300-second
coverage, independent evidence rechecking, uncertainty/no replay, empty memory on
a fresh run, version/budget tampering and unchanged historical prompt hashes.
They are source validation, not evidence that this baseline earns XP in a game.
