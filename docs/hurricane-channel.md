Hurricane channel reconstruction v1
===================================

Patch `0018-hurricane-channel.patch` gives Bowmaster skill 3121004 an explicit
held-key lifecycle. It is a versioned reconstruction, not a claim of complete
original-client animation or timing fidelity. Previously the port invoked an
ordinary attack on both skill key edges and had no continuous channel timer.

The projectile interval is 120ms of simulation time, independent of weapon
speed. This comes from LazyBui's pre–Big Bang packet tick-count experiment,
[Attack Speed Reference](https://www.southperry.net/showthread.php?tid=3088)
(September 4, 2008; revised August 3, 2009), which reports “Hurricane (per arrow)
All: 120ms.” No code or game assets from that page are copied.

Preparation is 960ms, taken from the pinned skill node
`312.img/skill/3121004/prepare/time`; `prepare/action` names `shoot1`.
This is an explicit conservative port policy, not a measured canonical delay
from keydown to first damage. The reference also lists 300ms delay and 330ms
spamming, whose exact relation to preparation is not established here.
The 70ms effect frames and 30ms projectile animation frames do not set firing
cadence. Fixed 8ms simulation updates make both 960ms and 120ms exact; the channel
adds no separate wall-clock catch-up loop or accumulated input replay.

Pressing the key once starts preparation; OS repeat neither accelerates nor
restarts it. Release cancels future pulses, including release during preparation.
Death, loss of resources/skill/weapon eligibility, movement, other attacks,
map clear, focus loss, text entry, Escape, and disabled UI stop future pulses.
Cancellation keeps the key latch until release, preventing held repeat events
from resurrecting the channel. Already dispatched arrows may finish in flight.
The client checks its observed resources before every pulse; authoritative
server cost and ammunition checks remain on the ordinary ranged-attack path.
No extra skill-use packet charges MP a second time.

Current presentation reuses `shoot1`; looping prepare/keydown/keydownend effects,
remote-character start/cancel broadcast presentation, and exact original
startup/end recovery remain unqualified. Client resource observations can lag
server updates; this patch does not fabricate local acknowledgements or waive
server rejection. Native qualification must measure actual held/release packet
cadence, server MP/ammunition changes, visible damage, ordinary save and restore,
and cancellation on the new built client. Unit tests alone do not accept those
live behaviors or qualify the full Bowmaster toolkit.
