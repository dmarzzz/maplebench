# Shadow Partner native source regression

These are exact public Journey source bytes from the production client through
MapleBench patch 0016, source `772630c0791897f04bf65066e0a30fdec9905001`.
Upstream: [nmnsnv/maplestory-wasm at bc0234fe](https://github.com/nmnsnv/maplestory-wasm/tree/bc0234fe7c7f53322453e7bdd79564d9aca4cd8b).
`SHA256.json` pins every C++ input; original AGPL notices and license are retained.
No game assets, credentials or runtime evidence are included.

`skill-scalars.json` contains only numeric Shadow Partner/Shadow Stars definition
facts independently matched between Skill.nx and Cosmic XML, for levels 1–30.
The runtime still reads its real NX data; these facts are inert test storage.

The test applies 0020 with zero fuzz and compiles the actual Player buff and
admission methods, Combat::apply_move, Mob::calculate_damage/next_damage, Attack
types and AttackPacket constructor. A small move fixture supplies already-loaded
skill hit counts; it does not claim to test all of Skill::apply_stats. Rendering,
socket transport, inventory/NX storage and stat sources are inert. The RNG uses
distinct deterministic line values to detect cloning, missing rolls or duplicate
scaling. Both native damage-line order and original packet bytes are checked.

This validates source behavior, not official-client formula parity, live effects,
server consumption, a complete toolkit or model performance. The source proposal's
damage semantics and remaining runtime gates are documented in
`docs/FULL_CLIENT_SHADOW_PARTNER.md`.
