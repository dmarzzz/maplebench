# Skillbook design study

Open `/skillbook/` from the existing examples HTTP server. This standalone prototype does not alter either the historical recording page or the live catalog.

- Class trials use a frozen, minimal projection of the public September 8 pilot snapshot, retrieved September 12, 2026. `data.json` records its source URL and full-source SHA-256.
- Twelve cells map one-to-one to published attempts. Values are exact signed persisted XP, with one verified attempt per cell. Color is relative within each column; there is no overall ranking.
- Proposed skill tasks are explicitly untested. Their cells contain no fabricated scores.
- Native buttons and a semantic table support keyboard selection; the matrix scrolls within its own region on phones. Cell selection exposes original recording and cohort links.
- `research.md` records the source review, task proposals, scorer requirements, failure semantics, and rollout recommendation.

The code is original. RuneBench supplies design inspiration; no code or game icons were copied from it. The prototype reuses MapleBench’s existing original illustration and self-hosted licensed font.

Checks: all 12 cell values/model/attempt mappings match the frozen public source; desktop/mobile rendering, keyboard selection, 24 unscored proposed cells, local resource links, and JavaScript syntax verified.
