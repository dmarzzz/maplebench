# Full-client persistence scoring

`scripts/full_client_score.py` calculates `net_xp` from supplied server persistence
evidence. It is the offline scoring component used by the durable full-client
trial adapter. Actual trials now restore an offline baseline, use ordinary
login and logout, and collect positive native save receipts. Historical demos
remain unranked integration runs. The publication gate supports persisted-character
evidence in schema 2 only after verifying the actual bundle. The calculator alone cannot grant ranked eligibility. Schema 1
publication manifests are structural legacy attestations and never return ready.

```sh
python3 scripts/full_client_score.py /path/to/private/trial/persistence.json
```

The command emits JSON and exits 0 for a scored record, 1 for insufficient or
inconsistent evidence, and 2 for unreadable or invalid JSON. It does not touch
the database, services, queue, or browser. Duplicate JSON keys, nonfinite numbers,
and JSON files over 16 MiB are rejected.

## Collection contract

The trusted trial runner collects these records from the actual server
and database. Boolean fields are attestations by that collector, not permission
to perform operations. Hashes bind evidence; this calculator cannot authenticate
its origin or check referenced files. Never synthesize missing receipts to make
an integration run scoreable.

The version 1 evidence object has these fields:

| Field | Required contents |
| --- | --- |
| `schema_version`, `source`, `run_id` | `1`, `cosmic_persisted_character`, unique attempt ID |
| `scenario_fingerprint` | SHA-256 of the frozen scenario inputs |
| `baseline` | `sha256` of the private frozen database backup, and `character` |
| `reset` | Matching `run_id`, `baseline_sha256`, `completed_at_ms`; `world_lock_held`, `queue_lock_held`, `server_stopped`, `verified` all true |
| `initial`, `final` | Matching `run_id`, `source`, `character`, `captured_at_ms`, `account_logged_in: 0`, and `evidence_sha256` of each raw database export |
| `session` | Matching `run_id`, unique fresh `server_instance_id`, `disconnect_kind: normal`, both `world_lock_held_throughout` and `queue_lock_held_throughout` true, timestamps below, and `save` |

Every `character` contains integer `character_id`, `account_id`, `level`, `exp`,
and `hp` from the database. Additional baseline fields are allowed; the complete
initial character object must exactly match the baseline object. Both final
character/account IDs must match. Version 1 supports levels 1–200 and requires
the level to stay unchanged. It rejects level transitions instead of reporting
the level XP rollover as a loss. A pinned experience table is needed to extend
that contract.

The required session timestamps, in order, are `server_started_at_ms`,
`login_at_ms`, `api_started_at_ms`, `api_ended_at_ms`, `controller_started_at_ms`,
`controller_ended_at_ms`, `disconnect_requested_at_ms`, and `logged_out_at_ms`.
All timestamps are integer milliseconds from the same trusted host clock.
The baseline restore and initial database read precede the fresh server start;
the final read follows logout. A backwards clock invalidates the evidence.
Keep monotonic budget enforcement in the runner as well.

`session.save` requires:

- `status: confirmed`, matching `run_id`, `server_instance_id`, and `character_id`.
- `committed_at_ms` between the disconnect request and confirmed logout.
- `evidence_sha256` identifying positive server save-completion evidence.
- `logs_sha256`, `log_checked_from_ms`, `log_checked_through_ms`, and
  `save_error_count: 0`, covering fresh server start through the final read.

Offline account status and the absence of error messages alone are insufficient
to manufacture a confirmed save receipt. The collector still needs an observable
save-completion signal from the pinned server, bound to this session. A process
kill cannot stand in for normal disconnect. Raw evidence stays private.

## Output semantics

`metrics.net_xp` is final persisted XP minus initial persisted XP. It includes
death penalties, accepts zero, and preserves negative scores. Gross XP, monster
kills, damage, or survival throughout the run cannot be inferred from two rows.
`alive_at_logout` describes only final HP, not whether the character died earlier.

`timing.session_ms` covers login through logout, including API planning and
settlement. `api_ms`, `controller_ms`, and `settlement_ms` are reported separately;
settlement begins when controller execution ends. Output `evidence_sha256` hashes
the entire parsed evidence object using sorted compact UTF-8 JSON (with Python's
default ASCII escaping and no nonfinite numbers). It is not a hash of the original
JSON file bytes. `publication_eligible` is always false.

## Durable adapter and comparison scope

The [durable runner](FULL_CLIENT_RUNNER.md) and [Linux backend](FULL_CLIENT_RUNTIME.md)
acquire the existing locks, restore the baseline with Cosmic stopped, verify the
actual fresh server process, and coordinate one browser through ordinary login,
bounded API control, normal disconnect and final offline collection. Fsynced
intents preserve uncertain attempts; explicit recovery cleans up without replaying
an API request. The [results dashboard](FULL_CLIENT_DASHBOARD.md) shows completed
persisted scores and retains failed attempts.

Four actual models have completed one trial each from the same frozen inputs.
That establishes preliminary multi-model operation. A public ranking still needs
a declared repeated-trial design, balanced model order and uncertainty reporting.
Equal baselines do not make combat RNG deterministic. The separate publication
gate and exact recording review remain required for every eligible trial.

## Verifying a private artifact bundle

The durable runner calls this before completing an attempt:

```python
score = verify_trial_bundle(evidence, artifact_root, artifacts)
```

This function in `scripts/full_client_score.py` raises `EvidenceError` on missing
or inconsistent evidence. Each `artifacts` entry is `{path, sha256}` with a relative
path under `artifact_root` and the SHA-256 of the actual file bytes. Absolute paths,
parent traversal, symlinks, nonregular files, empty files, and hash mismatches fail.
JSON and JSONL artifacts are bounded to 16 MiB. The baseline and scenario files
are bounded to 4 GiB. Consumers retain the verified file descriptor, read bounded
bytes, and rehash the exact consumed bytes. File identity, size, and modification
and change timestamps must remain stable through consumption. Keep the private
bundle immutable while verifying it.

| Artifact name | Exact contents and binding |
| --- | --- |
| `baseline` | Original private frozen database backup; bytes hash to `baseline.sha256` |
| `scenario` | Frozen scenario JSON; bytes hash to `scenario_fingerprint` |
| `persistence` | Complete persistence evidence object being scored |
| `reset` | The exact `evidence.reset` collector receipt |
| `initial_db`, `final_db` | Raw numeric database snapshot JSON, equal to the corresponding evidence snapshot after removing only `evidence_sha256` |
| `session` | Exact `evidence.session` collector receipt, including save and timing references |
| `save` | Original native server save-commit JSONL journal, hashed by `session.save.evidence_sha256` |
| `server_log` | Structured collector phase JSONL journal, hashed by `session.save.logs_sha256` |
| `native_log` | Complete fresh-server stdout/stderr capture, hashed by `session.save.native_logs_sha256` |

Raw database snapshots have `schema_version: 1` and retain all safe collector
fields. Verified bundles additionally require `baseline.keymap` as numeric
`[key, type, action]` rows, identical to initial and final snapshot keymaps. Ctrl
slot 29 must be `[29,5,52]` and Space slot 57 `[57,5,53]`. This ensures malformed
menu-typed Jump/Attack bindings cannot silently enter a frozen baseline. The
complete baseline character object must still match the initial character.

The native save journal contains positive records emitted **after the database
commit**, with this shape:

```json
{"schema_version":1,"source":"cosmic_persisted_character","kind":"save_committed","run_id":"attempt-id","server_instance_id":"fresh-instance","character_id":7,"account_id":9,"committed_at_ms":7900}
```

There must be exactly one matching commit at the timestamp selected in
`session.save`; it must occur during ordinary logout. Other autosave commits in
the same run are allowed. A `save_failed` record invalidates the trial. Every
record must identify this run, fresh server instance, character, and account.
Do not fabricate a commit record from the presence of a changed database row.

The actual native stdout/stderr capture is also required, bounded to 16 MiB and
covering server initialization through final collection. It must contain exactly
one `MapleBench persistence journal initialized` marker, and no
`MapleBench persistence journal failed` or `Error saving chr` marker. A complete
JSON commit line can remain readable after its journal fsync fails; its presence
alone cannot certify durable receipt storage. Capture the original server output
and preserve its failure markers. A collector-generated clean log is not valid
evidence. The structured phase journal does not replace this native log.

The phase journal contains events with `event`, `at_ms`, `run_id`, and
`server_instance_id`. Exactly one each of `server_started`, `login`, `logged_out`,
and `collection_completed` must match the corresponding evidence timestamps;
the latter three also require `character_id` and `account_id`. Events are ordered.
Save/server failures invalidate the trial. These are actual collector observations
of the lifecycle; the native journal supplies the positive commit signal.

The verified score adds `artifacts_verified: true` but retains
`publication_eligible: false`. Hashing and cross-checking artifacts establishes
consistency, not authentication of their origin. The runtime host, native receipt
writer, database collector, and reviewer remain trusted. Private raw evidence is
never printed by either validator.

## Publication manifest version 2

```sh
python3 scripts/full_client_publish.py /private/trial/publication.json \
  --artifact-root /private/trial
```

Version 2 retains the legacy manifest's `result`, `budgets`, `timeline`, `scenario`,
`score`, and `video` sections, and adds the artifact references below. It requires
`schema_version: 2`, `run_kind: ranked`, and a result originally collected as
`source: full-client-trial`. Existing integration results cannot be relabeled.

`score` must exactly equal the recomputed verified score, including `net_xp`,
its evidence digest, timings, and final HP. `scenario.fingerprint` hashes the
frozen scenario file, which contains matching `id` and `budgets`;
`scenario.reset_fingerprint` equals the frozen database backup hash.
The frozen scenario also contains `instructions_sha256` for the exact formatted
UTF-8 controller instructions and `reasoning: {effort: ...}` for the actual API
request. The model itself is bound across the request, response, controller, and
review so the same scenario can be used to compare different models.
`result.timeline` must equal the manifest timeline. API/controller offsets must
agree with the persistence session clock to within 100 ms, and result start/end
must lie inside ordinary login/disconnect. Client observation and rendered-frame
ages must both remain under 1500 ms in each recorded observation.

| Additional artifact | Required verification |
| --- | --- |
| `result` | Exact complete result JSON, including SDK receipts and timeline |
| `score` | Exact verified score JSON, recomputed again by the publication gate |
| `api_request` | Complete actual Responses API body, including exact requested model, frozen instructions/reasoning, initial observation input, strict output schema, bounded output limit, `store:false`, and `metadata.maplebench_run_id` |
| `api_response` | Full provider response with matching run metadata, response ID, model, status, usage, and generated program output |
| `program` | Raw executed UTF-8 JavaScript bytes, identical to provider JSON output `code` and `result.programSha256` |
| `video` | Actual `.webm` or `.mp4` recording, at most 1 GiB; same path and hash as `video` section |
| `video_probe` | `{video_sha256,width,height,frames,duration_ms}` measured from the recording |
| `video_review` | `{video_sha256,run_id,overlay,reviewed:true,post_render_capture:true,reviewed_at_ms}` for the exact finished recording |

The supported request body has exactly `model`, `store`, `reasoning`,
`instructions`, `input`, `max_output_tokens`, `text`, and `metadata`. `input` is
JSON text containing exactly `{observation: result.initial}`. The `text.format`
contract is the strict `maple_program` JSON schema in `scripts/maple_agent.py`:
an object containing only string fields `note` and `code`, both required. Hidden
prior response IDs, tools, extra input context, or a changed prompt fail closed.

The validator invokes `ffprobe` itself with a 30-second timeout against the
retained verified descriptor (`/proc/self/fd` on Linux, `/dev/fd` on macOS), and
compares the actual video stream's dimensions, decoded frame count, and duration
to the saved probe and manifest. Replacing the pathname cannot substitute a
different video during probing; in-place changes or path changes are rejected.
Missing ffprobe, invalid media, incomplete coverage, or
missing review fails closed. Review confirms the actual run/model overlay and
post-render capture; an automated metadata check cannot replace that visual check.
The `overlay` is `{controller_id,mode:"api",model}` and must match the exact
requested and returned model. API keys and request headers never belong in artifacts.

Version 2 supports exactly one API request per trial. Frozen budgets include
`api_requests:1`, `output_tokens`, `total_tokens`, `program_ms`, `run_ms`, `actions`,
and `sdk_requests`. SDK holds must be fully acknowledged; receipt counts, argument
bounds, sequential held/waited time, and budgets are checked. Valid terminal
outcomes include `program_complete`, `death`, `time_limit`, and `action_limit`;
death requires persisted zero HP, and limit outcomes must exhaust the relevant
budget. Zero or negative net XP does not block publication. Partial inputs,
infrastructure errors, stale observations, model substitutions, or interrupted
recordings do. This gate does not publish files or change repository visibility.

The recorded `programSeconds` and `controllerSeconds` must match the frozen
scenario's active duration and controller envelope: 22/24 or 60/62 seconds.
Acknowledged holds and waits remain within the active budget; the total recorded
controller interval, including executor termination, remains within the separate
controller envelope. A time-limit outcome cannot precede the active deadline.
Clock-precision tolerance does not extend either budget. Both the original
result and controller `trialContext` must match the byte-verified scenario and
baseline fingerprints. Version 2 derives freshness and capture continuity from
actual observations, acknowledgments and recording artifacts; it does not require
invented timeline attestation fields.

## Measured capture bundle

Version 2 also requires `recording`, `capture`, `capture_ready`, `capture_clock`,
and `capture_terminal` artifact references. These are the exact bridge files
`recording.json`, `capture.json`, `capture-ready.json`, `capture-clock.json`, and
`capture-terminal.json`, copied privately by the runtime collector.
The recording receipt binds both video and capture SHA-256 values. The validator
recomputes all measured recording fields from the raw browser and server
receipts. A later visual review may change only `reviewed`; it cannot rewrite
capture measurements or the immutable controller result timeline.

`capture.json` records the run and renderer identities, browser wall start/end,
monotonic duration, first/last post-render frame wall times, rendered frame count,
maximum frame gap, hidden/error/relay-loss/interruption observations, a measured
clock sample, and the server-issued terminal token. The clock sample includes
client send/receive and server receive/send timestamps; its matching raw server
receipt must be present. `capture-ready.json` records when the server actually
received the first valid post-render frame acknowledgement.

The first-frame acknowledgement must precede API planning. Conservative bounds
from the measured clock-offset interval must cover both planning and the whole
program, with uncertainty at most 250 ms. The terminal token must have been
issued after the immutable controller result ended; capture may continue for a
tail of at most two seconds. This accommodates the actual final-frame/upload
flow without extending controller execution time. Hidden/error/relay-loss flags,
frame gaps above one second, or wall/monotonic drift above 100 ms invalidate the
recording. The independent ffprobe duration must still match the saved measured
duration within 100 ms. These checks establish measured capture continuity and
coverage; they do not replace review of the exact video and actual model overlay.
