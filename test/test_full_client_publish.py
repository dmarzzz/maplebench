"""Synthetic manifests test the gate; none represent published gameplay evidence."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from full_client_publish import PROGRAM_FORMAT, main, validate_manifest
from full_client_score import open_verified_artifact, verify_trial_bundle
from full_client_capture import capture_receipt
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_full_client_score import bundle_fixture, write_artifact


def complete_manifest():
    """Structurally complete test attestation, not real server/API/media evidence."""
    observation = {"ready": True, "ageMs": 10, "character": {"exp": 100, "hp": 500, "alive": True}}
    return {
        "schema_version": 1, "run_kind": "ranked",
        "result": {
            "controller": {"id": "fixture-run", "adapter": "full-client", "mode": "api",
                           "status": "completed", "model": "fixture-model", "returnedModel": "fixture-model"},
            "programSha256": "a" * 64,
            "program": {"reason": "program_complete", "error": None, "actions": 1, "steps": [
                {"kind": "sdk", "method": "observe", "args": [], "result": copy.deepcopy(observation)},
                {"kind": "sdk", "method": "pressKeys", "args": [["RIGHT"], 200],
                 "result": {"accepted": True, "error": None, "observation": copy.deepcopy(observation)}},
                {"kind": "sdk", "method": "wait", "args": [100], "result": {"waitedMs": 100}},
            ]},
            "initial": copy.deepcopy(observation), "final": copy.deepcopy(observation), "observedXpDelta": 0,
            "api": {"id": "fixture-response", "model": "fixture-model", "status": "completed",
                    "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}},
            "timing": {"startedAtMs": 1000000, "endedAtMs": 1002000, "elapsedMs": 2000, "apiLatencyMs": 500},
        },
        "budgets": {"api_requests": 1, "output_tokens": 100, "total_tokens": 200,
                    "program_ms": 1500, "run_ms": 3000, "actions": 5},
        "timeline": {"status": "completed", "api_started_ms": 0, "api_ended_ms": 500,
                     "program_started_ms": 600, "program_ended_ms": 1900,
                     "client_observations_fresh": True, "interrupted": False},
        "scenario": {"id": "fixture-scenario", "fingerprint": "b" * 64, "reset_fingerprint": "c" * 64},
        "score": {"source": "cosmic-server-events", "run_id": "fixture-run", "scenario_fingerprint": "b" * 64,
                  "reset_fingerprint": "c" * 64, "evidence_sha256": "d" * 64, "score_sha256": "e" * 64,
                  "metrics": {"xpGainedThisRun": 0}},
        "video": {"path": "video/fixture.mp4", "sha256": "f" * 64, "status": "completed",
                  "start_ms": 550, "end_ms": 1950, "duration_ms": 1400, "interrupted": False, "reviewed": True,
                  "overlay": {"controller_id": "fixture-run", "mode": "api", "model": "fixture-model"}},
    }


class PublicationGateTests(unittest.TestCase):
    def assert_blocked(self, manifest, reason):
        verdict = validate_manifest(manifest)
        self.assertFalse(verdict["ready"], verdict)
        self.assertTrue(any(reason in item for item in verdict["reasons"]), verdict)

    def test_manifest_only_attestations_never_grant_ranked_eligibility(self):
        manifest = complete_manifest()
        before = copy.deepcopy(manifest)
        self.assert_blocked(manifest, "structural only")
        self.assertEqual(manifest, before)

    def test_integration_never_becomes_ranked_even_with_all_attestations(self):
        manifest = complete_manifest()
        manifest["run_kind"] = "integration"
        self.assert_blocked(manifest, "integration/manual smoke runs")

    def test_ranked_label_cannot_override_integration_result_provenance(self):
        manifest = complete_manifest()
        manifest["result"]["source"] = "client telemetry; unscored integration run"
        self.assert_blocked(manifest, "result.source")

    def test_current_integration_result_produces_actionable_scoring_reset_blockers(self):
        manifest = complete_manifest()
        manifest["run_kind"] = "integration"
        manifest.pop("scenario")
        manifest.pop("score")
        self.assert_blocked(manifest, "scenario.reset_fingerprint")
        self.assert_blocked(manifest, "server-authoritative")

    def test_client_or_persisted_character_score_cannot_impersonate_event_score(self):
        for source in ("client telemetry", "cosmic_persisted_character"):
            with self.subTest(source=source):
                manifest = complete_manifest()
                manifest["score"]["source"] = source
                self.assert_blocked(manifest, "score.source")

    def test_scores_are_bound_to_run_and_reset(self):
        for key, value in (("run_id", "another-run"), ("scenario_fingerprint", "1" * 64),
                           ("reset_fingerprint", "2" * 64), ("evidence_sha256", "not-a-hash"),
                           ("score_sha256", None), ("metrics", {"xp": float("nan")})):
            with self.subTest(key=key):
                manifest = complete_manifest()
                manifest["score"][key] = value
                self.assert_blocked(manifest, f"score.{key}")

    def test_requested_returned_and_overlay_models_must_agree(self):
        for section, key in (("controller", "returnedModel"), ("api", "model")):
            manifest = complete_manifest()
            manifest["result"][section][key] = "different-model"
            self.assert_blocked(manifest, "model")
        manifest = complete_manifest()
        manifest["video"]["overlay"]["model"] = "different-model"
        self.assert_blocked(manifest, "video.overlay")

    def test_api_status_usage_and_budgets_are_not_optional(self):
        mutations = [
            (lambda m: m["result"]["api"].update(status="incomplete"), "completed API response"),
            (lambda m: m["result"]["api"]["usage"].update(total_tokens=151), "result.api.usage"),
            (lambda m: m["budgets"].pop("total_tokens"), "budgets.total_tokens"),
            (lambda m: m["budgets"].update(output_tokens=49), "exceeded the limit"),
            (lambda m: m["budgets"].update(actions=0), "budgets.actions"),
            (lambda m: m["budgets"].update(program_ms=1000), "budgets.program_ms"),
            (lambda m: m["budgets"].update(run_ms=1500), "budgets.run_ms"),
        ]
        for change, reason in mutations:
            with self.subTest(reason=reason):
                manifest = complete_manifest()
                change(manifest)
                self.assert_blocked(manifest, reason)

    def test_program_complete_does_not_hide_partial_or_missing_ack(self):
        for accepted in (False, None, 1, "true"):
            with self.subTest(accepted=accepted):
                manifest = complete_manifest()
                manifest["result"]["program"]["steps"][1]["result"]["accepted"] = accepted
                self.assert_blocked(manifest, "fully acknowledged")

    def test_rejected_rpc_receipt_error_and_missing_actions_fail(self):
        changes = [
            (lambda p: p["steps"].append({"kind": "rejected_rpc"}), "invalid/rejected RPC"),
            (lambda p: p["steps"][1]["result"].update(error="interrupted"), "receipt reports an error"),
            (lambda p: p.update(actions=2), "count must match"),
            (lambda p: p["steps"].pop(1), "count must match"),
            (lambda p: p.update(reason="program_timeout"), "clean program_complete"),
            (lambda p: p["steps"][1].update(args=[["LEFT", "RIGHT"], 100]), "bounded key-hold"),
        ]
        for change, reason in changes:
            with self.subTest(reason=reason):
                manifest = complete_manifest()
                change(manifest["result"]["program"])
                self.assert_blocked(manifest, reason)

    def test_stale_capture_or_observation_fails_even_when_run_completed(self):
        changes = [
            (lambda m: m["timeline"].update(interrupted=True), "timeline.interrupted"),
            (lambda m: m["timeline"].pop("client_observations_fresh"), "client_observations_fresh"),
            (lambda m: m["video"].update(interrupted=True), "uninterrupted capture"),
            (lambda m: m["result"]["final"].update(ready=False), "result.final"),
            (lambda m: m["result"]["program"]["steps"][0]["result"].update(ageMs=1500), "observation was stale"),
            (lambda m: m["result"]["program"]["steps"][1]["result"]["observation"].update(ready=False), "fresh observation"),
        ]
        for change, reason in changes:
            with self.subTest(reason=reason):
                manifest = complete_manifest()
                change(manifest)
                self.assert_blocked(manifest, reason)

    def test_timeline_must_be_ordered_and_consistent(self):
        for key, value in (("api_ended_ms", 800), ("program_ended_ms", 500), ("program_ended_ms", 4000)):
            with self.subTest(key=key, value=value):
                manifest = complete_manifest()
                manifest["timeline"][key] = value
                self.assert_blocked(manifest, "timeline:")
        manifest = complete_manifest()
        manifest["result"]["timing"]["endedAtMs"] += 1000
        self.assert_blocked(manifest, "wall duration")

    def test_video_cannot_be_missing_unreviewed_or_a_selected_excerpt(self):
        changes = [
            (lambda v: v.update(reviewed=False), "video.reviewed"),
            (lambda v: v.update(sha256=None), "SHA-256"),
            (lambda v: v.update(path="../private.mp4"), "relative .mp4"),
            (lambda v: v.update(path="https://example.test/clip.mp4"), "relative .mp4"),
            (lambda v: v.update(start_ms=1000, duration_ms=950), "complete program"),
            (lambda v: v.update(duration_ms=1), "measured duration disagree"),
        ]
        for change, reason in changes:
            with self.subTest(reason=reason):
                manifest = complete_manifest()
                change(manifest["video"])
                self.assert_blocked(manifest, reason)

    def test_diagnostic_xp_must_match_but_cannot_replace_missing_server_score(self):
        manifest = complete_manifest()
        manifest["result"]["observedXpDelta"] = 100
        self.assert_blocked(manifest, "result.observedXpDelta")
        manifest["result"]["final"]["character"]["exp"] += 100
        manifest.pop("score")
        self.assert_blocked(manifest, "score.source")

    def test_malformed_types_booleans_nonfinite_numbers_do_not_crash_or_pass(self):
        for value in (None, [], True, "ranked", 1):
            self.assert_blocked(value, "JSON object")
        for section in ("result", "video", "scenario", "score", "budgets", "timeline"):
            manifest = complete_manifest()
            manifest[section] = []
            self.assertFalse(validate_manifest(manifest)["ready"])
        for value in (True, float("nan"), float("inf"), 10 ** 1000):
            manifest = complete_manifest()
            manifest["result"]["timing"]["elapsedMs"] = value
            self.assert_blocked(manifest, "result.timing")
        manifest = complete_manifest()
        manifest["schema_version"] = True
        self.assert_blocked(manifest, "schema_version")

    def test_cli_returns_json_and_nonzero_for_ineligible_or_invalid_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            for value, code in ((complete_manifest(), 1), ({"run_kind": "integration"}, 1)):
                path.write_text(json.dumps(value))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main([str(path)]), code)
                self.assertEqual(json.loads(output.getvalue())["ready"], code == 0)
            path.write_text("{bad json")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([str(path)]), 2)
            self.assertFalse(json.loads(output.getvalue())["ready"])


PROBE = {"width": 1024, "height": 768, "frames": 120, "duration_ms": 5000}


def persisted_manifest(directory):
    """Synthetic collector files; media probing is explicitly mocked in tests."""
    manifest = complete_manifest()
    manifest["schema_version"] = 2
    manifest["budgets"].update(program_ms=5000, run_ms=6000, sdk_requests=20)
    instructions = "Synthetic program-generation instructions; this is not an actual API run."
    reasoning = {"effort": "low"}
    evidence, artifacts = bundle_fixture(directory, {"id": "fixture-scenario", "budgets": manifest["budgets"],
        "instructions_sha256": hashlib.sha256(instructions.encode()).hexdigest(), "reasoning": reasoning})
    result = manifest["result"]
    result["source"] = "full-client-trial"
    result["controller"]["id"] = evidence["run_id"]
    result["controller"]["client"] = "fixture-client"
    result["timing"].update(startedAtMs=2200, endedAtMs=7100, elapsedMs=4900, apiLatencyMs=800)
    manifest["timeline"].update(api_started_ms=0, api_ended_ms=800, program_started_ms=900, program_ended_ms=4800)
    result["timeline"] = copy.deepcopy(manifest["timeline"])
    observations = [result["initial"], result["final"], result["program"]["steps"][0]["result"],
                    result["program"]["steps"][1]["result"]["observation"]]
    for observation in observations:
        observation["renderAgeMs"] = 10
    manifest["scenario"].update(fingerprint=evidence["scenario_fingerprint"],
                                 reset_fingerprint=evidence["baseline"]["sha256"])
    manifest["score"] = verify_trial_bundle(evidence, directory, artifacts)
    write_artifact(directory, artifacts, "score", manifest["score"])
    code = "await sdk.pressKeys(['RIGHT'], 200);"
    result["programSha256"] = write_artifact(directory, artifacts, "program", code.encode(), raw=True)
    metadata = {"maplebench_run_id": evidence["run_id"]}
    write_artifact(directory, artifacts, "api_request", {"model": "fixture-model", "metadata": metadata,
        "max_output_tokens": 100, "store": False, "reasoning": reasoning, "instructions": instructions,
        "input": json.dumps({"observation": result["initial"]}), "text": {"format": PROGRAM_FORMAT}})
    response = result["api"] | {"metadata": metadata, "output": [{"type": "message", "content": [
        {"type": "output_text", "text": json.dumps({"note": "synthetic", "code": code})}]}]}
    write_artifact(directory, artifacts, "api_response", response)
    write_artifact(directory, artifacts, "result", result)
    video_hash = write_artifact(directory, artifacts, "video", b"synthetic mocked video", raw=True)
    old_path = Path(directory) / artifacts["video"]["path"]
    old_path.rename(Path(directory) / "video.webm")
    artifacts["video"]["path"] = "video.webm"
    manifest["video"].update(path="video.webm", sha256=video_hash)
    manifest["video"]["overlay"]["controller_id"] = evidence["run_id"]
    clock = {"id": "e" * 32, "client_sent_ms": 2190, "server_received_ms": 2200, "server_sent_ms": 2200}
    ready = {"runId": evidence["run_id"], "serverReceivedAtMs": 2200, "renderedFrames": 1}
    terminal = {"id": "d" * 32, "serverIssuedAtMs": 7100}
    capture = {"schema_version": 1, "run_id": evidence["run_id"], "client_id": "fixture-client",
               "start_wall_ms": 2200, "end_wall_ms": 7200, "duration_ms": 5000,
               "first_frame_wall_ms": 2200, "last_frame_wall_ms": 7190,
               "rendered_frames": 120, "max_frame_gap_ms": 50, "hidden": False, "errors": 0,
               "relay_lost": False, "interrupted": False, "clock": clock | {"client_received_ms": 2210},
               "terminal_token": terminal["id"]}
    for name, value in (("capture", capture), ("capture_ready", ready), ("capture_clock", clock), ("capture_terminal", terminal)):
        write_artifact(directory, artifacts, name, value)
    measured = capture_receipt(capture, {"id": evidence["run_id"], "client": "fixture-client", "startedAtMs": 2200},
                               ready, clock, terminal)
    manifest["video"].update(measured, capture_sha256=artifacts["capture"]["sha256"])
    write_artifact(directory, artifacts, "recording", manifest["video"] | {"reviewed": False})
    write_artifact(directory, artifacts, "video_probe", PROBE | {"video_sha256": video_hash})
    write_artifact(directory, artifacts, "video_review", {
        "video_sha256": video_hash, "run_id": evidence["run_id"], "reviewed": True,
        "post_render_capture": True, "overlay": manifest["video"]["overlay"], "reviewed_at_ms": 7300})
    manifest["artifacts"] = artifacts
    return manifest


class PersistedPublicationTests(unittest.TestCase):
    def test_measured_capture_tail_does_not_rewrite_controller_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            original = copy.deepcopy(manifest["result"]["timing"])
            self.assertGreater(manifest["video"]["end_ms"], original["elapsedMs"])
            with patch("full_client_publish._probe_video", return_value=PROBE):
                self.assertTrue(validate_manifest(manifest, directory)["ready"])
            self.assertEqual(manifest["result"]["timing"], original)

    def test_capture_raw_artifacts_are_required_and_bound_to_saved_recording(self):
        for missing in ("capture", "capture_ready", "capture_clock", "capture_terminal", "recording"):
            with tempfile.TemporaryDirectory() as directory:
                manifest = persisted_manifest(directory)
                manifest["artifacts"].pop(missing)
                self.assertFalse(validate_manifest(manifest, directory)["ready"])
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            artifacts = manifest["artifacts"]
            capture = json.loads((Path(directory) / artifacts["capture"]["path"]).read_text())
            capture["hidden"] = True
            write_artifact(directory, artifacts, "capture", capture)
            self.assertFalse(validate_manifest(manifest, directory)["ready"])

    def test_rehashed_capture_cannot_hide_planning_gap_clock_uncertainty_or_excessive_tail(self):
        mutations = [
            lambda capture, ready, clock, terminal: ready.update(serverReceivedAtMs=2300),
            lambda capture, ready, clock, terminal: capture.update(first_frame_wall_ms=2400),
            lambda capture, ready, clock, terminal: terminal.update(serverIssuedAtMs=7000),
            lambda capture, ready, clock, terminal: capture.update(end_wall_ms=10000, duration_ms=7800),
            lambda capture, ready, clock, terminal: capture["clock"].update(client_received_ms=3000),
            lambda capture, ready, clock, terminal: capture.update(max_frame_gap_ms=1001),
        ]
        for mutation in mutations:
            with tempfile.TemporaryDirectory() as directory:
                manifest = persisted_manifest(directory)
                artifacts = manifest["artifacts"]
                names = ("capture", "capture_ready", "capture_clock", "capture_terminal")
                values = [json.loads((Path(directory) / artifacts[name]["path"]).read_text()) for name in names]
                mutation(*values)
                capture, ready, clock, terminal = values
                for name, value in zip(names, values):
                    write_artifact(directory, artifacts, name, value)
                measured = capture_receipt(capture, {"id": manifest["result"]["controller"]["id"],
                    "client": "fixture-client", "startedAtMs": 2200}, ready, clock, terminal)
                manifest["video"].update(measured, capture_sha256=artifacts["capture"]["sha256"])
                write_artifact(directory, artifacts, "recording", manifest["video"] | {"reviewed": False})
                with patch("full_client_publish._probe_video", return_value=PROBE):
                    self.assertFalse(validate_manifest(manifest, directory)["ready"])

    def test_actual_request_input_prompt_reasoning_and_output_contract_are_frozen(self):
        changes = [lambda r: r.pop("input"), lambda r: r.update(instructions="different instructions"),
                   lambda r: r.update(input=json.dumps({"observation": {"ready": True}})),
                   lambda r: r.update(input=json.dumps({"observation": {}, "extra": "context"})),
                   lambda r: r.update(store=True), lambda r: r["reasoning"].update(effort="high"),
                   lambda r: r["text"]["format"].update(strict=False),
                   lambda r: r.update(previous_response_id="unrecorded-context")]
        for change in changes:
            with tempfile.TemporaryDirectory() as directory:
                manifest = persisted_manifest(directory)
                artifacts = manifest["artifacts"]
                request = json.loads((Path(directory) / artifacts["api_request"]["path"]).read_text())
                change(request)
                write_artifact(directory, artifacts, "api_request", request)
                self.assertFalse(validate_manifest(manifest, directory)["ready"])

    def test_complete_bundle_recomputes_score_and_probes_exact_video(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            with patch("full_client_publish._probe_video", return_value=PROBE) as probe:
                self.assertEqual(validate_manifest(manifest, Path(directory)), {"ready": True, "reasons": []})
            probe.assert_called_once_with(Path(directory) / "video.webm", manifest["video"]["sha256"])
            self.assertFalse(validate_manifest(manifest)["ready"])

    def test_existing_integration_cannot_be_promoted_with_artifact_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            for field in ("kind", "source"):
                value = copy.deepcopy(manifest)
                if field == "kind":
                    value["run_kind"] = "integration"
                else:
                    value["result"]["source"] = "client telemetry; unscored integration run"
                self.assertFalse(validate_manifest(value, directory)["ready"])

    def test_recomputed_score_frozen_budgets_and_session_timeline_cannot_be_forged(self):
        mutations = [
            lambda m: m["score"]["metrics"].update(net_xp=9000),
            lambda m: m["budgets"].update(actions=6),
            lambda m: m["result"]["timing"].update(startedAtMs=2300, endedAtMs=7200),
        ]
        for change in mutations:
            with tempfile.TemporaryDirectory() as directory:
                manifest = persisted_manifest(directory)
                change(manifest)
                write_artifact(directory, manifest["artifacts"], "score", manifest["score"])
                write_artifact(directory, manifest["artifacts"], "result", manifest["result"])
                # A 100 ms clock tolerance is intentional, so shift by another millisecond.
                if manifest["result"]["timing"]["startedAtMs"] == 2300:
                    manifest["result"]["timing"]["startedAtMs"] += 1
                    manifest["result"]["timing"]["endedAtMs"] += 1
                    write_artifact(directory, manifest["artifacts"], "result", manifest["result"])
                with patch("full_client_publish._probe_video", return_value=PROBE):
                    self.assertFalse(validate_manifest(manifest, directory)["ready"])

    def test_provider_program_binding_is_checked_even_after_rehash(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            artifacts = manifest["artifacts"]
            manifest["result"]["programSha256"] = write_artifact(
                directory, artifacts, "program", b"await sdk.wait(200);", raw=True)
            write_artifact(directory, artifacts, "result", manifest["result"])
            verdict = validate_manifest(manifest, directory)
            self.assertFalse(verdict["ready"])
            self.assertIn("provider output", verdict["reasons"][0])

    def test_program_swap_after_hash_cannot_match_different_provider_output(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            artifacts = manifest["artifacts"]
            path = Path(directory) / artifacts["program"]["path"]
            response = json.loads((Path(directory) / artifacts["api_response"]["path"]).read_text())
            replacement_code = "await sdk.wait(200);"
            response["output"][0]["content"][0]["text"] = json.dumps({"note": "synthetic", "code": replacement_code})
            write_artifact(directory, artifacts, "api_response", response)

            @contextlib.contextmanager
            def changed_after_hash(root, reference, label, *args, **kwargs):
                with open_verified_artifact(root, reference, label, *args, **kwargs) as stream:
                    if label == "program":
                        replacement = path.with_suffix(".replacement")
                        replacement.write_text(replacement_code)
                        replacement.replace(path)
                    yield stream

            with patch("full_client_score.open_verified_artifact", changed_after_hash):
                self.assertFalse(validate_manifest(manifest, directory)["ready"])

    def test_video_probe_uses_verified_descriptor_and_rejects_path_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            path = Path(directory) / "video.webm"
            original = path.read_bytes()

            def substituted_probe(command, **kwargs):
                fd, = kwargs["pass_fds"]
                self.assertTrue(command[-1].endswith("/fd/" + str(fd)))
                replacement = path.with_suffix(".replacement")
                replacement.write_bytes(b"different unverified video")
                replacement.replace(path)
                self.assertEqual(os.pread(fd, len(original), 0), original)
                raw = {"streams": [{"width": 1024, "height": 768, "nb_read_frames": "120"}],
                       "format": {"duration": "4.0"}}
                return SimpleNamespace(returncode=0, stdout=json.dumps(raw).encode())

            with patch("full_client_publish.subprocess.run", side_effect=substituted_probe) as probe:
                self.assertFalse(validate_manifest(manifest, directory)["ready"])
            probe.assert_called_once()

    def test_video_in_place_change_during_probe_cannot_hide_behind_restored_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            path = Path(directory) / "video.webm"
            original = path.read_bytes()

            def changed_probe(command, **kwargs):
                before = path.stat()
                path.write_bytes(b"changed during probe")
                path.write_bytes(original)
                # Deterministic stamp change even on filesystems with coarse clocks.
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
                raw = {"streams": [{"width": 1024, "height": 768, "nb_read_frames": "120"}],
                       "format": {"duration": "4.0"}}
                return SimpleNamespace(returncode=0, stdout=json.dumps(raw).encode())

            with patch("full_client_publish.subprocess.run", side_effect=changed_probe):
                self.assertFalse(validate_manifest(manifest, directory)["ready"])

    def test_raw_provider_receipt_is_required_and_bound_to_run(self):
        for mutation in (lambda response: response.pop("output"),
                         lambda response: response["metadata"].update(maplebench_run_id="other-run"),
                         lambda response: response.update(model="other-model")):
            with tempfile.TemporaryDirectory() as directory:
                manifest = persisted_manifest(directory)
                artifacts = manifest["artifacts"]
                response = json.loads((Path(directory) / artifacts["api_response"]["path"]).read_text())
                mutation(response)
                write_artifact(directory, artifacts, "api_response", response)
                self.assertFalse(validate_manifest(manifest, directory)["ready"])

    def test_saved_probe_cannot_override_actual_video_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            with patch("full_client_publish._probe_video", return_value=PROBE | {"duration_ms": 1}):
                verdict = validate_manifest(manifest, directory)
                self.assertFalse(verdict["ready"])
                self.assertIn("actual recording", verdict["reasons"][0])

    def test_missing_probe_utility_and_bad_media_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            with patch("full_client_publish.subprocess.run", side_effect=FileNotFoundError):
                verdict = validate_manifest(manifest, directory)
                self.assertFalse(verdict["ready"])
                self.assertIn("ffprobe", verdict["reasons"][0])

    def test_post_render_and_exact_video_review_cannot_be_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            artifacts = manifest["artifacts"]
            review = json.loads((Path(directory) / artifacts["video_review"]["path"]).read_text())
            review["post_render_capture"] = False
            write_artifact(directory, artifacts, "video_review", review)
            with patch("full_client_publish._probe_video", return_value=PROBE):
                self.assertFalse(validate_manifest(manifest, directory)["ready"])

    def test_cli_rejects_duplicate_manifest_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text('{"schema_version":1,"schema_version":2}')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(path)]), 2)


if __name__ == "__main__":
    unittest.main()
