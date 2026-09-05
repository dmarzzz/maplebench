"""Build a self-contained results gallery from a batch's real local artifacts.

No server, network request, browser dependency, or synthetic result is involved.
The runner owns trial state; this module only publishes a sanitized snapshot.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import html
import json
import math
import os
from pathlib import Path
import tempfile
from urllib.parse import quote


GAME_OUTCOMES = {"completed", "time_limit", "death", "decision_limit", "api_budget", "token_limit", "budget_limit", "action_limit"}
KNOWN_STATUSES = GAME_OUTCOMES | {
    "queued", "running", "rendering", "interrupted", "infrastructure_error", "cancelled", "failed", "budget_exhausted"
}
ARTIFACTS = {
    "score": "score.json", "trace": "episode.jsonl", "decisions": "decisions.json",
    "observations": "observations.json", "controller": "controller.json", "prompt": "prompt.txt",
    "steps": "steps.jsonl", "scenario": "scenario.json", "provenance": "provenance.json",
}


def _text(value, limit=1000):
    return str(value)[:limit] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def _dict(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _contained(root, value, *, base=None, directory=False):
    """Resolve symlinks and reject anything outside the batch, including URLs."""
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        return None
    raw = str(value)
    if "://" in raw or raw.startswith("//") or "\\" in raw or "\x00" in raw:
        return None
    try:
        path = Path(raw)
        path = path if path.is_absolute() else (base or root) / path
        path = path.resolve(strict=True)
        path.relative_to(root)
        if (directory and path.is_dir()) or (not directory and path.is_file()):
            return path
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def _url(root, path):
    return quote(path.relative_to(root).as_posix(), safe="/") if path else None


def _read_json(path, default=None):
    # A half-written or oversized artifact must not prevent queue publication.
    try:
        if path and path.stat().st_size <= 16 * 1024 * 1024:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        pass
    return default


def _pick_number(source, *names):
    for name in names:
        value = _number(source.get(name))
        if value is not None:
            return value
    return None


def _normalize_trial(root, batch, trial):
    trial = _dict(trial)
    attempt = _contained(root, trial.get("attempt_dir"), directory=True)
    files = {key: _contained(root, filename, base=attempt) if attempt else None
             for key, filename in ARTIFACTS.items()}
    score = _dict(_read_json(files["score"], {}))
    controller = _dict(_read_json(files["controller"], {}))
    decisions = _read_json(files["decisions"], [])
    if not isinstance(decisions, list):
        decisions = []
    responses = [_dict(_dict(decision).get("response")) for decision in decisions]
    provider_models = sorted({_text(response.get("model"), 200) for response in responses
                              if _text(response.get("model"), 200)})
    if not provider_models:
        returned_model = trial.get("provider_model") or controller.get("provider_model")
        provider_models = [_text(returned_model, 200)] if returned_model else []
    model = _text(trial.get("model") or controller.get("model") or score.get("model"), 200)

    metrics = {**score, **_dict(trial.get("metrics"))}
    duration = _pick_number(metrics, "duration_sec", "duration_seconds")
    if duration is None:
        milliseconds = _pick_number(metrics, "durationMs", "duration_ms")
        duration = milliseconds / 1000 if milliseconds is not None else None
    usage = metrics.get("apiUsage")
    if not isinstance(usage, list):
        usage = [_dict(response.get("usage")) for response in responses]
    totals = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        values = [_number(_dict(item).get(key)) for item in usage]
        values = [value for value in values if value is not None]
        totals[key] = _pick_number(metrics, key)
        if totals[key] is None and values:
            totals[key] = sum(values)

    status = _text(trial.get("status") or "queued", 80)
    reason = _text(trial.get("reason") or score.get("reason"), 300)
    outcome = reason if status == "completed" and reason in GAME_OUTCOMES else status
    if outcome not in KNOWN_STATUSES:
        outcome = "unknown"
    # A failed run is never silently classified as a gameplay defeat.
    if status in {"failed", "error"} or reason == "error":
        outcome = "infrastructure_error"

    video = _contained(root, trial.get("video_path"))
    if video is None and attempt and trial.get("video_path"):
        video = _contained(root, trial.get("video_path"), base=attempt)
    if video is None and attempt and not trial.get("video_path"):
        video = _contained(root, "video/henesys-overlay.mp4", base=attempt)
    if video and video.suffix.lower() != ".mp4":
        video = None
    poster = _contained(root, "video/poster.jpg", base=attempt) if attempt else None

    backend = _text(trial.get("backend") or batch.get("backend"), 100)
    markers = " ".join(_text(value).lower() for value in (
        trial.get("run_kind"), trial.get("backend"), controller.get("name"),
        controller.get("backend"), controller.get("inference"), batch.get("backend")))
    if trial.get("mock") or trial.get("dry_run") or "mock" in markers or "dry_run" in markers:
        provenance = "mock"
    elif backend == "cosmic-v83":
        provenance = "cosmic-v83"
    else:
        provenance = "unverified"
    return {
        "id": _text(trial.get("id"), 200), "model": model or "Unspecified model",
        "provider_models": provider_models,
        "scenario": _text(trial.get("scenario") or controller.get("scenario"), 200) or "Unspecified scenario",
        "repetition": _number(trial.get("repetition")),
        "attempt": _number(trial.get("attempt")), "status": status, "outcome": outcome,
        "reason": reason, "error": _text(trial.get("error") or score.get("error")),
        "render_status": _text(trial.get("render_status") or metrics.get("render_status"), 80),
        "render_error": _text(trial.get("render_error") or metrics.get("render_error")),
        "provenance": provenance,
        "metrics": {
            "duration_sec": duration,
            "xp_gained": _pick_number(metrics, "xp_gained", "xpGainedThisRun", "xp"),
            "hp": _pick_number(metrics, "hp", "finalHp", "final_hp"),
            "kills": _pick_number(metrics, "monstersKilled"),
            "damage_dealt": _pick_number(metrics, "damageDealt"),
            "incoming_damage": _pick_number(metrics, "incomingDamage"),
            "incoming_hits": _pick_number(metrics, "incomingHits"),
            "minimum_hp_percent": _pick_number(metrics, "minimumHpPercent"),
            "maximum_combo": _pick_number(metrics, "maximumComboOrbs"),
            "targets_per_attack": _pick_number(metrics, "averageTargetsPerAttack"),
            "buff_uptime": {str(key): value for key, value in _dict(metrics.get("buffUptimePercent")).items()
                            if str(key).isdigit() and _number(value) is not None and 0 <= value <= 100},
            "accepted": _pick_number(metrics, "accepted", "accepted_actions"),
            "rejected": _pick_number(metrics, "rejected", "rejected_actions"),
            "decisions": _pick_number(metrics, "decisions"), **totals,
        },
        "video_url": _url(root, video),
        "poster_url": _url(root, poster),
        "artifacts": {key: _url(root, path) for key, path in files.items() if path},
    }


def _atomic_write(path, content):
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build_gallery(batch_dir, batch_dict, trials_list):
    """Atomically publish index.html and summary.json; return the index Path.

    Paths may be absolute within batch_dir, or relative to it. video_path may
    alternatively be relative to attempt_dir. Unknown fields are not published.
    Every file link must resolve to an existing file contained in batch_dir.
    """
    root = Path(batch_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    batch = _dict(batch_dict)
    trials = []
    for trial in trials_list:
        trial = _dict(trial)
        history = trial.get("attempts")
        if isinstance(history, list) and trial.get("attempt_dir"):
            for previous in history:
                previous = _dict(previous)
                number = previous.get("number")
                if type(number) is not int or number < 1 or number == trial.get("attempt"):
                    continue
                historical = {**trial, "attempt": number, "status": previous.get("status"),
                              "reason": None if previous.get("status") == "completed" else previous.get("status"),
                              "error": previous.get("error"),
                              "attempt_dir": str(Path(trial["attempt_dir"]).parent / f"attempt-{number:02d}"),
                              "metrics": {}, "video_path": None, "render_error": None, "render_status": None}
                trials.append(_normalize_trial(root, batch, historical))
        trials.append(_normalize_trial(root, batch, trial))
    snapshot = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "batch": {key: _text(batch.get(key), 500) for key in (
            "id", "name", "status", "code_revision", "created_at", "backend")},
        "counts": dict(Counter(trial["outcome"] for trial in trials)),
        "trials": trials,
    }
    if not snapshot["batch"]["code_revision"]:
        snapshot["batch"]["code_revision"] = _text(batch.get("git_commit"), 500)
    raw = json.dumps(snapshot, ensure_ascii=False, allow_nan=False, indent=2)
    embedded = (raw.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
                .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    template = Path(__file__).with_name("gallery-template.html").read_text(encoding="utf-8")
    title = html.escape(snapshot["batch"]["name"] or snapshot["batch"]["id"] or "MapleBench batch", quote=True)
    output = template.replace("__MAPLEBENCH_TITLE__", title).replace("__MAPLEBENCH_DATA__", embedded)
    _atomic_write(root / "summary.json", raw + "\n")
    _atomic_write(root / "index.html", output)
    return root / "index.html"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch_dir", type=Path)
    parser.add_argument("--snapshot", type=Path, required=True,
                        help="Runner snapshot JSON containing batch and trials keys")
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    print(build_gallery(args.batch_dir, snapshot["batch"], snapshot["trials"]))


if __name__ == "__main__":
    main()
