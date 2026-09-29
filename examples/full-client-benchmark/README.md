# Saved MapleBench gameplay

Public site: https://maplebench.vercel.app/

Share the latest verified recording: https://maplebench.vercel.app/latest/

This self-contained snapshot includes eight original canvas recordings and eleven attempt summaries. The main page features the latest completed, evidence-checked Astra run while retaining failed and incomplete attempts in history. The `/latest/` page contains only that selected run. This is a recorded development benchmark, not a live feed or a model ranking.

The featured run is `4149dc7596194dc49067a9ed3af9e3d7`: exact requested/returned `gpt-6-astra`, 34 acknowledged inputs, +9,250 persisted XP after ordinary logout, and alive at logout. The player opens near the recorded program start, skipping approximately 12.3 seconds of API wait. **Full recording** returns to the beginning. First-input timing was not recorded for this historical run; the player labels that limitation.

Serve this directory over HTTP from the repository root:

```sh
python3 -m http.server 8080 --directory examples/full-client-benchmark --bind 127.0.0.1
```

Then open http://127.0.0.1:8080/latest/. GitHub's file browser stores the files but does not run the dashboard. This is an older development snapshot, not the current live catalog. Do not deploy it over the live site without integrating the current results and cohort URLs. Keep `.vercel/` project linkage and credentials outside Git.

The manifest pins every included video by SHA-256 and byte count. Results are sanitized projections of runner evidence, not the underlying private receipts; a repository clone cannot independently recompute persisted XP. No API credentials, account exports, database, raw prompts/responses, server binaries or WZ assets are included. Videos contain game canvas capture and synthetic benchmark telemetry. MapleStory imagery and other third-party material retain their respective rights; the code license does not relicense that material.

## Results website

The public page is an independent static research site inspired by RuneBench: a centered introduction and four equal gameplay views, a collapsible distributed simulation lab, frozen-input comparison chart and table, model-filtered recording explorer, and expandable complete history. Montage excerpts are muted and can be paused; reduced-motion preferences disable their automatic playback. The full player retains the original recording and uses only the recorded program-start or first-input cues.

`index.html`, `style.css`, and `dashboard.js` are mirrored into `latest/`, which loads its own single-run snapshot. Update both copies together. Result JSON and the recording manifest remain the source of the displayed evidence.

The visual direction combines RuneBench’s readable research-page structure with an original MapleStory-inspired world background. Five opaque paper cards separate the overview, architecture, results, recordings, and methodology. Consistent mascot headers and sticky section navigation make the page easier to scan; detailed prose and evidence tables open on demand. Layout and critique guidance was consulted from [Impeccable](https://github.com/pbakaus/impeccable). Manrope is self-hosted under the SIL Open Font License; see `fonts/OFL-Manrope.txt`.

## MapleStory accents and distributed architecture

The clean layout now includes original pixel-art fan illustrations: a maple leaf in the title, mushroom/slime companions above the recordings, red/blue potions beside the SDK example, a meso pouch in Results, and a return scroll beside the quest and the “Back to town” link. Small EXP and observation icons continue the theme. The artwork and exact generation/edit prompts are in `illustrations/README.md`; no extracted game artwork was added. Below-the-fold sprites use lazy loading and all decorative images have empty alternative text. The existing game-image non-affiliation notice stays in the footer.

The **Simulation lab** is a native disclosure, closed by default. Its single, unframed diagram connects shared inference to three workers and expands one into the controller, sandbox, Journey client, Cosmic server, assets, and MySQL persistence. Navigation to the lab opens it; Enter and Space operate the disclosure. No nested diagram panels, architecture tabs, or repeated worker cards remain. The diagram describes this snapshot’s historical single-request protocol; it does not claim a shared job queue or autoscaler.

The rollout facts were checked on September 12, 2026 against the pilot/expansion infrastructure definitions, rollout retirement records, and the public result catalog: three temporary workers provisioned, four vCPU and 16 GB per worker, all workers retired; 12 completed five-minute pilots and recordings across three public cohorts. These historical infrastructure and public catalog counts are separate from this directory’s older eight-recording snapshot. Provisioning, native qualification, and completed model trials must remain distinct. Keep whole cohorts on a single host; matching VM sizes do not imply scene equality or cross-host score comparability.

When porting the design to the live catalog, retain the current result data, cohort URLs, newer protocol wording and evidence controls. Copy `fonts/` and `illustrations/` along with the styles/scripts, and resolve each page’s relative resource paths.

## Section cards and reading depth

The page has five main section cards, each with an accessible heading and a matching navigation anchor: `overview`, `approach`, `results`, `trajectories`, and `methodology`. The introductory quest is condensed into the overview card; the complete attempt history sits inside Recordings. A full-viewport `henesys-world.png` backdrop gives the page a continuous illustrated setting, while opaque warm-white card surfaces preserve text contrast. The sticky navigation highlights the current reading section and works at mobile widths.

The architecture diagram, rollout facts, XP chart, selected recording, and essential limitations stay visible. Architecture, observation/control notes, and the SDK example sit inside the Simulation lab disclosure. Per-run evidence tables use their own native disclosure. Methodology is three short, always-visible rules; linked OSS credits live in the footer. No benchmark attempts, result values, recording files, publication evidence, or cohort rules were changed.

The copy pass applied Impeccable’s [Distill](https://github.com/pbakaus/impeccable/blob/main/skill/reference/distill.md) and [Clarify](https://github.com/pbakaus/impeccable/blob/main/skill/reference/clarify.md) guidance. It removed repeated subtitles, redundant diagram explanations, duplicate methodology prose, and the extra hero architecture button (the navigation still links there). Static body copy outside the SVG, including all disclosures, fell from 1,193 to 602 whitespace-delimited words. Important limitations remain beside the relevant evidence; missing scores are never described as zero.

New background provenance and its exact built-in generation prompt are recorded in `illustrations/WORLD-BACKGROUND.md`. Earlier section-art prompts remain in `illustrations/SECTION-ART.md`. All decorative source PNGs retain their provenance. The scenery is fixed, noninteractive, and nonanimated; below-fold section art uses lazy loading. Serve this growing artwork collection as cacheable static files rather than inlining every original into a size-limited production UI payload.
