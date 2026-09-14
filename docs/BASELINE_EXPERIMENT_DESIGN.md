# Baseline before strategy search

Design proposal, September 13, 2026. This document orders the next work; it is
not a frozen protocol, runtime qualification, completed comparison or ranking.
The user wants a scientifically defensible baseline before self-review/search.
The central question and eventual 30-minute score remain in
[RESEARCH_FRAMING.md](RESEARCH_FRAMING.md).

## What the current Mage clips measure

The three recent expanded-toolkit clips each use one actual model response and
up to 60 seconds of model-authored JavaScript. The prompt asks for skill
exploration and survival. The program can repeatedly call `sdk.observe()` and
react through its own branches; the model receives no subsequent execution
feedback and cannot rewrite that program within these previews.

The model receives structured character state and monster coordinates, not the
recording a human viewer sees. The short-preview observation contract does not
expose monster HP, authoritative damage, cast acceptance, cooldowns or terrain
geometry. An acknowledged key is not a confirmed cast. Instructions, feedback
limits, strategy quality and incomplete native mechanics qualification can all
affect the observed behavior. These clips cannot isolate the effect of using
code as the action interface.

All three public previews saved zero net XP. They demonstrate several native
spell effects and movement, not an effective training strategy. Increasing the
number of different skills pressed is a mechanics-check objective; efficient
play may correctly choose a small subset of the available skills.

The actual preview programs are not equally reactive: Astra reselects targets
before spells, Sol checks resources and includes a blocked-Teleport fallback,
while Terra never reads monster positions in its program. These are examples
of program-level decisions, without subsequent model-level critique.

Earlier five-minute pilots already used repeated model/program cycles with
limited skill fixtures. They are not a controlled comparison against these
expanded-toolkit previews: prompt, toolkit, horizon and feedback differ.

## First gate: prove an attainable, observable task

Before a fresh model comparison:

- Verify the declared skills with native effects, costs and ordinary persisted
  resources. Fix or exclude unsupported routes before freezing the toolkit.
- Use an explicitly labeled internal control through the same gameplay SDK to
  demonstrate repeatable monster defeat, authoritative XP gain, ordinary logout
  and baseline restoration in the selected fixture. A stationary no-input
  control checks for unsolicited progress. Neither defines the score's
  denominator, and neither is presented as a model result.
- Review whether the equipment, monster HP/defenses, platform layout and allotted
  time permit productive play. Freeze the resulting scenario before evaluation;
  do not alter difficulty to rescue a particular model's outcome.
- Validate that allowed observations give usable feedback about actions. Any
  added cast/cooldown/damage/terrain fields must be native-backed, documented,
  versioned and identical across compared agents. Unsupported values stay absent.
- Test the authoritative XP ledger and fixed windows against native gains,
  level transitions, penalties and ordinary saves. Until accepted, report only
  verified signed persisted net XP; do not reconstruct peak rates from endpoints.

## Baseline agent and controlled variants

The primary baseline should be a simple observe/act/replan agent, consistent
with the project's strategy-discovery goal. No cross-run memory, candidate
population, human repair or hidden combat helper. The existing adaptive runner
is a starting point; its behavior still requires qualification with the newly
frozen fixture and feedback contract.

| Condition | Behavior | Question answered |
| --- | --- | --- |
| A: one generated program | One model response; program may observe and branch | How much is lost without model-level replanning? |
| B: ordinary replanning | Fresh state and a fixed execution summary feed the next bounded program | Does feedback and replanning improve play? This is the primary baseline agent. |
| C: explicit self-review | Same inputs and limits as B, plus a bounded critique and revision step | Does explicit reflection improve on ordinary replanning? |
| D: candidate search, later | Generate, evaluate and select program variants | Does search improve results for its total evaluation cost? |

For B versus C, give both the same execution information, history allowance,
model settings, wall-clock budget and inference caps. Include critique tokens
and latency in C's budget; report actual usage. Do not give only C video or
hidden native state. Adding visual feedback is a separate intervention.

A versus B changes the opportunity for model inference. Report that comparison
as a whole-agent configuration difference, not proof that feedback alone caused
the improvement. Let A's generated policy run and observe for the same outer
budget as B; comparing a 60-second showcase against five minutes of replanning
would confound horizon with feedback. Both include initial inference in their
wall clock, with identical action and observation permissions.
To distinguish informed improvement from extra candidate
sampling, later compare self-review/search with independent best-of-K candidates
under matched total evaluation and inference budgets.

A direct-action agent can be an additional code-interface ablation. Keep its
observation privileges, action semantics, game speed and outer budgets matched;
report unavoidable differences in inference frequency and overhead. Do not
attribute a difference to code syntax alone when those differ.

## Experimental discipline

1. Start with one qualified Mage task. Freeze exact model identifiers, prompt,
   toolkit, map/equipment/resources, observations, harness commit, cadence,
   scoring, wall time, inference caps and failure rules before collecting data.
2. Use short development trials to repair mechanics and estimate variance.
   Keep those out of the evaluation set. Select repetitions and uncertainty
   analysis before examining confirmatory model differences; one clip per
   model does not establish a dependable ranking.
3. Randomize model/condition order within recorded environment blocks. Restore
   fixtures and record actual live starts. Do not call runs seed-paired or
   deterministic unless the world RNG and spawn-state replay are verified.
4. Reset agent memory and baseline state between independent replicates. Any
   self-improvement inside an evaluated run consumes that run's fixed budget.
   Cross-run learning is a separate condition with an explicit training budget.
5. Count inference, reflection, failed candidates, resets used for search and
   gameplay evaluation in the declared optimization budget. Parallel search
   also reports aggregate worker/gameplay time and cost, not just elapsed time.
6. Keep every predeclared attempt and its model/infra/unknown failure category.
   A model's valid zero-XP outcome remains zero. Missing evidence is missing.
   Apply predefined infrastructure replacement rules; never selectively retry
   weak model play or replay an uncertain API operation.
7. Report per-run outcomes and uncertainty, not only a winning clip. Preserve
   signed net XP, survival, resource use, native-confirmed effects, wall time,
   tokens and cost. The intended best complete 15-second XP rate remains the
   research score only after its runtime gate passes; also show sustained/total
   progress because a short peak can reflect a lucky monster cluster.
8. Evaluate selected search strategies on fresh, held-out starts after freezing
   selection. Report training/search cost and all evaluations. Reusing the
   winning training episode is not evidence of generalization.

## Next-work burn-down

- [x] Audit short-preview objectives and distinguish program reactivity from
  model-level replanning.
- [ ] Qualify an end-to-end productive Mage control: defeat, native XP, save and
  restore, plus no-input control.
- [ ] Finish the declared skill/observation qualification and freeze one task.
- [ ] Verify ordinary replanning on that task with complete feedback receipts.
- [ ] Freeze a repeated four-model baseline protocol and failure rules, then run
  and publish all attempts with uncertainty appropriate to the sample size.
- [ ] Compare one-program versus ordinary replanning on the same frozen task.
- [ ] Add explicit self-review as a separately labeled controlled experiment.
- [ ] Consider candidate search only after those baselines, with independent
  sampling controls, aggregate budgets and held-out evaluation.
- [ ] Expand the accepted procedure to Hero, Bowmaster and Night Lord.

The initial review experiments may be short and explicitly labeled as such.
They do not replace or establish the eventual 30-minute research benchmark.

## Relevant precedents

- [Code as Policies](https://code-as-policies.github.io/) demonstrates generated
  programs with reactive feedback loops; code is not inherently an open-loop
  action representation.
- [Voyager](https://voyager.minedojo.org/) combines executable skills with
  environmental feedback, execution errors and iterative program improvement.
- [Reflexion](https://arxiv.org/abs/2303.11366) studies verbal feedback retained
  for later attempts without changing model weights.

These motivate experiments; they do not establish that MapleBench will benefit.
Self-review of one program is iterative refinement. A genetic algorithm would
add an explicit population, variation and selection process.
