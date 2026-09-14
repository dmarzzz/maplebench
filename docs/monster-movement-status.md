Server-driven monster movement effects
======================================

Client patch `0021-monster-movement-status.patch` and server patch
`cosmic/0002-monster-status-order.patch` are a matched protocol change. Both
`PacketCreator.applyMonsterStatus` and `encodeTemporary` now snapshot entries in
`MonsterStatus` enum order. The old unordered-map payload order cannot safely
identify several simultaneous values from a mask alone. The spawn serializer
continues excluding WATK/WDEF; dynamic parsing includes their payloads.

Spawn masks use slots 0/2 (with Cosmic's repeated companion integers). Dynamic
apply/cancel masks use slots 2/3 after an eight-byte zero prefix. The parser checks
mask layouts, known bits, complete payload sizes and dynamic trailers before
applying any state. It skips nonmovement status payloads without granting them
unimplemented behavior. Reflection trailers follow the pinned server's distinct
spawn and dynamic layouts. Unknown/truncated packets cannot partially apply an
effect. There is no guessed expiry: the server sends duration -1 and owns cancel.

SPEED, STUN and FREEZE are stored for known or queued spawn lifetimes. A later
full spawn supplies its initial snapshot; following apply/cancel events remain
ordered through deferred construction and controller updates. Kill clears the
lifetime, and map clear drains pending spawns and statuses. Unknown-object
statuses cannot leak into a future reuse of that object ID.

Stun/freeze stop motion forces, velocity and AI progression while preserving
animations, HP display, liveness and normal death handling. Slow uses the received
SPEED value added to the native baseline percentage, clamped to 0–200%, following
the declared proportional policy in `MapleBenchMobMotion.speed`. It changes
movement force, not animation speed or damage. Server cancellation resumes the
normal AI; no local kill, fake damage or status expiration is synthesized.

This does not implement status icons, every monster debuff, or original-client
knockback/airborne subtleties. Native qualification must show server-applied
stun/freeze/slow, actual movement reduction, cancellation and correct ordinary
save/restore on the matched new client/server pair. Compiler tests alone do not
qualify Arrow Bomb, Coma, freezing attacks or Hamstring end to end.
