"""No Docker processes: exercise the binding against inert local file identities."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from full_client_docker import (DockerBindingError, bound_invocation, configured_command,
                                freeze_binding, validate_binding)
from docker_binding_fixture import local_binding


class DockerBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.binding = local_binding(self, self.temp.name)

    def test_empty_config_and_fixed_local_endpoint_ignore_all_inherited_routing(self):
        hostile = {"MAPLEBENCH_DOCKER_COMMAND": "private-launcher --remote",
                   "DOCKER_HOST": "tcp://private-host:2375", "DOCKER_CONTEXT": "private-context",
                   "DOCKER_CONFIG": "/private/config", "HOME": "/private/home",
                   "PATH": "/private/bin", "XDG_RUNTIME_DIR": "/private/runtime",
                   "OPENAI_API_KEY": "private-key"}
        with patch.dict(os.environ, hostile), bound_invocation(self.binding) as (prefix, env):
            config = Path(prefix[2])
            self.assertEqual(prefix, [self.binding["executable"]["path"], "--config", str(config),
                                      "--host", "unix://" + self.binding["socket_path"]])
            self.assertEqual((config / "config.json").read_text(), "{}\n")
            self.assertEqual(config.stat().st_mode & 0o777, 0o700)
            self.assertEqual(env, {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": str(config), "DOCKER_CONFIG": str(config)})
            self.assertFalse(any(value in str((prefix, env)) for value in hostile.values()))
        self.assertFalse(config.exists())

    def test_binary_change_symlink_socket_and_missing_pin_fail_closed(self):
        Path(self.binding["executable"]["path"]).write_bytes(b"changed bytes\n")
        with self.assertRaisesRegex(DockerBindingError, "docker_executable_changed"):
            validate_binding(self.binding)
        with self.assertRaisesRegex(DockerBindingError, "invalid_docker_binding"):
            validate_binding(None)
        bad = copy.deepcopy(self.binding)
        alias = Path(self.temp.name).resolve() / "socket-alias"
        alias.symlink_to(self.binding["socket_path"])
        bad["socket_path"] = str(alias)
        # Remove the unrelated executable mismatch to test the endpoint directly.
        bad["executable"] = freeze_binding([self.binding["executable"]["path"]], self.binding["socket_path"])["executable"]
        with self.assertRaisesRegex(DockerBindingError, "invalid_docker_socket"):
            validate_binding(bad)

    def test_only_exact_vetted_sudo_prefix_is_representable(self):
        binding = copy.deepcopy(self.binding)
        binding["launcher"] = {"path": "/usr/bin/sudo", "sha256": "a" * 64}
        self.assertEqual(configured_command(binding), ["/usr/bin/sudo", "-n", binding["executable"]["path"]])
        for path in ("/private/launcher", "/bin/sudo"):
            binding["launcher"]["path"] = path
            with self.assertRaisesRegex(DockerBindingError, "invalid_docker_command"):
                configured_command(binding)
        for command in (["docker"], ["sudo", "-n", "/usr/bin/docker"],
                        ["/usr/bin/sudo", "-E", "/usr/bin/docker"],
                        ["/usr/bin/sudo", "-n", "env", "/usr/bin/docker"]):
            with self.subTest(command=command), self.assertRaises(DockerBindingError):
                freeze_binding(command, self.binding["socket_path"])


if __name__ == "__main__":
    unittest.main()
