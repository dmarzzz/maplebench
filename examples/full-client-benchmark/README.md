# Saved MapleBench gameplay

Public site: https://maplebench.vercel.app/

Share the latest verified recording: https://maplebench.vercel.app/latest/

This self-contained snapshot includes eight original canvas recordings and eleven attempt summaries. The main page features the latest completed, evidence-checked Astra run while retaining failed and incomplete attempts in history. The `/latest/` page contains only that selected run. This is a recorded development benchmark, not a live feed or a model ranking.

The featured run is `4149dc7596194dc49067a9ed3af9e3d7`: exact requested/returned `gpt-6-astra`, 34 acknowledged inputs, +9,250 persisted XP after ordinary logout, and alive at logout. The player opens near the recorded program start, skipping approximately 12.3 seconds of API wait. **Full recording** returns to the beginning. First-input timing was not recorded for this historical run; the player labels that limitation.

Serve this directory over HTTP from the repository root:

```sh
python3 -m http.server 8080 --directory examples/full-client-benchmark --bind 127.0.0.1
```

Then open http://127.0.0.1:8080/latest/. GitHub's file browser stores the files but does not run the dashboard. This directory is also a standalone static Vercel deployment; link it to the existing MapleBench project before deploying. Keep `.vercel/` project linkage and credentials outside Git.

The manifest pins every included video by SHA-256 and byte count. Results are sanitized projections of runner evidence, not the underlying private receipts; a repository clone cannot independently recompute persisted XP. No API credentials, account exports, database, raw prompts/responses, server binaries or WZ assets are included. Videos contain game canvas capture and synthetic benchmark telemetry. MapleStory imagery and other third-party material retain their respective rights; the code license does not relicense that material.
