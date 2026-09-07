# Saved MapleBench gameplay

This self-contained dashboard snapshot includes seven original canvas recordings and nine attempt summaries. It is a saved development sample, not a live benchmark or a model ranking.

For a public deployment, build the site with `python3 scripts/prepare-full-client-site.py /absolute/path/to/new-output` from the repository root (requires FFmpeg with libx264). The output must be a new directory outside the checkout. It contains the approved originals plus H.264 MP4 viewing copies with duration metadata and a fast-start index. Deploy that output directory as a static site. The player uses these MP4 copies; the original recording hashes remain unchanged in the results. `playback-manifest.json` records each viewing copy's hash, size, and source hash. Generated video files stay outside Git.

Serve this directory over HTTP to use the player. From the repository root:

```sh
python3 -m http.server 8080 --directory examples/full-client-benchmark --bind 127.0.0.1
```

Then open http://127.0.0.1:8080/. GitHub’s file browser stores the files but does not run the dashboard.

The latest completed Astra recording includes approximately thirteen seconds waiting for the API, followed by twenty seconds of controller execution. Its saved XP increased by 9,000 after ordinary logout. Other recordings include no-op programs, an incomplete action-receipt check, and a recovered invalid attempt. The dashboard preserves those qualifications; sharing a clip does not make it eligible for a ranked comparison.

The recording manifest pins every included file by SHA-256 and byte count. The accompanying results are a sanitized projection of runner evidence, not the underlying private receipt bundle; a repository clone alone cannot independently recompute persisted XP. No API credentials, account export, database, raw prompts/responses, server binary, or WZ assets are included. Videos contain game canvas capture and synthetic benchmark telemetry. MapleStory imagery and other third-party material retain their respective rights; the repository code license does not relicense that material.
