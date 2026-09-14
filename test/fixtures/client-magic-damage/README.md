# Spell damage regression source

These are the actual Journey client sources used by the preceding native
verification build, before `0008-spell-damage.patch`. The base is
[`nmnsnv/maplestory-wasm`](https://github.com/nmnsnv/maplestory-wasm/tree/bc0234fe7c7f53322453e7bdd79564d9aca4cd8b)
at `bc0234fe7c7f53322453e7bdd79564d9aca4cd8b`, with the earlier integration,
ammunition and Teleport changes already applied. Each exact fixture hash is
checked by `test_client_spell_damage.py`; a base commit alone does not describe
these patched bytes. Retain the AGPL notices in the source files.

The test applies the production patch with zero fuzz and compiles the actual
`Player::prepare_attack`, `Skill::apply_stats`, and `Mob` damage methods, using
inert stat/asset storage and deterministic RNG. The original methods reproduce
different spells retaining the same weapon-derived damage range. The patched
methods exercise the INT/equipment-to-packet-damage path. No assets, account
data or live observations are included. This is source verification, not a
completed native qualification or model result.
