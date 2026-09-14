# Skill diagnostic source fixtures

Journey AGPL-3.0 sources, upstream `bc0234fe7c7f53322453e7bdd79564d9aca4cd8b`,
as used by MapleBench runtime source `772630c0791897f04bf65066e0a30fdec9905001`.
The original license notices remain in each file. SHA256.json pins exact bytes.

The test applies patch 0019 without fuzz and compiles the actual diagnostic
serializer. Storage/I/O collaborators are inert. Tests check server-received
buff identity and cancellation semantics, signed/zero values, bounded output,
and separation from the existing model observation. They do not prove live
skill effects or server persistence. No game assets or runtime records included.
