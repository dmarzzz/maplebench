# Private Cosmic trial backend

`scripts/full_client_runtime.py` implements the existing durable runner's real
phase interface. It has no live defaults. Offline tests validate refusal and
recovery behavior with mocked host operations. Actual bounded trials now also
verify the pinned native JAR, ordinary login/logout, persisted scoring and saved
evidence; see the [acceptance record](FULL_CLIENT_ACCEPTANCE.md). This establishes
controlled operation, with unattended availability and broader statistical
validation still outstanding. Deploying this code does not rank an integration
recording.

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
| `docker_launcher` | Optional, exactly `/usr/bin/sudo`; produces only `/usr/bin/sudo -n <docker>` |
| `docker_socket` | Existing local Unix socket path; default `/var/run/docker.sock`, canonical target must match the manifest |

The scenario contains `program_seconds` (22 or 60), `trial_budgets` exactly equal
to the runner request's budgets, `instructions_sha256` of the bridge's formatted
PROMPT, and `reasoning:{effort:"low"}`. Keep the publication scenario's `id` and
`budgets` too. The bridge's actual limits are 80 actions/100 SDK calls for 22
seconds, or 240 actions/600 SDK calls for 60 seconds, with 3000 output tokens and
two seconds of controller termination slack. Configure a finite total token
ceiling and enough total/operation time for bounded API planning and collection.
Freeze `settlement_policy` with `capture_tail_ms:2000`,
`upload_after_program_ms:5000`, `disconnect_after_program_ms:5000`, and
`logout_after_disconnect_ms:5000`. Upload timing records when the coordinator
observed the saved receipt, rather than claiming an unavailable wire timestamp.
The disconnect deadline includes recording finalization and upload. An overrun
invalidates the attempt even if the character survived and the video was saved.

The runtime manifest includes working directory, WZ path, exact scripts/WZ
inventory, config.yaml, JAR, client JS/WASM, and existing Docker image ID. Full
inventories run outside the online session, including immediately before login
and after confirmed logout. Cheap process, identity and lock checks continue
while the character is online. The JAR must contain
`server/bots/MapleBenchPersistence.class`. The owned trial drop-in overrides
WorkingDirectory and ExecStart with the pinned Java/JAR/WZ paths, a 1536 MiB Java
heap and two active processors. Actual process arguments and service working
directory are checked after start. The prior service launch returns when the
owned runtime drop-in is removed; no persistent service change is required.
New trials require runtime manifest schema 2. Its `docker_binding` has exactly
`schema_version:1`, `executable:{path,sha256}`, `launcher:null` or
`launcher:{path:"/usr/bin/sudo",sha256}`, and `socket_path`. Paths name the
canonical existing executable and local Unix socket. The freezer's
`docker_command` is either `[absolute_docker]` or exactly
`["/usr/bin/sudo","-n",absolute_docker]`; the backend configuration must select
the same command and endpoint. No image is pulled. Schema 1 remains verifiable
for historical evidence but cannot authorize a new production trial.

The private `start` request must include the frozen `docker_binding` alongside
`docker_image_id`. The bridge validates it before claiming a new attempt and
again before the provider call; the executor checks it at launch and cleanup.
The binding becomes part of the immutable request identity and private result.
Public start, status and renderer-poll responses omit these host paths. The
runtime and publication validator require the result's `dockerBinding` and
`dockerImageId` to match the schema-2 runtime artifact.

Inspection, execution and cleanup use the same fixed executable/launcher and
explicit `--host unix://<socket_path>`. Each invocation has a fresh mode-0700
directory containing an empty Docker config, passed with `--config`, and a
minimal fixed environment. Inherited `MAPLEBENCH_DOCKER_COMMAND`, Docker
contexts/hosts/configuration, HOME, PATH, XDG settings and credentials cannot
redirect trial execution. Cleanup reuses the launch invocation and checks the
executable pin again; drift fails the run without executing the changed binary.
Generic non-trial adapters retain their existing operator-configured invocation.

The host administrator remains responsible for the parent directories and
socket service: these pins check executable bytes/owner/mode and the canonical
socket's type/owner/mode, but do not authenticate a daemon against root or hash
every ancestor. Python import roots, virtual-environment package bytes and
third-party dependencies are a separate deployment gate; this Docker binding
does not establish their complete identity.

The manifest's `extra_files` must include the serving script, its sibling
`full_client_bridge.py`, `full_client_session.py`, `full_client_capture.py`, `full_client_docker.py`, `maple_agent.py`,
`agent-sandbox.mjs` (the exact JavaScript dispatcher supplied to Docker), repository
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
full_client_docker, and maple_agent. Protect those sources and configuration from other users.

Operational errors cross the backend/runner/dashboard boundary only as exact
reviewed codes. Freezer failures such as `inventory_timeout` and
`runtime_manifest_drift`, and relay failures such as `recorder_not_ready` or
`docker_binding_required`, remain visible. Unknown codes, additional error
fields, raw stderr, private paths and arbitrary exception strings keep a generic
failure. A code looking like an identifier does not make it safe.

Apply the shared-host two-CPU bound to the runner and its subprocesses as well
as the game server. An `RLIMIT_CPU` value limits accumulated CPU seconds; it
does not restrict the number of available CPUs. During release acceptance, the
Docker image check exited 2 under a 768 MiB address-space cap with unrestricted
CPU affinity, then succeeded with the same cap and two-CPU affinity. Full runner
preflight subsequently passed with that affinity. Use an explicit allowed CPU
set or a validated equivalent; do not resolve this prerequisite failure by
removing resource limits or changing frozen game inputs.

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
   Cosmic-owned mode-0700 child for a new journal and the owned runtime drop-in
   `zz-maplebench-trial.conf`, ordered after existing `seed.conf` overrides,
   preserving the nonroot service user and overriding only the trial launch. The drop-in sets
   2300 MiB memory, no swap, two CPUs, a bounded lease, and the five native trial
   variables documented below. A start is never automatically replayed.
   Before ordinary login it also requires the fresh invocation's native journal
   initialization and Cosmic online marker plus every configured listening port
   owned by that exact JVM PID; Type=simple process activation is insufficient.
   Startup observations retain only invocation-bound byte/marker counts and
   listener readiness in the private backend journal. A deadline reports the
   last missing evidence (native log, journal initialization, online marker or
   owned listener) when the wait expires after a complete observation. A timeout
   inside an incomplete probe retains `operation_deadline`. These
   codes describe observed evidence, not an inferred underlying server cause.
   Duplicate startup markers fail as ambiguous. `journalctl` still reads only
   the owned invocation under the command output/time limits; there is no
   fallback to an unrelated log. Process tables are byte-bounded and native
   socket enumeration stops at 4,096 descriptors, checking the deadline while
   traversing descriptors and network rows.
4. `login` uses the private socket's ordinary `connect` navigation, then observes
   fresh rendered gameplay and actual account state 2 before recording login.
5. `run_controller` validates the frozen prompt/budgets and sends exactly one
   private `start` with run ID equal to request ID, exact model/image, token
   ceiling, trial context and lock descriptions. A lost response stays uncertain.
   It waits for that exact terminal run and both recording/evidence uploads,
   durably records a disconnect intent, and immediately requests ordinary
   navigation to waiting. It independently waits for DB offline and one positive
   native commit before copying or verifying artifacts. This ordinary logout is
   part of the preauthorized controller operation and has its own durable backend
   intent, so an interrupted response cannot cause an API replay.
   Actual request/response/program/result/video bytes retain their exact bindings;
   capture and media verification occur offline.
6. `disconnect` verifies the already completed ordinary disconnect and its
   durable native commit receipt. It does not issue a second navigation or save.
   Offline alone and forced service stop cannot manufacture a save receipt.
7. `collect_final` exports the offline numeric row, native journal and actual
   fresh invocation's stdout/stderr, constructs the measured lifecycle bundle,
   probes the encoded recording and checks the frozen settlement policy and
   capture receipts, then calls `verify_trial_bundle`. Journal initialization and absence of native
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

Cleanup journals the exact owned drop-in path/hash before removing the file,
fsyncs its directory, and checkpoints the required systemd reload. Explicit
recovery after an interrupted removal repeats only that reload. A missing file
alone does not authorize reloading unknown configuration. Both clean cleanup
and subsequent ready status require no trial file, no effective trial drop-in
or native trial environment, and `NeedDaemonReload=no`. A successful reload
command alone is insufficient. The checkpoint is verified before returning
clean, so a crash between unlink and reload cannot expose cached trial settings
to the next attempt.

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
