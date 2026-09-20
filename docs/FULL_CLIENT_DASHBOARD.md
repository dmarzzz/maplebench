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

For automatic uploads after each successful run, use the separate opt-in gallery
exporter. Select the fresh group IDs explicitly and keep any previously approved
recording map. Run one exporter per output directory; stop an older snapshot
watcher first so it cannot overwrite the new recording links.

```sh
python3 scripts/full_client_gallery.py \
  --attempt-root /private/trials --relay-root /private/relay/runs \
  --admin-socket /private/control.sock \
  --output-directory /public/gallery/full-client-benchmark \
  --recording-map /private/recording-map.json \
  --recording-prefix /full-client-benchmark/recordings/ \
  --run-id SELECTED_32_HEX_ATTEMPT_ID --watch-seconds 600
```

Repeat `--run-id` for each selected attempt, up to 32. The exporter waits for a
completed runner and consistent score receipts, verifies the video hash while
copying it, and exposes the replay only after the complete file is available.
It updates results every two seconds without waiting for the rest of the group.
Zero and negative scores remain visible. Failed attempts retain their failure
rows; a missing or corrupt clip does not hide an otherwise verified score or
delay another success. Existing conflicting video files are never overwritten.
Only videos and the public results projection are copied. Private evidence,
accounts and game assets stay outside the gallery. This does not grant visual
review or ranked publication status, start trials, or deploy the site to GitHub.

Replays with verified action and synchronized capture receipts open near the
first acknowledged input. The cue includes a short lead-in; the original video
is unchanged and **Full recording** returns to its beginning. Historical runs
without first-input timestamps can open at **Program start**, labeled separately.
API wait time remains visible. Missing or invalid timing falls back to the full
video. Zero-action runs are never given a gameplay cue. When complete receipts
prove there were no SDK calls, the page says the program exited without SDK calls;
that is distinct from a program that observed or waited but sent no inputs.

A separate publication-evidence column shows the trusted validator's checked,
blocked or awaiting-review status. The exporter discovers a bounded set of
versioned verdict receipts, binds the latest verdict to the exact reviewed
manifest and original runner artifacts, and verifies the hashed visual review.
It exports only fixed labels; private reasons, paths and review text stay private.
A blocked publication check preserves an independently verified persisted score.
Even an evidence-checked row remains unranked in this preliminary dashboard.

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
