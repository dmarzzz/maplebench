# Scripted environment-check showcase

`full_client_environment_checks` is a read-only library. It attaches exactly four
original active `scripted-native-productivity-v2` recordings—Hero, Bowmaster,
Ice/Lightning Arch Mage and Night Lord—to an already verified catalog. The
180-second program ceiling is distinct from each actual execution and video
duration. No controller, API request, deployment, retry or runtime mutation is
performed here.

The four cards occupy the illustrated overview only when all four validated rows
are present. They say **Scripted · no model · unranked**. Saved XP is recomputed
from ordinary saved snapshots and is separate from model scores. Zero, signed
losses and death remain visible. Input acknowledgements do not qualify all skills.
The original model attempts, comparisons, research matrix, cohort annotations,
short previews, nested cohort files and recordings remain unchanged.

## Explicit private inputs

Call `attach_checks(catalog, selections, output_root, qualify_clock=...,
probe_video=...)`. `catalog` is the existing verified catalog receipt. Each of the
four selections has exactly:

- `folder`: absolute private backup directory;
- `artifacts`: relative JSON artifact-map path and `artifacts_sha256`;
- `source_revision`: exact 40-character source revision, identical across the four;
- `runtime_manifest_sha256`: the measured manifest for that class run;
- `clock_verifier_sha256`: exact operator-reviewed clock-verifier source hash.

Every artifact-map value is a relative `path` plus its SHA-256. Original backup
subdirectories such as `acceptance/` and `maintenance/` are supported; internal
runtime references in the original receipts must retain their original bytes.
The exact required keys are `REQUIRED_ARTIFACTS` in the module:

- outer completion, executor completion and backend state;
- original canonical scenario, result and program;
- initial/final/restored DB snapshots, baseline snapshot, reset, save journal and
  native log;
- before-login/after-logout/after-restore finite inventory receipts;
- runtime manifest;
- raw capture, ready/clock/terminal capture receipts, recording, saved video
  probe, and original video;
- raw operational `clock` sidecar and bound `clock_qualification` envelope.

The maintenance identity is `native-productivity-development-v2`. Success must
be `native_productivity_closed_unscored` outside and
`native_productivity_collected_unscored` inside, with no inner failure. A clean
cleanup-only receipt is insufficient. Completion and artifact hashes bind the
ordinary save and exact restored baseline/inventory; a saved `accepted` boolean
cannot substitute for those artifacts.

The original backend must also bind `native_warmup` (requested 3000ms, after
ordinary login and before the captured run) and `native_settlement` (requested
2000ms, after the saved capture and before ordinary disconnect). Both carry
status observation counts, actual start/end times, zero new inputs and zero API
calls. The settlement receipt explicitly acknowledges that ordinary late
settlement can contribute to saved diagnostic XP. Actual pause durations are
reported; small millisecond rounding is tolerated and the original 720-second
lifecycle bound applies, without inventing a tight per-pause timeout. Cards say
that saved XP includes post-recording settlement, rather than attributing the
entire saved delta to actions visibly completed inside the clip.

The clock envelope has exactly `schema_version:1`, `run_id`, `native_protocol`,
`source_revision`, `runtime_manifest_sha256`, `capture_sha256`, `video_sha256`,
`clock_sha256`, `verifier_sha256`, and `qualification`. The last field must equal
the result of the supplied clock verifier on the exact sidecar and raw capture.
The sidecar's capture endpoints must equal the actual capture endpoints. The
qualified measurement requires at least 30 capture FPS, simulation/wall ratio
within one percent, less than one full 8ms pending step, and samples covering the
entire recording. Renderer strings and samples remain private.

`qualify_clock` is an explicit trusted operator transport to the pinned verifier,
not a way to supply a `qualified: true` shortcut. The operator must bind and
review the exact executable/source hash. The optional `probe_video` transport
has the same trust boundary as short-preview publication: it independently
decodes the exact video and accepts `maximum_ms=185000` plus the exact encoded
policy. Its result must equal the original saved probe. Default decoding uses
the existing bounded local Linux implementation. Neither callback grants runtime
or model authority.

## Immutable public attachment

Only sanitized `environment_checks` rows and entries in the recording manifest
are added. The only new public files are
`checks/<run-id>/recordings/<same-run-id>.webm`. No private receipt, SQL, renderer
string, account identity, source program or raw clock sample is copied.

The new publication package keeps the original cohort files unchanged and adds
`environment_checks_payload_sha256`, binding the entire exact deployment
inventory. If an existing preview payload binding is present, the new publication
identity binds both sidecars to the same new inventory; the old identity and its
publication intent remain untouched. The old intent is never reset or copied.
Existing 100-file, 96MiB per short video and 512MiB aggregate limits still apply.
The attachment fails closed on insufficient capacity or an existing native
selection. It does not alter or retire the original catalog.

## Validation boundary

Focused source tests use synthetic emitter-shaped save, inventory, capture and
clock receipts. Production SDK and encoded-ledger validation run; decoder and
clock transports are explicitly mocked. Tests include negative/zero saved XP,
failed cleanup, mismatched owners/pins, legacy program relabeling, modified video,
clock mismatch, first-input cues, four distinct classes, and coexistence with a
previously claimed short-preview package. These tests establish implementation
behavior, not live gameplay, real GPU timing, or successful skill effects.
