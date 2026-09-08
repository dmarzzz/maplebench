"""Offline failure tests for the private backend; never touch live services/DB."""
import hashlib
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import stat
import unittest
from unittest.mock import MagicMock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import full_client_runtime as runtime


class CachedSystemd:
    """Disk edits dirty the manager; only reload changes its cached properties."""
    def __init__(self, dropin, normal):
        self.dropin = dropin
        self.loaded = dropin.read_bytes()
        self.normal = normal
        self.reload_calls = 0
        self.fail_before_reload = False
        self.fail_after_reload = False
        self.apply_reload = True

    def disk(self):
        return self.dropin.read_bytes() if self.dropin.exists() else None

    def unit(self, systemctl, name):
        if name != "cosmic.service":
            return dict(self.normal)
        return self.normal | {"NeedDaemonReload": "yes" if self.disk() != self.loaded else "no",
            "DropInPaths": str(self.dropin) if self.loaded is not None else "",
            "Environment": "MAPLEBENCH_ENABLED=false MAPLEBENCH_TRIAL_ID=synthetic"
                           if self.loaded is not None else "MAPLEBENCH_ENABLED=true"}

    def command(self, argv, **kwargs):
        if argv == ["/usr/bin/systemctl", "daemon-reload"]:
            self.reload_calls += 1
            if self.fail_before_reload:
                raise SystemExit("synthetic crash before manager reload")
            if self.apply_reload:
                self.loaded = self.disk()
            if self.fail_after_reload:
                raise SystemExit("synthetic crash after manager reload")
            return b""
        if argv[0] == "/usr/bin/mysql":
            return b"0\n"
        raise AssertionError("unexpected service operation in cleanup fixture")


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.run_id = "a" * 32
        self.directory = self.root / self.run_id
        self.directory.mkdir(mode=0o700)
        self.binding = {"schema_version": 1, "executable": {"path": "/usr/bin/docker", "sha256": "a" * 64},
                        "launcher": None, "socket_path": str(Path("/var/run/docker.sock").resolve())}
        self.host = MagicMock()
        self.host.remaining.return_value = 120
        self.host.now.return_value = 2000
        self.host.deadline = 0
        self.backend = runtime.CosmicRuntime.__new__(runtime.CosmicRuntime)
        self.backend.host = self.host
        self.backend.directory = self.directory
        self.backend.run_id = self.run_id
        self.backend.config = {
            "services": {k: k + ".service" for k in ("world", "worker", "cosmic", "web")},
            "systemctl": "/usr/bin/systemctl", "journalctl": "/usr/bin/journalctl", "docker": "/usr/bin/docker",
            "dropin_root": str(self.root / "dropins"), "admin_socket": str(self.root / "admin.sock"),
            "mysql": {"command": ["/usr/bin/mysql"], "database": "trial", "character_id": 10, "account_id": 20},
            "attempt_root": str(self.root), "relay_output_root": str(self.root / "relay"),
            "native_output_root": str(self.root / "native")}
        self.backend.config["queue_database"] = str(self.root / "queue.sqlite3")
        self.host.queue_count.return_value = 0
        self.backend.context = {"attempt_id": self.run_id, "request": {"model": "gpt-6-astra"}}
        self.backend.state = {"schema_version": 1, "attempt_id": self.run_id, "intents": [], "events": [],
                              "session": {}, "artifacts": {}, "server_instance_id": "b" * 32}
        self.backend.baseline = {"character":{"map_id":1}}
        self.backend.ownership = MagicMock()
        self.backend.quiet = MagicMock()
        self.backend.frozen = MagicMock()
        self.backend.online_identity = MagicMock()
        self.offline_unit = {"LoadState": "loaded", "ActiveState": "inactive", "MainPID": "0",
                             "DropInPaths": "", "Environment": "", "NeedDaemonReload": "no"}
        self.host.unit.return_value = self.offline_unit
        self.host.admin.return_value = {"session": {"state": "waiting", "fresh": True, "pinned": True,
                                                    "artifactsSettled": True}, "bridge": {"run": None}}
        self.host.command.return_value = b"0\n"

    def policy(self):
        return {"schema_version":1,"expected_map_id":1,"min_monsters":1,
                "min_samples":3,"min_span_ms":1000,"timeout_ms":10000}

    def tearDown(self):
        self.temp.cleanup()

    def ref(self, key, value, raw=False):
        path = self.root / (key + (".sql" if raw else ".json"))
        data = value if raw else runtime.encoded(value)
        path.write_bytes(data)
        self.backend.config[key] = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}
        return self.backend.config[key]

    def restore_fixture(self):
        snapshot = {"schema_version": 1, "source": "cosmic_persisted_character", "run_id": self.run_id,
                    "account_logged_in": 0, "captured_at_ms": 2001,
                    "character": {"character_id": 10, "account_id": 20, "level": 100, "exp": 40, "hp": 500},
                    "keymap": [[29, 5, 52], [57, 5, 53]]}
        self.backend.baseline = snapshot
        self.host.snapshot.return_value = snapshot
        self.ref("baseline", b"-- trusted synthetic test SQL\n", raw=True)
        self.ref("baseline_snapshot", snapshot)
        self.ref("scenario", {"id": "synthetic"})
        self.ref("runtime_manifest", {"schema_version": 1})
        self.host.command.side_effect = lambda argv, **kw: (
            b"accounts:InnoDB\ncharacters:InnoDB\nkeymap:InnoDB\n"
            if b"information_schema" in kw.get("data", b"") else b"0\n")

    def test_restore_never_executes_sql_when_server_running(self):
        self.host.unit.return_value = {"LoadState": "loaded", "ActiveState": "active", "MainPID": "123"}
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "restore_requires_stopped_offline"):
            self.backend.restore_baseline()
        self.host.command.assert_not_called()
        self.assertEqual(self.backend.state["intents"], [])

    def test_restore_never_executes_baseline_while_account_online(self):
        self.host.command.return_value = b"2\n"
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "restore_requires_stopped_offline"):
            self.backend.restore_baseline()
        self.assertEqual(self.host.command.call_count, 1)
        self.assertIn(b"SELECT loggedin", self.host.command.call_args.kwargs["data"])

    def test_restore_requires_fresh_pinned_waiting_browser(self):
        self.host.admin.return_value["session"]["fresh"] = False
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "waiting_browser_required"):
            self.backend.restore_baseline()
        self.assertEqual(self.backend.state["intents"], [])

    def test_restore_executes_exact_frozen_bytes_and_compares_snapshot(self):
        self.restore_fixture()
        receipt = self.backend.restore_baseline()
        self.assertTrue(receipt["reset_verified"])
        calls = [call.kwargs["data"] for call in self.host.command.call_args_list]
        self.assertEqual(calls.count(b"-- trusted synthetic test SQL\n"), 1)
        state = json.loads((self.directory / "backend-state.json").read_text())
        self.assertIn("restore_baseline", state["intents"])
        self.assertIn("baseline", state["artifacts"])
        self.assertEqual(self.backend.state["initial"]["captured_at_ms"], 2001)

    def test_partial_restore_cannot_be_automatically_retried(self):
        self.restore_fixture()
        original = self.host.command.side_effect
        def fail_restore(argv, **kwargs):
            if kwargs.get("data") == b"-- trusted synthetic test SQL\n":
                raise runtime.RuntimeErrorCode("database_connection_lost")
            return original(argv, **kwargs)
        self.host.command.side_effect = fail_restore
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "database_connection_lost"):
            self.backend.restore_baseline()
        self.assertNotIn("reset", self.backend.state)
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "operation_already_attempted"):
            self.backend.restore_baseline()

    def test_restored_character_mismatch_never_gets_reset_receipt(self):
        self.restore_fixture()
        self.host.snapshot.return_value = dict(self.backend.baseline, character={"character_id": 10, "exp": 99})
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "restored_baseline_mismatch"):
            self.backend.restore_baseline()
        self.assertNotIn("reset", self.backend.state)

    def test_nontransactional_tables_refuse_restore(self):
        self.restore_fixture()
        original = self.host.command.side_effect
        self.host.command.side_effect = lambda argv, **kw: (b"accounts:MyISAM\n" if b"information_schema" in kw.get("data", b"") else original(argv, **kw))
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "transactional_score_tables_required"):
            self.backend.restore_baseline()
        self.assertFalse(any(call.kwargs.get("data") == b"-- trusted synthetic test SQL\n"
                             for call in self.host.command.call_args_list))

    def test_unowned_running_cosmic_is_never_stopped(self):
        self.host.unit.return_value = {"LoadState": "loaded", "ActiveState": "active", "MainPID": "123"}
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "unowned_server_cleanup_refused"):
            self.backend.cleanup()
        self.host.command.assert_not_called()
        self.host.admin.assert_not_called()

    def test_changed_dropin_blocks_stop_before_any_service_mutation(self):
        unit = {"LoadState": "loaded", "ActiveState": "active", "MainPID": "123"}
        self.host.unit.return_value = unit
        self.backend.state["dropin"] = str(self.root / "wrong.conf")
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "dropin_owner_path_mismatch"):
            self.backend.cleanup()
        self.host.command.assert_not_called()

    def test_cleanup_cannot_report_clean_while_database_online(self):
        self.host.command.return_value = b"2\n"
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "cleanup_requires_stopped_offline"):
            self.backend.cleanup()
        self.assertNotIn("clean", self.backend.state)

    def cleanup_configuration_fixture(self):
        dropin = self.backend.trial_dropin_path()
        dropin.parent.mkdir(parents=True)
        raw = b'[Service]\nEnvironment="MAPLEBENCH_TRIAL_ID=synthetic"\n'
        dropin.write_bytes(raw)
        self.backend.state.update(dropin=str(dropin), dropin_sha256=hashlib.sha256(raw).hexdigest())
        manager = CachedSystemd(dropin, self.offline_unit)
        self.host.unit.side_effect = manager.unit
        self.host.command.side_effect = manager.command
        self.backend.settle_owned_controller = MagicMock()
        self.backend.preserve_failure_evidence = MagicMock()
        return dropin, manager

    def test_cleanup_crash_after_unlink_reloads_cached_configuration_on_recovery(self):
        dropin, manager = self.cleanup_configuration_fixture()
        manager.fail_before_reload = True
        original_unlink = Path.unlink
        def checked_unlink(path, *args, **kwargs):
            checkpoint = json.loads((self.directory / "backend-state.json").read_text())["configuration_cleanup"]
            self.assertEqual(checkpoint, {"path": str(dropin), "sha256": self.backend.state["dropin_sha256"],
                                          "phase": "remove_pending"})
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", checked_unlink), self.assertRaises(SystemExit):
            self.backend.cleanup()
        self.assertFalse(dropin.exists())
        self.assertIsNotNone(manager.loaded)
        stored = json.loads((self.directory / "backend-state.json").read_text())
        self.assertEqual(stored["configuration_cleanup"]["phase"], "reload_pending")
        self.assertFalse(stored["clean"])
        self.assertFalse(self.backend.status()["ready"])
        self.backend.state = stored  # New backend invocation reads only durable state.
        manager.fail_before_reload = False
        self.assertEqual(self.backend.cleanup(), {"clean": True})
        self.assertEqual(manager.reload_calls, 2)
        self.assertIsNone(manager.loaded)
        self.assertEqual(self.backend.state["configuration_cleanup"]["phase"], "verified")
        self.assertTrue(self.backend.status()["ready"])

    def test_cleanup_repeats_reload_after_response_lost_without_recreating_dropin(self):
        dropin, manager = self.cleanup_configuration_fixture()
        manager.fail_after_reload = True
        with self.assertRaises(SystemExit):
            self.backend.cleanup()
        self.assertFalse(dropin.exists())
        self.assertIsNone(manager.loaded)
        self.backend.state = json.loads((self.directory / "backend-state.json").read_text())
        self.assertEqual(self.backend.state["configuration_cleanup"]["phase"], "reload_pending")
        manager.fail_after_reload = False
        self.assertEqual(self.backend.cleanup(), {"clean": True})
        self.assertEqual(manager.reload_calls, 2)
        self.assertFalse(dropin.exists())

    def test_cleanup_zero_exit_reload_must_remove_effective_trial_settings(self):
        dropin, manager = self.cleanup_configuration_fixture()
        manager.apply_reload = False
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "cleanup_configuration_still_loaded"):
            self.backend.cleanup()
        self.assertFalse(dropin.exists())
        self.assertIsNotNone(manager.loaded)
        self.assertFalse(self.backend.state["clean"])
        self.assertFalse(self.backend.status()["ready"])
        self.assertEqual(self.backend.state["configuration_cleanup"]["phase"], "reload_pending")

    def test_cleanup_missing_file_without_owned_removal_cannot_reload_cached_trial(self):
        dropin, manager = self.cleanup_configuration_fixture()
        dropin.unlink()
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "cleanup_dropin_removal_unowned"):
            self.backend.cleanup()
        self.assertEqual(manager.reload_calls, 0)
        self.assertIsNotNone(manager.loaded)
        self.assertFalse(self.backend.status()["ready"])

    def test_cleanup_changed_owned_file_or_checkpoint_never_unlinks_or_reloads(self):
        dropin, manager = self.cleanup_configuration_fixture()
        dropin.write_bytes(b"unrelated replacement")
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "dropin_ownership_lost"):
            self.backend.cleanup()
        self.assertEqual(dropin.read_bytes(), b"unrelated replacement")
        self.assertEqual(manager.reload_calls, 0)
        self.backend.state["configuration_cleanup"] = {"path": str(dropin), "sha256": "0" * 64, "phase": "removed"}
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "cleanup_checkpoint_invalid"):
            self.backend.cleanup()
        self.assertEqual(manager.reload_calls, 0)

    def test_status_requires_absent_effective_trial_config_even_with_stopped_server(self):
        changes = [{"Environment": name + "=synthetic"} for name in runtime.ENV_NAMES]
        changes += [{"DropInPaths": str(self.backend.trial_dropin_path())}, {"NeedDaemonReload": "yes"},
                    {"DropInPaths": None}, {"Environment": None}, {"Environment": '"unterminated'}]
        for values in changes:
            with self.subTest(values=values):
                self.host.unit.return_value = self.offline_unit | values
                result = self.backend.status()
                self.assertTrue(result["server_stopped"])
                self.assertFalse(result["ready"])

    def test_offline_without_native_commit_is_not_successful_logout(self):
        self.backend.owned_server = MagicMock()
        native = self.root / "native"
        native.mkdir()
        (native / "save.jsonl").write_bytes(runtime.encoded({**self.backend.identity(), "kind": "save_committed", "committed_at_ms": 1000}))
        self.backend.state["native_directory"] = str(native)
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "native_logout_commit_missing_or_ambiguous"):
            self.backend.request_ordinary_disconnect()
        self.assertNotIn("committed_at_ms", self.backend.state)

    def test_native_failed_save_invalidates_logout(self):
        self.backend.owned_server = MagicMock()
        native = self.root / "native"
        native.mkdir()
        (native / "save.jsonl").write_bytes(runtime.encoded({**self.backend.identity(), "kind": "save_failed", "committed_at_ms": 2000}))
        self.backend.state["native_directory"] = str(native)
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "native_save_failure_or_identity_mismatch"):
            self.backend.request_ordinary_disconnect()

    def test_offline_positive_native_commit_records_ordinary_logout(self):
        self.backend.owned_server = MagicMock()
        native = self.root / "native"
        native.mkdir()
        (native / "save.jsonl").write_bytes(runtime.encoded({**self.backend.identity(), "kind": "save_committed", "committed_at_ms": 2000}))
        self.backend.state["native_directory"] = str(native)
        result = self.backend.request_ordinary_disconnect()
        self.assertTrue(result["normal_disconnect"])
        self.assertEqual(self.backend.state["committed_at_ms"], 2000)
        self.assertEqual(self.backend.state["events"][-1]["event"], "logged_out")
        persisted = json.loads((self.directory / "backend-state.json").read_text())
        self.assertEqual(persisted["ordinary_logout"]["save_committed_at_ms"], 2000)
        before = self.host.admin.call_count
        self.assertEqual(self.backend.disconnect(), result)
        self.assertEqual(self.backend.disconnect(), result)
        self.assertEqual(self.host.admin.call_count, before)

    def test_disconnect_phase_never_reissues_an_uncertain_navigation(self):
        self.backend.owned_server = MagicMock()
        self.backend.state["intents"] = ["disconnect"]
        self.backend.state["session"]["disconnect_requested_at_ms"] = 1000
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "normal_committed_logout_required"):
            self.backend.disconnect()
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "operation_already_attempted"):
            self.backend.request_ordinary_disconnect()
        self.assertEqual(self.backend.state["session"]["disconnect_requested_at_ms"], 1000)
        self.host.admin.assert_not_called()

    def test_disconnect_intent_is_durable_before_navigation_and_late_logout_is_invalid(self):
        self.backend.owned_server = MagicMock()
        self.host.now.side_effect = [1000, 6001]
        def admin(path, request, **kwargs):
            if request["op"] == "disconnect":
                stored = json.loads((self.directory / "backend-state.json").read_text())
                self.assertIn("disconnect", stored["intents"])
                self.assertEqual(stored["session"]["disconnect_requested_at_ms"], 1000)
                return {}
            return {"session": {"state": "waiting", "fresh": True, "artifactsSettled": True}}
        self.host.admin.side_effect = admin
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "settlement_logout_timeout"):
            self.backend.request_ordinary_disconnect()
        self.assertNotIn("ordinary_logout", self.backend.state)

    def test_collector_cannot_start_without_normal_commit(self):
        self.backend.owned_server = MagicMock()
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "normal_committed_logout_required"):
            self.backend.collect_final()
        self.host.snapshot.assert_not_called()

    def test_start_forwards_only_inherited_lock_descriptions(self):
        self.backend.lock_fds = MagicMock(return_value=[51, 52])
        self.backend.context["lock_paths"] = {"world": "/world.lock", "queue": "/queue.lock"}
        self.backend.admin("start", run_id=self.run_id)
        self.assertEqual(self.host.admin.call_args.kwargs["lock_fds"], [51, 52])
        self.assertEqual(self.host.admin.call_args.args[1]["lock_paths"], self.backend.context["lock_paths"])
        self.backend.admin("status")
        self.assertEqual(self.host.admin.call_args.kwargs["lock_fds"], ())

    def test_new_trial_docker_binding_requires_schema2_and_exact_operator_routes(self):
        for manifest in ({"schema_version":1}, {"schema_version":2}, {"schema_version":2.0,"docker_binding":self.binding}):
            self.backend.manifest=manifest
            with self.assertRaisesRegex(runtime.RuntimeErrorCode,'docker_binding_required'):
                self.backend.docker_binding()
        self.backend.manifest={"schema_version":2,"docker_binding":self.binding}
        self.assertEqual(self.backend.docker_binding(),self.binding)
        for name, value in (('docker','/private/docker'),('docker_socket','/private/docker.sock'),
                            ('docker_launcher','/usr/bin/sudo')):
            with self.subTest(name=name), patch.dict(self.backend.config,{name:value}):
                with self.assertRaisesRegex(runtime.RuntimeErrorCode,'docker_binding_mismatch'):
                    self.backend.docker_binding()
        binding=copy.deepcopy(self.binding);binding['launcher']={'path':'/usr/bin/sudo','sha256':'b'*64}
        self.backend.manifest['docker_binding']=binding
        with patch.dict(self.backend.config,{'docker_launcher':'/usr/bin/sudo'}):
            self.assertEqual(self.backend.docker_binding(),binding)

    def test_failed_api_start_claim_is_durable_and_not_replayed(self):
        self.backend.owned_server = MagicMock()
        self.backend.account_state = MagicMock(return_value=2)
        self.backend.state["session"]["login_at_ms"] = 1000
        self.backend.manifest = {"schema_version": 2, "docker_binding": self.binding, "docker_image_id": "sha256:" + "1" * 64}
        self.backend.context["request"].update(scenario_fingerprint="2" * 64, baseline_sha256="3" * 64,
            budgets={"controller_seconds": 24, "max_actions": 80, "max_output_tokens": 3000, "max_total_tokens": 9000})
        from full_client_bridge import PROMPT
        prompt = PROMPT.format(program_seconds=22, action_limit=80, sdk_request_limit=100)
        self.backend.scenario = {"program_seconds": 22, "instructions_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                                 "reasoning": {"effort": "low"}, "readiness_policy":self.policy()}
        self.backend.admin = MagicMock(side_effect=runtime.RuntimeErrorCode("uncertain_transport"))
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "uncertain_transport"):
            self.backend.run_controller()
        persisted = json.loads((self.directory / "backend-state.json").read_text())
        self.assertIn("run_controller", persisted["intents"])
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "operation_already_attempted"):
            self.backend.run_controller()
        self.assertEqual(sum(call.args[0] == "start" for call in self.backend.admin.call_args_list), 1)
        self.assertTrue(self.backend.state["failure_disconnect_unconfirmed"])

    def test_new_runtime_requires_frozen_readiness_policy_and_baseline_map(self):
        from full_client_bridge import PROMPT
        scenario={"id":"future-fixture","program_seconds":22,"reasoning":{"effort":"low"},
            "instructions_sha256":hashlib.sha256(PROMPT.format(program_seconds=22,action_limit=80,sdk_request_limit=100).encode()).hexdigest(),
            "trial_budgets":{"max_total_tokens":30000},"settlement_policy":dict(runtime.SETTLEMENT_POLICY),
            "budgets":{"api_requests":1,"output_tokens":3000,"total_tokens":30000,"program_ms":22000,
                       "run_ms":85000,"actions":80,"sdk_requests":100},"readiness_policy":self.policy()}
        self.ref('baseline_snapshot',{'account_logged_in':0,'character':{'character_id':10,'account_id':20,'map_id':1}})
        self.ref('runtime_manifest',{'schema_version':2,'docker_binding':self.binding,
                                   'working_directory':str(self.root),'wz_path':str(self.root/'wz')})
        self.ref('scenario',scenario)
        self.backend.load_pins()
        for altered,reason in [(dict(scenario,readiness_policy=None),'readiness_policy_required'),
                (dict(scenario,readiness_policy=self.policy()|{'expected_map_id':2}),'invalid_readiness_policy'),
                (dict(scenario,readiness_policy=self.policy()|{'min_samples':2}),'invalid_readiness_policy'),
                (dict(scenario,budgets=scenario['budgets']|{'run_ms':75000}),'frozen_bridge_budgets_mismatch')]:
            with self.subTest(reason=reason):
                self.ref('scenario',altered)
                with self.assertRaisesRegex(runtime.RuntimeErrorCode,reason): self.backend.load_pins()
        self.host.command.assert_not_called(); self.host.admin.assert_not_called()

    def test_runtime_forwards_the_validated_policy_in_single_start(self):
        self.controller_fixture()
        original=self.backend.admin
        self.backend.admin=MagicMock(side_effect=original)
        self.backend.run_controller()
        starts=[call for call in self.backend.admin.call_args_list if call.args[0]=='start']
        self.assertEqual(len(starts),1)
        self.assertEqual(starts[0].kwargs['readiness_policy'],self.policy())

    def controller_fixture(self, terminal="completed"):
        from full_client_bridge import PROMPT
        self.host.now.return_value = 25000
        self.backend.owned_server = MagicMock()
        self.backend.manifest = {"schema_version": 2, "docker_binding": self.binding, "docker_image_id": "sha256:" + "1" * 64}
        self.backend.context["request"].update(scenario_fingerprint="2" * 64, baseline_sha256="3" * 64,
            budgets={"controller_seconds": 24, "max_actions": 80, "max_output_tokens": 3000, "max_total_tokens": 9000})
        self.backend.scenario = {"program_seconds": 22, "reasoning": {"effort": "low"},
            "instructions_sha256": hashlib.sha256(PROMPT.format(program_seconds=22, action_limit=80,
                                                                  sdk_request_limit=100).encode()).hexdigest(),
            "settlement_policy": dict(runtime.SETTLEMENT_POLICY), "readiness_policy":self.policy()}
        self.backend.state["session"]["login_at_ms"] = 1000
        native = self.root / "native"
        native.mkdir()
        (native / "save.jsonl").write_bytes(runtime.encoded({**self.backend.identity(), "kind": "save_committed",
                                                            "committed_at_ms": 25000}))
        self.backend.state["native_directory"] = str(native)
        online, events = [True], []
        self.backend.account_state = lambda: 2 if online[0] else 0
        run = {"id": self.run_id, "status": terminal, "workerActive": False,
               "evidenceStatus": "saved" if terminal == "completed" else "failed", "recordingStatus": "saved"}
        def admin(op, **kwargs):
            events.append(op)
            if op == "disconnect":
                stored = json.loads((self.directory / "backend-state.json").read_text())
                self.assertIn("disconnect", stored["intents"])
                self.assertNotIn("result", stored)
                if terminal == "completed":
                    self.assertEqual(stored["upload_status"]["status"]["bridge"]["run"]["id"], self.run_id)
                online[0] = False
            if op == "release_failed_run":
                run["failureAcknowledged"] = True
            return {"bridge": {"run": dict(run), "browserReleasePending": False},
                    "session": {"state": "connected" if online[0] else "waiting", "fresh": True,
                                "artifactsSettled": True}}
        self.backend.admin = admin
        def metadata():
            self.assertFalse(online[0])
            events.append("metadata")
            self.backend.state["result"] = {"source": "full-client-trial",
                "controller": run | {"model": "gpt-6-astra", "mode": "api", "dockerImageId": self.backend.manifest["docker_image_id"], "dockerBinding": self.binding},
                "api": {"model": "gpt-6-astra", "status": "completed", "usage": {"output_tokens": 30, "total_tokens": 50}},
                "trialContext": {"scenario_fingerprint": "2" * 64, "baseline_sha256": "3" * 64},
                "timing": {"startedAtMs": 1000, "endedAtMs": 23000},
                "timeline": {"api_started_ms": 100, "api_ended_ms": 2000, "program_started_ms": 2000,
                             "program_ended_ms": 22000}, "program": {"actions": 4}}
            self.backend.state["artifacts"]["capture"] = self.backend.artifact("capture.json",
                {"end_wall_ms": 24000, "clock": {"server_received_ms": 1000, "client_sent_ms": 1000}})
        self.backend.copy_controller_metadata = MagicMock(side_effect=metadata)
        self.backend.copy_run = MagicMock()
        self.backend.verify_api_result = MagicMock()
        return online, events

    def test_adaptive_controller_retains_ordinary_logout_before_metadata(self):
        from full_client_adaptive import DEFAULT_PROTOCOL, PROTOCOL, prompt
        online, events = self.controller_fixture()
        protocol = copy.deepcopy(DEFAULT_PROTOCOL)
        self.backend.scenario.update(protocol=PROTOCOL, adaptive_protocol=protocol, program_seconds=300,
            instructions_sha256=hashlib.sha256(prompt(protocol).encode()).hexdigest())
        self.backend.context["request"].update(schema_version=2, protocol=PROTOCOL)
        original = self.backend.admin
        self.backend.admin = MagicMock(side_effect=original)
        self.backend.verify_adaptive_controller = MagicMock(return_value={"protocol":PROTOCOL,"api_requests":12})
        receipt = self.backend.run_controller()
        self.assertFalse(online[0])
        self.assertLess(events.index("disconnect"), events.index("metadata"))
        self.assertEqual(events.count("start"),1)
        start = next(call for call in self.backend.admin.call_args_list if call.args[0]=="start")
        self.assertEqual(start.kwargs['duration_seconds'],300)
        self.assertEqual(start.kwargs['adaptive_protocol'],protocol)
        self.backend.verify_adaptive_controller.assert_called_once()
        self.backend.verify_api_result.assert_not_called()
        self.assertEqual(receipt['api_requests'],12)

    def test_completed_run_logs_out_before_any_artifact_work(self):
        online, events = self.controller_fixture()
        receipt = self.backend.run_controller()
        self.assertFalse(online[0])
        self.assertLess(events.index("disconnect"), events.index("metadata"))
        self.assertEqual(events.count("start"), 1)
        self.assertEqual(events.count("disconnect"), 1)
        self.assertEqual(receipt["actions"], 4)
        self.backend.copy_run.assert_not_called()
        self.backend.frozen.assert_not_called()
        self.assertEqual(self.backend.state["session"]["upload_observed_at_ms"], 25000)

    def test_failed_run_ordinary_disconnects_before_quarantine_without_replaying_api(self):
        online, events = self.controller_fixture("failed")
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "controller_run_failed"):
            self.backend.run_controller()
        self.assertFalse(online[0])
        self.assertLess(events.index("release_failed_run"), events.index("disconnect"))
        self.assertEqual(events.count("start"), 1)
        self.assertEqual(events.count("disconnect"), 1)
        self.backend.copy_controller_metadata.assert_not_called()
        self.backend.copy_run.assert_not_called()
        self.backend.frozen.assert_not_called()
        self.assertTrue(self.backend.state["ordinary_logout"])

    def test_settlement_rejects_overlong_upload_navigation_logout_or_capture(self):
        self.controller_fixture()
        self.backend.run_controller()
        session = self.backend.state["session"]
        for field, value in (("upload_observed_at_ms", 28001), ("disconnect_requested_at_ms", 28001),
                             ("logged_out_at_ms", 30001), ("upload_observed_at_ms", 22999),
                             ("upload_observed_at_ms", True)):
            original = session[field]
            session[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(runtime.RuntimeErrorCode):
                self.backend.validate_settlement()
            session[field] = original
        capture = {"end_wall_ms": 25001, "clock": {"server_received_ms": 1000, "client_sent_ms": 1000}}
        self.backend.state["artifacts"]["capture"] = self.backend.artifact("late-capture.json", capture)
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "settlement_capture_tail_exceeded"):
            self.backend.validate_settlement()

    def test_settlement_requires_frozen_policy_and_actual_upload_status_identity(self):
        self.controller_fixture()
        self.backend.run_controller()
        self.backend.state["upload_status"]["status"]["bridge"]["run"]["id"] = "f" * 32
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "settlement_status_mismatch"):
            self.backend.validate_settlement()
        self.backend.scenario["settlement_policy"]["disconnect_after_program_ms"] = 6000
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "invalid_settlement_policy"):
            self.backend.validate_settlement()

    def perform_fixture(self):
        request = {"schema_version": 1, "model": "gpt-6-astra", "scenario_fingerprint": "2" * 64,
                   "baseline_sha256": "3" * 64, "budgets": {"total_seconds": 120, "operation_seconds": 30,
                   "controller_seconds": 24, "max_actions": 80, "max_api_requests": 1,
                   "max_output_tokens": 3000, "max_total_tokens": 9000}}
        self.backend.config.update(baseline={"sha256": "3" * 64}, scenario={"sha256": "2" * 64},
                                   runtime_manifest={"sha256": "4" * 64})
        self.backend.scenario = {"trial_budgets": request["budgets"]}
        self.backend.load_pins = MagicMock()
        return {"attempt_id": self.run_id, "attempt_dir": str(self.directory), "request": request}

    def test_login_perform_inventories_only_before_client_connects(self):
        context = self.perform_fixture()
        online, events = [False], []
        def freeze():
            self.assertFalse(online[0])
            events.append("freeze")
        def login():
            stored = json.loads((self.directory / "backend-state.json").read_text())
            self.assertIn("prelogin_frozen", stored)
            online[0] = True
            self.backend.state["session"]["login_at_ms"] = 2000
            events.append("login")
            return {"ordinary_login": True}
        self.backend.frozen.side_effect = freeze
        self.backend.login = login
        self.backend.owned_server = MagicMock()
        self.backend.account_state = lambda: 2 if online[0] else 0
        self.backend.perform("login", context, timeout_seconds=30)
        self.assertEqual(events, ["freeze", "login"])
        self.backend.online_identity.assert_called_once()

    def test_run_and_recovery_cleanup_perform_disconnect_before_full_inventory(self):
        context = self.perform_fixture()
        self.backend.state["prelogin_frozen"] = {"scenario_sha256": "2" * 64, "manifest_sha256": "4" * 64,
                                                 "checked_at_ms": 1000}
        self.backend.state["session"]["login_at_ms"] = 2000
        for operation in ("run_controller", "cleanup"):
            online, events = [True], []
            def body():
                events.append(operation)
                online[0] = False
                return {"clean": True}
            def freeze():
                self.assertFalse(online[0])
                events.append("freeze")
            setattr(self.backend, operation, body)
            self.backend.frozen.side_effect = freeze
            self.backend.account_state = lambda: 2 if online[0] else 0
            self.backend.perform(operation, context | {"recovery": operation == "cleanup"}, timeout_seconds=30)
            self.assertEqual(events, [operation, "freeze"])

    def test_recovery_status_and_online_preflight_never_inventory_live_assets(self):
        self.backend.context["recovery"] = True
        self.backend.load_pins = MagicMock()
        self.host.command.return_value = b"2\n"
        result = self.backend.status()
        self.assertFalse(result["ready"])
        self.backend.frozen.assert_not_called()
        self.backend.ownership.assert_called_once()
        self.backend.load_pins.assert_called_once()
        self.backend.context["recovery"] = False
        self.backend.status()
        self.backend.frozen.assert_not_called()

    def test_long_operation_caps_inventory_at_its_own_hard_deadline(self):
        # Adaptive operations can last 360 seconds, but the inventory contract
        # deliberately rejects a scan budget above 300 seconds.
        self.backend.account_state = MagicMock(return_value=0)
        self.backend.load_pins = MagicMock()
        self.backend.manifest = {"working_directory": str(self.root), "wz_path": str(self.root)}
        self.backend.docker_binding = MagicMock(return_value=self.binding)
        for remaining, expected in ((359.8, 300), (1800, 300), (120.8, 120), (1.2, 1)):
            self.host.remaining.return_value = remaining
            with self.subTest(remaining=remaining), patch.object(runtime, "verify_manifest",
                    side_effect=runtime.RuntimeErrorCode("inventory_test_boundary")) as verify:
                with self.assertRaisesRegex(runtime.RuntimeErrorCode, "inventory_test_boundary"):
                    runtime.CosmicRuntime.frozen(self.backend)
                self.assertEqual(verify.call_args.kwargs["limits"], {"timeout_seconds": expected})

    def test_full_inventory_and_large_artifact_reads_require_offline_account(self):
        self.backend.account_state = MagicMock(return_value=2)
        for operation in (lambda: runtime.CosmicRuntime.frozen(self.backend),
                          self.backend.copy_controller_metadata, self.backend.copy_run,
                          self.backend.preserve_failure_evidence):
            with self.assertRaises(runtime.RuntimeErrorCode):
                operation()

    def video_fixture(self):
        source = Path(self.backend.config["relay_output_root"]) / self.run_id
        source.mkdir(parents=True)
        video = b"synthetic media bytes; decoder is mocked"
        (source / "video.webm").write_bytes(video)
        recording = {"sha256": hashlib.sha256(video).hexdigest(), "duration_ms": 1000}
        self.backend.state["ordinary_logout"] = {"synthetic": True}
        self.backend.state["result"] = {"synthetic": True}
        self.backend.state["artifacts"]["recording"] = self.backend.artifact("recording.json", recording)

    def test_offline_probe_failure_has_distinct_safe_code(self):
        self.video_fixture()
        with patch("full_client_publish._probe_video", side_effect=runtime.EvidenceError("/private/secret-marker")):
            with self.assertRaisesRegex(runtime.RuntimeErrorCode, "^recording_probe_failed$") as error:
                self.backend.copy_run()
        self.assertNotIn("secret-marker", str(error.exception))

    def test_offline_capture_failure_has_distinct_safe_code(self):
        self.video_fixture()
        probe = {"duration_ms": 1000, "width": 800, "height": 720, "frames": 60}
        with patch("full_client_publish._probe_video", return_value=probe), \
                patch("full_client_publish.verify_capture_bundle", side_effect=runtime.EvidenceError("secret-marker")):
            with self.assertRaisesRegex(runtime.RuntimeErrorCode, "^capture_verification_failed$") as error:
                self.backend.copy_run()
        self.assertNotIn("secret-marker", str(error.exception))

    def test_offline_video_duration_must_match_independent_capture(self):
        self.video_fixture()
        with patch("full_client_publish._probe_video", return_value={"duration_ms": 899}), \
                patch("full_client_publish.verify_capture_bundle") as capture:
            with self.assertRaisesRegex(runtime.RuntimeErrorCode, "recording_duration_mismatch"):
                self.backend.copy_run()
            capture.assert_not_called()

    def test_status_does_not_treat_stale_waiting_page_as_ready(self):
        self.host.admin.return_value["session"]["fresh"] = False
        result = self.backend.status()
        self.assertFalse(result["ready"])
        self.assertTrue(result["account_offline"])

    def test_status_accepts_actual_initial_bridge_idle_only_without_run_identity(self):
        run = {"status": "idle", "mode": "manual", "model": None}
        self.host.admin.return_value["bridge"]["run"] = run
        self.assertTrue(self.backend.status()["controller_idle"])
        run["id"] = None
        self.assertTrue(self.backend.status()["controller_idle"])
        run["id"] = self.run_id
        self.assertFalse(self.backend.status()["controller_idle"])
        run.update(id=None, status="running")
        self.assertFalse(self.backend.status()["controller_idle"])
        run.update(status="idle", workerActive=True)
        self.assertFalse(self.backend.status()["controller_idle"])
        run.update(workerActive=False, leaseReleasePending=True)
        self.assertFalse(self.backend.status()["controller_idle"])
        run.update(leaseReleasePending=False)
        self.host.admin.return_value["bridge"]["browserReleasePending"] = True
        self.assertFalse(self.backend.status()["controller_idle"])

    def test_stopped_worker_does_not_hide_pending_queue_rows(self):
        self.host.queue_count.return_value = 1
        result = self.backend.status()
        self.assertFalse(result["queue_idle"])
        self.assertFalse(result["ready"])

    def test_queue_reader_is_read_only_and_counts_all_active_states(self):
        import sqlite3
        path = self.root / "queue.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE trials(status TEXT)")
            db.executemany("INSERT INTO trials VALUES (?)", [(s,) for s in ("queued", "running", "rendering", "completed")])
        before = path.read_bytes()
        host = runtime.Host()
        host.deadline = runtime.time.monotonic() + 10
        self.assertEqual(host.queue_count(str(path)), 3)
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "queue_database_missing"):
            host.queue_count(str(self.root / "missing.sqlite3"))
        self.assertFalse((self.root / "missing.sqlite3").exists())

    def test_kernel_ancestry_and_configured_lock_inodes_are_required(self):
        self.ref("orchestrator", b"# frozen synthetic source\n", raw=True)
        paths = {}
        locks = []
        for key in ("world", "queue"):
            path = self.root / (key + ".lock")
            path.touch()
            self.backend.config[key + "_lock"] = str(path)
            paths[key] = str(path)
            info = path.stat()
            locks.append(f"1: FLOCK ADVISORY WRITE 100 {os.major(info.st_dev):x}:{os.minor(info.st_dev):x}:{info.st_ino} 0 EOF")
        self.backend.context.update(lock_owner_pid=100, guard_pid=200, guard_parent_pid=100, lock_paths=paths)
        source = self.backend.config["orchestrator"]["path"].encode()
        self.host.proc.side_effect = lambda pid, name: (b"PPid:\t100\n" if name == "status" else
            b"/usr/bin/python3\0" + source + b"\0" + (b"_adapter_guard\0" if pid == 200 else b"run\0"))
        self.host.locks.return_value = "\n".join(locks)
        with patch.object(runtime.os, "geteuid", return_value=0), patch.object(runtime.os, "getppid", return_value=200), patch.object(runtime.sys, "platform", "linux"):
            runtime.CosmicRuntime.ownership(self.backend)
            self.host.locks.return_value = locks[0]
            with self.assertRaisesRegex(runtime.RuntimeErrorCode, "world_or_queue_lock_not_owned"):
                runtime.CosmicRuntime.ownership(self.backend)
            self.host.proc.side_effect = lambda pid, name: b"PPid:\t999\n"
            with self.assertRaisesRegex(runtime.RuntimeErrorCode, "guard_ancestry_mismatch"):
                runtime.CosmicRuntime.ownership(self.backend)

    def test_no_phase_receipt_on_backend_deadline(self):
        host = runtime.Host()
        host.deadline = 0
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "operation_deadline"):
            host.remaining()

    def test_frozen_file_byte_changes_rejected(self):
        ref = self.ref("scenario", {"id": "original"})
        Path(ref["path"]).write_text('{"id":"changed"}')
        with self.assertRaises(ValueError):
            runtime.ref_bytes(ref)

    def test_private_capture_rejects_symlink_and_oversized_file(self):
        original = self.root / "source"
        original.write_bytes(b"abcdef")
        link = self.root / "link"
        link.symlink_to(original)
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "artifact_symlink"):
            self.backend.read_stable(link, 10)
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "artifact_size_limit"):
            self.backend.read_stable(original, 3)

    def test_server_ready_requires_markers_and_its_own_listening_sockets(self):
        self.backend.owned_server = MagicMock(return_value={"MainPID": "123"})
        self.backend.state["invocation_id"] = "c" * 32
        self.backend.config["game_ports"] = [8484, 7575]
        self.host.command.return_value = b"MapleBench persistence journal initialized\nCosmic is now online after 20 ms.\n"
        self.host.listening_ports.return_value = {8484}
        self.assertFalse(self.backend.server_ready())
        self.host.listening_ports.return_value = {8484, 7575}
        self.assertTrue(self.backend.server_ready())
        self.host.command.return_value += b"MapleBench persistence journal failed\n"
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "native_startup_or_save_failed"):
            self.backend.server_ready()

    def test_native_initialization_without_online_marker_does_not_consume_login(self):
        self.backend.owned_server = MagicMock(return_value={"MainPID": "123"})
        self.backend.state["invocation_id"] = "c" * 32
        self.backend.config["game_ports"] = [8484, 7575]
        self.host.command.return_value = b"MapleBench persistence journal initialized\n"
        self.host.listening_ports.return_value = {8484, 7575}
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "server_not_ready_for_ordinary_login"):
            self.backend.login()
        self.host.admin.assert_not_called()

    def test_startup_timeout_retains_specific_last_observation_without_log_contents(self):
        self.backend.owned_server = MagicMock(return_value={"MainPID": "123"})
        self.backend.state["invocation_id"] = "c" * 32
        self.backend.config["game_ports"] = [8484, 7575]
        initialized = b"MapleBench persistence journal initialized\n"
        online = b"Cosmic is now online after 20 ms.\n"
        cases = [(b"", {8484, 7575}, "native_log_unavailable"),
                 (b"private unrelated content\n", {8484, 7575}, "native_journal_initialization_missing"),
                 (initialized, {8484, 7575}, "native_online_marker_missing"),
                 (initialized + online, {8484}, "native_listener_unavailable")]
        self.host.sleep.side_effect = runtime.RuntimeErrorCode("operation_deadline")
        for logs, ports, code in cases:
            with self.subTest(code=code):
                self.host.command.return_value = logs
                self.host.listening_ports.return_value = ports
                with self.assertRaisesRegex(runtime.RuntimeErrorCode, "^" + code + "$"):
                    self.backend.wait_for_server_ready()
                saved = json.loads((self.directory / "backend-state.json").read_text())["startup_readiness"]
                self.assertEqual(saved["invocation_id"], "c" * 32)
                self.assertEqual(saved["log_bytes"], len(logs))
                self.assertNotIn("private unrelated", json.dumps(saved))
                self.assertIn("_SYSTEMD_INVOCATION_ID=" + "c" * 32, self.host.command.call_args.args[0])

    def test_startup_does_not_mask_owned_instance_failure_or_stale_diagnostics(self):
        self.backend.state["invocation_id"] = "c" * 32
        self.backend.state["startup_readiness"] = {"invocation_id": "d" * 32, "log_bytes": 0}
        self.backend.owned_server = MagicMock(side_effect=runtime.RuntimeErrorCode("operation_deadline"))
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "^operation_deadline$"):
            self.backend.wait_for_server_ready()
        self.backend.owned_server.side_effect = runtime.RuntimeErrorCode("server_instance_ownership_lost")
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "^server_instance_ownership_lost$"):
            self.backend.wait_for_server_ready()

    def test_incomplete_next_probe_does_not_reclassify_previous_missing_evidence(self):
        self.backend.owned_server = MagicMock(return_value={"MainPID": "123"})
        self.backend.state["invocation_id"] = "c" * 32
        self.backend.config["game_ports"] = [8484]
        self.host.listening_ports.return_value = set()
        self.host.command.side_effect = [b"", runtime.RuntimeErrorCode("operation_deadline")]
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "^operation_deadline$"):
            self.backend.wait_for_server_ready()
        self.assertEqual(self.backend.state["startup_readiness"]["log_bytes"], 0)
        self.host.sleep.assert_called_once_with()

    def test_startup_ambiguous_markers_fail_without_waiting_or_login(self):
        self.backend.owned_server = MagicMock(return_value={"MainPID": "123"})
        self.backend.state["invocation_id"] = "c" * 32
        self.host.command.return_value = b"MapleBench persistence journal initialized\n" * 2
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "^native_startup_markers_ambiguous$"):
            self.backend.wait_for_server_ready()
        self.host.sleep.assert_not_called()
        self.host.admin.assert_not_called()

    def test_native_diagnostic_persistence_changes_only_with_observations(self):
        self.backend.owned_server = MagicMock(return_value={"MainPID": "123"})
        self.backend.state["invocation_id"] = "c" * 32
        self.backend.config["game_ports"] = [8484]
        self.host.command.return_value = b""
        self.host.listening_ports.return_value = set()
        with patch.object(self.backend, "persist", wraps=self.backend.persist) as persist:
            self.assertFalse(self.backend.server_ready())
            self.assertFalse(self.backend.server_ready())
            self.assertEqual(persist.call_count, 1)
            self.host.command.return_value = b"MapleBench persistence journal initialized\n"
            self.assertFalse(self.backend.server_ready())
            self.assertEqual(persist.call_count, 2)

    def test_proc_reader_is_byte_bounded_and_checks_deadline(self):
        host = runtime.Host()
        host.remaining = MagicMock(return_value=1)
        stream = io.BytesIO(b"x" * 34)
        with patch.object(runtime, "JSON_LIMIT", 32), patch.object(Path, "open", return_value=stream):
            with self.assertRaisesRegex(runtime.RuntimeErrorCode, "^proc_output_limit$"):
                host.proc(123, "net/tcp")
        host.remaining.side_effect = runtime.RuntimeErrorCode("operation_deadline")
        with patch.object(Path, "open") as opening:
            with self.assertRaisesRegex(runtime.RuntimeErrorCode, "^operation_deadline$"):
                host.proc(123, "status")
            opening.assert_not_called()

    def test_native_socket_scan_stops_before_reading_excess_descriptors(self):
        host = runtime.Host()
        host.remaining = MagicMock(return_value=1)
        host.proc = MagicMock(return_value=b"")
        entries = [MagicMock(path="/synthetic/fd/" + str(i)) for i in range(4)]
        with patch.object(runtime, "MAX_PROCESS_FDS", 2), \
                patch.object(runtime.os, "scandir", return_value=contextlib.nullcontext(iter(entries))), \
                patch.object(runtime.os, "readlink", return_value="socket:[1]") as readlink:
            with self.assertRaisesRegex(runtime.RuntimeErrorCode, "^server_descriptor_limit$"):
                host.listening_ports(123)
            self.assertEqual(readlink.call_count, 2)
            host.proc.assert_not_called()

    def test_host_command_timeout_is_safe_deadline_code(self):
        host = runtime.Host()
        host.remaining = MagicMock(return_value=1)
        with patch.object(runtime.subprocess, "run", side_effect=subprocess.TimeoutExpired("private", 1)):
            with self.assertRaisesRegex(runtime.RuntimeErrorCode, "^operation_deadline$"):
                host.command(["/synthetic/command"])

    def test_cleanup_cancels_then_preserves_failure_before_acknowledging(self):
        statuses = [
            {"bridge": {"run": {"id": self.run_id, "status": "running", "workerActive": True}, "browserReleasePending": False}},
            {"bridge": {"run": {"id": self.run_id, "status": "failed", "workerActive": False}, "browserReleasePending": True}},
            {"bridge": {"run": {"id": self.run_id, "status": "failed", "workerActive": False}, "browserReleasePending": False}}]
        events = []
        def admin(op, **kwargs):
            events.append(op)
            if op == "status":
                return statuses.pop(0)
            if op == "release_failed_run":
                stored = json.loads((self.directory / "backend-state.json").read_text())
                self.assertEqual(stored["failure_cleanup_status"]["bridge"]["run"]["id"], self.run_id)
                self.assertFalse((self.directory / "failure-cleanup-status.json").exists())
            return {}
        self.backend.admin = admin
        self.backend.settle_owned_controller()
        self.assertEqual(events, ["status", "cancel", "status", "status", "release_failed_run"])
        self.assertNotIn("failure_evidence_preserved", self.backend.state)
        self.backend.preserve_failure_evidence()
        self.assertTrue(self.backend.state["failure_evidence_preserved"])

    def test_cleanup_refuses_to_cancel_another_active_run(self):
        self.host.admin.return_value = {"bridge": {"run": {"id": "f" * 32, "status": "running", "workerActive": True}}}
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "unowned_controller_cleanup_refused"):
            self.backend.settle_owned_controller()
        self.host.admin.assert_called_once()

    def test_successful_run_cleanup_does_not_acknowledge_failure(self):
        self.host.admin.return_value = {"bridge": {"run": {"id": self.run_id, "status": "completed", "workerActive": False,
                                                              "recordingStatus": "saved"}, "browserReleasePending": False}}
        self.backend.settle_owned_controller()
        self.assertTrue(all(call.args[1]["op"] == "status" for call in self.host.admin.call_args_list))

    def test_candidate_keeps_actual_artifacts_but_never_invents_visual_review(self):
        recording = {"path": "video.webm", "sha256": "1" * 64, "reviewed": False, "interrupted": None}
        arts = {"recording": self.backend.artifact("recording.json", recording),
                "video": {"path": "video.webm", "sha256": "1" * 64}}
        self.backend.state["result"] = {"source": "full-client-trial", "timeline": {"status": "completed"}}
        self.backend.scenario = {"id": "synthetic", "budgets": {"actions": 80}}
        self.backend.config["scenario"] = {"sha256": "2" * 64}
        self.backend.config["baseline"] = {"sha256": "3" * 64}
        self.backend.write_publication_candidate({"publication_eligible": False}, arts)
        candidate = json.loads((self.directory / "publication-candidate.json").read_text())
        self.assertEqual(candidate["candidate_status"], "awaiting_exact_recording_review")
        self.assertEqual(candidate["artifacts"], arts)
        self.assertIs(candidate["video"]["reviewed"], False)
        self.assertIsNone(candidate["video"]["interrupted"])
        self.assertNotIn("video_review", candidate["artifacts"])
        self.assertNotIn("ready", candidate)

    def web_fixture(self):
        script = self.root / "repo/scripts/serve-full-client.py"
        client = self.root / "client"
        required = [script, *(script.parent / name for name in ("full_client_bridge.py", "full_client_adaptive.py", "full_client_session.py", "full_client_capture.py", "full_client_docker.py", "full_client_readiness.py", "maple_agent.py", "agent-sandbox.mjs")),
                    *(self.root / "repo/ui/full-client" / name for name in ("controller.js", "waiting.html")),
                    *(client / "web" / name for name in ("index.html", "assets_server.py", "ws_proxy.py"))]
        for path in required:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic frozen source")
        self.backend.manifest = {"client_js": {"path": str(client / "build/JourneyClient.js")},
                                 "client_wasm": {"path": str(client / "build/JourneyClient.wasm")},
                                 "extra_files": [{"path": str(path), "sha256": "1" * 64} for path in required]}
        (client / "assets").mkdir()
        asset = self.root / "Map.nx"
        asset.write_bytes(b"synthetic asset")
        (client / "assets/Map.nx").symlink_to(asset)
        self.backend.manifest["extra_files"].append({"path": str(asset), "sha256": "2" * 64})
        self.backend.config.update(web_script=str(script), relay_output_root=str(self.root / "relay/runs"),
                                   world_lock=str(self.root / "world.lock"), queue_lock=str(self.root / "queue.lock"))
        self.ref("web_python", b"synthetic interpreter", raw=True)
        executable = self.backend.config["web_python"]["path"]
        env = {"MAPLEBENCH_CLIENT_ROOT": str(client), "MAPLEBENCH_CLIENT_OUTPUT": str(self.root / "relay"),
               "MAPLEBENCH_ADMIN_SOCKET": self.backend.config["admin_socket"],
               "MAPLEBENCH_WORLD_LOCK_FILE": self.backend.config["world_lock"],
               "MAPLEBENCH_QUEUE_LOCK_FILE": self.backend.config["queue_lock"]}
        values = {"cmdline": (executable + "\0" + str(script) + "\0").encode(),
                  "status": b"Uid:\t1234\t1234\t1234\t1234\n",
                  "environ": b"\0".join((key + "=" + value).encode() for key, value in env.items())}
        self.host.proc.side_effect = lambda pid, name: values[name]
        self.host.executable.return_value = executable
        self.host.process_started_ms.return_value = runtime.time.time() * 1000 + 10000
        return values

    def test_active_web_must_serve_the_exact_frozen_client_root(self):
        values = self.web_fixture()
        user = MagicMock(pw_uid=1234)
        with patch.object(runtime.pwd, "getpwnam", return_value=user):
            self.backend.web_identity({"MainPID": "123", "User": "synthetic"})
            values["environ"] = values["environ"].replace(b"MAPLEBENCH_CLIENT_ROOT=", b"WRONG_CLIENT_ROOT=")
            with self.assertRaisesRegex(runtime.RuntimeErrorCode, "web_runtime_paths_mismatch"):
                self.backend.web_identity({"MainPID": "123", "User": "synthetic"})

    def test_active_web_requires_frozen_imports_and_restart_after_source_change(self):
        self.web_fixture()
        with patch.object(runtime.pwd, "getpwnam", return_value=MagicMock(pw_uid=1234)):
            self.host.process_started_ms.return_value = 0
            with self.assertRaisesRegex(runtime.RuntimeErrorCode, "web_process_predates_frozen_sources"):
                self.backend.web_identity({"MainPID": "123", "User": "synthetic"})
            self.backend.manifest["extra_files"].pop(0)
            with self.assertRaisesRegex(runtime.RuntimeErrorCode, "serving_sources_not_frozen"):
                self.backend.web_identity({"MainPID": "123", "User": "synthetic"})

    def test_container_dispatcher_cannot_be_omitted_from_frozen_runtime(self):
        self.web_fixture()
        self.backend.manifest["extra_files"] = [
            ref for ref in self.backend.manifest["extra_files"]
            if Path(ref["path"]).name != "agent-sandbox.mjs"]
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "serving_sources_not_frozen"):
            self.backend.web_identity({"MainPID": "123", "User": "synthetic"})
        self.host.proc.assert_not_called()

    def test_readiness_helper_cannot_be_omitted_from_frozen_runtime(self):
        self.web_fixture()
        self.backend.manifest['extra_files']=[ref for ref in self.backend.manifest['extra_files']
                                             if Path(ref['path']).name!='full_client_readiness.py']
        with self.assertRaisesRegex(runtime.RuntimeErrorCode,'serving_sources_not_frozen'):
            self.backend.web_identity({'MainPID':'123','User':'synthetic'})
        self.host.proc.assert_not_called()

    def test_web_asset_link_inventory_cannot_switch_or_omit_frozen_files(self):
        self.web_fixture()
        asset_link = self.root / "client/assets/Map.nx"
        asset_link.unlink()
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "client_asset_inventory_mismatch"):
            self.backend.web_identity({"MainPID": "123", "User": "synthetic"})
        other = self.root / "Other.nx"
        other.write_bytes(b"wrong asset")
        asset_link.symlink_to(other)
        with self.assertRaisesRegex(runtime.RuntimeErrorCode, "unexpected_client_asset_entry"):
            self.backend.web_identity({"MainPID": "123", "User": "synthetic"})

    def test_trial_dropin_overrides_inherited_legacy_bot_mode(self):
        native_root = Path(self.backend.config["native_output_root"])
        native_root.mkdir(mode=0o711 if os.geteuid() == 0 else 0o700)
        native_root.chmod(0o711 if os.geteuid() == 0 else 0o700)
        Path(self.backend.config["dropin_root"]).mkdir()
        uid = os.geteuid() or 1234
        user = MagicMock(pw_uid=uid, pw_gid=os.getegid(), pw_name="synthetic")
        before = self.offline_unit | {"User": "synthetic", "Environment": "MAPLEBENCH_ENABLED=true",
                                      "InvocationID": "old"}
        after = before | {"ActiveState": "active", "MainPID": "123", "InvocationID": "new"}
        self.host.unit.side_effect = [before, before, before | {"WorkingDirectory": str(self.root)}, after]
        self.backend.state["reset"] = {"verified": True}
        self.backend.context["request"]["budgets"] = {"total_seconds": 120}
        self.backend.config["java"] = {"path": "/usr/bin/java"}
        self.backend.manifest = {"wz_path": str(self.root / "wz"), "working_directory": str(self.root),
                                 "server_jar": {"path": str(self.root / "Server.jar")}}
        self.backend.validate_process = MagicMock()
        self.backend.wait_for_server_ready = MagicMock(return_value=True)
        with patch.object(runtime.pwd, "getpwnam", return_value=user), patch.object(runtime.os, "chown"):
            self.backend.start_server()
        dropin = Path(self.backend.state["dropin"]).read_text()
        self.assertEqual(Path(self.backend.state["dropin"]).name, "zz-maplebench-trial.conf")
        self.assertGreater(Path(self.backend.state["dropin"]).name, "seed.conf")
        self.assertIn('Environment="MAPLEBENCH_ENABLED=false"', dropin)
        self.assertNotIn("MAPLEBENCH_ENABLED=true", dropin)
        self.assertIn("WorkingDirectory=" + str(self.root) + "\nExecStart=\nExecStart=", dropin)
        self.assertNotIn('WorkingDirectory="', dropin)
        self.assertEqual(self.backend.state["native_environment"]["MAPLEBENCH_ENABLED"], "false")
        self.assertTrue(set(runtime.ENV_NAMES) <= set(self.backend.state["native_environment"]))
        self.assertEqual(before["Environment"], "MAPLEBENCH_ENABLED=true")
        if shutil.which("systemd-analyze"):
            # Ask the actual parser to read the generated directives, without
            # loading a unit into the service manager or starting any process.
            unit = self.root / "maplebench-parser-check.service"
            unit.write_text(dropin)
            parsed = subprocess.run(["systemd-analyze", "--man=no", "verify", str(unit)],
                                    capture_output=True, timeout=20)
            self.assertEqual(parsed.returncode, 0, parsed.stderr.decode())
            unit.write_text(dropin.replace("WorkingDirectory=" + str(self.root),
                                           'WorkingDirectory="' + str(self.root) + '"'))
            rejected = subprocess.run(["systemd-analyze", "--man=no", "verify", str(unit)],
                                      capture_output=True, timeout=20)
            self.assertNotEqual(rejected.returncode, 0)

    def test_working_directory_is_a_literal_scalar_not_an_exec_argument(self):
        directory = str(self.root / "directory with spaces")
        self.assertEqual(runtime.systemd_working_directory(directory), directory)
        for suffix in (' ', '\\bad', '"bad', '\tbad'):
            with self.subTest(suffix=suffix), self.assertRaises(runtime.RuntimeErrorCode):
                runtime.systemd_working_directory(str(self.root) + suffix)

    def test_running_trial_rejects_enabled_legacy_bot_adapter(self):
        self.backend.config["java"] = {"path": "/usr/bin/java"}
        self.backend.manifest = {"wz_path": str(self.root / "wz"), "working_directory": str(self.root),
                                 "server_jar": {"path": str(self.root / "Server.jar")}}
        self.backend.state.update(service_user="synthetic", native_environment={"MAPLEBENCH_ENABLED": "false"})
        argv = ["/usr/bin/java", "-Xmx1536m", "-XX:ActiveProcessorCount=2", "-Dwz-path=" + str(self.root / "wz"),
                "-jar", str(self.root / "Server.jar")]
        values = {"status": b"Uid:\t1234\t1234\t1234\t1234\n", "cmdline": ("\0".join(argv) + "\0").encode(),
                  "environ": b"MAPLEBENCH_ENABLED=false\0"}
        self.host.proc.side_effect = lambda pid, name: values[name]
        unit = {"User": "synthetic", "MainPID": "123", "WorkingDirectory": str(self.root)}
        with patch.object(runtime.pwd, "getpwnam", return_value=MagicMock(pw_uid=1234)):
            self.backend.validate_process(unit)
            for bad in (b"MAPLEBENCH_ENABLED=true\0", b""):
                values["environ"] = bad
                with self.assertRaisesRegex(runtime.RuntimeErrorCode, "legacy_bot_adapter_must_be_disabled"):
                    self.backend.validate_process(unit)


class SafeRuntimeErrorTests(unittest.TestCase):
    def test_online_snapshot_race_keeps_safe_specific_error_code(self):
        host=runtime.Host(); host.remaining=MagicMock(return_value=5)
        config={'command':['/usr/bin/mysql'],'database':'synthetic','character_id':1,'account_id':2}
        with patch.object(runtime,'collect',side_effect=ValueError('account_still_online')):
            with self.assertRaisesRegex(runtime.RuntimeErrorCode,'^account_still_online$'):
                host.snapshot(config,'a'*32)
        self.assertIn('account_still_online',runtime.RUNTIME_ERROR_CODES)

    def test_admin_only_preserves_exact_reviewed_error_envelopes(self):
        host=runtime.Host(); host.remaining=MagicMock(return_value=5)
        cases=[({'ok':False,'error':code},code) for code in
               ('recorder_not_ready','client_busy_or_not_ready','docker_executable_changed','guard_lock_descriptor_mismatch')]
        cases += [({'ok':False,'error':'private_code_looks_safe'},'admin_operation_failed'),
                  ({'ok':False,'error':'/private/password'},'admin_operation_failed'),
                  ({'ok':False,'error':['recorder_not_ready']},'admin_operation_failed'),
                  ({'ok':False,'error':'recorder_not_ready','detail':'private-marker'},'admin_operation_failed')]
        for envelope,expected in cases:
            connection=MagicMock(); connection.recv.return_value=runtime.encoded(envelope)
            manager=MagicMock(); manager.__enter__.return_value=connection
            with self.subTest(expected=expected), patch.object(runtime.socket,'socket',return_value=manager), \
                 patch.object(Path,'lstat',return_value=MagicMock(st_mode=stat.S_IFSOCK|0o600)):
                with self.assertRaisesRegex(runtime.RuntimeErrorCode,'^'+expected+'$'):
                    host.admin('/unused/admin.sock',{'op':'status'})

    def test_cli_preserves_vetted_freezer_codes_but_never_arbitrary_exception_text(self):
        for error,expected in ((runtime.FreezeError('inventory_timeout'),'inventory_timeout'),
                               (runtime.FreezeError('runtime_manifest_drift'),'runtime_manifest_drift'),
                               (runtime.DockerBindingError('docker_executable_changed'),'docker_executable_changed'),
                               (runtime.FreezeError('/private/password'),'runtime_operation_failed'),
                               (runtime.RuntimeErrorCode('private_looks_safe'),'runtime_operation_failed'),
                               (ValueError('/private/password'),'runtime_operation_failed')):
            output=io.StringIO()
            source=MagicMock(); source.buffer=io.BytesIO(runtime.encoded({'operation':'status','context':{},'timeout_seconds':5}))
            with self.subTest(error=type(error).__name__), patch.object(runtime.os,'geteuid',return_value=0), \
                 patch.object(runtime.sys,'platform','linux'), patch.object(runtime.sys,'stdin',source), \
                 patch.object(runtime,'read_private_json',return_value={}), \
                 patch.object(runtime,'CosmicRuntime') as backend, contextlib.redirect_stdout(output):
                backend.return_value.perform.side_effect=error
                self.assertEqual(runtime.main(['--config','/unused/private.json']),1)
            self.assertEqual(json.loads(output.getvalue()),{'error':expected})
            self.assertNotIn('/private/password',output.getvalue())


if __name__ == "__main__":
    unittest.main()
