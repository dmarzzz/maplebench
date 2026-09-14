# Public research dashboard

The current presentation follows the approved illustrated-world design: a fixed
original landscape, opaque paper sections, mascot headings, sticky navigation,
and one collapsed How agent simulations work section. A feedback-loop diagram
leads into the Agent SDK, followed by the Distributed simulation environment.
The overview connects model, program and world, with two observation paths:
fresh state returns to the running program through the SDK, and a state snapshot
returns for the next model call. The caption explains program-level observation,
controller-supplied execution feedback and the shared time budget. A separate
branch verifies saved XP after logout; mobile uses a vertical layout. Tinted header bands and Maple icons
distinguish the three subsections. The
earlier gridded component diagram and Maple scenery remain. Operator-managed experiment coordination assigns plans to
a stack of complete worker boundaries. Each contains the controller, sandbox,
browser and local asset service, proxy, Cosmic server, local MySQL and verifier.
Remote inference and experiment coordination sit outside the worker boundary.
The Worker runner node groups local finite-plan execution and the durable trial
runner: it resets, executes and collects evidence on its own worker, without
assigning work to other workers. Separate VMs
can run concurrently, with one trial per world under exclusive local locks. This is
a deployment schematic; stacked layers do not assert a live worker count.
Within the worker, Agent runtime groups the controller and generated-program
sandbox. Game environment groups the Journey WASM frontend, Cosmic Java backend
and MySQL persistence. These are logical software groups, not additional VM or
security boundaries. Worker lifecycle execution and evidence collection remain
outside the evaluated agent group. The external Model inference provider lists
OpenAI API as the current implementation. The host controller has network access. Only model-written JavaScript runs in
the networkless Docker sandbox; validated SDK requests use stdin/stdout pipes.
This boundary is checked against `maple_agent.py` and `agent-sandbox.mjs`, not
presented as an independent security audit or a live-host isolation attestation.
The evidence path distinguishes the reusable worker-local game database from
private per-attempt artifact files. Controller metrics and video, database exports
and save receipts feed the runner’s verified evidence bundle. A separate publisher
exports allowlisted metrics and recordings to the static site; the diagram does
not claim a central telemetry database or automated cloud artifact backup. An
optional evidence disclosure lists storage, per-run/per-cycle measurements and
publication boundaries. Direct flow, SDK and environment anchors expand the parent disclosure. Source links
point to the runtime documentation and SDK implementation. The full catalog, model/class selector,
recording player, research matrix, skill and timing evidence, operator notes,
failed attempts and original recording cues remain available.

The page and navigation order is Overview, How it works, Methodology, Results,
then Recordings. The matrix leads Results, followed by an embedded Skill
experiments gallery labelled Exploratory runs and explicitly unscored. The
gallery uses subsection/model headings and a simple divider within the Results
card. The results-development-previews slot gives the publisher an explicit
embedded mount point; legacy standalone mounts remain supported. Class comparisons, per-cell counts,
verification metadata and skill inputs expand on demand. Scripted environment
clips use Class demo title bars, brief class descriptions and MapleStory Wiki links.
Saved XP and recording length stay visible with explicit labels; Full details
expands the complete run list and identifies demos as unscored preset inputs.
Demo scores remain separate from model results. Preview layout styles belong
to this UI, not the publisher.

Four preview slots come from distinct exact models in one selected frozen group.
Missing recordings remain empty; zero and negative XP do not remove a slot.
No API-latency estimate substitutes for a verified playback cue. Result refresh
preserves the selected video position and playback state. Historical results and
protocols are unchanged by presentation refresh.

The linked Built by dmarz byline sits beneath the hero description. The sticky
header contains only section navigation, keeping it to one row on phones.

Methodology describes the published pilot's controls, signed XP equation,
verification, limited replication, request reserve and failure accounting.
Future scoring is a separate disclosure. Results uses selectable square cells
with an evidence inspector; Class pilots reads the unchanged research matrix.
Skill suite shows six proposed tasks as unrun and cannot supply model scores.
Zero, loss, unknown and unrun have separate labels and colors. Detailed planning
and exact proposed entry schedules live in `docs/NEXT_SIMULATION_PLAN.md`.
The compact footer links to GitHub and Twitter with a non-affiliation notice.
Its update date describes the website presentation, independently of result
timestamps. The presentation publisher stamps `site-updated` when preparing a
release; update the HTML fallback date when publishing by another workflow.
OSS credits live in the architecture caption. Background refresh status stays
quiet unless the feed is unavailable or an active operator run has stale data.

`index.html`, `style.css` and `dashboard.js` remain the required three UI files.
Manrope and its complete SIL Open Font License remain embedded in the stylesheet;
`OFL-Manrope.txt` preserves the standalone notice. Ten optional original generated
illustrations are served as ordinary relative PNG files. Their exact names,
SHA-256 values and byte counts are frozen by `full_client_presentation_assets.py`
under `maplebench-original-illustrations-v1`. The source PNGs were copied unchanged
with generation metadata; see `illustrations/README.md`, `SECTION-ART.md` and
`WORLD-BACKGROUND.md`. They are decorative fan art, not extracted game assets.

Legacy packages omit `presentation_assets` and retain their original exact file
layout. New packages explicitly bind the policy and each PNG in their content
inventory. Refresh changes only UI/presentation bytes and binds the original
package with `presentation_parent_sha256`. Catalog and deployment checks verify
the same original artwork at each mounted root/cohort path. Unknown PNG names,
missing art, changed bytes, symlinks and unrecognized policies fail closed.
The limits remain 4 MiB per non-video file, 100 public files and 512 MiB aggregate.

The donor's standalone Skillbook was an untested task-design study and is not
included in this live-data presentation. No donor result JSON, recordings,
private runtime evidence or credentials are copied into the source UI.
