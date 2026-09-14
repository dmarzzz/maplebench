# Packet framing compilation fixture

These are the original Journey client source files at upstream revision
`bc0234fe`, as retained in the verified client source manifest for the
`573ff2e1b12c820bfbae7a42581c58a1fa420ff1` build. `Session.cpp` includes the
previously applied local-channel routing patch. SHA256.json binds the exact
pre-0015 bytes. Original AGPL notices are retained; these files are test inputs,
not an alternative runtime implementation. No game assets or runtime data are
included. Tests apply 0015 with zero fuzz and compile the actual parser and
cryptography against an in-memory socket and packet dispatch sink.
