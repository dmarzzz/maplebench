# Explicit 30-minute controller/recorder candidate — phase 1 only

`long_horizon_protocol(profile)` freezes exactly1800 wall seconds, including model
latency, under `final-program-slot-1800-v1`. The existing300-second defaults,
policies, prompts and evidence limits remain unchanged. Other wall durations,
mismatched policies and larger undeclared budgets fail validation.

New ceilings:72 requests,3000 output tokens per response,1,440,000 aggregate
reserved tokens,14,400 action attempts,60,000 SDK calls and24MiB controller
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

## Not runnable through the trial adapter yet

This intentionally bounded first phase does **not** claim an1800-second trial,
publication, native XP ledger or live capture has passed. Existing adapter guards
still refuse it. Integration must resolve these remaining contracts together:

- `full_client_trial.validate_spec`: explicit successor trial budget/schema;
  total must allow controller1800 plus bounded login/restore/ordinary logout and
  upload/verification. Existing total1800/controller300 caps remain unchanged.
- `full_client_runtime`: scenario duration, expected request budgets, service
  lifetime, `_probe_video` maximum and full evidence/copy bounds. Do not silently
  inflate legacy operation or cleanup deadlines.
- `full_client_bridge`: start duration validation, adaptive origin subtraction,
  capture failure/frame count caps and runtime-owner capture validation.
- `serve-full-client`: current100MiB upload cap; make the larger cap depend on the
  authenticated run's exact frozen policy before reading payload bytes. Bound
  upload time/disk and temporary file cleanup without whole-video buffering.
- Shared video probing and publication: per-file bytes/packet arrays/timeouts,
  package/catalog total512MiB cap, anonymous verification and deployment quotas.
  A600MiB maximum cannot fit the old catalog ceiling unchanged. Choose a measured
  bitrate or explicit publication policy; do not weaken old package validation.
- XP-window/score/trial schema: current300-second windows and completeness need
  an explicit1800 wall contract, and fixtures must support ordinary level-up/save.
- Worker host manifests, finite coordinator plan, maintenance/expiry cutoff and
  backup reserve must cover these declared limits. No existing IDs are reusable.

Local tests use fake clocks and synthetic packet bytes, with no model calls or
native world. They prove deadline arithmetic, tamper refusal, no uncertain retry,
long ledger validation and mux/constructor policy selection. They are not real
30-minute game/capture evidence. Next integration should be reviewed and tested
as one frozen successor before one bounded live verification.
