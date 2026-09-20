# Where agent performance is actually bounded

Read of the published snapshot, the frozen scenarios and the runtime code as of
September 20, 2026. This is an audit of existing artifacts, not a new
experiment. Nothing here measures model capability; it measures how much room
the current harness gives a model to express it.

The prompting question was why recorded agents hunt along a line instead of
clearing a group, moving on, and clearing the next. The short answer is that
three of the published fixtures forbid vertical movement and the agent gets
about twenty seconds of gameplay per attempt. Neither is a model result.

## 1. The published fixtures are one-dimensional

All three Hero cave scenarios declare a single y value:

```json
"coordinate_bounds": { "min_x": -430, "max_x": 1900, "min_y": 260, "max_y": 260 }
```

`scenarios/hero-cave.json`, `hero-cave-staged.json` and `hero-timeless-cave.json`
are therefore lines, not maps. `crusader-c1.json` states the same intent in
prose: *"hunt across the floor and wait for normal respawns instead of climbing
decorative platforms."*

The remaining scenarios — `hero-c1`, `warrior-beach`, `henesys-warrior`,
`henesys-crusader` — declare no bounds, so vertical movement is possible there.
Recorded rope use comes from those.

Consequence: navigation, target selection across platforms and route planning
are **not currently under test**. An agent that never moves vertically on a
one-dimensional fixture is complying with the fixture.

## 2. Gameplay is roughly nine percent of an attempt

The featured Astra run, `4149dc7596194dc49067a9ed3af9e3d7`:

| Phase | ms | Note |
| --- | ---: | --- |
| `attempt_elapsed_ms` | 237,774 | the whole attempt |
| `session_ms` | 36,978 | login through logout |
| `api_ms` | 12,320 | model latency |
| `controller_ms` | **20,838** | program executing |
| `settlement_ms` | 1,788 | persistence settle |

About **201 seconds sit outside the game session entirely** — world reset,
baseline restore, client boot, evidence collection. Program execution is
**8.8 percent** of the attempt.

Every scored attempt in the snapshot lands in the same band:

| Attempt | Model | API | Program | Acks | Saved XP |
| --- | --- | ---: | ---: | ---: | ---: |
| `4149dc75` | GPT-6 Astra | 12.3s | 20.8s | 34 | +9,250 |
| `a154c7a1` | GPT-6 Astra | 13.1s | 20.2s | 25 | +9,000 |
| `aad11d7a` | GPT-6 Astra | 10.9s | 20.6s | 29 | +9,500 |
| `332112a3` | GPT-5.6 Terra | 19.9s | 22.3s | 34 | +4,500 |
| `feb1b38a` | GPT-6 Astra | 11.3s | 21.0s | 27 | 0 |
| `a88b83dc` | GPT-5.6 Luna | 9.6s | **0.9s** | 0 | 0 |
| `219403ef` | GPT-5.6 Sol | 19.9s | **0.9s** | 0 | 0 |

The two 0.9s programs are the known declared-but-never-invoked failures. They
are evidence about program validity, not about play.

This is the dominant constraint. At a 10:1 ratio of setup to play, throughput
and credit ceiling are both governed by the 201 seconds, and no improvement in
agent reasoning can move a twenty-second score very far.

## 3. Every published attempt is a single API call

`charged_usage.api_requests` is `1` for all nine dispatched attempts. The model
writes one program **before seeing any observation**, and that program is the
entire run. Reactivity exists only inside a loop authored blind.

`control_mode: "continuous"` is implemented and exercised by two configs —
`hero-cave-continuous-openai-3m.json` and `hero-timeless-openai-3m.json`, both
at `program_seconds: 60`. Nothing published uses it. Continuous mode raises the
per-program SDK budget from 100 to 600 requests and begins replanning while the
current program still runs.

This matches the roadmap's own open item M4.1 and the
[research framing](RESEARCH_FRAMING.md)'s statement that one-response programs
do not establish the intended 30-minute adaptive protocol.

## 4. Reasoning effort is frozen at `low`

`{"effort": "low"}` is pinned in the scenario and verified at
`scripts/full_client_runtime.py:324` and `:785`, and enforced again at
publication (`scripts/full_client_publish.py:511`). This is deliberate freezing,
not a stray default — and the publication validator already accepts `low`
through `ultra`.

Raising it is therefore a **scenario version change**, not a code change, and
under the roadmap's own rule it requires fresh evaluation data rather than
reuse of existing trials. Worth doing deliberately: effort is currently a silent
term in every cross-model comparison.

## 5. The observation contract has no terrain

The prompt instructs the model to *"Follow actual footholds."* The observation
never says what they are.

`Observation` in `src/protocol.ts` carries `character`, `monsters`, `drops`,
`inventory`, `skills`, `portals` and `monsterSimulation`. The only terrain
reference in the entire protocol is `Position.foothold?: number` — an opaque
identifier with no geometry attached. There is no foothold list, no platform
extents, no rope or ladder positions, no connectivity.

So an agent can see a monster's coordinates above it and has no representation
of how to reach it. On a one-dimensional fixture this costs nothing. On any
multi-level map, route planning is not merely untested — it is **inexpressible**
through the frozen SDK, and would have to be rediscovered by trial and error
inside each program lease.

This is the blocking dependency for the M5 ranged, magic and navigation
fixtures. Those columns cannot test navigation while navigation has no
representation.

## 6. The SDK request budget binds at longer horizons

100 requests per program in serial mode, 600 in continuous. `observe()` and
`wait()` both count. A reactive engagement loop — observe, decide, act, wait —
costs about four requests, so 100 requests is roughly 25 decisions. That is not
binding across 20 seconds. Across a five- or thirty-minute lease it is, and the
budget should be derived from the intended decision rate rather than inherited.

## Suggested sequence

1. **Publish a continuous-mode group.** Both the mode and the configs already
   exist. This is the cheapest change that converts one blind program into a
   replanning loop, and it directly serves M4.1.
2. **Amortize the 201 seconds.** Either raise the lease substantially or reuse a
   prepared world across trials. Until this moves, every other improvement is
   competing for a twenty-second window.
3. **Add foothold geometry to `Observation`** before building any vertical
   fixture. Ordering matters: shipping a navigation column against a blind SDK
   would produce a column of zeros that looks like a model result.
4. **Decide reasoning effort explicitly** and freeze a new scenario version, so
   it stops being an undeclared constant in model comparisons.

## What this does not establish

These are constraints on measurement, not findings about models. Nothing here
shows any model would play better with more time, more cycles, higher effort or
terrain data; it shows those hypotheses are currently untestable. The
Bowmaster and Ice/Lightning columns of the twelve-cell pilot are zero for all
four models, which is more consistent with a fixture or harness defect than
with four independent model failures, but that remains uninvestigated and is
not explained by anything above.
