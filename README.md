# MapleBench

**Status: v0 scaffold / active prototype.**

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
- `docs/COSMIC_INTEGRATION.md` — concrete server adapter plan.
- `docs/RECORDING.md` — gameplay video pipeline.
- `docs/MULTIAGENT_KPQ.md` — first multi-agent research design.

## Run the current scaffold

Requires Node 22+ and TypeScript (`tsc`). No npm dependencies are currently required.

```bash
npm test
npm run score:demo
```

The demo command scores a tiny example server event stream. It is deliberately independent of Cosmic so we can lock the benchmark contract before wiring the game server.

## Near-term milestones

- [x] Define server-authoritative episode/event schema.
- [x] Implement total XP and rolling XP-rate scorers.
- [x] Define narrow TypeScript SDK contract.
- [ ] Pin and boot Cosmic/bot fork in a reproducible local deployment.
- [ ] Implement `observe` + `move_to` + `basic_attack` adapter path.
- [ ] Log XP events from normal Cosmic reward logic.
- [ ] Run one end-to-end `maximize-xp-10m` episode.
- [ ] Attach observer client and emit `run.mp4`.
- [ ] Wrap SDK in an `execute_code` MCP tool / Harbor task.
- [ ] Generalize harness to four characters.
- [ ] Implement Kerning PQ evaluation.

## Upstream references

- Cosmic: <https://github.com/P0nk/Cosmic>
- Cosmic bot fork: <https://github.com/NDBellisario/cosmic>
- Maplewright: <https://github.com/Sheilem/maplewright>
- RuneBench: <https://github.com/MaxBittker/runebench>

## Licensing / assets

This repository should only contain original benchmark/framework code unless otherwise clearly marked. MapleStory names, game data, WZ files, art, audio and other proprietary assets are not distributed here. Any Cosmic-derived server patches must preserve the applicable upstream license.
