# Publishing a four-model cohort

`scripts/full_client_publication.py` prepares a static site from one exact,
SHA-256-pinned four-model plan. It never calls a model, runs a trial, changes the
database, starts a browser, or invokes Vercel. The deployer remains separate from
the experiment runner, so retrying publication cannot replay gameplay.

Every planned model has a row from the first snapshot. Missing attempts say
**Not started**; failures and uncertain API outcomes stay visible. Completed
scores are recomputed by the existing receipt projector. Zero and negative XP,
and programs that execute no inputs, remain valid displayed outcomes. A missing
or corrupt recording does not erase a verified score or delay another model's
recording. A request or runtime that does not match the pinned plan cannot become
a cohort score.

Only the existing dashboard assets, projected results, a recording manifest,
Vercel's static-site configuration, and the selected verified videos enter the
public directory. Original video bytes are preserved, including their verified
first-input playback cues. Private journals, credentials, host paths, and older
recordings are never copied. Scores remain unranked: frozen inputs do not prove
identical live monster scenes.

## Prepare after each new result

Run the preparation command with absolute private paths:

```sh
python3 scripts/full_client_publication.py prepare \
  --plan /private/group/experiment-plan.json \
  --plan-sha256 PLAN_SHA256 \
  --attempt-root /private/attempts \
  --output-root /private/publication-packages
```

The returned `site` directory is the complete public payload. Its parent is
private publication state; never deploy that parent or the input directories.
The package is named by a digest of its exact file inventory and cohort identity.
Preparing unchanged evidence reuses the same package after verifying its bytes.
New evidence creates a new package and leaves every previous package and all
private evidence unchanged. Unexpected files, symlinks, or corrupted package
bytes refuse reuse.

A progress package targets `/cohorts/<plan-digest-prefix>/`. Mount its `site`
contents at that path in the existing deployment, retaining the existing public
archive. Relative recording URLs work at either that subpage or the final root.
The root deployer can run this preparation after each newly completed trial and
publish each new digest as it appears; preparation itself does not schedule or
perform an external deployment.

After all four models have completed with rechecked persisted scores, exact model
attribution, matching frozen inputs and verified recording bytes, add
`--replace-archive`. That produces a distinct final package whose target is `/`.
It contains exactly the four selected outcomes and recordings. Earlier test
recordings are absent from the new public payload, while private originals remain
untouched. An incomplete cohort cannot authorize archive replacement. Publication
review labels are projected separately and are never promoted by this helper.

## Claim, deploy, verify, record

Before deploying a prepared package, claim its exact digest:

```sh
python3 scripts/full_client_publication.py claim \
  --package /private/publication-packages/CONTENT_SHA256 \
  --content-sha256 CONTENT_SHA256
```

Only the first successful claim returns `deployment_allowed: true`. It creates a
durable intent before the external action. A second claim reports
`pending_reconciliation` and refuses another submission. If a Vercel reply is
lost, inspect Vercel for the deployment associated with this content digest;
do not automatically deploy it again. Use the digest as Vercel deployment metadata
so the root deployer can identify the result.

The root deployer mounts or replaces the public payload as indicated, deploys it,
and checks anonymous public access and every file's byte count/hash against
`package-manifest.json`. Verify playback and video byte ranges as part of that
external check. Only then record the returned deployment ID, final public URL,
and the explicitly verified content digest:

```sh
python3 scripts/full_client_publication.py record-deployment \
  --package /private/publication-packages/CONTENT_SHA256 \
  --content-sha256 CONTENT_SHA256 \
  --deployment-id dpl_RETURNED_DEPLOYMENT_ID \
  --url https://PROJECT.vercel.app/cohorts/PLAN_DIGEST_PREFIX/ \
  --verified-content-sha256 CONTENT_SHA256
```

Use the root URL for a final replacement package. This receipt records an
operator-supplied public-content check; the helper does not claim to have contacted
Vercel or verified remote bytes itself. Repeating the exact completion is
idempotent. A conflicting deployment receipt is refused, and an already published
package never grants another deployment claim.

The bounded synthetic suite is `test/test_full_client_publication.py`. It exercises
progress before all models finish, zero/negative/no-op results, failure and unknown
rows, plan mismatches, corrupt/symlink videos, package allowlisting, unchanged-content
reuse, uncertain deployment claims, and conflicting publication receipts.
