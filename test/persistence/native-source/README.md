# Pinned native experience table

`constants/game/ExpTable.java` is an unchanged copy from Cosmic commit
`b01cf27833f568cde52a0a70a38532474eedd4d9`, matching `upstream.lock.json`.
Original path: `src/main/java/constants/game/ExpTable.java`.
SHA-256: `4faa01f027a11773df0ac7421d59e1b793934282f98e837e06cb967c44629132`.
Its original AGPL-3.0 copyright and license notice is retained.

The lightweight Maven harness compiles this real table because persistence now
also closes native XP windows. This fixture is not a replacement table, a game
asset, or a production overlay. Production still uses the pinned upstream file.
The Python source-pin check prevents silent fixture drift or an upstream-lock
change without an explicit review of this copy. Both persistence and XP-ledger
Java tests run without a database, assets, or a game server.
