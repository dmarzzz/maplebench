# Public model and class catalog

`scripts/full_client_catalog.py` composes one to three **already public** adaptive
cohort packages into a static root dashboard. Every source cohort must contain
exactly Astra, Sol, Terra and Luna, including planned, failed and unknown attempts.
Hero, Bowmaster and Ice/Lightning remain separate fixture columns. Signed saved
XP is retained; no native scorer runs and no peak score is inferred.

Prepare each source with `full_client_publication.prepare_package(...,
replace_archive=False)`, including complete cohorts. The immutable package stays
at `/cohorts/<first-16-plan-hash>/`; the composer copies every file byte for byte.
The existing Vercel driver's primary-cohort mount check remains applicable. Root
assets and `results.json` show the combined matrix, latest verified recording,
cohort links and every planned model. Open catalog pages refetch saved results
every ten seconds, so a subsequent deployment becomes visible without a reload.
This does not turn the static site into live game control.

## Pinned input

Supply a private JSON request with exactly:

```json
{
  "schema_version": 1,
  "cohorts": [
    {"package": "/absolute/private/public-package-directory", "content_sha256": "<64 lowercase hex characters>"}
  ],
  "primary_content_sha256": "<content hash of the newly updated cohort>",
  "archive": null
}
```

The expected package hashes must come from the accepted public publisher's output.
They are a trust input, not values to derive from arbitrary downloaded packages.
The composer verifies their complete content, public schema, four-model identity,
fixture/profile separation, recording manifest/link bindings and public summary.
Source cohorts must use identical dashboard asset versions. Root assets come from
the reviewed local source; nested packages remain unchanged. Unknown code-shaped
JSON extensions, private receipt fields, malformed hashes, symlinks, missing
models and mixed asset/schema versions fail closed.

While the public test archive still exists, replace `archive: null` with:

```json
{
  "site": "/absolute/private/existing-public-site",
  "inventory": "/absolute/private/public-file-inventory.json",
  "inventory_sha256": "<64 lowercase hex characters>"
}
```

The explicitly pinned inventory must cover every existing public file, including
recordings and optional `latest/` pages. It must contain no private runtime inputs
or earlier nested adaptive cohorts. Until one source cohort has all four verified
recordings, the composed site retains those archive rows, videos and `latest/`
files. Once that condition holds, the composed site omits the legacy archive.
Original packages, evidence and recordings are never modified or deleted. A
missing or corrupt fourth clip keeps the archive even when all four scores exist.
After archive retirement, future requests may use `archive: null`.

Run the local composer with the request file's actual SHA-256:

```sh
python3 scripts/full_client_catalog.py --request /absolute/private/catalog-request.json \
  --request-sha256 "$REQUEST_SHA256" --output-root /absolute/private/catalog-outputs
```

It returns an immutable catalog directory, `site`, `inventory`,
`inventory_sha256`, `primary_package` and `primary_content_sha256`. The inventory
and catalog manifest live outside `site`; neither contains credentials. The
entire planned payload is bounded before copying: at most 100 files and 512 MiB,
with the existing 96 MiB per-adaptive-recording limit. Large files are copied and
hashed in bounded chunks. There is no Blob provisioning or hosting change.

A separate authorized publisher passes those returned fields to the existing
Vercel driver. Choose the newly updated cohort as `primary_content_sha256` so the
existing no-replay publication claim belongs to this update. A repeated identical
composition is idempotent; this script never deploys, claims a deployment, calls a
model, restores a baseline, or starts a service. Native receipt verification stays
with the producer; the catalog rechecks pinned public artifacts and does not claim
to authenticate a runtime host from public JSON alone.

## Verification

The focused catalog tests build public packages through the actual synthetic
native/cycle publication fixtures, then exercise three-class matrices, each-run
updates, negative and zero XP, failures and unknowns, exact nested-byte/driver
binding, archive retirement, hash/summary/link tampering, payload limits and the
actual JavaScript refresh/link functions. They do not establish live API success.
