# Achilles authority repair

Patch 0022 is a source-tested successor. It has not been live-qualified and must
not be attributed to the earlier scripted controls or published model previews.

Hero Achilles 1120004 is already registered in the native passive dispatcher.
Its matched NX/XML levels store `x=995` through `850`: damage remaining in
thousandths. The port interpreted those values as the fraction removed, so
level 30 removed 85% in the local estimate. The corrected fraction removed is 15%.

There is a second boundary: `Player::damage` returns the damage that
`TakeDamagePacket` writes. The matched Cosmic `TakeDamageHandler` applies
Achilles to that received value before changing HP. Correcting only the native
fraction would therefore still apply the passive twice.

The patch computes the contact base once, uses that same value for a separate
local display prediction, and sends the base unchanged. Cosmic alone applies
Power Guard, Achilles and Magic Guard in its existing order and persists HP/MP.
For an isolated1,100-point contact base and level 30, the outgoing value is 1,100
and the server loss is 935. It is neither the old 140-point loss nor a double
15% reduction. Local Achilles prediction follows the server's double multiply
and integer truncation, including non-divisible values; it does not assert that
the display predicts combined Power Guard/Magic Guard effects.

Three focused regressions compile the real passive→stats→Player→packet path
with pinned original inputs. They cover all 30 levels, the unchanged unlearned
path, a single base calculation, stat removal, misses, ladder/dead states and
non-divisible bases. The server ordering is verified from pinned original Java
source; no Java server is run by these tests.

The existing contact defense estimate remains unchanged and explicitly lacks
original-client defense/RNG qualification. This repair supplies no local HP
mutation, server protocol change, passive learning during a run, or XP claim.
