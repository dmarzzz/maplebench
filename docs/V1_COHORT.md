# v1 cohort: Hero-180, five-minute adaptive, 16 attempts

Status: **release plan, recorded 2026-09-18.** Nothing here is an accepted result.
This document says what v1 collects, what must be re-pinned before it can run, and
what v1 will not claim.

## Scope

| Element | Value | Why |
| --- | --- | --- |
| Fixture | Hero-180 on map `240040511` | The baseline, keymap, profile and 300-second machinery are already live and accepted here |
| Protocol | `full-client-adaptive-pilot-v1`, 300 s wall | Measures replanning, not one-try code generation |
| Cohort recipe | `encoded` (full-horizon reserve + `post-render-encoded-frame-v1`) | Exactly what the accepted five-minute runs used |
| Models | `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` | Unchanged four-model scope |
| Repetitions | 4 per model → **16 attempts**, declared order balance | One attempt per model cannot separate model from variance |
| Score | Signed persisted `net_xp`, persistence schema 2 | Includes death penalties, preserves negatives and zero |
| Knowledge | none for this fixture yet — see below | Knowledge is a frozen axis of the evaluated system |

`hero-cave` is deferred to v2. It has no level-150 baseline snapshot or verified
keymap for map `240050300`, and its nine invocable skills do not yet map onto the
protocol's four neutral slots. Its reference pack is committed at
`knowledge/hero-cave/` and its extraction pattern transfers; a Hero-180 pack for
this map still has to be written, and adding one changes the frozen prompt.

## Freeze

```sh
python3 scripts/full_client_scenario_freeze.py hash
python3 scripts/full_client_scenario_freeze.py build \
    --id hero-180-v1-pilot-cohort-v1 --expected-map-id 240040511 \
    --output <private>/scenario-hero-180-v1.json
python3 scripts/full_client_scenario_freeze.py check <private>/scenario-hero-180-v1.json
```

Defaults are the accepted Hero-180 profile and the `encoded` recipe, so the
generated `adaptive_protocol` and `readiness_policy` are byte-identical to the
accepted cohort. The only intended difference is the prompt.

With the corrected prompt at this revision, `instructions_sha256` is
`ca0bb3c7f56a1e4f081f906ad3536eb0159089dc0002ff2497eafb8b7e4903c9`. Recompute it
with `hash` rather than trusting this line — if the two disagree, the prompt moved
and this document is stale.

The builder never reads private baselines. `--expected-map-id` must equal the
frozen baseline character's `map_id`; three independent checks enforce that at
plan, runtime and publication time, and all three will refuse a mismatch before
any provider request.

## Re-pin checklist

The prompt change alters `scripts/full_client_adaptive.py`, which is a pinned
frozen source. Every item below must be redone or the runtime fails closed.

- [ ] **Runtime inventory manifest.** `full_client_adaptive.py` is in the mandatory
      web import closure, so its SHA-256 changed. Rebuild with
      `full_client_freeze.py create`; it refuses to overwrite, so a new version
      gets a new file. Stale manifest → `runtime_manifest_drift` /
      `serving_sources_not_frozen`.
- [ ] **Backend config `scenario` ref** → the new `{path, sha256}`.
- [ ] **Plan fixture** `scenario`, `budgets`, `protocol` and `runtime_manifest`.
      The coordinator cross-checks config against fixture; a mismatch is
      `backend_fixture_mismatch`.
- [ ] **Runner `dependencies`** must still contain `full_client_adaptive.py`,
      `full_client_adaptive_evidence.py` and `maple_agent.py`, with fresh hashes.
      Otherwise `runner_dependencies_missing`.
- [ ] **Adapter fingerprint** on the fixture — recompute, else `adapter_changed`.
- [ ] **Restart the web/serving process.** It must start *after* every frozen
      source's mtime/ctime, else `web_process_predates_frozen_sources`.
- [ ] **Fresh attempt IDs and a new experiment id.** Never retrofit receipts onto
      an earlier freeze.

Historical evidence is unaffected: each past trial carries its own recorded
prompt bytes and its own scenario hash, and publication compares those to each
other, not to today's source.

## What v1 reports

Per attempt: signed `net_xp`, `alive_at_logout`, wall duration, API time,
controller time, cycle count, token usage, and the readiness receipt proving a
populated scene preceded the first request.

Per group: **attempted / completed / invalid, broken out by cause.** This is the
answer to "does the machinery work" and it is a first-class published number, not
a footnote. Valid zero, negative and death outcomes count. Infrastructure-invalid
and missing-evidence attempts stay distinct and appear in denominators.

Gate for the release: **three consecutive complete groups with no ad hoc repair
between models.**

## What v1 does not claim

- No ranking. Four models × four repetitions on one fixture cannot establish
  relative model quality; report per-model spread and the eligible fraction.
- No peak XP/min. Rate-based scoring needs the native XP-window ledger and a
  fixed-width window definition; v1 is net XP over a declared horizon.
- No cross-provider claim. All four models are from one provider.
- No statement about `hero-cave`, other classes, or horizons beyond 300 seconds.
- Kills, gross XP, damage and survival-throughout stay unknown: two persistence
  snapshots cannot support them.

## Regression oracle

v1 runs on the current reset path (stop server, restore frozen database, hold
world and queue locks, fresh server, ordinary login/logout). Keep it that way.
The proposal in [M1_WORLD_IMAGE.md](M1_WORLD_IMAGE.md) replaces that path with a
container per trial; without a clean 16-attempt baseline first, a later change in
the XP distribution cannot be attributed to a fixed defect or a new one.
