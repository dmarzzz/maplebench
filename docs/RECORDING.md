# Episode recording

## Principle

Recording is an observer, not part of scoring. The benchmark score is always computed from the server event log, so renderer lag or dropped video frames cannot change results.

## Preferred pipeline

```text
Cosmic world
   |
   +--> evaluated character (controlled through MapleBench SDK)
   |
   +--> observer client / renderer
            |
            +--> Chromium/headless window capture
            +--> HUD overlay from event stream
            +--> ffmpeg -> MP4
```

Maplewright is a promising renderer because it targets a clean Rust/WASM v83 client architecture and browser execution. If compatibility is insufficient, an ordinary compatible client can be used for the first recording milestone while the scoring stack stays unchanged.

## HUD

The recording should overlay benchmark metadata rather than relying only on in-game UI:

- model / agent name
- task id
- elapsed simulated time
- level and current EXP
- total benchmark XP gained
- rolling 60s XP/min
- map id/name
- optional current agent plan / latest action

## Artifacts per run

```text
artifacts/<run-id>/
  task.json
  metadata.json
  events.jsonl
  score.json
  agent-transcript.jsonl
  run.mp4
```

`events.jsonl` is the canonical gameplay trace. `run.mp4` is a presentation artifact.

## Replay vs live capture

For v0, live observer capture is enough and fastest to ship.

Longer term, if the server trace contains enough movement/combat state, deterministic or near-deterministic replay is preferable because we can re-render old evaluations with new overlays and camera logic without rerunning the agent.
