# hero-cave reference pack

Reference material for the `hero-cave` fixture (Advanced Hero in the Cave of
Light, map `240050300`). Read what you need; nothing here is required reading.

| File | Contents |
| --- | --- |
| `character-and-skills.md` | The build, every invocable skill, costs, targets, combo mechanics |
| `map-and-monsters.md` | Floor geometry, spawn, the Skelegon population, excluded actors |
| `consumables-and-scoring.md` | Finite potions, what is scored, what is not |

## Provenance and trust

Every fact carries a source tag:

- **`[scenario]`** — declared in `scenarios/hero-cave.json`. Authoritative for
  this fixture.
- **`[repo]`** — documented in `docs/SCENARIOS.md` for a shared preset. Reliable,
  but written for the level-130 `hero` preset; `hero-cave` uses `hero_advanced`.
- **`[unconfirmed]`** — consistent with the above but not independently verified
  against WZ data in this repository. Do not rely on an exact number here.

Nothing in this pack is a promise about server configuration, RNG, respawn
timing, or monster positions at any moment. Observe the live game.

## Pack identity

This directory is hashed as a unit and pinned into the runtime inventory, so the
knowledge available to a model is part of the frozen evaluated system
(*model + harness + tools + knowledge + budgets*) rather than an implicit
variable. Build the manifest with:

```sh
python3 scripts/knowledge_pack.py knowledge/hero-cave
```

Changing any file here changes the pack hash and therefore requires a new
scenario version. It does **not** change `scenario_fingerprint`, so fixture
identity and reference material version independently — which is the point.
