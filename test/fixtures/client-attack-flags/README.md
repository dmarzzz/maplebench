These AGPL-3.0 source fixtures preserve their upstream notices. SkillData.cpp
and SkillId.h are from Journey upstream bc0234fe7c7f53322453e7bdd79564d9aca4cd8b.
Combat.cpp is the existing MapleBench integration source used to build the active
client; only its actual apply_move method is extracted by the test. The harness
compiles the real classification and dispatch methods with inert game/packet
collaborators; it proves branch selection, not server damage or qualification.
No game assets are included. Fixture SHA-256 values are pinned in the test.
