"""Synthetic manifests test the gate; none represent published gameplay evidence."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from full_client_publish import main, validate_manifest


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

    def test_complete_zero_xp_run_is_eligible_and_input_unchanged(self):
        manifest = complete_manifest()
        before = copy.deepcopy(manifest)
        self.assertEqual(validate_manifest(manifest), {"ready": True, "reasons": []})
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
            for value, code in ((complete_manifest(), 0), ({"run_kind": "integration"}, 1)):
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


if __name__ == "__main__":
    unittest.main()
