# Scenarios and character presets

The short Henesys scenarios test the integration. The natural hunting scenarios
test repeated combat, movement, target selection, survival, and potion management.
They use normal Cosmic monsters and spawn points loaded from WZ data. They do not
refill the map, increase damage, heal the player, or choose actions for the model.

| Scenario | Character | Map | Time limit | Purpose |
| --- | --- | --- | --- | --- |
| `henesys-warrior` | Level 15 Warrior | Henesys `100000000` | 90 seconds | Three explicitly spawned Slimes; target 30 XP |
| `henesys-crusader` | Level 100 Crusader | Henesys `100000000` | 90 seconds | Three explicitly spawned Jr. Yetis; target 405 XP |
| `warrior-beach` | Level 15 Warrior | Beach Hunting Ground `104010002` | 600 seconds | Natural Pigs and Ribbon Pigs, finite potions |
| `crusader-c1` | Level 100 Crusader | Lab - Area C-1 `261020300` | 600 seconds | Natural Roid hunting, single-target versus area attacks, finite potions |
| `hero-c1` | Level 130 Hero | Lab - Area C-1 `261020300` | 600 seconds | Fourth-job Brandish, natural Roid hunting, finite potions |

## Why C-1 is the first longer scenario

The map's twenty Roid spawn points all have `mobTime=0` and ground `cy=167`.
Footholds 26, 23, 24 and 25 connect from x=-714 through x=893 at y=167. There are
decorative platforms above the floor, but no Roid spawn points on them. Starting
at `(0,167)` lets the model fight along this continuous floor without requiring
ladders or precise platform jumps. This reduces the effect of the known upstream
navigation precision failure while retaining normal movement and contact damage.

Roid `5110301` is level 54, has 4,400 HP and gives 168 base XP. The map declares
`mobRate=2.0`; the actual population and XP are also affected by server configuration,
which must be recorded with the batch. The fixture does not claim that exactly
twenty monsters will always be visible. An empty observation during a natural
hunt is a reason to wait or move, not a successful terminal condition.

Beach Hunting Ground has eighteen natural spawn points: eight Pigs `1210100`
(75 HP, 15 base XP) and ten Ribbon Pigs `1210101` (120 HP, 20 base XP). Fourteen
spawn points are at y=215; four are on shallow changes at y=275 or 335. It avoids
the Iron Hog found in the separate Pig Beach map. It is a useful easier movement
and resource-management scenario, but C-1 is the first advanced-character target.

## Presets

`scripts/seed-presets.sql` creates synthetic characters if absent. It does not
overwrite existing state. The batch runner resolves the database character ID by
name and resets the scenario's stats before each new server process starts.

| Preset | Synthetic character | Starting stats | Weapon | Skills |
| --- | --- | --- | --- | --- |
| `warrior` | `Agent01`, job 100, level 15 | STR 70, DEX 15, INT/LUK 4; HP 500, MP 100 | Sword `1302000` | Power Strike `1001004` level 1 |
| `crusader` | `Agent90`, job 111, level 100 | STR 350, DEX 120, INT/LUK 4; HP 4,000, MP 1,000 | Stonetooth Sword `1402037` | Power Strike `1001004` level 20, Slash Blast `1001005` level 20, passive Sword Mastery `1100000` level 20 |
| `hero` | `AgentHero`, job 112, level 130 | STR 500, DEX 120, INT/LUK 4; HP 8,000, MP 2,000 | Stonetooth Sword `1402037` | Brandish `1121008` level/master level 30, plus the Crusader preset's verified attack and mastery skills |

All start with equipment `1040036`, `1060026`, `1072001`, face `20000`, and hair
`30030`. Stonetooth's WZ requirements are level 100 and DEX 120; its default weapon
attack is 101. These are explicit benchmark builds, not claims that the character
has completed normal job-advancement quests or a complete player skill build.

Power Strike level 1 costs 4 MP and has 165% damage in this WZ dataset. At level
20 it costs 12 MP and has 260% damage. Slash Blast level 20 costs 16 HP and 14 MP,
has 130% damage, and can hit up to six nearby targets. Normal weapon damage,
accuracy, defense, attack locks and range checks still apply. Sword Mastery is a
learned passive rather than an action. The pinned upstream mastery lookup currently
omits two-handed sword type 140, so its improvement is not yet applied to
Stonetooth in this build. No automatic Final Attack or autonomous buff casting is
enabled.

Hero Brandish level 30 costs 25 MP, delivers two hits with 260% damage each, and
can hit up to three targets. Its WZ actions are `brandish1` and `brandish2`.
It does not require an active Combo buff, so the direct attack bridge can expose
a real fourth-job attack without adding autonomous buff setup or combo finishers.

Crusader Shout is deliberately omitted pending its own live skill validation.
An earlier Shout experiment used a newly created character whose equipment stats
were stale; it cannot establish whether the skill itself works. Runtime setup now
calls the ordinary `equipChanged()` path after installing gear and rejects a preset
with zero weapon attack. The earlier Slash Blast fixture earned 405 XP from three
Jr. Yetis; that result does not validate every Crusader skill.

## Finite consumables and control API

Each natural scenario starts with 100 White Potions `2000002` (300 HP each) and
100 Blue Potions `2000003` (100 MP each). Henesys smoke fixtures start with none.
The character receives exactly that inventory once at startup. Nothing replenishes
it during an episode, and the model must explicitly choose to use a potion.

`GET /v1/observe` includes, for example:

```json
{"inventory":[{"itemId":2000002,"name":"White Potion","quantity":100,"hpRestore":300,"mpRestore":0}]}
```

`POST /v1/action` accepts:

```json
{"type":"use_item","itemId":2000002}
```

The bridge permits only the two supported potion IDs, requires a live character
and a positive inventory quantity, then calls Cosmic's ordinary
`UseItemHandler.consumeUseItem`. That handler removes one item and applies its WZ
effect. It may waste a potion used at full HP/MP, just like ordinary use. There is
no separate potion cooldown in that upstream handler; benchmark action limits
remain separate input constraints. Observation and action calls serialize at the
controller so simultaneous requests cannot double-consume one remaining potion.

Loot collection, shops, travel between maps, combo finishers, and character revival
are not implemented in this scenario version. Death should end a trial as gameplay
failure; infrastructure restart is a new attempt, not free revival.

## Scenario configuration contract

Each file in `scenarios/` is a complete task definition:

- `id`, `name`, `description`: stable identifier and model-visible task instructions.
- `preset`, `character_name`, `seed_sql`, `reset`: setup and reset contract. `reset`
  uses database column names including `meso`, `maxhp`, and `maxmp`. IDs are resolved
  at runtime; no host paths, passwords, or real account data belong in task files.
- `map_id`, optional `spawn`: requested map and grounded starting coordinates.
- `demo_mobs`: `true` selects the explicit Henesys fixture; `false` preserves natural
  map spawns. A false value must not make an empty map terminate the hunt.
- `duration_seconds`, `max_action_duration_ms`: gameplay wall-clock and per-action
  limits. API budgets and repetitions are configured at the batch level.
- `allowed_skills`: active attack skill IDs; basic attacks are separate. Passive
  skills are not included. `allowed_items` lists permitted consumables.
- `inventory`: finite starting items as `{item_id, quantity}`. The current runtime
  accepts only White and Blue Potions with quantities from zero to 100.
- `objective`: `{"type":"xp"}` for continuous hunting, or an additional `target_xp`
  for a short clear fixture. Score server XP-gain events, not just the final EXP bar,
  because a level-up can reset that bar.
- `render_map`, `render_character`: names of already baked remote assets. Rendering
  must select the trial's actual map and equipment.

The launcher maps the scenario to `MAPLEBENCH_PRESET`, `MAPLEBENCH_BOT_NAME`,
`MAPLEBENCH_CHARACTER_ID`, `MAPLEBENCH_MAP_ID`, `MAPLEBENCH_DEMO_MOBS`, optional
`MAPLEBENCH_SPAWN_X/Y`, and `MAPLEBENCH_HP_POTIONS/MP_POTIONS`. A fresh server process
resets monsters, drops and transient combat state. The runtime replaces equipped
items and the USE inventory with the preset, sets supported skill levels, and
validates that the database job matches the preset. The runner must reset persisted
stats, learned skills and other character state before loading it.

Damage and spawn scheduling are not yet deterministically seeded. Record upstream
revision, scenario contents, runtime configuration identity,
and action/observation timestamps; run repetitions before comparing models.

## Ground-monster movement

The original server-only clips and batches had stationary monsters. Cosmic's
`MoveLifeHandler` expects coordinates from a connected v83 client; the offline bot
does not supply those packets. Normal respawning and contact damage alone did not
provide locomotion. Treat those older scores as stationary-monster baselines.

`ground-patrol-v1` now supplies an explicit benchmark ground-mob simulation in the
dedicated controlled map. Monsters patrol with staggered pauses, pursue the live
character for six seconds after HP loss, and respect connected foothold slopes,
walls and ledges. They stop for stun, freeze and web effects. Movement updates the
actual server positions used by range and contact-damage checks. Normal spawn and
combat handlers remain responsible for respawn, HP loss and XP.

This controller approximates client behavior: speed is 40 pixels/second at WZ
speed zero, scaled by the WZ speed and SPEED status. For C-1's Roid, WZ speed -40
gives 24 pixels/second. This scale follows Maplewright's patrol baseline and has
not been calibrated against a retail client. Flying mobs, bosses, jumping,
knockback and active monster skill AI are not implemented. The controller yields
when a real player is present. It must not be described as full v83 physics parity.

Observations identify `monsterSimulation: "ground-patrol-v1"` and include each
monster's `moving`, `facingLeft` and `movementMode`. Replays interpolate those
recorded positions and animate the WZ walk/stand frames; they do not invent paths.
Keep trials from different server/JAR versions in separate frozen batches.

The moving-monster Hero check recorded 19 of 20 initial Roids displaced by at
least ten pixels during an eight-second idle observation, with patrol, chase and
boundary-turn states. The subsequent thirty-second scripted hunt earned 5,208 XP,
hit three targets with Brandish, and observed 25 new natural respawn IDs. All mob
positions stayed on the floor, allowing Cosmic's normal one-pixel spawn offset;
fresh-reset inventory, MP and XP checks passed. This is scripted mechanics
validation, not an OpenAI model result.

### Contact damage and replay visibility

Contact damage runs on Cosmic's bot tick, including while the controller is idle.
The server intersects the player's swept foot-position bounds with the monster's
hitbox, rolls physical touch damage, deducts HP, applies eligible knockback, and
starts a 1,500 ms contact-hit cooldown. Visual sprite overlap by itself does not
guarantee another damaging hit: hitboxes, accuracy and that cooldown still apply.

The moving-monster scripted check lost 253 and 244 HP during its opening idle
period, leaving 7,503 of 8,000 HP. Its subsequent Brandish hunt had no further
observed HP loss. The first moving-monster Astra ten-minute run recorded 69 HP
decreases totaling 17,132 HP and 55 recoveries totaling 16,500 HP. All recoveries
matched accepted White Potion actions in the same observation interval; inventory
fell from 100 to 45. Brandish was the only accepted skill and has no HP cost.
These are sampled HP changes, not an exact count of damage rolls.

The older replay drew floating damage only over monsters. The player HUD updated,
but lacked a visible incoming-loss indicator. Updated replays add player HP-loss
and recovery numbers plus a health bar; see [replay semantics](REPLAY.md). This
presentation fix does not change monster damage, HP, cooldowns or potion behavior.

## Evidence and release checks

Live scripted mechanics checks on the natural C-1 map earned 4,200 XP in 55 seconds
with the Crusader and 3,864 XP in 30 seconds with Hero Brandish. They verified real
HP loss, skill costs, new monster object IDs from normal respawns, and finite potion
consumption. Slash Blast affected four observed targets in one action and Brandish
affected three. Fresh-process checks restored full configured potion quantities,
MP and zero XP. These are integration checks with `Model: None (scripted policy)`,
not model-comparison results. Hero was tested after removing persisted inventory so
the equipment-cache correction was exercised on a genuinely fresh character load.
The Beach scenario has been checked against map data but still needs its own live
hunting validation before use in a scored batch.

Data was inspected in these remote, excluded WZ XML files:

- `Map.wz/Map/Map2/261020300.img.xml`, `Map.wz/Map/Map1/104010002.img.xml`:
  map metadata, portals, footholds and natural life spawns.
- `Mob.wz/5110301.img.xml`, `Mob.wz/1210100.img.xml`, `Mob.wz/1210101.img.xml`:
  monster HP, levels, damage and base XP.
- `Skill.wz/100.img.xml`, `Skill.wz/110.img.xml`, `Skill.wz/112.img.xml` and
  `Character.wz/Weapon/01402037.img.xml`: skills and weapon requirements.
- `Item.wz/Consume/0200.img.xml`: exact potion effects.

In pinned Cosmic source, `MapFactory.loadLifeRaw` registers normal spawn points
when `mobTime != -1`; `MapManager.updateMaps`, `MapleMap.respawn` and
`SpawnPoint` implement the ordinary refill schedule while players occupy the map.
`UseItemHandler.consumeUseItem` implements the normal potion-consumption path.
No game data files are distributed in this repository.

Before adding C-1 to a scored batch:

1. Build the modified bridge; boot each preset and verify character name, job,
   starting stats, map and inventory from observations.
2. On C-1, record Roid IDs, defeat at least one, then observe a new object ID of the
   same monster type after a normal spawn update. Check that no demo mobs appeared.
3. Use Power Strike and Slash Blast; confirm accepted attacks reduce actual monster
   HP and consume MP (and HP for Slash Blast). A nearby group should take area damage.
4. Use a potion after damage or MP expenditure. Confirm quantity decreases by one
   and the relevant stat recovers by the WZ amount, capped at its current maximum.
   Invalid IDs and absent inventory must reject without changing stats or quantity.
5. Restart for a new trial and verify stats and potion counts reset exactly. Check
   that the frozen scenario and model identity appear in the replay and results.
6. Run a bounded natural-hunt smoke attempt before enabling full ten-minute trials.


## Advanced Hero cavern (`hero-cave`)

This level 150 Hero has Brandish 30, Combo Attack 30, Advanced Combo 30,
Sword Booster 20, Rage 20, Power Stance 30, Panic 30 and Coma 30, plus the
previous Warrior skills and Sword Mastery 20. Buffs start inactive. The model
casts them through `sdk.useSkill(skillId)`; attacks still require an observed
target. Passive skills cannot be cast. Readiness describes learned levels,
resources and animation locks; it does not promise that a target is in range.

The Cave of Light (`240050300`) is a **controlled quest-map hunting fixture**.
Its fifteen ordinary Skelegon spawn points remain intact: level 110, 80,000 HP,
1,500 base XP, ground y=260. Six one-shot Skelosaurus quest actors (`9300077`)
are explicitly omitted at map load via `excluded_oneshot_monsters`; their active
attack behavior is unsupported. Exclusions only affect the configured map's
one-shot actors (`mobTime=-1`), never ordinary respawn points. Quest progression
and enemy active skill AI are outside this scenario. The existing declared
`ground-patrol-v1` simulation supplies walking, chasing and status immobilization.

Combo Attack builds up to ten charged orbs with Advanced Combo. Recasting Combo
resets its charge; Panic and Coma consume it and reject with zero charge.
Coma can stun several targets. Normal Cosmic handlers apply resource costs,
attack damage, buff effects and stun; the controller does not grant damage or XP.
Stance reduces knockback probability, without preventing incoming HP loss.
The inventory contains exactly 60 Ice Cream Pops (2,000 HP each) and 60 Mana
Elixirs (300 MP each), with no automatic healing, renewal or refills.

Mechanics version `hero-control-v2` also fixes two-handed sword classification in
Cosmic's mastery resolver. A Stonetooth Hero with Sword Mastery 20 now receives
0.60 physical mastery instead of the erroneous untrained 0.10. Earlier C-1
results use older mechanics and are historical baselines, not directly comparable
measures of model improvement.

The score adds actual monster kills, applied HP loss, rolled damage, overkill,
incoming hits/misses, knockbacks, minimum HP, targets per attack, skill/potion use,
maximum combo and buff uptime. Uptime is weighted by observed milliseconds;
gaps over two seconds are unknown and excluded. Observation coverage is reported.
Legacy recordings without the required state retain unknown values, not invented
zeros. Damage and spawn timing still contain randomness; one short trial per
model is a smoke comparison, not a stable ranking.


The final live scripted check started at x=-400 with full 10,000 HP. In 105.247
seconds it killed 40 monsters for 60,000 XP, recorded 45 damaging contacts and
seven knockbacks, and reached ten combo orbs. Both Panic and Coma consumed their
orbs. The minimum observed HP was 53.1%; 52 HP potions and seven MP potions were
consumed, with exact healing and inventory decrements verified. This is scripted
integration validation, not an API model score.

Release checks: 130 focused Java tests, 57 Python tests including all four Docker
isolation tests, and four TypeScript scoring tests passed. A separate baseline
run of upstream `CombatFormulaProviderTest` had three pre-existing formula
assertion failures (Lucky Seven, Dragon Roar, physical skill scaling); those broad
upstream tests are not part of the green focused suite. The new mastery regression
is tested directly in `MapleBenchSkillsTest`.
