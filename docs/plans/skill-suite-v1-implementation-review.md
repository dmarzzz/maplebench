# Skill suite implementation review

Reviewed September 14, 2026 against design commit
`1df503bf55037bb6b3d4e519b5427dd38a2d9c34`. This document records implementation
findings; it does not change the draft design, schedules, task criteria, or the
meaning of older recordings. Progress is in `skill-suite-v1-progress.json`.

## What this release measures

The first release asks whether four fixed models can complete specific control
and resource tasks using the ordinary full client. Task completion is scored
from independently checked native evidence. Model latency consumes the task
clock. Each attempt has a fresh session and a restored, pinned fixture. The
development pilot and comparative cohort remain separate.

| Phase | Planned entries | Horizon | Gate |
| --- | ---: | --- | --- |
| Initial native qualification | 36 | 120 seconds maximum | Three tasks × three variants × four controls |
| Development pilot | 96 | 120 seconds | All initial native controls accepted; frozen execution configuration and budget |
| Remaining native qualification | 36 | 300 seconds | Buff upkeep, portals, and recovery |
| Comparative cohort | 576 | 120 or 300 seconds | Six qualified tasks; separate frozen cohort and funding/storage admission |
| Training qualification | 12 | 300 seconds | Exact-build native XP acceptance for three classes |
| Proposed long training | 96 | 1,800 seconds | Separate later authorization and acceptance |

There are 852 planned entries across these phases, including 72 native controls.
The 780 model entries include a later proposed training phase; they are not an
authorized, unconditional batch. A correctly rejected negative native control
passes its check without becoming a model success. Unstarted trials have no score.

## Findings that affect execution

1. **Movement proof is incomplete.** The existing server accepts client movement
   coordinates without validating the complete physical path. Polling that state
   ten times per second does not establish fresh grounded dwell. Platforming
   qualification requires fresh native movement evidence plus explicit geometry
   and physics validation. The producer reports this capability as unavailable
   until that path is implemented and qualified.
2. **Teleport acceptance and displacement are separate.** The current client can
   displace before the ordinary skill request is accepted. An animation, key
   acknowledgment, or nearby MP debit cannot establish the required causal link.
   The scorer must reject missing linkage, including the insufficient-MP control.
3. **Potion use can be linked through the real transaction.** The native item
   handler, item-effect return, stat change, and inventory decrement need linked
   evidence. The handler's boolean alone is insufficient: its return may not
   match the item effect's return. Boundary resource snapshots and a sealed ledger
   are also required for passive and empty-inventory negative controls.
4. **The old controller is a different protocol.** Its 300/1,800-second timing and
   request reserve cannot be relabelled as the new 120-second tasks. The new
   controller has a separate identifier, fixed limits, task-restricted keys, and
   inference-inclusive deadlines. It requires a qualified task contract before
   any model call. Native controls cannot enter its model path.
5. **Three worker lanes are not yet an accepted fleet.** Inventory currently
   establishes one existing runtime candidate and zero suite-qualified workers.
   Worker A/B/C in the design are planned assignments. An execution manifest must
   declare actual accepted workers and assignment; unrelated machines and expired
   leases are not silently reused as capacity.
6. **The publication format needs task-sized shards.** Older four-entry cohort
   pages and the 100-row research reader cannot represent this schedule. The new
   projection preserves every planned entry, stable experiment/trial numbers,
   task variant, repetition, model, configuration state and evidence references.
   A bounded manifest plus 21 phase/task shards keeps every denominator explicit.
7. **Video capacity is a separate gate.** Existing static publication limits stay
   in force. Hundreds of recordings require approved storage, byte hashes,
   retention/access rules and a reviewed publication adapter. A missing video
   cannot be hidden, silently dropped, or replaced by a different recording.

## Budget review

The standing authorization is $50 total; added account credits do not change
that cap. Existing spending and uncertain reservations must be reconciled before
new model dispatch. Native controls do not call a model.

Standard per-million input/output prices checked September 14, 2026 are
[$10/$50 for Astra](https://developers.openai.com/api/docs/models/gpt-6-astra),
[$4/$20 for Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol),
[$2/$12 for Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra), and
[$0.20/$1.20 for Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna).
These pages also specify a 1.25× input rate for cache writes. Execution must pin
standard service and reserve conservatively for the actual complete request
envelope plus maximum output. Discounts must not be assumed. These estimates
are admission ceilings, not billed-cost claims.

At the full short-task token ceiling, 24 trials per model permit 84,000 input
tokens and 12,000 output tokens per trial. Charging input at the cache-write
ceiling gives a conservative whole-pilot maximum of $64.7856 before prior spend,
worker costs or storage. This is an upper bound, not an expected cost: a smaller
actual request envelope can reserve substantially less. The controller must
stop admission at the available cap and retain incomplete coverage honestly.
The larger comparison is separately budget-gated.

## Burn-down and execution order

- [x] Pin the upstream design and preserve both schedule files unchanged.
- [x] Audit native movement, Teleport and potion semantics against task criteria.
- [x] Implement first-three-task immutable contracts and restricted SDK routing.
- [x] Implement the new controller kernel and deterministic deadline/failure tests.
- [ ] Complete and test native transaction ledger, clock binding and closeout.
- [ ] Bind real safe-map fixtures and verify ordinary login, potion use and restore.
- [ ] Implement and qualify fresh grounded movement and Teleport causal linkage.
- [ ] Complete all 36 initial native controls, recording every positive and negative.
- [ ] Publish the full progress table with explicit planned/executed configuration.
- [ ] Reconcile prior spending; freeze worker, model, fixture, scorer and storage bindings.
- [ ] Dispatch the 96 development trials in preserved order, updating each attempt.
- [ ] Review all pilot outcomes and a balanced set of original recordings.
- [ ] Qualify remaining tasks, then admit the separately budgeted comparison.
- [ ] Qualify native training XP before considering the proposed long training.

Every dispatched entry must be registered in the durable runtime journal by
`plan_entry_id` and execution-manifest hash. GitHub and the site are reporting
views, not queues. An uncertain launch or write reply is reconciled, never
replayed to fill a blank row. A protocol change creates a new configuration and
cohort. Historical demos remain visibly separate from this skill suite.
