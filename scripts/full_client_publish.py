"""Fail-closed ranked-publication gate for full-client evidence manifests.

This is a pure manifest validator, not a publisher or a score calculator. It does
not change the existing gallery schema/pipeline. Use a trusted evidence builder:
hashes, server origin, API receipts, capture integrity, and visual review are
attestations here, not independently authenticated by this tool. ``ready`` means
the manifest satisfies this evidence contract, not that its claims are proven.

Schema v1 (all fields required for ranked eligibility):
  schema_version: 1; run_kind: "ranked" ("integration" always fails the gate)
  result: the bridge's result.json object, including controller, program,
    initial/final ready client observations, api, programSha256, observedXpDelta,
    and timing {startedAtMs, endedAtMs, elapsedMs, apiLatencyMs}.
    controller: {id, adapter:"full-client", mode:"api", status:"completed",
      model, returnedModel}; api: {id, model, status:"completed", usage:
      {input_tokens, output_tokens, total_tokens}}. Extra metadata is retained
    by the builder but not emitted by this gate. Client XP is diagnostic only.
  budgets: {api_requests, output_tokens, total_tokens, program_ms, run_ms, actions}
    Positive integer limits, except actions may be zero. V1 records one API
    request; multiple-request runs require a future schema with every receipt.
  timeline: {status:"completed", api_started_ms, api_ended_ms,
    program_started_ms, program_ended_ms, client_observations_fresh:true,
    interrupted:false}. Offsets are monotonic milliseconds from run start.
  scenario: {id, fingerprint, reset_fingerprint}
  score: {source:"cosmic-server-events", run_id, scenario_fingerprint,
    reset_fingerprint, evidence_sha256, score_sha256, metrics:{name:number,...}}
    Hashes identify the complete server event evidence and scored artifact;
    neither score nor authoritative metrics may be copied from client telemetry.
  video: {path, sha256, status:"completed", start_ms, end_ms, duration_ms,
    interrupted:false, reviewed:true, overlay:{controller_id, mode:"api", model}}
    The video covers the entire program interval. API-planning footage is
    optional. The review attests that the overlay identifies the actual model.

All fingerprints/digests are lowercase 64-character SHA-256 hex strings. Video
path is a relative .mp4 artifact reference, never an absolute path or URL. This
validator does not read artifact files or decode video; the trusted builder must
verify the referenced bytes before supplying their hashes/review attestations.
Millisecond comparisons permit 100 ms of clock rounding/frame-boundary slack.
The clean ``program_complete`` requirement is a conservative prototype-only
transport contract, not a policy of publishing only winners. Zero XP is valid.
A future ranked trial runner must distinguish legitimate death/time/action-budget
outcomes from infrastructure interruption and accept fully evidenced outcomes.

Persisted-character scoring is deliberately unsupported in v1. A future
``cosmic_persisted_character`` contract must require verified logout/save,
unchanged level, numeric initial/final server stats, baseline parity, and net_xp
semantics including death penalties. It must not relabel client telemetry.

CLI: python3 scripts/full_client_publish.py MANIFEST.json
Prints only JSON {ready, reasons}; exits 0 if eligible, 1 if ineligible, 2 for
unreadable/invalid JSON. Integration evidence remains useful without being ranked.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path, PurePosixPath
import re


SHA256 = re.compile(r"[0-9a-f]{64}\Z")
KEYS = frozenset({"LEFT", "RIGHT", "UP", "DOWN", "JUMP", "ATTACK", "BRANDISH",
                  "COMBO", "BOOSTER", "MAPLE_WARRIOR", "HP_POTION", "MP_POTION"})
SLACK_MS = 100


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
    return type(value) is int and value >= minimum


def _hash(value):
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _video_path(value):
    if not _text(value) or any(c in value for c in (":", "\\", "\x00")):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and path.suffix == ".mp4"


def validate_manifest(manifest):
    """Return all actionable blockers without mutating or trusting client scores."""
    reasons = []

    def require(condition, reason):
        if not condition and reason not in reasons:
            reasons.append(reason)
        return condition

    if not isinstance(manifest, dict):
        return {"ready": False, "reasons": ["manifest: expected a JSON object."]}
    m = manifest
    require(type(m.get("schema_version")) is int and m["schema_version"] == 1,
            "schema_version: use the supported manifest version 1.")
    require(m.get("run_kind") == "ranked",
            "run_kind: integration/manual smoke runs are ineligible for ranked publication; "
            "collect a reproducible scored benchmark run.")
    result = _object(m.get("result"))
    source = result.get("source")
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
    require(program.get("reason") == "program_complete" and program.get("error") in (None, ""),
            "result.program: require clean program_complete, not timeout, interruption, or failure.")

    def observation(value):
        obs = _object(value)
        char = _object(obs.get("character"))
        return (obs.get("ready") is True and bool(char)
                and ("ageMs" not in obs or (_number(obs["ageMs"]) and obs["ageMs"] < 1500)))

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
            require(observation(receipt.get("observation")), f"{prefix}: input receipt needs a fresh observation.")
        elif method == "observe":
            require(observation(receipt), f"{prefix}: observation was stale, missing, or not ready.")
        else:
            require(_number(receipt.get("waitedMs")) and receipt["waitedMs"] <= 3000,
                    f"{prefix}: preserve a valid completed wait receipt.")
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
        if valid_timing:
            require(d <= timing["elapsedMs"] + SLACK_MS and abs(b - a - timing["apiLatencyMs"]) <= SLACK_MS,
                    "timeline: offsets disagree with recorded elapsed time or API latency.")
        if _integer(budgets.get("program_ms")):
            require(d - c <= budgets["program_ms"] + SLACK_MS, "budgets.program_ms: program exceeded its limit.")

    require(_text(scenario.get("id")) and _hash(scenario.get("fingerprint")),
            "scenario: record the reproducible scenario ID and SHA-256 fingerprint.")
    require(_hash(scenario.get("reset_fingerprint")),
            "scenario.reset_fingerprint: supply verified initial reset parity, not an uncontrolled integration state.")
    require(score.get("source") == "cosmic-server-events",
            "score.source: supply server-authoritative cosmic-server-events scoring; client XP is ineligible.")
    require(_text(score.get("run_id")) and score.get("run_id") == controller.get("id"),
            "score.run_id: bind server scoring evidence to this controller run.")
    for key, target in (("scenario_fingerprint", "fingerprint"), ("reset_fingerprint", "reset_fingerprint")):
        require(_hash(score.get(key)) and score.get(key) == scenario.get(target),
                f"score.{key}: server evidence must match the declared scenario/reset.")
    for key in ("evidence_sha256", "score_sha256"):
        require(_hash(score.get(key)), f"score.{key}: hash the authoritative evidence/scored artifact.")
    metrics = score.get("metrics")
    require(isinstance(metrics, dict) and bool(metrics)
            and all(_text(k) and _number(v, -math.inf) for k, v in metrics.items()),
            "score.metrics: supply finite numeric server metrics; do not promote observedXpDelta.")

    require(_video_path(video.get("path")) and _hash(video.get("sha256")),
            "video: supply a relative .mp4 artifact path and its SHA-256 digest.")
    require(video.get("status") == "completed" and video.get("interrupted") is False,
            "video: require a completed, uninterrupted capture, not a partial or failed recording.")
    require(video.get("reviewed") is True, "video.reviewed: visually review the exact hashed video and model overlay.")
    require(overlay.get("controller_id") == controller.get("id") and _text(overlay.get("controller_id"))
            and overlay.get("mode") == controller.get("mode") == "api"
            and overlay.get("model") == controller.get("model") == api.get("model") and _text(overlay.get("model")),
            "video.overlay: reviewed overlay must identify this run's actual API controller/model.")
    valid_video_times = all(_number(video.get(key)) for key in ("start_ms", "end_ms", "duration_ms"))
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
            require(end <= timing["elapsedMs"] + SLACK_MS, "video: capture end lies outside the recorded run timeline.")
    return {"ready": not reasons, "reasons": reasons}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate a full-client ranked-publication evidence manifest.")
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.manifest.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("oversized manifest")
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError, RecursionError):
        print(json.dumps({"ready": False, "reasons": ["manifest: provide readable valid JSON (at most 16 MiB)."]}))
        return 2
    verdict = validate_manifest(manifest)
    print(json.dumps(verdict, allow_nan=False))
    return 0 if verdict["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
