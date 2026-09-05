# Journey WASM integration patch

Upstream: https://github.com/nmnsnv/maplestory-wasm
Commit: `bc0234fe7c7f53322453e7bdd79564d9aca4cd8b` (AGPL-3.0).

From that checkout, apply `0001-demo-control-and-observation.patch`, then copy
`DemoLogin.h` into `src/client/IO/DemoLogin.h`. Retain upstream license notices.
Build with the upstream documented workflow. The verified ARM64 fallback used
Emscripten 4.0.21, one build job, two CPUs, a 3500 MiB memory cap, and no swap.

The patch:

- Queues browser keyboard callbacks onto the game loop to avoid entering an
  Asyncify-suspended client while assets are loading.
- Bounds catch-up updates per render pass while preserving queued physics ticks,
  and publishes a render timestamp so stalled frames cannot masquerade as live video.
- Treats level bytes as unsigned, so a level 180 character displays correctly.
- Automatically performs ordinary login/world/single-character selection when
  the optional demo session is enabled. Password authentication still applies.
- Publishes numeric character and monster state from the game loop for the
  program controller. This is client telemetry, not server-authoritative scoring.

No assets are included or modified. Upstream requires v83 NX files and a newer
UI NX; its original v83 UI is insufficient. Build/provide those separately.
See [full-client control](../../docs/FULL_CLIENT.md) for the relay and runner.
