# Live client adapter: findings for the benchmark contract

A second adapter was built against a **live MapleLegends client** (closed
binary, no server access) to test the MapleBench observation and action
contracts against something that is not the Cosmic bridge. It drives the game
the way a person does: reads the rendered frame, posts key and mouse events.
No client patching, no memory access, no protocol manipulation.

This adapter is **not a benchmark scoring path**. Its readings are
screen-derived and not server-authoritative. It exists to answer one question:
*what does the current contract silently assume about having a server?*

Scripts: `scripts/legends_window.py`, `legends_input.py`, `legends_calibrate.py`,
`legends_state.py`, `legends_play.py`, `legends_bot.py`.
Tests: `test/test_legends_gauges.py` (8 tests, no client needed).

## Measured episode

One 4.91-minute session, level-3 Beginner, Maple Road, blind walk-and-swing
policy (walk a leg, swing on a timer, tap loot, reverse every third leg).

| Quantity | Value |
| --- | --- |
| Wall clock | 4.91 min |
| Server-visible XP (client display) | 38 -> 53 = **15 XP** |
| XP rate | 3.05 XP/min |
| Level bar gained, adapter estimate | 0.2703 |
| Level bar gained, ground truth | 0.2632 |
| **XP estimate error** | **+2.7% relative** |
| Observations | 104, 0 unreadable |
| Perception total | 39,815 ms (**383 ms per observation**) |
| Action total | 235,250 ms |
| Perception share of wall clock | 14.5% |
| Swings / turns / potions | 312 / 34 / 0 |

Gauge accuracy against the client's own numeric readout:

| Gauge | Adapter | Client | Error |
| --- | --- | --- | --- |
| HP | 0.641 | 50/79 = 0.633 | +1.3% |
| MP | 1.000 | 28/28 = 1.000 | 0 |
| EXP | 0.6667 | 66.66% | +0.01% |

## Findings

### 1. The Observation contract is unsatisfiable without a server

`Observation` requires `EntityId` for the character, every monster, and every
drop, plus absolute `exp`, `mesos`, `mapId`, and `position`. From pixels this
adapter can supply only HP, MP, and EXP **as fractions of their bars**. There
are no object ids on screen at all.

That is not a gap in the adapter. It is the contract assuming server
authority. Three of the eight actions are addressed by id and are therefore
unreachable from a screen: `basic_attack(targetId)`, `use_skill(skillId,
targetId)`, `loot(dropId)`.

**Proposal.** Give tasks an explicit observation profile rather than one
implicit level of privilege. A `human-equivalent` profile would expose only
what is rendered and replace id-addressed actions with direction-addressed
ones (`attack_facing`, `loot_nearby`). The interesting benchmark question --
*how much of an agent's score comes from privileged state?* -- cannot be asked
while there is only one profile. See the proposed types in `src/protocol.ts`.

### 2. `ActionResult.accepted` is unfalsifiable off-server

The screen adapter cannot know whether an action was accepted. Worse, it
cannot know whether the key even reached the game: the client keeps a chat
field at the bottom of the window, and while that field holds focus every
hotkey becomes a **public chat message** instead of an action. A bot tapping
its loot and potion keys spams world chat and gets the account banned, while
every `accepted: true` it reports is a lie.

The adapter now clicks the viewport to drop chat focus and then **verifies
actuation** -- walk briefly, require the frame to change -- before trusting a
single measurement.

**Proposal.** Require adapters to declare whether `accepted` is authoritative
or best-effort, and record that in the episode header. A run whose acceptance
signal is best-effort is not comparable with one whose is authoritative.

### 3. Perception latency belongs in the contract

Each observation costs **383 ms** on this adapter, against a cheap in-process
call on the Cosmic bridge. At a 1 Hz observe-act loop that is 38% of a
10-minute episode spent looking rather than acting.

`tasks/maximize-xp-10m/prompt.md` already tells the agent that "wall-clock
game time includes model/API latency; the game is live while you think."
The same is true of perception, and it is adapter-dependent by two orders of
magnitude. Comparing scores across adapters without recording observation cost
compares plumbing, not policy.

**Proposal.** Record per-observation latency in the episode and report it
beside the score. Consider a per-episode observation budget so a policy cannot
buy score with observation frequency the adapter happens to make cheap.

### 4. Absent state is not zero state

During a map transition the client draws no status bar. Counting gauge pixels
returns zero, which reads as **0% HP**. The first live run aborted on its HP
floor at a moment when the character was at full health, standing still.

This generalises past this adapter. Any observation channel needs to
distinguish *absent*, *unreadable*, and *genuinely zero*. `Observation` today
has no way to say "this field was not observable on this tick" -- every field
is required and typed as a number.

**Proposal.** Make the weaker profile's fields nullable and add an explicit
`observable: false` state, so a policy can tell "HP is 0" from "HP unknown".
A benchmark that cannot express uncertainty trains agents to trust stale
readings.

### 5. A scripted live-client baseline

**3.05 XP/min** for blind walk-and-swing at level 3. Useful only as a floor,
and the floor is very low precisely because the policy has no monster
positions -- it is a random walk that swings on a timer. The distance between
this and a targeting policy is the thing worth measuring, and it is invisible
if the only adapter hands the agent monster coordinates for free.

## What this cost to get right

Four defects, each of which would have produced confident and wrong numbers.
Recorded because they are the failure modes a vision-based adapter invites,
not because they were interesting individually.

1. Fill fraction stopped counting at the first unfilled pixel, so every gauge
   read 100% and the potion logic could never fire.
2. Track extension assumed the empty track was darker than the UI chrome. It
   is lighter (190,190,190 against 45,51,57). The walk ran off the gauge.
3. `cliclick` holds modifiers only, so arrow keys could be tapped but never
   held -- the character could turn but not walk. Replaced with CGEvent
   key-down/key-up, which is what `move_to` would need anyway.
4. Absent status bar read as 0% HP (finding 4 above).

Only the first was caught by unit tests written in advance; the rest needed
either a real frame or a real episode. A synthetic fixture built from guessed
colours confirms the guesses, not the client.

## Not done

- No monster, drop, or position perception. Sprite detection is the next
  meaningful capability and would make the human-equivalent profile real
  rather than hypothetical.
- No absolute XP. The client renders it as text; template-matching the bitmap
  digits would give exact values instead of a bar fraction.
- Level is not read, so the level-up bar wrap is inferred from a backwards
  jump rather than observed.
