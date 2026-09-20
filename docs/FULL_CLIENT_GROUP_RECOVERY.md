# Recover a failed entry under its original group claim

Future finite groups can use `recover-entry` to run bounded cleanup through the
original pinned trial CLI. The parent retains the group's admission claim; the
child proves the inherited admission before taking the ordinary world and queue
locks. It executes `recover`, never `run` or another controller request.

This path must be present in the source frozen for the group. It cannot retrofit
an older claim by changing its authority, source files, plan or adapter. A proven
untouched failure without native backend ownership still requires the separate
pre-runtime abort procedure; this command cannot fabricate cleanup evidence.

After the original group process has stopped, inspect its failed journal and
coordinator. Supply both exact hashes and the original authority/claim references:

```sh
python3 scripts/full_client_experiment.py recover-entry \
  --plan /private/group/experiment-plan.json \
  --directory /private/group/experiment \
  --operation-authority /private/group/authority.json \
  --operation-authority-sha256 AUTHORITY_SHA256 \
  --operation-claim /private/attempts/.operations/OPERATION_ID/claim.json \
  --operation-claim-sha256 CLAIM_SHA256 \
  --attempt-id LAST_SUBMITTED_ATTEMPT_ID \
  --journal-sha256 FAILED_TRIAL_JOURNAL_SHA256 \
  --coordinator-sha256 COORDINATOR_SHA256 \
  --timeout-seconds 120
```

The timeout is 1–300 seconds, with the existing five-second child-launch allowance.
It is an explicit cleanup budget, separate from the original gameplay budget.
Original API/token reservations remain charged; recovery does not refund uncertain
provider usage or make the failed attempt eligible for a score.

Only the last submitted, unresolved failed/interrupted entry can be selected.
Earlier submissions must be settled or explicitly retired before launch, and
later IDs must remain absent. Before entering the child, the parent stores an
exact copy of the failed journal and an immutable descriptor in `recoveries/`.
The descriptor binds the original claim, plan, coordinator, failed journal,
request, adapter and timeout. The inherited envelope binds that descriptor.
The child checks the failed journal hash again under the runner locks.

The command launches at most one recovery child per attempt. If the reply is
lost, repeating the exact command checks the existing recovery descriptor and
saved native cleanup evidence. It returns success only when the actual journal
is recovered, its original failure events and usage remain intact, and the
ordinary final status/backend receipts prove cleanup. Otherwise it stays
quarantined. It never launches a second cleanup child merely because an outcome
is uncertain. An interrupted descriptor or failed cleanup needs explicit operator
investigation; deleting receipts to force another child is not recovery.

Successful recovery leaves the coordinator unchanged and the group claim pending.
The operator can then explicitly `resume` the still-valid original plan, which
submits only later entries within its remaining limits, or `seal` the exact
coordinator to permanently withdraw future entries and complete the claim.
Recovery itself performs neither action. A lost completion write can be repaired
from the same saved evidence without another child or model request.

The private completion receipt identifies the descriptor, recovered journal and
backend state, with `new_api_requests: 0` and `publication_eligible: false`.
The root/Linux tests use actual CLI parsers, parent/child processes, inherited
flocks and lock-retaining guards with a synthetic cleanup-only backend. They do
not operate a game, database, browser or model provider.
