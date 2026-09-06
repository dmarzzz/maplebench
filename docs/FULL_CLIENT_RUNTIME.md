# Private Cosmic trial backend

`scripts/full_client_runtime.py` implements the existing durable runner's real
phase interface. It has no live defaults. Its offline tests validate refusal and
recovery behavior with mocked host operations; this backend remains **unverified
for live production trials** until an actual end-to-end trial succeeds with the
pinned native persistence JAR, ordinary browser login/logout, and saved evidence.
No existing integration recording becomes ranked by deploying this code.

The runner/backend execute as root on Linux. Existing Cosmic and web services
must declare existing nonroot users. The backend does not provision services,
launch another relay/browser, stop the normal worker, seize locks, or choose a
baseline. It refuses an active world helper or normal worker. Operator-selected
frozen SQL executes only while Cosmic is stopped and the account is offline.

## Private configuration

Supply one root-owned mode-0600 JSON file. All paths below are absolute, resolved
paths supplied on the runtime host; never commit this configuration or its
contents. The required version-1 fields are:

| Field | Contract |
| --- | --- |
| `services` | Four distinct existing `.service` units keyed `world`, `worker`, `cosmic`, `web` |
| `world_lock`, `queue_lock` | Existing distinct lock files used by the normal world/queue tools |
| `queue_database` | Existing private queue SQLite file; queued/running/rendering row count must be zero even when the worker is stopped |
| `attempt_root` | Existing root-owned mode-0700 runner attempt directory |
| `admin_socket` | Existing private AF_UNIX socket belonging to the web service |
| `relay_output_root` | Existing root-readable private bridge run-artifact directory |
| `native_output_root` | Existing Cosmic-owned mode-0700 directory, or root-owned mode-0711 directory; all ancestors permit service traversal |
| `mysql` | `{command:[absolute_mysql_executable], database, defaults_file:null-or-private-path, character_id, account_id}`; no credentials in argv |
| `baseline` | `{path,sha256}` for the reviewed frozen SQL, at most 64 MiB |
| `baseline_snapshot` | `{path,sha256}` for the offline collector snapshot matching that SQL; full numeric character and keymap are compared after restore |
| `scenario` | `{path,sha256}` for the frozen scenario JSON |
| `runtime_manifest` | `{path,sha256}` for the inventory produced by `full_client_freeze.py` |
| `orchestrator` | `{path,sha256}` for the exact root/guard `full_client_trial.py` source |
| `java` | `{path,sha256}` for the resolved existing Java executable used by the owned trial drop-in |
| `web_script`, `web_python` | Absolute serving script path and `{path,sha256}` for its resolved Python executable |
| `game_ports` | Actual login/channel TCP ports; each must be listening on a socket owned by this Cosmic PID |
| `dropin_root` | Exactly `/run/systemd/system` |
| `systemctl`, `journalctl`, `docker` | Absolute existing host executable paths |

The scenario contains `program_seconds` (22 or 60), `trial_budgets` exactly equal
to the runner request's budgets, `instructions_sha256` of the bridge's formatted
PROMPT, and `reasoning:{effort:"low"}`. Keep the publication scenario's `id` and
`budgets` too. The bridge's actual limits are 80 actions/100 SDK calls for 22
seconds, or 240 actions/600 SDK calls for 60 seconds, with 3000 output tokens and
two seconds of controller termination slack. Configure a finite total token
ceiling and enough total/operation time for bounded API planning and collection.

The runtime manifest includes working directory, WZ path, exact scripts/WZ
inventory, config.yaml, JAR, client JS/WASM, and existing Docker image ID. Every
phase checks these inputs before and after. The JAR must contain
`server/bots/MapleBenchPersistence.class`. The owned trial drop-in overrides
WorkingDirectory and ExecStart with the pinned Java/JAR/WZ paths, a 1536 MiB Java
heap and two active processors. Actual process arguments and service working
directory are checked after start. The prior service launch returns when the
owned runtime drop-in is removed; no persistent service change is required.
Docker inspection uses the existing local Unix daemon and never pulls images.
The manifest's `extra_files` must include the serving script, its sibling
`full_client_bridge.py`, `full_client_session.py`, `full_client_capture.py`, `maple_agent.py`, repository
`ui/full-client/controller.js` and `waiting.html`, and client root
`web/index.html`, `assets_server.py`, and `ws_proxy.py`. The actual nonroot web
process's interpreter, entrypoint, environment roots, output/admin/lock paths
must match; it must have started after these source files last changed.
Also include every resolved client `assets/*.nx` target in `extra_files`.
The backend requires exactly that NX inventory and filename-preserving links;
changed links, missing assets, unexpected entries and nested directories fail.
The existing asset files are hashed in place, never copied into the repository.

Configure the runner's command adapter with absolute Python executable, backend
script, `--config`, and config path. Include all imported source dependencies in
its frozen dependency list: collector, freeze, score, trial, publisher, bridge,
and maple_agent. Protect those sources and configuration from other users.

## Ownership, browser, and phases

The backend checks actual `/proc` ancestry `runner -> guard -> backend`, exact
root/guard source command lines, and both lock inodes held by the root PID in
`/proc/locks`. The guard passes the two inherited lock descriptions to the
backend. `start` transfers them with `SCM_RIGHTS` and exact `lock_paths` to the
private web socket, whose configured expected paths must match. The bridge
retains those descriptions until API/program execution is quiescent even if the
runner dies. No phase opens a replacement lock and calls that ownership.

1. `status` performs read-only service, private browser, offline-account, and
   frozen-input checks. Ready requires a fresh pinned waiting page and settled
   uploads. A static game character does not establish readiness.
2. `restore_baseline` records durable intent, privately copies the exact frozen
   SQL/input artifacts, checks the stopped/offline conditions again, requires
   transactional score tables, applies SQL once, and compares an actual offline
   snapshot to the frozen full character/keymap. A partial failure stays failed.
3. `start_server` persists its unique owner, native directory, expected drop-in
   bytes and previous invocation before changing the service. It creates a
   Cosmic-owned mode-0700 child for a new journal and one owned runtime drop-in,
   preserving the nonroot service user and overriding only the trial launch. The drop-in sets
   2300 MiB memory, no swap, two CPUs, a bounded lease, and the five native trial
   variables documented below. A start is never automatically replayed.
   Before ordinary login it also requires the fresh invocation's native journal
   initialization and Cosmic online marker plus every configured listening port
   owned by that exact JVM PID; Type=simple process activation is insufficient.
4. `login` uses the private socket's ordinary `connect` navigation, then observes
   fresh rendered gameplay and actual account state 2 before recording login.
5. `run_controller` validates the frozen prompt/budgets and sends exactly one
   private `start` with run ID equal to request ID, exact model/image, token
   ceiling, trial context and lock descriptions. A lost response stays uncertain.
   It waits for that exact terminal run and both recording/evidence uploads,
   copies actual request/response/program/result/video bytes, verifies their
   model/prompt/observation/code bindings, and probes the saved video.
   It retains the raw capture/clock/first-frame/terminal receipts and recomputes
   bounded continuous coverage of API planning and the program. A stopped or
   interrupted recorder fails that phase even if a video upload exists.
6. `disconnect` uses ordinary browser navigation to waiting, independently waits
   for DB offline, and requires one positive native commit during that disconnect.
   Offline alone and forced service stop cannot manufacture a save receipt.
7. `collect_final` exports the offline numeric row, native journal and actual
   fresh invocation's stdout/stderr, constructs the measured lifecycle bundle,
   and calls `verify_trial_bundle`. Journal initialization and absence of native
   save/journal failures are checked from actual logs by that verifier.
8. `cleanup` disconnects/stops only a process matching its durable owner,
   invocation, nonroot user, exact JAR, native environment and drop-in. It removes
   only that exact drop-in, leaves private evidence intact, and reports clean
   only when Cosmic is stopped and the account offline. Recovery never retries
   SQL, API or server start. Missing or ambiguous ownership requires intervention.
   An owned active controller is cancelled once, then polled until its worker
   stops and the browser acknowledges key release. Available failure files and
   status are retained before `release_failed_run` allows ordinary navigation;
   original bridge recordings remain in place, including failed recordings.

The native variables are `MAPLEBENCH_TRIAL_ID`,
`MAPLEBENCH_SERVER_INSTANCE_ID`, `MAPLEBENCH_PERSIST_CHARACTER_ID`,
`MAPLEBENCH_PERSIST_ACCOUNT_ID`, and `MAPLEBENCH_SAVE_JOURNAL`. The native journal
is copied into the root evidence directory after ordinary logout; the service
never needs access to the root attempt directory. Native journal creation must
remain create-once and fsynced by the patched server.

The stdin request is `{operation,context,timeout_seconds}` and stdout is the
direct JSON phase receipt expected by `CommandAdapter`. Failures return a safe
code and nonzero exit status without raw subprocess stderr or private input.
All service/SQL invocations use argv, not a shell. Subprocess output and deadlines
are bounded; the runner guard provides process-group/orphan cleanup.

## Evidence limits

Collection verifies artifact bytes and trusted-host consistency, not the honesty
of the host operator. It computes persisted net XP only after the native save
proof and offline DB exports pass. The result remains `publication_eligible:false`.
The recording receipt's `reviewed:false` remains unchanged. Actual measured
coverage is checked from the raw capture bundle, while a real visual review is
still required by the separate version-2 publication gate. Successful upload
alone cannot establish uninterrupted coverage or replace that review.
`publication-candidate.json` assembles that gate's target schema from the actual
collected artifacts, frozen budgets and verified score. Its `run_kind:ranked`
states the proposed publication category only; `candidate_status` identifies
pending review, `video.reviewed` remains false, and no visual review receipt or
readiness assertion is created. Review the exact video hash later, attach a real
`video_review`, and run the gate before publication.
