"""Synthetic persistence evidence; these tests are not actual scored game runs."""
import contextlib
import copy
import io
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from full_client_score import (EvidenceError, SOURCE, main, open_verified_artifact, read_artifact_bytes,
                               score_trial, verify_trial_bundle, verified_artifact)


def fixture():
    row = {"character_id": 7, "account_id": 9, "level": 180, "exp": 1000, "hp": 12000}
    return {
        "schema_version": 1, "source": SOURCE, "run_id": "synthetic-trial",
        "scenario_fingerprint": "a" * 64,
        "baseline": {"sha256": "b" * 64, "character": copy.deepcopy(row)},
        "reset": {"run_id": "synthetic-trial", "baseline_sha256": "b" * 64,
                  "world_lock_held": True, "queue_lock_held": True,
                  "server_stopped": True, "verified": True, "completed_at_ms": 1000},
        "initial": {"source": SOURCE, "run_id": "synthetic-trial", "account_logged_in": 0,
                    "captured_at_ms": 1100, "evidence_sha256": "c" * 64,
                    "character": copy.deepcopy(row)},
        "final": {"source": SOURCE, "run_id": "synthetic-trial", "account_logged_in": 0,
                  "captured_at_ms": 8200, "evidence_sha256": "d" * 64,
                  "character": copy.deepcopy(row)},
        "session": {
            "run_id": "synthetic-trial", "server_instance_id": "fresh-process-1",
            "disconnect_kind": "normal", "world_lock_held_throughout": True,
            "queue_lock_held_throughout": True, "server_started_at_ms": 1200,
            "login_at_ms": 2000, "api_started_at_ms": 2200, "api_ended_at_ms": 3000,
            "controller_started_at_ms": 3100, "controller_ended_at_ms": 7000,
            "disconnect_requested_at_ms": 7100, "logged_out_at_ms": 8000,
            "save": {"status": "confirmed", "run_id": "synthetic-trial",
                     "server_instance_id": "fresh-process-1", "character_id": 7,
                     "committed_at_ms": 7900, "evidence_sha256": "e" * 64,
                     "logs_sha256": "f" * 64, "log_checked_from_ms": 1200,
                     "log_checked_through_ms": 8300, "save_error_count": 0},
        },
    }


def write_artifact(directory, artifacts, name, value, *, raw=False):
    content = value if raw else json.dumps(value, sort_keys=True).encode()
    path = Path(directory) / (name + (".bin" if raw else ".json"))
    path.write_bytes(content)
    artifacts[name] = {"path": path.name, "sha256": hashlib.sha256(content).hexdigest()}
    return artifacts[name]["sha256"]


def bundle_fixture(directory, scenario=None):
    """Synthetic files only: never evidence of a real database, API, or game."""
    evidence, artifacts = fixture(), {}
    baseline = write_artifact(directory, artifacts, "baseline", b"synthetic database baseline", raw=True)
    evidence["baseline"]["sha256"] = evidence["reset"]["baseline_sha256"] = baseline
    evidence["baseline"]["keymap"] = [[29, 5, 52], [57, 5, 53], [85, 5, 52]]
    evidence["scenario_fingerprint"] = write_artifact(directory, artifacts, "scenario", scenario or {"id": "synthetic"})
    for name in ("initial", "final"):
        evidence[name].update(schema_version=1, keymap=copy.deepcopy(evidence["baseline"]["keymap"]))
        raw = {key: value for key, value in evidence[name].items() if key != "evidence_sha256"}
        evidence[name]["evidence_sha256"] = write_artifact(directory, artifacts, name + "_db", raw)
    identity = {"run_id": evidence["run_id"], "server_instance_id": evidence["session"]["server_instance_id"],
                "character_id": 7, "account_id": 9}
    receipt = {"schema_version": 1, "source": SOURCE, "kind": "save_committed", **identity,
               "committed_at_ms": evidence["session"]["save"]["committed_at_ms"]}
    evidence["session"]["save"]["evidence_sha256"] = write_artifact(
        directory, artifacts, "save", (json.dumps(receipt) + "\n").encode(), raw=True)
    evidence["session"]["save"]["native_logs_sha256"] = write_artifact(
        directory, artifacts, "native_log", b"MapleBench persistence journal initialized\n", raw=True)
    events = [{"event": event, "at_ms": at, **identity} for event, at in
              (("server_started", 1200), ("login", 2000), ("logged_out", 8000), ("collection_completed", 8200))]
    evidence["session"]["save"]["logs_sha256"] = write_artifact(
        directory, artifacts, "server_log", "".join(json.dumps(row) + "\n" for row in events).encode(), raw=True)
    for name in ("reset", "session"):
        write_artifact(directory, artifacts, name, evidence[name])
    write_artifact(directory, artifacts, "persistence", evidence)
    return evidence, artifacts


class PersistenceScoreTests(unittest.TestCase):
    def test_gain_zero_and_death_penalty_are_not_filtered(self):
        for xp, hp, expected in ((1400, 11000, 400), (1000, 12000, 0), (400, 0, -600)):
            with self.subTest(xp=xp):
                evidence = fixture()
                evidence["final"]["character"].update(exp=xp, hp=hp)
                original = copy.deepcopy(evidence)
                score = score_trial(evidence)
                self.assertEqual(score["metrics"], {"net_xp": expected})
                self.assertEqual(score["alive_at_logout"], hp > 0)
                self.assertEqual(score["timing"], {"session_ms": 6000, "api_ms": 800,
                                                  "controller_ms": 3900, "settlement_ms": 1000})
                self.assertFalse(score["publication_eligible"])
                self.assertEqual(evidence, original)

    def assert_rejected(self, path, value, reason):
        evidence = fixture()
        target = evidence
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
        with self.assertRaisesRegex(EvidenceError, reason):
            score_trial(evidence)

    def test_client_telemetry_and_mismatched_trial_cannot_be_scored(self):
        for name in ("initial", "final"):
            self.assert_rejected((name, "source"), "client telemetry", "source")
            self.assert_rejected((name, "run_id"), "another-run", "run_id")
            self.assert_rejected((name, "character", "account_id"), 10, "account_id")
            self.assert_rejected((name, "character", "character_id"), 8, "character_id")
        for name in ("reset", "session"):
            self.assert_rejected((name, "run_id"), "another-run", "run_id")

    def test_reset_requires_both_locks_stopped_server_and_frozen_parity(self):
        for field in ("world_lock_held", "queue_lock_held", "server_stopped", "verified"):
            for invalid in (False, None, 1, "true"):
                self.assert_rejected(("reset", field), invalid, field)
        self.assert_rejected(("reset", "baseline_sha256"), "0" * 64, "baseline")
        self.assert_rejected(("initial", "character", "exp"), 999, "restored row")
        for field in ("world_lock_held_throughout", "queue_lock_held_throughout"):
            self.assert_rejected(("session", field), False, "locks")

    def test_level_transition_is_not_reported_as_negative_xp(self):
        self.assert_rejected(("final", "character", "level"), 181, "level transitions")

    def test_offline_without_save_proof_is_insufficient(self):
        self.assert_rejected(("session", "save", "status"), "unknown", "offline status alone")
        self.assert_rejected(("session", "save", "save_error_count"), 1, "save errors")
        self.assert_rejected(("session", "save", "server_instance_id"), "old-process", "receipt")
        self.assert_rejected(("session", "save", "run_id"), "old-run", "receipt")
        self.assert_rejected(("session", "save", "character_id"), 8, "another character")
        self.assert_rejected(("session", "disconnect_kind"), "server_killed", "ordinary client")
        for name in ("initial", "final"):
            for state in (1, 2):
                self.assert_rejected((name, "account_logged_in"), state, "offline account")

    def test_stale_or_incomplete_evidence_is_rejected(self):
        for path, value, reason in (
            (("final", "captured_at_ms"), 7000, "timeline"),
            (("initial", "captured_at_ms"), 1400, "timeline"),
            (("session", "api_ended_at_ms"), 4000, "timeline"),
            (("session", "save", "committed_at_ms"), 4000, "during normal logout"),
            (("session", "save", "log_checked_from_ms"), 2000, "log review"),
            (("session", "save", "log_checked_through_ms"), 8100, "log review"),
            (("session", "save", "evidence_sha256"), None, "digest"),
        ):
            with self.subTest(path=path):
                self.assert_rejected(path, value, reason)

    def test_bad_numeric_types_cannot_produce_scores(self):
        for value in (True, False, "1000", -1, 1.5, float("nan"), float("inf"), 2**80, None):
            self.assert_rejected(("final", "character", "exp"), value, "bounded integer")
        self.assert_rejected(("final", "account_logged_in"), False, "bounded integer")
        self.assert_rejected(("session", "save", "save_error_count"), False, "bounded integer")
        self.assert_rejected(("final",), [], "object")

    def test_digest_is_stable_and_covers_the_evidence(self):
        evidence = fixture()
        first = score_trial(evidence)["evidence_sha256"]
        reordered = dict(reversed(list(evidence.items())))
        self.assertEqual(first, score_trial(reordered)["evidence_sha256"])
        evidence["final"]["character"]["exp"] += 1
        self.assertNotEqual(first, score_trial(evidence)["evidence_sha256"])
        evidence["extra"] = float("nan")
        with self.assertRaisesRegex(EvidenceError, "finite JSON"):
            score_trial(evidence)

    def test_cli_rejects_duplicates_and_does_not_echo_private_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            for raw, expected in ((json.dumps(fixture()), 0),
                                  ('{"source":"private-marker","source":"other"}', 1),
                                  ('private-marker not json', 2)):
                path.write_text(raw)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    status = main([str(path)])
                self.assertEqual(status, expected)
                result = json.loads(out.getvalue())
                self.assertEqual(result["scored"], expected == 0)
                self.assertNotIn("private-marker", out.getvalue())


class TrialBundleTests(unittest.TestCase):
    def test_journal_consumers_reject_swaps_and_growth_after_initial_hash(self):
        for label in ("save", "server_log"):
            for action in ("replace", "grow"):
                with self.subTest(label=label, action=action), tempfile.TemporaryDirectory() as directory:
                    artifacts = {}
                    write_artifact(directory, artifacts, label, b'{"old":1}\n', raw=True)
                    path = Path(directory) / artifacts[label]["path"]

                    @contextlib.contextmanager
                    def changed_after_hash(*args, **kwargs):
                        with open_verified_artifact(*args, **kwargs) as stream:
                            if action == "replace":
                                replacement = path.with_suffix(".replacement")
                                replacement.write_bytes(b'{"new":1}\n')
                                replacement.replace(path)
                            else:
                                path.write_bytes(b"x" * 33)
                            yield stream

                    with patch("full_client_score.open_verified_artifact", changed_after_hash):
                        with self.assertRaises(EvidenceError):
                            read_artifact_bytes(directory, artifacts[label], label, maximum=32)

    def test_byte_verified_score_still_does_not_grant_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, artifacts = bundle_fixture(directory)
            score = verify_trial_bundle(evidence, Path(directory), artifacts)
            self.assertTrue(score["artifacts_verified"])
            self.assertFalse(score["publication_eligible"])
            self.assertEqual(score["metrics"], {"net_xp": 0})

    def test_missing_and_tampered_files_fail_closed(self):
        for name in ("baseline", "scenario", "persistence", "reset", "initial_db", "final_db", "session", "save", "server_log", "native_log"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                evidence, artifacts = bundle_fixture(directory)
                path = Path(directory) / artifacts[name]["path"]
                path.write_bytes(path.read_bytes() + b"tampered")
                with self.assertRaises(EvidenceError):
                    verify_trial_bundle(evidence, directory, artifacts)
                path.unlink()
                with self.assertRaises(EvidenceError):
                    verify_trial_bundle(evidence, directory, artifacts)

    def test_rehashed_database_export_cannot_replace_scored_row(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, artifacts = bundle_fixture(directory)
            raw = {key: value for key, value in evidence["final"].items() if key != "evidence_sha256"}
            raw["character"] = raw["character"] | {"exp": 999999}
            evidence["final"]["evidence_sha256"] = write_artifact(directory, artifacts, "final_db", raw)
            write_artifact(directory, artifacts, "persistence", evidence)
            with self.assertRaisesRegex(EvidenceError, "database export differs"):
                verify_trial_bundle(evidence, directory, artifacts)

    def test_native_commit_identity_and_failure_are_checked_after_rehash(self):
        for change in ({"kind": "save_failed"}, {"run_id": "old-run"},
                       {"server_instance_id": "old-process"}, {"account_id": 10}, {"committed_at_ms": 7800}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                evidence, artifacts = bundle_fixture(directory)
                path = Path(directory) / artifacts["save"]["path"]
                receipt = json.loads(path.read_text()) | change
                evidence["session"]["save"]["evidence_sha256"] = write_artifact(
                    directory, artifacts, "save", (json.dumps(receipt) + "\n").encode(), raw=True)
                write_artifact(directory, artifacts, "session", evidence["session"])
                write_artifact(directory, artifacts, "persistence", evidence)
                with self.assertRaisesRegex(EvidenceError, "save journal"):
                    verify_trial_bundle(evidence, directory, artifacts)

    def test_phase_event_cannot_be_missing_or_misdated(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, artifacts = bundle_fixture(directory)
            path = Path(directory) / artifacts["server_log"]["path"]
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            rows[-1]["at_ms"] += 1
            evidence["session"]["save"]["logs_sha256"] = write_artifact(
                directory, artifacts, "server_log", "".join(json.dumps(row) + "\n" for row in rows).encode(), raw=True)
            write_artifact(directory, artifacts, "session", evidence["session"])
            write_artifact(directory, artifacts, "persistence", evidence)
            with self.assertRaisesRegex(EvidenceError, "collection_completed"):
                verify_trial_bundle(evidence, directory, artifacts)

    def test_native_journal_failure_rejects_a_complete_looking_commit_record(self):
        # A write may leave a whole JSON commit line even if force/fsync fails.
        # The original native stderr record must invalidate those visible bytes.
        for marker in (b"MapleBench persistence journal failed; trial evidence is invalid\n",
                       b"Error saving chr synthetic-character\n"):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as directory:
                evidence, artifacts = bundle_fixture(directory)
                evidence["session"]["save"]["native_logs_sha256"] = write_artifact(
                    directory, artifacts, "native_log", b"MapleBench persistence journal initialized\n" + marker,
                    raw=True)
                write_artifact(directory, artifacts, "session", evidence["session"])
                write_artifact(directory, artifacts, "persistence", evidence)
                with self.assertRaisesRegex(EvidenceError, "native log: journal I/O"):
                    verify_trial_bundle(evidence, directory, artifacts)

    def test_disabled_reused_or_unbound_native_log_cannot_certify_health(self):
        for raw in (b"ordinary server startup without native instrumentation\n",
                    b"MapleBench persistence journal initialized\n" * 2):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as directory:
                evidence, artifacts = bundle_fixture(directory)
                evidence["session"]["save"]["native_logs_sha256"] = write_artifact(
                    directory, artifacts, "native_log", raw, raw=True)
                write_artifact(directory, artifacts, "session", evidence["session"])
                write_artifact(directory, artifacts, "persistence", evidence)
                with self.assertRaisesRegex(EvidenceError, "initialization"):
                    verify_trial_bundle(evidence, directory, artifacts)
        with tempfile.TemporaryDirectory() as directory:
            evidence, artifacts = bundle_fixture(directory)
            evidence["session"]["save"].pop("native_logs_sha256")
            write_artifact(directory, artifacts, "session", evidence["session"])
            write_artifact(directory, artifacts, "persistence", evidence)
            with self.assertRaises(EvidenceError):
                verify_trial_bundle(evidence, directory, artifacts)

    def test_escape_symlink_and_duplicate_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, artifacts = bundle_fixture(directory)
            for path in ("../outside", "/absolute", "a/../baseline.bin", "./baseline.bin", "a//b", "https://bad"):
                with self.subTest(path=path), self.assertRaises(EvidenceError):
                    verified_artifact(directory, artifacts["baseline"] | {"path": path}, "baseline")
            (Path(directory) / "link").symlink_to(Path(directory) / artifacts["baseline"]["path"])
            with self.assertRaisesRegex(EvidenceError, "symlinks"):
                verified_artifact(directory, artifacts["baseline"] | {"path": "link"}, "baseline")
            write_artifact(directory, artifacts, "reset", b'{"run_id":"x","run_id":"y"}', raw=True)
            with self.assertRaisesRegex(EvidenceError, "duplicate"):
                verify_trial_bundle(evidence, directory, artifacts)


if __name__ == "__main__":
    unittest.main()
