# Explicit-frame capture prototype

This opt-in prototype adds `ui/full-client/webcodecs-recorder.js`. It does not
change the legacy controller, accepted capture policies, source activation, or
historical recording eligibility. Controller/runtime/publication integration
must explicitly freeze `post-render-encoded-frame-v1` and schema 3 before use.

The implementation uses WebCodecs' association of output timestamps/durations
with submitted VideoFrames and flush completion before closing. Queue size
alone does not cover codec-internal pending work, so both pending encode calls
and submitted-minus-output counts are bounded. Codec support is checked rather
than assumed. [W3C WebCodecs specification](https://www.w3.org/TR/webcodecs/).

Encoding requires `latencyMode: "quality"`: WebCodecs permits bitrate/framerate
driven frame drops in `realtime` mode and forbids them in `quality` mode. Support
that changes or omits this setting is refused before encoding.
[WebCodecs latency modes](https://www.w3.org/TR/webcodecs/#latency-mode).
Chromium 152.0.7977.82 disables VP8's drop threshold in quality mode while keeping
its fast VP8 speed setting and realtime encoding deadline.
[Chromium VP8 implementation](https://chromium.googlesource.com/chromium/src/+/refs/tags/152.0.7977.82/media/video/vpx_video_encoder.cc).
This producer change requires fresh source pins. It retains the eight-frame
pending limit, 30 fps hint, 2 Mbps bitrate and every-hook capture; overload still
fails. Existing evidence and capture-policy acceptance rules remain unchanged.

The current producer synchronously reads the already composited post-render
canvas into sRGB, 8-bit RGBA `ImageData`, then constructs `VideoFrame` from that
CPU byte buffer with explicit sRGB color metadata. It does not retain a
canvas-backed GPU resource while waiting for the next frame's timestamp. The
canvas read and raw-frame construction both finish inside the same render hook;
no delayed read, frame selection, extra frame or GPU-source fallback is allowed.
The HTML canvas API supplies the pixel copy, and the raw-buffer VideoFrame
constructor copies those pixels into its own media resource.
[HTML pixel manipulation](https://html.spec.whatwg.org/multipage/canvas.html#dom-context-2d-getimagedata),
[WebCodecs VideoFrame constructors](https://www.w3.org/TR/webcodecs/#videoframe-constructors).
Unexpected dimensions, color space, byte format, or readback/construction errors
abort capture with the allowlisted `capture_snapshot_failed` diagnostic.

This source-pinned change tests GPU resource retention as one possible cause of
encoding stalls under game load. It does not establish the cause or guarantee
loaded-game throughput. The copy consumes CPU time within the existing capture
deadline; the queue, frame-gap limits, every-hook requirement and complete
encoded/decoded ledger checks are unchanged. The source must receive fresh
activation pins and native acceptance before model trials. Historical recordings
are not reinterpreted under the new producer.

WebM uses a single VP8 track, a 1 ms timestamp scale, explicit BlockDuration for
every frame, delta-frame references, a duration header and keyframe cues. There
is no guessed duration, default frame rate, frame lacing or audio. Ledger Tags
precede clusters so bounded metadata probes can read them. These choices follow
the container's block timestamp and duration rules. [WebM container guidelines](https://www.webmproject.org/docs/container/),
[Matroska element specification](https://www.matroska.org/technical/elements.html).

## Browser API

```js
import {createPostRenderRecorder} from './webcodecs-recorder.js';
const recorder = await createPostRenderRecorder(outputCanvas, {
  maxDurationMs: 335000,
  onFailure: code => handleInterruptedCapture(code),
});
// Only inside the existing post-render hook, after drawing game canvas + HUD:
recorder.onRendered();
// Stop accepts no further frames and records its endpoint before awaiting work:
const {blob, encoder_receipt, measurements} = await recorder.stop();
```

The factory has a five-second support/configuration bound, then samples arm
monotonic and wall clocks synchronously. It does not manufacture an initial
frame. `onRendered()` snapshots immediately, returns true on acceptance, and
increments `frames`. It throws on overload or capture failure. `submittedFrames`,
`outputFrames`, `failed`, `startedAt` and `startedWall` are available. There is no
MediaRecorder fallback. `stop()` returns the same promise on repeated calls,
flushes within five seconds and completes all hashing/muxing within 15 seconds.
Failures abort the encoder and never return an uploadable Blob.

Keep one snapshot pending until the next actual render supplies its duration;
close snapshots promptly after submission. The first post-render snapshot is
PTS 0. Later timestamps are `floor(render_monotonic_ms - first_render_ms) * 1000`
integer microseconds. Duplicate quantized timestamps are a failure, not a drop.
Durations are the difference to the next timestamp. The final duration ends at
`ceil(duration_ms - first_frame_offset_ms) * 1000`, with a minimum one-millisecond
terminal tick after the last PTS. Use those exact serialized operands in both
the producer and verifier; algebraically equivalent floating-point subtraction
can fall on the other side of a tick boundary. A quantized final duration above
250 ms fails capture even if the raw tail is within 250 ms. Never clamp it.
The rounding contributes one timestamp tick, plus floating-point representation
error at an exact tick boundary.

Raw capture measurements retain arm→stop time and first/last frame offsets.
Video time instead begins at the first rendered frame. Replay cues must subtract
the first-frame offset; comparing video extent directly to raw arm duration is
incorrect. The same offset must be used by frame-specific terminal evidence.

## Evidence and fixed bounds

`encoder_receipt` contains exactly:

```json
{
  "schema_version": 1,
  "codec": "vp8",
  "timebase_us": 1000,
  "submitted_frames": 0,
  "encoded_frames": 0,
  "flushed": true,
  "ledger_sha256": "<exact UTF-8 ledger SHA-256>",
  "ledger_bytes": 0,
  "webm_sha256": "<whole saved WebM SHA-256>",
  "webm_bytes": 0
}
```

The zeros above describe field types, not an eligible empty recording. The actual
receipt requires at least two frames. The WebM's `MAPLEBENCH_ENCODER_LEDGER_V1`
TagString holds exact UTF-8 JSON with keys `schema_version`, `codec`,
`timebase_us`, `submitted_timestamps_us`, `encoded_timestamps_us`, `durations_us`,
`encoded_sha256`, and `flushed`. The arrays have one entry per accepted frame.
Output callbacks must match the next expected input timestamp and duration;
duplicates, reordering, missing outputs, invisible VP8 frames, changed dimensions
and unmet requested keyframes invalidate the recording. The hash array covers
each exact encoded VP8 packet payload, not decoded pixels. The software encoder
configuration does not promise identical compressed bytes across machines.

The frozen capture policy is:

```json
{"id":"post-render-encoded-frame-v1","max_endpoint_gap_ms":250,"max_wall_drift_ms":5,"timestamp_slack_ms":2,"max_frame_gap_ms":1000,"max_frames":20000}
```

Code additionally bounds encoded pending work at eight frames, simultaneous
packet hashes at 16, embedded ledger at 8 MiB, and the entire final upload at
95 MiB. A 30 fps bitrate hint does not resample the hook: every rendered callback
must be accepted and encoded, or capture fails. Hidden pages, relay loss and
native source/clock/terminal identity remain the caller's explicit checks.

The new verifier must hash the saved video and exact raw ledger UTF-8, then
compare every decoded packet PTS, explicit duration and packet SHA-256 against
the ledger. It must verify decoded frame count too, and preserve original raw
capture/terminal evidence. Impose the ledger limit before JSON parsing and a
bounded ffprobe output size. Do not promote a receipt to game/action/model
evidence merely because encoding passed.

## Validation

`node --test scripts/test_webcodecs_recorder.mjs` covers ordered timing, exact
counts, duplicate/missing output, invisible frame rejection, queue limits,
quantization, clock drift, gaps, resize, unsupported codec, quality-mode support, failed hashes and
bounded configuration/flush/finalization. CPU snapshot tests also cover exact
pixel bytes and format, synchronous snapshot ownership across later canvas
changes, retained-frame closeout and readback errors without fallback.

`scripts/check_webcodecs_capture.mjs` runs an isolated headless browser on a
synthetic canvas through this exact module, then checks ffprobe packet hashes,
PTS/durations, decoded count, container extent and ledger/file hashes. It requires
an explicit fresh private output directory plus `PLAYWRIGHT_MODULE_PATH` and
`CHROME_EXECUTABLE`; it never loads game assets or control endpoints. Synthetic
video outputs are runtime artifacts and must remain outside Git. This harness
is a codec/container test, not native gameplay acceptance or a five-minute run.
