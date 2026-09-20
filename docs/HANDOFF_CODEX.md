# MapleBench release handoff

Read [V1_STATUS.md](V1_STATUS.md) and [V1_COHORT.md](V1_COHORT.md) first. The older
visual roadmap describes the previous scope; the cohort document supersedes it
for this expanded release. The candidate branch is
`codex/v1-cross-provider-release`, based on integration revision `5c94df5`.

Fetch all working branches in both MapleBench and its companion agent-devops
repository before choosing source; do not assume an old local `main` is current:

```sh
git config --replace-all remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git fetch --all --prune
```

The fixture is Hero-180 on map `240040511`, with the new declared ten-skill toolkit
and matching knowledge. Do not substitute level-150 `hero-cave`, an earlier
four-slot baseline, or mismatched Journey/Cosmic binaries. The readiness gate is
mandatory. Five-minute adaptive evidence uses persistence schema 2.

Reuse the companion repository's `scripts/maplebench-fresh-runtime/` toolkit:
`prepare.py`, `install_units.py`, `import_database.py`, and `enroll.py`. It renders
six units, including display and browser. Inspect actual prerequisites: the
native amd64 sandbox image and preflight must exist before preparation. The
original bundle's SQL template needs its separately qualified corrections; an
archive hash does not establish a compatible expanded baseline.

Runtime artifacts, host access, lease credentials and operator configuration are
in private records. Use a fresh lease/controller namespace, arm external deletion
before provisioning, and bind cleanup to the actual lease identity. Verify both
instance absence and an empty lease tag at closeout.

All builders/planners are offline unless their explicit run command is invoked.
Keep synthetic tests, zero-model native qualification and scored provider runs
separate. Never retrofit new protocol receipts onto historical attempt IDs.
