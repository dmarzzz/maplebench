# Agent handoff — 2026-09-29 (from the MacBook Claude session)

Written for the next agent picking up MapleBench. Read this first, then `AGENTS.md`.

## TL;DR

- **v1 is shipped and live.** Release `v0.1.0`, site at
  https://maplebench.vercel.app/cohorts/edd1f4b505e7415f/. `main` = `52200ba`.
- **v0.2.0 (reasoning effort `low` → `medium`) is blocked** on a native
  qualification failure whose real cause the runner masks. Nothing has been
  spent on it ($0; native runs make no API calls).
- **Every local branch is now on GitHub.** On 2026-09-29 I pushed 60 branches
  that only existed on this laptop (83 commits). None were merged — they are
  there for preservation, not approval.

## Which line is which (this trips everyone up)

| Line | What it is |
|---|---|
| `main` | Live site UI + v1 release (PRs #9, #10, #11 merged). |
| `codex/v1-cross-provider-release` | The v1 release line (PR #9, evaluated source pinned at `f3a71f5`). |
| `codex/native-research-integrated` | Older integration line; much of the `codex/*` work forked from here. |
| `codex/v0.2.0-measurement-fixes` | v0.2.0 work: effort=medium (`0371952`), root-cause doc (`ee20a64`). |

Branches forked from stale `main` (e.g. `codex/mobile-continuous-sheet`) will
show badly outdated status. Check which line a fact came from before quoting it.

## v1 results (4 models × 4 reps, Hero-180, map 240040511, 5-min adaptive pilot)

16/16 attempts sealed: 14 verified, 2 retained infrastructure failures (kept
visible as 3/4, not hidden as 3/3).

| # | Model | Verified | Mean XP | Median | Best |
|---|---|---|---:|---:|---:|
| 1 | gpt-6-astra | 3/4 | +32,083 | +32,000 | +36,750 |
| 2 | gpt-5.6-sol | 4/4 | +25,188 | +27,500 | +27,500 |
| 3 | claude-opus-5 | 3/4 | +22,833 | +18,250 | +32,000 |
| 4 | claude-sonnet-5 | 4/4 | +16,000 | +16,000 | +18,250 |

## Website/UI state (done)

- The illustrated design (Henesys backdrop, sprite emblems, Manrope, cards) is
  ported onto v1's `dashboard.js`, **keeping** the replay timeline
  (`updateReplayTimeline`, `replayControls`, `openReplay`, `playFrom`,
  `adaptiveHold`, `adaptiveDetails`). Do not swap in the standalone illustrated
  page wholesale: it drops those, and ~12 tests catch it.
- Sections are `<details>` dropdowns; **Simulation lab is section 2 and
  collapsed by default** (the user asked for this explicitly, twice).
- Last fix (`52200ba`): the lab emblem rendered 353px wide because of a
  `h2#approach-title > span { flex: 1 1 auto }` rule; now 44px, left-aligned.
- The deployed UI is built from **`ui/full-client-dashboard/`** via
  `full_client_publication.py`, **not** `examples/full-client-benchmark/`.
  Editing the examples directory changes zero deployed bytes.
- The user has been frustrated by "it's fixed" claims that weren't visible live.
  After any deploy, open the actual live URL (root **and** `/cohorts/...`) and
  check it before saying it's done.

## v0.2.0: where it stopped

Goal: a single-variable cohort, reasoning effort `medium` vs v1's `low`,
with everything else byte-identical (knowledge pack `d2096b63…`, 500k token
budget, same native scenario `90665625…`, same baseline `8104deb6…`).

| Step | State |
|---|---|
| Source exported + hash-verified | ✓ `ee20a646…` |
| `freeze_worker_v11` authored | ✓ `d16ec239…` |
| Freeze-v11 | ✓ receipt `c99751ea…`, eval scenario `025b5eb9…` |
| Native qualification | ✗ failed in `preflight` after 18s, reason masked as `hero_native_operation_failed` |
| `plan_worker_v12` / `launch_v12`, launch | not started |

Ruled out (by checking): the effort change (the native runtime overrides
`load_pins` and never reads `reasoning`), manifest drift (all 24,618 entries
verify), `verify_manifest`, deadline, baseline drift, locks.

**Next step:** make the runner keep the underlying error (it discards codes
outside `FAILURE_CODES`), then rerun native qualification. Before freezing,
confirm the character is at the pristine baseline (exp 73250 / hp 12000 /
mp 6000); a previous cohort's end state was left in the DB once.

Rules the reviewed helpers enforce: plan/launch helpers hard-pin the lease
chain by hash and deadline delta, so extending a lease needs a **new versioned
helper pair**, not new arguments. Arm the external destroy controller
**before** apply. The last cloud worker's lease ran to 2026-09-21T03:19Z. Its
destruction has not been re-verified since, so check the provider for stray
droplets.

## Open audit findings (checked against v1, not stale `main`)

- Reasoning effort frozen at `low`: fixed on `codex/v0.2.0-measurement-fixes`.
- **No terrain in `Observation`**, only an opaque `foothold` id. Still open,
  and the most important agent-capability gap.
- Legacy `moveTo(x,y)` fixtures clamp to 1-D (`hero-cave*`, `hero-timeless-cave`).
  v1 uses `pressKeys` only, so it is unaffected, but those files are a trap.
- The zero-XP columns in older cohorts came from a **broken client**
  (spell/bow damage unimplemented before patches 0008–0018), not the models.

## What I did on 2026-09-29

1. Pushed 60 laptop-only branches with upstream tracking. Before pushing I
   scanned every unpushed commit for keys, private evidence paths, host
   details, WZ/SQL assets and large blobs, and found nothing.
2. Committed two dirty worktrees as clearly labeled **WIP, untested** snapshots:
   - `codex/mobile-continuous-sheet` → `6770b3d`: illustrated results-site
     snapshot (the `illustrations/` and `fonts/` that were never committed
     before), skillbook, and a `recover` runner path in
     `full_client_experiment.py`/`full_client_trial.py`.
   - `codex/skill-suite-v1-budget-simulation` → `f64999f`: skill-suite
     budget/pilot simulation plus its tests.
3. Deleted a debug scratch page (`ui/full-client-dashboard/_q.html`).
4. Wrote this note. I merged nothing and deployed nothing.

## Not on GitHub (on purpose)

The private operator evidence, host access and runner state stay on the
laptop/runner. The game runtime and WZ assets live on the on-prem runner, not
the laptop. Don't go looking for them in the repo, and never commit them.
