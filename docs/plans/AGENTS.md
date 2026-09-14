# Trial execution and progress updates

These instructions apply when implementing, qualifying or executing the suite in
`../NEXT_SIMULATION_PLAN.md`, including work initiated from another agent task.

## Read first

- `../NEXT_SIMULATION_PLAN.md`: task criteria, qualification gates and failure rules.
- `skill-suite-v1.json`: proposed design and unresolved bindings.
- `skill-suite-v1-schedule.csv` and `skill-suite-v1-native-checks.csv`: planned entries.
- `skill-suite-v1-progress.json` and `skill-suite-v1-progress.md`: reported progress.

The plan is a draft with execution disabled. A progress update does not authorize
API calls or live trials. Use the user's existing execution authorization and the
accepted runtime's admission requirements. Confirm exact qualified bindings before
launching any phase. Historical runs are not results of this new suite.

## Update during execution

1. Before dispatch, reconcile progress with the durable runtime journal. An absent
   progress entry is not proof that an attempt was never submitted. Never replay
   an uncertain submission merely to fill the schedule.
2. Register the `plan_entry_id` and frozen execution-manifest hash when a trial is
   admitted. Keep live ownership, locks, private paths and raw receipts in the
   ignored runtime state. GitHub progress is a reporting view, not a job queue.
3. After each terminal trial or native check, update its entry in the progress
   JSON from verified receipts. Upsert by unique `plan_entry_id`; preserve prior
   outcomes and corrections in `updates`. Use `success`, `gameplay_failure`,
   `invalid`, `not_started` or `in_progress`. A negative native control that is
   correctly rejected is a passed check, not a model gameplay success.
4. Recompute phase counts from entries; distinguish reported progress from the
   planned denominator. Update the Markdown summary after every completed block
   and immediately when a blocker, qualification decision or protocol revision
   changes the next action. Retain all failed and invalid entries.
5. Commit and push sanitized progress after each completed block or material
   blocker, subject to repository checks and existing publishing authorization.
   Fetch before pushing; merge concurrent progress by entry ID and reconcile
   conflicting evidence against runtime journals. Never force-push over another
   agent's updates. Do not interrupt active runtime work to run concurrent builds.

## Progress JSON contract

The top-level `phase_counts` are derived summaries. `entries` is keyed by public
plan entry ID, including native control IDs. Each entry may contain only:

```json
{
  "status": "in_progress",
  "execution_manifest_sha256": null,
  "updated_at_utc": null,
  "outcome": null,
  "reason_code": null,
  "evidence_sha256": [],
  "public_evidence_urls": [],
  "updates": []
}
```

Populate timestamps with the actual UTC reporting time and hashes from real
artifacts. `outcome` is a small verified metric object appropriate to the task;
leave it null until verified. Native checks use `passed` or `failed` as their
outcome and retain expected-positive/expected-negative identity from the schedule.
Each `updates` item records timestamp, previous/new status and a short sanitized
reason. Do not invent hashes, URLs, success values or completion dates.

Only public evidence URLs and content hashes may be tracked. Never include raw
prompts/programs, account/character identifiers, credentials, SQL, recordings,
game assets, private URLs, hostnames or absolute runtime paths. Keep detailed
evidence on the runtime host and approved storage. Repository-wide boundaries
and secret scanning still apply.

## Keep design and results separate

- Do not change schedule rows or task criteria to match observed outcomes.
- Binding a launchable protocol creates a separately pinned execution manifest;
  link its hash in progress. A protocol change requires a new version/cohort.
- Work not matching this suite belongs in a separately labelled experiment.
- Before completing an execution task, update progress with terminal counts,
  unresolved entries, evidence references, blockers and the exact next action.

Before committing, run `node scripts/check-tracked-files.mjs` and the redacted
staged Gitleaks scan through the configured `.githooks` pre-commit hook.
