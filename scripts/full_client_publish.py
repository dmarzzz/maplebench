"""Verify full-client publication evidence without publishing or changing state.

Schema 1 remains a structural legacy contract and never returns ranked-ready.
Schema 2 requires actual contained artifact files, recomputed persisted net XP,
normal-reset/session/native-save evidence, a complete provider request/response,
exact executed program bytes, and the complete post-render recording with a
matching review. The validator independently hashes files and probes video with
ffprobe. Integration runs always remain ineligible.

The trusted collector and native server remain the provenance boundary. Matching
hashes, JSON receipts, and a visual-review record establish consistency; they do
not cryptographically authenticate a dishonest collector or replace human review.
The artifact directory must remain immutable during verification. No credentials,
database contents, event payloads, or private paths are emitted in verdicts.

See docs/FULL_CLIENT_TRIALS.md for versioned record and artifact shapes.
CLI: python3 scripts/full_client_publish.py MANIFEST.json --artifact-root BUNDLE
Exit 0 means the complete evidence contract passed; 1 means missing/inconsistent
required evidence; 2 means unreadable or invalid manifest JSON. This tool never
uploads anything or changes repository visibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

from full_client_score import (EvidenceError, SOURCE, JSON_LIMIT, parse_json,
                               open_verified_artifact, read_artifact_bytes, read_json_artifact,
                               same_json, verified_artifact, verify_trial_bundle)


SHA256 = re.compile(r"[0-9a-f]{64}\Z")
KEYS = frozenset({"LEFT", "RIGHT", "UP", "DOWN", "JUMP", "ATTACK", "BRANDISH",
                  "COMBO", "BOOSTER", "MAPLE_WARRIOR", "HP_POTION", "MP_POTION"})
SLACK_MS = 100
CAPTURE_TAIL_MS = 2000
CAPTURE_UNCERTAINTY_MS = 250
PROGRAM_FORMAT = {"type": "json_schema", "name": "maple_program", "strict": True,
                  "schema": {"type": "object", "additionalProperties": False,
                             "properties": {"note": {"type": "string"}, "code": {"type": "string"}},
                             "required": ["note", "code"]}}


def _object(value):
    return value if isinstance(value, dict) else {}


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 500


def _number(value, minimum=0):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= minimum
    except OverflowError:
        return False


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= 2**53 - 1


def _hash(value):
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _video_path(value, version=1):
    if not _text(value) or any(c in value for c in (":", "\\", "\x00")):
        return False
    path = PurePosixPath(value)
    return (not path.is_absolute() and ".." not in path.parts
            and path.suffix in ((".mp4", ".webm") if version == 2 else (".mp4",)))


def _validate_structure(manifest):
    """Return all actionable blockers without mutating or trusting client scores."""
    reasons = []

    def require(condition, reason):
        if not condition and reason not in reasons:
            reasons.append(reason)
        return condition

    if not isinstance(manifest, dict):
        return {"ready": False, "reasons": ["manifest: expected a JSON object."]}
    m = manifest
    version = m.get("schema_version")
    require(type(version) is int and version in (1, 2),
            "schema_version: use supported manifest version 1 or 2.")
    require(m.get("run_kind") == "ranked",
            "run_kind: integration/manual smoke runs are ineligible for ranked publication; "
            "collect a reproducible scored benchmark run.")
    result = _object(m.get("result"))
    source = result.get("source")
    if version == 2:
        require(source == "full-client-trial", "result.source: require a collected full-client-trial result.")
    require(not isinstance(source, str) or not any(marker in source.lower() for marker in ("integration", "unscored")),
            "result.source: an unscored integration result cannot be relabeled as a ranked benchmark.")
    controller = _object(result.get("controller"))
    program = _object(result.get("program"))
    api = _object(result.get("api"))
    timing = _object(result.get("timing"))
    timeline = _object(m.get("timeline"))
    budgets = _object(m.get("budgets"))
    scenario = _object(m.get("scenario"))
    score = _object(m.get("score"))
    video = _object(m.get("video"))
    overlay = _object(video.get("overlay"))

    require(_text(controller.get("id")), "result.controller.id: supply the unique run ID.")
    require(controller.get("adapter") == "full-client", "result.controller.adapter: must be full-client.")
    require(controller.get("mode") == "api", "result.controller.mode: ranked v1 requires an API controller.")
    require(controller.get("status") == "completed", "result.controller.status: the run must be completed.")
    require(_text(controller.get("model")), "result.controller.model: record the requested API model.")
    require(_text(controller.get("returnedModel")) and controller.get("returnedModel") == controller.get("model"),
            "result.controller.returnedModel: record and match the API-returned model.")
    require(_hash(result.get("programSha256")), "result.programSha256: hash the executed program.")
    outcomes = ("program_complete", "death", "time_limit", "action_limit") if version == 2 else ("program_complete",)
    require(program.get("reason") in outcomes and program.get("error") in (None, ""),
            "result.program: require clean program_complete, not timeout, interruption, or failure.")

    def observation(value):
        obs = _object(value)
        char = _object(obs.get("character"))
        return (obs.get("ready") is True and bool(char)
                and ("ageMs" not in obs or (_number(obs["ageMs"]) and obs["ageMs"] < 1500))
                and (version != 2 or all(_number(obs.get(key)) and obs[key] < 1500
                                         for key in ("ageMs", "renderAgeMs"))))

    for name in ("initial", "final"):
        require(observation(result.get(name)), f"result.{name}: record a ready, fresh client observation.")
    initial = _object(_object(result.get("initial")).get("character"))
    final = _object(_object(result.get("final")).get("character"))
    require(_number(initial.get("exp")) and _number(final.get("exp"))
            and _number(result.get("observedXpDelta"), -math.inf)
            and result.get("observedXpDelta") == final.get("exp", 0) - initial.get("exp", 0),
            "result.observedXpDelta: match final minus initial client XP; keep it diagnostic, not a server score.")

    steps = program.get("steps")
    require(isinstance(steps, list), "result.program.steps: preserve the complete SDK receipt list.")
    action_count = 0
    held_ms = 0
    for index, raw in enumerate(steps if isinstance(steps, list) else []):
        step = _object(raw)
        receipt = _object(step.get("result"))
        method = step.get("method")
        prefix = f"result.program.steps[{index}]"
        if not require(step.get("kind") == "sdk" and method in ("pressKeys", "observe", "wait"),
                       f"{prefix}: reject invalid/rejected RPCs and preserve only supported SDK receipts."):
            continue
        require(receipt.get("error") in (None, ""), f"{prefix}: SDK receipt reports an error.")
        if method == "pressKeys":
            action_count += 1
            require(receipt.get("accepted") is True,
                    f"{prefix}: input must be fully acknowledged; interrupted or partial holds are ineligible.")
            args = step.get("args")
            valid_args = isinstance(args, list) and len(args) == 2
            if valid_args:
                keys, duration = args
                valid_args = (isinstance(keys, list) and 1 <= len(keys) <= 3
                              and all(isinstance(k, str) and k in KEYS for k in keys)
                              and len(set(keys)) == len(keys)
                              and not ({"LEFT", "RIGHT"} <= set(keys) or {"UP", "DOWN"} <= set(keys))
                              and _integer(duration, 30) and duration <= 1500)
            require(valid_args, f"{prefix}: preserve valid bounded key-hold arguments.")
            if valid_args:
                held_ms += args[1]
            require(observation(receipt.get("observation")), f"{prefix}: input receipt needs a fresh observation.")
        elif method == "observe":
            require(step.get("args") == [], f"{prefix}: observe takes no arguments.")
            require(observation(receipt), f"{prefix}: observation was stale, missing, or not ready.")
        else:
            args = step.get("args")
            valid_wait = (isinstance(args, list) and len(args) == 1 and _integer(args[0], 1) and args[0] <= 3000
                          and _number(receipt.get("waitedMs")) and receipt["waitedMs"] <= args[0])
            require(valid_wait and (receipt["waitedMs"] == args[0]
                    or version == 2 and program.get("reason") == "time_limit" and index == len(steps) - 1),
                    f"{prefix}: preserve a valid completed wait receipt.")
            if valid_wait:
                held_ms += receipt["waitedMs"]
    require(_integer(program.get("actions")) and program.get("actions") == action_count,
            "result.program.actions: count must match the complete input receipt list.")

    require(_text(api.get("id")) and api.get("status") == "completed",
            "result.api: preserve the completed API response ID and status.")
    require(_text(api.get("model")) and api.get("model") == controller.get("model") == controller.get("returnedModel"),
            "result.api.model: requested, returned controller, and API receipt models must agree.")
    usage = _object(api.get("usage"))
    valid_usage = all(_integer(usage.get(key)) for key in ("input_tokens", "output_tokens", "total_tokens"))
    require(valid_usage and usage.get("total_tokens") == usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            "result.api.usage: record consistent input/output/total token counts.")
    for key in ("api_requests", "output_tokens", "total_tokens", "program_ms", "run_ms", "actions"):
        require(_integer(budgets.get(key), 0 if key == "actions" else 1),
                f"budgets.{key}: supply the explicit integer run limit.")
    if version == 2:
        require(type(budgets.get("api_requests")) is int and budgets["api_requests"] == 1,
                "budgets.api_requests: version 2 binds exactly one provider request per trial.")
        require(_integer(budgets.get("sdk_requests"), 1)
                and isinstance(steps, list) and len(steps) <= budgets["sdk_requests"],
                "budgets.sdk_requests: preserve and enforce the frozen SDK request limit.")
    for key in ("output_tokens", "total_tokens"):
        if _integer(usage.get(key)) and _integer(budgets.get(key)):
            require(usage[key] <= budgets[key], f"budgets.{key}: recorded API usage exceeded the limit.")
    if _integer(budgets.get("actions")):
        require(action_count <= budgets["actions"], "budgets.actions: acknowledged input count exceeded the limit.")

    require(timeline.get("status") == "completed", "timeline.status: record a completed capture/run timeline.")
    require(timeline.get("interrupted") is False, "timeline.interrupted: attest no client/run interruption.")
    require(timeline.get("client_observations_fresh") is True,
            "timeline.client_observations_fresh: verify client freshness throughout the run.")
    timing_keys = ("startedAtMs", "endedAtMs", "elapsedMs", "apiLatencyMs")
    valid_timing = all(_number(timing.get(key)) for key in timing_keys)
    require(valid_timing, "result.timing: record finite wall timestamps and monotonic elapsed/API milliseconds.")
    if valid_timing:
        require(timing["endedAtMs"] >= timing["startedAtMs"] and timing["elapsedMs"] > 0
                and abs(timing["endedAtMs"] - timing["startedAtMs"] - timing["elapsedMs"]) <= SLACK_MS,
                "result.timing: wall duration and monotonic elapsed time disagree.")
        if _integer(budgets.get("run_ms")):
            require(timing["elapsedMs"] <= budgets["run_ms"] + SLACK_MS, "budgets.run_ms: run exceeded its limit.")
    offsets = ("api_started_ms", "api_ended_ms", "program_started_ms", "program_ended_ms")
    valid_offsets = all(_number(timeline.get(key)) for key in offsets)
    require(valid_offsets, "timeline: record API and program start/end offsets from run start.")
    if valid_offsets:
        a, b, c, d = (timeline[key] for key in offsets)
        require(a <= b <= c < d, "timeline: API/program intervals are reversed, overlapping, or empty.")
        require(held_ms <= d - c + SLACK_MS,
                "timeline: acknowledged sequential key holds and waits exceed program duration.")
        if valid_timing:
            require(d <= timing["elapsedMs"] + SLACK_MS and abs(b - a - timing["apiLatencyMs"]) <= SLACK_MS,
                    "timeline: offsets disagree with recorded elapsed time or API latency.")
        if _integer(budgets.get("program_ms")):
            require(d - c <= budgets["program_ms"] + SLACK_MS, "budgets.program_ms: program exceeded its limit.")

    require(_text(scenario.get("id")) and _hash(scenario.get("fingerprint")),
            "scenario: record the reproducible scenario ID and SHA-256 fingerprint.")
    require(_hash(scenario.get("reset_fingerprint")),
            "scenario.reset_fingerprint: supply verified initial reset parity, not an uncontrolled integration state.")
    require(score.get("source") == (SOURCE if version == 2 else "cosmic-server-events"),
            "score.source: supply server-authoritative cosmic-server-events scoring; client XP is ineligible.")
    require(_text(score.get("run_id")) and score.get("run_id") == controller.get("id"),
            "score.run_id: bind server scoring evidence to this controller run.")
    for key, target in (("scenario_fingerprint", "fingerprint"),
                        ("baseline_sha256" if version == 2 else "reset_fingerprint", "reset_fingerprint")):
        require(_hash(score.get(key)) and score.get(key) == scenario.get(target),
                f"score.{key}: server evidence must match the declared scenario/reset.")
    for key in (("evidence_sha256",) if version == 2 else ("evidence_sha256", "score_sha256")):
        require(_hash(score.get(key)), f"score.{key}: hash the authoritative evidence/scored artifact.")
    metrics = score.get("metrics")
    require(isinstance(metrics, dict) and bool(metrics)
            and all(_text(k) and _number(v, -math.inf) for k, v in metrics.items()),
            "score.metrics: supply finite numeric server metrics; do not promote observedXpDelta.")

    require(_video_path(video.get("path"), version) and _hash(video.get("sha256")),
            "video: supply a relative .mp4 artifact path and its SHA-256 digest.")
    require(video.get("status") == "completed" and video.get("interrupted") is False,
            "video: require a completed, uninterrupted capture, not a partial or failed recording.")
    require(video.get("reviewed") is True, "video.reviewed: visually review the exact hashed video and model overlay.")
    require(overlay.get("controller_id") == controller.get("id") and _text(overlay.get("controller_id"))
            and overlay.get("mode") == controller.get("mode") == "api"
            and overlay.get("model") == controller.get("model") == api.get("model") and _text(overlay.get("model")),
            "video.overlay: reviewed overlay must identify this run's actual API controller/model.")
    valid_video_times = (all(_number(video.get(key)) for key in ("end_ms", "duration_ms"))
                         and _number(video.get("start_ms"), -CAPTURE_UNCERTAINTY_MS if version == 2 else 0))
    require(valid_video_times, "video: record capture offsets and measured duration in milliseconds.")
    if valid_video_times:
        start, end, duration = (video[key] for key in ("start_ms", "end_ms", "duration_ms"))
        require(end > start and duration > 0 and abs(end - start - duration) <= SLACK_MS,
                "video: capture interval and measured duration disagree.")
        if valid_offsets:
            require(start <= timeline["program_started_ms"] + SLACK_MS
                    and end + SLACK_MS >= timeline["program_ended_ms"],
                    "video: capture must cover the complete program, not only a selected excerpt.")
        if valid_timing:
            require(end <= timing["elapsedMs"] + (CAPTURE_TAIL_MS if version == 2 else SLACK_MS),
                    "video: capture end lies outside the bounded recording tail.")
    return {"ready": not reasons, "reasons": reasons}


def _probe_video(path, expected_sha256):
    """Inspect the actual video stream under a bounded, read-only subprocess."""
    try:
        if os.name != "posix":
            raise EvidenceError("video: safe descriptor-based probing is unavailable on this host")
        reference = {"path": path.name, "sha256": expected_sha256}
        with open_verified_artifact(path.parent, reference, "video", 1024**3) as stream:
            fd = stream.fileno()
            descriptor_path = ("/proc/self/fd/" if sys.platform.startswith("linux") else "/dev/fd/") + str(fd)
            try:
                process = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                     "-show_entries", "stream=width,height,nb_read_frames,duration:format=duration",
                     "-of", "json", descriptor_path], stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
                    check=False, pass_fds=(fd,))
            except (OSError, subprocess.TimeoutExpired) as error:
                raise EvidenceError("video: ffprobe unavailable or timed out") from error
        if process.returncode != 0 or len(process.stdout) > JSON_LIMIT:
            raise EvidenceError("video: actual recording could not be probed")
        probe = parse_json(process.stdout)
        stream = probe["streams"][0]
        duration = float(probe.get("format", {}).get("duration", stream.get("duration"))) * 1000
        width, height, frames = (int(stream[key]) for key in ("width", "height", "nb_read_frames"))
        if not _number(duration, 1) or min(width, height, frames) <= 0:
            raise EvidenceError("video: require a nonempty measurable video stream")
        return {"width": width, "height": height, "frames": frames, "duration_ms": duration}
    except EvidenceError:
        raise
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError, IndexError) as error:
        raise EvidenceError("video: ffprobe unavailable, timed out, or rejected the recording") from error


def _verify_persisted_manifest(manifest, artifact_root):
    def require(condition, reason):
        if not condition:
            raise EvidenceError(reason)

    artifacts = manifest.get("artifacts")
    require(isinstance(artifacts, dict), "artifacts: provide a complete private evidence bundle")
    evidence = read_json_artifact(artifact_root, artifacts, "persistence")
    score = verify_trial_bundle(evidence, artifact_root, artifacts)
    require(same_json(score, manifest["score"])
            and same_json(score, read_json_artifact(artifact_root, artifacts, "score")),
            "score: supplied score differs from recomputed verified persistence score")
    result = manifest["result"]
    require(same_json(read_json_artifact(artifact_root, artifacts, "result"), result),
            "artifacts.result: complete result artifact differs from manifest")
    scenario = read_json_artifact(artifact_root, artifacts, "scenario")
    require(isinstance(scenario, dict) and scenario.get("id") == manifest["scenario"]["id"],
            "artifacts.scenario: frozen scenario ID differs from manifest")
    require(same_json(scenario.get("budgets"), manifest["budgets"]),
            "budgets: limits must match the scenario frozen before the trial")
    require(same_json(result.get("timeline"), manifest["timeline"]),
            "timeline: preserve the timeline recorded in the result artifact")
    session = evidence["session"]
    started = result["timing"]["startedAtMs"]
    for offset, timestamp in (("api_started_ms", "api_started_at_ms"), ("api_ended_ms", "api_ended_at_ms"),
                              ("program_started_ms", "controller_started_at_ms"),
                              ("program_ended_ms", "controller_ended_at_ms")):
        require(abs(started + manifest["timeline"][offset] - session[timestamp]) <= SLACK_MS,
                "timeline: controller result and persisted session clocks disagree")
    require(session["login_at_ms"] <= started
            and result["timing"]["endedAtMs"] <= session["disconnect_requested_at_ms"],
            "timeline: result must lie inside the ordinary connected session")

    request = read_json_artifact(artifact_root, artifacts, "api_request")
    response = read_json_artifact(artifact_root, artifacts, "api_response")
    model = result["controller"]["model"]
    run_id = result["controller"]["id"]
    require(isinstance(request, dict) and request.get("model") == model
            and _object(request.get("metadata")).get("maplebench_run_id") == run_id,
            "api_request: bind the actual model request to this run")
    require(set(request) == {"model", "store", "reasoning", "instructions", "input",
                             "max_output_tokens", "text", "metadata"},
            "api_request: require the complete supported program-request body")
    require(request.get("store") is False
            and same_json(request.get("text"), {"format": PROGRAM_FORMAT}),
            "api_request: require store false and the exact strict program-output schema")
    require(same_json(request.get("reasoning"), scenario.get("reasoning"))
            and isinstance(request.get("reasoning"), dict)
            and set(request["reasoning"]) == {"effort"}
            and request["reasoning"]["effort"] in ("low", "medium", "high", "xhigh", "max", "ultra"),
            "api_request: reasoning effort must match the frozen scenario")
    instructions = request.get("instructions")
    require(isinstance(instructions, str) and 0 < len(instructions) <= 32000
            and _hash(scenario.get("instructions_sha256"))
            and hashlib.sha256(instructions.encode("utf-8")).hexdigest() == scenario["instructions_sha256"],
            "api_request: formatted instructions differ from the frozen scenario")
    require(isinstance(request.get("input"), str)
            and same_json(parse_json(request["input"]), {"observation": result["initial"]}),
            "api_request: actual input must contain exactly the recorded initial observation")
    require(_integer(request.get("max_output_tokens"), 1)
            and request["max_output_tokens"] <= manifest["budgets"]["output_tokens"],
            "api_request: requested output limit exceeds the frozen budget")
    require(isinstance(response, dict), "api_response: require the full provider response")
    require(all(same_json(response.get(key), result["api"].get(key)) for key in ("id", "status", "model", "usage")),
            "api_response: provider metadata differs from recorded result")
    require(_object(response.get("metadata")).get("maplebench_run_id") == run_id,
            "api_response: response metadata does not identify this run")
    output = response.get("output")
    require(isinstance(output, list), "api_response: preserve provider output, not only token metadata")
    text_parts = []
    for item in output:
        require(isinstance(item, dict), "api_response: invalid output envelope")
        if item.get("type") == "message":
            content = item.get("content")
            require(isinstance(content, list), "api_response: missing output content")
            for part in content:
                require(isinstance(part, dict), "api_response: invalid content envelope")
                if part.get("type") == "output_text":
                    require(isinstance(part.get("text"), str), "api_response: invalid program text")
                    text_parts.append(part["text"])
    choice = parse_json("".join(text_parts))
    require(isinstance(choice, dict) and set(choice) == {"note", "code"}
            and isinstance(choice.get("note"), str) and len(choice["note"]) <= 2000
            and isinstance(choice.get("code"), str) and 0 < len(choice["code"]) <= 12000,
            "api_response: missing bounded generated program")
    program_bytes = read_artifact_bytes(artifact_root, artifacts.get("program"), "program", 64 * 1024)
    require(program_bytes == choice["code"].encode("utf-8")
            and artifacts["program"]["sha256"] == result["programSha256"],
            "program: executed bytes differ from provider output or recorded hash")

    # Every terminal outcome is publishable when it is evidenced; low XP and
    # death are not infrastructure failures and must not be filtered away.
    reason = result["program"]["reason"]
    if reason == "death":
        require(evidence["final"]["character"]["hp"] == 0
                and result["final"]["character"].get("alive") is False,
                "outcome: death requires persisted zero HP and a dead final client observation")
    if reason == "action_limit":
        require(result["program"]["actions"] == manifest["budgets"]["actions"],
                "outcome: action_limit requires exhaustion of the frozen action budget")
    if reason == "time_limit":
        duration = manifest["timeline"]["program_ended_ms"] - manifest["timeline"]["program_started_ms"]
        require(abs(duration - manifest["budgets"]["program_ms"]) <= SLACK_MS,
                "outcome: time_limit requires exhaustion of the frozen program budget")

    verify_capture_bundle(manifest, artifact_root)

    video = manifest["video"]
    video_path = verified_artifact(artifact_root, artifacts.get("video"), "video", 1024**3)
    require(artifacts["video"] == {"path": video["path"], "sha256": video["sha256"]},
            "video: manifest does not reference the verified recording")
    measured = _probe_video(video_path, video["sha256"])
    probe = read_json_artifact(artifact_root, artifacts, "video_probe")
    require(isinstance(probe, dict) and probe.get("video_sha256") == video["sha256"]
            and all(probe.get(key) == measured[key] for key in ("width", "height", "frames"))
            and _number(probe.get("duration_ms"))
            and abs(probe["duration_ms"] - measured["duration_ms"]) <= SLACK_MS
            and abs(video["duration_ms"] - measured["duration_ms"]) <= SLACK_MS,
            "video_probe: saved probe and manifest disagree with actual recording")
    review = read_json_artifact(artifact_root, artifacts, "video_review")
    require(isinstance(review, dict) and review.get("video_sha256") == video["sha256"]
            and review.get("run_id") == run_id and review.get("overlay") == video["overlay"]
            and review.get("reviewed") is True and review.get("post_render_capture") is True,
            "video_review: require review of this exact recording, model overlay, and post-render capture")
    require(type(review.get("reviewed_at_ms")) is int
            and review["reviewed_at_ms"] >= result["timing"]["endedAtMs"],
            "video_review: review must follow the completed run")


def verify_capture_bundle(manifest, artifact_root):
    """Recompute measured capture timing and conservative full-run coverage.

    Browser telemetry is collector evidence, not a visual review. Server-issued
    clock/ready/terminal artifacts bind causal order without equating host clocks.
    """
    from full_client_capture import capture_receipt
    def require(condition, reason):
        if not condition:
            raise EvidenceError(reason)
    artifacts, result, video = manifest["artifacts"], manifest["result"], manifest["video"]
    capture = read_json_artifact(artifact_root, artifacts, "capture")
    ready = read_json_artifact(artifact_root, artifacts, "capture_ready")
    clock = read_json_artifact(artifact_root, artifacts, "capture_clock")
    terminal = read_json_artifact(artifact_root, artifacts, "capture_terminal")
    recording = read_json_artifact(artifact_root, artifacts, "recording")
    run_id, started = result["controller"]["id"], result["timing"]["startedAtMs"]
    require(isinstance(recording, dict) and recording.get("capture_sha256") == artifacts["capture"]["sha256"]
            and recording.get("sha256") == video["sha256"]
            and same_json({key: value for key, value in recording.items() if key != "reviewed"},
                          {key: value for key, value in video.items() if key != "reviewed"}),
            "capture: recording and capture hashes or measured metadata differ")
    require(isinstance(ready, dict) and set(ready) == {"runId", "serverReceivedAtMs", "renderedFrames"}
            and ready["runId"] == run_id and _integer(ready["renderedFrames"], 1)
            and _number(ready["serverReceivedAtMs"]), "capture: invalid server first-frame receipt")
    require(isinstance(clock, dict) and set(clock) == {"id", "client_sent_ms", "server_received_ms", "server_sent_ms"}
            and _text(clock["id"]) and all(_number(clock[key]) for key in set(clock) - {"id"})
            and started <= clock["server_received_ms"] <= clock["server_sent_ms"],
            "capture: invalid issued clock sample")
    require(isinstance(terminal, dict) and set(terminal) == {"id", "serverIssuedAtMs"}
            and _text(terminal["id"]) and _number(terminal["serverIssuedAtMs"]),
            "capture: invalid terminal server receipt")
    require(_text(result["controller"].get("client")), "capture: controller renderer identity missing")
    try:
        measured = capture_receipt(capture, {"id": run_id, "client": result["controller"]["client"],
                                             "startedAtMs": started}, ready, clock, terminal)
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise EvidenceError("capture: raw measurements failed validation") from error
    require(all(same_json(video.get(key), value) for key, value in measured.items()),
            "capture: recording fields differ from recomputed raw measurements")
    require(measured["interrupted"] is False and measured["post_render_capture"] is True
            and measured["rendered_frames"] >= ready["renderedFrames"]
            and _number(measured.get("timing_uncertainty_ms"))
            and measured["timing_uncertainty_ms"] <= CAPTURE_UNCERTAINTY_MS,
            "capture: require continuous post-render frames with bounded measured clock uncertainty")
    lower, upper = measured["clock_offset_ms"]["lower"], measured["clock_offset_ms"]["upper"]
    api_start = started + result["timeline"]["api_started_ms"]
    program_end = started + result["timeline"]["program_ended_ms"]
    ended = result["timing"]["endedAtMs"]
    require(started <= ready["serverReceivedAtMs"] <= api_start
            and capture["first_frame_wall_ms"] + upper <= api_start + SLACK_MS,
            "capture: recording must begin before the API planning interval")
    require(ended <= terminal["serverIssuedAtMs"]
            and capture["last_frame_wall_ms"] + lower >= program_end - SLACK_MS
            and capture["end_wall_ms"] + lower >= terminal["serverIssuedAtMs"] - SLACK_MS
            and capture["end_wall_ms"] + upper <= ended + CAPTURE_TAIL_MS,
            "capture: terminal receipt and conservative bounds must cover the program with a bounded tail")
    return measured


def validate_manifest(manifest, artifact_root=None):
    """A ranked-ready verdict requires schema 2 and verified artifact bytes."""
    verdict = _validate_structure(manifest)
    if not verdict["ready"]:
        return verdict
    if manifest["schema_version"] != 2:
        return {"ready": False, "reasons": ["schema_version: v1 attestations are structural only; "
                "use version 2 with verified persisted-trial artifacts for ranked publication."]}
    if artifact_root is None:
        return {"ready": False, "reasons": ["artifacts: supply the private artifact root for byte verification."]}
    try:
        _verify_persisted_manifest(manifest, artifact_root)
    except EvidenceError as error:
        return {"ready": False, "reasons": [str(error)]}
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return {"ready": False, "reasons": ["artifacts: incomplete, unreadable, or inconsistent evidence bundle."]}
    return {"ready": True, "reasons": []}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate a full-client ranked-publication evidence manifest.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.manifest.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("oversized manifest")
        manifest = parse_json(args.manifest.read_bytes())
    except (OSError, ValueError, UnicodeError, RecursionError):
        print(json.dumps({"ready": False, "reasons": ["manifest: provide readable valid JSON (at most 16 MiB)."]}))
        return 2
    verdict = validate_manifest(manifest, args.artifact_root)
    print(json.dumps(verdict, allow_nan=False))
    return 0 if verdict["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
