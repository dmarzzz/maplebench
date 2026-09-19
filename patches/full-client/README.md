# Journey WASM integration patch

Upstream: https://github.com/nmnsnv/maplestory-wasm
Commit: `bc0234fe7c7f53322453e7bdd79564d9aca4cd8b` (AGPL-3.0).

From that checkout, apply `0001-demo-control-and-observation.patch` and
`0002-key-config-access.patch` in order, then copy `DemoLogin.h` into
`src/client/IO/DemoLogin.h`. Retain upstream license notices.
Build with the upstream documented workflow. The verified ARM64 fallback used
Emscripten 4.0.21, one build job, two CPUs, a 3500 MiB memory cap, and no swap.

## Expanded v1 candidate

The original two-patch instructions above describe the early integration. The
expanded Hero candidate uses the complete ordered Client C series: `0001` through
`0006`, then `0008` through `0023` (there is no `0007`). Exact patch and binary
hashes, upstream revision and source revision are recorded in
[V1_NATIVE_BUILD_INPUTS.json](../../docs/V1_NATIVE_BUILD_INPUTS.json).

The recovered JavaScript and WebAssembly bytes independently matched those pins.
Their historical build receipt is not fresh native skill qualification. Keep the
whole patch series when reproducing that candidate: later patches depend on earlier
combat, packet and observation changes. In particular, Combo/finishers and ordinary
multi-field buffs require `0017` and `0023`. The included monster-status client
decoder requires the matching Cosmic `0002-monster-status-order.patch`.

Game binaries and assets remain private. A newly instrumented server receives its
own build/runtime hash before the cohort; it does not inherit the old JAR's pin.

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
