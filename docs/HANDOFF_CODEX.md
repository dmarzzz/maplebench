# MapleBench v1 — handoff

## First, orient yourself

Clone/pull both repos, then **immediately fix the fetch refspec** — both were
configured to fetch only `refs/heads/main`, which hides every working branch.
This trap already caused duplicated work once:

    git config --replace-all remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
    git fetch --all --prune

- `git@github.com:dmarzzz/maplebench.git` → branch `codex/v1-release-integration`
- `git@github.com:dmarzzz/agent-devops.git` → branch `codex/maplebench-cloud-worker`

**Open `docs/v1-roadmap.html` in a browser first.** It is the current picture of
what is done, what is not, and what blocks what. Everything below is detail on it.

Then read, in order:
- `docs/V1_STATUS.md` — status, corrections to earlier beliefs, next actions
- `docs/V1_COHORT.md` — v1 scope, the 7-step re-pin checklist, explicit non-claims
- `docs/M1_WORLD_IMAGE.md` — proposal to make a world image the reset primitive

## Facts that will mislead you if you assume otherwise

1. **The integration line is `codex/native-research-integrated`, not `main`.**
   `main` is stale. Branches forked from it (e.g. `codex/mobile-continuous-sheet`)
   report badly outdated status — that's where the wrong "1 of 24 deliverables
   accepted" figure comes from. The real number is **9 of 24, 15 remaining**.

2. **v1's fixture is Hero-180 on map `240040511`, not `hero-cave`.** hero-cave has
   no level-150 baseline or verified keymap for map `240050300`, and the runtime
   binds the profile's level to the baseline character's level, refusing a mismatch
   with `baseline_identity_mismatch`. Its nine invocable skills also don't map onto
   the protocol's four neutral slots.

3. **The WZ assets are not on the laptop.** They live on `orbital-one` (on-prem,
   LAN-only, `orbital-one.local`, user `dmarz`, key `~/.ssh/orbital-one_ed25519`,
   passwordless sudo) under `/home/dmarz/maplebench-work` (~30 GB): all 12 WZ
   archives in `server-data/wz` (575 MB), `private/baseline.sql`,
   `cosmic/target/Cosmic.jar`, `full-client`, `assets/`, `baked/`. It runs `assetd`
   on :8820 and has the emscripten WASM build chain, Java 21, Python 3.12, Node 18.
   A Spotlight search of the Mac finds zero `.wz` files — don't conclude they're gone.
   Caveat: orbital-one is **aarch64 with no browser**, so it can't reproduce the
   accepted amd64 pinned-Chrome rendering stack. It can run headless simulation,
   the Cosmic server, and replay rendering.

4. **The readiness gate is mandatory and fails closed** in planner, runtime and
   bridge, with independent recomputation in publication and ~25 tests. It is not
   dormant.

5. **The five-minute adaptive protocol has run live** — 9 cycles, 9/9 confirmed API
   responses, `controller_ms 300038`, persistence **schema 2** (not schema 1).

## What was shipped (8 commits on `codex/v1-release-integration`)

1137 tests, 17 failures / 47 errors — **identical to a pristine `ee1c893` baseline**,
so 35 tests added and zero new failures. The pre-existing failures are Linux/root/
Docker tests running on macOS.

- `d40ff93` — fixed the adaptive prompt's key ambiguity. It advertised
  "PRIMARY_SKILL, SECONDARY_SKILL, BUFF_1 and BUFF_2 press A, S, D and F"; Luna sent
  a raw `D` where the SDK requires `BUFF_1` and the guard rejected its first RPC.
  **This is a new prompt version — `instructions_sha256` changes and a re-pin is
  required.**
- `827266e` — `scripts/full_client_scenario_freeze.py`, offline build/hash/check for
  a frozen adaptive scenario. Its `check` accepts a real accepted production freeze
  and independently re-derives that scenario's hash, budgets and trial budgets.
  Point `MAPLEBENCH_FROZEN_SCENARIO` at a private accepted scenario to run that
  regression. 25 tests.
- `df4f7eb` — `knowledge/hero-cave/` + `scripts/knowledge_pack.py`, 9 tests.
  **Deliberately not wired into any prompt** (see V1_COHORT.md for why).
- `4c74a1b`, `7753f83`, `5851787`, `8c0ecd1`, `c7cdcda` — decision records, the
  depth-before-breadth priority revision, first coverage for
  `frozen_prompt_mismatch`, status, and the roadmap page.

In `agent-devops`: `b20d2cf` records a worker lease that was provisioned, verified
reachable by Ansible, and destroyed on schedule by its external controller. It was
**never bootstrapped** (no runtime bundle), so it produced no evidence. That record
also lists three latent failures fixed pre-apply that would each have left a worker
running past its deadline — read it before taking another lease.

## Do not rewrite this

A runtime unit renderer was written in `agent-devops` and then **reverted**
(`3f8bee2`). PR #11's branch `codex/maplebench-verification-plan-20260912` already
has `scripts/maplebench-fresh-runtime/` — `prepare.py`, `install_units.py`,
`import_database.py`, `enroll.py` — which renders **six** units (cosmic,
full-client-web, worker, display, browser, full-client-world). The reverted version
did four, omitting the Xvfb display and browser units and two required environment
variables, so its output would not have run. That toolkit already ran on the
September 12 verification worker and covers the database import the reproducibility
doc still lists as outstanding. **Use it.**

## Next actions, in order

1. **Runtime bundle — this blocks everything.** `ansible/playbooks/maplebench-worker.yml`
   requires `maplebench_bundle_path` + SHA-256 and a pinned Chrome `.deb` + SHA-256.
   The ingredients are on orbital-one; the original 5.4 GB bundle
   (`cf10358488769a564878e4f09ff1fc9615397de14f200acf322d7ed2493044c2`) is not on
   the laptop. Either build and pin a new bundle from those components, or find the
   original.
2. **Adopt the fresh-runtime toolkit** from PR #11 rather than writing anything new.
3. **Optional free rehearsal on orbital-one** — headless simulation and replay
   rendering to exercise the pipeline before taking a lease.
4. **Re-pin and freeze** — the seven steps in `docs/V1_COHORT.md`. Needs a host.
   Freeze with:

       python3 scripts/full_client_scenario_freeze.py build \
           --id hero-180-v1-pilot-cohort-v1 --expected-map-id 240040511 \
           --output <private>/scenario-hero-180-v1.json

   Recompute the hash with the `hash` subcommand rather than trusting any recorded
   value; if they disagree the prompt moved and the docs are stale.
5. **Collect 16 attempts** — 4 models × 4 repetitions on Hero-180, declared order
   balance. **Requires an OpenAI API key, which is not yet available.**
6. **Reliability metric then publish** — attempted/completed/invalid per group by
   cause; gate on three consecutive clean groups.

## Ansible

Not installed system-wide. Use a venv with `ansible-core` plus the five collections
in `ansible/requirements.yml`. SOPS is **not** required for the worker path: the
tofu-generated inventory at
`tofu/environments/maplebench-pilot/generated/inventory.yml` is standalone, so use a
minimal `ansible.cfg` with `roles_path` set and point `-i` at it directly.
