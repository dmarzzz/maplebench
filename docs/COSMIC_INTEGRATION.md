# Cosmic integration plan

## Upstreams

Canonical world/server candidate:

- `P0nk/Cosmic` (v83 server emulator)

Implementation reference / likely development base:

- `NDBellisario/cosmic` bot fork

The bot fork advertises real-character bots plus movement, navigation, combat, skills, consumables, equipment, quests, parties, and partial Kerning PQ automation. Its source tree includes dedicated classes such as `BotMovementManager`, `BotNavigationManager`, `BotCombatManager`, `BotAttackExecutionProvider`, `BotPhysicsEngine`, and `server/bots/pq/*`.

## Clean boundary

Do not vendor Cosmic into the benchmark framework repo initially. Instead:

1. Pin an upstream commit SHA in deployment config.
2. Maintain a small patch series or a separate AGPL adapter branch against Cosmic.
3. Run the server as its own process/container.
4. Expose only the MapleBench adapter HTTP/WebSocket port to the SDK container.

This keeps the benchmark framework easy to audit and makes upstream licensing clearer.

## Adapter endpoints (v0)

### `GET /v1/observe`

Return only information an agent is allowed to know:

- own character state
- visible monsters and drops in the current map
- visible/known portals
- inventory, skills, stats as permitted by task

### `POST /v1/action`

Accept exactly one action from `MapleAction`. The adapter maps it to normal Cosmic mechanics.

Important: `move_to` may use the fork's navigation implementation to find a legal physical route, but should not instantly set the character's coordinates.

### `GET /v1/events?since_seq=N`

Return append-only server-authoritative benchmark events.

### Private harness endpoints

The runner (not the agent) also needs privileged endpoints or direct DB/server hooks for:

- reset episode
- load task snapshot
- start timer
- stop timer
- fetch complete trace

These must live on a separate interface/network so evaluated code cannot call them.

## First code-reading targets

Before writing the Java adapter, inspect and map the public methods/state transitions in:

1. `BotManager`
2. `BotEntry`
3. `BotMovementManager`
4. `BotNavigationManager`
5. `BotCombatManager`
6. `BotAttackExecutionProvider`
7. `BotInventoryManager`
8. `BotPotionManager`
9. `server/bots/pq/*`

The objective is not to call the existing `grind` command. It is to identify the lowest safe primitive that still causes ordinary game-visible movement and combat.

## v0 acceptance test

A successful integration should prove all of the following with one character and one normal observer client:

1. Adapter observes a nearby monster.
2. SDK sends `move_to`.
3. Character visibly walks/jumps/climbs to attack range.
4. SDK sends `basic_attack` or `use_skill`.
5. Ordinary Cosmic combat logic applies damage.
6. Monster dies and XP is awarded by normal server logic.
7. `xp_gain` event appears in the benchmark log.
8. Observer client sees the same action sequence.
9. Score computed from the event log matches awarded XP.
