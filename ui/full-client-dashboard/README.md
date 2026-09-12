# Public research dashboard

The public catalog uses the RuneBench-inspired MapleBench design: a quiet white
page, four equal recording previews, class selection, an architecture explorer,
and inspectable results. The read-only dashboard also retains the operator
receipt view and complete attempt history.

Previews take one recorded attempt per distinct requested/returned model from a
single frozen group. Missing recordings remain explicit empty slots. Neither XP
nor completion status is used to cherry-pick another group. Zero, negative and
unknown scores stay distinct. Playback seeks only to a validated recording cue;
total model latency is never substituted for a first-input timestamp. Refreshing
results preserves the selected player's position and playback state.

Adaptive runs display elapsed wall time separately from model waits and
observation-only intervals. Each selected run exposes the fixture's available
skills, acknowledged input evidence, model cycles and authoritative XP windows
when their existing verification gates pass. Historical pilots keep their
original protocols and scores.

The publisher distributes three self-contained files: `index.html`, `style.css`
and `dashboard.js`. Manrope is embedded in the stylesheet with its full SIL Open
Font License, also preserved in `OFL-Manrope.txt`. Original decorative artwork is
embedded in the HTML; see `ARTWORK.md` for provenance. No runtime game assets or
private experiment evidence are bundled in the UI. Each UI file is bounded by the
same 4 MiB ceiling used for non-video package verification.

`full_client_presentation.refresh` creates a new immutable UI package while
retaining every result and recording byte. The catalog's `cohort-limitations`
comment places operator notes near the results. Older templates retain their
header fallback. Existing cohort URLs remain stable.
