# Explicit 30-minute controller/recorder candidate — source candidate

`long_horizon_protocol(profile)` freezes exactly1800 wall seconds, including model
latency, under `final-program-slot-1800-v1`. The existing300-second defaults,
policies, prompts and evidence limits remain unchanged. Other wall durations,
mismatched policies and larger undeclared budgets fail validation.

New ceilings:72 requests,3000 output tokens per response,1,440,000 aggregate
reserved tokens,14,400 action attempts,60,000 SDK calls and16MiB controller
evidence. These are maxima, not requested spending. The final program stays
bounded to145seconds and the original wall deadline minus5seconds; provider
requests remain50seconds and input ACKs remain3seconds. Cancellation/death or an
uncertain call terminates normally without a replay.

The explicitly selected `post-render-encoded-frame-1800-v1` recorder and shared
verifier support1835seconds,120,000frames,600MiB WebM and32MiB ledger. Endpoint
250ms, frame gap1000ms, wall drift5ms, queue pressure, quality mode and exact
packet/ledger verification remain unchanged. Legacy mux/recorder calls retain
335seconds/20,000frames/95MiB. The controller selects the long recorder only from
the declared long policy. These changes include actual recorder/mux capacity,
not just a longer descriptive wall value. Large capture buffers need measured
memory and upload/verification closeout time on the eventual worker.

## Finite adapter integration

The opt-in trial request includes `horizon_seconds: 1800`. It requires exactly
2400 total seconds, 1800 controller seconds and an operation bound from1835 to
2100seconds. The runtime binds those budgets to the frozen scenario, starts the
ordinary server with the corresponding bounded lifetime, and retains normal
ownership, cleanup and no-replay rules. The five-minute request shape is unchanged.

Long scenarios freeze `LONG_SETTLEMENT_POLICY`: capture tail remains2000ms;
upload observation and disconnect allow180000ms; ordinary logout remains5000ms.
The server derives its600MiB streaming upload limit and180-second deadline from
the authenticated run's validated protocol. The browser upload deadline is185s.
Shared probing permits1835seconds only with the exact long capture policy, with
120000 frames,96MiB probe JSON,180s CPU/wall and768MiB address space. Short probes
retain their previous limits. Persistence timing carries the explicit horizon.

This is source support, not live qualification. The coordinator must generate the
explicit trial discriminator and bind all per-cohort budgets; native XP-window
and publication integration are separate companion changes. The existing512MiB
catalog cap remains fail-closed, so a near-600MiB recording cannot be published
there. Large probe artifacts also require explicit policy-bound reader capacity.
No old result, recording, fixture, deadline or failed attempt is reinterpreted.

Local tests exercise fake-clock1800-second completion, uncertainty/no replay,
strict capture/probe limits, explicit trial budgets, authenticated upload limits,
and actual runtime frozen-scenario loading. Existing runtime, publication and
short controller suites remain required. A real long capture still needs measured
worker RAM, upload/verification closeout and external expiry/backup reserves.

Adaptive JSON artifacts also retain the existing16MiB per-file reader ceiling.
The controller measures actual compact serialized bytes (including the newline)
before writing any artifact, and validates both final envelopes before writing
either. The SDK-step budget is an additional cap, not a promise that duplicated
trace/program envelopes fit. Oversize fails with `adaptive_artifact_byte_limit`,
preserves the last valid trace and records its hash in the bounded failure record;
it never leaves an oversized completed artifact or resumes that attempt. The
check runs at existing evidence persistence boundaries, avoiding repeated copying
of a growing trace inside every live input callback.
