# Expanded toolkit qualification

The next release gate is a verified, explicitly limited toolkit for Hero,
Bowmaster, Ice/Lightning Arch Mage and Night Lord. Each class has ten physical
skill bindings. This is not the complete original MapleStory class kit, and
neither source tests nor positive XP qualify every skill.

The opt-in `full-client-skill-toolkit-v2` policy and
`scripted-native-toolkit-acceptance-v2` recipe preserve the exact historical v1
policy, fixtures and programs. The new native recipe permits 120 seconds,
128 input actions and 600 SDK requests, with a 125-second recording bound.
It uses preset inputs, no model and no ranked score. The normal SDK's
30–1500 ms input bounds remain unchanged.

## Source changes under verification

| Area | Candidate behavior | Required live evidence |
| --- | --- | --- |
| Hero Combo and finishers | Server-received orbs affect physical damage; zero-orb finishers are refused; the server owns accumulation and consumption | Buff identity, ordinary hits building orbs, finisher effects and subsequent orb reset |
| Hero Achilles | Send pre-passive contact damage; the server applies its remaining-damage factor once | Ordinary contact with the passive learned, saved HP changes and matching wire/server evidence |
| Sharp Eyes | Received packed values affect physical critical chance and the additive critical coefficient | Buff receipt, native critical damage lines and ordinary cancellation |
| Hurricane | Held input prepares for 960 ms, then fires every 120 ms of simulation time; release stops subsequent shots | Repeated native shots during a hold, cessation after release, finite costs and real-time capture |
| Shadow Partner | Ranged claw damage gains extra lines using the pinned normal/skill ratios; activation requires a real Summoning Rock | Buff receipt, extra damage lines, ordinary saved rock/ammunition costs |
| Shadow Stars | Recognize its zero-valued received buff; require its 200-star activation fee | Upfront cost, attacks during the active exemption, cancellation and subsequent costs |
| Monster movement statuses | Parse matching server status packets; stun/freeze halt movement and slow adjusts movement force | Eligible monsters stop/slow, then resume after a received cancellation |

Achilles is an additional level-30 passive in Hero v2. Its pinned `x=850` means
85% damage remains. The local damage number is a prediction; saved HP/MP remain
server-owned, including Power Guard and Magic Guard. The port's underlying
contact-damage estimate is not a qualified original-client formula.

Hurricane's preparation and movement-status scaling are declared port policies.
Original-client animation fidelity and all canonical class mechanics are not
established. Shadow Partner's damage path does not establish its follow-along
visual effect or original-client correlation of duplicate critical/miss rolls.
See the individual repair documents for exact scope and source tests.

The client monster-status patch requires the matching Cosmic serializer patch.
The packet format has no identity beside each status value, so the server must
write values in canonical enum order rather than concurrent-map iteration order.
Deploy those two patches together.

## Finite resources and restoration

V2 creates a new immutable offline fixture; it does not edit a running database.
The fixture replaces USE and ETC contents with the declared finite supplies.
Historical v1 still replaces only USE and preserves ETC. Existing original
baselines remain separate artifacts.

All classes receive 100 shared Power Elixirs. Bowmaster receives four ordinary
arrow stacks; Night Lord receives 23 stacks of 800 Ilbi stars, plus ten
Summoning Rocks (`4006001`) in ETC. USE has 24 slots; ETC is a separate tab.
The other three v2 ETC tabs start empty. The rock's pinned NX and XML definitions
agree; absent `slotMax` uses Cosmic's ordinary non-equipment default of 100.

Owned read-only receipts capture USE and ETC in one consistent offline SQL
transaction before login, after ordinary logout and after baseline restoration.
They bind all frozen ETC contents, reject growth, moved/substituted supplies and
unrelated depletion, and require positive rock consumption for a successful
Night Lord toolkit proof. Cleanup can still succeed after an unsuccessful
attempt with zero consumption. Inventory depletion does not establish hits or
attack counts, and these receipts never award a model score.

## Diagnostic state

Patch 0019 exposes `Module.MapleBenchSkillState` separately from the existing
model observation. It reports the native position, HP/MP, derived stat totals,
attack speed and received buff identities/values. Zero and negative buff values
remain meaningful. Durations are the last values received, not remaining timers.
The snapshot contains no character name, account data or qualification flag.

For this native protocol only, a private browser trace copies these snapshots
and monster positions with sequence numbers and browser monotonic time. Input
markers retain command IDs and the same handler-start clock used by original
ACK receipts. It is bounded to 8192 records and 12 MiB; exceeding either limit
records a failure rather than silently losing early evidence. Operators must
checkpoint it before navigation or another run. It never enters model
observations, ACK payloads, scoring or automatic admission. Identical wall-clock
timestamps can describe distinct simulation updates and are retained separately.

This state is diagnostic evidence, not the authoritative saved-XP ledger.
It helps distinguish a delivered key from a received buff and an actual stat
change. Tests compile the production serializer, retain the unchanged model
observation and verify inactive-state clearing.

## Release gates

- [ ] Freeze reviewed source, matching client/server binaries and definition hashes.
- [ ] Prepare and retain each new immutable class fixture and toolkit fingerprint.
- [ ] Run each bounded native recipe through ordinary login, with fresh rendered state.
- [ ] Review every declared skill's native effect; a delivered key is insufficient.
- [ ] Verify real-time simulation, post-render recording and accurate scripted labels.
- [ ] Verify saved resource costs, saved XP diagnostics and exact baseline restoration.
- [ ] Publish per-skill capability status and the exact unsupported scope.
- [ ] Freeze the separate four-model baseline experiment after these gates pass.

The existing four three-minute videos remain scripted environment checks on an
older toolkit. They must not be relabeled as evidence for v2 or inserted into
the model matrix. Summons, Flash Jump, Big Bang and other explicitly excluded
mechanics remain outside this release's advertised bindings.

Related: [baseline checklist](BASELINE_RELEASE_CHECKLIST.md),
[Combo/Sharp Eyes](FULL_CLIENT_COMBAT_BUFFS.md),
[Hurricane](hurricane-channel.md),
[Shadow Partner](FULL_CLIENT_SHADOW_PARTNER.md),
[monster statuses](monster-movement-status.md), and
[matrix integration](MATRIX_INTEGRATION_REVIEW.md).
