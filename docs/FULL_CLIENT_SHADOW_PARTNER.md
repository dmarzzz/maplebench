# Shadow Partner: native ranged damage candidate

`0020-shadow-partner.patch` adds a bounded client attack path for Hermit's
Shadow Partner (`4111002`) on actual claw projectile attacks. It is source work,
not an activated client, accepted toolkit, benchmark result or official-client
parity claim. Existing source, fixtures, recorded runs and protocol identities
remain unchanged. Apply it after the existing repair sequence; it also applies
after 0017–0019 without editing their damage-stat, channel or observation methods.

## Confirmed source gap

The client stores the server's `SHADOWPARTNER` buff but does not consume it when
preparing attacks. Lucky Seven and Triple Throw therefore retain two and three
lines respectively in the native result and ranged packet. The matching Cosmic
ranged handler already doubles the projectile requirement and consumption, and
its attack parser expects the partner lines in the second half of each target's
damage vector. Merely changing an on-screen animation would not correct this.

The candidate reads the received `4111002` buff and its matching learned-level
NX data. A missing, cancelled, foreign or mismatched buff does not grant damage.
In particular, changing the learned level cannot upgrade an older received buff:
the received value must still equal that level's `x`. It supports only ranged
claw attacks, leaving melee fallback, magic and other weapons unchanged.

After the ordinary skill has set its hit count, `Combat::apply_move` doubles it
once, before the existing single native damage pass. One to seven primary hits
fit the packet's four-bit count when doubled; current scoped claw attacks use
one, two or three. All primary and partner lines pass through the existing native
defense, accuracy, critical and damage-cap calculation. The second half is then
scaled before local effects and the unchanged `AttackPacket` serializer. Misses
stay zero; positive lines retain the native minimum of one; critical flags and
per-target ordering are preserved. No new critical roll or second mob-update
side effect is added by scaling.

## Damage interpretation and its limit

The pinned NX/XML scalars agree at all 30 levels:

| Partner level | `x` | `y` | MP | Duration | Item cost |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 | 20 | 21 | 200 | 60 s | 1 × 4006001 |
| 15 | 60 | 29 | 130 | 120 s | 1 × 4006001 |
| 30 | 80 | 50 | 55 | 180 s | 1 × 4006001 |

The exact String.nx descriptions confirm `x` is ordinary-attack percent and `y`
is skill-attack percent at every level: level 30 says “Attack 80%, Skill 50%.”
The candidate applies this percentage to the defended final line. Its independently rolled partner
lines follow the matching server's `BotCombatManager` description and
`CombatFormulaProvider` structure. That bot helper hardcodes half damage and
therefore is **not** evidence for every level or ordinary-attack percentage.
The server parser's half-damage bound is anti-cheat headroom, not a complete
official-client formula specification. Official-client critical/miss correlation
still needs independent confirmation before
calling this canonical. Source tests establish the explicit candidate behavior.

Definition identity: Skill.nx SHA-256
`7379bcc75a10f0befc23a6b39b2218e5b7fe6a6927e87bb4f238e9464490e74f`;
Cosmic `411.img` SHA-256
`5e2e507e33b6d72d492ca0fad734b1beaa5f2388fa90ed4c341a2164edd494b8`.
The private read-only scalar/description receipt is hash-bound as
`6c2ab72b7f3c0df416b7bb6e5bdaa6109d23abf7e6bc9d8d716fb389f28f43f7`;
only numeric facts and asset hashes are retained in the public test fixture.
The actual server source retains ordinary item and ammunition ownership;
upstream [StatEffect](https://github.com/P0nk/Cosmic/blob/b01cf27833f568cde52a0a70a38532474eedd4d9/src/main/java/server/StatEffect.java)
and [RangedAttackHandler](https://github.com/P0nk/Cosmic/blob/b01cf27833f568cde52a0a70a38532474eedd4d9/src/main/java/net/server/channel/handlers/RangedAttackHandler.java)
show the corresponding resource routes.

## Ordinary resources and Shadow Stars preparation

Shadow Partner's cast checks the real item ID/quantity from its NX level against
ordinary inventory before sending the skill. Existing learned-level, job, HP,
MP, cooldown and weapon checks remain in place. No item is deducted or created
locally and no acknowledged key grants a buff; the server performs both changes.
An active partner also doubles the claw ammunition admission requirement.

Existing `0013-shadow-stars-cost-and-presence.patch` remains unchanged. It admits
Shadow Stars (`4121006`) only with a qualifying single real star stack covering
the 200-star upfront fee and recognizes the server's zero-valued `SHADOW_CLAW`
buff. Partner does not double that buff's upfront fee. While Shadow Stars is
active, the server still requires a real projectile stack for attacks, including
Partner's doubled count, and controls whether subsequent attacks consume it.
Soul Arrow or separate insufficient stacks cannot synthesize that requirement.
See [Shadow Stars source and admission](FULL_CLIENT_SHADOW_STARS.md).

Before live use, freeze a new binary, toolkit and ordinary finite-resource
fixture. Separately verify: missing-rock refusal; exact rock/MP cast cost and
received Partner identity; 1→2, 2→4 and 3→6 real projectile/damage lines; damage
and critical behavior; ordinary doubled star consumption; cancellation/expiry;
the single 200-star Shadow Stars fee, real buff presence and unchanged subsequent
star inventory while active; resumed consumption after cancellation; normal save
and exact baseline restoration. The original ordinary resource evidence must be
independent of SDK input counts. None of these live gates is completed here.

The focused compiled regression also reproduces the original missing lines and
local missing-rock admission, checks all inspected levels, unrelated routes,
packet counts/bytes, no local inventory changes, misses, critical flags and
bounded second-half scaling. No model API calls or remote build is involved.
