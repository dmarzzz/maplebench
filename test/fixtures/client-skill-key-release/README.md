`Stage.cpp` is the existing MapleBench integration of Journey upstream
`bc0234fe7c7f53322453e7bdd79564d9aca4cd8b`, used for the client built with source
`173f5bc9c180dbede3ccf59b2ffbf8555d499bb1`. It retains its AGPL license notice.
Its exact SHA-256 is pinned in `test_client_skill_key_release.py`.

The test applies the optional sixth client patch, then compiles the actual
`Stage::send_key` and `Stage::handle_held_actions` methods with inert game
collaborators. It verifies dispatch and release behavior, including the previous
unwanted casts on keyup. It does not simulate native damage or qualify Hurricane
channeling. No game assets or runtime configuration are included.
