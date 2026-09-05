# Next experiments

Completed: compile and boot the patched Cosmic server, seed a synthetic Warrior,
disable upstream autonomous policy for the controlled character, request movement
and sword attacks through the SDK, and replay observations using Maplewright.

The first Henesys combat fixture earned 30 server-authoritative XP from three
Slimes. Its initial idle check earned zero XP. This was a short baseline run,
not the standardized ten-minute benchmark. Clips include action, controller/model,
HP, level, elapsed-time, and XP overlays.

The OpenAI queue uses direct API requests and identical scenario resets. Record
model IDs returned by the provider, request usage, latency, chosen actions,
server observations, and XP. Keep model-driven runs distinct from scripted
baselines and operator-driven demos.

1. Improve movement presentation and add authoritative damage numbers.
2. Compare API models on a larger combat fixture with additional skills.
3. Add full database snapshots and run the standardized ten-minute task in a
   natural combat map.
4. Connect an observer through the actual client network path for continuous
   recordings. The current renderer replays observations and interpolates poses.
5. Add loot, items, portals, and skill-allocation actions through normal handlers.
6. Generalize the harness to four characters and implement the Kerning PQ task.

Keep secrets, personal data, runtime configuration, game assets, and recordings
out of Git. Run the tracked-file guard and Gitleaks before each commit and scan
the full history before publication or a visibility change.
