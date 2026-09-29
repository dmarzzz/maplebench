# MapleBench skillbook matrix

Build a compact model-by-scenario matrix with square cells. Each square should open the evidence for one frozen task, while the grid reveals where an agent performs well and where coverage is missing. Use MapleStory’s skillbook as the visual reference and RuneBench’s matrix as the interaction reference.

The immediate chart should show the three published class fixtures. A second, explicitly proposed view can describe future skill tests. This separates a useful chart that can be built now from the additional benchmark work needed to claim specific abilities.

## What makes RuneBench’s chart work

RuneBench gives every row a model configuration and every column a recognizable game skill. Small icons make the columns compact; numerical cells preserve the measured result; green intensity makes differences easy to scan. Clicking a populated cell opens its trajectory. The implementation also supports sorting by a skill and orders the default view by an aggregate of log-transformed rates. These details were checked against the [heatmap source at revision ccaf6d7](https://github.com/MaxBittker/runebench/blob/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac/app/components/Heatmap.js).

The transferable idea is the relationship between the overview and the evidence: a reader can see a pattern, choose a square, and investigate the run that produced it. The square is a doorway into an experiment, not a decorative grade.

Some implementation choices should stay specific to RuneBench. Its heatmap falls back to zero for absent skill data, uses each column’s maximum for color, and calculates a mean of `ln(1 + rate)` across the skill suite. MapleBench must preserve missing evidence and negative net XP explicitly. Relative color is useful for a frozen release, but it is not a calibrated measure of task difficulty.

RuneBench’s task generator distinguishes 16 skill objectives and separate gold tasks. Its instructions describe peak XP rate under declared simulation and XP multipliers. MapleBench’s class fixtures are a different task axis: Hero, Bowmaster, and Ice/Lightning are not separately trained XP skills such as RuneScape’s fishing and mining. Copying their labels or scoring denominator would change the meaning of this benchmark. [Task generator](https://github.com/MaxBittker/runebench/blob/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac/generate-tasks.ts)

## What MapleBench can honestly show today

The public snapshot retrieved September 12, 2026 contains a `research_matrix` with four models, three class fixtures, and one verified pilot per model/fixture pair. Every column uses `full-client-adaptive-pilot-v1`; the declared budget is 300 seconds including inference. The metric is persisted net XP across the run’s cycles. The twelve `authoritative_peak_xp_per_minute` fields are null. These are five-minute adaptive pilots, distinct from the older single-request recordings in the local example page. [Public result dataset](https://maplebench.vercel.app/results.json)

| Model | Hero | Bowmaster | Ice/Lightning |
| --- | ---: | ---: | ---: |
| GPT-6 Astra | +18,250 | 0 | 0 |
| GPT-5.6 Sol | +18,250 | 0 | 0 |
| GPT-5.6 Terra | +18,250 | 0 | 0 |
| GPT-5.6 Luna | +23,000 | 0 | 0 |

Values are saved XP, with one run in each cell. This is coverage across fixtures, not an overall model ranking. The dataset explicitly marks it unranked and uncertainty unestimated. The Bowmaster annotation also states that this port implements discrete Hurricane attacks rather than continuous channeling; that limitation belongs in its cell details. [Hero cohort](https://maplebench.vercel.app/cohorts/189edbdd723728a7/), [Bowmaster cohort](https://maplebench.vercel.app/cohorts/7f57831f59bf5f35/), [Ice/Lightning cohort](https://maplebench.vercel.app/cohorts/0040d7cec0f101e1/)

A zero is informative: no net saved XP was achieved. It does not identify whether targeting, movement, skill selection, native client behavior, or another factor was responsible. Similarly, acknowledged inputs establish that inputs were accepted; they do not prove damage or skill effects. “Alive at logout” is an endpoint observation, not a complete record of deaths or potion management. These distinctions follow the repository’s [class benchmark design](../../../docs/CLASS_BENCHMARK_DESIGN.md).

The present dataset therefore supports a model-by-class **training result** matrix. It does not support assigning separate navigation, combat, resource-management, or planning grades to those same runs.

## Recommended visual and interaction design

Use one unframed matrix inside the existing Results surface. Keep models in a stable order and show text under small class symbols. The names remain readable even without recognizing an icon. Cells show exact values; selected cells receive a clear outline. Color compares values within that fixture only.

Put sample count and the active metric beside the matrix. For the current release, “Saved XP · 5-minute pilots · 1 run per cell” is enough. Avoid an overall score, podium, stars, percentage of intelligence, or auto-sorting that suggests the single-run pilot establishes a winner.

Selecting a cell should update a nearby evidence panel with the model, fixture, metric, verified/planned counts, uncertainty status, and links to the original recording and cohort. Show only the selected cell’s special limitations. Use ordinary buttons inside a semantic table so keyboard and screen-reader interaction remain straightforward; mobile can scroll the matrix while retaining the model names in a production implementation. Do not make tooltips the only way to discover a task or failure reason.

A sparse first grid is preferable to decorative data. Three class columns can grow into grouped scenario columns without changing the relationship between a square and its experiment. Keep “Proposed skill tasks” separate and explicitly unscored. Native qualification checks, single-model demonstrations, and new protocols should never silently fill an existing comparison cell.

| Option | Strength | Limitation | Decision |
| --- | --- | --- | --- |
| Model × class training matrix | Uses current verified outcomes; directly connects to recordings | Cannot isolate individual abilities | Ship this first |
| Model × controlled skill tasks | Produces specific, interpretable capability evidence | Requires qualified fixtures and new experiments | Build next |
| Per-model radar chart | Compact summary | Mixes units; hides missing coverage; encourages arbitrary grades | Do not use |
| Achievement tree | Strong game identity; shows task dependencies | Edges can imply unproven prerequisites | Revisit after task contracts exist |

The standalone prototype implements the first two views with current pilot data and empty proposed slots. It contains no invented model results and does not modify the live result catalog.

## A defensible skill suite

A skill cell needs a task that requires the ability and an independent verifier for the outcome. A generated program mentioning `Teleport` is not sufficient; the game must show the qualified effect. A replay is useful supporting evidence, but scorer inputs should come from authoritative events or validated state deltas.

Crafter provides a useful precedent: it evaluates semantically meaningful achievements inside a single game environment. MapleBench can borrow the idea of understandable, verifiable objectives while choosing tasks appropriate to its client and server. This does not make the benchmarks equivalent or establish the same cognitive constructs. [Hafner, *Benchmarking the Spectrum of Agent Capabilities*](https://danijar.com/project/crafter/)

| Proposed fixture | Required outcome | Evidence needed | Likely confound to control |
| --- | --- | --- | --- |
| Platforming | Reach a marked ledge and land in its target zone | Authoritative positions and landing state | Spawn position, platform geometry, physics |
| Native Teleport | Cross a specified gap and stop in the target zone | Native skill event, displacement, resource change | Walking access, cooldown, unsupported client bindings |
| Potion use | Restore MP from a declared low-MP start | Native item-use event or validated inventory/MP deltas | Passive regeneration, starting supplies, outside help |
| Buff upkeep | Maintain a named buff during a bounded task | Timestamped apply/expire events and complete coverage | Buff availability, cooldown, class-specific rules |
| Navigation | Reach a destination through allowed portals | Authoritative map transitions and final location | Route knowledge, spawn randomness, teleport shortcuts |
| Recovery | Resume productive hunting after a controlled setback | Setback, respawn/route, and resumed-progress events | Different setbacks, free healing, ambiguous progress |

These are proposed fixtures, not frozen tasks or claims of available telemetry. Start with platforming, Teleport, and potion use because each has a relatively concrete outcome. Qualification should first establish that the native mechanic works. Then give every compared model the same versioned task, permitted controls, budget, and observations. Keep those qualification scripts out of model-result rows.

Longer navigation chains, quests, resupply decisions, and party support could extend the suite. They should not be added merely to make the grid wider. Each new column needs an actual scorer, fixture, and failure policy. Party support in particular needs party-level outcomes rather than the supporting character’s personal XP.

## Cell semantics and scoring

Every square should distinguish these states:

| State | Cell display | Meaning |
| --- | --- | --- |
| Verified positive XP | Signed number, green fill | Measured net gain |
| Verified zero XP | `0`, neutral fill | Measured zero, not missing |
| Verified negative XP | Signed negative number, warm fill | Measured loss, retained in the result |
| Task not run | `—`, empty outline | No attempt under this contract |
| Infrastructure/evidence failure | Short status or `?`, patterned fill | Outcome cannot be verified; retain attempt details |
| Valid skill-task failure | `0/n` or measured completion fraction | Task was evaluated and its success condition was not met |
| In progress | Named state | An active run, never a provisional success score |

Current XP cells show exact signed results. With repeated runs, choose and freeze the statistic before collecting data; retain the distribution and all attempts in the drilldown. Skill tasks should normally display success counts such as `3/5`, together with the attempt denominator and time-to-success details. Do not convert all metrics to a single percentage simply because they share a grid.

A one-trial cell should never display a confidence interval of zero width. There is no empirical replication variance to estimate from one run. The uncertainty problem is familiar in game-agent evaluation: Agarwal and colleagues show that few-run point estimates can lead to unreliable comparisons and advocate interval estimates and distribution-aware reporting. The application here is a methodological recommendation, not an assertion that MapleBench shares the paper’s experimental distribution. [*Deep Reinforcement Learning at the Edge of the Statistical Precipice*](https://arxiv.org/abs/2108.13264)

The longer-term MapleBench framing already proposes 30-minute adaptive tasks, a peak rate from complete authoritative 15-second windows, and an aggregate over a frozen scenario suite. Preserve that prospective contract rather than retrofitting the five-minute pilots into it. The production research matrix itself labels peak-rate scoring unavailable. A diagnostic observation sequence cannot supply an authoritative peak merely because timestamps exist. [Research framing](../../../docs/RESEARCH_FRAMING.md), [public protocol metadata](https://maplebench.vercel.app/results.json)

When that protocol is accepted, the same visual component can show peak XP/min under a new protocol selector. Keep signed total net XP alongside it. Version the roster and normalization with the release. Relative cell colors may use within-column maxima, but the legend must make their scope explicit; adding a stronger model can change a cell’s shade without changing its score.

## Data contract and rollout

The backend already publishes most of the structure needed for the first view. Reuse `research_matrix.columns`, its model cells, and `attempt_ids`. A column identity must retain protocol, task, class fixture, and fingerprint; a visual class name alone is insufficient to group experiments. Display `valid`, `planned`, `failed`, `unknown`, `no_ops`, `in_progress`, and the declared uncertainty status when present. Do not reconstruct membership by scanning whichever successful recordings are easiest to load.

For controlled skill tasks, extend the published cell schema with an explicit metric ID, unit, scorer version, success definition, evaluated count, success count, and the declared repetition statistic. Keep qualification status and model evaluation status separate. The optional narrative evidence attached to a recording must not become the scorer by accident.

A practical rollout is:

1. **Current pilots:** replace the existing research table’s presentation with the square matrix, preserving its frozen membership, data and cohort links. Keep the historical local snapshot separate.
2. **Short skill fixtures:** qualify a few native mechanics, freeze task contracts, and run the same models under each contract. Publish untested and failed-evidence states explicitly.
3. **Repeated comparisons:** predeclare repetitions and balanced run order; publish all attempts and uncertainty. Five repetitions may expose variance, but it is not a guarantee of adequate statistical power.
4. **Long-horizon training:** add authoritative window scores only after runtime acceptance. Keep prior protocols accessible without mixing their cells.

The design should earn its visual richness by accumulating experiments. It should not manufacture a broad ability profile from a narrow XP test.

## Source record

- Max Bittker et al., [RuneBench](https://maxbittker.github.io/runebench/), inspected September 12, 2026.
- RuneBench [heatmap](https://github.com/MaxBittker/runebench/blob/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac/app/components/Heatmap.js), [task generator](https://github.com/MaxBittker/runebench/blob/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac/generate-tasks.ts), and [skill verifier](https://github.com/MaxBittker/runebench/blob/ccaf6d77cb0a557220574c5d79ecfa6329c3dbac/shared/check_skill_xp.ts), revision `ccaf6d77cb0a557220574c5d79ecfa6329c3dbac`.
- MapleBench, [public result snapshot](https://maplebench.vercel.app/results.json), retrieved September 12, 2026. Source SHA-256: `bd3d37402284bc136ce873e71aa47603a883832aa49cecdddb19edb3e9a64974`. A minimal, public-data projection is preserved in [data.json](./data.json); the prototype does not poll the live site.
- MapleBench, [class benchmark design](../../../docs/CLASS_BENCHMARK_DESIGN.md) and [research framing](../../../docs/RESEARCH_FRAMING.md), local design records. Their prospective proposals are not implementation evidence.
- Danijar Hafner, [*Benchmarking the Spectrum of Agent Capabilities*](https://danijar.com/project/crafter/), ICLR 2022.
- Rishabh Agarwal et al., [*Deep Reinforcement Learning at the Edge of the Statistical Precipice*](https://arxiv.org/abs/2108.13264), NeurIPS 2021, revised January 2022.
