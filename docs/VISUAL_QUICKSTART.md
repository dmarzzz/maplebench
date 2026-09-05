# Fastest path to a real Maple visual

Goal: get a real v83 game canvas on screen first, then wire the benchmark controller into it.

## 0. See the benchmark UI immediately

```bash
npm run ui
```

Open http://127.0.0.1:8787 and click **Play demo**. No game assets are needed.

## 1. Pull the pinned engines

```bash
npm run doctor
npm run bootstrap
```

This checks out:

- `upstream/cosmic` at the pinned bot-fork commit and installs the MapleBench control-plane overlay + narrow core hooks.
- `upstream/maplewright` at the pinned browser-client commit.

Both are AGPL-3.0 upstream projects. We keep their source and notices intact.

## 2. Bring your own v83 WZ files

Set a local path such as:

```bash
export MAPLE_WZ="$HOME/maple-v83-wz"
```

Do **not** commit these files. Maplewright expects v83 GMS WZ files and its generated outputs are designed to stay gitignored.

## 3. First real visual before benchmark control exists

From `upstream/maplewright`, build its tools and bake one map:

```bash
cargo build --workspace --exclude web --release

mkdir -p crates/web/assets/maps/100000000
WZMAP_BGDUMP=crates/web/assets/maps/100000000 \
WZMAP_DUMP=crates/web/assets/maps/100000000/map.fh \
cargo run -p wz --release --bin wzmap -- \
  "$MAPLE_WZ/Map.wz" \
  crates/web/assets/maps/100000000/fg.png \
  Map/Map1/100000000.img
```

For the absolute first screenshot, the native client is the shortest path:

```bash
cargo run -p client --release -- crates/web/assets/maps/100000000
```

That proves WZ decoding + map render + physics before we debug networking.

## 4. Browser observer

Then build Maplewright's browser target:

```bash
rustup target add wasm32-unknown-unknown
cargo install wasm-bindgen-cli
cargo build -p web --target wasm32-unknown-unknown --release
wasm-bindgen target/wasm32-unknown-unknown/release/web.wasm \
  --out-dir crates/web/dist/pkg --target web
```

Run Maplewright's `wsproxy` between the browser WebSocket and Cosmic's TCP ports. Once connected to the v83 server, the browser canvas becomes the observer we embed in the center of `ui/index.html`.

## 5. Put the real Cosmic bridge on the same live UI

Once Cosmic itself boots normally, set:

```bash
export MAPLEBENCH_ENABLED=true
export MAPLEBENCH_BOT_NAME=Agent01
export MAPLEBENCH_CONTROL_PORT=8790
export MAPLEBENCH_TASK_ID=maximize-xp-10m-warrior-v0
export MAPLEBENCH_EPISODE=/absolute/path/to/maplebench/artifacts/live/episode.jsonl
```

Spawn/register `Agent01` in the bot fork, then verify:

```bash
curl http://127.0.0.1:8790/v1/observe
MAPLEBENCH_URL=http://127.0.0.1:8790 npm run demo:agent
```

`npm run ui` will already be tailing the exact event file written by Cosmic. See `COSMIC_BRIDGE_V0.md`.

## 6. Recording

For live benchmark runs, launch Chromium against the observer page and capture the canvas/window with ffmpeg. We should record two synchronized artifacts:

- `episode.jsonl` — authoritative benchmark events and score inputs.
- `gameplay.mp4` — human-readable observer rendering.

The recording is evidence/visualization, not the source of truth for scoring.

## 7. After the first real attack

The first `MapleBenchController` source is already included. After `observe` + `move_to` + requested attack are proven against the full server, extend it in this order: loot, use-item, portal, AP/SP, reset/snapshot automation.

Do not expose upstream autonomous `grind`, automatic skill selection, auto-build, quest automation, teleport, direct XP mutation, or direct HP mutation to the agent.
