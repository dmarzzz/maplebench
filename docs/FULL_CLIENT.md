# Full-client program controller (integration prototype)

This adapter runs MapleBench JavaScript programs against the Journey WASM client
connected to Cosmic. Ordinary client code handles physics, contact damage,
attacks, animation, and monster hit reactions. It does not call the older
server-bot movement or attack shortcuts.

The existing sandbox now offers `sdk.pressKeys(keys, milliseconds)`. It accepts
up to three named keys for 30–1500 ms and releases them afterward. Keyboard
input is available only when the scenario declares `adapter: full-client`.
Programs still execute in a networkless, read-only, resource-limited Docker
container. Credentials remain in the trusted host process.

```js
const state = await sdk.observe();
if (state.character.hp < state.character.maxHp / 2)
  await sdk.pressKeys(['HP_POTION'], 100);
await sdk.pressKeys(['LEFT'], 300);
await sdk.pressKeys(['BRANDISH'], 650);
```

Allowed keys: LEFT, RIGHT, UP, DOWN, JUMP, ATTACK, BRANDISH, COMBO, BOOSTER,
MAPLE_WARRIOR, HP_POTION, MP_POTION. The example character must have ordinary
key bindings for those named skills/items. The supplied frontend maps arrows,
Space, Ctrl, A/S/D/F, and Q/W respectively.

## Setup

1. Build the pinned client with [the integration patch](../patches/full-client/README.md).
2. Supply the upstream asset files separately and install its Python web dependencies.
3. Start a dedicated Cosmic world and create a disposable synthetic account and
   single character. Use a normal hunting map, not a quest map with a forced return.
4. Provide environment variables to `python3 scripts/serve-full-client.py`:

| Variable | Purpose |
| --- | --- |
| `MAPLEBENCH_CLIENT_ROOT` | Built upstream checkout, with its read-only `assets/` |
| `MAPLEBENCH_DEMO_ACCOUNT_FILE` | Mode-0600 JSON with generated `username` and `password` |
| `MAPLEBENCH_CLIENT_OUTPUT` | Ignored directory for videos and per-run outputs |
| `MAPLEBENCH_API_KEY_FILE` | Optional mode-0600 OpenAI key file |
| `MAPLEBENCH_DOCKER_COMMAND` | Optional trusted Docker command prefix |

The sandbox image `node:22.19.0-bookworm-slim` must already exist; runtime pulls
are disabled. The HTTP wrapper listens on loopback 8840, the bounded game proxy
on 8841, and the asset service on 8842. Tunnel those ports when the client is on
another machine. The web UI may be forwarded to a different local HTTP port.

Open `/web/index.html`. It performs normal account login automatically. The
manual toolbar remains useful for integration checks. **Run SDK script** runs a
deterministic smoke program. The four named API buttons request a program from
the selected OpenAI model, then execute it through the same SDK. Each run makes
at most one API request with 3000 output tokens and executes for at most 22
seconds. The game continues during API latency. The live and recorded overlays identify manual,
scripted, and API control, current keys, HP/MP and diagnostic XP change. API
recordings include the exact requested model; the runner rejects a different
returned model. Recording includes API planning time and retains the native HUD.

The relay rejects stale observations or render frames, concurrent clients/runs, invalid key
combinations, and unacknowledged input. An action is acknowledged after its key
hold ends. Expired undelivered commands are discarded. All key holds have local
release timers. The renderer must remain open and active for this prototype.

## Evidence and current limits

The integration smoke program completed 26 keyboard actions and gained 14,000
client-reported XP. A subsequent `gpt-6-astra` API program completed 25 actions
and gained 4,750 client-reported XP; the level 180 Hero survived both runs.
Recordings show the actual client canvas, with controller labels. These were
sequential integration tests with different starting states, not a comparison.

This is not yet connected to the durable four-model batch queue or its scoring
pipeline. `result.json` records initial/final client state, API response metadata,
programs, and acknowledged SDK actions. Client XP changes are diagnostic only;
a ranked benchmark still needs server-event scoring, reset parity, and a remote
headless renderer. Currently assets, API requests, and program containers can
run on the remote host while WASM rendering/input executes in the viewing browser.
The reused client is a reconstruction, not proof of official-client fidelity.

Do not run this world alongside a queue trial on the same character/world. The
operator must own the existing world locks and restore the normal worker when
the demo lease ends. Never commit credentials, outputs, or game assets.

## Next scored adapter: normal persistence

The existing bot event sink is disabled in full-client mode. The smallest
server-backed score uses a frozen private database baseline restored while Cosmic
is stopped, a fresh server per trial, and final numeric character stats after
ordinary client disconnect has saved and logged off the account. Check save-error
logs and compare final client state diagnostically; offline status alone cannot
prove that saving succeeded. Never reset rows while the character is online.

This contract should be named `net_xp` from `cosmic_persisted_character`, counting
death penalties as well as gains. Initially require unchanged level; supporting
level transitions later needs the pinned server experience table. Measure the
whole connection-to-logout session and report API/controller/settlement durations
separately. Identical database baselines do not imply deterministic combat RNG.
Kills and damage remain unknown without additional authoritative evidence.

The publication validator in `scripts/full_client_publish.py` is a fail-closed
check of supplied evidence and hashes, not an independent proof of API/server
truth. Current integration manifests intentionally omit reset/server-score
evidence and cannot pass ranked publication.
