# MapleBench viewer

Zero-dependency run viewer. It is intentionally asset-free so the benchmark repo can stay distributable without MapleStory game assets.

## Fastest path

```bash
npm run ui
```

Open http://127.0.0.1:8787 and click **Play demo**.

You can also load any MapleBench episode JSONL through the file picker.

## Live mode

When served with `npm run ui`, the page automatically opens an SSE connection and tails:

```text
artifacts/live/episode.jsonl
```

Override it with:

```bash
MAPLEBENCH_EPISODE=/path/to/run/episode.jsonl npm run ui
```

As soon as the Cosmic bridge appends valid MapleBench JSONL events, the score, action display, chart and log update live. This gives the server integration an intentionally tiny visual contract: **append events to one file**.

## Intended game-canvas integration

The synthetic center viewport is temporary. The surrounding UI is the durable part: run metadata, score HUD, public agent notes/actions, XP chart, and episode log. Replace the `.viewport` contents with either:

1. Maplewright's browser canvas connected to Cosmic via its `wsproxy`, or
2. a video element playing the observer recording for completed runs.

Do not surface hidden model chain-of-thought. If we show reasoning in recordings, it should be an explicit agent-authored public plan/summary field produced by the benchmark harness.
