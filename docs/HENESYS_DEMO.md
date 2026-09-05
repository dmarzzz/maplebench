# Henesys server demo

The demo runs a synthetic level-15 Warrior through the real Cosmic movement and
requested-attack methods. The baseline policy chooses the closest monster, walks
within sword range, and requests a basic attack. Normal server damage, cooldown,
monster HP, death, and experience handling remain in effect.

The first successful scripted run recorded 11 accepted actions, one rejected
attack, 30 XP gained, and zero XP during its initial idle check. It produced an
18.2-second replay including the idle period. These are smoke-test results, not
a standardized benchmark score.

Henesys is a town. `MAPLEBENCH_DEMO_MOBS=true` explicitly adds three ordinary Slimes
as a combat fixture during startup; they are not natural town spawns. Startup
equipment and placement are scenario setup, outside the agent action API.

## Server setup

Use the pinned upstreams and bootstrap overlay with `npm run bootstrap`. Cosmic
requires Java 21, Maven, a dedicated MySQL database, and compatible WZ XML game
data. Follow its upstream setup instructions; do not use a personal game account
or production database. Apply `scripts/seed-cosmic.sql` only to the dedicated
experiment database and use its resulting synthetic character ID.

Run the built server with these environment variables:

```bash
MAPLEBENCH_ENABLED=true
MAPLEBENCH_BOT_NAME=Agent01
MAPLEBENCH_CHARACTER_ID=<synthetic-character-id>
MAPLEBENCH_MAP_ID=100000000
MAPLEBENCH_DEMO_MOBS=true
MAPLEBENCH_EPISODE=<ignored-output-directory>/episode.jsonl
```

The control API binds to localhost by default. Keep the server and database
isolated; use an SSH tunnel for access from another machine. Runtime configuration
and generated passwords belong outside the repository in files readable only by
the runtime user. Do not enable the demo fixture on a shared game server.

The controlled-character tick disables upstream autonomous grinding, shopping,
chat, and other policy decisions, while retaining requested movement, action
timers, physics, and incoming monster damage.

## Record an experiment

```bash
npm ci
npm run build
MAPLEBENCH_OUTPUT=artifacts/henesys-demo \
MAPLEBENCH_DURATION_MS=16000 node scripts/run-cosmic-smoke.mjs
```

The script verifies the real backend and checks for zero XP during an initial
two-second idle period. It writes observations, authoritative events, and a score.
It exits unsuccessfully if no XP was earned. Restart/reset the synthetic scenario
between experiments; this script is not yet a deterministic benchmark resetter.

## Render the clip

Maplewright needs separately obtained v83 WZ art. Keep assets and baked images
outside Git. With the work directory containing `maplewright`, `baked/henesys`
(foreground, footholds, backgrounds), and `baked/warrior` (character frames):

```bash
node scripts/patch-maplewright.mjs
# Rebuild the patched native client and wzchar; export the equipped character
# again so the manifest includes the swing and stab animation frames.
MAPLEBENCH_WORK=<work-directory> \
  node scripts/render-cosmic-clip.mjs artifacts/henesys-demo
```

The monster asset service must be listening on localhost:8820. The renderer
requires FFmpeg with libass support. It creates a plain MP4 and an MP4 with action,
HP, level, elapsed-time, and XP overlays in the ignored experiment directory.

The video is a **Maplewright replay of an actual Cosmic server run**, not a screen
capture of an official client. Character positions are interpolated between
observations; walk and attack poses are presentation animations inferred from
movement and accepted action events. Monster HP and XP come from the server.
The overlay discloses these rendering boundaries.
The camera follows horizontal movement smoothly and holds its vertical reference
for this flat-ground fixture. Floating damage labels show observed HP loss,
including the remaining HP on a kill, rather than invented per-hit damage rolls.

The overlay also reads `controller.json` from the experiment directory. If absent,
it labels the nearest-monster baseline and states that no model ran that policy.
For external agent control, `scripts/record-cosmic-run.mjs` records observations
without issuing any actions. Set `MAPLEBENCH_CONTROLLER` and `MAPLEBENCH_MODEL`
to the actual controller and model identity, then submit actions separately.
These labels are operator-supplied metadata, not model-provider attestation.

## Four-model API batch

After configuring the dedicated `maplebench-cosmic` service and disposable
`maplebench` database, provide `OPENAI_API_KEY` through the environment or set
`MAPLEBENCH_API_KEY_FILE` to a private file outside the repository. Then run:

```bash
python3 scripts/run-openai-queue.py --preflight --output artifacts/preflight
python3 scripts/run-openai-queue.py --output artifacts/openai-batch-001
```

The queue currently compares `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, and
`gpt-5.6-luna` using OpenAI's API, low reasoning effort, and structured action
outputs. Each run has a 90-second/12-decision limit and resets the synthetic
Warrior's health, experience, stats, and placement. It stops early after all
Slimes die. A file lock serializes access to the single world.

The operator running the queue needs permission to restart that dedicated service
and reset that dedicated database. For unattended work, launch it under a process
supervisor so a dropped SSH connection does not cancel experiments.

The recorder samples at 10 Hz and saves prompt, provider-returned model identity,
action intentions, outcomes, usage, latency, observations, and score. No API
credential is included in prompts or saved artifacts. This fixture is too small
and unseeded combat randomness too influential to infer model rankings from a
single run each.

Validation: the framework's four scoring tests and three action-boundary tests
pass. The upstream bot suite ran 403 tests with one remaining failure in
`BotMovementSimulationLabTest.shouldReachMoveTargetOnFlatGround`; its other
402 tests passed. Treat precise navigation as a known limitation.

## Before committing

Enable `.githooks`, install Gitleaks on the development host, and run the tracked
file guard and redacted current-file and full-history scans. Keep assets, databases,
host configuration, recordings, and account information out of Git. Synthetic
example data is safe to retain; real run outputs remain ignored.
