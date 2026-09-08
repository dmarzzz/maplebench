# Hurricane channel work

This is a source-only first correction and a bounded implementation plan. It
does **not** implement or qualify continuous Hurricane. Existing cohort videos,
scores, baselines and deployed client bytes remain unchanged.

## First correction: `skill-keydown-dispatch-v1`

The optional `0006-skill-keydown-dispatch.patch` changes only the SKILL branch of
`Stage::send_key`: a release cannot call `Combat::use_move`. Previously the
ordinary timed keyup and a repeated cleanup keyup could each attempt another
skill after the original animation finished. A keydown rejected while attacking
could therefore turn into a successful cast on release. Buffs were affected as
well as attacks.

Skill keydown still reaches the original combat checks. This patch does not
change job, level, weapon, HP, MP, ammunition, cooldown or attack eligibility.
Repeated browser keydown remains unchanged. Basic attack and jump keep their
existing fixed-update repeats, movement retains down/up delivery, and item/face
dispatch is outside this patch. There is no new skill repeat loop.

The regression compiles the real pinned `Stage::send_key` and
`Stage::handle_held_actions` methods before and after patch application. It
demonstrates release-only, duplicate-release and previously-denied-press bugs;
checks the fixture attacks and buffs; and preserves basic attack, jump,
direction, sit, inactive-stage and intro-input behavior. Inert collaborators
record dispatch and do not stand in for native damage or server acceptance.

This optional patch changes the client version. Applying it requires a new
source and runtime inventory, rebuilt WASM/JS hashes and fresh native
qualification before any new model cohort. It cannot be applied to a running
cohort or used to reinterpret previous action counts. No server JAR change is
required by the patch itself.

## What the inspected sources establish

Journey upstream is
[`bc0234fe7c7f53322453e7bdd79564d9aca4cd8b`](https://github.com/nmnsnv/maplestory-wasm/tree/bc0234fe7c7f53322453e7bdd79564d9aca4cd8b).
The inspected client included the first five integration patches and was built
from MapleBench source `173f5bc9c180dbede3ccf59b2ffbf8555d499bb1`, used by
the later `b8e38f58ce375caca41d07903f3cef21a4fd9cea` trial source.

| Component | Established behavior |
|---|---|
| `Stage::handle_held_actions` | Repeats Jump, basic Attack and Pickup; it does not repeat SKILL. |
| `Stage::send_key` | Before this patch, dispatches SKILL on both down and up. |
| `UIStateGame::send_key` | Forwards both skill edges when a focused UI element does not consume them. |
| `Combat::use_move` | Requires `Player::can_attack` and the ordinary `Player::can_use` checks. |
| `Skill` / `SkillAction` | Ignore channel-specific art trees and select `RegularAction` when the generic action is absent. |
| Pinned Hurricane NX metadata | Has `prepare`, `keydown`, `keydownend` and `ball`; no generic action/effect. Level 30 has `damage=100`, `mpCon=9`; absent `bulletCount` defaults to one in this client. No asset is bundled here. |
| Cosmic `SkillEffectHandler` | Reads skill ID (int), level (byte), flags (byte), speed (byte), direction (byte); Hurricane follows a broadcast-only effect path. This does not apply damage or establish a firing interval. |
| Cosmic `CancelBuffHandler` | Hurricane cancellation broadcasts the channel-effect stop instead of ordinary buff cancellation. |
| Cosmic ranged damage path | Damage continues through ranged attack packets, including the corrected Hurricane header padding. Generic `UseSkillPacket` is not a substitute. |

The inspected source bytes are pinned below. Server handler pins describe the
read-only source inspection; they are not a new deployed-JAR attestation.

| Source file | SHA-256 |
|---|---|
| `Gameplay/Stage.cpp` | `9eb05190e3fb802a4953a5f38297a60d35b42dd77b23f46bab97b37d467b36bf` |
| `Gameplay/Combat/Combat.cpp` | `3c4521660455ae9b272dc6643e83b8a30a696df4bb8700021c5d30b31877df52` |
| `Gameplay/Combat/Skill.cpp` | `d2a66dcb19bb093e4159e8d1322f7e2bed5316b631b57a70dd8eb2fd1251ed14` |
| `Gameplay/Combat/SkillAction.cpp` | `ce0dd7b60cb667bde27f4d53462e11a197030422263ffdb71205877c60cb7f66` |
| `Character/Player.cpp` | `c00f250c959a0988870155cad4cbdc31592e15818bbf9efc091e6c6967765b01` |
| `SkillEffectHandler.java` | `38edd35adbd992964eea98281fbae41dc54dd27a184fb1b02770522e601faf0e` |
| `CancelBuffHandler.java` | `9ed797131118e3d9f96c990b8ea25d39ef25acb9e6ce36cd940969f3fbf9c8e1` |
| `RangedAttackHandler.java` | `913173c38f1170a92af350c988e623ec2c56eea9d9e601873f6da1c4d97fae20` |

## Next implementation: `hurricane-channel-v1` (proposed, not implemented)

Scope the first channel to Bowmaster skill `3121004`. Other channel skills,
damage tuning and class fixture changes are separate work. The required path is:

1. A fresh keydown passes normal ability, weapon, resource and character checks,
   captures its owning character/map/skill, and enters `Preparing`. Repeated
   keydown does not restart it. A distinct channel-start packet uses the actual
   server skill-effect layout.
2. Render the native prepare phase, then enter `Channeling`. This needs a
   dedicated character pose/effect lifecycle; repeatedly invoking the existing
   regular bow action would reset its animation and preserve the wrong gate.
3. While the same key is held, emit separately timestamped ranged attacks at
   the verified native cadence. Each emission uses current target geometry and
   ordinary resource/weapon checks. Preserve damage calculation, ammunition
   handling and server validation. Do not replay overdue shots in a catch-up
   burst after a renderer or network stall.
4. Keyup, owner/map change, death, invalid state, lost ammunition/resources or
   input cancellation leaves the firing state synchronously. The native end
   phase and one channel-cancel packet complete `Stopping`; duplicate releases
   and delayed events cannot fire, restart or cancel a different owner.
5. Stage clearing, UI focus/visibility loss and disconnection must explicitly
   cancel channel state, even when UI routing consumes keyup. Preserve final
   input-release acknowledgments and the current capture guards.

The channel belongs in Combat/character animation with Stage forwarding edges;
it must not be a controller-side timer that fabricates generic skill presses.
`Player::can_attack` must remain unchanged for ordinary attacks. A separate
channel continuation check must retain death, climbing, sitting, weapon,
cooldown, skill level and resource restrictions. Direction-change and movement
rules during the channel require native evidence before choosing whether to
reject them, interrupt, or allow them.

The sources establish packet structure and the presence of phase art, but
**do not establish the native firing cadence, prepare/end phase durations,
character action mapping, or movement/interruption rules**. A frame-animation
delay is not by itself a proven shot interval. No 100 ms timer or equivalent
rate is invented here. The next evidence acquisition is bounded read-only
extraction of relevant original NX phase metadata, plus an approved native v83
channel trace or equivalent primary implementation evidence for shot timing and
start/cancel fields. These values must become explicit versioned fixtures before
channel implementation can be declared complete.

## Acceptance for a future channel candidate

Compile the real channel and packet methods against inert collaborators:
down/up ownership, release during prepare, duplicate edges, no-input ticks,
resource exhaustion, state invalidation, delayed tick without catch-up burst,
and exact packet bytes must all be checked. Exercise the implementation with a
fake clock instead of duplicating its transition logic in tests.

Then rebuild an isolated client under the normal shared-build limits. A fresh
zero-API native recipe must record short and sustained holds, correct prepare /
loop / end visuals, actual repeated ranged damage, normal MP consumption, one
stop, no damage after acknowledged release, ordinary logout and persisted XP
when a kill is actually achieved. Include a real target kill and server XP
receipt before describing class kill/XP qualification. Visible numbers alone
are not that proof. Verify the complete post-render recording and declare the
new client/fixture identity before launching a fresh model cohort.

The completed Bowmaster pilot remains a result for the previous discrete-skill
port. Its landed hits and saved zero XP are retained. Neither the channel
limitation nor this first correction assigns all zero XP to one cause.
