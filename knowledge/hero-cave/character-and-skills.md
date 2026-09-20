# Character and skills

## The build

| Property | Value | Source |
| --- | --- | --- |
| Name | `AgentHero` | `[scenario]` |
| Job | 112 (Hero) | `[scenario]` |
| Level | 150 | `[scenario]` |
| STR / DEX / INT / LUK | 600 / 120 / 4 / 4 | `[scenario]` |
| HP / MP | 10,000 / 10,000 max · 2,500 / 2,500 max | `[scenario]` |
| EXP at start | 0 | `[scenario]` |
| Meso | 1,000 | `[scenario]` |
| Weapon | Stonetooth Sword `1402037`, two-handed sword (type 140) | `[scenario]` `[repo]` |

Stonetooth's WZ requirements are level 100 and DEX 120; its default weapon attack
is 101. `[repo]`

This is an explicit benchmark build. It does not imply completed job-advancement
quests or a complete player skill build. `[repo]`

## Invocable skills

These nine IDs are the only skills you may use — they are the fixture's
`allowed_skills`. `[scenario]`

| ID | Skill | Role | Notes |
| --- | --- | --- | --- |
| `1001004` | Power Strike | attack | Single target. At level 20: 12 MP, 260% damage. `[repo]` |
| `1001005` | Slash Blast | attack | Up to **six** nearby targets. At level 20: 16 HP + 14 MP, 130% damage. `[repo]` |
| `1121008` | Brandish | attack | **Two hits of 260% each**, up to **three** targets, 25 MP at level 30. WZ actions `brandish1` / `brandish2`. Does not require an active Combo buff. `[repo]` |
| `1111003` | Panic | finisher | Single-target. **Consumes all charged combo orbs.** `[scenario]` `[unconfirmed]` |
| `1111005` | Coma | finisher | Area finisher, **chance to stun up to six monsters**. Consumes all charged orbs. `[scenario]` `[unconfirmed]` |
| `1111002` | Combo Attack | buff | Accumulates up to **ten** orbs. **Recasting resets the charge.** `[scenario]` |
| `1101004` | Sword Booster | buff | Speeds attacks. Costs **10 HP + 10 MP**. `[scenario]` |
| `1101006` | Rage | buff | Attack buff. `[scenario]` |
| `1121002` | Power Stance | buff | Reduces **knockback, not damage**. `[scenario]` |

### Buffs start inactive

All four buffs — Combo Attack, Sword Booster, Rage, Power Stance — begin inactive
and require an explicit cast. Nothing casts them for you and there is no
autonomous buff upkeep. `[scenario]`

The fixture's `self_buff_skills` list is exactly `1111002`, `1101004`, `1101006`,
`1121002`. `[scenario]`

### Combo and finisher interaction

Combo Attack charges up to ten orbs. Panic spends all of them on one target;
Coma spends all of them across an area with a stun chance on up to six monsters.
Recasting Combo Attack resets the charge to zero — so recasting a running Combo
buff throws away banked orbs. `[scenario]`

### Learned passives — present but not invocable

The fixture's prose describes the character as having **Sword Mastery** level 20
and **Advanced Combo** level 30. Neither appears in `allowed_skills`, because both
are learned passives rather than actions. Sword Mastery is `1100000`. `[repo]`

> **Discrepancy worth knowing:** the fixture prose names nine skills (Sword
> Mastery, Brandish, Advanced Combo, Combo Attack, Sword Booster, Rage, Power
> Stance, Panic, Coma) while `allowed_skills` carries a different nine — it omits
> the two passives and adds Power Strike `1001004` and Slash Blast `1001005`,
> which the prose never mentions. Treat `allowed_skills` as authoritative for what
> you can invoke. `[scenario]`

MapleBench fixes the pinned upstream mastery lookup for two-handed sword type
140; results before mechanics `hero-control-v2` lacked that correction. `[repo]`

No automatic Final Attack and no autonomous buff casting is enabled. `[repo]`

## What still applies

Normal weapon damage, accuracy, defense, attack locks and range checks all apply.
`[repo]` Observe current skill costs, readiness, active buffs and remaining
durations rather than assuming them. `[scenario]`

`max_action_duration_ms` is 1,500. `[scenario]`
