"""Private handoff preparation: real files/flocks, synthetic host observations.

No services, database, browser, model API, or lifecycle start is invoked.
"""
import copy
from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import full_client_lifecycle as native
import full_client_operations_handoff as handoff
import test_full_client_lifecycle as fixtures


class ObservedHost(fixtures.FakeHost):
    """Keep fake service/DB responses but use the real Linux lock inventory."""
    remaining = native.Host.remaining
    kernel_read = native.Host.kernel_read
    lock_owners = native.Host.lock_owners

    def __init__(self, *args):
        super().__init__(*args)
        self.snapshot_calls = 0
        self.browser_mutation = None
        self.unit_mutation = None
        self.pending = 0

    def snapshot(self, config, run_id):
        self.snapshot_calls += 1
        value = super().snapshot(config, run_id)
        value.update(run_id=run_id, captured_at_ms=self.now())
        return value

    def browser(self, *args):
        value = super().browser(*args)
        if self.browser_mutation:
            self.browser_mutation(value)
        return value

    def unit(self, *args):
        value = super().unit(*args)
        if self.unit_mutation:
            self.unit_mutation(args[-1], value)
        return value

    def queue(self, _):return self.pending

    def command(self, *args, **kwargs):
        raise AssertionError("handoff preparer must never request a host mutation command")


@unittest.skipUnless(sys.platform.startswith("linux"), "Uses the actual Linux FLOCK owner inventory")
class HandoffTests(unittest.TestCase):
    def setUp(self):
        # Reuse only fixture construction, without inheriting/rerunning its
        # lifecycle start/reconcile tests in this focused module.
        self.fixture = fixtures.LifecycleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.config, self.engine = self.fixture.root, self.fixture.config, self.fixture.engine
        self.host = ObservedHost(self.config, self.fixture.snapshot, self.fixture.request)
        self.host.engine = self.engine
        self.engine.host = self.host
        self.engine.begin_deadline()
        self.operation = "3" * 32
        self.destination = self.root / "prepared-handoff"
        self.attempts = copy.deepcopy(self.fixture.request["attempts"])
        self.expected = copy.deepcopy(self.fixture.request["offline_snapshot"])

    def prepare(self, *, held=True):
        if not held:
            return handoff.prepare_handoff(self.engine, self.destination, self.operation, self.attempts,
                                          expected_snapshot_ref=self.expected)
        with self.engine.serialized():
            self.engine.acquire_world_locks()
            return self.prepare(held=False)

    def read(self, ref):
        return native.read_ref(ref, uid=os.geteuid())

    def test_complete_group_keeps_last_persisted_xp_and_existing_lifecycle_schema(self):
        final = copy.deepcopy(self.fixture.snapshot)
        final["character"]["exp"] = 18500  # 9000 -> 18500 across two completed synthetic attempts.
        final["character"]["hp"] = 777
        final["run_id"] = "2" * 32
        second = self.root / "attempts" / final["run_id"]
        second.mkdir(mode=0o700)
        journal = fixtures.write_json(second / "journal.json", {"attempt_id": final["run_id"], "status": "completed",
            "phase_status": "returned", "pending": None, "receipts": {"cleanup": {"attempt_id": final["run_id"], "clean": True}}})
        backend = fixtures.write_json(second / "backend-state.json", {"attempt_id": final["run_id"], "clean": True})
        self.attempts.append({"id": final["run_id"], "journal": journal, "backend": backend})
        self.expected = fixtures.write_json(second / "final-db.json", final)
        self.host.expected = final
        original = {pin["path"]: Path(pin["path"]).read_bytes() for row in self.attempts for pin in (row["journal"], row["backend"])}
        deadline = self.host.deadline
        original_request = self.engine.request
        with self.engine.serialized():
            self.engine.acquire_world_locks()
            result = self.prepare(held=False)
            self.assertIs(self.engine.request, original_request)
            self.assertEqual(self.host.deadline, deadline)
            # The result is consumed unchanged by the existing lifecycle API.
            self.engine.load_handoff(result["handoff"])
            checked = self.engine.preflight(result["handoff"])
            self.assertGreaterEqual(checked["available_bytes"], 8 * 1024**3)
            with open(self.config["locks"]["world"]["path"], "r+") as rival:
                with self.assertRaises(BlockingIOError):fcntl.flock(rival, fcntl.LOCK_EX | fcntl.LOCK_NB)
        value = self.read(result["handoff"])
        self.assertEqual(value["operation_id"], self.operation)
        self.assertEqual(value["attempts"], self.attempts)
        self.assertEqual(value["offline_snapshot"], result["offline_snapshot"])
        self.assertEqual(self.read(result["offline_snapshot"])["character"], final["character"])
        preparation = self.read(result["preparation"])
        self.assertEqual(preparation["expected_snapshot"], self.expected)
        self.assertEqual(preparation["observation"]["stopped_invocations"], self.fixture.request["stopped_invocations"])
        self.assertFalse(preparation["lifecycle_invoked"])
        self.assertEqual(self.host.started, [])
        self.assertGreaterEqual(self.host.snapshot_calls, 3)
        for path, raw in original.items():self.assertEqual(Path(path).read_bytes(), raw)
        for path in self.destination.iterdir():self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(sorted(p.name for p in self.destination.iterdir()), ["handoff.json", "offline-snapshot.json", "preparation.json"])

    def test_changed_current_xp_keymap_or_offline_account_refuses(self):
        changes = (lambda s:s["character"].update(exp=9001), lambda s:s.update(keymap=[[57, 4, 53]]),
                   lambda s:s.update(account_logged_in=1), lambda s:s.update(account_logged_in=False))
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                self.host.expected = copy.deepcopy(self.fixture.snapshot);change(self.host.expected)
                with self.assertRaises(native.LifecycleError):self.prepare()
                self.assertFalse(self.destination.exists())

    def test_attempt_inventory_and_terminal_receipt_drift_refuse(self):
        extra = self.root / "attempts" / ("4" * 32);extra.mkdir(mode=0o700)
        with self.assertRaisesRegex(native.LifecycleError, "attempt_inventory_changed"):self.prepare()
        extra.rmdir()
        backend = Path(self.attempts[0]["backend"]["path"])
        backend.write_text("{}")
        with self.assertRaisesRegex(native.LifecycleError, "reference_changed"):self.prepare()
        self.assertFalse(self.destination.exists())

    def test_fresh_hash_cannot_authorize_an_unclean_attempt(self):
        path = Path(self.attempts[0]["backend"]["path"])
        self.attempts[0]["backend"] = fixtures.write_json(path, {"attempt_id": self.attempts[0]["id"], "clean": False})
        with self.assertRaisesRegex(native.LifecycleError, "attempt_not_terminal_clean"):self.prepare()
        self.assertFalse(self.destination.exists())

    def test_missing_actual_locks_cannot_be_replaced_by_descriptor_claims(self):
        with self.assertRaisesRegex(native.LifecycleError, "handoff_serialization_required"):self.prepare(held=False)
        with self.engine.serialized():
            with self.assertRaisesRegex(native.LifecycleError, "handoff_world_locks_required"):self.prepare(held=False)
            self.engine.acquire_world_locks()
            for fd in self.engine.world_fds:fcntl.flock(fd, fcntl.LOCK_UN)  # Negative fixture only.
            with self.assertRaisesRegex(native.LifecycleError, "world_lock_owner_changed"):self.prepare(held=False)
        self.assertFalse(self.destination.exists())

    def test_stale_browser_queue_or_capacity_refuses(self):
        self.host.browser_mutation = lambda v:v["session"].update(fresh=False)
        with self.assertRaisesRegex(native.LifecycleError, "handoff_browser_not_settled"):self.prepare()
        self.host.browser_mutation = None;self.host.pending = 1
        with self.assertRaisesRegex(native.LifecycleError, "queue_not_idle"):self.prepare()
        self.host.pending = 0;self.host.memory_bytes = 1024
        with self.assertRaisesRegex(native.LifecycleError, "capacity_insufficient"):self.prepare()
        self.assertFalse(self.destination.exists())

    def test_running_or_changed_service_refuses_without_commands(self):
        self.host.identities["cosmic"] = {"pid": 101, "start_ticks": "101", "invocation_id": "1" * 32}
        with self.assertRaisesRegex(native.LifecycleError, "handoff_stopped_instance_required"):self.prepare()
        del self.host.identities["cosmic"]
        self.host.unit_mutation = lambda unit, value:value.update(NeedDaemonReload="yes")
        with self.assertRaisesRegex(native.LifecycleError, "service_configuration_changed"):self.prepare()
        self.assertFalse(self.destination.exists())

    def test_service_invocation_change_during_preparation_refuses(self):
        original = self.host.snapshot
        def changed(*args):
            value = original(*args)
            self.host.request = copy.deepcopy(self.host.request)
            self.host.request["stopped_invocations"]["cosmic"] = "6" * 32
            return value
        self.host.snapshot = changed
        with self.assertRaisesRegex(native.LifecycleError, "handoff_identity_changed"):self.prepare()
        self.assertFalse(self.destination.exists())

    def test_expected_reference_missing_or_expired_deadline_refuses(self):
        self.expected["sha256"] = "0" * 64
        with self.assertRaisesRegex(native.LifecycleError, "reference_changed"):self.prepare()
        self.host.deadline = time.monotonic() - 1
        with self.assertRaisesRegex(native.LifecycleError, "lifecycle_deadline"):self.prepare(held=False)
        self.assertLess(self.host.deadline, time.monotonic())
        self.assertFalse(self.destination.exists())

    def test_native_prefix_change_refuses_and_append_is_preserved(self):
        path = Path(self.config["native"]["path"])
        original_snapshot = self.host.snapshot
        def rewritten(*args):
            path.write_bytes(b"replaced prefix\n")
            return original_snapshot(*args)
        self.host.snapshot = rewritten
        with self.assertRaisesRegex(native.LifecycleError, "native_boundary_ambiguous"):self.prepare()
        path.write_bytes(b"previous log\n")
        changed = False
        def appended(*args):
            nonlocal changed
            if not changed:
                with path.open("ab") as stream:stream.write(b"final ordinary append\n")
                changed = True
            return original_snapshot(*args)
        self.host.snapshot = appended
        result = self.prepare()
        observation = self.read(result["preparation"])["observation"]
        self.assertGreater(observation["native_boundary"]["bytes"], observation["native_boundary_before"]["bytes"])
        self.assertEqual(path.read_bytes(), b"previous log\nfinal ordinary append\n")

    def test_failed_create_does_not_publish_a_partial_handoff_or_overwrite(self):
        original = handoff._write_new
        def failed(directory, name, value):
            if name == "handoff.json":raise OSError("synthetic create failure")
            return original(directory, name, value)
        with patch.object(handoff, "_write_new", side_effect=failed):
            with self.assertRaises(OSError):self.prepare()
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.host.started, [])
        self.destination.mkdir(mode=0o700)
        marker = self.destination / "preserved";marker.write_bytes(b"operator evidence")
        with self.assertRaisesRegex(native.LifecycleError, "handoff_destination_exists"):self.prepare()
        self.assertEqual(marker.read_bytes(), b"operator evidence")

    def test_late_file_drift_after_staging_is_refused(self):
        original = handoff._write_new
        def changed(directory, name, value):
            result = original(directory, name, value)
            if name == "preparation.json":
                Path(self.config["services"]["worker"]["files"][0]["path"]).write_bytes(b"changed worker")
            return result
        with patch.object(handoff, "_write_new", side_effect=changed):
            with self.assertRaisesRegex(native.LifecycleError, "frozen_service_file_changed"):self.prepare()
        self.assertFalse(self.destination.exists())

    def test_does_not_invoke_lifecycle_or_manage_callers_lock_and_deadline(self):
        with self.engine.serialized():
            self.engine.acquire_world_locks()
            methods = ("start", "reconcile", "begin_deadline", "serialized", "acquire_world_locks", "close_world_locks")
            with ExitStack() as stack:
                for method in methods:
                    stack.enter_context(patch.object(native.NormalLifecycle, method,
                        side_effect=AssertionError("handoff must not invoke lifecycle or change its ownership")))
                self.prepare(held=False)
                self.engine.verify_world_locks()
        self.assertEqual(self.host.started, [])

    def test_lost_publication_reply_preserves_complete_evidence_and_refuses_replay(self):
        original = native.publish_attempt
        def lost_reply(staging, destination):
            original(staging, destination)
            raise OSError("synthetic lost publication reply")
        with patch.object(native, "publish_attempt", side_effect=lost_reply):
            with self.assertRaises(OSError):self.prepare()
        saved = {path.name: path.read_bytes() for path in self.destination.iterdir()}
        self.assertEqual(set(saved), {"handoff.json", "offline-snapshot.json", "preparation.json"})
        with self.assertRaisesRegex(native.LifecycleError, "handoff_destination_exists"):self.prepare()
        self.assertEqual(saved, {path.name: path.read_bytes() for path in self.destination.iterdir()})
        self.assertEqual(self.host.started, [])


if __name__ == "__main__":unittest.main()
