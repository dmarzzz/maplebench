# Automated batches

MapleBench has a durable, single-world worker for Orbital One or another dedicated
Linux host. Model inference uses OpenAI's API. JavaScript programs run in disposable
Docker containers with no network or credentials, and a trusted proxy exposes only
scenario-approved game actions. See [programmable control](PROGRAMMABLE_AGENT.md).

The worker consumes a persistent SQLite queue, resets the full disposable database,
boots the selected character/map, records the server, scores the attempt, renders
its labeled replay, and publishes a browsable local gallery. The first rollout
uses this local worker; a Harbor adapter is not implemented yet.

## Prepare the dedicated host

Follow [the server setup](HENESYS_DEMO.md) and [scenario setup](SCENARIOS.md). Install
Docker, Python 3, Node 22, FFmpeg/ffprobe and the existing Cosmic/Maplewright tools on
the experiment host. Keep all game downloads, WZ data and caches there. Pull the
sandbox image once:

```bash
sudo docker pull node:22.19.0-bookworm-slim
```

Create a baseline dump of the dedicated `maplebench` database while Cosmic is
stopped. Store it outside Git in a private directory, mode 0600. The worker never
uses personal game accounts or databases. Each scenario seeds synthetic characters,
then resets stats, equipment, learned scenario skills and finite potion inventory.
The complete database dump is restored before every attempt.

Set host-only environment variables (paths below are placeholders):

```bash
export MAPLEBENCH_WORK=<work-directory>
export MAPLEBENCH_DB_SNAPSHOT=<private-directory>/baseline.sql
export MAPLEBENCH_API_KEY_FILE=<private-directory>/openai-key
export MAPLEBENCH_DOCKER_COMMAND='sudo -n docker'
```

Use `scripts/install-services.py --work ... --key-file ...` to install the persistent
worker and localhost gallery services. It requires passwordless administrative
access on the dedicated host and reads the key from its private file; the key is
never included in a unit file, prompt, child sandbox, or source archive. The Cosmic
service and database also need to be configured to start after a host reboot.

## Submit, inspect, and resume

Run from the repository on the experiment host:

```bash
python3 scripts/maplebench.py submit configs/smoke-20.json --batch smoke-20
python3 scripts/maplebench.py status --batch smoke-20
```

The manifest creates four API models × five repetitions. Models are rotated in
order between repetitions. To run without an installed worker service:

```bash
python3 scripts/maplebench.py worker --batch smoke-20 --work "$MAPLEBENCH_WORK"
```

Run the same worker command after an interruption to resume. Submission deliberately
rejects an existing batch ID. Every retry has a separate attempt directory and the
gallery retains interrupted and failed attempts. A recorded final score is adopted
after a worker crash, preventing a second paid model run. Rendering recovers
separately; it validates the MP4 and never reruns inference to repair a clip.

`configs/hero-c1-10m.json` runs four models for up to ten minutes each using the
level-130 Hero in Magatia. `configs/crusader-c1-10m.json` uses the level-100 Crusader.
The short town fixture remains an integration check, not a model ranking.

## Frozen inputs and budgets

Submission copies the runner/controller source, server JAR, server scripts,
configuration, WZ XML, database snapshot, character/map bakes and native renderer
into an ignored batch directory. It pins the local Docker image ID. Development
can continue while those frozen inputs run. Monster sprite export still uses the
shared localhost asset service; leave that service and its art files unchanged
until the queue drains. Never publish the `_runtime` directory: it includes private
server configuration and the database snapshot. The gallery server denies access
to it, `_source`, SQLite files, raw manifests, and arbitrary filesystem paths.

Each attempt reserves bounded API calls and tokens before starting. Known completed
usage releases unused reservations; an interrupted attempt with unknown provider
usage consumes its full reservation. This favors staying within the configured
budget over silently issuing replacement calls. Retries are limited and only
infrastructure failures are retried automatically. Death, a time/action/decision
limit, and poor XP are legitimate model outcomes.

Combat randomness remains unseeded. Trials share an initial snapshot, not a claim
of bit-for-bit deterministic trajectories. Wall time includes API latency and
program execution. Events after the scenario deadline are excluded from scoring.
The verifier records total XP, average XP/min, a trailing 60-second peak, deaths,
HP, actions, token usage, and whether a complete 60-second window was observed.

## Results

The installed gallery listens on localhost:8830. Access it through an SSH tunnel;
the root page lists available batches. Every successful recording has a score,
model/program trace, provenance metadata, an MP4 with the model overlay, and a
thumbnail. [Gallery details](RESULTS_GALLERY.md) describe filtering and evidence.
Replays interpolate server observations and attack poses. Brandish damage is real
server damage; its full skill visual effect is not currently reproduced.

The queue is durable across SSH loss. Its systemd worker restarts after failure;
reboot recovery also requires the host's dedicated Cosmic/MySQL services to be
persistent. This does not install a recurring Codex automation or silently submit
unlimited new experiments.
