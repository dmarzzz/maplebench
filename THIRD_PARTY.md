# Third-party / IP notes

MapleBench is designed to keep its benchmark framework separate from game assets and server implementations.

- Cosmic and forks have their own upstream licenses; any derived server patches must comply with those licenses.
- MapleStory game data/assets (including WZ files) are not part of this repository.
- Maplewright and any other renderer/client remain separate upstream dependencies and retain their own licenses.
- No source code from Cosmic, Maplewright, or RuneBench is copied into the initial MapleBench scaffold.

Before public distribution of a complete benchmark image, review exactly which game data is required at runtime and whether it may be redistributed. Prefer a benchmark-specific clean content pack if broad redistribution becomes a goal.
