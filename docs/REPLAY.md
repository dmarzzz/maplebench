# Authoritative observations and replay animation

The replay draws recorded Cosmic positions. It interpolates a monster's x/y
coordinates only between observations containing the same living object ID and
monster type. A new spawn appears at its first observation; a removed monster is
not extrapolated into an invented position. HP changes remain discrete observed
values. Legacy recordings show observed HP loss; `combat-v1` recordings carry
individual server hit events and packet damage lines.

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

## Legacy player HP feedback

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

## Combat trace v1

New Cosmic observations include `combatTrace: "combat-v1"` and
`character.motion`: airborne/climbing/swimming/crouching state, facing, movement
intent, the remaining attack/hurt cooldowns, and the selected action name/start.
The bridge reads the existing mechanics; it does not change damage, movement,
Stance probability, hitboxes, or attack timing.

- `combat_attack` records the selected WZ action, skill, facing, speed and the
  existing plan's cooldown/hit delay. Its sequence number identifies the attack.
- `monster_hit` is emitted immediately after `MapleMap.damageMonster` applies
  damage and before disposal/XP. It carries the monster object/type, position,
  HP before/after, actual HP loss and the server's killed flag. Synchronous hits
  reference the attack sequence and include its individual packet rolls and
  critical-line indices. These rolls can exceed remaining HP or differ from
  damage after shared-handler adjustments. Delayed/unattributed applications
  have `attackId: -1` and no invented damage lines.
- `player_hit` records touch/fall source, damage or miss, HP before/after, and the
  actual knockback decision after Stance/rope/death checks. HP after the ordinary
  damage/autopot path is separate from the damage number. Skill HP costs do not
  become incoming-hit events.

Replay uses the recorded attack duration, stops an attack pose on knockback, and
keeps the recorded facing during recoil. Airborne state replaces the old
height-relative-to-camera guess. Individual outgoing rolls stack above each
monster, with separate columns when nearby targets would overlap; incoming
damage/misses appear in purple. Green numbers remain observed
net HP recovery. The health bar continues to show discrete observed HP.

A surviving monster plays WZ `hit1` after a damaging hit; only an explicit killed
flag starts `die1`. Reaction frames use the asset service's WZ durations, saved as
`mob-animations.json` beside the recording. Death presentation ends after that
sequence; a disappearing monster or unrelated XP event cannot imply a kill.
Snapshot-only tests can supply this timing file without assets or network access.

The paper-doll patch resolves direct WZ action/frame references, including both
seven-frame Brandish sequences and their signed delay magnitudes. It refuses
chained/cyclic references. Hero C-1 now selects the `hero-combat-v1` bake; generate
it on the runtime host after applying `scripts/patch-maplewright.mjs` and rebuilding
`wzchar` with the repository's memory/job limits:

```sh
# From the runtime work directory, using legally supplied local v83 assets:
maplewright/target/release/wzchar assets/Character.wz assets/Base.wz \
  baked/hero-combat-v1 0 20000 30030 1040036,1060026,1072001,1402037
```

`node scripts/bootstrap-upstreams.mjs --patch-only` installs the overlay/hooks
into already pinned checkouts without fetching either upstream. Normal bootstrap
continues to fetch the locked revisions. Patch application is repeatable.

This is a Cosmic run presented by Maplewright, not a recording of an official
client. Positions between observations are interpolated. Skill-effect particles,
weapon trails, damage-font sprites, invulnerability blinking, full Hero buffs,
and more demanding encounters remain future work. The recorded hit delay is
metadata: these ordinary Cosmic damage applications occur synchronously, and
replay does not move them to a fabricated impact time. Existing frozen batches
retain their original server, character bake and rendering code.

## Gameplay references and next fidelity checks

Visually reviewed selected sections of these YouTube videos, rather than relying
on their descriptions:

- [Original level-127 one-handed Hero training](https://www.youtube.com/watch?v=e9nvdwmmrn8&t=75s):
  inspected around 1:02, 1:17 and successive frames at 1:53–1:57. The footage shows
  paired outgoing damage lines, a purple incoming-damage number, combo orbs,
  attacks against clustered enemies, and movement between fighting positions.
  The map visibly contains ladders and multiple platforms.
  Its weapon/build differs from our two-handed Hero; do not copy its attack speed
  or damage values as calibration constants.
- [Pre–Big Bang Hero recreation](https://www.youtube.com/watch?v=ncA93xXPCdM&t=764s):
  sampled around 7:58 and 12:44. Useful for skill-effect and buff presentation,
  but this is a MapleStory Worlds recreation with different progression settings,
  not evidence of exact v83 physics or balance.

The implementation priorities from this comparison were:

1. Record individual server hits, source/target and action/knockback state.
   Implemented in `combat-v1`; legacy traces retain their original limitations.
2. Render skill actions/effects and monster hit/death states. Brandish body
   sequences and WZ monster reactions now use the trace; effect particles and
   weapon trails remain to be implemented.
3. Validate a complete, explicitly controlled Hero build: combo/buff state and
   available tactical skills, followed by a hunting scenario that rewards grouping
   and repositioning. C-1 remains a useful mechanics check; its level-54 Roids and
   our level-130 Hero are not a representative challenge for the advanced build.

The visual review did not measure gravity, collision widths, invulnerability
duration or attack delays. Measure those with matched client/server state and WZ
data before changing constants. Keep scenario and gameplay changes in new frozen
batches so existing model comparisons remain interpretable.
