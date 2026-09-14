# Fixed-step loop source fixture

These three asset-free files are copied from the hash-verified client source
used to build the September 13, 2026 native controls at MapleBench
`e875bdb4a4a905a4995be8c0d032bec459441b28`. They retain upstream notices and
AGPL-3.0-or-later licensing. Upstream is
https://github.com/nmnsnv/maplestory-wasm at
`bc0234fe7c7f53322453e7bdd79564d9aca4cd8b`, with the existing integration patches.

`test_client_fixed_step.py` pins each file's bytes, applies patch 0014, and
compiles the actual original and repaired `main_tick` with a controlled elapsed
clock and inert update/render collaborators. It also compiles the real Timer
header and evaluates the JavaScript emitted by a named-first-argument EM_ASM
macro, so unprotected object-literal commas cannot hide behind a variadic stub.

No game assets, runtime recordings, private configuration or credentials are
included. Source timing checks are not live renderer qualification.
