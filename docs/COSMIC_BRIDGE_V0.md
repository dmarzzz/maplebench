# Cosmic bridge v0

The repository now contains the first concrete Cosmic adapter under:

```text
patches/cosmic/overlay/src/main/java/server/bots/
  MapleBenchControlServer.java
  MapleBenchController.java
  MapleBenchEventSink.java
  MapleBenchJson.java
  MapleBenchRuntime.java
```

`npm run bootstrap` installs those sources into the pinned `NDBellisario/cosmic` checkout and adds these hooks:

1. `BotCombatManager.tryRequestedAttack(...)` — executes only the exact basic/skill attack the agent requested and returns `false` for illegal/cooldown/resource-gated actions.
2. `BotManager.findActiveBotEntry(...)` — lets the local adapter bind to one already-spawned benchmark character by name.
3. `Character.gainExpInternal(...)` — emits the exact EXP delta *after* Cosmic applies it to the authoritative character EXP counter.
4. `Server.main(...)` — starts the localhost control plane after normal Cosmic initialization, only when `MAPLEBENCH_ENABLED=true`.
5. The controlled-character tick keeps requested movement, physics, cooldowns,
   and incoming damage while bypassing upstream autonomous policies.

The overlay has been compiled against the full checkout, booted with MySQL and
WZ XML, and exercised through real movement, attacks, and XP events. See
[the Henesys demo](HENESYS_DEMO.md) for the opt-in seeded runtime and recording path.

The adapter does **not** expose autonomous `grind`, target selection, automatic best-skill selection, direct teleport, direct HP mutation, or direct EXP mutation.

## Environment

Run Cosmic normally, but add:

```bash
export MAPLEBENCH_ENABLED=true
export MAPLEBENCH_BOT_NAME=Agent01
export MAPLEBENCH_CONTROL_PORT=8790
export MAPLEBENCH_TASK_ID=maximize-xp-10m-warrior-v0
export MAPLEBENCH_SEED=trial-001
export MAPLEBENCH_EPISODE=/absolute/path/to/maplebench/artifacts/live/episode.jsonl
```

The control port binds to `127.0.0.1` only.

## v0 HTTP contract

Implemented:

```text
GET  /v1/observe
POST /v1/action       move_to | basic_attack | use_skill
GET  /v1/events?since_seq=N
GET  /health
```

`basic_attack` and `use_skill` require an explicit `targetId` in the first bridge so the adapter never chooses a target on the agent's behalf.

`move_to` uses the bot fork's normal navigation/movement path (`BotManager.issueMoveTo`) rather than setting coordinates.

## First live smoke test

After Cosmic is online and `Agent01` is spawned/registered as a bot:

```bash
curl http://127.0.0.1:8790/health
curl http://127.0.0.1:8790/v1/observe
```

In the MapleBench repo, keep the viewer running:

```bash
npm run ui
```

Then point any SDK script at the real adapter:

```bash
MAPLEBENCH_URL=http://127.0.0.1:8790 npm run demo:agent
```

The existing demo agent is only a smoke-test policy; real benchmark agents will receive the same SDK contract through the harness/MCP layer.

## Still required before calling v0 complete

- Add a deterministic benchmark-character reset/snapshot path.
- Implement loot/use-item/portal/AP/SP actions after the three core actions are proven.
- Verify another v83 client sees the physical movement and attacks.
- Connect Maplewright as the observer canvas.
