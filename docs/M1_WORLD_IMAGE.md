# M1 reshape: the world image as the reset primitive

Status: **proposal, recorded 2026-09-18.** This document argues for changing what
M1.3/M1.4 deliver. It does not change the evidence contract, the scorer, the
renderer invariants, or the meaning of any historical result. It does not
invalidate the reviewed infrastructure plan in
[agent-devops PR #10](https://github.com/dmarzzz/agent-devops/pull/10); that work
stands and is largely done.

## Correcting the roadmap's status

[ROADMAP.md](ROADMAP.md) shows M1.2 ("deploy and configure the pilot") unchecked.
The `agent-devops` deployment records show it substantially complete:

- Isolated state `tofu/environments/maplebench-pilot` applied 2026-09-08: six
  creations, zero changes/deletions. Droplet 598634072, `g-4vcpu-16gb`, NYC1,
  $0.1875/hour. External lease-tag destroy controller verified before apply.
- `ansible/playbooks/maplebench-worker.yml` bootstraps a worker: prerequisites,
  explicit Chrome package hash check, hash-checked private runtime bundle import,
  optional narrowly pinned sandbox broker.
- The private runtime bundle (5,407,324,160 bytes, SHA-256
  `cf10358488769a564878e4f09ff1fc9615397de14f200acf322d7ed2493044c2`) transfers
  directly over SSH without staging on the laptop.
- Two expansion workers bootstrapped and handed off for native setup.

So provisioning is not the gap, and the Ansible work is not throwaway. The
roadmap's M1.2 box should close and the open gate is M1.3 — cloud rendering and
evidence acceptance.

## The actual blocker

[`maplebench-runtime-reproducibility.md`](https://github.com/dmarzzz/agent-devops/blob/main/docs/deployments/maplebench-runtime-reproducibility.md)
states it directly: the playbook "is a bootstrap, not a reproducible end-to-end
benchmark deploy." It does **not** generate the six runtime systemd units, perform
the guarded initial database import, activate a source successor, or generate a
qualified trial plan. The pilot did those steps with *reviewed private operator
helpers* that "contain host-bound receipts and must not be copied into this
repository wholesale."

That is the reproducibility ceiling. M1.4 asks for "a reproducible worker
configuration," and the remaining 40% of the deploy is by construction
un-committable in its current form.

## Proposal

**Make a built, hash-pinned world image the reset primitive, and make a fresh
container the unit of trial isolation.** The image carries the pinned Cosmic
source, the seeded baseline database, the six runtime units' equivalents as
container entrypoints, and the pinned Chrome + Xvfb + SwiftShader renderer stack.
A trial gets a new container from a known image digest; teardown is discard.

This replaces the host-bound operator helpers with an artifact that *is* the
reproducible configuration, which is exactly what M1.4 asks for.

### What it replaces

| Reset step today | Under a world image |
| --- | --- |
| Stop the running server | Container did not exist yet |
| Restore frozen DB backup, verify `baseline_sha256` | Baseline is a layer; image digest is the attestation |
| Acquire and hold `world_lock` + `queue_lock` throughout | No shared world to lock — one world per container |
| Start a fresh server, mint `server_instance_id` | Container start |
| Guarded initial database import (private helper) | Built once at image build, checked by digest |
| Source successor activation (private helper) | New image tag |
| Teardown, restore normal services, reconcile status | `docker rm`; nothing shared was touched |

The failure classes that have actually cost groups — stale game URL reopening
after logout, collection finding the account online, relay restart repair,
post-cleanup status reconciliation — all live inside that serialized critical
section. They are artifacts of reusing one long-lived world, not of the game.

### What it does not change

- **The evidence contract.** Initial/final offline database reads, ordinary login
  and logout, the confirmed save receipt, the hash chain, signed `net_xp`. All of
  it still applies; the reads happen against the container's database.
  `reset.world_lock_held` / `queue_lock_held` attestations need reinterpretation
  for a single-tenant world — see open questions.
- **Renderer invariants.** Xvfb, `--use-gl=angle --use-angle=swiftshader
  --enable-unsafe-swiftshader`, CPU-owned sRGB RGBA snapshots after real native
  rendering, VP8 in explicit quality mode, fail-closed with no GPU fallback, media
  time from the first real rendered frame, the 250-ms endpoint contract. These are
  software rendering already, so they containerize without change.
- **Scoring, readiness, publication.** Untouched.

### Why this is feasible here

- A `docker` Ansible role already exists in `agent-devops`, and
  `ansible/roles/maplebench_worker/tasks/sandbox.yml` plus
  `files/sandbox_docker.py` already run the model's generated program in a
  container. The pattern and the review precedent are in place — this extends
  containerization from the SDK sandbox to the world.
- The renderer is CPU-only by design (SwiftShader), so there is no GPU
  passthrough problem.
- Capacity: RuneBench budgets 2 CPU / 8192 MB / 10240 MB per task. A
  `g-4vcpu-16gb` worker maps to roughly two concurrent trials, or one with
  renderer headroom. That is the first real parallelism the project would have.

### Prior art worth copying

[RuneBench](https://maxbittker.github.io/runebench/) runs LostCity headless in a
Docker container per task with pre-built save files baked into the image, and
orchestrates with [Harbor](https://github.com/harbor-framework/harbor) (from the
Terminal-Bench authors; `harbor run --n-concurrent N`, plus parallel sandbox
providers). Harbor is a candidate to replace the bespoke coordinator, admission,
and lifecycle components — evaluate it at M1.4, not before.

## What must be proven before adopting

Unproven, in rough order of risk:

1. **Boot cost.** Container start plus server ready plus client login must be
   comparably fast to the current restore path, or throughput gains are eaten by
   setup. Measure it.
2. **Renderer fidelity inside a container.** Frame cadence and the capture-clock
   handshake are already delicate (see the post-render cadence bound for
   high-refresh displays). The readiness policy requires `ageMs` and
   `renderAgeMs` under 1500 ms and three increasing post-render frame counters
   spanning a second. Prove those hold under container scheduling.
3. **Lock attestations.** `full_client_score.py` schema 1 requires
   `world_lock_held`, `queue_lock_held`, `server_stopped` and
   `world_lock_held_throughout`. In a single-tenant container these are trivially
   true, which means they stop carrying information. Either keep collecting them
   against the container's own world or define a schema that states the isolation
   differently — do not quietly pass `true` and call the contract satisfied.
4. **Image digest as baseline attestation.** Decide whether `baseline.sha256`
   stays a database-file hash or becomes an image digest, and keep one frozen
   meaning per scenario version. Do not retrofit historical receipts.
5. **Concurrency and the license/asset boundary.** Two containers means two game
   worlds; confirm nothing in the private asset bundle or runtime credentials
   assumes singleton use.

## Sequencing

This is **M1.3/M1.4 content and runs in parallel with M2**, per the roadmap's own
dependency chain. It must not block v1 collection.

v1 (4 models × 4 repetitions on `hero-cave`) stays on the current laptop renderer
at 1× on the current reset path. That cohort is the regression oracle: without a
clean baseline on the existing architecture, a post-containerization change in the
XP distribution cannot be attributed to either a fixed defect or a new one.

Ownership stays as the roadmap defines it — MapleBench owns the runtime and
evidence contract, `agent-devops` owns the image build and deployment receipts.
The image *definition* is a MapleBench artifact; building and shipping it is not.
