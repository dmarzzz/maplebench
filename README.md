# MapleBench

**Status: active prototype.** The patched Cosmic server boots with a controllable
character. The repository also includes a server-observation replay renderer.
Four OpenAI API models have completed the initial Henesys combat fixture through
the narrow control API. This is an integration smoke test, not a model ranking.

MapleBench is an experimental benchmark for evaluating coding agents in a persistent MapleStory-like game environment, beginning with simple XP optimization and progressing toward multi-agent party-quest coordination.

The intended world implementation is a MapleStory v83-compatible open-source server such as Cosmic. The benchmark framework itself contains **no Nexon game assets or WZ data**.

## Research progression

1. **Maximize XP** — give an agent a standardized character and 10 minutes; score total server-authoritative XP gained.
2. **Maximize XP rate** — score peak sustained XP/min over a rolling 60-second window.
3. **Multi-agent party quests** — multiple agents coordinate to complete Kerning PQ under controlled communication topologies.

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

## Near-term milestones

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
