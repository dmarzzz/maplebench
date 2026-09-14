# Monster lifetime ordering repair

`0016-mob-lifecycle-order.patch` changes only the client `MapMobs.cpp` queue and
reuse logic. Apply it after the existing patch stack, including 0015. No private
diagnostic hook, packet format, skill rule, SDK field or score rule is included.

Cosmic's `net.server.channel.handlers.PlayerMapTransitionHandler` performs an
ordinary map-transition refresh: stop control, destroy the monster, remove its
controller, send a full spawn, then assign control again. The inspected
`PlayerMapTransitionHandler.java` bytes have SHA256
`c3047a6a2b5104c46be585c0b7b91a1a48239e481fa24341b6b669daab60c59f`.
Destroy sends kill animations 0 and 1. Together with initial spawn/control,
this produces two full-spawn packets (236), two kill packets (237), and four
controller packets (238) per monster. The diagnostic's 34/34/68 counts for
17 monsters match that normal server path, with no handler errors.

The client defers full spawns until its next update but applies kills
immediately. Previously, a kill before that update found no object and left
its queued spawn intact. If the initial spawn had already been instantiated,
kill0 disabled it and kill1 marked it dying. A later same-OID spawn merely
reactivated that old object, retaining dying/dead/fade state; it could remain
visible while being excluded from `get_alive_positions`. The same packet
sequence therefore produced different final states depending on update timing.

The repair makes a recognized kill cancel all earlier queued spawns for its
OID, preserving the FIFO order of other objects. It then uses the existing
kill-animation path for an instantiated object. A later full spawn recreates
a non-alive object after removing its old object and layer membership. Live
duplicate/controller spawns retain the existing object and control-update
behavior. Unknown kill-animation values remain no-ops for both queued and
instantiated monsters. There is no retry, resurrection of a final-killed
queued object, or change to existing death-animation timing.

Run the bounded local regression:

```
python3 -m unittest discover -s test -p test_client_mob_lifecycle.py -v
```

The tests apply the exact patch with zero fuzz to licensed source fixtures,
compile the affected MapMobs methods, the real MapObjects implementation and
the real Mob::kill/is_alive bodies, and mock asset construction/physics edges.
They reproduce both original failures and exercise all 128 update-boundary
partitions of the actual initial-spawn/controller → stop → kill0 → kill1 →
stop → full-respawn/controller sequence. Additional checks cover a final kill
before first instantiation, unrelated FIFO order, a later new lifetime, old
layer cleanup, live duplicate identity, death animations and unknown values.
These are source checks; a rebuilt client's fresh native control and ordinary
saved closeout remain the live acceptance gate. Prior failed recordings and
results remain unchanged.
