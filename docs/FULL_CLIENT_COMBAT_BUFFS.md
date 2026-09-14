# Combo and physical Sharp Eyes damage

Candidate `0017-combat-buff-semantics.patch` follows the complete0016 client.
It requires a fresh measured build and live qualification. Historical recordings,
protocols and client identities retain their original meaning.

Combo and Sharp Eyes already arrived through ordinary buff packets, but the
native attack producer ignored both. `ActiveBuffs` has no handlers for them;
`PassiveBuffs` also does not implement Advanced Combo. Putting these effects
into `CharStats` would modify the base range before defense and could cache
stale skill/buff state. This patch instead derives an attack-local coefficient
from the received buff and current learned levels.

## Formula evidence

The original [pre-Big-Bang formula compilation](https://www.southperry.net/showthread.php?tid=1033)
places Combo and finishers on the skill coefficient, after defense and before
additive critical damage. For one through five orbs, it adds
`floor((orbs − 1) × ComboLevel / 6)` percentage points to the skill's first-orb
percentage; beyond five, it adds20 plus4 per additional orb. The original
[Combo experiments and Advanced table](https://www.southperry.net/showthread.php?pid=5870&tid=666)
support Advanced level1 starting at121%, and level30 rising from150% at one orb
to190% at ten. Panic/Coma multiply by1,1.2,1.54,2 or2.5 for one,two,three,four,
or at least five orbs respectively.

The [original physical Sharp Eyes observation](https://www.southperry.net/showthread.php?pid=27424&tid=1033)
distinguishes its physical bonus from the skill description: maxed Sharp Eyes
adds140 percentage points; it combines with the existing100-point Critical
Shot/Throw bonus. It is not a multiplier of the whole attacking skill.

These are source and historical formula references, not a claim of a newly
measured native-client formula trace. Earlier discussion contains conflicting
low-level Combo proposals; this implementation follows the later consolidated
formula and the explicit Advanced table. Lower-level live checks remain pending.

## Server authority and native behavior

The matching Cosmic source provides packet/state semantics, separately from its
anti-cheat allowance:

- `StatEffect.loadFromData` publishes Combo as count1 and Sharp Eyes as
  `(x << 8) | y`. Count1 means zero accumulated orbs.
- `CloseRangeDamageHandler.applyCloseRangeEffects` grants ordinary and Advanced
  extra orbs and caps them using the learned skill's `x`. It sends the new count.
- `Character.handleOrbconsume` sends count1 when finishers consume their orbs.
- Client `ApplyBuffHandler`, `Player.give_buff` and `cancel_buff` store and clear
  those received values. This patch does not increment or consume them locally.

Combo uses the current native `damage` and `x` level fields. Advanced requires
learned Combo30 and a learned Advanced level; otherwise the normal Combo level
applies. Current sword/axe close attacks receive the coefficient. A cancellation,
weapon switch, skill removal or new received count affects the next attack.
A prior count is bounded by the current learned capacity. Missing/invalid native
level fields grant no multiplier. Panic and Coma require a received nonzero orb
count before the existing job, learned-skill, weapon and resource checks.

Physical Sharp Eyes accepts the normal Bowmaster/Marksman buff source IDs,
including a received party buff. Its high byte adds critical probability,
bounded at100%; the low byte adds critical damage percentage points. Passive
critical weapon/projectile gates remain intact. A maxed Bowmaster therefore
has55% critical chance and a240-point critical bonus. Reapplying or cancelling
the buff does not accumulate a cached bonus.

`Mob` uses `(skill_percent × combo_and_finisher_multiplier + critical_bonus)`
after its existing defense calculation. Fractional finisher coefficients survive
until the ordinary final damage truncation. Magic and fixed damage do not use
these physical modifiers. The existing Arrow Bomb splash exception, damage floor,
cap and hit-chance calculation are unchanged. Cosmic's `CombatFormulaProvider`
explicitly follows anti-cheat headroom; its extra50-point Combo allowance and
placement of small additive terms are not copied into the native formula.

## Verification and remaining work

`test_full_client_combat_buffs.py` applies the complete patch with zero fuzz to
new hash-pinned production sources. It compiles the real receive/cancel methods,
Player admission/attack preparation, Skill application and Mob damage, using
real `Buff`, `Attack` and `EnumMap` types. Numeric NX/stat storage and RNG are inert.
Six tests reproduce the old missing-buff behavior and verify current buff order,
cancellation, party receipt, selected low/max levels, capacity, weapon switching,
all four finisher IDs, zero-orb rejection, nonzero-defense results, fractional
coefficients, magic/fixed isolation, misses and damage bounds.

Live qualification must still prove received orb progression and reset, accepted
normal/finisher hits, and physical critical damage with the new binary. Combo orb
visuals, magic Sharp Eyes, Stun Mastery, other jobs' Combo skills, and complete
class skill coverage are not implemented or qualified by this patch. New monster
status support must independently qualify Panic/Coma status effects. No model
request, SDK policy, fixture SQL, scoring rule or runtime is changed here.
