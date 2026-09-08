# Finite per-completion publication

`full_client_follow_publication.py` watches one explicitly selected four-model
cohort and publishes its verified results through the existing exporter, catalog
builder and Vercel driver. It does not admit trials, operate the game, recover
failures, call a model, manage credentials or provision infrastructure. No live
watcher is installed by this source change.

The local CLI accepts `--config PATH --config-sha256 SHA --state-root DIRECTORY`.
The library entry point is `follow(config_path, config_sha256, state_root)`.
Use an immutable, fully populated private configuration and a shared private
state root. Every watcher and manual publisher for the same project must respect
the publication handoff; the current manual publisher must finish before the
watcher starts. There is no background daemon or automatic restart policy.

## Configuration and trust boundary

The exact schema is version 1 with protocol `finite-publication-follow-v1` and
the following fields. All `{path, sha256}` references are exact, protected local
files unless explicitly described as remote identity below. Private configuration,
state, evidence and command receipts stay outside Git and outside public payloads.

| Field | Required value |
| --- | --- |
| `cohort` | `{plan: {path, sha256}, runtime_manifest_sha256, class_id, attempts}`. The plan path identifies the already-frozen remote plan; it is not executed. `attempts` is exactly four `{id, model}` rows in Astra, Sol, Terra, Luna order, with their exact model IDs and fresh planned run IDs. |
| `source` | `{path, commit}` for the clean local checkout running this module. Source is rechecked during the watch. This is separate from the exporter's frozen evidence-verification checkout. |
| `observer` | `{argv, dependencies}` for one reviewed, read-only local adapter. It returns the compact observation below. Every executable/script/config path supplied as an absolute argv element must appear in the dependency hashes. |
| `exporter` | `{command, config, receipt_root, completion_prefix}`. `command` is the same pinned argv/dependencies form. Its argv ends in `--config PATH --config-sha256 SHA`, bound to `config`. That file must select this exact plan, class and four IDs using the existing completed-evidence exporter contract. The coordinator appends only `--attempt-id ID` and optionally `--snapshot`. |
| `catalog` | `{cohorts, previous_cohorts, archive, output_root}`. At most two already-published other current classes and three previous cohorts, using existing schema-2 catalog references. The selected cohort is added as primary. Archive retention/retirement remains the catalog's existing evidence-based rule. |
| `publication` | `{project_link, public_origin, executable}`. Hash-pinned existing Vercel project-link JSON and executable; the public origin must satisfy the existing driver. Local CLI authentication remains private and is never placed in argv. |
| `seed` | `null`, or the explicit already-published import described below. A success boolean is insufficient. |
| `bounds` | `{}` defaults to 3,600 watch seconds. The sole optional key is integer `watch_seconds`, from 5 through 7,200. |

The command roles are an **operator trust boundary**. Their hashes prove which
reviewed adapter/configuration is being used; a hash does not prove that arbitrary
code is read-only. The operator must review the observer and exporter dependency
closure before signing this configuration. No model output or observed data may
choose argv, paths, executable hashes, project, plan or class. The coordinator
does not interpret shell strings, accepts no shell or inline-program command,
and never appends an unselected attempt ID.

The observer's exact JSON object is:

```text
{
  schema_version: 1,
  plan_sha256: SHA,
  runtime_manifest_sha256: SHA,
  class_id: CLASS,
  cohort_terminal: BOOLEAN,
  attempts: [
    {id: ID, model: MODEL, status: STATUS,
     journal_sha256: SHA_OR_NULL, completed_at_ms: INTEGER_OR_NULL},
    ... exactly four rows in the configured order
  ]
}
```

The reviewed observer must check the original pinned remote plan/runtime and
read stable journals without acquiring gameplay authority. `completed_at_ms`
comes from the actual successful `attempt_completed` event, not observation time,
score calculation, recording upload or publication. It is positive only for a
completed row; every other status uses null. The journal hash may be null only
for missing pending or withdrawn attempts. Supported statuses are `pending`,
`running`, `recovering`, `completed`, `failed`, `interrupted`, `recovered`,
`withdrawn`, and `unknown`. Unreadable transport is an observer failure, not a
fabricated set of unknown results. `cohort_terminal` requires the original
coordinator's terminal/closed evidence; the watcher never creates that evidence.

No new all-failed snapshot adapter is included. If changed terminal outcomes
exist with no completed anchor, the watcher persists all four observations and
stops with `snapshot_adapter_required`. An existing completed anchor can use
the accepted exporter's `--snapshot` path to publish later failure outcomes.

## One finite sequence

The watcher holds a nonblocking project lock, keyed by existing project and
organization IDs, for the whole invocation. All watchers must use the same
private state root. The original lock inode is checked before export and
publication. Different state roots cannot coordinate ownership: all manual and
automatic deployment paths must use the designated project root and explicit
sole-owner handoff. Existing per-package and Vercel submission locks remain in force.

It polls at most once every five seconds and allows no more than
`floor(watch_seconds / 5) + 1` observations across all resumes. The original
wall and monotonic deadlines are persisted and never renewed. At most nine
changed-outcome operations are permitted. Exhaustion produces `unfinished` or
a bounded refusal while preserving observed state; it never silently resets
the budget or claims four completed runs.

For each new completed member:

1. Persist the exact observation, selected anchor and phase intent before the
   existing exporter is called. The exporter backs up the completed private
   evidence, prepares the public cohort package and transfers only its allowlist.
2. Verify the exact export receipt, plan/class/model/journal binding, protected
   private backup receipt and archive bytes, and original public package. Keep
   the package's four outcomes. If a sibling completed during export, defer
   publication until that sibling's completed export/backup has also been
   verified. Multiple already-completed members may share one subsequent update.
3. Save one immutable schema-2 catalog request and compose it through the existing
   catalog CLI. Verify its source package set, inventory and primary binding.
   Retain the existing archive until the catalog has a valid accepted four.
4. Save publication intent, then call the existing Vercel driver with the exact
   package, catalog payload, inventory, project and public origin. Only its
   verified production receipt can finish the operation. Match every expected
   public-file hash and video range proof before recording local completion.

Running heartbeat/hash changes alone do not cause deployments. Changed terminal
outcomes use a completed anchor's snapshot export, without labeling a failed
member as a successful recording. Zero/negative XP, no-ops and failed/unknown
rows retain the existing projector's treatment. The watcher does not rewrite
scores, recordings, gameplay IDs, class fixtures or source assets.

External observer calls have at most 15 seconds, existing exports at most 720,
catalog composition at most 120 and the existing deployment step at most 300.
Each is additionally clipped to the remaining original watch deadline. Child
process groups are stopped on timeout, and stdout/stderr are bounded to 2 MiB
each. Raw command output and error text are discarded; durable status uses
allowlisted error codes. Local evidence reads retain the existing file limits.

## Resume and uncertainty

Resume only with the **identical config hash and state root**. Every phase has
an exclusive, fsynced intent. Orphan operations, changed source/config, modified
backups, conflicting receipts, new journal bytes for a completed result and
ambiguous project ownership stop the watcher.
A saved `complete` invocation only rechecks local publication proofs on resume;
it cannot restart observation, export or deployment, even after its watch deadline.

- A lost completion-export reply can use only its exact known receipt path:
  `receipt_root / (completion_prefix + attempt_id + ".json")`. The whole receipt
  and backup/package bindings are rechecked. If absent, return `follow_export_uncertain`;
  never call the exporter a second time for that intent.
- Snapshot receipt names depend on content. A lost snapshot reply therefore
  remains uncertain; this implementation does not search private directories or
  generate a replacement snapshot to guess what happened.
- Catalog composition can repeat only its identical immutable request. It has
  no remote publication side effect and reuses its content-addressed output.
- Vercel resumes through the existing exact marker, payload and metadata
  reconciliation. A lost reply never causes a fresh submission. Uncertainty
  stops later alias updates until the same operation is reconciled.

The coordinator's publication marker does not substitute for the Vercel
driver's intent. If a child never wrote a Vercel submission marker, the existing
driver decides whether any new submission is safe. The coordinator never deletes
markers, changes a payload under a claim, or interprets a missing reply as failure
with permission to resubmit.

## Importing a manually published result

Use `seed = {observation, exports, primary_export, publication}`. `observation`
is a pinned compact observer document for the published snapshot; `exports` is
one to four pinned completed-export receipts; `primary_export` is one of them.
`publication = {complete, verification, catalog}` contains hash-pinned actual
`publication-complete.json`, `vercel-public-verification.json`, and catalog result
references for the same primary package. All declared completed members must
already be represented and backed up. File/range proofs, project/origin and
package content and observed outcomes must match, including configured catalog
sources. Existing successes are imported without another export or deployment.
The seed's snapshot timestamp is recorded as `seed_snapshot_upper_bound` with
`completion_to_known_public_ms`. A later snapshot cannot establish an earlier
member's exact first-publication time; imported timing therefore does not make
a 60-second first-delivery claim.

## Latency and completion meaning

Each publication records deployment-step latency separately from actual
`attempt_completed` to first verified public visibility. It also records
observation-to-public time. A previously published member keeps its original
first-publication measurement when a later sibling or failure snapshot is added.
The 60,000 ms target applies to **end-to-end latency**, not just upload/deployment.
A slow but valid result is still published honestly. Unit tests with a synthetic
55-second end-to-end interval and three-second deployment interval demonstrate
the distinction; they are not a production latency measurement.

`complete` means the pinned cohort is terminal and its latest observed outcomes
were published. `unfinished` means the finite watch ended. `blocked` or
`uncertain` preserves the exact reason and pending operation. No status claims
that an API run was retried, a new cohort was launched, or all recordings passed.
Root's reviewed handoff and an actual production invocation are still required
before this source can claim automatic per-completion delivery.
