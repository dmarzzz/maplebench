# Admission for the next three-class pilot matrix

This is a readiness contract for a future finite matrix, not a runtime launch
plan or a claim that newly provisioned workers are accepted. The target is one
four-model group for each of Hero, Bowmaster and Ice/Lightning Arch Mage. Keep
each group labeled as a five-minute port pilot. The [roadmap](ROADMAP.md) records
which effects and cohorts have actually been demonstrated.

## What qualifies a worker

Both new workers must independently pass the same checks. A successful import,
HTTP 200, running web service or another machine's native receipt is insufficient.
Deployment configuration, credentials and addresses stay in private operations
records; the public evidence needs safe build, fixture and worker fingerprints.
The current two-worker allocation has the same four dedicated vCPUs, 16 GB
memory and Ubuntu 24.04 base. Bootstrap must validate each intended host's
identity before provisioning its runtime; no broader host allowlist or copied
live session is implied by adding a second worker.

| Gate | Evidence required before the first evaluated request |
| --- | --- |
| Isolation and expiration | Separate infrastructure state, dedicated access identity/firewall, own database, world, Chrome/display, relay, output roots and admission locks. An external deletion controller is installed before provisioning and binds the exact created resource IDs. The private deadline is finite and leaves time for cleanup and verified off-host backup. The original pilot remains independent. |
| Exact runtime | Hash-verified private import; clean source commit and complete Python/JS/native dependency closure; actual client JS/WASM pair, game JAR, assets, SDK container, Java/Python/Chrome and configuration fingerprints. Generate a new manifest from the measured worker. Never copy the old host's manifest, service invocation, locks or account session as proof. |
| Comparable capacity | Declare CPU, memory, render backend, browser viewport and capture configuration. Measure fresh loaded-game rendering, input latency, frame gaps, encoder backlog and peak resource use. Use the same declared capacity for a comparison; do not change it while a group runs. Package installation and heavy builds do not share a worker with a live group. |
| Ownership and idle state | No unresolved prior API or native operation; original-owner terminal closeout; empty queue, paused background workers, offline account and owned stopped world before restore. Hold that worker's normal operation, world, queue and runner locks through the established restore/login/collect/logout path. Start only its one pinned browser/relay. |
| Native qualification | Fresh native identity on that exact source, client, class baseline and worker; actual jump, mapped skill effects and damage as declared below; verified capture and ordinary save. The scripted check uses zero model calls and is never admitted or published as an evaluated model. |
| Final readiness | Native cleanup and exact baseline restoration confirmed; fresh pinned waiting browser, idle capture, settled artifacts and current service identities. Frozen runtime preflight must pass before the class plan is admitted. Changed source, assets or services require revalidation and new pins. |

The source closure must include the actual recorder/controller and native skill
repairs, not merely a repository HEAD with similarly named files. R6's accepted
runtime revision is historical provenance, not authority to reuse its private
manifest on a new host. A changed client requires fresh native checks before
model evaluation; source-only or synthetic tests do not replace that gate.

## Class fixtures and qualification scope

Restore each declared baseline only with the owned world stopped and account
offline. Hash the exact private SQL and independently measure the restored
character, inventory, equipment, learned skills and key types/IDs. Pin job/level,
map/spawn, stats, XP, resources, supplies and allowed skills. A SQL-derived expected
snapshot may prepare a check, but the model plan must use the actual observed
restored snapshot from successful native qualification. After every attempt,
ordinary logout/save and the same restored fixture must verify again.

| Class | Already demonstrated on the original pilot | Required on a new worker; additional claim gates |
| --- | --- | --- |
| Hero | Visible movement, jump, buffs, Brandish damage, ordinary positive saved XP in model runs; R5 has three accepted results and one unscored failure. | Re-prove mapped controls, native damage, capture, save and restoration from the declared Hero fixture. Run a fresh complete four-model group; R5 is not four successful results. A level transition or fixed-cutoff XP claim additionally needs native ledger acceptance. |
| Bowmaster | Discrete Hurricane damage, Arrow Rain effect/damage, Soul Arrow/Sharp Eyes, jump and restored baseline. R6 has four accepted zero-XP port results. | Re-prove the scoped ranged effects and resource behavior. A faithful continuous-Hurricane claim additionally needs held-channel cadence, native damaging hits while held, correct release/stop behavior and resource/ammunition evidence on a repaired client. The current discrete-cast port must retain its limitation if used unchanged. Real-arrow consumption and Soul Arrow behavior must not be conflated. |
| Ice/Lightning Arch Mage | Chain Lightning damage, mana use, buffs, jump and directional Teleport in a scripted check. | Re-prove those effects on the new worker. Qualify area/chain behavior with multiple distinct affected entities and corresponding visible/native effects; casting animation or MP loss alone cannot pass this gate. Verify the declared range and Teleport displacement from actual observations. No four-model Mage result set has yet been accepted. |

The existing scripted check remains bounded to 30 seconds, 12 input actions,
100 SDK requests and 45 seconds of recording, with ordinary cleanup and a fresh
native ID. If those bounds cannot demonstrate a missing capability, design and
review a separately versioned finite check. Do not quietly extend the current
recipe or reinterpret an older rejected recording. See
[native acceptance](FULL_CLIENT_NATIVE_ACCEPTANCE.md) for its trust boundary.

A valid model may earn zero or negative XP, perform no useful action, or die.
Native setup acceptance must prove the declared mechanics, not force a positive
model result. Reachable monsters and native damage alone do not prove calibrated
difficulty, equal monster positions, paired RNG seeds or authoritative kill counts.
Tune difficulty only in a separately labeled development version, then freeze
new fixtures and collect new evaluation samples.

## Freeze one finite four-model plan per class

Use the exact model identities `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra` and
`gpt-5.6-luna`, with identical declared low reasoning effort within the group.
Reject a different returned model before executing its program. Freeze the
profile, prompt, SDK/reference material, physical skill slots, source closure,
baseline, scenario, manifest and adapter together. Record the actual requested
and returned model for every cycle; do not turn the final cycle into a legacy
single-response result.

The next plan may retain the measured R6 ceilings below only when its exact
source and scenario implement them. These are limits, not target consumption:

| Bound | Per trial | Four-model group |
| --- | ---: | ---: |
| Evaluated wall horizon, including inference and waits | 300 seconds | Four separate 300-second horizons |
| Model requests | 12 | 48 |
| Reserved and actual aggregate tokens | 240,000 | 960,000 |
| Maximum output per response / total | 3,000 / 36,000 tokens | 144,000 total output tokens |
| One model-authored program | 20 seconds | Same per-program bound |
| Attempted input actions / SDK requests | 1,600 / 6,000 | 6,400 / 24,000 |
| Complete SDK receipt bytes | 4 MiB | Same limit for each trial |
| Recording envelope / upload | 335 seconds / 96 MiB | Same limit for each recording |
| Outer trial / operation time | 1,200 / 360 seconds | Declared coordinator wall cap: 4,820 seconds |

Pin the explicit encoded-frame and full-horizon policies as complete objects.
The existing reserve requires 50 seconds for the model request, 20 for the
program and five for settlement before another request may start. After the
request window closes, passive observation consumes the rest of the original
300-second horizon. Report that wait; do not insert hidden inputs or reset the
clock. Preserve strict frame/PTS/hash verification and fresh physical-input ACKs.

Allocate four fresh attempt IDs, a new plan and an original admission claim on
that worker. Predeclare order and the attempted-set denominator. Stop on failure;
keep infrastructure-invalid and uncertain outcomes distinct from valid zero.
Only the original owner may recover cleanup or explicitly resume future
unsubmitted entries. Never replay an uncertain request or reuse an old ID.

## Execute and publish without confounding the matrix

Once individually qualified, one worker can run Mage while the other runs Bow.
After one group has terminal closeout and verified restoration, one declared
worker can run the fresh Hero group. This is three finite plans, twelve planned
attempts and at most 144 requests / 2,880,000 reserved tokens. It does not authorize
repetitions, replacement attempts or an unbounded queue. Before each admission,
the full plan bound plus cleanup/backup reserve must fit before that worker's
fixed shutdown deadline; otherwise reduce scope before admission or defer it.

Keep all four models of one fixture on the same declared worker and capacity.
Do not assign one model systematically to a faster worker. For repetitions,
predeclare model-order rotation and worker assignment so hardware/order effects
are not mistaken for model effects. The current single repetition is not an
order-balanced estimate. Compare models within a fixture; do not average raw
Hero, Bow and Mage XP into a winner or pool changed client versions.

Workers export only checked public packages after saving independent private
evidence backups. Use the existing finite publication follower and exact
intent/receipt reconciliation. Different gameplay workers still share one
publication owner and one canonical project state root: concurrent publishers
must not race to replace the public catalog. With parallel completions, queue
publication ownership or explicitly hand it off; a future catalog must include
all latest accepted current cohorts before submission. Never edit the frozen
config of a running follower or silently replace a newer cohort with an older
snapshot. Current Hero and Bow evidence remains present when Mage is added.

Measure completion-to-public latency and package-ready-to-public latency
separately. R6 demonstrated automatic publication but missed the one-minute
end-to-end target. Validate public bytes, anonymous playback and video range
requests; retain separate artifact-bound visual reviews. Failed or missing
attempts stay in the matrix denominator. The retired testing archive stays off
the current alias, while original private evidence and immutable receipts remain.

## Work still required

New-worker runtime bootstrap and native readiness; continuous Hurricane qualification
if canonical Bow is claimed; Mage multi-entity effects; a fresh complete Hero
group; three consecutive same-release groups; balanced repetitions; publication
under one minute; native cumulative XP, level transitions and fixed 15-second
windows; calibrated task difficulty and normalization; navigation objectives;
and independent reproducibility remain open. These pilots cannot establish a
30-minute research protocol, statistical ranking or official-client fidelity.
