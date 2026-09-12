# MapleBench

**Can an agent discover a better training strategy within a fixed time budget?**
MapleBench evaluates model-authored programs through a rendered MapleStory-like
client. Agents observe, move, choose skills, manage resources and revise their
programs while the world continues to run. The benchmark evaluates the complete
model, prompt, tools and execution setup. See the
[research framing](docs/RESEARCH_FRAMING.md).

**Public evidence, September 12, 2026:** the [results site](https://maplebench.vercel.app/)
contains 12 completed five-minute pilots: Astra, Sol, Terra and Luna on Hero,
Bowmaster and Ice/Lightning Arch Mage. All have matching recordings and verified
saved net XP. The limited Bowmaster and Mage fixtures produced zero saved XP;
these results do not establish canonical class behavior or a model ranking.
Night Lord has no completed public model cohort. The earlier failed group is
closed and will not be resumed.

The adapter restores a frozen offline baseline, uses ordinary login and logout,
and checks model identity, input receipts, recording bytes and signed persisted
XP. Frozen saved inputs alone do not guarantee identical live scenes or combat
RNG. Historical pilots retain their original protocols and scores.

The next version adds expanded class kits, explicit 30-minute runs and native
15-second XP-window evidence. These features are implemented as opt-in source
candidates; they still require qualification on the actual game runtime before
new comparisons. The new kits map ten skills each for Hero, Bowmaster and
Ice/Lightning, and eight for Night Lord. Unsupported port mechanics remain
explicitly excluded. See [skill toolkits](docs/FULL_CLIENT_SKILL_TOOLKITS.md),
[native score delivery](docs/FULL_CLIENT_NATIVE_XP_DELIVERY.md), and the
[roadmap and release burn-down](docs/ROADMAP.md).

Moving to another computer? See [the laptop handoff](docs/LAPTOP_HANDOFF.md) to
reuse the existing runner without transferring its assets or credentials.

The earlier four-model server-bot batches and replay renderer remain available.
Their scores and rendering provenance are separate from the new full-client
recordings. See [scenarios](docs/SCENARIOS.md) and [replay provenance](docs/REPLAY.md).

The [production readiness criteria](docs/PRODUCTION_READINESS.md) track durable
isolated attempts, native save receipts, exact recording review and verified
publication evidence. Repeated trials, balanced model order and longer operational
acceptance remain necessary before a dependable public ranking. The new
[finite experiment coordinator](docs/FULL_CLIENT_EXPERIMENTS.md) implements
predeclared repeated plans, explicit resume without API replay, and complete-plan
reports. Its single-entry live acceptance passed; repeated-model and unattended
operation still require acceptance.

MapleBench is an experimental benchmark for evaluating coding agents in a persistent MapleStory-like game environment, beginning with simple XP optimization and progressing toward multi-agent party-quest coordination.

The intended world implementation is a MapleStory v83-compatible open-source server such as Cosmic. The benchmark framework itself contains **no Nexon game assets or WZ data**.

## Longer-term research directions

These are proposed directions, not completed full-client protocols. The
[current roadmap](docs/ROADMAP.md) gates longer tasks on repeatable operation and
the native scoring evidence each metric requires.

1. **Training strategy discovery:** a 30-minute wall-clock budget including
   inference; score the best normalized XP/min in a complete fixed 15-second
   native window and preserve signed total net XP separately.
2. **Class and task coverage:** freeze useful class toolkits and hunting,
   navigation or objective fixtures, then collect balanced repetitions and
   uncertainty before computing an overall score.
3. **Party quests:** study multiple agents under controlled communication rules
   after the required native mechanics and task evidence are implemented.

The older TypeScript total-XP and rolling-window tasks remain separate scaffold
protocols. They do not define the next full-client research score.

Every benchmark run should also produce a gameplay recording suitable for inspection and demos.

## Design principle

Agents should control a real in-world character through a narrow SDK, not mutate server state.

```text
coding agent -> MapleBench SDK/MCP -> Cosmic adapter -> Cosmic server
                                              |             |
                                              v             v
                                           events        observer
                                              |             |
                                           verifier       MP4
```

The upstream Cosmic bot fork is useful because it already implements real-character movement/navigation, combat, inventory, skills and party behavior. MapleBench should reuse those *execution primitives* while withholding its built-in autonomous policies (`grind`, auto-quest, etc.) from evaluated agents.

## Current repo contents

- `src/protocol.ts` — action, observation, task, and event contracts.
- `src/sdk.ts` — thin TypeScript agent SDK + HTTP transport.
- `src/scoring.ts` — total-XP and rolling XP-rate scoring.
- `tasks/` — initial XP and XP-rate task specs/prompts.
- `docs/COSMIC_INTEGRATION.md` — server adapter architecture.
- `docs/COSMIC_BRIDGE_V0.md` — concrete Java control-plane overlay + first live smoke test.
- `docs/RECORDING.md` — gameplay video pipeline.
- `docs/MULTIAGENT_KPQ.md` — first multi-agent research design.

## Run the current scaffold

Requires Node 22+. The pinned TypeScript compiler is installed with `npm ci`.

```bash
npm ci
npm test
npm run score:demo
```

The demo command scores a tiny example server event stream. It is deliberately independent of Cosmic so we can lock the benchmark contract before wiring the game server.

## Original server-bot milestones

This historical scaffold checklist describes the earlier adapter. Use the
[full-client roadmap](docs/ROADMAP.md#burn-down) for current release priorities.

- [x] Define server-authoritative episode/event schema.
- [x] Implement total XP and rolling XP-rate scorers.
- [x] Define narrow TypeScript SDK contract.
- [x] Identify concrete Cosmic movement/combat integration methods.
- [x] Pin Cosmic bot fork + Maplewright commits and automate checkout.
- [x] Build a zero-setup live viewer and end-to-end mock SDK plumbing.
- [x] Prepare `observe` + `move_to` + requested-attack Cosmic Java bridge source.
- [x] Prepare authoritative XP hook at Cosmic's real EXP mutation point.
- [x] Compile/boot the patched full Cosmic checkout on a machine with upstream/network access.
- [ ] Run one real end-to-end `maximize-xp-10m` episode.
- [ ] Attach Maplewright observer client and emit `run.mp4`.
- [ ] Wrap SDK in an `execute_code` MCP tool / Harbor task.
- [ ] Generalize harness to four characters.
- [ ] Implement Kerning PQ evaluation.

For the seeded Henesys combat fixture and replay commands, see
[the server demo guide](docs/HENESYS_DEMO.md). This short baseline experiment is
separate from a standardized ten-minute benchmark episode.

`scripts/run-openai-queue.py` runs a bounded, serialized OpenAI Responses API
batch against the dedicated disposable server/database. Each model gets the same
reset and prompt. Model IDs returned by the API, chosen actions, latency, usage,
observations, and scores stay in ignored run directories. Credentials come only
from the runtime environment or a private runtime file.

## Upstream references

- Cosmic: <https://github.com/P0nk/Cosmic>
- Cosmic bot fork: <https://github.com/NDBellisario/cosmic>
- Maplewright: <https://github.com/Sheilem/maplewright>
- RuneBench: <https://github.com/MaxBittker/runebench>

## Licensing / assets

This repository should only contain original benchmark/framework code unless otherwise clearly marked. MapleStory names, game data, WZ files, art, audio and other proprietary assets are not distributed here. Any Cosmic-derived server patches must preserve the applicable upstream license.

## Instant live demo

The full benchmark plumbing can be exercised before Cosmic/Maplewright are installed:

```bash
npm run demo:live
```

Then open http://127.0.0.1:8787. A tiny mock control backend on port 8790 accepts the same `MapleSDK` HTTP contract intended for Cosmic, a demo agent issues movement/attack/skill actions, the backend appends authoritative JSONL events, and the viewer updates from that file over SSE.

This mock exists only to validate benchmark plumbing. It is **not** a game simulator and is never used for benchmark scores.

## Unattended experiments

Submit `configs/smoke-20.json` to the persistent queue to run four OpenAI API models
five times, with automatic scoring, replay rendering and a local results gallery.
The worker resumes interrupted batches and keeps each attempt. See
[automated batches](docs/AUTOMATED_BATCHES.md), [programmable control](docs/PROGRAMMABLE_AGENT.md),
and [scenario presets](docs/SCENARIOS.md).
