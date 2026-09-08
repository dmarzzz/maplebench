# Encoded post-render capture contract

`post-render-encoded-frame-v1` is an explicit frozen opt-in. Legacy duration and
`post-render-frame-envelope-v1` verdicts remain unchanged; historical recordings
cannot gain a new verdict by relabeling their policy.

Schema 3 capture metadata carries an `encoder_receipt`: schema version 1, VP8,
1000-microsecond timebase, submitted and encoded frame counts, successful flush,
and the SHA-256 hashes and byte lengths of both the WebM and its embedded ledger.
The first submitted post-render frame has presentation timestamp zero. Its
separately measured monotonic offset binds that origin to the synchronous capture
arm clock; asynchronous recorder events do not define the origin.

The UTF-8 `MAPLEBENCH_ENCODER_LEDGER_V1` WebM tag contains the exact submitted and
encoded timestamp arrays, frame durations, and encoded payload SHA-256 hashes.
The saved stream must decode to exactly those packets, timestamps, durations and
payloads. Intermediate durations equal successive timestamp differences. Every
frame is accounted for; dropped, duplicated, reordered or substituted packets
fail verification. The final duration is bounded by the endpoint limit after quantization.
Its end timestamp is exactly `max(last_pts_us + 1000,
ceil(duration_ms - first_frame_offset_ms) * 1000)`. Producer and verifier
subtract these same serialized offsets, avoiding different floating-point
cancellation from separately subtracting absolute clock readings. No padding
tolerance is added.

The ledger is bounded to 8 MiB, the WebM to 95 MiB, and the count to 20,000 frames.
Existing bounded descriptor-based probing reads the verified artifact, obtains
packet data hashes, and checks the complete decoded frame count. Clock, endpoint,
interruption and causal start/terminal receipts remain required. These are
capture-integrity checks; they do not constitute visual gameplay acceptance or
make a scripted native test an API benchmark.
