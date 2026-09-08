
## Retain earlier pilot cohorts while a replacement is incomplete

Current cohorts support Hero, Bowmaster, Ice/Lightning Arch Mage and Night Lord,
with up to four explicitly selected class packages. This enables a sixteen-result
matrix; listing a class does not establish its native qualification or scores.
The existing total file, byte and per-recording limits still apply.

Request schema 2 adds `previous_cohorts`, a list of at most three explicit
`{package, content_sha256}` selections. `cohorts` still contains at most one active
cohort per class and all active cohorts must share dashboard assets. Previous
packages may have different frozen fixtures and assets; each passes the existing
four-model package verifier independently. Their original nested package bytes
and mounts remain unchanged. Mount and attempt collisions fail closed.

The root catalog exposes `catalog.schema_version: 2` and
`catalog.previous_cohorts`. Each previous entry has the usual cohort metadata plus
`scope: "previous_cohort"` and `label: "Previous pilot cohort"`. All four historical
attempts remain present, including failures and unstarted entries. Root comparison
IDs are namespaced by the previous plan so repeated identical fixtures cannot pool
scores across cohorts. The active research matrix and active planned/verified
counts exclude historical rows. The UI must display a separate history callout
using this metadata. If the active cohort has no video yet, a verified previous
video may remain featured.

Once the **primary cohort has four verified videos and one matching comparison
group**, and every retained historical class has a complete active replacement,
both previous cohorts and the legacy archive are omitted from the new
public payload. Original private packages remain unchanged. No retirement occurs
merely because four scores exist, a previous cohort is complete, or a model failed.
All output still passes the existing 100-file/512MiB allowlist and payload checks.
A complete Bowmaster group cannot retire an incomplete Hero group's previous
recordings. The finite publisher carries the operator notes through every update
and allows three retained current classes alongside the class being published.

## Immutable operator cohort limitations

Either request schema optionally accepts `annotations`, at most six objects with
exactly `plan_sha256` and `text`. Each plan must identify an active or retained
previous cohort included in this catalog. Notes targeting a retired cohort are
rejected. A plan and note text may appear only once. Omission or an empty list
preserves the existing catalog digest and bytes.

Text is stripped plain prose, 1–400 characters. Markup, control characters,
links, email/IP address shapes, absolute paths, credential assignments, and extra
fields are rejected. This validation does not replace the operator's review for
personal information. Ampersands and quotes are escaped for HTML. The composer
derives the affected cohort link from the verified package; callers cannot
supply a destination.

Notes appear directly below the root page header under “Cohort limitations,”
linked to the affected cohort. They are included in `catalog.annotations` in
root results and in the content-derived catalog manifest. The changed root HTML
and results remain hash-bound by the deployment inventory. All original nested
cohort files, recordings, results, grouping and retirement rules remain intact.
Direct links to original cohort pages preserve their original evidence; share
the root catalog URL when the operator caveat must be visible.
