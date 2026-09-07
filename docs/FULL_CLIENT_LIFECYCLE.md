# Explicit normal-runtime restoration

`scripts/full_client_lifecycle.py` provides a private Linux operator command for
restoring the existing normal Cosmic service and queue worker after completed
trial cleanup. The trial runner still finishes with Cosmic stopped. Restoration
has its own durable journal and deliberately separate authority.

The command does not provision infrastructure, reset game data, stop or restart
a service, submit an API request, or replay an uncertain start. It requires
existing services, reviewed configuration, existing world/queue/runner locks,
terminal clean attempts, an unchanged offline character snapshot and a fresh
settled waiting browser. Missing prerequisites cause an explicit refusal.

## Invocation and private inputs

Run the command as root on the Linux runtime host under the shared-host resource
policy. The private JSON configuration supplies all paths, service identities,
source hashes and limits; never copy it into the repository. The command applies
its configured address-space, CPU-time, CPU-affinity and wall-clock limits.

```text
full_client_lifecycle.py --config PRIVATE_CONFIG check --request HANDOFF --sha256 HANDOFF_HASH
full_client_lifecycle.py --config PRIVATE_CONFIG start --request HANDOFF --sha256 HANDOFF_HASH
full_client_lifecycle.py --config PRIVATE_CONFIG reconcile --journal JOURNAL --sha256 JOURNAL_HASH
```

`check` validates prerequisites while briefly acquiring the existing locks. It
may create the command's own private serialization lock. It does not start a
service or create a restoration attempt. `start` creates one new operation;
an existing unfinished operation must be reconciled explicitly.

The configuration includes these bindings; `validate_config()` is the exact
schema authority:

| Binding | Purpose |
| --- | --- |
| `state_root`, `attempt_root` | Existing private lifecycle journal and trial evidence directories |
| `locks` | Existing world, queue and runner paths, device/inode, owner and mode |
| `services` | Existing world helper plus exact normal Cosmic/worker/web units, executable hashes, argv, UID, effective properties, environment, drop-ins and file hashes |
| `source_files`, `commands` | Pinned lifecycle/dependency source and existing systemctl/MySQL executables |
| `mysql`, `queue_database` | Fixed read-only character/account collection and an empty experiment queue |
| `admin_socket` | Existing web process's private status endpoint, checked with kernel peer credentials |
| `native` | Existing native log, exact startup/error markers, owned game ports and byte/descriptor bounds |
| `worker_receipt_directory` | Existing worker-owned mode-0700 directory for create-only first-idle receipts |
| `min_available_bytes`, `limits` | Explicit capacity admission and bounded command/readiness/idle/resource budgets |

The hash-bound handoff names the operation ID, boot ID, config hash, exact
terminal attempt journals/backend states, offline snapshot, stopped invocation
IDs, web instance and browser run ID. It cannot authorize a different machine
boot, configuration, inventory or active character session.

## Durable transitions

Before starting Cosmic, the command records its intent and previous invocation.
It then binds the new PID, start ticks and invocation ID, verifies the actual
process and waits for native startup evidence and sockets owned by that PID.
The native evidence must distinguish bytes written after this start from the
pre-start file boundary; an ambiguous same-inode rewrite is refused. A new file
generation requires independent birth evidence as well as exact process-FD
ownership. An unsupported log generation is a configuration/acceptance gate,
not permission to reuse an old online marker.

After native readiness and another quiet/capacity check, the command durably
records the worker handoff and closes its three world/queue/runner descriptors.
It retains the separate lifecycle serialization lock while starting the worker.
The worker must acquire its usual world/queue locks itself. Command supervisors
retain inherited ownership until their command process group is gone, including
after operator death; descriptors are closed rather than explicitly unlocked.
The small retaining guard is exempt from CPU-time exhaustion; the operator and
command child retain their configured CPU limits. If a descendant cannot be
terminated, the guard keeps the locks and requires operator investigation. An
outer supervisor must not kill that guard to manufacture a clean handoff.

The worker hook is opt-in through `MAPLEBENCH_LIFECYCLE_RECEIPT_DIR`. Its receipt
is written only at the first idle point, before any trial has been claimed. It
binds the worker invocation/PID/start ticks, boot, unchanged Cosmic instance,
actual worker source hash and the two held lock descriptors' inodes. Publication
is create-only. The lifecycle command independently checks that receipt, the
empty queue, worker lock ownership and absence of a worker child before marking
restoration complete. The supported hook uses the existing
`maplebench-cosmic.service` target; an alternate target is refused.

## Interrupted commands

Reconcile only the exact current private journal hash. An observed Cosmic
instance is reused; it is never restarted. Once worker-start intent exists,
reconciliation only observes the existing worker and completes verification; it
does not acquire its locks or issue another start.

If a start reply was lost before its new identity was journaled, reconciliation
requires an explicit private instance observation with `--observation` and
`--observation-sha256`. That document binds operation, boot, role and exact
PID/start ticks/invocation. An absent, replaced or ambiguous instance is refused.
This evidence must be reviewed against the live host; a sleeping process alone
cannot substitute for the worker receipt.

This source command and its offline failure tests require deployment acceptance
before being used for restoration. Existing live acceptance remains bound to
its own source revision. Private one-off recovery helpers already consumed by
earlier operations must never be replayed.
