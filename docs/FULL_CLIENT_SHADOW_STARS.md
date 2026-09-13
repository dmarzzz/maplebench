# Shadow Stars: native admission and buff presence

`0013-shadow-stars-cost-and-presence.patch` is a successor client source repair
for Night Lord's Shadow Stars (`4121006`, server buff `SHADOW_CLAW`). It has
focused compiled source verification. It has not been built or live-qualified,
and is not part of the accepted `e875bdb4a4a905a4995be8c0d032bec459441b28`
runtime. The existing toolkit neither learns nor binds this skill.

## Corrected finding

Per-attack ammunition consumption was already server-owned. Cosmic skips its
ordinary projectile deduction while `SHADOW_CLAW` is present, including when
the buff's numeric value is zero. It still selects a real matching projectile
with sufficient quantity before accepting a normal ranged attack. Shadow Stars
does not grant Soul Arrow's virtual-arrow admission or a default star visual.
See the pinned [ranged attack handler](https://github.com/P0nk/Cosmic/blob/b01cf27833f568cde52a0a70a38532474eedd4d9/src/main/java/net/server/channel/handlers/RangedAttackHandler.java).

The native client had two narrower gaps:

- `Player::has_buff` tested only `value > 0`, overlooking this zero-valued buff.
  The repair recognizes its received `SHADOW_CLAW` and `4121006` identity.
  Ordinary cancellation clears the entry. Other buff predicates are unchanged.
- The general exemption for non-attacking skills bypassed the upfront star fee.
  `Player::can_use` now finds the largest single throwing-star stack in USE;
  `Skill::can_use` compares that count with the positive, loaded `bulletConsume`
  value after existing level, job, HP, MP and required-weapon checks.

Cosmic pays the upfront fee from the first qualifying **single** USE stack.
Two insufficient stacks cannot be combined. The native check only establishes
that such a stack exists; the server selects and debits it. The skill has no
asset weapon restriction, so the check does not invent an equipped-claw gate.
The throwing-star predicate is `itemId / 10000 == 207`. These facts were checked
against the actual pinned environment and its upstream
[StatEffect](https://github.com/P0nk/Cosmic/blob/b01cf27833f568cde52a0a70a38532474eedd4d9/src/main/java/server/StatEffect.java)
and [ItemConstants](https://github.com/P0nk/Cosmic/blob/b01cf27833f568cde52a0a70a38532474eedd4d9/src/main/java/constants/inventory/ItemConstants.java).

The patch neither subtracts inventory locally nor grants a buff on an
acknowledged key press. Existing authoritative buff and inventory packets
continue to own those changes. A successful admission check alone proves
neither a cast nor a consumption exemption.

## Inspected definition facts

The original NX and Cosmic XML agree on these numeric fields:

| Learned level | Upfront stars (`bulletConsume`) | MP (`mpCon`) | Duration (`time`) |
| --- | ---: | ---: | ---: |
| 1 | 200 | 15 | 62 seconds |
| 30 | 200 | 25 | 120 seconds |

The root has `masterLevel=10` and no `weapon` field. Journey derives its
`get_masterlevel()` ceiling from the number of skill-level records (30), not
that separate root field. Admission reads the existing native scalar loader;
neither the 200-star fee nor duration is hardcoded into the patch.

Definition identity, with assets retained privately:

- Skill NX SHA-256: `7379bcc75a10f0befc23a6b39b2218e5b7fe6a6927e87bb4f238e9464490e74f`
- Skill XML `412.img` SHA-256: `ad4a02311d9b9d0653ba78ba1e9fcb16228405fde575857aba67e85ee155f867`
- Journey upstream: `bc0234fe7c7f53322453e7bdd79564d9aca4cd8b`
- Cosmic upstream: `b01cf27833f568cde52a0a70a38532474eedd4d9`

## Verification and remaining work

`test/test_client_shadow_stars.py` compiles the actual pinned Player admission,
buff apply/cancel/presence and Skill admission/classification methods, the
native bullet-cost loader statements, and the existing ammunition policy.
Inert storage replaces external I/O. It reproduces the old empty-ammo approval
and missing zero-valued buff, then checks both corrections; level 1/30 costs;
split, insufficient, non-star, cash and out-of-range stacks; ordinary gates;
and unchanged projectile/Soul Arrow behavior. Admission must not mutate
inventory or grant a buff. These are source tests, not gameplay recordings.

Apply the patch after the existing client patch sequence through `0012`; it
does not edit critical calculation or the ammunition policy. Before adding the
skill to any accepted toolkit, freeze a new fixture/policy and binary identity,
then verify actual casting, the one-time fee, unchanged ammunition over attacks
while the authoritative buff is active, expiry/cancellation, ordinary logout
persistence and restored resources. No full Night Lord qualification follows
from this repair.
