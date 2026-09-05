# Repository boundaries

Never commit credentials, personal information, account exports, private transcripts,
host-specific configuration, database files, recordings, or game assets.
Keep runtime configuration and outputs in ignored directories. Generate passwords on
the runtime host; do not embed them in commands, documentation, or source.

Before committing, run `node scripts/check-tracked-files.mjs` and a redacted Gitleaks
scan. Enable the fail-closed local hook with `git config core.hooksPath .githooks`.
Scan the full Git history before publishing or changing repository visibility.
Review new files for personal information; secret scanning cannot detect every kind
of personal data. Retain upstream license notices and keep WZ assets out of Git.

Use localhost control endpoints and an SSH tunnel for remote experiments. Label
mock runs, offline renders, baseline policies, and actual server runs accurately.

The runtime machine is shared. Run only one build/test job at a time, with a hard
memory limit and explicit JVM heap/fork limits. Use the focused tests for the
change; do not launch the full bot optimizer suites concurrently. A useful Java
build cap is 2300 MiB total, 768 MiB Maven heap, one 1024 MiB test fork, two CPUs,
and a five-minute timeout. Build native replay code with one Cargo job and a
hard memory limit. Check available memory before starting live experiments.
