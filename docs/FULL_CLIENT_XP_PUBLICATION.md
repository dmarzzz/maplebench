# Native XP-window publication adapter

`full_client_xp_publication.py` prepares a public-safe evidence projection for
`full-client-xp-windows-v1` trials. Its own adapter identity is
`full-client-native-xp-publication-v1`. It is a separate, unranked **300-second
pilot** with twenty fixed, complete 15-second windows. It does not implement the
30-minute research task, a task-suite aggregate, a site package, or deployment.
Existing legacy and adaptive net-XP publishers are unchanged.

## Calling the bounded adapter

Call `verify_attempt(attempt_directory, context)` for strict verification, or
`project_attempt(attempt_directory, context)` to produce an explicit unknown row
when saved evidence is missing or inconsistent. Neither function executes game
or model actions or copies files. The sole subprocess is the existing read-only
video probe: one decoder thread, a 30-second timeout, bounded output and resource
limits. Video hashing is streamed with a 96 MiB cap and a 335-second duration cap.

The caller supplies a context from its already accepted finite plan and final
attempt receipt. Do not generate these pins from untrusted candidate output and
then represent them as independent approval. Exact context fields are:

| Field | Required value or origin |
| --- | --- |
| `schema_version` | Integer `1` |
| `protocol` | `full-client-native-xp-publication-v1` |
| `run_id` | Planned 32-character hexadecimal attempt ID |
| `request` | Exact frozen schema-3 `full-client-xp-windows-v1` trial request |
| `adapter_fingerprint` | Accepted fixture's adapter fingerprint |
| `runtime_manifest_sha256` | Accepted fixture's native runtime manifest hash |
| `scorer_sha256` | Accepted runner dependency hash of `full_client_xp_windows.py` |
| `journal` | Exact final reference `{path: "journal.json", sha256: ...}` |
| `backend` | Exact final reference `{path: "backend-state.json", sha256: ...}` |

The artifact directory must be canonical and absolute; artifact references remain
relative to it. Malformed caller context is an error. An otherwise valid context
with absent, corrupt, mismatched, or unverified evidence returns `status: unknown`,
null peak/net/coverage fields, and an empty window list. Unknown is never zero.

## Evidence required for a verified row

The adapter checks the completed runner's request, exact model, confirmed usage,
verification event, ordinary logout, final clean backend, and idle cleanup receipt.
It rehashes and recomputes the full native window manifest, checks that its score
matches both the saved score and journal, and binds the initial native header to
the backend's startup receipt. Frozen baseline/scenario/runtime/scorer hashes,
experience table, class protocol, full-horizon policy, prompt, and trial budgets
must all agree.

Every adaptive response/program/input receipt is rechecked. If the frozen protocol
permits level progression, the adapter passes explicit native identity, initial
and final progression, ledger, committed save time, and control window to the
adaptive verifier. Client observations alone cannot authorize a level change.
The ordinary save and native ledger must reconcile across level-ups and signed
losses. A complete native save must cover the full deadline.

The original capture handshake, terminal receipt, post-render coverage, exact
model overlay, actual decoded video, and frozen upload/logout settlement policy
are also required. With no frozen `capture_duration_policy`, the original 100 ms
decoded-duration contract remains mandatory. An explicitly frozen
`post-render-frame-envelope-v1` policy instead uses the shared runtime/publication
verifier: schema-2 raw monotonic offsets, bounded first/last-frame gaps, bounded
wall drift, matching frame counts and decoded presentation endpoints. The policy
comes only from the verified adaptive scenario, not a publication option or a
recording that happens to fail the old tolerance. Historical Terra evidence lacks
these frozen schema-2 receipts and remains ineligible. The projection records the
selected policy and capture-verifier source hash in its provenance.

## Public metrics and provenance

- `authoritative_peak_xp_per_minute` is the maximum normalized rate of the twenty
  complete, fixed, half-open windows aligned to control start, with a zero floor.
- Each window retains signed `net_xp`, normalized XP/min, elapsed start/end, and
  `best_so_far`. Normalization removes only the declared server XP and simulation
  speed multipliers, which are included as numerator/denominator pairs.
- `control_window_net_xp` includes changes from control start up to, but excluding,
  its deadline. `persisted_net_xp` includes all reconciled changes through ordinary
  save, including deadline and logout-tail events. These can differ and are never
  substituted for the peak metric.
- Per-cycle usage, actions, model attribution, class profile and passive-hold
  timing use the existing safe adaptive projection. Its old nested pilot peak
  field remains null; only the separately identified native metric carries a peak.
- Provenance contains source identity, scorer/adapter/native-JAR/table hashes,
  exact artifact hashes, and the trusted-native-runtime/collector boundary. It
  contains no filesystem paths, account/character IDs, prompts, code, native log
  text, credentials, or database content. Recording metadata provides a hash and
  first-input cue; visual review is explicitly not assessed by this adapter.

Calls without acceptance arguments retain `ranked: false`,
`publication_eligible: false`, and
`new_native_runtime_and_baseline_acceptance_required`. Their output is unchanged.
No historical run is upgraded to this protocol.

## Optional native acceptance and recording review

Both functions accept keyword-only `native_acceptance=None` and
`recording_review=None`. The read-only library `full_client_native_xp_gate.py`
checks the separate native evidence. It never starts a service, reads a live
database, changes a JAR, dispatches a model, or deploys a site. Its only subprocess
is the existing bounded video probe. Neither a boolean acceptance flag nor a
synthetic test result can replace the original evidence contract.

The native context has exactly these fields:

| Field | Required binding |
| --- | --- |
| `schema_version` | Integer `1` |
| `protocol` | `native-xp-runtime-acceptance-v1` |
| `root` | Canonical absolute native artifact directory, separate from the API attempt directory |
| `run_id` | Original native run ID, distinct from the model attempt ID |
| `complete`, `backend` | Hash-pinned original native executor completion and final backend artifacts |
| `runtime_manifest` | Hash-pinned native runtime manifest; its hash must exactly match the model fixture's accepted runtime manifest |
| `visual_review` | Hash-pinned native visual-review artifact |

Each reference is `{path, sha256}` relative to the native root. Pins must come
from an independently reviewed operator record; generating new hashes from
untrusted candidate output is not independent approval. The manifest binds the
candidate server JAR and full frozen source inventory. No current remote host
path or substitute local JAR is consulted.

The native executor must have completed successfully with no model/API identity,
one original native submission, ordinary logout, no unresolved operation,
confirmed cleanup, and an actual restored offline baseline. The gate recomputes
`full_client_native_xp_acceptance.verify_bundle`, including its original finite
native program, 300-second passive coverage, twenty windows, native ledger and
ordinary save. At least one positive native transaction in that window is
required. A complete zero-transaction native check remains insufficient even
when its cleanup succeeded. The original short recording is rehashed, decoded
and checked with the shared capture verifier and frozen native policy, retaining
the 45-second bound. It is never described as a five-minute model recording.

The class profile, baseline SQL hash, restored character/keymap, normalization,
experience table, source inventory and server JAR must agree with the model
fixture. Native evidence stays separately identified and never supplies a model
score. Passing it adds a public hash-only acceptance summary and changes the
blocker to `model_recording_visual_review_required`; the model recording's
`visual_review` remains `not_assessed`.

Each visual review has exactly `schema_version: 1`, `protocol`, `binding`,
`reviewed_at_ms`, and `observations`. Observations are explicit intervals
`{start_ms, end_ms}` within the original decoded recording. They are operator
attestations about that exact media, not automatically inferred pixel evidence
or cryptographic proof of human review.

The native review protocol is `native-xp-runtime-visual-review-v1`. Its binding
contains `run_id`, `model: null`, and the complete/backend/runtime-manifest/
native-manifest/video/capture/recording hashes plus `class_profile_sha256`.
Use the field names implemented by `verify_native`; all are required and no
extensions are accepted. Required observations are `vertical_jump`,
`monster_contact`, `native_class_hud`, and `script_overlay`. Its review timestamp
must follow the independently measured restored baseline.

`recording_review` is a separate `{path, sha256}` reference relative to the API
attempt directory. Its protocol is `native-xp-model-visual-review-v1`. Its binding
contains the API `run_id` and exact `model`, `video_sha256`, `xp_manifest_sha256`,
`capture_sha256`, `recording_sha256`, `runtime_manifest_sha256`,
`projection_provenance_sha256` (the canonical original projection's provenance),
and `native_acceptance_sha256` (the accepted native gate's derived digest).
Required observations are `exact_model_overlay`, `recording_matches_actions_and_waits`, and
`native_hud`. The review timestamp must follow the conservative recorded end
bound on the server clock. Waiting, observation-only, no-op and negative-XP model
outcomes remain valid when their evidence and recording agree; this review does
not require constant input or a positive model score. Native review cannot
substitute for model review.

Only both passing gates set `publication_eligible: true` and clear the blocker.
`ranked` remains false, the protocol remains the 300-second pilot, and deployment
still requires the caller's separate authorization and publication workflow.
`verify_attempt` raises for invalid supplied acceptance/review. `project_attempt`
keeps independently verified signed XP/window metrics and blocks publication
with `native_runtime_acceptance_unverified` or
`model_recording_visual_review_unverified`. Missing model evidence still produces
the existing unknown row. Unknown or rejected evidence never becomes a fake zero.

## Focused validation

Synthetic tests cover complete zero windows, negative total XP, signed window
losses, deadline cutoff, multiplier normalization, level progression, exact
attribution and usage, all-cycle evidence, native save/header corruption,
missing coverage, frozen pins, capture overlays, the unchanged duration limit,
failed uploads, decoder errors, file substitution, and private-data exclusion.
Synthetic recording fixtures stub decoding explicitly; they are not real clips
or native runtime acceptance results.
Gate tests also recompute native ledgers, exercise the real shared capture and
encoded-frame validators with an explicitly mocked decoder, require separate
artifact-bound reviews, reject changed runtime/class/baseline and file swaps,
preserve negative model XP on gate failure, and keep default calls unchanged.
