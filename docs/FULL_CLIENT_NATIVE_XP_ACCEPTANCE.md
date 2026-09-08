# Native XP-window acceptance envelope

`native-xp-ledger-acceptance-v1` is a separate zero-model acceptance protocol.
The read-only verifier in `full_client_native_xp_acceptance.py` does not launch a
world, grant locks, restore a database, or accept adaptive API evidence. The
existing adaptive window verifier remains unchanged.

The frozen scenario binds the ordinary finite native recipe, baseline hash,
experience-table hash and normalization. One control submission must make zero
API calls, use no model, and finish within the recipe's 30-second bound. The
session remains owned for a separate fixed 300-second interval. At most 301
compact status samples cover that interval with a monotonic clock, bounded gaps,
matching native identities and fresh rendering. The passive collector schedules
against the original absolute monotonic deadline and never retries uncertain
reads or writes. It accepts no control/action callback.

The envelope independently checks the baseline/reset, offline initial/final
snapshots, ordinary logout chronology, persistence journal, native XP hash chain,
phase log and complete terminal save. It then calls the existing signed native
window scorer. At least one positive transaction inside the fixed interval is
required for the XP-hook acceptance result. Complete zero windows produce an
explicit insufficient-transaction result; missing coverage is rejected. Later
transactions remain part of persisted reconciliation but cannot prove the
in-window hook or improve its window score.

Returned windows are diagnostic. The result remains ineligible for publication
and requires separate visual acceptance; it does not claim level-up or loss-hook
coverage merely because those arithmetic unit tests passed.

## Remaining executor boundary

A future operator executor must bind the exact source, immutable candidate JAR,
new runtime inventory and baseline; hold the normal operation/world/queue/runner
locks; create durable single-use control/save/restore intents; preserve the short
native recording; and ordinary-logout/restore under the same ownership. This
module deliberately provides no dispatch CLI. A valid offline envelope cannot
by itself authorize that executor or attest cleanup. Existing live pilot IDs,
receipts and runtime remain unchanged.
