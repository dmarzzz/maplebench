# NanoCodex controller candidate

Research checked 2026-09-05. No NanoCodex integration or gameplay performance
claim is established by this document.

The likely intended project is [gakonst/nanocodex](https://github.com/gakonst/nanocodex).
It is an embeddable agent SDK with retained sessions, tool execution, events,
retries, and cancellation. It could become an optional MapleBench controller;
overlay, repeatable scenarios, authoritative scoring, and valid publication
remain the immediate priorities.

## Version boundary

The inspected Astra-capable source revision is
`3d8d6ea7477e64d82e5fb1347958979f3fc3e048`. Its
[model types](https://github.com/gakonst/nanocodex/blob/3d8d6ea7477e64d82e5fb1347958979f3fc3e048/js/nanocodex/types.d.mts)
include `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna`.
This verifies declared support, not a successful MapleBench API run.

At inspection, the [npm registry release](https://registry.npmjs.org/nanocodex/latest)
was `0.5.0`, requiring Node.js >=22.13. Its
[published types](https://unpkg.com/nanocodex@0.5.0/types.d.mts) list only
Sol/Terra/Luna. Its constructor accepts `apiKey` directly, whereas the
[pinned source guide](https://github.com/gakonst/nanocodex/blob/3d8d6ea7477e64d82e5fb1347958979f3fc3e048/js/nanocodex/README.md)
uses `Transport.openAi({ apiKey })`. Do not mix master examples with the registry
package. An all-four-model trial needs an Astra-capable pinned build and a smoke
test of each requested model. The
[source manifest](https://github.com/gakonst/nanocodex/blob/3d8d6ea7477e64d82e5fb1347958979f3fc3e048/Cargo.toml)
declares `MIT OR Apache-2.0`.

## Smallest useful experiment

The existing full-client controller generates one JavaScript program per API
request and executes it through the restricted SDK. NanoCodex could retain
history across repeated observe, execute, inspect, and revise steps within one
trial. That may improve adaptation; it requires measurement.

1. Run a trusted sidecar on the remote experiment host. Keep API credentials in
   that trusted process and out of generated code, browser state, and outputs.
2. Select `toolMode: "direct"`. Supply `observe` and `run_program` application
   tools; route `run_program` through the existing networkless, read-only,
   resource-limited Docker executor and validated full-client keyboard relay.
3. Keep one session per trial, with no history carried between scored trials.
   Enforce wall-clock, API, token, and action limits in the host. Cancel on
   expiry and release held keys. Verify the effective tool catalog: extra
   workspace, network, and default subagent capabilities must be disabled or
   denied, not merely omitted from the prompt.
4. Feed controller name, exact model, runtime revision, usage, and status into
   the existing overlay and result manifest. Compare controllers under the
   same reset state, observation contract, scenario, and budgets.

Preserve the sandbox: the published Node host defaults to Code Mode and passes
`require` into a runtime that evaluates generated JavaScript with
`AsyncFunction`. It is not equivalent to our Docker isolation. See the
[published host](https://unpkg.com/nanocodex@0.5.0/node/host.mjs),
[code runtime](https://unpkg.com/nanocodex@0.5.0/runtime/code-runtime.mjs), and
[direct-mode option](https://unpkg.com/nanocodex@0.5.0/node/Agent.d.mts).

Keep MapleBench's queue, world locks, reset policy, server-event scorer, recorder,
and publication checks. NanoCodex does not replace those or improve game physics.
Do not automatically replay uncertain game actions after recovery: its
[durability contract](https://github.com/gakonst/nanocodex/blob/3d8d6ea7477e64d82e5fb1347958979f3fc3e048/docs/DURABILITY.md)
allows unfinished effects to execute again. Initially fail interrupted trials
and rerun from a fresh reset.
