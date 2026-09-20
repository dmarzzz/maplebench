# Hero-180 v1 knowledge pack

This pack applies only to the MapleBench v1 `hero-180-expanded-v1` profile on
expected map `240040511`, under `full-client-adaptive-pilot-v1`. It expands the
accepted four-slot Hero profile to the 17-slot two-handed-sword toolkit declared
in this pack. Ten core slots have a separate native qualification recipe. Seven
additional active skills are exposed for scored play but remain explicitly
unqualified until matching native effect evidence exists.
The matching learned-skill rows, keymap, client routes, and native outcomes all
require a fresh release qualification. It must not be used for the level-150
`hero-cave` fixture on map `240050300`.

The task is to maximize **signed persisted net XP** during the declared
300-second wall-clock run. Net XP is final persisted EXP minus initial persisted
EXP. It includes death penalties and may be zero or negative. Client-reported EXP
is diagnostic; the persisted before/after score is authoritative.

Use current observations for character position, HP, MP, EXP, level, life state,
map, and monster object IDs and positions. `sdk.observe()` does not expose active
buffs, combo-orb count, cooldowns, monster HP, inventory quantities, or damage
rolls. Infer Combo charge cautiously from your own Combo activation and landed
attack history; each finisher consumes that inferred charge, so rebuild it before
trying the other finisher. Game time continues while the model plans. Get a
productive loop running, re-observe, and adapt without risking death or exhausting
the remaining action, SDK, request, and time budgets.

## Provenance

All facts here are reproducible from committed repository sources:

- `[protocol]` `scripts/full_client_adaptive.py`: profile, neutral key slots,
  timing and SDK limits.
- `[toolkit]` `scripts/full_client_hero_toolkit.py`: 17 invocable Hero mappings,
  eight learned passives, the core-ten qualification subset, and fixture exclusions.
- `[cohort]` `docs/V1_COHORT.md`: Hero-180/map-240040511 scope and signed
  persisted-net-XP objective.
- `[accepted]` `docs/FULL_CLIENT_ACCEPTANCE.md`: historical native Hero runs.
- `[admission]` `docs/CLASS_MATRIX_ADMISSION.md`: the conservative summary of
  native capabilities already observed and the requirement to re-prove controls
  on the declared release fixture.

These paths are provenance labels, not files exposed to model-written programs.
The pack contains no WZ data, game assets, credentials, host paths, account data,
private evidence, or runtime configuration.

The scoped toolkit is derived from the repository's earlier expanded-toolkit
work (`470dd8de24cc3ba1253268060198ecb992cf9d37`). Later candidate repairs
(`cd2c92e35420266043a963109afffc3b12167f89`) are qualification prerequisites
for Combo/Advanced Combo and finishers; citing them does not claim those repairs
are present in a runtime binary or that any native check passed.
