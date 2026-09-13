# Spell damage candidate

`0008-spell-damage.patch` repairs an identified client defect: `Player` provided
the physical weapon range, `Skill` stored spell power in `Attack.matk`, and `Mob`
never used that spell power. Chain Lightning and Blizzard consequently shared
the same weapon-derived range despite different native spell powers. An MP
change or visible damage number did not establish that spell mechanics were
correct.

The patch provides INT, LUK and total magic attack to the spell calculation.
Total magic is INT plus equipment/buff MAGIC; INT is added once. Skill power
(`mad`) and mastery come from the existing skill loader. Native mastery is a
five-percent tier above ten percent: tier 10 means 60%, as confirmed by the
pinned spell descriptions. Learned explorer Element Amplification uses its
damage field `y`; ordinary server effects continue charging the MP field `x`.

The maximum base and amplification rounding follow the pinned Cosmic
`CombatFormulaProvider.magicDamageBase` and the ordinary magic parser's ceiling:

```
max_base = ceil((Magic² / 1000 + Magic) / 30 + INT / 200)
min_base = ceil((Magic² / 1000 + Magic × mastery × 0.9) / 30 + INT / 200)
range = floor(base × amplification_percent / 100) × spell_power
```

The client uses its existing magic-defense deductions and damage-line serializer.
Spell accuracy uses INT/LUK and the level/avoidability calculation from that same
server reference. Ordinary spells no longer inherit the client's universal
physical critical chance. Physical attacks, staff basic attacks and fixed-damage
skills retain their existing paths.

For the regression fixture (INT 757, equipment MAGIC 140, mastery 60%,
amplification 140%), Chain Lightning's pre-defense range is 11,700–15,300.
Those are deterministic formula test values, **not observed gameplay damage or
benchmark results**. The compiled test reproduces the old defect, then checks
the actual producer/consumer methods, magic equipment and INT changes, spell
power differences, amplification, accuracy, defense, and unchanged physical and
fixed-damage branches.

This patch still needs a combined WASM build and productive native combat,
ordinary logout/save, and restore verification. It does not implement full
elemental/status semantics, summons, charged skills, or certify canonical v83
parity. The baseline must freeze the exact client source/binary and advertise
the verified capability set. Historical recordings and scores remain unchanged.
