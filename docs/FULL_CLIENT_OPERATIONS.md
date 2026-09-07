# Operations admission foundation

The coordinator can now permanently close a settled group with `seal`; see
[finite experiments](FULL_CLIENT_EXPERIMENTS.md#permanently-closing-a-group).
`scripts/full_client_operation_gate.py` supplies the separate admission primitive
needed to keep another operation out between trials and during restoration.
**It is not integrated into the production commands yet.** Existing trial,
experiment and normal-lifecycle commands do not acquire this new gate. No live
registry has been initialized, and there is no automatic restoration wrapper.

## Supported source contract

Explicit `initialize_registry(existing_attempt_root)` creates only a private
`.operations` directory beneath the existing canonical attempt root and its
`.gate.lock`. It returns the actual gate device/inode pin. An existing or partial
registry is refused. Production defaults require root ownership, directory mode
0700 and file mode 0600; an explicitly supplied test owner must be the effective
user. Setup never creates the attempt root or any world lock.

`OperationGate(attempt_root, pin).locked()` acquires that exact existing gate
nonblockingly and yields a process-local lease. Separate open descriptions cannot
enter concurrently. The lease supports three operations:

| Method | Required evidence | Result |
| --- | --- | --- |
| `begin(id, kind, authority_ref)` | New ID, validated private authority and no pending or malformed earlier claim | Create-only, fsynced claim reference |
| `reconcile(claim_ref)` | Exact existing claim path and hash; no other pending claim | Pending status or the original completed marker; no replay |
| `complete(receipt_ref)` | Active claim, matching terminal receipt and private referenced evidence | Create-only, fsynced terminal marker |

References use `{path, sha256}`. Claims bind their operation ID, kind, authority,
creation time and original owner. Supported kinds are `finite_group`,
`standalone_trial` and `standalone_lifecycle`. Completed IDs cannot be reused.
Closing the lease closes only its own descriptor; it never explicitly unlocks
another copy of that open description.

A terminal receipt names the exact operation and claim hash, states completion
and quiescence, and binds one to sixteen private JSON evidence files. The gate
checks their hashes and file protections. **The integrating caller must prove
actual service, trial and renderer quiescence.** A matching JSON statement alone
does not establish those semantics, successful gameplay, saved XP or restoration.

## Interruption and trust boundaries

A process exit releases its descriptor but leaves its pending claim. That claim
still blocks unrelated admission. There is no owner-death retirement, timeout
waiver, deletion, takeover or arbitrary borrowed-descriptor API. Partial claim
publication leaves a blocked directory; corrupt or changed authority/evidence
also blocks admission. A lost publication reply requires explicit observation
of the existing exact claim rather than a new ID.

The module refuses symlink, ownership, permission, hard-link and inode changes.
Reads are bounded by file size, total bytes, inventory count and checked elapsed
work. Integrators must also impose hard process resource limits: filesystem calls
are not forcibly interrupted by these checks. Protected ancestor directories
remain a trusted-host assumption.

## Remaining integration

Every mutating entrypoint must participate in the same derived gate before this
can provide exclusion across commands. A finite-group wrapper must hold only
this gate while each child runner obtains its existing world/queue/runner locks.
It must permanently close the group, verify every submitted outcome and actual
current persisted state, then invoke the existing normal lifecycle under
explicit restoration authority and a separately reserved deadline.

The real child runner needs a verified inherited-capability protocol before it
can join the parent's operation. The current lease deliberately refuses use
after fork and provides no such join mechanism. The bridge's existing two world
lock descriptors must remain unchanged. Uncertain trial or service outcomes must
still stop for exact-operation reconciliation; no automatic API retry is implied.

Twenty-four focused offline tests passed on the runtime host in a serialized,
memory- and CPU-capped job. They exercise real flocks, process exit with a surviving claim,
close-only descriptor release, immutable completion, reference corruption,
publication failures and resource bounds. These tests do not run a model, start
services or establish unattended production acceptance.
