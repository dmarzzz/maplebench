# Native critical passives repair

Candidate patch `0010-critical-passives.patch` follows `0008-spell-damage.patch`.
It changes native combat mechanics and needs a new measured client build and
ordinary gameplay qualification. Source tests are not live qualification.
Historical client hashes and run results remain unchanged.

The unfinished client assigned every character a 5% critical chance, ignored
learned Critical Shot/Throw and multiplied critical damage by a fixed 1.5.
The repair resolves a fresh per-attack profile from current learned skills:

| Passive | Eligible attack | Maximum level | Chance | WZ damage | Added critical damage |
| --- | --- | --- | --- | --- | --- |
| Critical Shot, 3000001 | Bow/crossbow projectile, including basic shots | 20 | 40% | 200% | +100% |
| Critical Throw, 4100001 | Claw projectile, including basic throws | 30 | 50% | 200% | +100% |

Unlearned skills, wrong weapons and melee fallback have no passive critical.
Skill removal and weapon switching take effect on the next attack, without
cached buff state. Lower learned levels use their actual asset values, including
Critical Shot level1 prop12/damage105 and Critical Throw level1 prop21/damage113.
These numeric definitions were compared in pinned NX and XML; game assets are
not part of this repository.

The repair also moves ordinary physical skill multiplication after defense.
For a successful hit, the existing defended random base is multiplied by
`(skill damage percent + critical bonus percent) / 100`. The bonus is zero on a
noncritical hit. Thus Triple Throw150% with a +100% critical uses250%, rather
than300%. Basic attacks use100%. This order is supported by the original
[pre-Big-Bang formula research](https://www.southperry.net/showthread.php?tid=1033),
which separately describes critical addition and Arrow Bomb's exception.
Integer percentages preserve asset values through the existing float loader.

Arrow Bomb's splash damage modifies the base range before defense; its critical
then uses100% plus the passive bonus. The test composes the actual asset-loader
expression from `0011-arrow-bomb-power.patch` to obtain130% from the native x
field. Distinct Arrow Bomb impact and splash targeting is still missing and is
not claimed by this repair.

Magic and fixed-damage attacks ignore the physical coefficient and passive
critical bonus. Existing defense functions, hit-chance logic, damage floor and
cap remain unchanged. Sharp Eyes, other critical passives and special skill
critical behavior are not implemented here. The separate candidate `0012-claw-skill-base.patch` supplies Lucky Seven/Triple
Throw's special LUK range, as described below. Coefficient tests alone do not
qualify their complete damage semantics.

`test/test_full_client_critical_passives.py` compiles pinned public C++ methods
for Player attack preparation, Skill application and Mob damage, before and
after the repair. It checks learned-skill and weapon gates, skill removal,
nonzero-defense results for basic/Strafe/Triple Throw/Brandish/Rush attacks,
Arrow Bomb's loader and critical exception, magic/fixed isolation, misses,
truncation and the existing damage bounds. Numeric storage and RNG are inert;
there is no server, model request or benchmark result in this test.

## Lucky Seven and Triple Throw base range

Candidate `0012-claw-skill-base.patch` follows0010. The same original formula
research specifies a base minimum of `LUK * 2.5 * WATK / 100` and maximum of
`LUK * 5.0 * WATK / 100` for Lucky Seven4001344 and Triple Throw4121007. Their
skill and critical coefficients are then applied through0010's damage path.

Player attack preparation copies current total WATK and marks whether this is
a ranged claw attack. Inventory's existing stat calculation already includes
the selected projectile's weapon attack. Skill application replaces the base
range only for those two skill IDs with that weapon/attack gate. The special
range is independent of STR, DEX and ordinary weapon mastery. Normal claw
throws, other skills, wrong weapons and melee fallback retain their prior
base range. Magic remains on the independent spell branch.

The compiled regression exercises0010 alone and0010+0012, including both skill
IDs, LUK/WATK sensitivity, ordinary-range perturbations representing STR/DEX,
weapon/ammunition/prone gates, nonzero defense, critical addition and magic
isolation. It uses the production Player/Skill/Mob methods with inert stat
storage. This remains source verification; server interaction and native
recordings must qualify the newly built client separately.
