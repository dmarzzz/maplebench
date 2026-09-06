# Live full-client results

The full-client dashboard shows actual trial phases, exact model attribution,
actions, survival, diagnostic client XP, and verified persisted XP. Failed and
recovered attempts remain visible. It never starts a controller or turns an
integration recording into a scored trial.

`scripts/full_client_dashboard.py` exports an allowlisted JSON projection from
private attempts. For a completed trial it rechecks the runner's small hashed
receipts and recomputes persisted XP. It does not repeat large asset or video
hashes on every refresh, and it identifies the trusted runner as the source of
verification. Matching fields alone do not authenticate an untrusted operator.

## Existing localhost gallery

Copy `ui/full-client-dashboard/{index.html,dashboard.js,style.css}` to the
existing gallery root's `full-client-benchmark` directory. Export only the
sanitized snapshot as `results.json`. The gallery permits these exact files and
explicitly copied `recordings/<32-hex-attempt-id>.webm` or `.mp4` files. It does
not expose private journals, API bodies, SQL snapshots, or arbitrary paths.

Run the exporter on the trusted runtime host with private paths supplied by the
operator:

```sh
python3 scripts/full_client_dashboard.py \
  --attempt-root /private/trials \
  --relay-root /private/relay/runs \
  --admin-socket /private/control.sock \
  --recording-map /private/recording-map.json \
  --recording-prefix /full-client-benchmark/recordings/ \
  --output /public/gallery/full-client-benchmark/results.json \
  --public-output --watch-seconds 600
```

The socket request is read-only `status`. Its directory, socket permissions and
peer identity must satisfy the private-socket checks. The watcher exports every
two seconds for the explicitly bounded window, at most one hour. It does not
install a service or schedule future runs. Without `--watch-seconds`, it exports
once. The page identifies stale snapshots when the exporter stops.

The private recording map binds an explicit gallery URL to an attempt ID and
the exact saved video's SHA-256 digest. A URL alone is insufficient. Copy and
verify a recording before adding that mapping; never symlink the private trial
directory into the gallery. A replay link does not imply publication approval.

## Interpreting comparisons

Comparison groups require completed, verified attempts from at least two exact
models with identical baseline, scenario, budgets, runtime inventory and sandbox
image. Each row shows one actual attempt. Zero XP and negative XP are preserved;
missing evidence stays unknown. A valid program that takes no actions can earn
zero XP, and is distinct from a failed API request or broken runtime.

One attempt per model is a preliminary comparison. A model ranking additionally
needs repetitions, balanced order, uncertainty reporting and the separate exact
recording review/publication gate. Combat randomness is not asserted to be
deterministic. The displayed subset is labeled when the bounded result limit
omits older attempts.
