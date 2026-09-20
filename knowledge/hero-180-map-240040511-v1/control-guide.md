# Control guide

The accepted `sdk.pressKeys` names are `LEFT`, `RIGHT`, `UP`, `DOWN`, `JUMP`,
`ATTACK`, `HP_POTION`, `MP_POTION`, and the 17 skill slots below. A call holds
one to three distinct names for 30–1500 ms. Do not
combine `LEFT` with `RIGHT` or `UP` with `DOWN`. Physical letters, key codes,
numeric skill IDs, and skill names are rejected as controls. `[protocol]`

The frozen Hero-180 slot mapping is:

| Slot | Mapped action |
| --- | --- |
| `PRIMARY_SKILL` | Brandish |
| `SECONDARY_SKILL` | Combo Attack |
| `BUFF_1` | Sword Booster |
| `BUFF_2` | Maple Warrior |
| `SKILL_5` | Rush |
| `SKILL_6` | Sword Coma |
| `SKILL_7` | Sword Panic |
| `SKILL_8` | Power Stance |
| `SKILL_9` | Rage |
| `SKILL_10` | Power Guard |
| `SKILL_11` | Enrage |
| `SKILL_12` | Hero's Will |
| `SKILL_13` | Shout |
| `SKILL_14` | Armor Crash |
| `SKILL_15` | Iron Body |
| `SKILL_16` | Power Strike |
| `SKILL_17` | Slash Blast |

These mappings say what each slot requests. They do not claim that a cast lands,
a buff activates, an attack deals damage, or a potion is available. Only a fresh
accepted action receipt plus native outcome evidence can establish those facts.
`sdk.observe()` reports character position, HP, MP, EXP, level, life state and map,
plus monster object IDs and positions. It does not report buff state, combo orbs,
cooldowns, monster HP, damage rolls, or inventory. After activating Combo Attack,
treat landed attacks as charge-building opportunities. Coma and Panic consume
that inferred charge; rebuild with landed attacks between finishers.

Useful conservative loop:

1. Observe. Confirm the character is alive, still on map `240040511`, and note
   nearby monster positions and current HP/MP.
2. Face or move toward nearby monsters with short holds. Re-observe rather than
   assuming a movement receipt means the character reached a destination.
3. Try a mapped attack with enough time for its animation, then re-observe EXP,
   HP/MP, position, and the monster list. Repeat what produces XP.
4. Treat buffs and potions as explicit experiments. Do not spam them merely
   because a slot exists; a release qualification result has not yet established
   every mapped cast or consumable on this fixture.
5. Keep enough HP and wall time to avoid turning positive XP into a death penalty.

`sdk.wait(1..3000)` and `sdk.observe()` consume SDK-request budget. Programs are
not replayed or repaired, and local variables do not survive the next model
response. `[protocol]`

Sword Mastery 20, Advanced Combo 30, Achilles 30, Final Attack: Sword 30,
Improved HP Recovery 5, Improved Max HP Increase 10, and Improved MP Recovery 11
plus Axe Mastery 1 are declared learned passives; they have no input slots. Axe
Mastery is inactive with the equipped sword and only accounts for the remaining
second-job point. The chosen active and passive levels consume 61 first-job SP,
121 second-job SP, 151 third-job SP, and 183 fourth-job SP. No beginner skill
allocation is declared. Monster Magnet is unavailable because its target-selection
packet is absent from the physical-client route. Guardian is unavailable because
this fixture uses a two-handed sword and no shield. Axe and shield variants are
incompatible with the fixed equipment. The native release receipt qualifies the
original core ten only; `SKILL_11` through `SKILL_17` are available controls whose
effects remain unqualified. `[toolkit]`
