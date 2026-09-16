# Executable skill-task contracts and native evidence

`full-client-skill-tasks-v1` is a separate executable contract for the first three
tasks in the frozen skill-suite draft. It does not edit that draft, launch a
trial, qualify a fixture, or change any historical protocol. The remaining three
tasks are reserved and are rejected by this contract factory.

`full_client_skill_tasks.contract` requires a complete fixture binding: geometry,
initial state, class, level, task variant, resource and keymap hashes, baseline,
native definitions, and source/client/server/SDK/scorer identities. The baseline
and proof artifacts remain private. `validate_contract` reconstructs the exact
canonical value; `allowed_keys` and `sdk_scenario` expose only that task's named
controls. `descriptor` contains public task geometry, goals and resources without
private identities, artifact hashes or qualification claims.

Each task has a 120-second ceiling that includes inference. Model use additionally
requires a pinned qualification receipt and at most four requests, 3,000 output
tokens per request, 96,000 aggregate reserved tokens, 10-second programs, 600
actions and 2,000 SDK requests. The runtime must verify the qualification receipt;
a digest alone does not grant admission. Native controls have zero API requests.
Requests require 15 seconds remaining; the timeout is at most 30 seconds or the
remaining time minus 10 seconds. Inputs must fit their complete three-second
acknowledgment allowance before the five-second settlement reserve. No evidence
at or after the original deadline can rescue the task outcome.

## Current verifier support

`full_client_skill_task_verifier.verify_ledger(raw_bytes, task_contract, expected)`
returns a private receipt with `success`, `gameplay_failure` or `invalid` status.
`expected` must come from separately verified runtime artifacts and contains
`run_id`, `server_instance_id`, `character_id`, `account_id`, `runtime_sha256`,
`ledger_sha256`, `start_monotonic_ns`, `start_wall_ms` and `duration_ns`.
The verifier never extracts these expected identities from the ledger itself.

It checks the exact raw JSONL bytes and hash chain, event sequence, native arm and
seal boundaries, frozen initial resources, online identity, and native monotonic
clock against wall time with the plan's 25 ms drift bound. The producer has a
broader 250 ms journal guard; this verifier rejects evidence outside the tighter
contract. The ledger may close up to five seconds after the deadline, but only
strictly earlier task events score. An unmet goal requires the full window unless the native terminal proves death;
a proven success permits early closure.

| Task | Present capability | Result today |
| --- | --- | --- |
| S1 platforming | Accepted client movement and static foothold geometry; no fresh stationary grounded/physics coverage | Invalid; cannot qualify |
| S2 native Teleport | Native skill commit and MP changes; no causal displacement link | Invalid; cannot qualify |
| S3 potion use | Ordinary item handler, linked inventory decrement, atomic HP/MP mutation, actual effect result | Source verifier implemented; live qualification pending |

S3 requires the one shared Power Elixir (`2000005`) to go from one to zero in an
ordinary item packet transaction. Its real inventory child must precede its
atomic resource mutation and successful effect result, matching the current
server handler. The exact linked native MP transition must reach at least 80%
while alive before the deadline. Neither a key acknowledgment, the handler's
return value alone, a native helper call, passive regeneration, nor final MP
alone proves this criterion. A consumed item whose effect returned false is a
known gameplay failure, not a successful restoration.

The current producer explicitly covers `applyHpMpChange` resource mutations and
`removeItem` inventory mutations only. Boundary snapshots are native but are not
atomic. The verifier preserves these limits: it does not claim a complete history
of every possible HP/MP writer, authenticate the collector, establish arbitrary
movement physics, certify save/restore, or authorize publication. Those remain
separate runtime gates. Missing or inconsistent transaction evidence is invalid;
a complete passive/no-op window without the item effect is gameplay failure.

The small public outcome is `{criterion_met, completion_ms, alive,
items_consumed, mp_fraction}` for S3. Successful MP ratio and survival refer to
the linked restoration; failed outcomes use the final native snapshot. Raw
transaction IDs, character identity and detailed evidence remain private.
Native-control pass/fail is derived separately from its scheduled positive or
negative expectation, never counted as a model result.

The focused Python fixtures are synthetic and explicitly labelled. They exercise
contract mutations, malformed or incomplete evidence, raw-byte tampering, clock
and sequence discontinuities, cross-transaction references, passive recovery,
empty inventory, false effect returns and the half-open deadline. Passing these
tests is source verification, not evidence of a live task or a complete skill kit.
