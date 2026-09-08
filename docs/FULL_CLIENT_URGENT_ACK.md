# Immediate input acknowledgment transport

The controller previously stored the completed keyboard receipt until its next
ordinary frame poll. A poll already in flight captured the old ACK value and
could wait up to two seconds before scheduling another poll. Thus a 1500 ms
hold could release before the fixed three-second deadline while its receipt
arrived too late. A fresh renderer does not prove timely ACK transport.

After releasing keys, the controller now makes one immediate same-origin
`/control/ack` POST. The original frame poll retains the identical receipt as a
fallback. A lost reply never retries input or creates another urgent POST.
The endpoint validates the session, pending run, renderer, command, current
observation, hold duration and original deadline. It cannot select an input
command or advance session navigation. Duplicate ACKs cannot replace the first
terminal input decision. Neither the SDK budget nor keyboard hold limits change.

New ACKs carry bounded, unscored client monotonic timing: handler entry,
keydown offset (or null), completion offset and urgent-send scheduling offset.
When an ACK reaches the pending request, its first server receipt and transport
are returned in `inputTiming` and retained by the existing SDK trace. Legacy ACKs
remain accepted without this optional field. This does not establish when an
unreceived command executed: no ACK, late rejected ACK, or lost response remains
uncertain. Browser timing is diagnostic, not authoritative gameplay evidence.

Tests exercise the actual JavaScript dispatcher while an ordinary poll remains
unresolved, lost urgent replies, same-receipt fallback, non-dispatching HTTP
routing, owner mismatch, stale frames, early/late ACKs and immutable duplicate
handling. This source candidate needs a new frozen runtime and fresh cohort;
previously failed attempts retain their original verdicts.
