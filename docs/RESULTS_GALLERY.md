# Batch results gallery

The queue publishes `index.html` and `summary.json` inside its ignored batch
artifact directory. Each trial has a video card, its exact requested model,
provider-returned model IDs when recorded, scenario, repetition, outcome, and
links to the score, action trace, observations, API decisions, controller, and
prompt. Unknown metrics appear as a dash; missing videos remain visible.

The gallery works directly from disk without a server or external dependencies.
When served over HTTP, it refreshes the summary every ten seconds while the tab
is visible. A playing video is preserved during a refresh. The model, scenario,
and outcome filters retain their selections.

Run the restricted artifact server on the experiment host, then use an SSH
tunnel to reach it:

```sh
python3 scripts/serve-gallery.py --root artifacts/batches --port 8848
```

It binds only to `127.0.0.1`. Its root page lists published batch galleries;
`/<batch-id>/index.html` opens one batch. MP4 byte ranges support seeking without
downloading the whole recording. It denies directory listings, symlinks, hidden
paths, frozen source, private database snapshots, the raw manifest, and queue state. Only
documented evidence filenames in the expected trial layout are served. Do not
substitute a general directory server pointed at the batch root.

Keep the gallery and its recordings private unless deliberately reviewed
for publication; generated artifacts are not Git source files. The gallery
does not upload anything or embed remote media, fonts, or scripts.

## Runner integration

```python
from maple_gallery import build_gallery

index_path = build_gallery(
    batch_dir,
    {
        "id": batch_id,
        "name": "Warrior repetitions",
        "status": "running",
        "backend": "cosmic-v83",
        "code_revision": frozen_revision,
    },
    trial_snapshots,
)
```

Call after state transitions and artifact rendering, using one queue publisher.
Both outputs are written to unique temporary files, flushed, and atomically
replaced. Each is a complete snapshot; the two files are not a multi-file
transaction. Existing galleries remain readable if a replacement fails.

Each trial accepts these fields:

| Field | Meaning |
| --- | --- |
| `id`, `model`, `scenario` | Trial identifier, requested API model, and scenario identifier |
| `repetition`, `attempt` | Numeric repetition and attempt numbers |
| `status`, `reason`, `error` | Worker state and separate gameplay outcome or failure explanation |
| `attempt_dir` | Existing artifact directory, relative to the batch or absolute inside it |
| `video_path` | Existing MP4, relative to the batch or attempt directory, or absolute inside the batch |
| `metrics` | Optional authoritative metric values overriding `score.json` |
| `provider_model` | Optional returned API model when response metadata is stored elsewhere |
| `render_status`, `render_error` | Rendering state, separate from the game result |
| `attempts` | Optional previous attempt records with `number`, `status`, and `error`; each gets its own evidence card |
| `backend`, `mock`, `dry_run` | Explicit provenance; mock flags override server labeling |

Normalized metrics are `duration_sec`, `xp_gained`, `hp`, `accepted`, `rejected`,
`decisions`, `input_tokens`, `output_tokens`, and `total_tokens`. Existing
`score.json` names such as `durationMs`, `xpGainedThisRun`, `finalHp`, and `apiUsage`
are also understood. Provider identities and token usage can fall back to
`decisions.json` response metadata. No cost is estimated without pricing data.

`completed`, `time_limit`, `death`, `decision_limit`, `api_budget`, `budget_limit`,
`action_limit`, and `token_limit` are distinct gameplay outcomes. `infrastructure_error` and
`interrupted` are visible failure categories. A worker state of `completed`
uses its recorded gameplay `reason` when present; it does not turn a time limit
into a successful clear. Keep retried attempts in the input list if they should
remain visible alongside the retry.

The current renderer produces `video/henesys-overlay.mp4`; the gallery discovers
that file and an optional `video/poster.jpg` only inside the supplied attempt directory. The queue owns invoking
`scripts/render-cosmic-clip.mjs` and selecting `MAPLEBENCH_CHARACTER_DIR`.
Rendering failures should update `render_error` without erasing a recorded game
score. No shell commands are executed by this gallery module.

For a manual rebuild from an exported queue snapshot:

```sh
python3 scripts/maple_gallery.py artifacts/batch-001 --snapshot artifacts/batch-001/snapshot.json
```

The snapshot must contain `batch` and `trials` objects matching the interface
above. Do not pass an unrelated batch's recordings as trial evidence.

## Evidence and safety

Server labeling requires `backend: cosmic-v83` from the caller. Unspecified
provenance is labeled unverified; explicit mock runs are labeled synthetic.
Cosmic videos are Maplewright replays of recorded server observations, with
interpolated movement and attack poses. They are not official-client recordings,
and short fixture results do not establish a model ranking.

The publisher copies only documented metadata into its output. It escapes the
embedded JSON and title, renders text through DOM `textContent`, and permits only
existing artifact links within the batch after resolving symlinks. Arbitrary
metadata, absolute host paths, external URLs, and non-MP4 video targets are not
published. This is not a credential scrubber: errors and other explicitly
published text must already be sanitized by the runner.

Run the security and compatibility checks with:

```sh
python3 -m unittest discover -s test -p 'test_maple_gallery.py'
```
