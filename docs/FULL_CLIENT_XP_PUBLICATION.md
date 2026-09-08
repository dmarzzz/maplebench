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
are also required. This branch retains its original 100 ms decoded-duration
contract. It cannot retroactively accept historical Terra capture failures or
silently opt into a later capture policy. Integrating a newer capture contract
requires its explicitly frozen verifier; this adapter does not invent one.

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

All rows retain `ranked: false`, `publication_eligible: false`, and
`new_native_runtime_and_baseline_acceptance_required`. A successful projection
checks saved evidence; it does **not** prove that the new native JAR and baseline
have passed real acceptance, authorize site publication, or authenticate a
malicious collector. Those remain independent requirements. No historical run is
upgraded to this protocol.

## Focused validation

Synthetic tests cover complete zero windows, negative total XP, signed window
losses, deadline cutoff, multiplier normalization, level progression, exact
attribution and usage, all-cycle evidence, native save/header corruption,
missing coverage, frozen pins, capture overlays, the unchanged duration limit,
failed uploads, decoder errors, file substitution, and private-data exclusion.
Synthetic recording fixtures stub decoding explicitly; they are not real clips
or native runtime acceptance results.
