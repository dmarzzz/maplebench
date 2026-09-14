# Achilles source regression inputs

These are unchanged public Journey C++ files from the MapleBench client through
patch 0016, together with its matched Cosmic `TakeDamageHandler.java` source.
The upstream client base is
[bc0234fe7c7f53322453e7bdd79564d9aca4cd8b](https://github.com/nmnsnv/maplestory-wasm/tree/bc0234fe7c7f53322453e7bdd79564d9aca4cd8b).
`sha256.json`, itself pinned in the test, binds these exact production inputs.
Original copyright notices and AGPL license are retained.

The compiled regression applies only 0022 with zero fuzz, then compiles actual
passive, stats, Player damage and TakeDamagePacket methods. Numeric asset
storage, packet bytes sink and irrelevant physics/UI dependencies are inert.
The matching server statement and its ordering are checked from original source;
the test does not compile or run a Java server. The original methods reproduce
the reversed passive and its already-reduced outgoing damage.

No NX/WZ assets, SQL, credentials, host configuration or runtime evidence are
included. Levels 1–30 `x=995..850` values were independently checked in NX and XML.
