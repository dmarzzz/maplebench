# Native XP scoring delivery

The existing `full-client-xp-windows-v1` schema-3 trial now connects to the
immutable cohort publisher and catalog. This is a separate scoring protocol;
historical net-XP recordings are never upgraded. The initial qualification is
300 seconds, with twenty fixed 15-second windows, and remains unranked.

The publisher recomputes the original ledger, ordinary save, level transitions,
all model cycles and original capture. A maximum window rate is never inferred
from initial/final XP. Signed losses remain signed; an event at the exact control
deadline is excluded from the control metric and retained in persisted net XP.
Only the peak has a zero floor. The research matrix uses the peak for this
protocol and keeps failed, unknown, unstarted and valid-zero denominators.

## Explicit publication input

Call `full_client_publication.prepare_package` with the accepted four-entry
schema-3 plan, its hash, frozen adaptive scenario, public research profile and
`xp_evidence`. The profile's `protocol_id` is `full-client-xp-windows-v1`; the
human-facing recipe label is Training v2 qualification. Both the original full
horizon and the separately validated final-program-slot policy are supported.
The policy, prompt, class and budget hashes still distinguish fixtures.

`xp_evidence` has exactly these fields:

```json
{
  "schema_version": 1,
  "protocol": "native-xp-cohort-evidence-v1",
  "scorer_sha256": "<accepted scorer source hash>",
  "native_acceptance": "<original native acceptance context or null>",
  "attempts": {
    "<planned attempt id>": {
      "journal": {"path": "journal.json", "sha256": "<final pinned hash>"},
      "backend": {"path": "backend-state.json", "sha256": "<final pinned hash>"},
      "recording_review": "<exact model video review reference or null>"
    }
  }
}
```

Angle-bracket values above describe required operator inputs and are not an
executable configuration. Native acceptance and model review use the full
artifact-bound contracts in `FULL_CLIENT_XP_PUBLICATION.md`. The CLI accepts
`--xp-evidence` only together with `--xp-evidence-sha256`. No context is inferred
from a candidate's self-reported approval. Unlisted terminal attempts wait for
operator pins; unrelated IDs are rejected.

A native gate failure does not erase the private verifier's valid raw metrics.
It keeps public scores and media pending. Both independent native acceptance
and the exact model recording review must pass before a public row carries
`publication_eligible: true`. This means evidence is eligible for this unranked
publication, not that it is ranked or that deployment is authorized. Only then
is the original video copied unchanged. Its existing first-input playback cue
is preserved. Four accepted recordings remain necessary for archive retirement.

The public `native_xp` object contains twenty signed windows, normalization,
initial/final levels, control and persisted XP, peak rate and hash-only review
provenance. No SQL, paths, account identifiers, prompts or raw private receipts
are copied. Existing immutable package claims and deployment receipts apply.
The site payload size limit remains enforced; the publisher does not trim,
transcode or silently omit evidence to fit it.

## Build prerequisites and finite native acceptance

1. Build a new immutable production JAR from Cosmic commit
   `b01cf27833f568cde52a0a70a38532474eedd4d9`, the pinned overlay and
   `bootstrap-upstreams.mjs` instrumentation. Verify idempotent patch application.
   A JDK 21 build must contain the actual Character transaction wrappers,
   ordinary SQL save-commit hook and Server startup initialization, as well as
   both `MapleBenchXpLedger` and `MapleBenchPersistence`. Merely finding those
   two class files in an old JAR is insufficient.
2. Run the two journal test classes and the production build under the shared
   serial lock, after checking memory, with explicit heap/fork/CPU/memory and
   time caps. Record the exact source, instrumented Character/Server, native
   threshold table, JAR and test-receipt hashes. Freeze new runtime inventory;
   do not reuse a prior runtime hash or relabel an old result.
3. For each intended class/toolkit, freeze ordinary equipment, skill levels,
   ammunition, map, normalization and baseline SQL. Native and model profiles
   must match exactly. Hold the normal operation gate, world, queue and runner
   locks; require all prior claims and native attempts clean and terminal.
   Restore only with Cosmic stopped. Use a new native ID and a durable intent
   before any action; an uncertain submission permits cleanup only.
4. Start the owned JAR once. Before login, require exactly one fresh native XP
   header matching baseline, table, run/account/character/server identities and
   normalization, plus the real save/ledger initialization markers. Then use
   ordinary login and the separately frozen bounded native recipe. Require
   visible jump, monster contact, correct class/HUD and a real positive XP
   transaction. A zero-XP recipe is honest evidence but cannot qualify the XP
   hook; do not manufacture an award or replay it under the same ID.
5. Keep the player connected for the complete 300-second owned ledger window,
   collecting fresh passive coverage every second. The short native recording
   retains its own capture limit; it is never described as five minutes of
   model play. Collect original program/capture receipts, ordinary logout/save,
   independent persisted state and twenty reconciled windows. Restore the exact
   baseline while stopped and verify the actual offline snapshot before clean
   closeout. Failed capture/save/coverage remains unaccepted, not zero.
6. Pin an independent review of that exact native video and restored evidence.
   Then run a newly admitted, bounded schema-3 API qualification using the same
   source/JAR/class fixture, followed by review of its exact API video. No native
   script result supplies a model score. Only this complete chain permits the
   public package above.

Before a research comparison, separately version and exercise an ordinary
near-level-threshold fixture and a real death-loss fixture. Verify one settled
outer XP event across the level transition, signed penalty/zero clamp, normal
save and baseline restore. These are additional explicitly planned native
acceptance cases, not score-tuned replacements or administrative XP grants.
Recorded software tests cover boundary arithmetic and corruption; they do not
substitute for these real JAR acceptance cases.

## Verification boundary

The package tests use a synthetic native ledger and real ledger/save/cycle and
hash verification, with video decoding and the separate visual-review boundary
explicitly mocked. Native gate tests independently verify the real evidence
structure. These tests prove source behavior only. This change neither builds
nor activates a JAR, changes a baseline, runs a model, or deploys a site.

## Explicit thirty-minute successor

An 1800-second model fixture must declare `horizon_seconds: 1800` in its finite
experiment fixture and schema-3 request. Its validated adaptive scenario must
select `final-program-slot-1800-v1`, the separate
`post-render-encoded-frame-1800-v1` capture policy, and a native window contract
with `wall_seconds: 1800`. All three durations must agree. Increasing only a
budget or stretching a saved timeline cannot opt in. The original 300-second
contracts, cap values and manifests keep their old shape.

The successor records 120 complete signed windows. The native ledger and
ordinary logout must cover the whole interval. Publication probes the original
video with the exact long policy: at most 1,835 seconds and 600 MiB per clip.
The immutable package additionally declares `horizon_seconds: 1800`; catalog
validation binds every accepted row to it. Timing and capture limits are never
chosen because an existing recording failed the short contract.

The deployment driver accepts a larger video only at the exact file path owned
by a verified native XP package declaring that long horizon. A catalog containing
long cohorts adds `cohort_manifests` to its private payload inventory: the exact
public package manifests, without private paths or native artifacts. The driver
rechecks each content digest, complete mounted file mapping and public cohort
semantics. Each recording inherits its own cohort's limit, so a new short primary
can retain an earlier long cohort. Unbound supplemental files retain the short
limit; the primary cannot grant its limit to other recordings. Inventories without
the extension keep their existing shape and primary binding. The inventory is
never uploaded as part of the public site. Total public payload remains
512 MiB, checked before upload. Exceeding it returns an explicit capacity error;
no partial copy, trimming, model replay or silent result omission is used to fit
sixteen long videos. A storage/deployment policy decision may therefore still
be needed before publishing a complete long matrix.

Native JAR qualification remains a separate 300-second zero-API ledger check.
The exact `scripted-native-toolkit-acceptance-v1` contract permits a 60-second
script and 75-second native recording; historical native contracts retain
30/45-second bounds. The executor derives the control/idle deadline from the
validated contract, preserves the five-second start allowance, and requires
the short recording saved by that contract's deadline. It never extends the
ledger horizon or its outer cleanup reserve.

Toolkit qualification must bind the exact canonical toolkit hash in both native
and model evidence. The native visual review also includes one `skill_<slot>`
interval for every declared skill, each attesting its actual native effect.
Successful input acknowledgements, an overall positive XP event, or an older
four-slot review cannot certify an expanded toolkit. Missing skill evidence
keeps publication ineligible. Ordinary resource consumption and restored
baseline checks remain independent required runtime evidence.
