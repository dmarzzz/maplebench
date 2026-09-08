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
import resource
import subprocess
import sys
import tempfile

from full_client_score import (EvidenceError, SOURCE, JSON_LIMIT, parse_json,
                               open_verified_artifact, read_artifact_bytes, read_json_artifact,
                               same_json, verified_artifact, verify_trial_bundle)
from full_client_docker import DockerBindingError, validate_binding


SHA256 = re.compile(r"[0-9a-f]{64}\Z")
KEYS = frozenset({"LEFT", "RIGHT", "UP", "DOWN", "JUMP", "ATTACK", "BRANDISH",
                  "COMBO", "BOOSTER", "MAPLE_WARRIOR", "HP_POTION", "MP_POTION"})
SLACK_MS = 100
CAPTURE_TAIL_MS = 2000
CAPTURE_UNCERTAINTY_MS = 250
VIDEO_MAX_MS = 125000
VIDEO_MAX_FRAMES = 100000
SETTLEMENT_POLICY = {"capture_tail_ms": 2000, "upload_after_program_ms": 5000,
                     "disconnect_after_program_ms": 5000, "logout_after_disconnect_ms": 5000}
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
            ("result.program: require a supported completed outcome without a program error."
             if version == 2 else
             "result.program: require clean program_complete, not timeout, interruption, or failure."))

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
    # Older receipts omit these counters. When recorded, they cannot contradict
    # the acknowledged inputs or hide an attempted input without a receipt.
    for section, key, label in ((program, "actionAttempts", "program.actionAttempts"),
                                (controller, "actions", "controller.actions")):
        if key in section:
            require(_integer(section[key]) and section[key] == action_count,
                    f"result.{label}: recorded count must match the complete acknowledged input receipt list.")

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
        program_seconds, controller_seconds = controller.get("programSeconds"), controller.get("controllerSeconds")
        require(type(program_seconds) is int and program_seconds in (22, 60)
                and type(controller_seconds) is int and controller_seconds == program_seconds + 2
                and budgets.get("program_ms") == program_seconds * 1000,
                "budgets.controller: require the recorded supported program and termination limits.")
        if _integer(budgets.get("program_ms"), 1):
            require(held_ms <= budgets["program_ms"],
                    "budgets.program_ms: acknowledged key holds and waits exceed the active program budget.")
    for key in ("output_tokens", "total_tokens"):
        if _integer(usage.get(key)) and _integer(budgets.get(key)):
            require(usage[key] <= budgets[key], f"budgets.{key}: recorded API usage exceeded the limit.")
    if _integer(budgets.get("actions")):
        require(action_count <= budgets["actions"], "budgets.actions: acknowledged input count exceeded the limit.")

    require(timeline.get("status") == "completed", "timeline.status: record a completed capture/run timeline.")
    if version != 2:
        require(timeline.get("interrupted") is False, "timeline.interrupted: attest no client/run interruption.")
        require(timeline.get("client_observations_fresh") is True,
                "timeline.client_observations_fresh: verify client freshness throughout the run.")
    # Version 2 derives these properties from every observation/acknowledgment
    # above and the byte-verified capture below, not synthetic timeline flags.
    timing_keys = ("startedAtMs", "endedAtMs", "elapsedMs", "apiLatencyMs")
    valid_timing = all(_number(timing.get(key)) for key in timing_keys)
    require(valid_timing, "result.timing: record finite wall timestamps and monotonic elapsed/API milliseconds.")
    if valid_timing:
        require(timing["endedAtMs"] >= timing["startedAtMs"] and timing["elapsedMs"] > 0
                and abs(timing["endedAtMs"] - timing["startedAtMs"] - timing["elapsedMs"]) <= SLACK_MS,
                "result.timing: wall duration and monotonic elapsed time disagree.")
        if _integer(budgets.get("run_ms")):
            require(timing["elapsedMs"] <= budgets["run_ms"] + (0 if version == 2 else SLACK_MS),
                    "budgets.run_ms: run exceeded its limit.")
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
        if version == 2:
            # The recorded interval includes executor/container termination.
            # Its declared allowance is independently bound to the frozen
            # scenario below; the active model-program limit remains unchanged.
            if _integer(controller.get("controllerSeconds"), 1):
                require(d - c <= controller["controllerSeconds"] * 1000,
                        "budgets.controller: controller exceeded its declared termination envelope.")
            if program.get("reason") == "time_limit" and _integer(budgets.get("program_ms")):
                require(d - c >= budgets["program_ms"],
                        "outcome: time_limit requires exhaustion of the active program budget.")
        elif _integer(budgets.get("program_ms")):
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


def _video_probe_limits():
    """Bound the independent decoder, including bytes produced before parsing."""
    for kind, requested in ((resource.RLIMIT_FSIZE, JSON_LIMIT),
                            (resource.RLIMIT_AS, 768 * 1024**2),
                            (resource.RLIMIT_CPU, 30)):
        _, hard = resource.getrlimit(kind)
        limit = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
        resource.setrlimit(kind, (limit, limit))


def _measure_video_probe(probe, *, maximum_ms=VIDEO_MAX_MS):
    """Measure actual presentation timestamps; never infer duration from FPS.

    MediaRecorder WebM often lacks a finalized Segment duration. The last video
    packet's presentation endpoint still measures the saved stream. When that
    packet has no declared duration, its presentation timestamp is a conservative
    endpoint; independent capture-duration comparison must still pass afterward.
    """
    def require(condition, reason):
        if not condition:
            raise EvidenceError(reason)
    require(type(maximum_ms) is int and maximum_ms in (VIDEO_MAX_MS, 335000),
            "video: unsupported protocol duration limit")
    require(isinstance(probe, dict) and isinstance(probe.get("streams"), list)
            and len(probe["streams"]) == 1, "video: require one selected decoded video stream")
    stream = probe["streams"][0]
    require(isinstance(stream, dict) and isinstance(probe.get("format", {}), dict),
            "video: invalid stream metadata")
    width, height, frames = (int(stream[key]) for key in ("width", "height", "nb_read_frames"))
    require(0 < width <= 8192 and 0 < height <= 8192 and width * height <= 32 * 1024**2
            and 0 < frames <= VIDEO_MAX_FRAMES, "video: decoded dimensions or frame count exceed limits")
    packets = probe.get("packets")
    # The supported recorder/container encodings carry one decoded video frame
    # per packet. Decoder drops or incomplete packet/frame accounting fail closed.
    require(isinstance(packets, list) and len(packets) == frames,
            "video: require complete bounded packet and decoded-frame accounting")
    presentations = []
    for packet in packets:
        require(isinstance(packet, dict) and isinstance(packet.get("flags"), str)
                and "C" not in packet["flags"] and "D" not in packet["flags"],
                "video: corrupt or discarded video packet")
        require(type(packet.get("pts_time")) in (str, int, float)
                and type(packet.get("duration_time")) in (str, int, float, type(None)),
                "video: invalid packet timestamp types")
        timestamp = float(packet["pts_time"]) * 1000
        raw_duration = packet.get("duration_time")
        duration = 0 if raw_duration in (None, "N/A") else float(raw_duration) * 1000
        require(_number(timestamp, -maximum_ms) and timestamp <= maximum_ms
                and _number(duration) and duration <= 1000,
                "video: invalid or out-of-bounds packet timestamps")
        presentations.append((timestamp, duration))
    presentations.sort()
    require(all(0 < later[0] - earlier[0] <= 1000
                for earlier, later in zip(presentations, presentations[1:])),
            "video: duplicate timestamps or excessive gaps in the saved stream")
    extent = max(timestamp + duration for timestamp, duration in presentations) - presentations[0][0]
    require(_number(extent, 1) and extent <= maximum_ms,
            "video: require a bounded nonempty presentation interval")
    headers = []
    for value in (probe.get("format", {}).get("duration"), stream.get("duration")):
        if value not in (None, "N/A"):
            header = float(value) * 1000
            require(_number(header, 1) and header <= maximum_ms and abs(header - extent) <= SLACK_MS,
                    "video: duration metadata disagrees with decoded packet coverage")
            headers.append(header)
    return {"width": width, "height": height, "frames": frames,
            "duration_ms": headers[0] if headers else extent}


def _probe_video(path, expected_sha256, *, maximum_ms=VIDEO_MAX_MS):
    """Inspect the actual video stream under a bounded, read-only subprocess."""
    try:
        if type(maximum_ms) is not int or maximum_ms not in (VIDEO_MAX_MS, 335000):
            raise EvidenceError("video: unsupported protocol duration limit")
        if os.name != "posix":
            raise EvidenceError("video: safe descriptor-based probing is unavailable on this host")
        reference = {"path": path.name, "sha256": expected_sha256}
        with open_verified_artifact(path.parent, reference, "video", 1024**3) as stream:
            fd = stream.fileno()
            descriptor_path = ("/proc/self/fd/" if sys.platform.startswith("linux") else "/dev/fd/") + str(fd)
            with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
                try:
                    process = subprocess.run(
                        ["ffprobe", "-v", "error", "-threads", "1", "-err_detect", "explode",
                         "-select_streams", "v:0", "-count_frames", "-show_packets",
                         "-show_entries", "packet=pts_time,duration_time,flags:stream=width,height,nb_read_frames,duration:format=duration",
                         "-of", "json", descriptor_path], stdin=subprocess.DEVNULL,
                        stdout=output, stderr=errors, timeout=30, check=False, pass_fds=(fd,),
                        preexec_fn=_video_probe_limits,
                        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
                except (OSError, subprocess.SubprocessError) as error:
                    raise EvidenceError("video: ffprobe unavailable or timed out") from error
                if process.returncode != 0 or not 0 < output.tell() < JSON_LIMIT or errors.tell() != 0:
                    raise EvidenceError("video: decoder failed, reported corruption, or exceeded output limits")
                output.seek(0)
                probe = parse_json(output.read(JSON_LIMIT + 1))
            measured = _measure_video_probe(probe, maximum_ms=maximum_ms)
        return measured
    except EvidenceError:
        raise
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError, IndexError, OverflowError) as error:
        raise EvidenceError("video: ffprobe unavailable, timed out, or rejected the recording") from error


def _verify_docker_execution(manifest, artifact_root):
    """Check receipt identity offline; never inspect this machine's Docker.

    Legacy bundles predate the execution binding and keep their original
    contract. New runtime manifests require the exact recorded binding.
    """
    controller = manifest["result"]["controller"]
    artifacts = manifest["artifacts"]
    runtime = (read_json_artifact(artifact_root, artifacts, "runtime_manifest")
               if "runtime_manifest" in artifacts else None)
    if not controller.get("dockerBinding") and (runtime is None or isinstance(runtime, dict)
            and type(runtime.get("schema_version")) is int and runtime["schema_version"] == 1):
        return
    try:
        if not isinstance(runtime, dict) or type(runtime.get("schema_version")) is not int or runtime["schema_version"] != 2:
            raise DockerBindingError("docker_binding_required")
        binding = validate_binding(runtime.get("docker_binding"), verify_files=False)
        if (not same_json(controller.get("dockerBinding"), binding)
                or controller.get("dockerImageId") != runtime.get("docker_image_id")
                or not isinstance(runtime.get("docker_image_id"), str)
                or not re.fullmatch("sha256:[0-9a-f]{64}", runtime["docker_image_id"])):
            raise DockerBindingError("docker_binding_mismatch")
    except DockerBindingError as error:
        raise EvidenceError("docker: frozen execution binding is missing, invalid or differs from the controller receipt") from error


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
    _verify_docker_execution(manifest, artifact_root)
    scenario = read_json_artifact(artifact_root, artifacts, "scenario")
    require(isinstance(scenario, dict) and scenario.get("id") == manifest["scenario"]["id"],
            "artifacts.scenario: frozen scenario ID differs from manifest")
    require(same_json(scenario.get("budgets"), manifest["budgets"]),
            "budgets: limits must match the scenario frozen before the trial")
    controller = result["controller"]
    require(type(scenario.get("program_seconds")) is int and scenario["program_seconds"] in (22, 60)
            and same_json(controller.get("programSeconds"), scenario["program_seconds"])
            and same_json(controller.get("controllerSeconds"),
                          _object(scenario.get("trial_budgets")).get("controller_seconds"))
            and controller["controllerSeconds"] == scenario["program_seconds"] + 2,
            "budgets.controller: recorded program/termination limits differ from the frozen scenario")
    trial_context = {"scenario_fingerprint": artifacts["scenario"]["sha256"],
                     "baseline_sha256": artifacts["baseline"]["sha256"]}
    require(same_json(result.get("trialContext"), trial_context)
            and same_json(controller.get("trialContext"), trial_context),
            "trialContext: recorded result and controller must bind the original frozen scenario and baseline")
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
    _verify_readiness_policy(manifest, artifact_root, evidence, scenario)
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
        require(manifest["budgets"]["program_ms"] <= duration
                <= scenario["trial_budgets"]["controller_seconds"] * 1000,
                "outcome: time_limit must exhaust the active program within the frozen controller envelope")

    verify_capture_bundle(manifest, artifact_root)
    _verify_settlement_policy(manifest, artifact_root, evidence, scenario)

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


def _verify_readiness_policy(manifest, artifact_root, evidence, scenario):
    """Enforce only a readiness policy frozen before this particular trial.

    Historical scenarios keep their original eligibility. New scenarios bind the
    pre-API receipt to saved capture identities and to the actual provider input;
    a fresh final frame cannot substitute for the required sustained window.
    """
    if "readiness_policy" not in scenario:
        return
    from full_client_readiness import ReadinessError, observation_matches, observation_sha256, validate_policy

    def require(condition, reason):
        if not condition:
            raise EvidenceError("readiness: " + reason)

    expected_map = _object(_object(evidence.get("baseline")).get("character")).get("map_id")
    require(_integer(expected_map), "persisted baseline must identify the expected map")
    try:
        policy = validate_policy(scenario["readiness_policy"], expected_map_id=expected_map)
    except (ReadinessError, TypeError, ValueError, OverflowError) as error:
        raise EvidenceError("readiness: frozen policy is missing, malformed, or differs from the baseline") from error
    artifacts, result = manifest["artifacts"], manifest["result"]
    receipt = read_json_artifact(artifact_root, artifacts, "readiness")
    require(isinstance(receipt, dict) and same_json(receipt, result.get("readiness"))
            and _hash(result.get("readinessSha256"))
            and artifacts["readiness"]["sha256"] == result["readinessSha256"],
            "result must bind the exact pre-API receipt bytes")
    fields = {"schema_version", "run_id", "client_id", "capture_clock_id", "capture_clock_client_received_ms", "capture_ready_at_ms",
              "policy", "wait_started_at_ms", "wait_started_run_ms", "qualified_at_ms", "qualified_run_ms",
              "samples", "initial_observation_sha256", "dispatch"}
    require(set(receipt) == fields and type(receipt.get("schema_version")) is int
            and receipt["schema_version"] == 1 and same_json(receipt.get("policy"), policy),
            "receipt schema or policy differs from the frozen scenario")
    capture = read_json_artifact(artifact_root, artifacts, "capture")
    ready = read_json_artifact(artifact_root, artifacts, "capture_ready")
    clock = read_json_artifact(artifact_root, artifacts, "capture_clock")
    controller = result["controller"]
    require(isinstance(capture, dict) and isinstance(ready, dict) and isinstance(clock, dict)
            and same_json(controller.get("readinessPolicy"), policy)
            and receipt["run_id"] == controller["id"] == capture.get("run_id") == ready.get("runId")
            and _text(receipt["client_id"]) and receipt["client_id"] == controller.get("client") == capture.get("client_id")
            and _text(receipt["capture_clock_id"]) and receipt["capture_clock_id"] == clock.get("id")
            and same_json(receipt["capture_ready_at_ms"], ready.get("serverReceivedAtMs")),
            "receipt belongs to a different run, renderer, or capture handshake")
    sync = _object(capture.get("clock"))
    require(_number(receipt["capture_clock_client_received_ms"])
            and same_json(receipt["capture_clock_client_received_ms"], sync.get("client_received_ms"))
            and all(same_json(sync.get(key), clock.get(key)) for key in
                    ("id", "client_sent_ms", "server_received_ms", "server_sent_ms"))
            and all(_number(clock.get(key)) for key in ("client_sent_ms", "server_received_ms", "server_sent_ms"))
            and clock["client_sent_ms"] <= receipt["capture_clock_client_received_ms"]
            and clock["server_received_ms"] <= clock["server_sent_ms"],
            "transit clock echo must match this capture's measured handshake")
    lower = clock["server_sent_ms"] - receipt["capture_clock_client_received_ms"]
    upper = clock["server_received_ms"] - clock["client_sent_ms"]
    require(0 <= upper - lower <= CAPTURE_UNCERTAINTY_MS * 2,
            "transit clock interval is inconsistent or too uncertain")
    timing_fields = ("capture_ready_at_ms", "wait_started_at_ms", "wait_started_run_ms",
                     "qualified_at_ms", "qualified_run_ms")
    require(all(_number(receipt[key]) for key in timing_fields), "receipt timestamps must be finite numbers")
    timeline, started = result["timeline"], result["timing"]["startedAtMs"]
    require(same_json(timeline.get("readiness_started_ms"), receipt["wait_started_run_ms"])
            and same_json(timeline.get("readiness_ended_ms"), receipt["qualified_run_ms"])
            and started <= receipt["capture_ready_at_ms"] <= receipt["wait_started_at_ms"] <= receipt["qualified_at_ms"]
            and 0 <= receipt["qualified_run_ms"] - receipt["wait_started_run_ms"] <= policy["timeout_ms"]
            and receipt["qualified_at_ms"] - receipt["wait_started_at_ms"] <= policy["timeout_ms"] + SLACK_MS,
            "qualification must follow capture readiness within the frozen timeout")
    expected_run_ms = 335000 if scenario.get("protocol") == "full-client-adaptive-pilot-v1" else (scenario["program_seconds"] + 63) * 1000
    require(manifest["budgets"].get("run_ms") == expected_run_ms,
            "future run budget must include only the frozen ten-second readiness allowance")
    for wall, elapsed in (("wait_started_at_ms", "wait_started_run_ms"), ("qualified_at_ms", "qualified_run_ms")):
        require(abs(receipt[wall] - started - receipt[elapsed]) <= SLACK_MS,
                "receipt wall and monotonic clocks disagree")
    samples = receipt["samples"]
    require(isinstance(samples, list) and policy["min_samples"] <= len(samples) <= 64,
            "preserve the complete bounded qualifying sample window")
    require(_integer(ready.get("renderedFrames"), 1) and _integer(capture.get("rendered_frames"), 1),
            "capture must provide measured post-render frame counters")
    sample_fields = {"rendered_frames", "server_received_at_ms", "run_elapsed_ms", "map_id", "alive",
                     "monster_count", "age_ms", "render_age_ms", "observation_sha256",
                     "frame_received_at_ms", "frame_received_run_ms", "client_sent_at_ms",
                     "reported_age_ms", "reported_render_age_ms", "transit_upper_ms", "server_residence_ms"}

    def sample(value, *, dispatch=False):
        clock_key = "checked_at_ms" if dispatch else "server_received_at_ms"
        expected_fields = (sample_fields - {"server_received_at_ms"}) | {clock_key}
        require(isinstance(value, dict) and set(value) == expected_fields,
                "sample has missing or unsupported fields")
        require(_integer(value.get("rendered_frames"), 1)
                and ready["renderedFrames"] <= value["rendered_frames"] <= capture["rendered_frames"]
                and _number(value.get(clock_key)) and _number(value.get("run_elapsed_ms"))
                and type(value.get("map_id")) is int and value["map_id"] == policy["expected_map_id"]
                and value.get("alive") is True and _integer(value.get("monster_count"), policy["min_monsters"])
                and all(_number(value.get(key)) and value[key] < 1500 for key in ("age_ms", "render_age_ms"))
                and _hash(value.get("observation_sha256")),
                "each sample must be a fresh living character on the expected populated map")
        require(abs(value[clock_key] - started - value["run_elapsed_ms"]) <= SLACK_MS,
                "sample wall and monotonic clocks disagree")
        transit_fields = ("frame_received_at_ms", "frame_received_run_ms", "client_sent_at_ms",
                          "reported_age_ms", "reported_render_age_ms", "transit_upper_ms", "server_residence_ms")
        require(all(_number(value.get(key)) for key in transit_fields)
                and receipt["capture_clock_client_received_ms"] <= value["client_sent_at_ms"]
                and receipt["capture_ready_at_ms"] <= value["frame_received_at_ms"] <= value[clock_key]
                and value["frame_received_run_ms"] <= value["run_elapsed_ms"]
                and abs(value["frame_received_at_ms"] - started - value["frame_received_run_ms"]) <= SLACK_MS,
                "transit measurements must follow the same capture and precede the sample")
        transit = value["frame_received_at_ms"] - (value["client_sent_at_ms"] + lower)
        require(transit >= 0 and abs(value["transit_upper_ms"] - transit) <= 0.000001,
                "transit upper bound must be recomputed from the measured clock interval")
        require(abs(value["server_residence_ms"] - value["run_elapsed_ms"] + value["frame_received_run_ms"]) <= 1,
                "server residence must agree with the frame and sample monotonic times")
        for adjusted, reported in (("age_ms", "reported_age_ms"), ("render_age_ms", "reported_render_age_ms")):
            require(abs(value[adjusted] - value[reported] - transit - value["server_residence_ms"]) <= 0.000001,
                    "freshness must include reported age, conservative transit, and server residence")

    for value in samples:
        sample(value)
        require(receipt["wait_started_run_ms"] <= value["run_elapsed_ms"] <= receipt["qualified_run_ms"]
                and receipt["wait_started_run_ms"] <= value["frame_received_run_ms"]
                and receipt["wait_started_at_ms"] <= value["server_received_at_ms"] <= receipt["qualified_at_ms"],
                "qualifying sample lies outside its recorded wait window")
    for previous, current in zip(samples, samples[1:]):
        require(current["rendered_frames"] > previous["rendered_frames"]
                and current["run_elapsed_ms"] >= previous["run_elapsed_ms"]
                and 0 <= current["frame_received_run_ms"] - previous["frame_received_run_ms"] < 1500
                and current["server_received_at_ms"] >= previous["server_received_at_ms"],
                "qualification needs distinct consecutive post-render samples without a stale gap")
    first, last = samples[0], samples[-1]
    require(last["frame_received_run_ms"] - first["frame_received_run_ms"] >= policy["min_span_ms"]
            and last["run_elapsed_ms"] <= receipt["qualified_run_ms"]
            and last["server_received_at_ms"] <= receipt["qualified_at_ms"],
            "qualification must follow the last sample after the frozen sustained interval")
    try:
        initial_valid = observation_matches(result["initial"], policy)
        initial_hash = observation_sha256(result["initial"])
    except (ReadinessError, TypeError, ValueError, OverflowError) as error:
        raise EvidenceError("readiness: invalid initial provider observation") from error
    require(initial_valid and receipt["initial_observation_sha256"] == last["observation_sha256"] == initial_hash
            and same_json(last["age_ms"], result["initial"].get("ageMs"))
            and same_json(last["render_age_ms"], result["initial"].get("renderAgeMs"))
            and last["monster_count"] == len(result["initial"]["monsters"]),
            "last qualifying sample must bind the actual initial provider observation")
    dispatch = receipt["dispatch"]
    sample(dispatch, dispatch=True)
    require(last["rendered_frames"] <= dispatch["rendered_frames"]
            and last["frame_received_run_ms"] <= dispatch["frame_received_run_ms"]
            and receipt["qualified_run_ms"] <= dispatch["run_elapsed_ms"] <= timeline["api_started_ms"]
            and timeline["api_started_ms"] - receipt["wait_started_run_ms"] <= policy["timeout_ms"]
            and all(last[key] + timeline["api_started_ms"] - last["run_elapsed_ms"] < 1500
                    for key in ("age_ms", "render_age_ms"))
            and receipt["qualified_at_ms"] <= dispatch["checked_at_ms"] <= started + timeline["api_started_ms"] + SLACK_MS,
            "fresh dispatch recheck must follow qualification and precede the API request")


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
                                             "startedAtMs": started, "protocol": result.get("protocol")}, ready, clock, terminal)
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


def _verify_settlement_policy(manifest, artifact_root, evidence, scenario):
    """Bind actual settled-upload observation and logout to the frozen cutoff."""
    def require(condition, reason):
        if not condition:
            raise EvidenceError(reason)
    require(same_json(scenario.get("settlement_policy"), SETTLEMENT_POLICY),
            "settlement: require the supported policy frozen before the trial")
    artifacts, session = manifest["artifacts"], evidence["session"]
    result = manifest["result"]
    receipt = read_json_artifact(artifact_root, artifacts, "upload_status")
    require(isinstance(receipt, dict) and set(receipt) == {"schema_version", "source", "run_id",
            "server_instance_id", "character_id", "account_id", "observed_at_ms", "status"}
            and type(receipt["schema_version"]) is int and receipt["schema_version"] == 1
            and receipt["source"] == "full_client_runtime_status", "settlement: invalid raw upload observation")
    identity = {"run_id": evidence["run_id"], "server_instance_id": session["server_instance_id"],
                "character_id": evidence["baseline"]["character"]["character_id"],
                "account_id": evidence["baseline"]["character"]["account_id"]}
    require(all(same_json(receipt.get(key), value) for key, value in identity.items()),
            "settlement: upload observation belongs to another trial or character")
    observed = session.get("upload_observed_at_ms")
    require(_integer(observed) and same_json(receipt["observed_at_ms"], observed),
            "settlement: session upload timestamp differs from the actual status observation")
    status = _object(receipt["status"])
    bridge = _object(status.get("bridge"))
    run = _object(bridge.get("run"))
    require(run.get("id") == evidence["run_id"] and run.get("status") == "completed"
            and run.get("evidenceStatus") == "saved" and run.get("recordingStatus") == "saved"
            and run.get("workerActive") is False and run.get("leaseReleasePending") is False
            and bridge.get("browserReleasePending") is False
            and _object(status.get("session")).get("artifactsSettled") is True,
            "settlement: raw status must prove this completed run and both settled uploads")
    program_end = result["timing"]["startedAtMs"] + result["timeline"]["program_ended_ms"]
    disconnect, logout = session["disconnect_requested_at_ms"], session["logged_out_at_ms"]
    require(program_end <= observed <= disconnect
            and observed - program_end <= SETTLEMENT_POLICY["upload_after_program_ms"]
            and disconnect - program_end <= SETTLEMENT_POLICY["disconnect_after_program_ms"]
            and disconnect <= logout <= disconnect + SETTLEMENT_POLICY["logout_after_disconnect_ms"],
            "settlement: upload/disconnect/logout exceeded the frozen post-program cutoff")
    capture = read_json_artifact(artifact_root, artifacts, "capture")
    require(capture["end_wall_ms"] + manifest["video"]["clock_offset_ms"]["upper"]
            <= program_end + SETTLEMENT_POLICY["capture_tail_ms"],
            "settlement: capture extended beyond the frozen post-program tail")


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
