# Native baseline readiness

As of September 13, 2026, the combined repaired client has completed
productive/idle control pairs for all four classes: Ice/Lightning Arch Mage,
Bowmaster, Hero and Night Lord. Productive controls saved **+14,000 XP**,
**+4,750 XP**, **+13,750 XP** and **+13,750 XP**, respectively. All four no-input
controls saved **0 XP**. Every control restored its class baseline after
ordinary logout.

These are actual server runs of `scripted-native-productivity-v1`: scripted
controls, `model:null`, zero API requests, unranked, and ineligible for model
score publication. They are environment checks, not the five-minute model
baseline or full class-skill qualification.

## Verified Mage pair

| Control | Run ID | Input actions | SDK requests | Saved XP change | Program duration | Recording duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Productive | `5c8c115edbc640a6b96542872cd9558a` | 91 | 291 | +14,000 | 113.420s | 115.091s |
| No input | `9b198412b3114eb6b256a690f617cbfa` | 0 | 227 | 0 | 114.229s | 116.425s |

Each control has a 120-second program ceiling and a 125-second recording
ceiling; the recipe stops before those limits. SDK requests include observations
and waits, so the idle control legitimately has requests with no input actions.

Both started at level 180, EXP 73,250, HP 12,000 and MP 16,000 on map 240040511.
The productive control finished alive at EXP 87,250; idle finished at EXP
73,250. Each original inner completion has `failure:null`, verified capture,
and a clean restored state. Independent review checked the canonical programs
and SDK receipts, recording hashes and capture bundles, and all 47 backed-up
files per run against their backup manifests.

Each run has one matching ordinary-disconnect save receipt, followed by an
offline character snapshot. Saved XP is the difference between those initial
and final persisted snapshots at the unchanged level. Post-run restoration
returned character state, gameplay attack/jump bindings, and USE inventory to
the same initial baseline. All 100 Power Elixirs remained after both runs:
this pair verifies restoration but does not establish potion consumption or
healing behavior. It also does not qualify the separate native XP-window ledger.

## Verified Bowmaster pair

| Control | Run ID | Input actions | SDK requests | Saved XP change | Program duration | Recording duration | Captured frames |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Productive | `b9f6425db54c4aff8a70e2b361e1a1ca` | 84 | 232 | +4,750 | 114.511s | 116.009s | 980 |
| No input | `e82c702036fe4ded86dbe37559ef0819` | 0 | 227 | 0 | 114.098s | 115.571s | 1,001 |

Both started at level 180, EXP 73,250, HP 12,000 and MP 6,000 on map 240040511.
Productive play finished alive at EXP 78,000; idle finished alive at EXP 73,250.
The productive recording shows a monster kill and XP gain near its end.
Each run has a completed post-render capture, one matching ordinary-disconnect
save, an offline final snapshot, and clean restoration of character, keymap and
USE inventory. All 32 files in each original backup manifest were hash-checked.
Both retained all 100 Power Elixirs; this is not potion-consumption proof.
Recording durations above use the original capture receipt rounded to
milliseconds; the idle container probe rounds its presentation extent to
115.572s. Neither pair qualifies the separate native XP-window ledger.

## Verified Hero pair

| Control | Run ID | Input actions | SDK requests | Saved XP change | Program duration | Recording duration | Captured frames |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Productive | `a77a308549314916a655914a185e57c5` | 91 | 309 | +13,750 | 114.541s | 115.650s | 983 |
| No input | `5c5b27a90eaa4e82821fbab0502a3ace` | 0 | 227 | 0 | 114.169s | 115.656s | 995 |

Both started at level 180 and EXP 73,250. Productive play finished alive at
EXP 87,000; idle finished alive at EXP 73,250. Each has one ordinary-disconnect
save, an offline final snapshot, clean character/keymap/USE restoration, and
32 original backup files checked against their hashes and sizes. All 100
Power Elixirs remained. This pair does not isolate Combo/Advanced Combo effects.

## Verified Night Lord pair

| Control | Run ID | Input actions | SDK requests | Saved XP change | Program duration | Recording duration | Captured frames |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Productive | `78edc5af1acc4d77b2f6eaa13bbfad07` | 85 | 254 | +13,750 | 113.771s | 115.758s | 982 |
| No input | `d77ebcbd3c324823bfa4bebb6afb4423` | 0 | 227 | 0 | 114.273s | 115.818s | 992 |

Both started at level 180, EXP 73,250. Productive play finished alive at EXP
87,000; idle finished alive at EXP 73,250. Each has an ordinary-disconnect save,
clean character/keymap/USE restoration, and 32 original backup files checked
against hashes and sizes. Productive play's persisted throwing stars changed
from 18,400 initially to 18,313 after logout and 18,400 after restoration;
idle retained all 18,400 stars. Both retained all 100 Power Elixirs. This verifies
87 consumed stars and restoration, not Shadow Stars behavior; that skill is
absent from this frozen toolkit.
Hero and Night Lord began at HP 12,000 and MP 6,000 on map 240040511.

These tables use original capture durations; packet/container rounding can
differ by less than one millisecond. No productive/idle pair alone qualifies
the separate native XP-window ledger or every class mechanic.

## Frozen implementation

The original runtime manifests identify source
`e875bdb4a4a905a4995be8c0d032bec459441b28` and these SHA-256 fingerprints:

| Artifact | SHA-256 |
| --- | --- |
| Client JavaScript | `83e758528ef7a2a212334fe8cb7abc5402a1d042f2d8f2ef69badc114c7217d8` |
| Client WASM | `508faf2c234e75bc207930e0f06b7f6958015943e4ecc8874eb7013bcddbabfa` |
| Server JAR | `c6258ee8408a4d41ea3ba5edc2eafd9bc51f92af5eb3c903a824e7cbb7712819` |

The combined build includes spell damage, Bow Expert, critical passives,
Arrow Bomb power, and Lucky Seven/Triple Throw base-range repairs. Successful
productive controls do not isolate every repaired mechanic.

## Remaining admission work

All four productive/idle pairs are complete. Offline fixtures and mapped skill
definitions still do not establish each skill's effects.

Verify each admitted skill's actual effects and persisted resources, and freeze
the declared scope before the
matched four-model baseline. Core gaps still include Hero Combo/Advanced Combo
damage; Bowmaster continuous Hurricane, Sharp Eyes and summons; Mage charged
Big Bang, Ifrit and full elemental/status behavior; and Night Lord Flash Jump,
Shadow Partner and live Shadow Stars cost/buff verification. Its per-attack
ammunition exemption is already server-owned; the separate
[0013 client admission/presence repair](FULL_CLIENT_SHADOW_STARS.md) is
source-tested only and is not in this frozen runtime. See the
[release checklist](BASELINE_RELEASE_CHECKLIST.md) and
[toolkit limitations](FULL_CLIENT_SKILL_TOOLKITS.md). No full-kit claim follows
from these pairs.

Raw recordings, receipts, database material and runtime configuration remain
private. This document contains only sanitized experiment facts and identities.
