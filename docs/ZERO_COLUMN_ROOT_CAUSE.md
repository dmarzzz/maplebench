# Why the Bowmaster and Ice/Lightning columns scored zero

Investigation dated 2026-09-20, into the three four-model cohorts run on
2026-09-08 under `full-client-adaptive-pilot-v1`. It replaces the open question
recorded in `AGENT_BOTTLENECKS.md`, which observed the zeros and correctly
declined to explain them.

**Conclusion: a client-build defect. Not model failure, not a keymap defect.**
Both classes were repaired five to six days after the pilot ran.

## What the zeros were

| Class | astra | sol | terra | luna | actions |
| --- | ---: | ---: | ---: | ---: | --- |
| Hero | 18,250 | 18,250 | 18,250 | 23,000 | 96/81/73/100 |
| Bowmaster | 0 | 0 | 0 | 0 | 107/97/80/94 |
| Ice/Lightning | 0 | 0 | 0 | 0 | 107/122/81/81 |

Every zero attempt recorded `status: completed`, `failure_code: null`,
`no_op: false`, `api_outcome: confirmed`, `alive_at_logout: true` and a full
300,000 ms. **The harness recorded no failure of any kind.** Diagnostic EXP was
frozen at 73,250 on every cycle of every model in both zero classes.

## Root cause

Both cohorts ran on runtime `b8e38f5`, which contains client patches 0001-0005.
The repairs those classes needed landed afterwards:

- **Ice/Lightning** — magic damage was never implemented. `0008-spell-damage`
  (2026-09-13) records that `Skill` stored spell power in `Attack.matk` and
  `Mob` never used it, and that magic used physical accuracy for hit rolls.
- **Bowmaster** — `0009-bow-expert` and `0010-critical-passives` (09-13) and
  `0018-hurricane-channel` (09-14). The unfinished client gave every character a
  flat 5% critical chance and ignored learned Critical Shot, and Hurricane
  resolved as a single 100%-damage shot per press.

Frame-by-frame review of the recordings shows competent play throughout: one
Bowmaster attempt pressed its primary attack 64 times for roughly 150,000 total
damage across 17 monsters, and all 164 observations returned the same 17 monster
ids. Not one monster died in 300 seconds.

## Why that was arithmetically hopeless, from this repository's own data

The v1 native qualification on the *same map* `240040511` recorded server-side
monster damage directly (`native-skill.jsonl`):

- monster HP up to **85,000**
- Hero hit damage min 3,988, mean 20,452, max 35,179
- three kills in a 103-second run

So a working class needs roughly four landed hits per monster. The broken
Bowmaster was landing 1,213-2,521 per hit and the mage 1,032-2,790, which is
about forty hits per monster, spread across seventeen of them. Zero kills and
therefore zero XP was the only possible outcome. This supersedes the earlier
estimate, which relied on HP figures documented for a different map.

## Where it is still live

| Branch | class-combat patches | Status |
| --- | --- | --- |
| `codex/v1-cross-provider-release` | 0003-0026 | source fixed, classes unqualified |
| `codex/native-research-integrated` | 0001, 0002 | still broken |
| `codex/mobile-continuous-sheet` | 0001, 0002 | still broken |
| `main` (pre-v1) | 0001, 0002 | still broken |

Branches without 0005 are worse, not better: the primary attacks send generic
skill-use packets that consume MP and dispatch no damage at all.

## Before any cross-class cohort

1. **The three class fixtures were one character re-jobbed.** All twelve
   attempts share `account_id 2, character_id 5, max_hp 12000, max_mp 3000,
   map_id 240040511`, differing only in `job`. A level-180 mage with 3,000 max MP
   is implausible; the repaired mage baseline uses 16,000. A Hero-derived stat
   block would suppress magic damage independently of any client patch. Audit the
   mage INT and MP before trusting a mage column.
2. **A knowledge pack is structurally unavailable off the Hero map.**
   `V1_KNOWLEDGE_PACK` is bound to `hero-180-map-240040511-v1` and
   `full_client_scenario_freeze.py` rejects a pack on any other map. Shipping a
   class column today would compare a Hero with a 17-slot toolkit and a 500,000
   token budget against classes with neither, which is a large undeclared axis.
3. **Qualify each class natively first.** The v1 native receipt has
   `qualification_scope: "core10"` and every qualified id is a warrior id.

## The harness change this argues for

`sdk.observe()` returns `{objectId, x, y}` per monster and nothing else. A model
whose attacks are silently doing nothing receives no signal at all, and the
resulting column scores zero with `failure_code: null` — indistinguishable from
model failure by anything the harness records. Exposing monster HP, or a
damage-dealt counter, would make a broken build visible in its own evidence
instead of requiring an investigation twelve days later.
