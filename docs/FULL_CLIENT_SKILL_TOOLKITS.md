# Expanded class toolkit candidate

The `full-client-training-v2` recipe opts into the frozen
`full-client-skill-toolkit-v1` policy. The existing 300-second
`full-client-adaptive-pilot-v1` controller envelope stays intact. Policy/profile,
fixture, prompt and source hashes separate these trials from previous four-slot
pilots. Existing native v1–v4 contracts and program bytes are unchanged.

This implementation has source and synthetic regression coverage. **The new
toolkits are not live-qualified.** No old four-slot acceptance can establish
that added skills, resources or the new compiled client work correctly. A new
WASM build, exact runtime NX/XML parity, ordinary login/bindings, native effects,
saved resources and reviewed recording remain release gates.

## Controls and declared kits

Movement, Jump, Attack and Q/W potion keys retain their meanings. Skill bindings
use ordinary keymap type 1. Ctrl Attack and Space Jump use type 5. All ten skill
keys avoid movement and potion scancodes. Added keys are admitted only with the
exact canonical toolkit policy; undeclared slots are rejected at both SDK and
browser dispatch boundaries.

| SDK slot / physical key | Hero | Bowmaster | Ice/Lightning | Night Lord |
|---|---|---|---|---|
| PRIMARY_SKILL / A | Brandish | Hurricane | Chain Lightning | Triple Throw |
| SECONDARY_SKILL / S | Combo Attack | Arrow Rain | Teleport | Avenger |
| BUFF_1 / D | Sword Booster | Soul Arrow | Magic Guard | Claw Booster |
| BUFF_2 / F | Maple Warrior | Sharp Eyes | Spell Booster | Haste |
| SKILL_5 / G | Rush | Strafe | Ice Strike | Drain |
| SKILL_6 / H | Sword Coma | Arrow Bomb | Thunder Spear | Lucky Seven |
| SKILL_7 / Z | Sword Panic | Bow Booster | Blizzard | Maple Warrior |
| SKILL_8 / X | Power Stance | Maple Warrior | Meditation | Meso Up |
| SKILL_9 / C | Rage | Hamstring | Maple Warrior | Unmapped |
| SKILL_10 / V | Power Guard | Inferno | Magic Armor | Unmapped |

The model receives names, learned levels, native roles and concise usage
constraints. It executes its own code without helper invocation repair, hidden
buffing, automatic combat or resource refill. A delivered key is not evidence
that the skill cast, hit, healed, moved or changed a buff.

The client attack table previously omitted Strafe, Arrow Bomb, Inferno, Ice
Strike, Thunder Spear and Blizzard. The separate
`0006-training-toolkit-attack-flags.patch`, applied after patch 0005, routes these
through the existing target/effect/attack-packet path. Drain is classified as a
ranged attack. Buffs retain ordinary skill-use packets. The focused C++ test
compiles actual pinned Journey classification and Combat dispatch methods with
inert collaborators; it checks new attacks and all declared buff routes. It
does not establish server damage or native rendering.

## Offline fixture preparation

`full_client_skill_definitions.py` reads the local `Skill.nx`, `Item.nx` and
matching Cosmic XML. It follows prerequisite skill levels, compares numeric
effect and requirement fields, and records source hashes. It exports scalar
metadata; it never exports bitmap/audio assets or connects to a game/database.

`full_client_toolkit_fixture.py` requires hashes of private input SQL and the
matching parity report. Its input must already contain one offline character of
the selected class with its ordinary class weapon. It writes a new private
fixture directory; it never executes SQL. Account fields and equipped items are
preserved byte for byte. Learned skills include prerequisites, keymaps contain
the actual skill IDs, and all changes are restricted to four INSERT value spans.
The input's ordinary equipment requirements still need independent validation.

The new resource fixture starts alive at full 12,000 HP. Mage starts with 16,000
MP; the other classes start with 6,000 MP. The preparer checks spell costs,
including Mage amplification, against MP capacity. Both Q and W consume the
same supply of 100 real Power Elixirs; this shared resource behavior is explicit
in the prompt. Bowmaster receives four stacks of 2,000 ordinary arrows as well
as Soul Arrow. Night Lord receives 23 stacks of 800 Ilbi stars. Stacks must fit
the verified item definitions and the prepared use inventory fits 24 slots.
Finite supplies can run out; duration alone does not promise enough ammunition.

The baseline should be restored only by the existing lock-owning lifecycle
adapter with Cosmic stopped. After ordinary logout, compare saved **logical
item/slot/quantity**, skill levels and keymap rows; normal saving can regenerate
database row IDs. Archive exact native resource changes, never infer them from
SDK action counts. The ordinary character-only XP snapshot is insufficient to
qualify ammunition and potion persistence.

## New native evidence contract

`contract(class_id, baseline_hash,
protocol='scripted-native-toolkit-acceptance-v1')` returns a separate exact
profile/toolkit contract: 60 seconds, 32 input actions, 180 SDK requests, and a
75-second recording ceiling. The finite recipe checks Jump, casts declared
buffs, approaches a nearby platform target, attempts every mapped skill and a
potion, and retains observations. Hero gets fresh ordinary contact opportunities
between Coma and Panic because each consumes combo orbs. Teleport follows the
offensive casts. The recipe never awards a score or declares an effect successful.

Native qualification must bind the exact policy and baseline hash and inspect
each declared skill: native animation and server contact for attacks; visible
and server-backed buff/resource effects; actual displacement for movement; and
ordinary persisted resource changes. Keep a per-skill acceptance matrix so a
single successful Brandish/Hurricane cast cannot certify an expanded kit.

For this opt-in toolkit only, the native XP owner also collects three bounded,
consistent READ ONLY USE-inventory snapshots under its existing maintenance
locks: `inventory_before_login` after the initial baseline restore,
`inventory_after_logout` after the ordinary saved disconnect, and
`inventory_after_restore` after stopped-server restoration. These artifacts are
required in the final backend/complete receipt. The earlier XP manifest stays
unchanged because final restoration has not happened when it is written.

The final gate rechecks all three receipts against the exact baseline SQL,
native/toolkit/runtime identities and session timestamps. Before and restored
rows must match that baseline. Ordinary logout may regenerate row IDs; saved
consumption is compared by item and inventory slot. Supplies may decrease or
disappear when exhausted; increases, new consumables and moved stacks fail the
gate. Qualification requires positive saved Power Elixir use and, for Night
Lord, positive saved star use. Soul Arrow can legitimately preserve Bowmaster's
physical arrows. Counts never establish an attack count, hit or XP award.
The resource proof and raw receipt hashes are bound into the final visual
review, including an observed potion-effect interval. Cleanup independently
checks exact inventory restoration even when the original run had no effect.

This inventory path has synthetic collector, lifecycle and publication-gate
tests. No live inventory transaction has been qualified by those tests.

## Known omissions and port limitations

- Hurricane remains discrete native casts. Authentic continuous channeling is
  not implemented by this toolkit, and scores must keep that caveat.
- Night Lord Flash Jump currently reaches an empty movement switch branch.
  The accepted runtime's asset displacement and physics behavior must be read
  and implemented before it is bound; this change does not invent a jump force.
- Shadow Partner hit duplication and Shadow Stars ammunition exemption are
  absent from this client path. Neither is granted or bound.
- Summons such as Puppet, Phoenix and Ifrit require their own native AI and
  packet/effect acceptance. They are excluded. Ice/Lightning's summon is Ifrit;
  Elquines belongs to Fire/Poison in the pinned server definitions.
- Big Bang charge/release and Monster Magnet target-selection behavior are
  excluded. This remains a declared training kit, not complete class emulation
  or a balanced cross-class ranking.

The definition audit uses the Cosmic revision in `upstream.lock.json`
(`b01cf27833f568cde52a0a70a38532474eedd4d9`), including its `constants/skills`,
`StatEffect`, `SpecialMoveHandler` and ordinary attack handlers, plus the pinned
Journey Combat/SkillData sources. Runtime NX parity is separate from this source
audit. Credentials, runtime dumps, raw reports and game assets stay outside Git.
