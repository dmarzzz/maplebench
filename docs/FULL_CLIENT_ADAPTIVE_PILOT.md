# Five-minute adaptive full-client pilot

`full-client-adaptive-pilot-v1` is an explicitly separate, unranked protocol. It
repeats fresh observation, one exact model response, and unchanged model-authored
JavaScript under one 300-second monotonic wall clock. Inference, execution,
sandbox cleanup and pauses all consume that clock. There is no background combat,
automatic code repair, provider fallback, or replay of an uncertain request.

This pilot is not the proposed 30-minute research protocol. Initial/final native
persistence proves signed net XP across ordinary login/logout; it does not prove
15-second XP peaks, kill counts, gross XP or rate-normalized task scores. Those
fields remain unavailable until a native authoritative event-window ledger exists.

## Frozen configuration

Import `DEFAULT_PROTOCOL` and `prompt` from `scripts/full_client_adaptive.py` when
preparing a new protected scenario. Freeze the complete protocol object under
`adaptive_protocol`, and set `protocol` to `full-client-adaptive-pilot-v1`.
The default caps are 12 API requests, 3,000 output tokens per request, 120,000
aggregate reserved/actual tokens, 1,600 attempted actions, 6,000 SDK requests,
20 seconds per program and 4,194,304 bytes of complete SDK receipts. Reservations
are charged before dispatch and never recycled. Exceeding an evidence cap fails
closed, preserving partial evidence without manufacturing a valid trial.

The profile is exactly `{id, class_name, level, skill_keys}`. Neutral SDK slots
`PRIMARY_SKILL`, `SECONDARY_SKILL`, `BUFF_1`, `BUFF_2` press A/S/D/F. `skill_keys`
maps those tokens to the actual native skill names. Job, equipment, learned skill
IDs and native key types must be separately verified in each frozen baseline.
Hero aliases remain available only to the legacy protocol.

For the default pilot, the scenario has `program_seconds: 300`, the SHA-256 of
`prompt(adaptive_protocol)`, low reasoning effort, and bridge budgets:

```json
{"api_requests":12,"output_tokens":36000,"total_tokens":120000,
 "program_ms":300000,"run_ms":335000,"actions":1600,"sdk_requests":6000}
```

Trial spec version 2 adds `protocol` and uses, for example, these finite budgets:

```json
{"total_seconds":1200,"operation_seconds":360,"controller_seconds":300,
 "max_actions":1600,"max_api_requests":12,"max_output_tokens":36000,
 "max_total_tokens":120000}
```

The existing frozen readiness and settlement policies still apply: capture and
fresh populated-world qualification precede the first model call; completed
upload is observed before ordinary disconnect; native committed logout is required.
Recording permits 335 seconds at 2 Mbps with a 96 MiB hard upload cap. Inference
remains visible in the scientific recording; first-input cues are separate offsets.
The adaptive ffprobe path requires the companion publication change permitting
`maximum_ms=335000`; the legacy default remains 125000.

Pin `full_client_adaptive.py` in the web import closure, and pin it together with
`full_client_adaptive_evidence.py` and `maple_agent.py` in runner dependencies.
Prepare a new scenario/baseline identity and new attempt IDs; do not retrofit old
receipts or reuse a submitted attempt.

## Opt-in full-horizon reserve

For fresh cohorts, copy `FULL_HORIZON_POLICY` into
`adaptive_protocol.horizon_policy` before freezing the scenario:

```json
{"id":"full-horizon-reserve-v1","request_timeout_seconds":50,
 "settlement_reserve_seconds":5,"passive_observation_interval_ms":1000}
```

This policy requires 50 seconds for the request, the configured program allowance
(20 seconds for the current cohort), and five seconds of settlement reserve before
a new request starts. With 20-second programs, the last request can start at most
225 seconds into the run. The request timeout stays 50 seconds. The dispatch guard
runs again after readiness and request persistence; an unsent request remains
`not_started`, even if its request artifact was already written.

When the reserve closes, or confirmed API/token/action/SDK budgets are exhausted,
the controller passively observes the live world until the original 300-second
deadline. It sends no gameplay inputs or model requests during this interval. The
live HUD and recording say **Waiting for deadline**, retain exact model attribution,
and show the wall clock. Death, cancellation, stale observations and actual request
failures still stop early. Uncertain requests are never converted into confirmed
responses or retried. The last four seconds use cancellable sleeps; an observation
is never given a timeout shortened against the normal deadline.

The optional `horizon_wait` receipt records the original stop reason, monotonic
start/end offsets, unchanged counters and at most 301 compact character/freshness
samples. It omits monster arrays. Verification checks serial timing, full request
reserve and timeout, fresh bounded samples, full elapsed wall time, and unchanged
usage/input counts. Public evidence exposes wait timing and sample count, not raw
samples. This proves controller/collector consistency, not native XP-window scores.

The policy changes the exact prompt and scenario hash. Prepare new attempt IDs,
refreeze prompt/source/scenario pins and keep old fixtures separate. Absence of the
policy preserves the original prompt and early-stop behavior; old traces remain
valid. Do not reinterpret old short runs as having used the full horizon.

## Native-window progression variant

`NATIVE_PROGRESSION_POLICY` is a separate optional frozen `progression_policy`.
It permits ordinary level increases from the exact initial profile level through
200 only with the full-horizon policy and native XP-window runtime/scenario opt-in.
The prompt changes and requires a new scenario identity. It does not allocate
points, heal, change native stats, or retrofit old pilot receipts.

`verify_result` refuses that variant unless the native-window verifier supplies
its hashed native ledger and offline initial/final/session contract. Observed
levels are checked against actual native transitions. The ordinary adaptive
publication path cannot substitute a client counter or a caller's verified flag.
See [native XP windows](FULL_CLIENT_XP_WINDOWS.md) for the full acceptance contract.

## Evidence and closeout

`result.json` contains an `adaptive` trace and its `adaptiveTrace` reference to
`adaptive.json`. Each indexed cycle uses only paths beneath `cycles/000/` etc:
`api-request.json`, `api-response.json`, `program.js`, `program.json`, and
`execution.json`. Request metadata binds `maplebench_run_id` and string
`maplebench_cycle_index`. Provider model, unique response ID, usage, exact program
bytes, SDK arguments, fresh action observations, budgets and serial timing are
cross-checked across every cycle.

`full_client_adaptive_evidence.verify_result(result, artifact_root,
protocol=..., model=...)` returns checked counters, API intervals, wall elapsed
milliseconds and summed API milliseconds. It grants no score or publication.
`full_client_score.verify_trial_bundle` additionally verifies persistence schema
2, native logout commit, baseline parity and signed net XP. Large controller data
stays in its hashed artifact rather than expanding the bounded control journal.

The runtime writes a schema-3 `adaptive_pilot` publication candidate with an
unverified peak score and no ranked eligibility. Public curation is a separate
adapter. Legacy trial schema 1 and ranked publication schema 2 retain their
single-response evidence requirements. Synthetic tests do not establish live
runtime acceptance or a successful five-minute API run.

An expired keyboard request now creates one private `input-timeout.json` receipt
before the relay clears its pending command, under the same condition lock. Its
schema 1 records the owned run/command, validated keys and hold, request budget,
dispatch time, request/dispatch/latest poll freshness and any matching ACK seen
before that timeout snapshot. The bounded receipt is at most 4096 bytes and
contains no raw observations, model text or arbitrary browser diagnostics.
`dispatched: true` means selected for the browser response; it does not prove
delivery or key-down. A missing matching ACK remains unknown, including any ACK
arriving after the pending command has already cleared.

This create-once diagnostic preserves `outcome: uncertain`, the original
`endpoint_timeout`, and all existing admission, hold and ACK deadlines. It cannot
accept an input, waive a capture failure or authorize a retry. Later timeouts
never overwrite the first receipt. If storage fails, the original timeout still
propagates and the controller records `inputTimeoutDiagnosticStatus: write_failed`.
Private failure backups should retain this file alongside `input-failure.json`
and `capture-failure.json`; it is not a public score or recording artifact.
