"""Offline command admission using real private receipts and operation flocks.

Only temporary fixture files are changed; no trial, lifecycle, service or API
operation is invoked. Lost replies occur after real create-only publication.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import full_client_operation_admission as admission
import full_client_operation_gate as gate
import full_client_operation_join as join

FIRST, SECOND = "1" * 32, "2" * 32


def file_ref(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write_json(path, value):
    path.write_bytes(gate.encoded(value))
    path.chmod(0o600)
    return file_ref(path)


class OperationAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.root.chmod(0o700)
        self.uid = os.geteuid()
        self.attempts = self.root / "attempts"
        self.attempts.mkdir(mode=0o700)
        self.pin = gate.initialize_registry(self.attempts, owner_uid=self.uid)
        self.registry = self.attempts / ".operations"
        self.subject = {"action": "synthetic_offline_action", "budget": 1}
        self.extra = self.root / "entry.py"
        self.extra.write_bytes(b"# Protected synthetic entry; never executed.\n")
        self.extra.chmod(0o600)
        self.sources = [file_ref(Path(module.__file__).resolve()) for module in (gate, join, admission)]
        self.sources.append(file_ref(self.extra))
        self.value = {"schema_version": 1, "operation_id": FIRST, "kind": "finite_group",
                      "gate": self.pin, "subject": self.subject, "source_files": self.sources}
        self.authority = write_json(self.root / "authority.json", self.value)
        self.evidence = write_json(self.root / "evidence.json", {"synthetic_terminal_observation": True})

    def enter(self, *, authority=None, subject=None, kind="finite_group", **kwargs):
        return admission.admitted(authority or self.authority,
            self.subject if subject is None else subject, kind, self.attempts,
            owner_uid=self.uid, required_sources=(self.extra,), **kwargs)

    def second_authority(self, *, kind="standalone_trial"):
        value = copy.deepcopy(self.value)
        value.update(operation_id=SECOND, kind=kind)
        return write_json(self.root / "second-authority.json", value)

    def files(self):
        return {str(path.relative_to(self.root)): (path.stat().st_ino, path.stat().st_mode, path.read_bytes())
                for path in self.root.rglob("*") if path.is_file()}

    def receipt_path(self):
        return self.root / ".operation-receipts" / FIRST / "terminal-receipt.json"

    def test_initial_claim_is_durable_and_exception_keeps_pending_for_explicit_reconciliation(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic caller failure"):
            with self.enter() as active:
                claim = copy.deepcopy(active.claim)
                self.assertFalse(active.completed)
                self.assertIsNone(active.terminal)
                self.assertEqual(json.loads(Path(claim["path"]).read_bytes())["authority"], self.authority)
                self.assertEqual(file_ref(Path(claim["path"])), claim)
                raise RuntimeError("synthetic caller failure")
        self.assertFalse((self.registry / FIRST / "terminal.json").exists())
        with self.assertRaisesRegex(gate.GateError, "pending_operation"):
            with self.enter():self.fail("implicit replay was admitted")
        second = self.second_authority()
        with self.assertRaisesRegex(gate.GateError, "pending_operation"):
            with self.enter(authority=second, kind="standalone_trial"):self.fail("another command passed pending claim")
        self.assertFalse((self.registry / SECOND).exists())
        with self.enter(claim_ref=claim) as reconciled:
            self.assertEqual(reconciled.claim, claim)
            self.assertFalse(reconciled.completed)

    def test_completed_reconciliation_returns_exact_terminal_and_does_not_reenter_operation(self):
        operations = []
        with self.enter() as active:
            claim = active.claim
            operations.append("synthetic operation")
            terminal = active.finish([self.evidence])
            self.assertTrue(active.completed)
            self.assertEqual(active.terminal, terminal)
            with self.assertRaisesRegex(admission.AdmissionError, "operation_already_completed"):
                active.finish([self.evidence])
        before = self.files()
        with self.enter(claim_ref=claim) as reconciled:
            if not reconciled.completed:operations.append("replayed operation")
            self.assertTrue(reconciled.completed)
            self.assertEqual(reconciled.terminal, terminal)
        self.assertEqual(operations, ["synthetic operation"])
        self.assertEqual(self.files(), before)
        with self.assertRaisesRegex(gate.GateError, "operation_exists"):
            with self.enter():self.fail("completed ID was reused")
        with self.enter(authority=self.second_authority(), kind="standalone_trial") as next_command:
            self.assertFalse(next_command.completed)
            self.assertNotEqual(next_command.claim, claim)

    def test_read_only_check_has_no_claim_or_receipt_and_still_excludes_pending_work(self):
        before = self.files()
        with self.enter(read_only=True) as check:
            self.assertIsNone(check.claim)
            self.assertIsNone(check.terminal)
            with self.assertRaisesRegex(admission.AdmissionError, "operation_already_completed"):
                check.finish([self.evidence])
        self.assertEqual(self.files(), before)
        self.assertEqual([path.name for path in self.registry.iterdir()], [".gate.lock"])
        with self.enter() as active:claim = active.claim
        with self.assertRaisesRegex(gate.GateError, "pending_operation"):
            with self.enter(read_only=True):self.fail("check ignored pending work")
        with self.assertRaisesRegex(admission.AdmissionError, "operation_check_cannot_reconcile"):
            with self.enter(read_only=True, claim_ref=claim):self.fail("check reconciled a claim")

    def test_exact_private_authority_and_subject_are_required_before_claim_creation(self):
        cases = ((dict(self.authority, sha256="0" * 64), self.subject, "reference_changed"),
                 (self.authority, dict(self.subject, budget=True), "operation_subject_mismatch"),
                 (self.authority, dict(self.subject, budget=2), "operation_subject_mismatch"))
        for authority, subject, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(gate.GateError, code):
                with self.enter(authority=authority, subject=subject):self.fail("unbound authority admitted")
        path = Path(self.authority["path"])
        path.chmod(0o644)
        with self.assertRaisesRegex(gate.GateError, "private_file_required"):
            with self.enter():self.fail("public authority admitted")
        path.chmod(0o600)
        public = self.root / "public";public.mkdir(mode=0o755);public.chmod(0o755)
        ref = write_json(public / "authority.json", self.value)
        with self.assertRaisesRegex(gate.GateError, "private_directory_required"):
            with self.enter(authority=ref):self.fail("public authority parent admitted")
        self.assertFalse((self.registry / FIRST).exists())

    def test_owner_and_gate_identity_are_not_caller_booleans(self):
        for uid in (False, self.uid + 1):
            with self.subTest(uid=uid), self.assertRaisesRegex(admission.AdmissionError, "operation_owner_mismatch"):
                admission.validate_authority(self.authority, self.subject, "finite_group", self.attempts, owner_uid=uid)
        value = copy.deepcopy(self.value);value["gate"]["inode"] += 1
        bad = write_json(self.root / "bad-gate-authority.json", value)
        with self.assertRaisesRegex(gate.GateError, "gate_pin_changed"):
            with self.enter(authority=bad):self.fail("substituted gate admitted")
        self.assertFalse((self.registry / FIRST).exists())

    def test_required_loaded_sources_and_actual_bytes_are_bound(self):
        for mutate, code in ((lambda v:v["source_files"].pop(), "operation_source_pins_missing"),
                             (lambda v:v["source_files"].pop(2), "operation_source_pins_missing"),
                             (lambda v:v["source_files"].append(copy.deepcopy(v["source_files"][0])), "operation_duplicate_source"),
                             (lambda v:v["source_files"][-1].update(sha256="0" * 64), "operation_source_changed")):
            value = copy.deepcopy(self.value);mutate(value)
            bad = write_json(self.root / "bad-sources.json", value)
            with self.subTest(code=code), self.assertRaisesRegex(admission.AdmissionError, code):
                with self.enter(authority=bad):self.fail("changed source closure admitted")
        self.extra.write_bytes(b"# Changed after authority freezing.\n")
        with self.assertRaisesRegex(admission.AdmissionError, "operation_source_changed"):
            with self.enter():self.fail("source drift admitted")
        self.assertFalse((self.registry / FIRST).exists())

    def test_source_mode_and_alias_refuse_before_claim_creation(self):
        self.extra.chmod(0o666)
        with self.assertRaisesRegex(admission.AdmissionError, "operation_source_unprotected"):
            with self.enter():self.fail("writable source admitted")
        self.extra.chmod(0o600)
        os.link(self.extra, self.root / "entry-hardlink.py")
        with self.assertRaisesRegex(admission.AdmissionError, "operation_source_unprotected"):
            with self.enter():self.fail("aliased source admitted")
        self.assertFalse((self.registry / FIRST).exists())

    def test_reconciliation_binds_exact_claim_authority_and_kind(self):
        with self.enter() as active:claim = active.claim
        with self.assertRaisesRegex(gate.GateError, "claim_reference_changed"):
            with self.enter(claim_ref=dict(claim, sha256="0" * 64)):self.fail("changed claim admitted")
        same_bytes_elsewhere = write_json(self.root / "copied-authority.json", self.value)
        with self.assertRaisesRegex(admission.AdmissionError, "operation_claim_mismatch"):
            with self.enter(authority=same_bytes_elsewhere, claim_ref=claim):self.fail("different authority path reconciled")
        changed = copy.deepcopy(self.value);changed["kind"] = "standalone_lifecycle"
        ref = write_json(self.root / "other-kind.json", changed)
        with self.assertRaisesRegex(admission.AdmissionError, "operation_claim_mismatch"):
            with self.enter(authority=ref, kind="standalone_lifecycle", claim_ref=claim):self.fail("claim kind changed")
        self.assertFalse((self.registry / FIRST / "terminal.json").exists())

    def test_finish_lost_receipt_reply_reuses_exact_create_only_receipt(self):
        real_create = gate.create_json
        def lost_receipt(directory, name, value, uid):
            result = real_create(directory, name, value, uid)
            if name == "terminal-receipt.json":raise OSError("synthetic lost receipt reply")
            return result
        with self.assertRaises(OSError):
            with self.enter() as active:
                claim = active.claim
                with mock.patch.object(gate, "create_json", side_effect=lost_receipt):active.finish([self.evidence])
        saved = self.receipt_path().read_bytes();inode = self.receipt_path().stat().st_ino
        self.assertFalse((self.registry / FIRST / "terminal.json").exists())
        with self.enter(claim_ref=claim) as reconciled:terminal = reconciled.finish([self.evidence])
        self.assertEqual(self.receipt_path().read_bytes(), saved)
        self.assertEqual(self.receipt_path().stat().st_ino, inode)
        self.assertEqual(json.loads(Path(terminal["path"]).read_bytes())["receipt"], file_ref(self.receipt_path()))

    def test_finish_lost_terminal_reply_is_observed_completed_without_new_publication(self):
        real_create = gate.create_json
        def lost_marker(directory, name, value, uid):
            result = real_create(directory, name, value, uid)
            if name == "terminal.json":raise OSError("synthetic lost terminal reply")
            return result
        with self.assertRaises(OSError):
            with self.enter() as active:
                claim = active.claim
                with mock.patch.object(gate, "create_json", side_effect=lost_marker):active.finish([self.evidence])
        before = self.files()
        with self.enter(claim_ref=claim) as reconciled:
            self.assertTrue(reconciled.completed)
            self.assertEqual(reconciled.terminal, file_ref(self.registry / FIRST / "terminal.json"))
            with self.assertRaisesRegex(admission.AdmissionError, "operation_already_completed"):
                reconciled.finish([self.evidence])
        self.assertEqual(self.files(), before)

    def test_changed_receipt_or_reordered_evidence_never_overwrites_lost_receipt(self):
        other = write_json(self.root / "other-evidence.json", {"second_terminal_observation": True})
        with self.enter() as active:
            claim = active.claim
            with mock.patch.object(active.lease, "complete", side_effect=OSError("synthetic before terminal marker")):
                with self.assertRaises(OSError):active.finish([self.evidence, other])
        saved = self.receipt_path().read_bytes()
        with self.enter(claim_ref=claim) as reconciled:
            with self.assertRaisesRegex(admission.AdmissionError, "operation_receipt_changed"):
                reconciled.finish([other, self.evidence])
        self.assertEqual(self.receipt_path().read_bytes(), saved)
        self.assertFalse((self.registry / FIRST / "terminal.json").exists())

    def test_invalid_evidence_cannot_create_terminal_receipt(self):
        with self.enter() as active:
            for evidence, code in (([], "operation_evidence_required"),
                                   ([self.evidence, self.evidence], "operation_duplicate_evidence"),
                                   ([dict(self.evidence, sha256="0" * 64)], "reference_changed")):
                with self.subTest(code=code), self.assertRaisesRegex(gate.GateError, code):active.finish(evidence)
            self.assertFalse((self.root / ".operation-receipts").exists())

    def test_closed_admission_refuses_before_any_receipt_directory_is_created(self):
        with self.enter() as active:pass
        with self.assertRaisesRegex(gate.GateError, "lease_not_local_active"):
            active.finish([self.evidence])
        self.assertFalse((self.root / ".operation-receipts").exists())
        self.assertFalse((self.registry / FIRST / "terminal.json").exists())

    def test_completed_evidence_drift_blocks_both_check_and_next_command(self):
        with self.enter() as active:active.finish([self.evidence])
        write_json(Path(self.evidence["path"]), {"changed_after_completion": True})
        other = self.second_authority()
        for read_only in (True, False):
            with self.subTest(read_only=read_only), self.assertRaisesRegex(gate.GateError, "reference_changed"):
                with self.enter(authority=other, kind="standalone_trial", read_only=read_only):self.fail("changed evidence waived")
        self.assertFalse((self.registry / SECOND).exists())

    def test_other_command_process_cannot_enter_while_read_only_admission_holds_gate(self):
        child = """
import json, os, sys
sys.path.insert(0, sys.argv[1])
import full_client_operation_admission as admission
import full_client_operation_gate as gate
try:
    with admission.admitted(json.loads(sys.argv[2]), json.loads(sys.argv[3]), 'finite_group', sys.argv[4],
                            read_only=True, owner_uid=os.geteuid(), required_sources=(sys.argv[5],)):
        print('unexpected_admission')
except gate.GateError as error:
    print(str(error))
"""
        with self.enter(read_only=True):
            result = subprocess.run([sys.executable, "-c", child, str(Path(admission.__file__).parent),
                json.dumps(self.authority), json.dumps(self.subject), str(self.attempts), str(self.extra)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                close_fds=True, timeout=10, check=True)
        self.assertEqual(result.stdout, b"operation_busy\n")
        self.assertEqual(result.stderr, b"")
        self.assertFalse((self.registry / FIRST).exists())
        with self.enter(read_only=True):pass

    def test_argument_refs_require_explicit_initial_vs_reconciliation_pairing(self):
        parser = argparse.ArgumentParser()
        admission.add_arguments(parser, inherited=True)
        initial = ["--operation-authority", self.authority["path"], "--operation-authority-sha256", self.authority["sha256"]]
        args = parser.parse_args(initial)
        self.assertEqual(admission.argument_refs(args), (self.authority, None))
        with self.assertRaisesRegex(admission.AdmissionError, "operation_exact_claim_required"):
            admission.argument_refs(args, reconcile=True)
        with self.enter() as active:claim = active.claim
        args = parser.parse_args([*initial, "--operation-claim", claim["path"], "--operation-claim-sha256", claim["sha256"]])
        self.assertEqual(admission.argument_refs(args, reconcile=True), (self.authority, claim))
        with self.assertRaisesRegex(admission.AdmissionError, "operation_initial_claim_forbidden"):
            admission.argument_refs(args)
        for argv, code in (([], "operation_authority_required"),
                           ([*initial, "--operation-claim", claim["path"]], "operation_claim_hash_required")):
            with self.subTest(code=code), self.assertRaisesRegex(admission.AdmissionError, code):
                admission.argument_refs(parser.parse_args(argv))


class LifecycleTerminalTests(unittest.TestCase):
    """Reobserve real saved bytes with synthetic service/process observations."""
    def setUp(self):
        import test_full_client_lifecycle as fixtures
        self.fixture = fixtures.LifecycleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine, self.host = self.fixture.engine, self.fixture.host
        original = self.host.command
        def command(argv):
            if argv[-1] == self.fixture.config["services"]["cosmic"]["unit"]:
                with Path(self.fixture.config["native"]["path"]).open("ab") as stream:
                    stream.write(b"Cosmic is now online after 10 ms.\n")
            return original(argv)
        self.host.command = command
        def native(pid, config, boundary, intent):
            path = Path(config["path"])
            raw, info = path.read_bytes(), path.stat()
            return {"device": info.st_dev, "inode": info.st_ino, "bytes": len(raw), "offset": boundary["bytes"],
                    "fd": 12, "observed_at_ms": self.host.now(), "ports": config["ports"],
                    "log_sha256": hashlib.sha256(raw).hexdigest(),
                    "startup_sha256": hashlib.sha256(raw[boundary["bytes"]:]).hexdigest()}
        self.host.native = native
        self.result = self.engine.start(self.fixture.request_ref)
        self.journal = self.result["journal"]

    def check(self):
        return admission.lifecycle_terminal(self.engine, self.journal, self.fixture.request_ref)

    def test_completed_native_prefix_and_append_reobserve_without_service_actions(self):
        before = Path(self.journal["path"]).read_bytes()
        with Path(self.fixture.config["native"]["path"]).open("ab") as stream:
            stream.write(b"later worker diagnostic\n")
        self.assertEqual(self.check(), [self.journal])
        self.assertEqual(self.host.started, ["cosmic", "worker"])
        self.assertEqual(Path(self.journal["path"]).read_bytes(), before)

    def test_missing_saved_native_receipt_refuses_even_with_current_marker(self):
        value = json.loads(Path(self.journal["path"]).read_bytes())
        value.pop("native_ready")
        self.journal = write_json(Path(self.journal["path"]), value)
        with self.assertRaisesRegex(admission.AdmissionError, "operation_native_receipt_missing"):
            self.check()
        self.assertEqual(self.host.started, ["cosmic", "worker"])

    def test_rewritten_original_startup_bytes_refuse_despite_later_valid_marker(self):
        value = json.loads(Path(self.journal["path"]).read_bytes())
        path = Path(self.fixture.config["native"]["path"])
        raw = path.read_bytes(); offset = value["native_ready"]["offset"]
        path.write_bytes(raw[:offset] + b"x" * (len(raw) - offset) + b"\nCosmic is now online after 10 ms.\n")
        with self.assertRaisesRegex(admission.AdmissionError, "operation_native_receipt_changed"):
            self.check()
        self.assertEqual(self.host.started, ["cosmic", "worker"])

    def test_missing_first_idle_or_changed_cosmic_refuse_without_restart(self):
        original = copy.deepcopy(self.host.identities["cosmic"])
        self.host.identities["cosmic"]["start_ticks"] = "999"
        with self.assertRaisesRegex(ValueError, "cosmic_instance_changed"):
            self.check()
        self.host.identities["cosmic"] = original
        idle = json.loads(Path(self.journal["path"]).read_bytes())["first_idle"]
        Path(idle["path"]).unlink()
        with self.assertRaisesRegex(ValueError, "worker_receipt_pending"):
            self.check()
        self.assertEqual(self.host.started, ["cosmic", "worker"])


if __name__ == "__main__":unittest.main()
