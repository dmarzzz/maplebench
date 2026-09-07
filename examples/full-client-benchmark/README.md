# Saved MapleBench gameplay

This self-contained dashboard snapshot includes seven original canvas recordings and nine attempt summaries. It is a saved development sample, not a live benchmark or a model ranking.

Serve this directory over HTTP to use the player. From the repository root:

```sh
python3 -m http.server 8080 --directory examples/full-client-benchmark --bind 127.0.0.1
```

Then open http://127.0.0.1:8080/. GitHub’s file browser stores the files but does not run the dashboard.

The latest completed Astra recording includes approximately thirteen seconds waiting for the API, followed by twenty seconds of controller execution. Its saved XP increased by 9,000 after ordinary logout. Other recordings include no-op programs, an incomplete action-receipt check, and a recovered invalid attempt. The dashboard preserves those qualifications; sharing a clip does not make it eligible for a ranked comparison.

The recording manifest pins every included file by SHA-256 and byte count. The accompanying results are a sanitized projection of runner evidence, not the underlying private receipt bundle; a repository clone alone cannot independently recompute persisted XP. No API credentials, account export, database, raw prompts/responses, server binary, or WZ assets are included. Videos contain game canvas capture and synthetic benchmark telemetry. MapleStory imagery and other third-party material retain their respective rights; the repository code license does not relicense that material.
