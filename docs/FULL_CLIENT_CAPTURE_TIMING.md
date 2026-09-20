# Opt-in post-render capture timing

`post-render-frame-envelope-v1` is a capture contract for future adaptive pilots.
It changes neither native XP scoring nor the five-minute model budget. It must be
frozen in `adaptive_protocol.capture_duration_policy` before dispatch:

```json
{
  "id": "post-render-frame-envelope-v1",
  "max_endpoint_gap_ms": 250,
  "max_wall_drift_ms": 5,
  "timestamp_slack_ms": 2,
  "max_initial_frames": 1
}
```

The exact object is required. Its addition changes the protocol and scenario
fingerprints; the model instructions do not change. Runs without this object keep
the original schema-1 capture and absolute 100ms recorder/probe duration check.
An old recording cannot acquire eligibility by adding this policy afterward: the
frozen protocol, request, schema-2 raw capture and recomputed recording receipt
must all agree. No previous result is reclassified by this change.

## What is measured

MediaRecorder callback duration includes the interval before the first post-render
frame and after the last. Decoded video duration instead comes from packet
presentation timestamps. A capture can contain an initial canvas frame followed
by the observed post-render frames. Subtracting callback duration from decoded
extent therefore compares different endpoints.

The schema-2 browser collector records `first_frame_offset_ms` and
`last_frame_offset_ms` using the same monotonic clock as recorder duration. Its
frozen policy is captured when recording starts. These offsets supplement the
existing wall timestamps, measured clock offset, causal first-frame/terminal
receipts, and maximum frame gap; none is a visual-review claim.

The independent bounded decoder now also reports `presentation_span_ms` (last PTS
minus first PTS), `presentation_extent_ms` (packet endpoint extent), and
`last_packet_duration_ms`. It continues checking every packet, corruption flags,
strictly increasing presentation timestamps, bounded gaps and the complete decoded
frame count. It never derives duration from nominal FPS.

For monotonic first/last frame offsets F and L, the accepted presentation span S
must satisfy `L - F - 2ms <= S <= L + 2ms`. This permits the measured initial-frame
interval, rather than an arbitrary extra duration tolerance. The declared final
packet duration must exactly account for extent minus span and stay within 250ms.
Both recorder-to-frame
endpoint gaps must be at most 250ms, wall/monotonic drift at most 5ms, and their wall
and monotonic timestamps must agree within measured drift plus 2ms quantization.
The 250ms endpoint SLA is a fixed admission cap, not additional duration slack.
Existing interruption, visibility, clock uncertainty and causal coverage guards
remain enforced. An interruption never becomes a valid capture through this rule.

Decoded frame count must equal the measured post-render count or exceed it by
exactly one initial canvas frame. Missing frames, additional unexplained frames,
packet-boundary truncation, late padding, missing offsets and changed policy
values fail closed. A renderer faster than the capture stream may violate this
strict accounting; investigate that separately rather than silently widening the
frame allowance.

`full_client_capture.verify_video_duration` is shared by offline runtime
collection and adaptive publication. `verify_capture_bundle` independently
recomputes the raw measurements under the protocol's policy. Publication still
requires native persistence and every model-cycle receipt, then independently
probes the exact hashed video. Failure to verify a recording leaves its video
unpublished; it does not manufacture or erase a separately verified native score.

## Acceptance before use

Freeze a new source/scenario and create a fresh attempt identity. A bounded future
capture must produce schema-2 offsets, the exact policy in its raw and derived
receipts, complete packet/frame accounting, and agreement under both runtime and
publication checks. Inspect the actual first/last frame endpoints and playback,
including first-input and terminal coverage. Preserve unsuccessful evidence for
diagnosis. Do not replay a previous API attempt or edit its frozen artifacts.

Tests use synthetic packet/capture fixtures, including a 117ms callback/decoded
extent difference inside a measured frame envelope. They do not create missing
monotonic measurements for a historical recording or claim native acceptance.
