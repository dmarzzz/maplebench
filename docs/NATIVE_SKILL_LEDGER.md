# Native skill evidence, version 1

`MapleBenchSkillLedger` is independent of the native XP ledger. Cosmic patch
`0003-native-skill-evidence.patch` observes ordinary movement, ordinary item use,
ordinary skill application, slot removal and the HP/MP mutation inside the native
stat lock. It does not move a character, grant a resource, validate physics, or
change an XP calculation. It is disabled unless the private skill journal
configuration is complete. These hooks are implementation work, not accepted
suite qualification evidence.

## Lifecycle and clock

The trusted runtime initializes the journal before login, then looks up the
configured ordinary character in its channel's `PlayerStorage`. After readiness,
it calls `MapleBenchSkillHooks.startWindow(character)` at the first-request
boundary. Initialization does **not** arm the clock. The response returns actual
server monotonic and wall start times. The caller must bind the first provider
request to that receipt, account for transport time, and retain the original
receipt; the old runtime start time cannot substitute for it.

The duration is exactly 120,000 ms. Scorers use `[0, deadline_elapsed_ns)` for
outcomes. Settlement events can remain in the journal after the deadline but
cannot become on-time outcomes. Before ordinary logout, the trusted runtime calls
`MapleBenchSkillHooks.sealWindow(character)`; both boundaries check configured
character/account identity and read the actual character, not request-supplied
stats. These calls provide no gameplay action or fixture restore.

Configuration uses `MAPLEBENCH_SKILL_JOURNAL`, `MAPLEBENCH_SKILL_TASK_ID`,
`MAPLEBENCH_SKILL_BINDING_SHA256`, `MAPLEBENCH_SKILL_RUNTIME_SHA256` and
`MAPLEBENCH_SKILL_DURATION_MS`, plus the existing trial/server-instance and
persistence character/account identifiers. Private paths and values stay outside
Git. The journal is create-only, mode 0600, with symlink ancestors refused.

## Byte and event contract

Each newline-terminated UTF-8 JSON object has these top-level fields:

- `schema_version: 1`, `source: cosmic_native_skill_ledger`, `kind`, `data`.
- `run_id`, `server_instance_id`, `character_id`, `account_id`, `task_id`,
  `binding_sha256`, `runtime_sha256`.
- `sequence` (zero-based), `event_id` (`e` plus eight decimal digits),
  `elapsed_ns`, `wall_ms`, `previous_sha256`.

The initial previous hash is 64 zeroes. Each following hash covers the exact
previous line **including its newline**. The collector must preserve original
bytes and externally pin the complete artifact's SHA-256; a hash chain alone is
not authentication. Limits are 100,000 events and 16 MiB, checked before writing.
Write/sync, clock, bound or hook failures prevent a complete terminal row. No
eviction, overwrite, gap-filling, or reconstructed event is permitted.

Header `data` includes actual `start_monotonic_ns`, `deadline_elapsed_ns`, and
`initial` actor state. Terminal `data` includes `complete`,
`event_count_before_terminal`, `qualification_claim: false`, and final `actor`
state. A missing terminal is invalid evidence. A terminal means the instrumented
stream was sealed without a detected fault; it does not assert every possible
native mutation path was instrumented or that a task passed.

Boundary actor state is `{item_id:2000005, quantity, hp, mp, max_hp, max_mp, alive,
online, snapshot_atomic:false}`. Quantity aggregates USE slots for that item;
online is native `isLoggedinWorld()`. Stat getters and the inventory snapshot
are separate reads, not a joint atomic state. The controlled safe fixture,
restricted input admission and linked mutation records are therefore necessary
qualification inputs. Boundary snapshots alone do not prove continuous survival.

## Native transactions

`transaction_begin` records transaction kind, subject ID, skill level and parent
transaction ID. Its event ID becomes the transaction ID. `transaction_end`
records the actual handler result. Nested helper/autopot calls have their own
IDs; their mutations cannot be attributed to the enclosing request. Sealing
with an open transaction is refused.

`resource_transaction` contains `transaction_id`, HP/MP before/after, maxima,
`route: apply_hp_mp_change`, and `native_stat_lock_held: true`. The measurements
surround `updateHpMp` while its existing stat write lock is held. Unrelated
mutations through this path have an empty transaction ID. Other resource paths
are **not** represented as exhaustive coverage or silently called regeneration.
Header `resource_coverage` is `apply_hp_mp_change_only`.

`inventory_transaction` contains `transaction_id`, `inventory_type`, `slot`,
`item_id`, slot quantity before/after, `route: inventory_remove_item`, and
`native_inventory_lock_held: false`. These are actual native slot mutations.
Upstream `removeItem` does not hold one inventory lock across its get/set/remove
sequence; the patch neither adds that locking contract nor claims it already
exists. Header `inventory_coverage` is `remove_item_only`: additions, trades and
refills must be excluded by the frozen fixture and input contract, not inferred
from an absence of removal events.

`item_effect_result` records the actual item effect's boolean return. This is
separate from the item handler return: upstream can remove an item and return
true even when its effect returned false. `item_transaction` contains aggregate
quantity and HP/MP endpoint snapshots, maxima, alive, actual handler result,
exact linked `resource_event_ids` and `inventory_event_ids`, and a route:
`ordinary_item_packet` or `native_item_helper`. The potion scorer must require
ordinary packet provenance, successful effect, the matching item decrement and
attributed resource mutation. A helper/autopot, passive wait, empty slot, dead
character or rejected effect is not a successful ordinary potion input.

## Movement and Teleport limits

`movement_accepted` records actual accepted server endpoint, map, life state,
fresh packet receipt time and absolute fragments: coordinates, received
foothold, stance, duration, native foothold endpoints and exact line consistency.
Client fragment durations are retained as client values; multiple fragments in
one received packet do not become independent 10 Hz server observations.

The existing server accepts absolute coordinates without validating movement
physics. It discards the received foothold in its normal state update and skips
Teleport fragment coordinates. Thus the header explicitly declares
`movement_physics_validated:false`, `coverage_source:accepted_movement_packets_only`
and `teleport_causal_link_supported:false`. It cannot qualify S1 or S2.
`skill_commit` records the actual ordinary `SpecialMoveHandler` apply result and
its resource child IDs, with empty `movement_event_id` and
`causal_displacement_link:false`. It never guesses that the next position belongs
to that cast. Existing client Teleport moves locally **before** sending the skill
request; the server can subsequently refuse its MP cost.

The minimum further work is a separately versioned movement protocol: retain
fresh sequence numbers and client simulation timing, validate received positions
against pinned native foothold geometry and a reviewed movement model, and send
fresh stationary/grounded samples at sufficient cadence rather than repeatedly
polling stale server state. For Teleport, a native cast identifier must span the
accepted skill cost and legal movement commit, with rejection preventing a
successful movement claim. This requires a reviewed client/server protocol and
collision semantics, not temporal nearest-neighbour matching or an animation
receipt. Geometry-only contact is not yet a physics certificate.

## Focused verification

`test/test_native_skill_ledger.py` applies the exact patch to licensed pinned
native method fixtures, then compiles actual item, inventory and resource method
bodies in inert Java harnesses. The journal harness exercises hash links,
create-only behavior, private permissions, identity/nested attribution, clock and
I/O failure, byte/event caps, boundary state and open-transaction refusal. These
are source tests; they do not start a world or establish deployed qualification.
