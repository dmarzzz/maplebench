# Short skill previews

`full-client-skill-preview-v1` is a development protocol for reviewing native
controls and model skill choices. It gives one model response up to 60 seconds
of program execution, with 240 acknowledged actions and 600 SDK requests at
most. Readiness and the single API request have separate bounded allowances;
the complete controller envelope is 123 seconds. Login, upload, ordinary logout,
and restoration add lifecycle time outside the program window.

Each preview freezes its class toolkit, equipped baseline, prompt, model, source,
and runtime. The model gets the actual named skills and resource constraints.
The mage prompt explicitly invites directional Teleport and varied spells.
This guided exploration is not an equal-start model comparison or an XP score.
It does not change the five-minute adaptive benchmark contract.

The current candidate toolkits map ten skills each for Hero, Bowmaster, and
Ice/Lightning Arch Mage, and eight for Night Lord. These are the implemented
candidate routes, not every skill in the original game. Unsupported summons,
charge mechanics, and Night Lord Flash Jump remain explicitly excluded pending
implementation and native qualification. See the canonical declarations in
`scripts/full_client_skill_toolkit.py`.

Before a model preview, run the separate bounded native development check on
the selected fixture. Its mage recipe probes Teleport before combat, in both
directions, with short holds and adjacent observations. Review displacement,
MP, collision, monster contact, and the original recording. A key acknowledgment
does not establish a cast, hit, or successful teleport.

Public previews use `scripts/full_client_skill_preview_publication.py`. The
exporter rechecks the exact requested/returned model, original model program,
SDK receipts and counters, time/token bounds, continuous post-render capture,
and an independent decode of the saved video. It exports a small allowlisted
summary and the original hashed recording. Playback opens at the first
acknowledged input; the complete recording including planning remains available.
Skill counts are labeled as inputs, not verified casts. No-op or incomplete
attempts stay in private evidence and are not fabricated into playable clips.

The optional preview panel preserves existing cohort files and benchmark
summaries byte for byte. Preview rows have no score or comparison group and are
not added to benchmark denominators. Runtime configuration, account data, raw
API responses, generated programs, and game assets are never published.
