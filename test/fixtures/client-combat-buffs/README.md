# Native combat buff regression sources

These public Journey C++ files are exact bytes from the production client built
through MapleBench0016 (public source772630c0791897f04bf65066e0a30fdec9905001).
The upstream base is
[nmnsnv/maplestory-wasm](https://github.com/nmnsnv/maplestory-wasm/tree/bc0234fe7c7f53322453e7bdd79564d9aca4cd8b),
commitbc0234fe7c7f53322453e7bdd79564d9aca4cd8b. Earlier integration patches
change those bytes; `sha256.json` pins each actual input, and the new test pins
the manifest itself. The source notices and upstream AGPL license are retained.

The tests patch these sources with zero fuzz and compile the production methods
for received buff storage/cancellation, attack admission, attack preparation,
skill application and monster damage. Only numeric asset/stat storage, UI and
RNG are inert. The original methods reproduce missing Combo/Sharp Eyes effects
and missing zero-orb finisher admission. Actual `Buff`, `Attack`, `EnumMap` and
weapon enum definitions are used. Upstream's deprecated `std::iterator` remains
unchanged; the test permits that deprecation warning under C++17.

No WZ/NX files, runtime evidence, accounts or recordings are included. Selected
numeric expectations came from independently matched native/server definitions;
this is source verification and requires a fresh build and live qualification.
