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

The build and offline preparation gates below are complete on source
`d2fe0671db0bf4932b44fc117e581c0258f65dbb`. Client build B includes patches
0017–0022 on the retained production base; server build C includes the matching
`0002-monster-status-order.patch`. The build receipts confirm that original
source, caches and binaries were preserved.

| Matched artifact | SHA-256 |
| --- | --- |
| Client JavaScript | `52b2c236b7c936e3169872219b2baef3161fd3ad2d8c354d25db18d4712aac66` |
| Client WebAssembly | `916e5260aae8e3ce4b29534c8f4bdf1adbf11dabb267a61b6b0bb037b1b592f8` |
| Server JAR | `394c2afee55f3affee0bc7df720ec972a2bb36a96b0386b637fb113e87e9942c` |

The server's seven XP-ledger and five persistence tests passed with zero errors,
failures or skips. Two focused Linux tests also passed with zero skips: actual
inherited-lock admission and an inert private Unix-socket handoff retaining those
locks. The latter verified 171 committed Python files and made no Docker or API
calls. These checks establish source and ownership behavior, not native gameplay.

All four new offline fixtures were derived in 3.158 seconds. For every toolkit,
the definition reader verified all declared skills at their frozen levels,
transitive prerequisites and finite resources against matching NX and XML.
Account/credential bytes and ordinary equipment were preserved. Each output
retains its parent hash, definition report, expected fixture and exact toolkit
fingerprint; no database was changed by this preparation.

| Class | Offline fixture SHA-256 | Toolkit fingerprint |
| --- | --- | --- |
| Night Lord | `63b02968f75acf6f510d7170261ac9c6a0c2d680a9987d1ff3451a302d13d43d` | `365149bc132a5a3862236a15b3dc5d689dae27487002d5b74aed4e1c9cda4125` |
| Ice/Lightning Arch Mage | `4e475c68c67a2ed01ce5b9f11e4ffb3072ad6fc890b0f4298783d5deb99e59e0` | `9f349fc7795201fcbf63c569814a26471bb20d760d8f5111ed19c6929a2537f9` |
| Hero | `9850f297330233ecf7b4a4bae93b6855d5df852124dcdb86dc0699e3347154e3` | `3b24693c0c2024e3bbb33030fb4ab33ab10b630dbf60cb9c2f98f7d02d047a1c` |
| Bowmaster | `64f3fd3dd6e5dcd7ede3184617d8407ed508dce6977ede2c1992d8261cd89e43` | `64b1de945214743557981fd81134798b86812d75847e4c749af72e46d0e2e09e` |

The fixture completion receipt is
`379cfecc0dfc84277bdfa58ee081c3af559532900b6a0065171cbde4c6ac4932`;
the inert Linux test receipt is
`dbd00d668cab7ff589069b08e870de1b2a1baf8a89480b593413257bbc9d9cda`.
The first Night Lord native check below did not qualify this pair; it exposed a
player-buff decoding defect. A repaired client needs fresh native verification.

- [x] Freeze reviewed source, matching client/server binaries and definition hashes.
- [x] Prepare and retain each new immutable class fixture and toolkit fingerprint.
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

## First native check

Run `26fa40f7215145209a4943add35891a0` exercised the Night Lord v2 fixture
with client B and server C. It was a scripted native acceptance check with
**zero model/API calls**, not a model result or a ranked trial. The 120-second
limit was a ceiling; actual capture lasted **38.899810 seconds**.

| Observed result | Value |
| --- | --- |
| Input actions / RPC requests | 28 / 124 |
| Captured frames / average capture FPS | 1,253 / 32.210797 |
| Diagnostic persisted XP | 0 |
| Final state | Alive; HP 11,492 |
| Persisted resource consumption | 6 Power Elixirs, 209 Ilbi stars, 1 Summoning Rock |
| Ordinary disconnect persistence | Verified |
| Character, keymap, USE and ETC baseline restoration | Exact match |

The closed browser trace contains 866 records and no collector failure. All ten
bindings were attempted. The trace records the six expected buff skill IDs and
a Drain use costing 24 MP, with HP rising from 10,547 to 12,000 before the later
potion. These observations do not establish every advertised effect. The
pre-Partner Triple Throw was skipped during movement, so this check supplies no
clean before/after Shadow Partner damage comparison.

Haste exposed an actual client defect: its speed-40/jump-20 payload became
speed-20/jump-40, yielding native totals 120/123 instead of 140/120. The decoder
iterated unordered stat maps and could consume shared Combo/Summon bits twice.
The [ordinary buff decoder repair](FULL_CLIENT_BUFF_WIRE_ORDER.md) addresses
that source defect; its tests do not retroactively qualify this recording.

The recording duration and transport clock were verified. Independent
simulation/wall timing was not collected here and remains required on the
repaired build. Native skill qualification and model admission remain open.

| Retained evidence | SHA-256 |
| --- | --- |
| Outer completion | `1a4ce2a06ab886ac26cb51e7db833d14891739dba0521f5f2078c7349067b9ed` |
| Inner completion | `e8126576d990c7fd0d7c19d687ada3b843115d4e227bac3b8c53b440ff8582f3` |
| Original recording | `0bcbdbe07f5cafa4bafd4b7f14c37793e38c3e1667ac603bb3d1e908ae0de92f` |
| Closed browser trace | `beca2d84cecc346562c73a5f22caba71ee3f455d7ad9a117873a6edf581ffe83` |

The original recording, trace and runtime evidence remain in private operational
storage; this source record publishes their identities and reviewed conclusions.
