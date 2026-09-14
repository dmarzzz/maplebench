# Three-minute scripted environment checks

The four checks below verify the repaired full client with real server state,
ordinary logout persistence, and original recordings. They use a fixed script
through the game SDK, make **zero model API calls**, and are **unranked**.
They are environment checks, not a four-model comparison or full-skill certification.

The protocol is `scripted-native-productivity-v2`: a 180-second execution ceiling,
with actual recording durations reported below. All four finished alive. Each
run independently verified capture, real-time simulation, ordinary save, and
restoration of its frozen class fixture and finite inventory.

| Class | Acknowledged inputs | Original video | Saved XP change | Capture FPS | Simulation / wall ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| Hero | 149 | 178.074 s | +32,000 | 34.109 | 1.000004 |
| Bowmaster | 198 | 178.028 s | +9,000 | 34.051 | 1.000039 |
| Ice/Lightning Arch Mage | 93 | 177.951 s | +18,250 | 34.161 | 0.999958 |
| Night Lord | 111 | 178.118 s | +18,250 | 33.933 | 0.999997 |

Saved XP includes the brief observation-only settlement after recording and
before logout. It is persisted gameplay evidence, not a leaderboard score or
a claim that every point was earned inside the video interval. The different
class fixtures and simple script also do not establish comparative class strength.

## Recordings and website

The woodland design selected from the local `http://127.0.0.1:8080/` preview is
integrated into [MapleBench](https://maplebench.vercel.app/#environment-checks).
These four checks are its featured videos. Historical model observations retain
their original labels and results in the separate results and recording sections.

- [Hero](https://maplebench.vercel.app/checks/abd3c826cb3b4178ae420fd2eced480d/recordings/abd3c826cb3b4178ae420fd2eced480d.webm)
- [Bowmaster](https://maplebench.vercel.app/checks/b4a28b13e7d2456886755ab3f0a40dfa/recordings/b4a28b13e7d2456886755ab3f0a40dfa.webm)
- [Ice/Lightning Arch Mage](https://maplebench.vercel.app/checks/0c099701a86645b1b4a8a9ecf327fb21/recordings/0c099701a86645b1b4a8a9ecf327fb21.webm)
- [Night Lord](https://maplebench.vercel.app/checks/e6cb2441343a48d0bf73066a0aa4434f/recordings/e6cb2441343a48d0bf73066a0aa4434f.webm)

The player opens at the first acknowledged input and offers the full original
recording. No footage is retimed or synthesized. Deployment: **dpl_6srFrcCWRVsEJSsozVQHqsCb1TXF**.
Independent decode and public browser verification: **All four original videos independently decoded; public file hashes and byte ranges verified; all four browser players advanced at 1× without media errors**.

## Repaired runtime and limits

The measured source is `772630c0791897f04bf65066e0a30fdec9905001`. Its clean client
build includes 0014 fixed-step timing, 0015 packet framing, and 0016 monster
lifetime ordering. Browser capture includes the cadence correction from
`ce3b6d045a22e6ff1c1312722a4d51b621aa0c32`.

The old clock could fall behind real time at low render rates. It now retains
8 ms simulation steps and accounts for elapsed wall time. Each accepted clock
measurement spans the original capture, requires at least 30 capture FPS,
simulation time within 1% of wall time, a GPU renderer, and less than one full
8 ms step of pending simulation debt. These are measurements of these runs,
not a guarantee about every machine or future recording.

The missing-monster incident came from the normal map-transition refresh:
stop control, kill0, kill1, full respawn, and controller reassignment. The client
queued spawns but applied kills immediately, making final alive state depend on
packet/update timing. The fix cancels earlier queued spawns on a recognized kill
and replaces a non-alive object on a later full spawn, including its layer
membership. Live duplicates and death-animation semantics remain unchanged.
See [the lifecycle repair](FULL_CLIENT_MOB_LIFECYCLE.md) and
[packet framing](FULL_CLIENT_PACKET_FRAMING.md).

The script follows a reachable nearby target and uses mapped attacks and buffs.
It has no vertical pathfinding or learned policy, so it may wait after clearing
nearby enemies. Bowmaster's continuous Hurricane channeling remains a known
port limitation. These checks do not certify every available skill, optimal
play, or a ranked model baseline. Earlier failures remain unchanged historical
evidence; the four runs above use the repaired production build without the
private diagnostic instrumentation.
