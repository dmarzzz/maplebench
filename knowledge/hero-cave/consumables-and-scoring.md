# Consumables and scoring

## Finite consumables

You start with exactly this, once, at startup. `[scenario]`

| Item | ID | Effect | Quantity | Source |
| --- | --- | --- | --- | --- |
| Ice Cream Pop | `2001001` | Restores 2,000 HP | 60 | `[scenario]` `[unconfirmed]` mapping of ID to name |
| Mana Elixir | `2000006` | Restores 300 MP | 60 | `[scenario]` `[unconfirmed]` mapping of ID to name |

`allowed_items` is exactly `2001001` and `2000006`. `[scenario]`

**Nothing replenishes these during a run, and nothing heals you automatically.**
You must explicitly choose to use a potion. `[scenario]` `[repo]`

Budget them against the run length. 60 Ice Cream Pops is 120,000 HP of healing
against a 10,000 max-HP pool; 60 Mana Elixirs is 18,000 MP against a 2,500 pool.
MP is the tighter constraint relative to costs: Brandish is 25 MP a cast, Sword
Booster costs 10 HP + 10 MP each time it is refreshed. `[scenario]` `[repo]`

Observations report per-item `quantity` along with restore amounts, so read your
remaining supply rather than counting casts. `[repo]`

## How you are scored

**Signed persisted net XP**: final persisted EXP minus initial persisted EXP, read
from the database while the account is offline, before and after the run. `[repo]`

What that means in practice:

- It **includes death penalties**. Dying costs you score.
- It **accepts zero** and **preserves negative** results. A valid bad outcome is
  recorded as a bad outcome, not discarded.
- **Gross XP, monster kills, damage dealt, and whether you survived the whole run
  cannot be inferred** from two snapshots. Only the net change is scored.
- `alive_at_logout` describes **final HP only** — it does not mean you never died.

Survival matters instrumentally: dying costs XP and costs time. It is not scored
separately.

## Level must not change

The persistence scorer (schema 1) requires the level to stay unchanged and
**rejects** a run that crosses a level boundary rather than reporting the rollover.
`[repo]`

This is not a practical constraint at this fixture. The character starts at level
150 with EXP 0, and reaching 151 requires **117,809,740** XP. A Skelegon gives
1,500 base XP, so the boundary is roughly 78,500 kills away. `[repo]`

Play for maximum XP. You will not accidentally invalidate the run by levelling.

## The clock

Time spent waiting for a model response is live game time — the game does not
pause. Actions already in flight may keep earning XP during that wait.
`[scenario]`

Planning is not free, and neither is over-planning. Get a working attack loop
producing non-zero XP first, then improve it.
