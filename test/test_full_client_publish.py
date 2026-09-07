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
from full_client_publish import (PROGRAM_FORMAT, main, validate_manifest, _measure_video_probe,
                                _probe_video, _video_probe_limits, _verify_settlement_policy,
                                _verify_docker_execution, _verify_readiness_policy, JSON_LIMIT)
from full_client_score import EvidenceError, open_verified_artifact, verify_trial_bundle
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
    def test_new_runtime_binding_matches_receipt_without_accessing_host_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest=complete_manifest(); manifest['artifacts']={}
            binding={'schema_version':1,'executable':{'path':'/frozen/private/docker','sha256':'a'*64},
                     'launcher':{'path':'/usr/bin/sudo','sha256':'b'*64},'socket_path':'/frozen/private/docker.sock'}
            runtime={'schema_version':2,'docker_binding':binding,'docker_image_id':'sha256:'+'c'*64}
            write_artifact(Path(directory),manifest['artifacts'],'runtime_manifest',runtime)
            manifest['result']['controller'].update(dockerBinding=copy.deepcopy(binding),dockerImageId=runtime['docker_image_id'])
            with patch('full_client_docker.executable_reference',side_effect=AssertionError('offline evidence only')):
                _verify_docker_execution(manifest,directory)
                for change in (lambda controller:controller.pop('dockerBinding'),
                               lambda controller:controller['dockerBinding'].update(socket_path='/other/socket'),
                               lambda controller:controller['dockerBinding']['executable'].update(sha256='d'*64),
                               lambda controller:controller.update(dockerImageId='sha256:'+'d'*64)):
                    bad=copy.deepcopy(manifest); change(bad['result']['controller'])
                    with self.assertRaisesRegex(EvidenceError,'docker: frozen execution binding'):
                        _verify_docker_execution(bad,directory)
            # Historical bundles are not relabeled or rewritten by the new check.
            old=complete_manifest(); old['artifacts']={}
            _verify_docker_execution(old,directory)
            write_artifact(Path(directory),old['artifacts'],'runtime_manifest',{'schema_version':1})
            _verify_docker_execution(old,directory)

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
POLICY = {"capture_tail_ms": 2000, "upload_after_program_ms": 5000,
          "disconnect_after_program_ms": 5000, "logout_after_disconnect_ms": 5000}


def persisted_manifest(directory, *, program_seconds=22, span_ms=3900, outcome="program_complete", readiness=False):
    """Synthetic collector files; media probing is explicitly mocked in tests."""
    manifest = complete_manifest()
    manifest["schema_version"] = 2
    manifest["budgets"].update(program_ms=program_seconds * 1000, run_ms=(program_seconds + 53) * 1000,
                                sdk_requests=100 if program_seconds == 22 else 600)
    manifest["timeline"].pop("interrupted")
    manifest["timeline"].pop("client_observations_fresh")
    instructions = "Synthetic program-generation instructions; this is not an actual API run."
    reasoning = {"effort": "low"}
    scenario = {"id": "fixture-scenario", "budgets": manifest["budgets"],
        "instructions_sha256": hashlib.sha256(instructions.encode()).hexdigest(), "reasoning": reasoning,
        "settlement_policy": copy.deepcopy(POLICY), "program_seconds": program_seconds,
        "trial_budgets": {"controller_seconds": program_seconds + 2}}
    setup_ms = 1100 if readiness else 0
    if readiness:
        manifest["budgets"]["run_ms"] = (program_seconds + 63) * 1000
        scenario["readiness_policy"] = {"schema_version": 1, "expected_map_id": 100000000,
            "min_monsters": 1, "min_samples": 3, "min_span_ms": 1000, "timeout_ms": 10000}
    evidence, artifacts = bundle_fixture(directory, scenario)
    delta = span_ms - 3900 + setup_ms
    if readiness:
        for row in (evidence["baseline"]["character"], evidence["initial"]["character"],
                    evidence["final"]["character"]):
            row["map_id"] = scenario["readiness_policy"]["expected_map_id"]
        evidence["initial"]["evidence_sha256"] = write_artifact(directory, artifacts, "initial_db",
            {key: value for key, value in evidence["initial"].items() if key != "evidence_sha256"})
        for key in ("api_started_at_ms", "api_ended_at_ms", "controller_started_at_ms"):
            evidence["session"][key] += setup_ms
    evidence["session"].update(controller_ended_at_ms=7000 + delta, upload_observed_at_ms=7300 + delta,
                               disconnect_requested_at_ms=7400 + delta, logged_out_at_ms=8000 + delta)
    evidence["session"]["save"]["committed_at_ms"] += delta
    evidence["session"]["save"]["log_checked_through_ms"] += delta
    evidence["final"]["captured_at_ms"] += delta
    if outcome == "death":
        evidence["final"]["character"].update(hp=0, exp=400)
    evidence["final"]["evidence_sha256"] = write_artifact(directory, artifacts, "final_db",
        {key: value for key, value in evidence["final"].items() if key != "evidence_sha256"})
    for name, time_key, hash_key in (("save", "committed_at_ms", "evidence_sha256"),
                                    ("server_log", "at_ms", "logs_sha256")):
        rows = [json.loads(line) for line in (Path(directory) / artifacts[name]["path"]).read_bytes().splitlines()]
        for row in rows:
            if row[time_key] >= 7000:
                row[time_key] += delta
        evidence["session"]["save"][hash_key] = write_artifact(directory, artifacts, name,
            b"".join(json.dumps(row).encode() + b"\n" for row in rows), raw=True)
    write_artifact(directory, artifacts, "session", evidence["session"])
    write_artifact(directory, artifacts, "persistence", evidence)
    write_artifact(directory, artifacts, "upload_status", {"schema_version": 1,
        "source": "full_client_runtime_status", "run_id": evidence["run_id"],
        "server_instance_id": evidence["session"]["server_instance_id"], "character_id": 7, "account_id": 9,
        "observed_at_ms": 7300 + delta, "status": {"bridge": {"run": {"id": evidence["run_id"], "status": "completed",
            "evidenceStatus": "saved", "recordingStatus": "saved", "workerActive": False,
            "leaseReleasePending": False},
            "browserReleasePending": False}, "session": {"artifactsSettled": True}}})
    result = manifest["result"]
    result["source"] = "full-client-trial"
    result["controller"]["id"] = evidence["run_id"]
    result["controller"]["client"] = "fixture-client"
    result["controller"].update(programSeconds=program_seconds, controllerSeconds=program_seconds + 2)
    if readiness:
        result["controller"]["readinessPolicy"] = copy.deepcopy(scenario["readiness_policy"])
    result["program"]["reason"] = outcome
    if outcome == "death":
        result["initial"]["character"]["exp"] = 1000
        result["final"]["character"].update(exp=400, hp=0, alive=False)
        result["observedXpDelta"] = -600
    if outcome == "action_limit":
        action = result["program"]["steps"][1]
        result["program"]["steps"] = [copy.deepcopy(action) for _ in range(manifest["budgets"]["actions"])]
        result["program"]["actions"] = manifest["budgets"]["actions"]
    result["timing"].update(startedAtMs=2200, endedAtMs=7100 + delta, elapsedMs=4900 + delta, apiLatencyMs=800)
    manifest["timeline"].update(api_started_ms=setup_ms, api_ended_ms=800 + setup_ms,
                                program_started_ms=900 + setup_ms, program_ended_ms=4800 + delta)
    if readiness:
        manifest["timeline"].update(readiness_started_ms=0, readiness_ended_ms=1000)
    result["timeline"] = copy.deepcopy(manifest["timeline"])
    observations = [result["initial"], result["final"]] + [
        step["result"] if step["method"] == "observe" else step["result"]["observation"]
        for step in result["program"]["steps"] if step["method"] != "wait"]
    for observation in observations:
        observation["renderAgeMs"] = 10
    if readiness:
        for observation in observations:
            observation["character"]["mapId"] = scenario["readiness_policy"]["expected_map_id"]
            observation["monsters"] = [{"objectId": 1, "x": 50, "y": 100}]
    manifest["scenario"].update(fingerprint=evidence["scenario_fingerprint"],
                                 reset_fingerprint=evidence["baseline"]["sha256"])
    result["trialContext"] = {"scenario_fingerprint": evidence["scenario_fingerprint"],
                              "baseline_sha256": evidence["baseline"]["sha256"]}
    result["controller"]["trialContext"] = copy.deepcopy(result["trialContext"])
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
    terminal = {"id": "d" * 32, "serverIssuedAtMs": 7100 + delta}
    capture = {"schema_version": 1, "run_id": evidence["run_id"], "client_id": "fixture-client",
               "start_wall_ms": 2200, "end_wall_ms": 7200 + delta, "duration_ms": 5000 + delta,
               "first_frame_wall_ms": 2200, "last_frame_wall_ms": 7190 + delta,
               "rendered_frames": 120, "max_frame_gap_ms": 50, "hidden": False, "errors": 0,
               "relay_lost": False, "interrupted": False, "clock": clock | {"client_received_ms": 2210},
               "terminal_token": terminal["id"]}
    for name, value in (("capture", capture), ("capture_ready", ready), ("capture_clock", clock), ("capture_terminal", terminal)):
        write_artifact(directory, artifacts, name, value)
    if readiness:
        initial_hash = hashlib.sha256(json.dumps(result["initial"], sort_keys=True,
            separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        sample = {"map_id": scenario["readiness_policy"]["expected_map_id"], "alive": True,
                  "monster_count": 1, "age_ms": 10, "render_age_ms": 10, "observation_sha256": initial_hash}
        def transit_fields(elapsed):
            # Synthetic clock interval [-10,+10] permits zero transit when the
            # browser wall clock is ten milliseconds ahead of this server.
            return {"frame_received_at_ms": 2200 + elapsed, "frame_received_run_ms": elapsed,
                    "client_sent_at_ms": 2210 + elapsed, "reported_age_ms": 10,
                    "reported_render_age_ms": 10, "transit_upper_ms": 0, "server_residence_ms": 0}
        receipt = {"schema_version": 1, "run_id": evidence["run_id"], "client_id": "fixture-client",
                   "capture_clock_id": clock["id"], "capture_clock_client_received_ms": 2210,
                   "capture_ready_at_ms": ready["serverReceivedAtMs"],
                   "policy": copy.deepcopy(scenario["readiness_policy"]), "wait_started_at_ms": 2200,
                   "wait_started_run_ms": 0, "qualified_at_ms": 3200, "qualified_run_ms": 1000,
                   "samples": [sample | transit_fields(elapsed) | {"rendered_frames": frames, "server_received_at_ms": 2200 + elapsed,
                                         "run_elapsed_ms": elapsed} for frames, elapsed in ((1, 0), (15, 500), (30, 1000))],
                   "initial_observation_sha256": initial_hash,
                   "dispatch": sample | transit_fields(1050) | {"rendered_frames": 32, "checked_at_ms": 3250, "run_elapsed_ms": 1050}}
        result["readiness"] = receipt
        result["readinessSha256"] = write_artifact(directory, artifacts, "readiness", receipt)
        write_artifact(directory, artifacts, "result", result)
    measured = capture_receipt(capture, {"id": evidence["run_id"], "client": "fixture-client", "startedAtMs": 2200},
                               ready, clock, terminal)
    manifest["video"].update(measured, capture_sha256=artifacts["capture"]["sha256"])
    write_artifact(directory, artifacts, "recording", manifest["video"] | {"reviewed": False})
    write_artifact(directory, artifacts, "video_probe", PROBE | {"duration_ms": 5000 + delta, "video_sha256": video_hash})
    write_artifact(directory, artifacts, "video_review", {
        "video_sha256": video_hash, "run_id": evidence["run_id"], "reviewed": True,
        "post_render_capture": True, "overlay": manifest["video"]["overlay"], "reviewed_at_ms": 7300 + delta})
    manifest["artifacts"] = artifacts
    return manifest


class PersistedPublicationTests(unittest.TestCase):
    def test_future_readiness_policy_passes_only_with_bound_pre_api_window(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory, readiness=True)
            before = copy.deepcopy(manifest)
            with patch("full_client_publish._probe_video", return_value=PROBE | {"duration_ms": 6100}):
                self.assertEqual(validate_manifest(manifest, directory), {"ready": True, "reasons": []})
            self.assertEqual(manifest, before)

    def test_future_readiness_recomputes_nonzero_transit_and_server_residence(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory, readiness=True)
            artifacts, result = manifest["artifacts"], manifest["result"]
            receipt = result["readiness"]
            receipt["samples"][1].update(client_sent_at_ms=2610, transit_upper_ms=100,
                                         age_ms=110, render_age_ms=110)
            receipt["samples"][-1].update(server_received_at_ms=3210, run_elapsed_ms=1010,
                client_sent_at_ms=3110, transit_upper_ms=100, server_residence_ms=10,
                age_ms=120, render_age_ms=120)
            receipt.update(qualified_at_ms=3210, qualified_run_ms=1010)
            result["timeline"]["readiness_ended_ms"] = 1010
            manifest["timeline"] = copy.deepcopy(result["timeline"])
            receipt["dispatch"].update(frame_received_at_ms=3240, frame_received_run_ms=1040,
                client_sent_at_ms=3150, transit_upper_ms=100, server_residence_ms=10,
                age_ms=120, render_age_ms=120)
            result["initial"].update(ageMs=120, renderAgeMs=120)
            digest = hashlib.sha256(json.dumps(result["initial"], sort_keys=True,
                separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
            receipt["samples"][-1]["observation_sha256"] = digest
            receipt["initial_observation_sha256"] = digest
            receipt["dispatch"]["observation_sha256"] = digest
            result["readinessSha256"] = write_artifact(directory, artifacts, "readiness", receipt)
            write_artifact(directory, artifacts, "result", result)
            request = json.loads((Path(directory) / artifacts["api_request"]["path"]).read_bytes())
            request["input"] = json.dumps({"observation": result["initial"]})
            write_artifact(directory, artifacts, "api_request", request)
            with patch("full_client_publish._probe_video", return_value=PROBE | {"duration_ms": 6100}):
                self.assertEqual(validate_manifest(manifest, directory), {"ready": True, "reasons": []})
            # Omitting transit from apparently fresh age fields cannot pass,
            # even after the altered artifact/result hashes are made consistent.
            receipt["samples"][1].update(age_ms=10, render_age_ms=10)
            result["readinessSha256"] = write_artifact(directory, artifacts, "readiness", receipt)
            write_artifact(directory, artifacts, "result", result)
            verdict = validate_manifest(manifest, directory)
            self.assertFalse(verdict["ready"], verdict)
            self.assertTrue(any("conservative transit" in reason for reason in verdict["reasons"]), verdict)

    def test_future_readiness_rejects_missing_malformed_and_unbound_receipts(self):
        changes = [
            ("missing artifact", lambda m: m["artifacts"].pop("readiness")),
            ("missing result receipt", lambda m: m["result"].pop("readiness")),
            ("missing controller policy", lambda m: m["result"]["controller"].pop("readinessPolicy")),
            ("wrong result hash", lambda m: m["result"].update(readinessSha256="a" * 64)),
            ("wrong result receipt", lambda m: m["result"]["readiness"].update(run_id="another-run")),
            ("missing timeline", lambda m: m["result"]["timeline"].pop("readiness_ended_ms")),
        ]
        for label, change in changes:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                manifest = persisted_manifest(directory, readiness=True)
                change(manifest)
                # Rebind result bytes; failure must come from readiness evidence.
                manifest["timeline"] = copy.deepcopy(manifest["result"]["timeline"])
                write_artifact(directory, manifest["artifacts"], "result", manifest["result"])
                verdict = validate_manifest(manifest, directory)
                self.assertFalse(verdict["ready"], verdict)
                self.assertTrue(any("readiness" in reason for reason in verdict["reasons"]), verdict)

    def test_future_readiness_checks_measurements_even_when_every_file_hash_matches(self):
        changes = [
            ("wrong run", lambda r: r.update(run_id="different-run")),
            ("wrong client", lambda r: r.update(client_id="different-renderer")),
            ("wrong clock", lambda r: r.update(capture_clock_id="f" * 32)),
            ("wrong ready receipt", lambda r: r.update(capture_ready_at_ms=2201)),
            ("wrong clock echo", lambda r: r.update(capture_clock_client_received_ms=2211)),
            ("unknown receipt field", lambda r: r.update(certified=True)),
            ("wrong policy", lambda r: r["policy"].update(min_monsters=0)),
            ("too few samples", lambda r: r["samples"].pop(1)),
            ("short sustained interval", lambda r: r["samples"][0].update(run_elapsed_ms=1, server_received_at_ms=2201,
                frame_received_run_ms=1, frame_received_at_ms=2201, client_sent_at_ms=2211)),
            ("repeated rendered frame", lambda r: r["samples"][1].update(rendered_frames=1)),
            ("frame beyond capture", lambda r: r["samples"][1].update(rendered_frames=121)),
            ("counter boolean", lambda r: r["samples"][1].update(rendered_frames=True)),
            ("wrong map", lambda r: r["samples"][1].update(map_id=200000000)),
            ("not alive", lambda r: r["samples"][1].update(alive=False)),
            ("boolean monster count", lambda r: r["samples"][1].update(monster_count=True)),
            ("no monsters", lambda r: r["samples"][1].update(monster_count=0)),
            ("stale observation", lambda r: r["samples"][1].update(age_ms=1500)),
            ("stale rendering", lambda r: r["samples"][1].update(render_age_ms=1500)),
            ("negative freshness", lambda r: r["samples"][1].update(age_ms=-1)),
            ("reversed monotonic sample", lambda r: r["samples"][1].update(run_elapsed_ms=1100)),
            ("wrong observation digest", lambda r: r["samples"][-1].update(observation_sha256="a" * 64)),
            ("wrong initial digest", lambda r: r.update(initial_observation_sha256="b" * 64)),
            ("dispatch before qualification", lambda r: r["dispatch"].update(run_elapsed_ms=900, checked_at_ms=3100)),
            ("dispatch after API", lambda r: r["dispatch"].update(run_elapsed_ms=1101, checked_at_ms=3301)),
            ("dispatch no monsters", lambda r: r["dispatch"].update(monster_count=0)),
            ("dispatch stale", lambda r: r["dispatch"].update(age_ms=1500)),
            ("dispatch counter regressed", lambda r: r["dispatch"].update(rendered_frames=29)),
            ("missing transit evidence", lambda r: r["samples"][1].pop("client_sent_at_ms")),
            ("invented zero transit", lambda r: r["samples"][1].update(client_sent_at_ms=2610)),
            ("negative transit bound", lambda r: r["samples"][1].update(client_sent_at_ms=2800)),
            ("send before clock echo", lambda r: r["samples"][1].update(client_sent_at_ms=2200)),
            ("residence absent from ages", lambda r: r["samples"][1].update(server_residence_ms=10)),
            ("boolean reported age", lambda r: r["samples"][1].update(reported_age_ms=True)),
            ("dispatch transit hidden", lambda r: r["dispatch"].update(client_sent_at_ms=3160)),
        ]
        for label, change in changes:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                manifest = persisted_manifest(directory, readiness=True)
                change(manifest["result"]["readiness"])
                manifest["result"]["readinessSha256"] = write_artifact(
                    directory, manifest["artifacts"], "readiness", manifest["result"]["readiness"])
                write_artifact(directory, manifest["artifacts"], "result", manifest["result"])
                verdict = validate_manifest(manifest, directory)
                self.assertFalse(verdict["ready"], verdict)
                self.assertTrue(any("readiness" in reason for reason in verdict["reasons"]), verdict)

    def test_future_readiness_policy_is_fixed_and_baseline_bound(self):
        policies = [None, [], True,
            {"schema_version": 1, "expected_map_id": 100000000, "min_monsters": 0,
             "min_samples": 3, "min_span_ms": 1000, "timeout_ms": 10000},
            {"schema_version": 1, "expected_map_id": 200000000, "min_monsters": 1,
             "min_samples": 3, "min_span_ms": 1000, "timeout_ms": 10000},
            {"schema_version": 1, "expected_map_id": 100000000, "min_monsters": 1,
             "min_samples": 2, "min_span_ms": 1000, "timeout_ms": 10000},
            {"schema_version": 1, "expected_map_id": 100000000, "min_monsters": 1,
             "min_samples": 3, "min_span_ms": 999, "timeout_ms": 10000},
            {"schema_version": 1, "expected_map_id": 100000000, "min_monsters": 1,
             "min_samples": 3, "min_span_ms": 1000, "timeout_ms": 10001}]
        for policy in policies:
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as directory:
                manifest = persisted_manifest(directory, readiness=True)
                evidence = json.loads((Path(directory) / manifest["artifacts"]["persistence"]["path"]).read_bytes())
                scenario = json.loads((Path(directory) / manifest["artifacts"]["scenario"]["path"]).read_bytes())
                scenario["readiness_policy"] = policy
                with self.assertRaisesRegex(EvidenceError, "readiness: frozen policy"):
                    _verify_readiness_policy(manifest, directory, evidence, scenario)

    def test_future_readiness_rejects_stale_sample_gaps_timeout_and_delayed_initial_payload(self):
        for failure in ("sample_gap", "qualification_timeout", "dispatch_timeout", "stale_initial"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                manifest = persisted_manifest(directory, readiness=True)
                artifacts, result = manifest["artifacts"], manifest["result"]
                evidence = json.loads((Path(directory) / artifacts["persistence"]["path"]).read_bytes())
                scenario = json.loads((Path(directory) / artifacts["scenario"]["path"]).read_bytes())
                receipt = result["readiness"]
                if failure in ("sample_gap", "qualification_timeout"):
                    times = (0, 1500, 2000) if failure == "sample_gap" else (9001, 9501, 10001)
                    for sample, elapsed in zip(receipt["samples"], times):
                        sample.update(run_elapsed_ms=elapsed, server_received_at_ms=2200 + elapsed,
                                      frame_received_run_ms=elapsed, frame_received_at_ms=2200 + elapsed,
                                      client_sent_at_ms=2210 + elapsed)
                    receipt.update(qualified_run_ms=times[-1], qualified_at_ms=2200 + times[-1])
                    result["timeline"]["readiness_ended_ms"] = times[-1]
                    receipt["dispatch"].update(run_elapsed_ms=times[-1] + 50, checked_at_ms=2250 + times[-1],
                        frame_received_run_ms=times[-1] + 50, frame_received_at_ms=2250 + times[-1],
                        client_sent_at_ms=2260 + times[-1])
                    result["timeline"]["api_started_ms"] = times[-1] + 100
                elif failure == "dispatch_timeout":
                    receipt["dispatch"].update(run_elapsed_ms=10001, checked_at_ms=12201,
                        frame_received_run_ms=10001, frame_received_at_ms=12201, client_sent_at_ms=12211)
                    result["timeline"]["api_started_ms"] = 10001
                else:
                    result["initial"]["ageMs"] = 1450
                    receipt["samples"][-1]["age_ms"] = 1450
                    receipt["samples"][-1]["reported_age_ms"] = 1450
                    digest = hashlib.sha256(json.dumps(result["initial"], sort_keys=True,
                        separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
                    receipt["samples"][-1]["observation_sha256"] = digest
                    receipt["initial_observation_sha256"] = digest
                result["readinessSha256"] = write_artifact(directory, artifacts, "readiness", receipt)
                with self.assertRaisesRegex(EvidenceError, "readiness:"):
                    _verify_readiness_policy(manifest, directory, evidence, scenario)

    def test_readiness_gate_preserves_historical_policy_absence(self):
        # No newly imposed requirement or inferred acceptance is added to a
        # historical scenario that did not freeze this prerequisite.
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            artifacts = manifest["artifacts"]
            evidence = json.loads((Path(directory) / artifacts["persistence"]["path"]).read_bytes())
            scenario = json.loads((Path(directory) / artifacts["scenario"]["path"]).read_bytes())
            before = copy.deepcopy(manifest)
            self.assertIsNone(_verify_readiness_policy(manifest, directory, evidence, scenario))
            self.assertEqual(manifest, before)
            with patch("full_client_publish._probe_video", return_value=PROBE):
                self.assertEqual(validate_manifest(manifest, directory), {"ready": True, "reasons": []})

    def test_actual_timeline_shape_needs_no_synthetic_freshness_or_interruption_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            self.assertEqual(set(manifest["timeline"]), {"status", "api_started_ms", "api_ended_ms",
                                                         "program_started_ms", "program_ended_ms"})
            before = copy.deepcopy(manifest)
            result_bytes = (Path(directory) / manifest["artifacts"]["result"]["path"]).read_bytes()
            with patch("full_client_publish._probe_video", return_value=PROBE):
                self.assertEqual(validate_manifest(manifest, directory), {"ready": True, "reasons": []})
            self.assertEqual(manifest, before)
            self.assertEqual((Path(directory) / manifest["artifacts"]["result"]["path"]).read_bytes(), result_bytes)

    def test_rehashed_present_action_counters_cannot_hide_unacknowledged_attempts(self):
        for section, key in (("program", "actionAttempts"), ("controller", "actions")):
            for value in (0, 2, None, True, "1", 1.0, -1):
                with self.subTest(section=section, value=value), tempfile.TemporaryDirectory() as directory:
                    manifest = persisted_manifest(directory, readiness=True)
                    manifest["result"][section][key] = value
                    # Preserve the altered result's byte reference: the counter
                    # inconsistency itself, not a stale digest, must block it.
                    write_artifact(directory, manifest["artifacts"], "result", manifest["result"])
                    with patch("full_client_publish._probe_video", return_value=PROBE | {"duration_ms": 6100}):
                        verdict = validate_manifest(manifest, directory)
                    self.assertFalse(verdict["ready"], verdict)
                    self.assertTrue(any(f"result.{section}.{key}" in reason for reason in verdict["reasons"]), verdict)

    def test_optional_action_counters_preserve_historical_absence_and_consistent_values(self):
        for readiness in (False, True):
            for counters in ((), (("program", "actionAttempts"),), (("controller", "actions"),),
                             (("program", "actionAttempts"), ("controller", "actions"))):
                with self.subTest(readiness=readiness, counters=counters), tempfile.TemporaryDirectory() as directory:
                    manifest = persisted_manifest(directory, readiness=readiness)
                    for section, key in counters:
                        manifest["result"][section][key] = manifest["result"]["program"]["actions"]
                    write_artifact(directory, manifest["artifacts"], "result", manifest["result"])
                    before = copy.deepcopy(manifest)
                    probe = PROBE | {"duration_ms": 6100} if readiness else PROBE
                    with patch("full_client_publish._probe_video", return_value=probe):
                        self.assertEqual(validate_manifest(manifest, directory), {"ready": True, "reasons": []})
                    self.assertEqual(manifest, before)

    def test_actual_observations_and_acknowledgments_are_required_without_timeline_attestations(self):
        paths = [("initial",), ("final",), ("program", "steps", 0, "result"),
                 ("program", "steps", 1, "result", "observation")]
        for path in paths:
            for key in ("ageMs", "renderAgeMs"):
                for stale in (None, 1500, True):
                    with self.subTest(path=path, key=key, stale=stale), tempfile.TemporaryDirectory() as directory:
                        manifest = persisted_manifest(directory)
                        observation = manifest["result"]
                        for part in path:
                            observation = observation[part]
                        observation[key] = stale
                        write_artifact(directory, manifest["artifacts"], "result", manifest["result"])
                        verdict = validate_manifest(manifest, directory)
                        self.assertFalse(verdict["ready"])
                        self.assertTrue(any("observation" in reason for reason in verdict["reasons"]), verdict)
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            manifest["result"]["program"]["steps"][1]["result"]["accepted"] = False
            write_artifact(directory, manifest["artifacts"], "result", manifest["result"])
            self.assertFalse(validate_manifest(manifest, directory)["ready"])

    def test_supported_frozen_controller_envelopes_apply_uniformly_to_all_outcomes(self):
        for seconds in (22, 60):
            for outcome in ("program_complete", "death", "action_limit", "time_limit"):
                for span in (seconds * 1000, seconds * 1000 + 319, (seconds + 2) * 1000):
                    with self.subTest(seconds=seconds, outcome=outcome, span=span), tempfile.TemporaryDirectory() as directory:
                        manifest = persisted_manifest(directory, program_seconds=seconds, span_ms=span, outcome=outcome)
                        probe = PROBE | {"duration_ms": manifest["video"]["duration_ms"]}
                        with patch("full_client_publish._probe_video", return_value=probe):
                            self.assertEqual(validate_manifest(manifest, directory), {"ready": True, "reasons": []})
                        if outcome == "death":
                            self.assertEqual(manifest["score"]["metrics"]["net_xp"], -600)

    def test_controller_envelope_has_no_extra_clock_slack_and_time_limit_cannot_end_early(self):
        for seconds in (22, 60):
            for outcome in ("program_complete", "death", "action_limit", "time_limit"):
                with self.subTest(seconds=seconds, outcome=outcome), tempfile.TemporaryDirectory() as directory:
                    manifest = persisted_manifest(directory, program_seconds=seconds,
                                                  span_ms=(seconds + 2) * 1000 + 1, outcome=outcome)
                    verdict = validate_manifest(manifest, directory)
                    self.assertFalse(verdict["ready"])
                    self.assertTrue(any("termination envelope" in reason for reason in verdict["reasons"]), verdict)
            with tempfile.TemporaryDirectory() as directory:
                manifest = persisted_manifest(directory, program_seconds=seconds, span_ms=seconds * 1000 - 1,
                                              outcome="time_limit")
                verdict = validate_manifest(manifest, directory)
                self.assertFalse(verdict["ready"])
                self.assertTrue(any("active program budget" in reason for reason in verdict["reasons"]), verdict)

    def test_termination_allowance_cannot_be_spent_on_acknowledged_gameplay(self):
        for gameplay_ms, expected in ((22000, True), (22001, False), (23000, False)):
            with self.subTest(gameplay_ms=gameplay_ms), tempfile.TemporaryDirectory() as directory:
                manifest = persisted_manifest(directory, span_ms=23300, outcome="time_limit")
                artifacts, result = manifest["artifacts"], manifest["result"]
                press = copy.deepcopy(result["program"]["steps"][1])
                press["args"][1] = 1000
                waits = [3000] * 7 + ([gameplay_ms - 22000] if gameplay_ms > 22000 else [])
                result["program"]["steps"] = [press] + [
                    {"kind": "sdk", "method": "wait", "args": [duration], "result": {"waitedMs": duration}}
                    for duration in waits]
                code = "await sdk.pressKeys(['RIGHT'], 1000);\n" + "\n".join(
                    f"await sdk.wait({duration});" for duration in waits)
                result["programSha256"] = write_artifact(directory, artifacts, "program", code.encode(), raw=True)
                response = json.loads((Path(directory) / artifacts["api_response"]["path"]).read_bytes())
                response["output"][0]["content"][0]["text"] = json.dumps({"note": "synthetic active-time accounting", "code": code})
                write_artifact(directory, artifacts, "api_response", response)
                write_artifact(directory, artifacts, "result", result)
                with patch("full_client_publish._probe_video", return_value=PROBE | {"duration_ms": manifest["video"]["duration_ms"]}):
                    verdict = validate_manifest(manifest, directory)
                self.assertEqual(verdict["ready"], expected, verdict)
                if not expected:
                    self.assertTrue(any("active program budget" in reason for reason in verdict["reasons"]), verdict)

    def test_both_recorded_trial_contexts_bind_exact_frozen_artifact_hashes(self):
        for owner in ("result", "controller"):
            for alteration in ("missing", "null", "empty", "scenario", "baseline", "extra"):
                with self.subTest(owner=owner, alteration=alteration), tempfile.TemporaryDirectory() as directory:
                    manifest = persisted_manifest(directory)
                    result = manifest["result"]
                    target = result if owner == "result" else result["controller"]
                    if alteration == "missing":
                        target.pop("trialContext")
                    elif alteration == "null":
                        target["trialContext"] = None
                    elif alteration == "empty":
                        target["trialContext"] = {}
                    elif alteration == "scenario":
                        target["trialContext"]["scenario_fingerprint"] = "0" * 64
                    elif alteration == "baseline":
                        target["trialContext"]["baseline_sha256"] = "0" * 64
                    else:
                        target["trialContext"]["retroactive"] = True
                    write_artifact(directory, manifest["artifacts"], "result", result)
                    verdict = validate_manifest(manifest, directory)
                    self.assertFalse(verdict["ready"])
                    self.assertIn("trialContext", verdict["reasons"][0])

    def test_regenerated_scenario_or_settlement_policy_cannot_rebind_unchanged_raw_result(self):
        for mutation in (lambda scenario: scenario.update(instructions_sha256="1" * 64),
                         lambda scenario: scenario["settlement_policy"].update(capture_tail_ms=3000)):
            with tempfile.TemporaryDirectory() as directory:
                manifest = persisted_manifest(directory)
                artifacts = manifest["artifacts"]
                result_path = Path(directory) / artifacts["result"]["path"]
                original_result = result_path.read_bytes()
                scenario = json.loads((Path(directory) / artifacts["scenario"]["path"]).read_bytes())
                evidence = json.loads((Path(directory) / artifacts["persistence"]["path"]).read_bytes())
                mutation(scenario)
                fingerprint = write_artifact(directory, artifacts, "scenario", scenario)
                evidence["scenario_fingerprint"] = manifest["scenario"]["fingerprint"] = fingerprint
                write_artifact(directory, artifacts, "persistence", evidence)
                manifest["score"] = verify_trial_bundle(evidence, directory, artifacts)
                write_artifact(directory, artifacts, "score", manifest["score"])
                verdict = validate_manifest(manifest, directory)
                self.assertFalse(verdict["ready"])
                self.assertIn("trialContext", verdict["reasons"][0])
                self.assertEqual(result_path.read_bytes(), original_result)

    def test_recorded_program_and_controller_limits_must_be_supported_exact_integers(self):
        for key, values in (("programSeconds", (None, True, "22", 22.0, 23)),
                            ("controllerSeconds", (None, True, "24", 24.0, 23, 25))):
            for value in values:
                with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as directory:
                    manifest = persisted_manifest(directory)
                    manifest["result"]["controller"][key] = value
                    write_artifact(directory, manifest["artifacts"], "result", manifest["result"])
                    verdict = validate_manifest(manifest, directory)
                    self.assertFalse(verdict["ready"])
                    self.assertTrue(any("budgets.controller" in reason for reason in verdict["reasons"]), verdict)

    def test_recorded_limits_must_match_the_byte_verified_frozen_scenario(self):
        changes = [lambda scenario: scenario.pop("program_seconds"),
                   lambda scenario: scenario.update(program_seconds=60),
                   lambda scenario: scenario.update(program_seconds=True),
                   lambda scenario: scenario.pop("trial_budgets"),
                   lambda scenario: scenario["trial_budgets"].pop("controller_seconds"),
                   lambda scenario: scenario["trial_budgets"].update(controller_seconds=25),
                   lambda scenario: scenario["trial_budgets"].update(controller_seconds=24.0)]
        for change in changes:
            with tempfile.TemporaryDirectory() as directory:
                manifest = persisted_manifest(directory)
                artifacts = manifest["artifacts"]
                scenario = json.loads((Path(directory) / artifacts["scenario"]["path"]).read_bytes())
                evidence = json.loads((Path(directory) / artifacts["persistence"]["path"]).read_bytes())
                change(scenario)
                fingerprint = write_artifact(directory, artifacts, "scenario", scenario)
                evidence["scenario_fingerprint"] = manifest["scenario"]["fingerprint"] = fingerprint
                write_artifact(directory, artifacts, "persistence", evidence)
                manifest["score"] = verify_trial_bundle(evidence, directory, artifacts)
                write_artifact(directory, artifacts, "score", manifest["score"])
                verdict = validate_manifest(manifest, directory)
                self.assertFalse(verdict["ready"])
                self.assertIn("recorded program/termination limits", verdict["reasons"][0])

    def test_publication_program_budget_cannot_differ_from_recorded_active_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            manifest["budgets"]["program_ms"] += 1
            verdict = validate_manifest(manifest, directory)
            self.assertFalse(verdict["ready"])
            self.assertTrue(any("budgets.controller" in reason for reason in verdict["reasons"]), verdict)

    def test_total_run_budget_is_not_extended_by_clock_precision_tolerance(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            manifest["budgets"]["run_ms"] = manifest["result"]["timing"]["elapsedMs"] - 1
            verdict = validate_manifest(manifest, directory)
            self.assertFalse(verdict["ready"])
            self.assertTrue(any("budgets.run_ms" in reason for reason in verdict["reasons"]), verdict)

    def test_zero_action_model_program_is_not_repaired_or_filtered(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory, span_ms=915)
            artifacts = manifest["artifacts"]
            code = "async function run() { await sdk.pressKeys(['RIGHT'], 200); }"
            result = manifest["result"]
            result["program"].update(actions=0, steps=[])
            result["programSha256"] = write_artifact(directory, artifacts, "program", code.encode(), raw=True)
            response = json.loads((Path(directory) / artifacts["api_response"]["path"]).read_bytes())
            response["output"][0]["content"][0]["text"] = json.dumps({"note": "synthetic uninvoked declaration", "code": code})
            write_artifact(directory, artifacts, "api_response", response)
            write_artifact(directory, artifacts, "result", result)
            with patch("full_client_publish._probe_video", return_value=PROBE | {"duration_ms": manifest["video"]["duration_ms"]}):
                self.assertEqual(validate_manifest(manifest, directory), {"ready": True, "reasons": []})
            self.assertEqual((Path(directory) / artifacts["program"]["path"]).read_text(), code)

    def test_upload_status_is_required_and_cannot_claim_another_run_or_unsettled_upload(self):
        changes = [lambda r: r.update(run_id="other-run"), lambda r: r.update(character_id=True),
                   lambda r: r.update(observed_at_ms=7301), lambda r: r.update(source="model_claim"),
                   lambda r: r["status"]["bridge"]["run"].update(status="running"),
                   lambda r: r["status"]["bridge"]["run"].update(recordingStatus="pending"),
                   lambda r: r["status"]["bridge"]["run"].update(evidenceStatus="pending"),
                   lambda r: r["status"]["bridge"]["run"].update(workerActive=True),
                   lambda r: r["status"]["bridge"]["run"].update(leaseReleasePending=True),
                   lambda r: r["status"]["bridge"]["run"].update(leaseReleasePending="false"),
                   lambda r: r["status"]["bridge"].update(browserReleasePending=True),
                   lambda r: r["status"]["session"].update(artifactsSettled=False)]
        for change in changes:
            with tempfile.TemporaryDirectory() as directory:
                manifest = persisted_manifest(directory)
                artifacts = manifest["artifacts"]
                receipt = json.loads((Path(directory) / artifacts["upload_status"]["path"]).read_text())
                change(receipt)
                write_artifact(directory, artifacts, "upload_status", receipt)
                with patch("full_client_publish._probe_video", return_value=PROBE):
                    self.assertFalse(validate_manifest(manifest, directory)["ready"])
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            manifest["artifacts"].pop("upload_status")
            self.assertFalse(validate_manifest(manifest, directory)["ready"])

    def test_settlement_cutoff_validator_enforces_frozen_limits_independently(self):
        for upload, disconnect, logout in ((6999, 7400, 8000), (7401, 7400, 8000),
                                           (12001, 12002, 12003), (7300, 12001, 12002),
                                           (7300, 7400, 12401)):
            with tempfile.TemporaryDirectory() as directory:
                manifest = persisted_manifest(directory)
                arts = manifest["artifacts"]
                evidence = json.loads((Path(directory) / arts["persistence"]["path"]).read_text())
                scenario = json.loads((Path(directory) / arts["scenario"]["path"]).read_text())
                evidence["session"].update(upload_observed_at_ms=upload, disconnect_requested_at_ms=disconnect,
                                             logged_out_at_ms=logout)
                receipt = json.loads((Path(directory) / arts["upload_status"]["path"]).read_text())
                receipt["observed_at_ms"] = upload
                write_artifact(directory, arts, "upload_status", receipt)
                with self.assertRaisesRegex(ValueError, "post-program cutoff"):
                    _verify_settlement_policy(manifest, directory, evidence, scenario)

    def test_policy_cannot_be_missing_relaxed_or_extend_tail_from_result_end(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            arts = manifest["artifacts"]
            evidence = json.loads((Path(directory) / arts["persistence"]["path"]).read_text())
            scenario = json.loads((Path(directory) / arts["scenario"]["path"]).read_text())
            _verify_settlement_policy(manifest, directory, evidence, scenario)
            for policy in (None, POLICY | {"disconnect_after_program_ms": 10000}):
                with self.assertRaisesRegex(ValueError, "policy frozen"):
                    _verify_settlement_policy(manifest, directory, evidence, scenario | {"settlement_policy": policy})
            capture = json.loads((Path(directory) / arts["capture"]["path"]).read_text())
            # This would fit result-ended+2s but exceeds program-ended+2s.
            capture["end_wall_ms"] = 9000
            write_artifact(directory, arts, "capture", capture)
            with self.assertRaisesRegex(ValueError, "post-program tail"):
                _verify_settlement_policy(manifest, directory, evidence, scenario)

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
                       "format": {"duration": "4.0"},
                       "packets": [{"pts_time": str(i / 30), "duration_time": str(1 / 30), "flags": "__"} for i in range(120)]}
                kwargs["stdout"].write(json.dumps(raw).encode())
                return SimpleNamespace(returncode=0)

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
                       "format": {"duration": "4.0"},
                       "packets": [{"pts_time": str(i / 30), "duration_time": str(1 / 30), "flags": "__"} for i in range(120)]}
                kwargs["stdout"].write(json.dumps(raw).encode())
                return SimpleNamespace(returncode=0)

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


class VideoTimestampProbeTests(unittest.TestCase):
    @staticmethod
    def packets():
        # Explicit synthetic VFR packets; absent WebM header duration is normal.
        return {"streams": [{"width": 800, "height": 720, "nb_read_frames": "4"}], "format": {},
                "packets": [{"pts_time": str(t), "flags": "__"} for t in (0, .038, .071)]
                           + [{"pts_time": ".104", "duration_time": ".033", "flags": "__"}]}

    def test_absent_webm_duration_uses_actual_variable_packet_timestamps(self):
        value = _measure_video_probe(self.packets())
        self.assertAlmostEqual(value["duration_ms"], 137)
        self.assertEqual(value["frames"], 4)
        self.assertEqual((value["width"], value["height"]), (800, 720))

    def test_missing_final_packet_duration_is_a_conservative_presentation_span(self):
        probe = self.packets()
        probe["packets"][-1].pop("duration_time")
        self.assertAlmostEqual(_measure_video_probe(probe)["duration_ms"], 104)

    def test_header_duration_must_agree_with_the_complete_saved_stream(self):
        probe = self.packets()
        probe["format"]["duration"] = ".137"
        self.assertAlmostEqual(_measure_video_probe(probe)["duration_ms"], 137)
        for header in ("4", "NaN", "inf", "0"):
            probe["format"]["duration"] = header
            with self.assertRaises(ValueError):
                _measure_video_probe(probe)

    def test_corruption_missing_frames_and_timestamp_resource_bounds_fail_closed(self):
        mutations = [
            lambda p: p["streams"][0].update(nb_read_frames="3"),
            lambda p: p["streams"][0].update(nb_read_frames="100001"),
            lambda p: p["streams"][0].update(width=20000),
            lambda p: p["packets"][1].update(flags="_C"),
            lambda p: p["packets"][1].update(flags="_D"),
            lambda p: p["packets"][1].pop("pts_time"),
            lambda p: p["packets"][1].update(pts_time="NaN"),
            lambda p: p["packets"][1].update(pts_time=True),
            lambda p: p["packets"][1].update(pts_time="0"),
            lambda p: p["packets"][-1].update(pts_time="2"),
            lambda p: p["packets"][-1].update(pts_time="126"),
            lambda p: p["packets"][-1].update(duration_time="-1"),
            lambda p: p["packets"][-1].update(duration_time="2"),
        ]
        for mutation in mutations:
            probe = self.packets()
            mutation(probe)
            with self.assertRaises((ValueError, KeyError)):
                _measure_video_probe(probe)

    def test_clean_packet_boundary_truncation_cannot_override_independent_capture_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = persisted_manifest(directory)
            probe = {"streams": [{"width": 1024, "height": 768, "nb_read_frames": "3"}], "format": {},
                     "packets": [{"pts_time": str(i), "duration_time": "1", "flags": "__"} for i in range(3)]}
            measured = _measure_video_probe(probe)
            write_artifact(directory, manifest["artifacts"], "video_probe", measured | {"video_sha256": manifest["video"]["sha256"]})
            with patch("full_client_publish._probe_video", return_value=measured):
                self.assertFalse(validate_manifest(manifest, directory)["ready"])

    def test_probe_limits_are_hard_caps_and_respect_inherited_limits(self):
        import resource
        with patch("full_client_publish.resource.getrlimit", return_value=(resource.RLIM_INFINITY, resource.RLIM_INFINITY)), \
             patch("full_client_publish.resource.setrlimit") as limit:
            _video_probe_limits()
            self.assertEqual({call.args[0]: call.args[1] for call in limit.call_args_list}, {
                resource.RLIMIT_FSIZE: (JSON_LIMIT, JSON_LIMIT),
                resource.RLIMIT_AS: (768 * 1024**2, 768 * 1024**2), resource.RLIMIT_CPU: (30, 30)})
        with patch("full_client_publish.resource.getrlimit", return_value=(7, 7)), \
             patch("full_client_publish.resource.setrlimit") as limit:
            _video_probe_limits()
            self.assertTrue(all(call.args[1] == (7, 7) for call in limit.call_args_list))

    def test_probe_bounds_subprocess_output_stderr_and_timeout_on_verified_descriptor(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recording.webm"
            raw = b"synthetic mocked media"
            path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            def process(command, **kwargs):
                fd, = kwargs["pass_fds"]
                self.assertEqual(os.pread(fd, len(raw), 0), raw)
                self.assertTrue(command[-1].endswith("/fd/" + str(fd)))
                self.assertEqual(kwargs["timeout"], 30)
                self.assertIs(kwargs["preexec_fn"], _video_probe_limits)
                self.assertNotIn("capture_output", kwargs)
                self.assertIn("-show_packets", command)
                self.assertIn("-count_frames", command)
                kwargs["stdout"].write(json.dumps(self.packets()).encode())
                return SimpleNamespace(returncode=0)
            with patch("full_client_publish.subprocess.run", side_effect=process):
                self.assertAlmostEqual(_probe_video(path, digest)["duration_ms"], 137)
            def corrupt(command, **kwargs):
                kwargs["stderr"].write(b"File ended prematurely")
                return process(command, **kwargs)
            with patch("full_client_publish.subprocess.run", side_effect=corrupt):
                with self.assertRaisesRegex(ValueError, "corruption"):
                    _probe_video(path, digest)
            def huge(command, **kwargs):
                kwargs["stdout"].seek(JSON_LIMIT)
                kwargs["stdout"].write(b"x")
                return SimpleNamespace(returncode=0)
            with patch("full_client_publish.subprocess.run", side_effect=huge):
                with self.assertRaisesRegex(ValueError, "output limits"):
                    _probe_video(path, digest)
            with patch("full_client_publish.subprocess.run", side_effect=subprocess.TimeoutExpired("ffprobe", 30)):
                with self.assertRaisesRegex(ValueError, "timed out"):
                    _probe_video(path, digest)
            with patch("full_client_publish.subprocess.run") as call:
                with self.assertRaises(ValueError):
                    _probe_video(path, "0" * 64)
                call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
