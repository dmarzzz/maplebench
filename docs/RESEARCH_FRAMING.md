# MapleBench: core research framing

Status: agreed research direction, recorded September 7, 2026. This document
guides future benchmark design and the eventual README update. It does not
change the implemented scorer, trial protocol, or interpretation of historical
results. Where older documents propose different horizons or scoring objectives,
this is the intended direction for the next protocol.

## Central question

**Given the same starting conditions, tools, and 30-minute wall-clock budget,
which LLM agent discovers and implements a gameplay strategy that achieves the
highest XP rate?**

MapleBench studies practical strategy discovery and optimization in a persistent
MapleStory-like game environment. An agent observes the world, chooses an
approach, implements it through gameplay tools or code, examines the outcome,
and adapts. Learning here means adaptation within a run, not model weight updates.

The design should stay close to RuneBench: reward the best training rate an
agent discovers within a fixed time budget. Time spent exploring, reading
documentation, obtaining equipment, or trying an unsuccessful approach can pay
off if it leads to a more effective strategy before the deadline.

## Questions we want to answer

1. **How effective a training strategy can each agent discover?** Peak XP/min is
   the primary outcome under matched task conditions.
2. **How quickly does it discover improvements?** The progression of its best
   XP rate over elapsed time shows when productive strategies emerge.
3. **How does performance vary across gameplay scenarios?** Class and starting
   conditions expose differences in positioning, navigation, targeting, skill
   use, and resource management.
4. **How reliably can it turn a plan into working gameplay and recover from
   mistakes?** Repeated outcomes, action failures, and recovery behavior help
   explain performance differences.
5. **What resources does that performance require?** Cost, tokens, tool calls,
   and LLM wait time describe the practical expense of the result.

The primary score measures the combined outcome of understanding, planning,
implementation, adaptation, and optimization. It does not independently measure
each ability. Attributing a difference to one component requires additional
controlled experiments, not just inspection of the leaderboard.

## Intended benchmark contract

| Element | Intended design |
| --- | --- |
| Rows | Evaluated agent configurations, with exact model and harness versions |
| Columns | Fixed training scenarios with declared class, level, equipment, inventory, starting location, and world configuration |
| Budget | 30 minutes of wall-clock time per task, including LLM latency, planning, tool execution, and gameplay waits |
| Interaction | The agent can observe, act, and revise its strategy throughout the run; available tools and action rules are fixed for the comparison |
| Task score | Highest normalized XP/min achieved in a complete, fixed 15-second sampling window within the budget |
| Normalization | Remove declared server XP and simulation-speed multipliers; do not divide by a reference bot's performance |
| Overall score | Equal-weight average of `ln(1 + task_score)` across the frozen task suite |
| Cell colors | Relative to the best model result in that column, for display only |

The game continues while the agent waits for an LLM response. Already running
actions may continue to earn XP. Inference speed therefore affects how much
experimentation an agent can perform; the experiment measures performance under
a real-time constraint, not reasoning quality independently of latency.

For an eligible run, a window's XP rate is its authoritative XP change divided
by elapsed minutes, adjusted for declared multipliers. The run score has a zero
floor so `ln(1 + task_score)` is defined. Preserve signed total net XP separately,
including losses. Define XP accounting across level-ups, death penalties, window
alignment, and incomplete or missing samples before implementing the protocol.
Missing evidence is not automatically a zero gameplay score.

The exact scenario roster remains to be selected and frozen. Changing the roster
changes the meaning of the aggregate and requires a new benchmark version.
Different scenarios can have inherently different XP opportunities; the log
transform compresses numerical scale but does not calibrate task difficulty.

## Why there is no reference policy in scoring

The comparison is between evaluated agents under matched conditions. A fixed
scripted policy is not required to answer the central question, and introducing
one would make results depend on its implementation and weaknesses.

A scripted bot may still be useful for environment smoke tests or regression
checks. Such runs should be labeled as internal baseline checks. They do not
provide the denominator for leaderboard scores or define successful gameplay.
An agent's own initial working strategy can also serve as its starting point for
optimization without becoming a benchmark reference policy.

## Supporting evidence and scientific limits

Keep the primary scoring rule simple, and collect supporting measurements where
the runtime can verify them:

- Best XP rate over elapsed time, to show the discovery process.
- Total signed net XP, to distinguish productive runs from brief peaks.
- Deaths, failed actions, and resource use, to describe reliability and recovery.
- Tokens, cost, tool calls, and LLM wait time, to describe resource requirements.
- Repeated runs and uncertainty, to distinguish consistent differences from luck.

Do not fold these diagnostics into the gameplay score. Unsupported metrics stay
unknown. Predeclare repetitions, run ordering, the rule for combining repeated
run scores, and treatment of gameplay versus infrastructure failures. Do not
selectively rerun poor outcomes. A single trial can be shown as a pilot result,
but provides weak evidence for a dependable model ranking.

Results describe the **whole agent configuration**: model, prompt, documentation,
tools, execution harness, and inference behavior. Hold the surrounding setup
constant when comparing models, and disclose unavoidable differences. Freeze
starting fixtures and record live starting conditions; identical saved inputs
alone do not establish equivalent live scenes or deterministic combat.

A 15-second peak establishes a brief achieved rate, not sustained efficiency.
Spawn luck, cooldowns, or a temporary cluster of enemies may affect it. XP
optimization also does not establish general MapleStory competence, quest-solving
ability, party coordination, or broad intelligence. Those require separate tasks.

## Implementation and documentation follow-through

The published full-client pilots verify initial/final persisted net XP; those
saved endpoints cannot reconstruct authoritative 15-second peaks. Historical
short trials and five-minute adaptive pilots do not establish the proposed
30-minute protocol. Opt-in native ledger, window scoring, longer controller and
publication implementations now exist in source; actual runtime qualification
remains necessary. See [native score delivery](FULL_CLIENT_NATIVE_XP_DELIVERY.md)
and [long-horizon control](FULL_CLIENT_LONG_HORIZON.md).
See [class benchmark design](CLASS_BENCHMARK_DESIGN.md) and
[full-client experiments](FULL_CLIENT_EXPERIMENTS.md) for existing constraints.

Before publishing this protocol, validate timestamped XP accounting on the actual runtime,
level transitions, window scoring, the full wall-clock deadline, and repeated
observation/action cycles. Freeze the scenario suite and failure rules. Preserve
historical results under their original protocol labels.

The README now adopts this central question and distinguishes historical scores,
source implementation and live acceptance. This framing document alone does not
claim that runtime qualification or repeated comparisons are complete.

## RuneBench sources

- [Project and scoring motivation](https://maxbittker.github.io/runebench/)
- [Task generator and time budgets](https://github.com/MaxBittker/runebench/blob/main/generate-tasks.ts)
- [Leaderboard aggregation and coloring](https://github.com/MaxBittker/runebench/blob/main/app/components/Heatmap.js)

MapleBench's fixed complete windows are an explicit protocol choice. RuneBench's
tracker normally samples every 15 seconds, while its verifier accepts other
positive intervals between adjacent samples; see the pinned source review in
[the existing design document](CLASS_BENCHMARK_DESIGN.md#runebench-reference).
