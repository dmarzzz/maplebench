"""Synthetic runtime inventories; no actual Docker, game files, or runtime mutations."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from full_client_freeze import (FreezeError, Inventory, build_manifest, inspect_image,
                                main, read_private_json, verify_manifest, write_manifest)


IMAGE = "sha256:" + "a" * 64


class RuntimeFreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.working = self.root / "runtime"
        self.scripts = self.root / "scripts"
        self.wz = self.root / "wz"
        for directory in (self.working, self.scripts, self.wz):
            directory.mkdir(mode=0o700)
        (self.working / "scripts").symlink_to(self.scripts, target_is_directory=True)
        (self.root / "wz-alias").symlink_to(self.wz, target_is_directory=True)
        self.inputs = {
            "server_jar": self.root / "Server.jar", "client_js": self.root / "client.js",
            "client_wasm": self.root / "client.wasm", "config": self.working / "config.yaml",
            "script": self.scripts / "map.js", "wz": self.wz / "map.bin"}
        for name, path in self.inputs.items():
            path.write_bytes(("synthetic-" + name).encode())
        self.inputs["config"].write_bytes(b"private-marker: synthetic-only")
        self.config = {"working_directory": str(self.working), "wz_path": str(self.root / "wz-alias"),
                       **{key: str(self.inputs[key]) for key in ("server_jar", "client_js", "client_wasm")},
                       "docker_image": "synthetic-existing:tag", "docker_command": [sys.executable]}
        self.inspect_patch = patch("full_client_freeze.inspect_image", return_value=IMAGE)
        self.inspect = self.inspect_patch.start()
        self.addCleanup(self.inspect_patch.stop)

    def manifest(self):
        return build_manifest(self.config)

    def test_complete_current_bytes_are_deterministic_and_roots_resolve_explicitly(self):
        manifest = self.manifest()
        self.assertEqual(manifest, self.manifest())
        self.assertEqual(manifest["working_directory"], str(self.working))
        self.assertEqual(manifest["wz_path"], str(self.wz))
        self.assertEqual(manifest["inventory_roots"], sorted([str(self.scripts), str(self.wz)]))
        self.assertEqual(manifest["docker_image_id"], IMAGE)
        self.assertEqual(manifest["extra_files"], [])
        self.assertEqual({item["path"] for item in manifest["files"]},
                         {str(self.inputs[key]) for key in ("config", "script", "wz")})
        for reference in [*manifest["files"], *(manifest[key] for key in ("server_jar", "client_js", "client_wasm"))]:
            self.assertEqual(reference["sha256"], hashlib.sha256(Path(reference["path"]).read_bytes()).hexdigest())
        self.assertNotIn("private-marker", json.dumps(manifest))
        self.assertIs(verify_manifest(manifest, docker_command=[sys.executable]), manifest)

    def test_explicit_web_dependencies_are_sorted_hashed_and_verified(self):
        extra_paths = [self.root / name for name in ("waiting.html", "serve.py", "controller.js", "index.html")]
        for path in extra_paths:
            path.write_bytes(("synthetic " + path.name).encode())
        self.config["extra_files"] = [str(path) for path in extra_paths]
        manifest = self.manifest()
        self.assertEqual(manifest["extra_files"], [{"path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(extra_paths)])
        self.assertIs(verify_manifest(manifest, docker_command=[sys.executable]), manifest)
        for path in extra_paths:
            with self.subTest(file=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b" changed")
                with self.assertRaisesRegex(FreezeError, "runtime_manifest_drift"):
                    verify_manifest(manifest, docker_command=[sys.executable])
                path.write_bytes(original)
        extra_paths[0].unlink()
        with self.assertRaises(FreezeError):
            verify_manifest(manifest, docker_command=[sys.executable])

    def test_extra_files_reject_invalid_paths_duplicates_and_oversized_lists(self):
        alias = self.root / "script-alias.py"
        alias.symlink_to(self.inputs["script"])
        for values in (str(self.inputs["script"]), ["relative.py"], [str(self.scripts)],
                       [str(alias), str(self.inputs["script"])], [str(alias)] * 7):
            with self.subTest(values=values), self.assertRaises(FreezeError):
                build_manifest(self.config | {"extra_files": values, "limits": {"max_files": 6}})
        self.config["extra_files"] = [str(alias)]
        self.assertEqual(self.manifest()["extra_files"][0]["path"], str(self.inputs["script"]))

    def test_extra_dependencies_share_global_inventory_budgets(self):
        extra = self.root / "wrapper.py"
        extra.write_bytes(b"synthetic wrapper")
        self.config["extra_files"] = [str(extra)]
        for limits, code in (({"max_files": 6}, "inventory_file_limit"),
                             ({"max_total_bytes": sum(path.stat().st_size for path in self.inputs.values())},
                              "inventory_byte_limit")):
            with self.subTest(limits=limits), self.assertRaisesRegex(FreezeError, code):
                build_manifest(self.config | {"limits": limits})
        # A named dependency also inside a scanned tree is one physical path in
        # the budget, while retaining an explicit role pin in extra_files.
        self.config["extra_files"] = [str(self.inputs["script"])]
        manifest = build_manifest(self.config | {"limits": {"max_files": 6}})
        self.assertEqual(manifest["extra_files"], [next(item for item in manifest["files"]
                                                     if item["path"] == str(self.inputs["script"]))])

    def test_extra_file_change_after_hash_is_detected_before_manifest_returns(self):
        extra = self.root / "wrapper.py"
        extra.write_bytes(b"synthetic wrapper")
        self.config["extra_files"] = [str(extra)]
        original = Inventory.hash_path
        def change_after_hash(inventory, path):
            reference = original(inventory, path)
            if path == extra:
                path.write_bytes(b"changed wrapper")
            return reference
        with patch.object(Inventory, "hash_path", new=change_after_hash):
            with self.assertRaisesRegex(FreezeError, "inventory_file_changed"):
                self.manifest()

    def test_extra_manifest_refs_cannot_be_duplicated_or_reordered(self):
        self.config["extra_files"] = [str(self.inputs["client_js"]), str(self.inputs["script"])]
        manifest = self.manifest()
        for change in (lambda value: value["extra_files"].append(value["extra_files"][0]),
                       lambda value: value["extra_files"].reverse(),
                       lambda value: value.pop("extra_files")):
            bad = copy.deepcopy(manifest)
            change(bad)
            with self.assertRaises(FreezeError):
                verify_manifest(bad, docker_command=[sys.executable])

    def test_any_config_script_wz_or_build_edit_is_drift(self):
        manifest = self.manifest()
        for name, path in self.inputs.items():
            with self.subTest(name=name):
                original = path.read_bytes()
                path.write_bytes(original + b"-changed")
                with self.assertRaisesRegex(FreezeError, "runtime_manifest_drift"):
                    verify_manifest(manifest, docker_command=[sys.executable])
                path.write_bytes(original)

    def test_new_and_deleted_inventory_files_are_drift(self):
        manifest = self.manifest()
        extra = self.scripts / "new.js"
        extra.write_bytes(b"new synthetic source")
        with self.assertRaisesRegex(FreezeError, "runtime_manifest_drift"):
            verify_manifest(manifest, docker_command=[sys.executable])
        extra.unlink()
        self.inputs["wz"].unlink()
        with self.assertRaisesRegex(FreezeError, "runtime_manifest_drift"):
            verify_manifest(manifest, docker_command=[sys.executable])

    def test_root_alias_retargeting_is_detected(self):
        manifest = self.manifest()
        changed = self.root / "changed-scripts"
        changed.mkdir(mode=0o700)
        (changed / "map.js").write_bytes(self.inputs["script"].read_bytes())
        (self.working / "scripts").unlink()
        (self.working / "scripts").symlink_to(changed, target_is_directory=True)
        with self.assertRaisesRegex(FreezeError, "runtime_manifest_drift"):
            verify_manifest(manifest, docker_command=[sys.executable])

    def test_all_descendant_symlinks_are_rejected_without_following_them(self):
        for target in (self.inputs["config"], self.wz):
            with self.subTest(target=target.name):
                link = self.scripts / "unsupported-link"
                link.symlink_to(target, target_is_directory=target.is_dir())
                with self.assertRaisesRegex(FreezeError, "inventory_symlink_descendant"):
                    self.manifest()
                link.unlink()

    def test_fifo_cannot_block_inventory(self):
        os.mkfifo(self.wz / "fifo", mode=0o600)
        with self.assertRaisesRegex(FreezeError, "inventory_non_regular_file"):
            self.manifest()

    def test_file_and_byte_limits_are_enforced_before_unbounded_hashing(self):
        for limits, reason in (({"max_files": 3}, "inventory_file_limit"),
                               ({"max_total_bytes": 1}, "inventory_byte_limit")):
            with self.subTest(limits=limits), self.assertRaisesRegex(FreezeError, reason):
                build_manifest(self.config | {"limits": limits})
        for limits in ({"max_files": True}, {"max_total_bytes": -1}, {"timeout_seconds": 301}, {"unknown": 1}):
            with self.subTest(limits=limits), self.assertRaises(FreezeError):
                build_manifest(self.config | {"limits": limits})

    def test_time_budget_stops_inventory(self):
        with patch("full_client_freeze.time.monotonic", side_effect=[0, 121]):
            with self.assertRaisesRegex(FreezeError, "inventory_timeout"):
                self.manifest()

    def test_same_size_edit_with_restored_mtime_is_detected_through_ctime(self):
        target = self.inputs["server_jar"]
        before = target.stat()
        original = os.read
        changed = False
        def mutate_after_read(descriptor, count):
            nonlocal changed
            raw = original(descriptor, count)
            if raw and not changed and os.fstat(descriptor).st_ino == before.st_ino:
                changed = True
                target.write_bytes(b"x" * before.st_size)
                os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
            return raw
        with patch("full_client_freeze.os.read", side_effect=mutate_after_read):
            with self.assertRaisesRegex(FreezeError, "inventory_file_changed"):
                self.manifest()
        self.assertTrue(changed)

    def test_addition_during_tree_scan_cannot_escape_inventory(self):
        original = Inventory.hash_fd
        added = False
        def add_after_hash(inventory, descriptor, path, expected=None):
            nonlocal added
            result = original(inventory, descriptor, path, expected)
            if path == self.inputs["script"] and not added:
                added = True
                (self.scripts / "late.js").write_bytes(b"late source")
            return result
        with patch.object(Inventory, "hash_fd", new=add_after_hash):
            with self.assertRaisesRegex(FreezeError, "inventory_directory_changed"):
                self.manifest()

    def test_image_change_during_inventory_and_later_drift_are_rejected(self):
        self.inspect.side_effect = [IMAGE, "sha256:" + "b" * 64]
        with self.assertRaisesRegex(FreezeError, "docker_image_changed"):
            self.manifest()
        self.inspect.side_effect = None
        manifest = self.manifest()
        self.inspect.return_value = "sha256:" + "b" * 64
        with self.assertRaisesRegex(FreezeError, "runtime_manifest_drift"):
            verify_manifest(manifest, docker_command=[sys.executable])

    def test_manifest_writer_is_private_durable_and_never_overwrites(self):
        manifest = self.manifest()
        output = self.root / "runtime-manifest.json"
        digest = write_manifest(output, manifest)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), digest)
        self.assertEqual(read_private_json(output), manifest)
        previous = output.read_bytes()
        with self.assertRaises(FileExistsError):
            write_manifest(output, manifest)
        self.assertEqual(output.read_bytes(), previous)
        public = self.root / "not-private"
        public.mkdir(mode=0o755)
        with self.assertRaisesRegex(FreezeError, "private_output_parent_required"):
            write_manifest(public / "manifest.json", manifest)

    def test_malformed_manifest_fields_do_not_weaken_inventory(self):
        manifest = self.manifest()
        for change in (lambda value: value.update(schema_version=True),
                       lambda value: value.update(inventory_roots=[]),
                       lambda value: value["files"].append(copy.deepcopy(value["files"][0])),
                       lambda value: value["server_jar"].update(sha256="missing"),
                       lambda value: value.update(unrecognized=True)):
            bad = copy.deepcopy(manifest)
            change(bad)
            with self.assertRaises(FreezeError):
                verify_manifest(bad, docker_command=[sys.executable])

    def test_cli_prints_only_safe_result_and_verifies_then_detects_drift(self):
        config = self.root / "config.json"
        config.write_text(json.dumps(self.config))
        config.chmod(0o600)
        output = self.root / "manifest.json"
        calls = (["--config", str(config), "create", "--output", str(output)],
                 ["--config", str(config), "verify", "--manifest", str(output)])
        for arguments in calls:
            text = io.StringIO()
            with contextlib.redirect_stdout(text):
                status = main(arguments)
            self.assertEqual(status, 0)
            self.assertNotIn(str(self.root), text.getvalue())
            self.assertNotIn("private-marker", text.getvalue())
        self.inputs["client_js"].write_bytes(b"different build")
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            self.assertEqual(main(calls[1]), 1)
        self.assertFalse(json.loads(text.getvalue())["verified"])

    def test_cli_configuration_switch_cannot_keep_verifying_old_inputs(self):
        manifest = self.manifest()
        output = self.root / "manifest.json"
        write_manifest(output, manifest)
        alternate = self.root / "alternate-client.js"
        alternate.write_bytes(self.inputs["client_js"].read_bytes())
        config = self.root / "config.json"
        config.write_text(json.dumps(self.config | {"client_js": str(alternate)}))
        config.chmod(0o600)
        response = io.StringIO()
        with contextlib.redirect_stdout(response):
            self.assertEqual(main(["--config", str(config), "verify", "--manifest", str(output)]), 1)
        self.assertEqual(json.loads(response.getvalue())["code"], "runtime_manifest_drift")

    def test_cli_extra_dependency_switch_is_drift_even_with_identical_bytes(self):
        original, alternate = self.root / "first.py", self.root / "second.py"
        for path in (original, alternate):
            path.write_bytes(b"same synthetic wrapper")
        self.config["extra_files"] = [str(original)]
        output = self.root / "manifest.json"
        write_manifest(output, self.manifest())
        config = self.root / "config.json"
        config.write_text(json.dumps(self.config | {"extra_files": [str(alternate)]}))
        config.chmod(0o600)
        response = io.StringIO()
        with contextlib.redirect_stdout(response):
            self.assertEqual(main(["--config", str(config), "verify", "--manifest", str(output)]), 1)
        self.assertEqual(json.loads(response.getvalue())["code"], "runtime_manifest_drift")


class LocalImageInspectionTests(unittest.TestCase):
    def test_fixed_local_command_ignores_remote_docker_environment_and_never_pulls(self):
        process = SimpleNamespace(returncode=0, stdout=(IMAGE + "\n").encode())
        with patch.dict(os.environ, {"DOCKER_HOST": "tcp://remote.invalid:2375", "DOCKER_CONTEXT": "remote"}), \
                patch("full_client_freeze.subprocess.run", return_value=process) as run:
            self.assertEqual(inspect_image([sys.executable], "synthetic:tag", 5), IMAGE)
        args, options = run.call_args
        self.assertEqual(args[0], [sys.executable, "--host", "unix:///var/run/docker.sock", "image", "inspect",
                                   "--format", "{{.Id}}", "--", "synthetic:tag"])
        self.assertEqual(options["timeout"], 5)
        self.assertEqual(options["env"], {"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        self.assertNotIn("pull", args[0])

    def test_failed_or_noncanonical_image_inspection_never_becomes_a_digest(self):
        for response in (SimpleNamespace(returncode=1, stdout=b"private-marker"),
                         SimpleNamespace(returncode=0, stdout=b"private-marker"),
                         SimpleNamespace(returncode=0, stdout=b"sha256:short")):
            with self.subTest(response=response.returncode), patch("full_client_freeze.subprocess.run", return_value=response):
                with self.assertRaises(FreezeError) as failure:
                    inspect_image([sys.executable], "synthetic:tag", 5)
                self.assertNotIn("private-marker", str(failure.exception))
        with patch("full_client_freeze.subprocess.run", side_effect=subprocess.TimeoutExpired("private-marker", 5)):
            with self.assertRaisesRegex(FreezeError, "docker_image_inspection_failed"):
                inspect_image([sys.executable], "synthetic:tag", 5)

    def test_command_prefixes_and_option_like_image_refs_are_rejected(self):
        for command, ref in ((["docker"], "synthetic:tag"),
                             ([sys.executable, "--host", "tcp://remote.invalid"], "synthetic:tag"),
                             ([sys.executable], "--pull")):
            with self.subTest(command=command), self.assertRaises(FreezeError):
                inspect_image(command, ref, 5)


if __name__ == "__main__":
    unittest.main()
