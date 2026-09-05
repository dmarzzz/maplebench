# Third-party software and game-content boundary

MapleBench intentionally separates the benchmark framework from the v83 server/client engines and from proprietary game content.

## Pinned upstream engines

### Cosmic bot fork

- Upstream: `NDBellisario/cosmic`
- Pinned commit: `b01cf27833f568cde52a0a70a38532474eedd4d9`
- License: GNU Affero General Public License v3.0 (AGPL-3.0)
- Use: authoritative v83 server/world plus the existing bot movement, physics, combat, navigation and party infrastructure.

MapleBench modifications to Cosmic must retain upstream notices and be distributed/served in compliance with AGPL-3.0. We prefer small, auditable control-plane patches that reuse normal game code paths.

### Maplewright

- Upstream: `Sheilem/maplewright`
- Pinned commit: `79b3e8fb25c84c45212c12b45235cdc00c6f6f3c`
- License: GNU Affero General Public License v3.0 (AGPL-3.0)
- Use: native/browser v83 observer client, WZ-to-render asset tooling, WebAssembly canvas, and WebSocket-to-TCP proxy.

Maplewright itself ships no MapleStory game content. Keep its generated asset paths ignored and retain its license/notices in any fork.

## MapleStory content

MapleStory names, trademarks, WZ data, artwork, audio, maps and other proprietary game content are not included in MapleBench. Local development may point the upstream engines at WZ files the developer has obtained legally. Do not commit or redistribute those files from this repository.

## Benchmark framework

The TypeScript benchmark harness, scoring code, task definitions and asset-free
viewer are original MapleBench code. This repository is distributed under
AGPL-3.0; see `LICENSE`. Cosmic and Maplewright modifications retain their
upstream notices and license. Proprietary game content is not included.
