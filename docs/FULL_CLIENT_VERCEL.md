# Publish each verified success

`scripts/full_client_vercel.py` submits one explicit public payload to an existing
Vercel project, then checks the public bytes and records the deployment. It never
starts a trial or calls a model. Repeating the same command reconciles its original
submission; it cannot issue another deploy for the same package.

First prepare the cohort package on the machine holding the private evidence,
using [the publication adapter](FULL_CLIENT_PUBLICATION.md). For an adaptive
cohort, pass its pinned plan, scenario and public class/task profile:

```sh
python3 scripts/full_client_publication.py prepare \
  --plan /private/cohort/experiment-plan.json \
  --plan-sha256 PLAN_SHA256 \
  --attempt-root /private/attempts \
  --output-root /private/publication-packages \
  --adaptive-scenario /private/cohort/scenario.json \
  --research-profile /private/cohort/research-profile.json \
  --research-profile-sha256 PROFILE_SHA256
```

Run this after each completed attempt. All four planned outcomes remain visible,
including not-started, failed, uncertain and zero-action results. A bad recording
does not conceal an independently accepted persisted score. Add `--replace-archive`
only when the existing adapter accepts all four completed scores and recordings.

Transfer **only** `package-manifest.json` and `site/` into a private package
directory on the deployment machine, and retain the returned content SHA through
the trusted handoff. Verification on that machine needs no source-host journals,
database files, account configuration or absolute evidence paths. The source-host
adapter performs the evidence checks; this driver checks the transferred public
package against that trusted digest.

For a progress package, assemble a fresh complete payload from the explicitly
approved public archive, and mount this package's `site/` at its returned
`/cohorts/<plan-digest-prefix>/` path. Replace that cohort subdirectory with each
new package; retain the approved archive at `/`. For the accepted final replacement
package, the complete payload is just its `site/`. Do not copy a private parent or
an old deployment's `.vercel/` directory into the payload.

Pin a separate JSON inventory of the complete payload. Both this mapping form and
a `files` array of `{path, sha256, bytes}` objects are supported:

```json
{"files":{"index.html":{"sha256":"EXACT_SHA256","bytes":1234}}}
```

Every file must be listed with its measured hash and size, including files under
the cohort path. The driver checks the exact set, names and package mount; callers
cannot relabel gameplay IDs or alter cohort results. It permits only the existing
static assets, manifests and named WebM recordings. Limits are 100 files, 512 MiB
total, 96 MiB per recording and 4 MiB per other file. The existing package adapter
retains its stricter legacy recording cap. Unlisted files and symlinks are refused.

Use the existing local Vercel CLI login and hash-pin the existing
`.vercel/project.json`. The driver copies only its `projectId`, `orgId` and
`projectName` into a fresh isolated stage. It never creates a project, changes
authentication, supplies a token argument, or changes deployment protection.

```sh
python3 scripts/full_client_vercel.py \
  --package /private/publication-packages/CONTENT_SHA256 \
  --content-sha256 CONTENT_SHA256 \
  --payload /private/approved-public-payload \
  --payload-inventory /private/payload-inventory.json \
  --payload-inventory-sha256 INVENTORY_SHA256 \
  --project-link /private/existing-project/.vercel/project.json \
  --project-link-sha256 PROJECT_LINK_SHA256 \
  --public-origin https://PROJECT.vercel.app \
  --vercel-executable /absolute/path/to/vercel \
  --timeout-seconds 300
```

The timeout is finite, from 1 to 600 seconds. CLI execution and HTTP requests use
bounded deadlines, output and response sizes. The target is publication within
60 seconds after package validation when upload and build speed allow it; the
receipt records actual latency and whether that target was met. It does not
promise 60 seconds or omit upload/build delay. A socket read may take up to its
15-second request timeout to return after a deadline check.

Before its sole `vercel deploy --prod` process, the driver writes the existing
package claim and a durable `vercel-submission.json`. Deployment metadata binds
the content digest, complete-payload digest and a fresh publication ID. A missing
reply cannot grant another submission. The driver uses metadata-filtered
`vercel list` and `vercel inspect` to identify one production deployment in the
linked project and check its ready state and public alias. Zero matches, multiple
matches, a truncated listing or unavailable responses stay uncertain. A later
invocation can reconcile the same intent, without replaying deployment or gameplay.
The CLI may perform its own transport retries; this driver launches it at most once.

Anonymous HTTPS verification reads and hashes every public file, including every
video, and checks a `206` byte-range response for each video. `vercel.json` and
`README.md` are deployment inputs and are excluded from public-serving checks.
Cross-origin redirects, protected pages, changed bytes, missing ranges and an
incorrect alias cannot become success. This is byte and range verification;
browser playback QA remains a separate check.

Private package state contains:

- `publication-intent.json`: the existing exclusive claim.
- `vercel-submission.json`: immutable project, origin, content and submission binding.
- `vercel-publication-status.json`: current publishing, verifying, uncertain or published state.
- `vercel-public-verification.json`: deployment ID, verified public inventory, video ranges and latency.
- `publication-complete.json`: the existing completion receipt, written after verification.

Exit `0` means published, `2` means publishing or uncertain, and `1` means invalid
inputs. Private CLI diagnostics are not printed in public status. Preserve the
package state and stage when an outcome is uncertain. A manual claim without this
driver's submission marker requires operator reconciliation; deleting an intent
to force another deploy is not recovery.

Command contracts follow the official [deploy](https://vercel.com/docs/cli/deploy),
[list](https://vercel.com/docs/cli/list) and
[inspect](https://vercel.com/docs/cli/inspect) documentation. The focused suite in
`test/test_full_client_vercel.py` mocks Vercel and HTTP responses. It makes no
external deployment or model requests; the first real deployment is an explicit
operator integration check with a newly prepared package.

Anonymous verification uses at most four concurrent file jobs. Each job streams
one full file through the existing bounded hash reader, then checks that video's
16-byte HTTP range before finishing. Receipt rows retain the input inventory
order regardless of completion order. The publisher does not buffer whole
videos, alter the exact byte/hash/206/Content-Range checks, or relax same-origin
redirects. Every job shares the original publication deadline.

On failure, no further files are submitted, queued jobs are cancelled, and active
streams observe cancellation between bounded chunks. A blocking network read
still uses its existing socket timeout; verification waits for active workers to
exit and never writes a success receipt for partial checks. Publication intent
and uncertain-deployment reconciliation are unchanged. Mock tests establish the
concurrency bound and overlap; no live deployment speedup is claimed by them.
