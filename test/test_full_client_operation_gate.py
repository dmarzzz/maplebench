"""Offline gate tests with real files/flocks; no services, runtime or API calls."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import full_client_operation_gate as gate


FIRST = "1" * 32
SECOND = "2" * 32


def write_json(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    path.write_bytes(raw)
    path.chmod(0o600)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


class OperationGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.root.chmod(0o700)
        self.attempts = self.root / "attempts"
        self.attempts.mkdir(mode=0o700)
        self.uid = os.geteuid()
        self.pin = gate.initialize_registry(self.attempts, owner_uid=self.uid)
        self.registry = self.attempts / ".operations"
        self.authority = write_json(self.root / "authority.json", {"kind": "offline_authority", "budget": 1})
        self.evidence = write_json(self.root / "evidence.json", {"owned_resources_quiescent": True})

    def new_gate(self):
        return gate.OperationGate(self.attempts, self.pin, owner_uid=self.uid)

    def receipt(self, claim, **changes):
        value = {"schema_version": 1, "operation_id": Path(claim["path"]).parent.name,
                 "claim_sha256": claim["sha256"], "status": "completed", "quiescent": True,
                 "evidence": [self.evidence]}
        value.update(changes)
        return write_json(self.root / (value["operation_id"] + "-receipt.json"), value)

    def completed(self, operation_id=FIRST):
        with self.new_gate().locked() as lease:
            claim = lease.begin(operation_id, "finite_group", self.authority)
            terminal = lease.complete(self.receipt(claim))
        return claim, terminal

    def test_setup_is_derived_private_create_only_and_never_creates_attempt_root(self):
        self.assertEqual(self.pin["path"], str(self.registry / ".gate.lock"))
        for path, mode in ((self.registry, 0o700), (Path(self.pin["path"]), 0o600)):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)
            self.assertEqual(path.stat().st_uid, self.uid)
        before = Path(self.pin["path"]).stat().st_ino
        with self.assertRaisesRegex(gate.GateError, "registry_exists"):
            gate.initialize_registry(self.attempts, owner_uid=self.uid)
        self.assertEqual(Path(self.pin["path"]).stat().st_ino, before)
        missing = self.root / "missing"
        with self.assertRaises(FileNotFoundError):
            gate.initialize_registry(missing, owner_uid=self.uid)
        self.assertFalse(missing.exists())

    def test_wrong_owner_mode_symlink_and_noncanonical_root_are_refused(self):
        with self.assertRaisesRegex(gate.GateError, "operator_uid_mismatch"):
            gate.OperationGate(self.attempts, self.pin, owner_uid=self.uid + 1)
        with self.assertRaisesRegex(gate.GateError, "operator_uid_mismatch"):
            gate.OperationGate(self.attempts, self.pin, owner_uid=False)
        self.attempts.chmod(0o755)
        with self.assertRaisesRegex(gate.GateError, "private_directory_required"):
            self.new_gate()
        self.attempts.chmod(0o700)
        alias = self.root / "alias"
        alias.symlink_to(self.attempts, target_is_directory=True)
        for path in (alias, str(self.attempts) + "/../attempts"):
            with self.subTest(path=str(path)), self.assertRaises(gate.GateError):
                gate.OperationGate(path, self.pin, owner_uid=self.uid)

    def test_gate_inode_replacement_and_hardlink_are_refused(self):
        existing = self.new_gate()
        path = Path(self.pin["path"])
        path.rename(self.registry / "original.lock")
        path.touch(mode=0o600)
        with self.assertRaisesRegex(gate.GateError, "gate_pin_changed"):
            with existing.locked():
                self.fail("replaced gate was admitted")
        path.unlink()
        (self.registry / "original.lock").rename(path)
        os.link(path, self.root / "duplicate.lock")
        with self.assertRaisesRegex(gate.GateError, "gate_pin_changed"):
            self.new_gate()

    def test_gate_symlink_wrong_mode_and_replaced_registry_are_refused(self):
        path = Path(self.pin["path"])
        path.chmod(0o644)
        with self.assertRaisesRegex(gate.GateError, "gate_pin_changed"):
            self.new_gate()
        path.chmod(0o600)
        moved = self.root / "moved.lock"
        path.rename(moved)
        path.symlink_to(moved)
        with self.assertRaisesRegex(gate.GateError, "symlink_path"):
            self.new_gate()
        path.unlink()
        moved.rename(path)
        existing = self.new_gate()
        self.registry.rename(self.root / "old-registry")
        self.registry.mkdir(mode=0o700)
        with self.assertRaisesRegex(gate.GateError, "directory_changed"):
            existing.check()

    def test_nonblocking_exclusion_applies_before_any_claim(self):
        with self.new_gate().locked():
            with self.assertRaisesRegex(gate.GateError, "operation_busy"):
                with self.new_gate().locked():
                    self.fail("second open description acquired the gate")
        with self.new_gate().locked() as lease:
            lease.begin(FIRST, "finite_group", self.authority)

    def test_release_closes_only_owned_description_without_unlocking_duplicate(self):
        duplicate = None
        try:
            with self.new_gate().locked() as lease:
                duplicate = os.dup(lease._fd)
            os.fstat(duplicate)
            with self.assertRaisesRegex(gate.GateError, "operation_busy"):
                with self.new_gate().locked():
                    self.fail("close performed LOCK_UN on a shared description")
            os.close(duplicate)
            duplicate = None
            with self.new_gate().locked():
                pass
        finally:
            if duplicate is not None:
                os.close(duplicate)

    def test_no_borrowed_descriptor_factory_or_closed_or_forked_lease_use(self):
        with self.assertRaisesRegex(gate.GateError, "lease_factory_required"):
            gate._Lease(self.new_gate(), -1, object())
        with self.new_gate().locked() as lease:
            with mock.patch.object(gate.os, "getpid", return_value=os.getpid() + 1):
                with self.assertRaisesRegex(gate.GateError, "lease_not_local_active"):
                    lease.begin(FIRST, "finite_group", self.authority)
        with self.assertRaisesRegex(gate.GateError, "lease_not_local_active"):
            lease.begin(FIRST, "finite_group", self.authority)

    def test_claim_is_durable_before_return_and_pending_blocks_later_operations(self):
        events = []
        real_sync, real_link = os.fsync, os.link
        def fsync(fd):
            events.append("file_sync" if stat.S_ISREG(os.fstat(fd).st_mode) else "directory_sync")
            return real_sync(fd)
        def link(*args, **kwargs):
            events.append("publish")
            return real_link(*args, **kwargs)
        with self.new_gate().locked() as lease:
            with mock.patch.object(gate.os, "fsync", side_effect=fsync), \
                 mock.patch.object(gate.os, "link", side_effect=link):
                claim = lease.begin(FIRST, "finite_group", self.authority)
            self.assertEqual(json.loads(Path(claim["path"]).read_bytes())["authority"], self.authority)
            self.assertEqual(hashlib.sha256(Path(claim["path"]).read_bytes()).hexdigest(), claim["sha256"])
        publication = events.index("publish")
        self.assertIn("file_sync", events[:publication])
        self.assertIn("directory_sync", events[publication + 1:])
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "pending_operation"):
                lease.begin(SECOND, "standalone_trial", self.authority)
        self.assertFalse((self.registry / SECOND).exists())

    def test_actual_owner_exit_does_not_retire_claim_or_authorize_another_id(self):
        child = """
import json, os, sys
sys.path.insert(0, sys.argv[1])
from full_client_operation_gate import OperationGate
with OperationGate(sys.argv[2], json.loads(sys.argv[3]), owner_uid=os.geteuid()).locked() as lease:
    lease.begin('1' * 32, 'finite_group', json.loads(sys.argv[4]))
    os._exit(0)
"""
        result = subprocess.run([sys.executable, "-c", child, str(Path(gate.__file__).parent),
                                 str(self.attempts), json.dumps(self.pin), json.dumps(self.authority)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                close_fds=True, timeout=10, check=True)
        self.assertEqual(result.stdout, b"")
        raw = (self.registry / FIRST / "claim.json").read_bytes()
        claim = {"path": str(self.registry / FIRST / "claim.json"), "sha256": hashlib.sha256(raw).hexdigest()}
        self.assertNotEqual(json.loads(raw)["owner"]["pid"], os.getpid())
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "pending_operation"):
                lease.begin(SECOND, "finite_group", self.authority)
            self.assertEqual(lease.reconcile(claim)["status"], "pending")

    def test_reconciliation_requires_exact_claim_hash_and_derived_path(self):
        with self.new_gate().locked() as lease:
            claim = lease.begin(FIRST, "standalone_lifecycle", self.authority)
        with self.new_gate().locked() as lease:
            wrong_hash = dict(claim, sha256="0" * 64)
            with self.assertRaisesRegex(gate.GateError, "claim_reference_changed"):
                lease.reconcile(wrong_hash)
            outside = write_json(self.root / "claim.json", json.loads(Path(claim["path"]).read_bytes()))
            with self.assertRaisesRegex(gate.GateError, "claim_outside_registry"):
                lease.reconcile(outside)
            self.assertEqual(lease.reconcile(claim), {"claim": claim, "status": "pending", "terminal": None})
            with self.assertRaisesRegex(gate.GateError, "lease_already_claimed"):
                lease.begin(SECOND, "finite_group", self.authority)

    def test_terminal_receipt_is_required_and_contradictions_leave_claim_pending(self):
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "active_claim_required"):
                lease.complete(self.authority)
            claim = lease.begin(FIRST, "finite_group", self.authority)
            for changes, code in (({"quiescent": False}, "invalid_terminal_receipt"),
                                  ({"quiescent": 1}, "invalid_terminal_receipt"),
                                  ({"claim_sha256": "0" * 64}, "invalid_terminal_receipt"),
                                  ({"operation_id": SECOND}, "invalid_terminal_receipt"),
                                  ({"status": "pending"}, "invalid_terminal_receipt"),
                                  ({"evidence": []}, "invalid_terminal_receipt"),
                                  ({"evidence": [self.evidence, self.evidence]}, "duplicate_terminal_evidence")):
                with self.subTest(changes=changes), self.assertRaisesRegex(gate.GateError, code):
                    lease.complete(self.receipt(claim, **changes))
                self.assertFalse((self.registry / FIRST / "terminal.json").exists())
            lease.complete(self.receipt(claim))

    def test_completed_operation_is_immutable_and_reconciliation_never_replays(self):
        claim, terminal = self.completed()
        claim_bytes = Path(claim["path"]).read_bytes()
        terminal_bytes = Path(terminal["path"]).read_bytes()
        with self.new_gate().locked() as lease:
            self.assertEqual(lease.reconcile(claim), {"claim": claim, "status": "completed", "terminal": terminal})
            with self.assertRaisesRegex(gate.GateError, "active_claim_required"):
                lease.complete(self.receipt(claim))
            with self.assertRaisesRegex(gate.GateError, "operation_exists"):
                lease.begin(FIRST, "finite_group", self.authority)
            lease.begin(SECOND, "standalone_trial", self.authority)
        self.assertEqual(Path(claim["path"]).read_bytes(), claim_bytes)
        self.assertEqual(Path(terminal["path"]).read_bytes(), terminal_bytes)

    def test_completed_evidence_and_authority_are_revalidated_before_admission(self):
        self.completed()
        original = Path(self.evidence["path"]).read_bytes()
        write_json(Path(self.evidence["path"]), {"owned_resources_quiescent": False})
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "reference_changed"):
                lease.begin(SECOND, "finite_group", self.authority)
        Path(self.evidence["path"]).write_bytes(original)
        write_json(Path(self.authority["path"]), {"changed": True})
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "reference_changed"):
                lease.begin(SECOND, "finite_group", self.authority)

    def test_completed_marker_hash_mismatch_and_unknown_claim_fields_are_quarantined(self):
        claim, terminal = self.completed()
        marker = json.loads(Path(terminal["path"]).read_bytes())
        marker["claim_sha256"] = "0" * 64
        write_json(Path(terminal["path"]), marker)
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "invalid_terminal"):
                lease.begin(SECOND, "finite_group", self.authority)
        Path(terminal["path"]).unlink()
        value = json.loads(Path(claim["path"]).read_bytes())
        value["abandoned"] = True
        write_json(Path(claim["path"]), value)
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "invalid_record"):
                lease.begin(SECOND, "finite_group", self.authority)

    def test_malformed_and_unknown_entries_are_never_waived_by_reconciliation(self):
        with self.new_gate().locked() as lease:
            claim = lease.begin(FIRST, "finite_group", self.authority)
        unknown = self.registry / ".unresolved"
        unknown.write_bytes(b"private malformed content")
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "unknown_registry_entry"):
                lease.reconcile(claim)
        unknown.unlink()
        empty = self.registry / SECOND
        empty.mkdir(mode=0o700)
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "malformed_claim_directory"):
                lease.reconcile(claim)

    def test_multiple_pending_claims_require_independent_resolution_not_a_bypass(self):
        with self.new_gate().locked() as lease:
            claim = lease.begin(FIRST, "finite_group", self.authority)
        second = self.registry / SECOND
        second.mkdir(mode=0o700)
        value = json.loads(Path(claim["path"]).read_bytes())
        value["operation_id"] = SECOND
        write_json(second / "claim.json", value)
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "other_pending_operation"):
                lease.reconcile(claim)

    def test_malformed_json_and_unsafe_claim_types_fail_with_safe_codes(self):
        with self.new_gate().locked() as lease:
            claim = lease.begin(FIRST, "finite_group", self.authority)
        original = Path(claim["path"]).read_bytes()
        malformed = ((b'{"secret": "DO_NOT_FORWARD",', "invalid_json"),
                     (b'{"x": 1, "x": 2}', "duplicate_json_key"),
                     (b'{"x": NaN}', "nonfinite_json"),
                     (b'{"x": 1e999}', "nonfinite_json"))
        for raw, code in malformed:
            Path(claim["path"]).write_bytes(raw)
            with self.subTest(code=code), self.new_gate().locked() as lease:
                with self.assertRaisesRegex(gate.GateError, "^" + code + "$"):
                    lease.begin(SECOND, "finite_group", self.authority)
        value = json.loads(original)
        value["kind"] = []
        write_json(Path(claim["path"]), value)
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "^invalid_claim$"):
                lease.begin(SECOND, "finite_group", self.authority)

    def test_reference_privacy_symlinks_and_hashes_are_validated_before_claim_creation(self):
        path = Path(self.authority["path"])
        path.chmod(0o644)
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "private_file_required"):
                lease.begin(FIRST, "finite_group", self.authority)
        path.chmod(0o600)
        alias = self.root / "authority-alias.json"
        alias.symlink_to(path)
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "symlink_path"):
                lease.begin(FIRST, "finite_group", dict(self.authority, path=str(alias)))
            with self.assertRaisesRegex(gate.GateError, "reference_changed"):
                lease.begin(FIRST, "finite_group", dict(self.authority, sha256="0" * 64))
        os.link(path, self.root / "authority-hardlink.json")
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "private_file_required"):
                lease.begin(FIRST, "finite_group", self.authority)
        self.assertFalse((self.registry / FIRST).exists())

    def test_reference_parent_must_be_private_even_when_file_is_private(self):
        public = self.root / "public"
        public.mkdir(mode=0o755)
        public.chmod(0o755)  # Do not depend on the serialized test job's restrictive umask.
        ref = write_json(public / "authority.json", {"kind": "authority"})
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "private_directory_required"):
                lease.begin(FIRST, "finite_group", ref)
        self.assertFalse((self.registry / FIRST).exists())

    def test_bounded_file_size_inventory_read_budget_and_work_deadline(self):
        oversized = self.root / "oversized.json"
        with oversized.open("wb") as stream:
            stream.truncate(gate.MAX_REFERENCE + 1)
        oversized.chmod(0o600)
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "file_size_limit"):
                lease.begin(FIRST, "finite_group", {"path": str(oversized), "sha256": "0" * 64})
            with mock.patch.object(gate, "MAX_READ_BYTES", 1):
                with self.assertRaisesRegex(gate.GateError, "gate_read_budget"):
                    lease.begin(FIRST, "finite_group", self.authority)
            ticks = itertools.count()
            with mock.patch.object(gate.time, "monotonic", side_effect=lambda: next(ticks)), \
                 mock.patch.object(gate, "WORK_SECONDS", 0):
                with self.assertRaisesRegex(gate.GateError, "gate_work_deadline"):
                    lease.begin(FIRST, "finite_group", self.authority)
        self.completed()
        with mock.patch.object(gate, "MAX_CLAIMS", 1), self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "claim_inventory_limit"):
                lease.begin(SECOND, "finite_group", self.authority)

    def test_failed_claim_publication_leaves_quarantine_not_a_reusable_id(self):
        with self.new_gate().locked() as lease:
            with mock.patch.object(gate.os, "link", side_effect=OSError("synthetic failed link")):
                with self.assertRaises(OSError):
                    lease.begin(FIRST, "finite_group", self.authority)
        self.assertEqual(list((self.registry / FIRST).iterdir()), [])
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "malformed_claim_directory"):
                lease.begin(SECOND, "finite_group", self.authority)

    def test_no_replace_publication_cannot_overwrite_a_preexisting_record(self):
        path = self.root / "record.json"
        ref = write_json(path, {"original": True})
        with self.assertRaises(FileExistsError):
            gate.create_json(self.root, path.name, {"replacement": True}, self.uid)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), ref["sha256"])
        self.assertFalse(any(p.name.startswith(".writing-") for p in self.root.iterdir()))

    def test_receipt_drift_during_publication_is_not_reported_as_completion(self):
        with self.new_gate().locked() as lease:
            claim = lease.begin(FIRST, "finite_group", self.authority)
            receipt = self.receipt(claim)
            original_create = gate.create_json
            def create_then_corrupt(parent, name, value, uid):
                result = original_create(parent, name, value, uid)
                if name == "terminal.json":
                    write_json(Path(self.evidence["path"]), {"changed_during_commit": True})
                return result
            with mock.patch.object(gate, "create_json", side_effect=create_then_corrupt):
                with self.assertRaisesRegex(gate.GateError, "reference_changed"):
                    lease.complete(receipt)
        self.assertTrue((self.registry / FIRST / "terminal.json").exists())
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "reference_changed"):
                lease.begin(SECOND, "finite_group", self.authority)

    def test_authority_drift_during_claim_publication_is_quarantined(self):
        original_create = gate.create_json
        def create_then_corrupt(parent, name, value, uid):
            result = original_create(parent, name, value, uid)
            write_json(Path(self.authority["path"]), {"changed_during_commit": True})
            return result
        with self.new_gate().locked() as lease:
            with mock.patch.object(gate, "create_json", side_effect=create_then_corrupt):
                with self.assertRaisesRegex(gate.GateError, "reference_changed"):
                    lease.begin(FIRST, "finite_group", self.authority)
        self.assertTrue((self.registry / FIRST / "claim.json").exists())
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "reference_changed"):
                lease.begin(SECOND, "finite_group", self.authority)

    def test_ensure_available_is_read_only_and_refuses_pending_or_malformed_registry(self):
        with self.new_gate().locked() as lease:
            lease.ensure_available()
            self.assertEqual([p.name for p in self.registry.iterdir()], [".gate.lock"])
        self.completed()
        with self.new_gate().locked() as lease:
            lease.ensure_available()
            lease.begin(SECOND, "standalone_trial", self.authority)
            with self.assertRaisesRegex(gate.GateError, "lease_already_claimed"):
                lease.ensure_available()
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "pending_operation"):
                lease.ensure_available()
        (self.registry / SECOND / "claim.json").write_bytes(b"bad private JSON")
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "invalid_json"):
                lease.ensure_available()

    def test_local_export_requires_pending_claim_and_closes_only_its_duplicate(self):
        with self.new_gate().locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "active_claim_required"):
                with lease.export_active():
                    self.fail("unclaimed lease exported")
            claim = lease.begin(FIRST, "finite_group", self.authority)
            with lease.export_active() as exported:
                fd = exported["fd"]
                self.assertNotEqual(fd, lease._fd)
                self.assertEqual(exported["claim"], claim)
                self.assertEqual(exported["gate_pin"], self.pin)
                self.assertEqual(exported["attempt_root"], str(self.attempts))
                os.fstat(fd)
            with self.assertRaises(OSError):
                os.fstat(fd)
            with self.assertRaisesRegex(gate.GateError, "operation_busy"):
                with self.new_gate().locked():
                    self.fail("export closed the original lease")
            self.assertFalse((self.registry / FIRST / "terminal.json").exists())
        with self.assertRaisesRegex(gate.GateError, "lease_not_local_active"):
            with lease.export_active():
                self.fail("closed lease exported")


if __name__ == "__main__":
    unittest.main()
