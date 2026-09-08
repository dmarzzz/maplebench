# Pre-runtime abort

`full_client_pre_runtime_abort.py` is an explicit operator closeout for one
narrow failure: the initial status inventory rejected the operation timeout,
then a read-only recovery status succeeded and cleanup refused the orchestrator
identity before entering runtime work. It accepts that exact event sequence.
It never runs cleanup, alters the failed journal, seals the coordinator, resets
the world, or claims a model score.

The CLI reconciles the original finite-group authority and exact claim. It holds
the operation gate, coordinator serialization, and existing world/queue/runner
locks. It verifies stopped services, no original coordinator/runner processes,
empty original group cgroup, settled idle browser, offline baseline snapshot,
unchanged input hashes and absence of per-attempt runtime artifacts. A shared
120-second deadline bounds native observations. Run it in a separately bounded
operator unit as an additional process lifetime/memory cap.

Private config schema version1 contains these explicit fields:

- `authority`, `claim`, `coordinator`, `journal`, `runtime`, `snapshot`,
  `implementation`: exact `{path, sha256}` references. `implementation` is the
  protected abort module itself; it is separate from the original authority.
- `original_source`: canonical scripts directory from the original authority's
  source closure. Loaded old modules must match that closure before observation.
- `attempt_ids`: all four original IDs in plan order, including unsubmitted IDs.
- `group_unit`, `group_invocation`: original group service and invocation identity.

Invoke `python3 scripts/full_client_pre_runtime_abort.py --config PRIVATE.json
--config-sha256 SHA256`. Config and evidence JSON stay mode0600 in private0700
directories. Do not copy host configuration into this repository.

Evidence is create-only under the attempt root's `.pre-runtime-aborts` directory.
The typed proof binds the original failed journal, coordinator, plan, authority,
claim, configuration, implementation and measured observations. The same original
gate claim is completed with this proof as its sole evidence. The certificate
then binds the actual gate terminal marker and its receipt; the original trial
remains failed and ineligible for publication.

A future runner accepts this failed journal only after independently validating
that complete chain. Every ID in the old plan is permanently retired. Partial,
changed, copied or malformed evidence blocks future admission. If a write reply
is lost, rerun only this exact config: the existing intent/proof/terminal is read
and reconciled. Existing proof is never replaced. No terminal claim means no
exemption. No alternate config may take over a partial abort.

## First live acceptance

On September 8, the original cloud cohort failed its initial inventory status
check before restoring a database, starting a trial world, or calling a model.
The attempted recovery reached a process-identity refusal without creating
backend state. The reviewed abort command then completed the original admission
claim under the existing locks in 32.168 seconds. Independent verification
confirmed the failed journal was byte-identical, all four original IDs were
blocked, and a distinct future ID could pass the quarantine scan.

The production-owner Linux test run passed all 13 abort tests. An earlier
unprivileged run correctly rejected the root-owned protected source in its three
writer integration cases; the actual command is restricted to the root operator.
No model calls occurred during this acceptance. This verifies the specific
pre-runtime abort contract, not recovery of a world that has already started.
