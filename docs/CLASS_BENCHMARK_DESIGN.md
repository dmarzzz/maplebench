# Class and task coverage for MapleBench

Status: proposed experiment design. Only the short Hero full-client scenario has
completed the current multi-model acceptance run. The classes and longer tasks
below are not implemented or benchmarked yet.

A useful benchmark should show which kinds of gameplay a model can handle. A
single well-equipped melee character on one monster map tests only a small part
of that ability. The next suite should vary class mechanics and objectives while
keeping each comparison's starting state, rules and budgets identical.

## Comparisons within each class

Start with a small representative set, expanding only after native skill effects
and persistence have been verified for every fixture:

| Archetype | Candidate class | Ability to test | Required evidence before inclusion |
| --- | --- | --- | --- |
| Close-range melee | Hero | Facing, platform approach, buffs and sustained attacks | Actual attack damage/contact, movement and saved XP |
| Ranged attacks | Bowmaster | Distance management and target access | Actual ranged hits, ammunition/resource behavior and native bindings |
| Area magic | Ice/Lightning Arch Mage | Grouping enemies, area coverage and mana management | Real area effects, affected entities and resource consumption |
| Mobile close-range attacks | Shadower | Approaching targets and choosing attacks | Actual skill availability, native movement and hit effects |
| Support and party play | Bishop | Healing, survival and coordination | Authoritative party health/objective events; no solo-XP proxy for support value |

These are candidate fixtures, not claims that the current client exposes all
skills correctly. Add other classes, including pirate classes, after the first
set passes physical-control and evidence checks. Do not transplant the Hero's
logical keys, prompt or equipment into another class and assume they work.

Each class fixture needs a versioned offline baseline: job, level, skill levels,
gear, stats, supplies, map/spawn, native keymap, allowed actions and inventory
rules. It also needs a class-specific SDK/prompt derived from that frozen
manifest. Verify actual movement and skill effects; a key acknowledgment alone
cannot qualify a fixture. The runtime, assets, scenario, prompt and budget hashes
remain part of the comparison identity.

All models receive the same fixture within a class. Different classes can have
different inherent damage, resource costs and XP opportunities; raw XP totals
across classes should not be averaged into an overall winner.

## Task families

1. **Control and combat:** the existing short run becomes an integration check.
   Include facing, jumping, target approach and native basic/class attacks.
2. **Sustained hunting:** a fixed declared wall-time budget tests net XP,
   survival, buff maintenance and supply management. Move to minutes only after
   the current deadline and action-receipt fixes pass acceptance.
3. **Navigation and progression:** reach a specified location or finish a
   server-observed sequence of objectives. Record completion and time to success,
   along with deaths and resource use when authoritative events exist.
4. **Party objectives:** fixed party composition and communication rules test
   coordination. Score the shared objective; do not judge a support class solely
   by its personal XP or damage.

For longer tasks, the clock and interaction contract must be declared before
runs. Report both wall time, including model reasoning/API latency, and active
controller time. Do not silently accelerate the server or pause game time for
some models. Longer horizons may require bounded replanning; those runs belong
to a separately versioned protocol from today's one-response program trials.

## Scorecard

Keep a small set of interpretable metrics instead of hiding them in one number:

- **Primary hunting score:** signed persisted net XP over the declared trial,
  including penalties. Preserve zero and negative outcomes.
- **Efficiency:** net XP per total session minute, with the denominator and API,
  controller and settlement durations visible. Early completion is explicit.
- **Peak execution rate:** a separately labeled rolling XP-rate metric, only
  after a complete authoritative timestamped XP ledger exists for full-client
  runs. State the fixed window and report it alongside total net XP; a short
  burst does not establish sustained performance.
- **Survival and resources:** alive at logout is available now. Death counts,
  potion use, mesos change, kills and damage require their own authoritative
  events or validated inventory deltas; keep unsupported metrics unknown.
- **Objectives:** completion fraction and time to completion for navigation or
  party tasks, based on explicit server-observed milestones.

The current full-client scorer has only offline initial/final persisted XP, so it
cannot reconstruct a peak window or identify a particular kill. The older
server-bot event scorer is a separate evidence path and sums positive gains;
its gross-XP metric cannot silently replace signed full-client net XP. Before
longer trials allow level-ups, pin the native experience table and verify
cumulative XP across transitions. The current scorer correctly rejects those
transitions rather than miscounting a rollover.

Display models as rows and class/task fixtures as columns, with the raw score,
number of trials, uncertainty and evidence failures available in each cell.
Initially publish per-fixture results without a combined score. Any later
aggregate must have predeclared class/task weights and stable normalization
references. Adding a new model must not silently redefine the reference scale.

## Experimental design

Freeze a finite comparison plan before model calls: supported exact model IDs,
class/task versions, repetitions, balanced order, spending and time limits,
failure policy and aggregate rules. An initial pilot can use five repetitions
per model per fixture to expose variance; that number is not a guarantee of
statistical precision. Expand the planned sample according to observed variance
and a declared precision target, without selectively rerunning poor outcomes.

Keep model-generated no-ops and gameplay failures visible. Distinguish them from
infrastructure/evidence failures. Report both eligible-run performance and the
fraction of attempts that produced eligible evidence; do not silently drop the
hardest runs. Combat RNG is not currently controlled. If seeds are introduced,
verify what state they actually control and pair the same seeds across models.

## Monster visibility observation

A viewer reported a monster remaining visible when disappearance was expected.
The run and timestamp are not yet identified, and the cause is unconfirmed. Keep
that report separate from a confirmed rendering defect or confirmed kill. It
could require comparing the original frames with authoritative entity state;
XP or a hit animation alone cannot establish a specific death.

Future kill scoring needs a native entity lifecycle ledger: map/world instance,
object identity plus spawn generation, ordered damage/death/despawn events and
reasons, and collection completeness. Distinguish death from respawn, unloading
and visibility changes. Preserve original recordings and results when logging an
anomaly; do not repair the evidence to make the rendered world appear cleaner.

## RuneBench reference

Reviewed primary source at commit
[`ccaf6d77cb0a557220574c5d79ecfa6329c3dbac`](https://github.com/MaxBittker/runebench/commit/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac).
RuneBench varies 16 trainable skills at 15- and 30-minute horizons and four gold
starting conditions. The inspected task schema has no character-class axis.
Its predefined saves motivate separate frozen fixtures here; they do not establish
seeded deterministic combat. [Task generator](https://github.com/MaxBittker/runebench/blob/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac/generate-tasks.ts)

Its XP verifier takes the highest positive rate between adjacent samples and
divides by 200 to account for its 8x simulation speed and 25x XP multiplier.
Sampling normally occurs every 15 seconds, but the verifier accepts other
positive interval lengths; this is not an exact fixed-width rolling window.
MapleBench should declare its own window and clocks rather than copy the scaling
constant. [XP verifier](https://github.com/MaxBittker/runebench/blob/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac/shared/check_skill_xp.ts),
[tracker](https://github.com/MaxBittker/runebench/blob/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac/shared/skill_tracker.ts)

Gold rewards the highest observed coins, including saved bank/equipment holdings,
and retains credit even if coins are later lost. It is neither net wealth gain
nor retained end-of-run wealth. That is a useful distinct objective, but it should
not replace MapleBench's signed persisted-XP score and penalties.
[Gold verifier](https://github.com/MaxBittker/runebench/blob/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac/shared/check_gold.ts)

The skill heatmap orders models by mean `ln(1 + normalized XP/min)` over all 16
skills, with missing entries treated as zero. Per-skill maxima set colors, not
that aggregate's reference scale. Borrow the readable task matrix and progress
curves. A logarithm of nonnegative RuneBench rates cannot be applied directly to
MapleBench's potentially negative net XP; preserve those values explicitly.
[Heatmap](https://github.com/MaxBittker/runebench/blob/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac/app/components/Heatmap.js)

Keep cutoff and attempt-selection rules explicit. RuneBench's XP extractor trims
post-horizon samples and chooses recent sufficiently sampled runs, using older
runs to fill gaps. Its gold extractor does not clamp samples to the horizon and
prefers bank-tracked results, then higher gold. Those are different policies,
not uniform averages over all declared repetitions. This observation does not
establish that any published result is inflated. MapleBench should retain its
predeclared attempt set, hard cutoff and visible failure policy.
[Skill extraction](https://github.com/MaxBittker/runebench/blob/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac/extractors/extract-skill-results.ts),
[gold extraction](https://github.com/MaxBittker/runebench/blob/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac/extractors/extract-gold-results.ts)
