# Map and monsters

## Cave of Light — map `240050300`

The Cave of Life quest map. `[scenario]`

| Property | Value | Source |
| --- | --- | --- |
| Spawn | `x = -400`, `y = 260` | `[scenario]` |
| Usable bounds | `x` from `-430` to `1900`, `y` fixed at `260` | `[scenario]` |
| Floor | One connected floor at `y = 260` | `[scenario]` |
| Render map | `cave-light` | `[scenario]` |

`min_y` and `max_y` are both 260, so the whole fixture is **one continuous
horizontal floor**. There are no ladders or platform jumps to solve, and no
vertical navigation is required or possible within bounds. You spawn at the left
edge (`x = -400`, 30 units inside the left bound) before entering the monster
pack. `[scenario]`

This choice is deliberate: a single connected floor reduces the effect of the
known upstream navigation-precision failure while keeping normal movement and
contact damage. `[repo]`

## Skelegon — the target population

| Property | Value | Source |
| --- | --- | --- |
| Count | 15 ordinary respawning Skelegons | `[scenario]` |
| Level | 110 | `[scenario]` |
| HP | 80,000 each | `[scenario]` |
| Base XP | 1,500 each | `[scenario]` |
| Controller | `ground-patrol-v1` | `[scenario]` |
| Damage to you | Contact damage only | `[scenario]` |

**Active monster skills are not simulated.** Skelegons patrol the ground and
damage you on contact; they do not cast. `[scenario]`

80,000 HP against Brandish at 260% × 2 hits means a Skelegon is a multi-hit
target, not a one-shot. Area attacks that strike several at once (Slash Blast up
to six, Brandish up to three, Coma across an area) matter more than they would
against low-HP mobs.

## Excluded actors

Six **Skelosaurus** quest actors (`9300077`) are explicitly excluded at map load,
because their active attack/controller behavior is unsupported. Quest progression
is outside this fixture. `[scenario]`

You will not see them. Do not plan around them.

## Population is not guaranteed

Actual population and XP are affected by server configuration, which is recorded
with the batch. A fixture does not claim that exactly fifteen monsters will always
be visible. **An empty observation during a natural hunt is a reason to wait or
move — it is not a successful terminal condition.** `[repo]`

Respawn timing, monster positions and combat RNG are not asserted to be identical
between runs, even from an identical database baseline. `[repo]`

## Time

`duration_seconds` in the fixture is 600, but **the active protocol's horizon
governs** — check your declared budget rather than assuming 600 seconds.
`[scenario]`

Model latency counts as live game time. The game continues while you wait for a
response, and actions already running may continue to earn XP. `[scenario]`
