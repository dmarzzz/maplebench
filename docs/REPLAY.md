# Authoritative observations and replay animation

The replay draws recorded Cosmic positions. It interpolates a monster's x/y
coordinates only between observations containing the same living object ID and
monster type. A new spawn appears at its first observation; a removed monster is
not extrapolated into an invented position. HP changes remain discrete observed
values, and damage labels report observed HP loss rather than invented damage rolls.

When present, `facingLeft` and `moving` select the monster's presentation direction
and move/stand stance. Legacy traces infer movement only when recorded coordinates
change, retaining the last observed movement direction when the monster stops.
An unchanged coordinate never becomes a fabricated patrol in the renderer.

Each native snapshot receives an explicit animation phase. Maplewright selects a
frame using the actual WZ frame delays after loading monster sprites, without
running its own monster AI or physics. This avoids the old behavior of displaying
the first standing frame and default facing direction in every screenshot.
Move/stand transitions reset animation phase; normal idle and walking frames then
continue across separately rendered snapshots. Pose timing between observations
is presentation, not a claim of exact retail-client frame timing.

Extended snapshot format:

```text
mob objectId monsterId x y hpPercent stance facing phaseMilliseconds
```

`facing` is -1 for left or +1 for right. The native reader still supports older
six-field mob rows. `MAPLEBENCH_SNAPSHOTS_ONLY=true` writes TSV frames and the overlay
without invoking asset export, the native renderer, or FFmpeg; regression tests use
this path with synthetic observations and no game assets.

When observations identify `monsterSimulation: "ground-patrol-v1"`, the overlay
shows **Ground-mob simulation**. That label describes the benchmark's server-side
ground controller. Its speed conversion and patrol/chase decisions are an
approximation, not parity with official MapleStory monster AI. The renderer does
not add that movement: it only presents positions the simulation actually recorded.
Frozen earlier runs retain their original movement and rendering versions.

## Player HP feedback

The overlay shows a player health bar, red floating HP-loss numbers, and green
HP-recovery numbers. Values change at the first observation that records them;
the renderer does not interpolate health or change combat. The previous overlay
only drew floating damage numbers for monsters, which made incoming hits hard to
see even though the server was deducting player HP.

These labels report **observed HP changes**, without assigning an attacker. A
skill such as Slash Blast spends HP, and damage plus healing between observations
can cancel or combine. This trace format cannot recover individual damage rolls,
misses, or exact impact times from HP samples. It also does not reproduce the
client's hit flash or invulnerability animation. The health bar and floating
numbers are presentation feedback over recorded server state.

To refresh an existing video's overlay without rerunning inference or native
rendering, copy its observations, events, controller metadata and plain
`video/henesys-first.mp4` into a separate artifact directory, then invoke the
renderer with the original map/character settings and
`MAPLEBENCH_OVERLAY_ONLY=true`. Keep the frozen trial's original artifacts intact
and identify the copy as a rerender of the same recorded run.
