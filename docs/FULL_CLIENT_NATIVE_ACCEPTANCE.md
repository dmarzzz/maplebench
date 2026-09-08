# Scripted native acceptance

`scripted-native-acceptance-v2` is a private setup check with zero model calls. It cannot be admitted as an API trial or published as a model result. It checks native controls and the recording contract before a new cohort is frozen. The earlier v1 recipe and its failed evidence keep their original identity and frozen source.

The private Unix control operation is `start_native`. Its exact fields are `op`, `run_id`, `request_id`, `native_acceptance`, `docker_image_id`, `docker_binding`, and `lock_paths`. Run and request IDs must be the same fresh 32-character hexadecimal ID. The two existing world and queue lock descriptions must arrive through `SCM_RIGHTS`; the coordinator verifies Linux kernel exclusive-lock receipts and the bridge keeps duplicates while the worker or key release remains active. Public HTTP controls do not expose this operation.

Generate `native_acceptance` with `full_client_native.contract(class_id, baseline_sha256)`. Accepted classes are `hero`, `bowmaster`, and `ice_lightning_arch_mage`. Each class has a fixed profile and physical-key program. No arbitrary program or model identity is accepted. Soul Arrow is cast before Bowmaster attacks. The request freezes 30 seconds of program time, at most 12 key actions and 100 SDK requests, and a 45-second recording ceiling. These are upper bounds; the finite recipe ordinarily finishes earlier.

The v2 recipe waits for the scene to settle, tests a 300 ms jump before any buffs, and observes immediately afterward. Skills have at least 1,100 ms between inputs so their animations can settle. After buffs, at most four observed approach steps of 1,500 ms bring the character toward a nearby monster, with a short facing input when within 110 pixels. Target selection uses a 45-pixel height band; the observation does not expose foothold identity. Movement can fail to reach a target, and the recipe does not turn that into a contact claim.

Review actual vertical displacement in the observations and recording, and require visible damage or native combat evidence for monster contact. A key acknowledgement, animation, MP cost, or unchanged monster count alone does not establish those effects. The independent saved-XP check and capture verification must still pass. Class acceptance remains a separate explicit review; this recipe never awards a model score.

The post-render capture policy is frozen directly in this native request, independently of the adaptive API protocol. Schema-2 capture measurements, the exact saved video hash and decoded presentation timestamps are verified through the same capture verifier. `verify_capture_bundle` permits native capture inspection but retains an explicit script identity, zero API count and no API planning interval. This does not grant model-publication eligibility.

Before execution, the outer maintenance owner must close any prior admission, hold the normal locks, verify the original queue is empty and workers paused, restore the exact declared baseline while Cosmic is stopped and the account is offline, independently collect a matching snapshot, and perform ordinary login in the one pinned browser. After execution it must save the evidence, perform ordinary disconnect/logout, independently collect persisted XP and native state, stop the owned world and restore the same baseline under the same locks. No script acknowledgement by itself proves a jump, skill effect, monster contact or XP gain; those need observed native effects and persisted evidence. Preserve zero gains and failures.

Runtime cleanup now journals an explicit `prepare_wait` after controller settlement, offline world shutdown, evidence preservation and owned configuration removal. It allows at most 15 seconds for a fresh, pinned waiting page with idle capture and settled artifacts. A missing acknowledgement or lost reply leaves cleanup unconfirmed. This applies to future source only; it does not rewrite historical failures.

## Reviewed cloud native-v10 evidence

The deployed pilot revision `b8e38f58ce375caca41d07903f3cef21a4fd9cea` uses the
explicit `scripted-native-acceptance-v4` recipe. Earlier recipe identities and
failed verdicts remain unchanged. For non-Hero fixtures, the recipe positions
within 300 pixels using the client's actual default 400-pixel attack range;
acknowledged movement alone does not establish a hit.

The client required three repairs: ammunition checks had blocked non-attacking
Bow buffs; Soul Arrow needed ranged classification and default projectile
visuals without inventory arrows; Hurricane's ranged packet needed four
skill-specific bytes. A further classification repair adds only Hurricane,
Arrow Rain and Chain Lightning to the upstream native attack table. Previously,
these three sent generic skill-use packets, consuming MP without damage dispatch.
Compiled tests exercise actual classification and combat branches with inert
collaborators. The deployed source/helper checks passed 215 Linux cases with one
skip. Client compilation and those tests are separate from visual qualification.

The rebuilt WASM is
`ccecd435851415a24fd9597b83976469f43aad99632109fa775084594a564624`;
its paired JS is
`ce76f9bfe0143d0fad0d776441caf6ea2b7c3261960a9afe2bac17554dd2f8af`.
The verified deployment manifest is
`47a39a4c4fca201d4bc93867b20960c5693e33b2cd038a64cfd357283d2affea`.
The original client pair and all earlier evidence remain preserved.

| Native check | Reviewed effects | Capture | Saved net XP |
| --- | --- | --- | --- |
| Bowmaster `1499961e3aed4186908406f32c03207d` | 64-pixel jump; Soul Arrow/Sharp Eyes and MP use; Hurricane damage 1,231 and 1,920 before basic attack; Arrow Rain effect and later damage | 198 rendered/submitted/encoded/decoded frames, 25.672 seconds | 0 |
| Ice/Lightning Arch Mage `5ba0f18f09bc47ba961592d3f22fb3af` | 64-pixel jump; Magic Guard/Spell Booster; Chain Lightning damage including 413 before basic attack; directional Teleport flash and 94-pixel observed horizontal relocation | 192 rendered/submitted/encoded/decoded frames, 25.245 seconds | 0 |

Both checks passed ordinary persistence/restoration and independent visual review
for the stated damaging-skill capability. Bow completion hash:
`37c7e2f031ab01593e32b9d06ec051cdb6d2ffcee37fcbccbe1dc62ee4bd162d`.
Mage completion hash:
`bab4f2d327baaab313432c464559b999bbd57905a4c73ebcb5a58f9ce55468a4`.
They made zero API calls and are not model results. Neither establishes a kill,
XP gain or player damage/contact. Mage's 30 saved HP loss matches Spell Booster's
cost; the check does not claim its nominal 150-pixel Teleport range.

Mage damage was hundreds while Bow damage was thousands. The unchanged fixtures
remain separately declared research pilots; these observations do not establish
balanced difficulty. Do not interpret raw XP differences between classes as
model differences; freeze and disclose fixture difficulty. Multi-entity area
behavior, longer hunting, navigation objectives and sampling calibration remain
roadmap work. In particular, damaging-skill qualification does not satisfy all
of M5, and native success does not complete M2's four-model publication gate.


### Hurricane channel limitation

The accepted Bow check proves discrete ranged damage in this client port. It
does not qualify sustained Hurricane channeling or canonical Bowmaster fidelity.
In the pinned upstream client source, `src/client/Gameplay/Stage.cpp` repeats
held Jump, basic Attack and Pickup in `handle_held_actions`, but has no held-skill
loop. `Stage::send_key` calls `combat.use_move(action)` for skill events without
checking the key-down boolean; `src/client/IO/UIStateGame.cpp` forwards both
press and release. `src/client/Character/Player.cpp` refuses another attack while
the current attack animation is active.

The controller in `ui/full-client/controller.js` emits a synthetic key-down and
timed release, then releases again during final cleanup. Duplicate key-up
callbacks can therefore occur; they are not a continuous channel cadence.
The generic implementation in `src/client/Gameplay/Combat/Skill.cpp` and
`SkillAction.cpp` uses ordinary attack actions. Although the native Hurricane
data contains prepare, keydown and keydownend animation trees, this path does
not implement those channel stages. Holding a skill key longer does not imply
continuous native Hurricane damage output.

The observed attack count and server damage rate in a model run remain separate
measurements. This limitation alone cannot explain every zero-XP result, and a
zero saved gain is not evidence of a scoring bug. Keep the current range and
resource qualification scoped to the declared port. Implementing faithful
channel behavior would change the client version and require fresh native
qualification and a new cohort; current results must retain their original
client identity and limitations.
