# v1 release status

Snapshot: **2026-09-20 UTC**, candidate branch `codex/v1-cross-provider-release`.
No scored attempt has yet run for this expanded candidate.
[V1_COHORT.md](V1_COHORT.md) is the current release scope.

## Established inputs

- The original private runtime archive was recovered and its historical SHA-256
  independently verified. Assets remain private.
- The required amd64 Chrome 152.0.7977.82 package is available from its official
  distributor; a private receipt records its exact hash and size.
- Both provider credentials authenticated, and all four selected model IDs are
  available. Credentials are private runtime files.
- A fresh, bounded worker uses the six-unit runtime toolkit, an enrolled operation
  gate, the expanded baseline and separately pinned client/server binaries.
- The candidate at `181a61e` passed Linux CI, including the native runner's real
  process-ownership test and the full-history secret scan. Later changes require
  their own focused checks.

## Implemented, awaiting live release acceptance

- Native OpenAI and Anthropic generation, exact request/response attribution and
  conservative error/token accounting.
- Hash-bound Hero knowledge, 17 invocable controls, exact learned-skill/keymap
  snapshots and new native toolkit qualification.
- Sixteen-attempt publication, per-model spread, retained denominators and
  consecutive operational groups.
- Recorded held-key HUD and media-clock model/input replay timeline.
- Light MapleStory-inspired results and replay UI, checked at desktop and narrow
  widths; development preview data is explicitly unscored.

## Native qualification findings

Six unsuccessful qualification attempts are retained privately. The first stopped
before gameplay because the launcher supplied the wrong process ancestry; the
corrected launcher passed a real Linux ownership check. The next five reached the
game, recorded the client, logged out and restored the baseline:

- The second attempt walked off the spawn platform before testing attacks.
- The third demonstrated Brandish damage and combo growth, but its target window
  skipped Rush, Coma and Panic.
- The fourth activated Coma and Panic and consumed their resources, but neither
  produced linked damage. It then stopped approaching distant monsters, leaving
  Rush untested. Those missing effects are qualification failures.
- The fifth, using the corrected client, demonstrated two Brandish hits and combo
  growth. A transient vertical displacement exceeded the recipe's floor guard;
  it immediately skipped all remaining casts before the character landed again.
  It did not exercise the corrected finishers or Rush.
- The sixth never left the starting ledge: two fixed-duration movement inputs
  produced less displacement than the recipe assumed. It demonstrated six buffs
  but no attacks. Descent must be confirmed through fresh observations.

Six buff effects and Brandish damage have been observed. Core-ten qualification
has not passed. Investigation found that the equipped sword's level-120
afterimage bucket is absent from the pinned client data. The ordinary-attack
fallback used by both finishers replaces their range with an empty rectangle.
The client lookup now falls back to a valid authored range for the same weapon
family and stance, with compiled regression coverage. A separate source-route
check also found and corrected Shout's missing attack classification. All 17
declared routes passed against the selected client source. These source checks
do not replace live effect evidence. The qualification recipe now adds bounded
recovery from transient knockback and requires stable landing observations before
resuming input. Initial descent now uses fresh position feedback with a bounded
number of movement steps. Its live effect requirements remain unchanged.
No qualification
attempt made a model API call or produced a model score. Original recordings,
failure receipts and restoration evidence remain separate from scored results.

## Remaining acceptance

1. Verify the corrected recipe under a new frozen live attempt.
2. Verify all 17 bindings and 25 learned rows, qualify the core ten effects,
   inspect the original recording and confirm exact restoration.
3. Freeze actual source/runtime/baseline/provider settings and declare 16 attempts.
4. Run and retain every attempt, verify three consecutive clean groups, and
   recheck original evidence and recordings independently.
5. Publish the reviewed public projection, methodology and limitations; verify
   deployed bytes and clean up the worker after a verified private backup.

Hostnames, account metadata, credentials and operator-specific run paths belong
in private operational records. Historical deployment receipts in the companion
repository describe prior candidates, not acceptance of this release.
