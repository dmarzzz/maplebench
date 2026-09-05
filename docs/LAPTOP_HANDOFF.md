# Continue on another laptop

Clone the code onto the new laptop and reuse the existing remote runner. The
compiled game client, upstream assets, Cosmic world, private configuration, API
key, and recordings can remain on that runner. Viewing the demo needs Git, SSH,
and a browser; it does not require rebuilding the client or running models locally.

## Get the current code

```sh
git clone https://github.com/dmarzzz/maplebench.git
cd maplebench
git status --short
git log -1 --oneline
```

If the repository is already present, inspect its working tree first and use
`git pull --ff-only` when clean. Preserve any local work instead of resetting it.
Read `AGENTS.md`, [full-client control](FULL_CLIENT.md), and the rest of this note
before changing the runtime. Developers should enable `.githooks` as described
in `AGENTS.md` and install its required secret scanner before committing.

## Reconnect to the existing demo

The new laptop needs its own authorized SSH access to the runner. Use its
existing access if available; otherwise authorize that laptop's public key.
Keep private keys and API keys on their original machines. A GitHub clone does
not grant runner access.

Replace `your-runner-ssh-alias` below with an SSH destination already configured
and verified on the new laptop:

```sh
ssh -N -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:8843:127.0.0.1:8840 \
  -L 127.0.0.1:8841:127.0.0.1:8841 \
  -L 127.0.0.1:8842:127.0.0.1:8842 \
  your-runner-ssh-alias
```

Keep this terminal running. Once any active run and recording upload finish,
close the old laptop's full-client browser tab. Then open
`http://127.0.0.1:8843/web/index.html` on the new laptop. The bridge admits one
active browser; it releases an absent browser's ownership after three seconds.
The other two forwards are required for the game and asset WebSockets.

Verify ordinary automatic login, fresh HP/MP, and the full native game HUD.
**Controls & models → Run SDK script** runs a short smoke check and saves its
recording on the runner. A scripted run correctly says **no evaluated model**.
The API buttons run the named OpenAI models remotely through the same SDK; the
viewing browser must stay open and active to render and receive inputs.

If SSH works but the page does not, inspect the existing demo service and its
bounded world lease. A lease may have expired while the laptops were being
switched. Reuse the existing operator setup and world locks; do not start a
second world or overwrite the database. If SSH reports a local port conflict,
identify the listener before changing or stopping it.

## Current continuation point

- The full Journey WASM client supplies ordinary movement, combat, monster
  contact, skill animation, and hit reactions.
- The live and recorded HUD uses violet, lime, and orange, a maple-leaf insignia,
  HP/MP meters, controller/model identity, held keys, and recording status.
- Manual controls, a sandboxed SDK script, and four OpenAI API model buttons work.
  Each API button requests one short program; this is not the durable batch queue.
- Per-run evidence and publication checks exist, but these full-client runs
  remain **unranked integration tests**. Shared baseline resets and authoritative
  server scoring still need to be connected to this adapter.
- [NanoCodex research](NANOCODEX.md) is documented; NanoCodex is not installed.

Runtime paths and access details are private operator configuration, deliberately
absent from this public repository. Do not commit them, game assets, credentials,
raw runtime outputs, or local handoff notes. Keep model/API execution and heavy
downloads on the runner unless the operator explicitly changes that setup.
