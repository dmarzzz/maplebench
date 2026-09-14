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

## Candidate 0014

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

These are source tests. A new combined WASM build must verify real-time
simulation, stable rendering and capture overhead during actual gameplay before
replacement recordings are promoted. Low FPS can remain visually choppy even
after game-time advancement is repaired. The three-minute scripted successor is
a different control identity from the historical 120-second controls and the
permanent five-minute agent baseline.
