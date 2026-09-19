# v1 status and next actions

Snapshot: **2026-09-19.** Branch `codex/v1-release-integration`, forked from
`codex/native-research-integrated` @ `ee1c893`. Nothing here is an accepted
benchmark result. No model was called and no trial ran during this work.

## Corrections to earlier beliefs

These were stated wrongly in planning and are corrected by audit. They matter
because plans were built on them.

| Claim | Actual |
| --- | --- |
| "78 branches, nothing merged back" | Overstated. The integration line already contains the stale-navigation fix, the readiness policy, the five-minute adaptive protocol and the `hero-cave` fixture. Minimal v1 merge set is **zero branches**. |
| "1 of 24 deliverables accepted" | **9 of 24, 15 remaining.** The 1/24 figure came from `codex/mobile-continuous-sheet`, which is branched off stale `main` (11 ahead, 0 behind) and never received the integration line's 92 commits. |
| "Readiness policy is built but unused" | It is **mandatory and fails closed** in planner, runtime and bridge, with independent recomputation in publication and ~25 tests. Every live adaptive run used it. |
| "The adaptive protocol is code-ready only" | It **has run live**: 9 cycles, 9/9 confirmed API responses, `controller_ms` 300038, persistence schema 2, video plus probe plus independent decoded counts. |
| "Luna failed by returning a function declaration" | That defect was real but already fixed in `2a93db5`. Luna's recorded failure was **ambiguous key notation**: it sent a raw `D` where the SDK requires `BUFF_1`, and the input guard rejected the first RPC. |
| "Adaptive scoring uses persistence schema 1" | Adaptive produces **schema 2**. The signed `net_xp` formula is shared and unchanged. |
| "The WZ assets are lost" | They are on **`orbital-one`**, on-prem and reachable. See below. |

## Verified environment

**`orbital-one`** (System76 Thelio Astra, Ubuntu 24.04.4, **aarch64**, 96 cores,
30 GB) holds the complete working tree at `/home/dmarz/maplebench-work` (30 GB):

| Component | Size |
| --- | --- |
| `server-data/wz` — all 12 WZ archives | 575 MB |
| `private/baseline.sql` | 1.1 MB |
| `cosmic/target/Cosmic.jar` | 52 MB |
| `full-client` | 71 MB |
| `assets` / `baked` | 3.0 GB / 43 MB |

It runs `assetd` on :8820 (maplewright, serving `Character.wz` + `Base.wz`), has the
emscripten WASM client build chain, Java 21, Python 3.12, Node 18, and a checkout at
`754d905`. **It has no browser and is ARM**, so it cannot reproduce the accepted
amd64 pinned-Chrome rendering stack — but it can run headless simulation, the
server, and replay rendering, at zero cost.

**v1 fixture is Hero-180 on map `240040511`**, not `hero-cave`. `hero-cave` has no
level-150 baseline or verified keymap for map `240050300`, and its nine invocable
skills do not map onto the protocol's four neutral slots. The runtime binds the
profile's level to the baseline character's level and refuses a mismatch with
`baseline_identity_mismatch`, so that fixture genuinely needs its own baseline.

## Shipped

Six commits on `codex/v1-release-integration`. Full suite **1137 tests, 17 failures
and 47 errors — identical to a pristine `ee1c893` baseline**, so 35 tests added and
zero new failures. The pre-existing failures are Linux/root/Docker tests on macOS.

- `docs/M1_WORLD_IMAGE.md` — world image as the reset primitive, with what must be
  proven first and why v1 stays on the current reset path.
- `knowledge/hero-cave/` + `scripts/knowledge_pack.py` + 9 tests — the facts buried
  in the fixture `description` extracted into a hashed pack with per-fact
  provenance. **Not wired into any prompt**; see the deferral in
  [the cohort plan](V1_COHORT.md).
- `scripts/full_client_scenario_freeze.py` + 25 tests — build, hash and check a
  frozen adaptive scenario offline. Its `check` accepts an accepted production
  freeze and independently re-derives that scenario's `instructions_sha256`,
  budgets and trial budgets, so it is verified against what actually ran.
- The adaptive prompt key-ambiguity fix, with a test pinning that physical keys are
  never advertised. This is a **new prompt version**, so `instructions_sha256`
  changes and a re-pin is required.
- `docs/V1_COHORT.md` — scope, the seven-step re-pin checklist, and explicit
  non-claims.
- `docs/ROADMAP.md` — execution priority revised to depth before breadth, plus the
  first test coverage for `frozen_prompt_mismatch`, which also checks the freeze
  builder against the runtime's own validator.

In `agent-devops`: a unit renderer was written, then **reverted** (`3f8bee2`)
because PR #11's `maplebench-fresh-runtime` toolkit already does it better — six
units against my four, including the display and browser units my version omitted
entirely. Plus the lease record at
`docs/deployments/maplebench-pilot-2026-09-18.md`.

## Infrastructure

One lease was taken and returned: droplet `601621266`, 11.95 hours, **≈ $2.24**,
destroyed on schedule with `deleted_and_absent` and an independent 404. It was
never bootstrapped — no runtime bundle was available — so it produced no evidence.
Three latent failures that would each have broken the billing guarantee were found
and fixed before apply; they are recorded in the `agent-devops` lease record and
are likely to recur on the next lease.

**The account is at $1,047.89 month-to-date.** An H200 GPU droplet
(`vd-gpu-nontee-04`, tagged `vd-lineage`, created 2026-09-14) is unrelated to this
project and is plausibly most of it; three droplets named `delete-*` total
$232/month, one running since March. None of that was touched.

## Next actions

1. **Decide the runtime bundle.** `maplebench-worker.yml` requires
   `maplebench_bundle_path` + SHA-256 and a pinned Chrome `.deb` + SHA-256. The
   ingredients are on `orbital-one`; the original 5.4 GB bundle
   (`cf10358488769a564878e4f09ff1fc9615397de14f200acf322d7ed2493044c2`) is not on
   the laptop. Either build and pin a new bundle from those components, or locate
   the original. **This blocks every bootstrap.**
2. **Adopt PR #11's `maplebench-fresh-runtime` toolkit** rather than writing
   anything new: `prepare.py`, `install_units.py`, `import_database.py`, `enroll.py`.
   It already ran on the September 12 verification worker and covers the database
   import this repository's reproducibility doc still lists as outstanding.
3. **Free rehearsal on `orbital-one`** — headless simulation and replay rendering
   to exercise the pipeline before paying for a lease. Not a substitute for the
   rendered cohort, which needs amd64 and the pinned Chrome.
4. **Re-pin and freeze** — the seven steps in [the cohort plan](V1_COHORT.md).
   Requires a host.
5. **Collect 16 attempts** — 4 models × 4 repetitions, Hero-180, declared order
   balance. **Requires an OpenAI API key**, which is not yet available.

## Open decisions

- Bundle: rebuild from `orbital-one` components, or recover the original.
- Whether the knowledge pack enters v1's prompt at all. Current answer is no, so
  that the prompt-contract change is the only variable in this cohort.
- Whether to spend the next rebuild on the world image instead of another VM. The
  regression-oracle argument still favours the VM, but the cost gap narrowed once
  the original host was destroyed.

## Housekeeping

The DigitalOcean token used for the lease was pasted into a chat transcript and
should be rotated. The dedicated SSH key, firewall and local OpenTofu state from
the destroyed lease should be reconciled with the destroy helper before the next
lease is taken.
