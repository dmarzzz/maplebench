# Ordinary player buff wire order

Patch `0023-ordinary-buff-wire-order.patch` fixes ordinary local player buff
decoding for the checked casts in the four selected toolkits. It requires a new native build and live verification; it does not
change any frozen toolkit, native recipe, or earlier recording.

The first Night Lord toolkit-v2 trace exposed Haste values assigned to the
wrong native stats: SPEED received 20 and JUMP received 40. The client then
derived speed 120 and capped jump 123. The matching Haste level-20 definitions
specify speed 40 and jump 20, which should produce native totals 140 and 120
from the fixture's unbuffed totals of 100.

The matching Cosmic `StatEffect` appends Haste SPEED before JUMP and Rage WATK
before WDEF. `PacketCreator.giveBuff` preserves the caller's order when writing
each ten-byte value/skill/duration field; its declaration-order comment is a
caller requirement, not an enforced sort. The 22 declared buff casts checked
for these four toolkits follow that order. This does not establish the order
of every other caller. Journey instead consumed values by iterating two
unordered maps. It also consumed the COMBO/SUMMON shared wire
bit twice. This could assign the wrong values or interpret trailer bytes as
another buff.

The new handler visits ordinary fields by ascending wire bit, second mask's
fields before first mask's fields, using the declaration order matched by the
checked four-toolkit callers. Other callers may require separate validation.
Mask words retain their existing first-mask/second-mask header order. Shared
bits are consumed once using COMBO, HANDS and PICKPOCKET, without treating
their legacy SUMMON, SHOWDASH and PUPPET aliases as additional values.
Signed Booster values, zero-valued Shadow Stars, packed Sharp Eyes values,
ordinary cancellation and stat recalculation retain their normal paths.
Apply packets preflight the complete selected tuple count and the ordinary
nine-byte trailer before any Player/UI mutation; unknown ordinary apply mask
bits and truncated bodies raise the existing packet error. Cancellation has
no value tuples and still clears known bits when an unknown bit accompanies
them, preserving its ordinary one-byte trailer.

The focused test compiles the production handler, packet reader, buff storage,
cancellation, active-buff application and stat setter methods. It verifies
Haste 40/20 and cancellation, Rage's signed multi-stat values, a single Combo
payload across server count/reset changes, other shared bits, mixed mask words,
signed/zero/packed values, malformed headers, and a truncated second Haste
tuple whose nine-byte trailer remains present. The latter must leave both
Player state and buff icons unchanged. Mixed known/unknown cancellation masks
must still remove known buffs. The old Combo decoder is a
deterministic failing witness; the old unordered traversal order itself is
implementation-dependent. Public source fixtures retain their license and
exact hash pins. No game assets are included.

This repairs the checked ordinary cast packets in the four selected toolkits. It does not
qualify special Pirate buff formats, unsupported summons, all first-mask stat
definitions, buff expiration, or damage effects merely from receiving a buff.
A known-bit mask alone does not distinguish every special-format body; in
particular this change does not identify or implement `givePirateBuff` or the
legacy composite Battleship format. No paired server change is needed for the
checked ordinary packets.
