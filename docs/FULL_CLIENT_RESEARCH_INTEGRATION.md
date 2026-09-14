# Isolated research/capture integration review

This candidate combines research/publication commit
`35cad2e7cf6348dde5bd8587120c9330a4d0db98` (research base `8bd2bf7`) with cloud
release `33bf16a5fcf0e1f492207696dc1bd999a01c3eb0`. The merge is
`8c5faa7` on the isolated `codex/research-capture-integration` branch. It does not
activate a release, deploy a JAR, alter databases, launch APIs, or replace either
source branch. The root task owns any later integration and native acceptance.

## Merge and contract review

| Component | Integration result |
| --- | --- |
| Adaptive validation | One textual conflict. Preserve `NATIVE_PROGRESSION_POLICY` and `CAPTURE_COHORT_RECIPE`; accept both independently validated optional fields `progression_policy` and `capture_duration_policy` alongside `horizon_policy`. Neither is implicitly enabled. |
| Native XP scorer, Java ledger and persistence overlay | Retain the research implementation unchanged. Native table/identity/transaction/save verification and explicit schema-3 admission remain required. |
| Runtime launch and collection | Automatic merge preserves seven XP environment settings, fresh native-header admission, ledger collection and manifest scoring, while retaining release33's shared capture-duration verifier. |
| Runtime dependencies and cleanup | Preserve release33's pinned `full_client_native.py` dependency and ordinary waiting-state verification after cleanup. Do not replace the final clean predicate with a saved or assumed result. |
| Status reconciliation | Preserve release33's original separately pinned status-only operator unchanged. This integration neither executes it nor modifies old recovery journals. |
| Native scripted acceptance | Preserve the separate zero-model, bounded native control protocol. It cannot be projected as an XP-window model trial. |
| XP publication | Use the same `verify_video_duration` implementation as runtime and adaptive publication. Policy comes only from the already verified frozen adaptive scenario. |

There is no global relaxation of duration tolerance. An absent capture policy
retains the original 100 ms rule and schema-1 capture. Explicit
`post-render-frame-envelope-v1` requires matching schema-2 monotonic offsets,
frame counts, bounded endpoint gaps/drift, and decoded presentation endpoints.
The raw-capture verifier independently recomputes these fields before the shared
duration verifier accepts them. A recording cannot select its own policy.

The XP trial identity remains `full-client-xp-windows-v1`; the publication adapter
remains `full-client-native-xp-publication-v1`. A newly enabled capture policy
changes the frozen scenario/controller contract and therefore its hash. The
adapter now exposes both the selected capture policy and capture-verifier source
hash. Existing prompts remain byte-identical when only capture policy changes.
Actual research source/runtime pins must be frozen again before a future run.

## Focused checks and remaining boundary

The adapter tests now include explicit-policy native windows, combined level
progression/capture opt-ins, excessive decoded frames, impossible presentation
span/tail, altered monotonic endpoints, policy tampering, and refusal to infer a
policy from schema or video duration. They retain the historical 117.265 ms
legacy failure regression using synthetic data, not reconstructed historical
monotonic receipts.

Run the native XP, progression, runtime/admission, adaptive publication, capture,
scripted native acceptance, and status-only recovery tests together against this
exact candidate before adoption. Native JAR deployment/acceptance and fresh
synthetic baseline acceptance remain outstanding. Publication stays unranked and
ineligible under that explicit blocker; the integration does not prove a live
research run or a 30-minute task.
