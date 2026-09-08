# Journey WASM integration patch

Upstream: https://github.com/nmnsnv/maplestory-wasm
Commit: `bc0234fe7c7f53322453e7bdd79564d9aca4cd8b` (AGPL-3.0).

From that checkout, apply `0001-demo-control-and-observation.patch` and
`0002-key-config-access.patch` in order. The optional Bow ammunition candidate
`0003-projectile-ammunition.patch` additionally requires copying
`AmmunitionPolicy.h` to `src/client/Gameplay/Combat/AmmunitionPolicy.h`.
This candidate has focused policy tests but has not yet passed a WASM rebuild or
live native qualification. Copy `DemoLogin.h` into
`src/client/IO/DemoLogin.h`. Retain upstream license notices.
Build with the upstream documented workflow. The verified ARM64 fallback used
Emscripten 4.0.21, one build job, two CPUs, a 3500 MiB memory cap, and no swap.

The first patch:

- Queues browser keyboard callbacks onto the game loop to avoid entering an
  Asyncify-suspended client while assets are loading.
- Bounds catch-up updates per render pass while preserving queued physics ticks,
  and publishes a render timestamp so stalled frames cannot masquerade as live video.
- Treats level bytes as unsigned, so a level 180 character displays correctly.
- Automatically performs ordinary login/world/single-character selection when
  the optional demo session is enabled. Password authentication still applies.
- Publishes numeric character and monster state from the game loop for the
  program controller. This is client telemetry, not server-authoritative scoring.

The second patch opens ordinary key configuration when Backslash is pressed and
has no configured binding. Existing bindings and chat text input retain their
normal behavior. It changes no action mappings or server state by itself.

## Repairing action bindings

The demo requires Space bound to Jump and Ctrl bound to Attack. Both use keymap
type `5` (action), with action IDs `53` and `52` respectively. Type `4` is a menu
binding; assigning those action IDs with type `4` causes these keys to do nothing.
The client and Cosmic's standard keysets agree on these types.

If either action is incorrectly typed, leave chat input, press Backslash, drag
the existing Jump icon back onto Space and the Attack icon back onto Ctrl, then
click **OK**. The key configuration icons supply the correct action type. This
updates bindings through the ordinary client keymap packet and immediately
applies them locally. If **OK** does not respond, press Escape and confirm
**Save key binding changes?** with Enter. This fallback was verified in the live
client. Jump stays on Space; this repair corrects its mapping type, without
moving it to Alt. Do not use **Default** for this repair; it replaces custom
skill and potion bindings. Verify a visible jump and attack afterward. The
server may persist the changed mappings during normal logout, so log out
ordinarily before checking the saved database rows.

No assets are included or modified. Upstream requires v83 NX files and a newer
UI NX; its original v83 UI is insufficient. Build/provide those separately.
See [full-client control](../../docs/FULL_CLIENT.md) for the relay and runner.

## Bow ammunition candidate

The upstream client defaults missing NX bullet-count/consumption fields to one.
Its projectile-weapon check also applies to non-attacking buffs, so an empty
bow inventory prevents Soul Arrow itself from being cast. The third patch
exempts non-attacking skills from ammunition checks after preserving skill
level, job, HP, MP and weapon requirements. Player-side ammunition availability
recognizes the existing Soul Arrow buff only for bows/crossbows, applying to
both basic and skill attacks. The same predicate preserves ranged attack type
instead of incorrectly selecting a reduced-damage close attack when the buff
substitutes for physical arrows. Claws and guns receive no exemption.

No arrows are inserted into inventory and no MP, job, timing or server validation
is bypassed. With Soul Arrow and no inventory arrow, ranged attacks select the
existing NX default bow/crossbow projectile animation; physical-arrow animations
remain unchanged. This visual ID is not serialized as packet ammunition.
Projectile effects and Hurricane's packet-specific layout still need actual
native verification. This patch does
not change that serializer. Keep failed class qualification evidence intact;
do not infer a valid class benchmark from these focused tests.

## Fixture attack classification

Apply `0005-fixture-attack-flags.patch` after the client patches above. The
upstream attack flag table omits Hurricane (3121004), Arrow Rain (3111004) and
Chain Lightning (2221006). Without these flags, the normal combat dispatcher
sends a generic skill-use packet and never selects targets or sends attack
damage, even though the server may consume MP. This patch adds only those three
native attack classifications; buffs and other unknown skills retain their
existing classification.

The focused regression compiles the actual upstream classification and combat
dispatch methods with inert game/packet collaborators. It demonstrates the
original three generic packets becoming three attack packets, with target and
effect dispatch, while fixture buffs remain generic skill-use packets. This is
source verification, not proof of native animation, server damage or class
qualification. All earlier native failures remain unchanged.
