# Fixed-step timing repair

The September 13 native controls exposed a real simulation slowdown in the
existing integration patch. Their videos preserve elapsed time, but the
client's game clock cannot keep up with the measured rendering cadence.

| Productive control | Rendered frames / second | Maximum game-time advancement / wall second |
| --- | ---: | ---: |
| Ice/Lightning Arch Mage | 8.56 | 0.548s |
| Bowmaster | 8.45 | 0.541s |
| Hero | 8.50 | 0.544s |
| Night Lord | 8.48 | 0.543s |

The source uses an 8ms physics/animation step, but patch 0001 limits the WASM
loop to eight updates per rendered frame. That advances at most 64ms of game
time per frame. At about 8.5 FPS, the simulation can advance only about 54% of
wall time. Keeping the remaining accumulator does not solve a persistent
throughput limit: debt grows every frame. The recorded frame counts and original
container durations establish the rendering cadence; this speed limit is a
source-derived upper bound, not a directly recorded simulation counter.

Saved XP, ordinary logout and baseline restoration in those controls remain
valid observations. Their successful capture checks establish video integrity,
not normal game speed. The controls must not qualify a normal-speed benchmark.
Historical recordings and scores remain unchanged and explicitly diagnostic.

## Repair 0014

`0014-fixed-step-catch-up.patch` preserves 8ms simulation steps and increases the
finite catch-up budget to 128 updates per rendered frame. This covers 1.024s of
simulation work, sufficient for the recorder's permitted one-second frame gap
when the client starts without accumulated debt. It does not advance steps
without elapsed time, discard remaining time, stretch video timestamps or alter
attack-speed constants. Overload beyond this finite budget retains its debt;
the source fix cannot guarantee that an arbitrarily slow host runs in real time.

The patch changes Timer to `std::chrono::steady_clock` and exposes
`Module.MapleBenchSimulationTiming`: actual update count, per-frame elapsed
time, cumulative elapsed/simulated time, pending debt and budget exhaustion.
The cumulative wall clock is sampled at tick entry. `published_wall_ms` is the
later publication time after updates and before drawing; it must not be used
as if it were the tick-entry measurement. Expensive updates or asset I/O are
charged to elapsed time at the next tick.

The initial accumulator contains one 8ms step, so the invariant is
`total_wall_ms + 8 = total_simulation_ms + pending_ms`. Live comparison should
use warmed sample deltas across the complete action/recording interval, inspect
debt and gaps, and account for the measurement phase. A single zero-debt sample
does not establish real-time behavior.

## Validation and remaining work

Nine focused regressions compile the real original/repaired loop and show:

- The old loop slows down at 115ms frame intervals; the repair catches up.
- Fast-frame simulation behavior remains unchanged, without acceleration.
- Frame gaps through one second leave less than one step of pending time.
- A three-second stall remains bounded and retains debt for later catch-up.
- Counters report the actual updates/debt; disconnect performs no extra work.
- The emitted timing object survives the C macro boundary and parses as JS.
- The real Timer header uses a monotonic clock.

These are source tests. The combined WASM build now includes this repair and
0013. During live scripted attempt `2403bfa428944dd5b4645e0c98dca97a`, independent
browser samples observed approximately one second of simulation per wall
second on the native Apple GPU. That attempt did **not** produce a saved video:
its recorder hit the byte limit. These timing observations alone do not qualify
the attempt or a replacement recording.

## High-refresh recording repair

The browser rendered near 120 FPS, while the VP8 encoder declared 30 FPS and
received every rendered frame. The recording reached its byte limit after
114.117 seconds, with 13,696 frames submitted. The original failed attempt is
retained; it is not a publishable clip.

Revision `ce3b6d045a22e6ff1c1312722a4d51b621aa0c32` bounds frame submission to
60 FPS and declares that cadence to the encoder. It selects actual post-render
frames and retains their actual timestamps. The first and final rendered
frames remain included. There is no interpolation, duplicate-frame insertion,
time scaling, changed game speed, or increase to the existing recording caps.
Low rendering rates and genuine gaps remain visible in the evidence.

The recording change passes 48 focused Python tests and 39 recorder tests.
Actual replacement clips must also pass independent decoding, complete capture
ledger checks, and browser clock measurements covering the recorded interval.
The clock gate requires simulation within one percent of wall time, less than
one pending 8ms step, and at least 30 captured frames per second.

The three-minute scripted successor is a different control identity from the
historical 120-second controls and the permanent five-minute agent baseline.
