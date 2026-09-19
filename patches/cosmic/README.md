# Cosmic patches

This directory contains small proposed patches against `NDBellisario/cosmic` required to create a policy-neutral benchmark control plane.

They are kept as patches rather than vendored server source so the MapleBench framework stays cleanly separated from the AGPL server implementation.

Current patch:

- `0001-expose-requested-attack-plan.patch` — exposes a package-private planner for one *requested* basic/skill attack, avoiding the upstream bot AI's automatic best-skill choice.

The patch is based on the current `master` shape observed while bootstrapping MapleBench and should be revalidated against a pinned upstream commit before application.

The bootstrap overlay also installs `MapleBenchPersistence`, a disabled-by-default
full-client save journal. Its character hook runs after the real save transaction
commits, and its error hook records failed saves. Initialization precedes server
login acceptance. See [production readiness](../../docs/PRODUCTION_READINESS.md)
for the private launcher settings, verification boundary, and focused native test.

`0003-native-hero-skill-evidence.patch` applies to the pinned server input in
[`V1_NATIVE_BUILD_INPUTS.json`](../../docs/V1_NATIVE_BUILD_INPUTS.json), after the
existing persistence/XP hooks and `0002-monster-status-order.patch`. Apply it to
an isolated copy of that source, then copy the three `MapleBenchSkill*.java`
overlay classes and `MapleBenchSkillEvidenceTest.java`. Its six source edits
observe ordinary physical skill handlers, the native HP/MP mutation lock, and
the native monster damage lock. The shared bot helper is not a source of
qualification events. Combat behavior, skill grants, and damage calculations
are unchanged.

The producer is disabled unless all journal settings are present. A private
launcher supplies `MAPLEBENCH_SKILL_JOURNAL`, `MAPLEBENCH_SKILL_TASK_ID`
(`hero-180-toolkit-qualification-v1`), `MAPLEBENCH_SKILL_BINDING_SHA256` (the
native contract fingerprint), `MAPLEBENCH_SKILL_RUNTIME_SHA256`, and
`MAPLEBENCH_SKILL_DURATION_MS` (`120000`). It reuses the existing run, server,
character, and account identity settings. The journal is created once with
mode 0600 and is capped at 16 MiB and 100,000 events. Every line contains the
previous line's SHA-256. An invalid clock, write, identity, transaction, or
budget prevents a complete seal.

The trusted runner also supplies `MAPLEBENCH_SKILL_CONTROL_TOKEN` (64 hex
characters), `MAPLEBENCH_SKILL_CONTROL_PORT`, `MAPLEBENCH_SKILL_WORLD_ID`, and
`MAPLEBENCH_SKILL_CHANNEL_ID`. The control server binds only to loopback.
Authenticated, bodyless requests can read `/v1/skill-ledger/status`, arm the
window once at `/v1/skill-ledger/arm`, and seal it once at
`/v1/skill-ledger/seal`. Lost responses are reconciled through status; arm and
seal are not retried. The runner keeps the token outside artifacts and model
inputs. It must independently prove lifecycle and frozen runtime identity.

Nonterminal events are limited to 120 seconds from arm; seal has a five-second
grace. Each cast summary links its actual locked resource and damage events.
Actor snapshots are explicitly non-atomic. The Python Hero verifier checks
their consistency and decides qualification from native effects, independently
of relay acknowledgements. The producer never asserts qualification itself.
The focused Java test is `MapleBenchSkillEvidenceTest`; its mocked actor checks
test the evidence contract and do not constitute live skill qualification.
