# Client stream framing repair

Apply `patches/full-client/0015-split-packet-framing.patch` after the existing
client patch stack. This source repair changes only `Net/Session.cpp`,
`Net/Session.h` and the encrypted length cast in `Net/Cryptography.cpp`.

The wire header is four bytes; the opcode is two payload bytes. Six bytes is
therefore the minimum complete frame, not a minimum socket-read size. The old
receiver discarded fresh reads shorter than six bytes and trailing fragments
shorter than six bytes after a complete packet. It also treated a full header
without payload as another new header on the next read. A consuming byte-stream
socket can produce any of these splits regardless of WebSocket message sizes.

The repair accumulates exactly four header bytes separately from the existing
131072-byte payload buffer. It preserves every fragment, validates a decoded
payload length of 2 through 131072 before copying, and decrypts/dispatches each
complete packet once. Coalesced packets are processed iteratively. Invalid
lengths close the connection; they do not attempt stream resynchronization.
A new connection resets partial state. A handler-triggered reconnect discards
only the remaining old-connection bytes, before the new handshake/IV can use
them. The encrypted header's 16-bit XOR is decoded as unsigned, preserving
valid 32768–65535-byte payloads. The wire format and fixed buffer cap are unchanged.

Run the bounded local source regression:

```
python3 -m unittest discover -s test -p test_client_packet_framing.py -v
```

The test applies the patch with zero fuzz to hash-bound, licensed source
fixtures and compiles the actual receiver and cryptography. An in-memory socket
and dispatch sink replace network/game effects. It reproduces the original
four-byte-header/two-byte-payload loss, then checks every one- and two-split
boundary of a multipacket stream, one-byte reads, empty reads, 15000 coalesced
packets, exact plaintext/encrypted bytes, maximum lengths, rejected fault
lengths, reconnects, and packet-handler errors. These checks are source
verification, not a WASM build or live gameplay qualification.

The earlier observation of server monsters with an empty client monster list
is not yet causally attributed to framing. Transport/observation evidence and
fresh native controls on a rebuilt candidate remain required; existing failed
attempts and recordings retain their original interpretation.
