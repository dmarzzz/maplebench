"""Offline one-shot Hero runner tests; no locks, services, DB, or gameplay."""
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import full_client_hero_native_runner as runner
from full_client_hero_native_evidence import VERIFIER_PROTOCOL


class HeroNativeRunnerTests(unittest.TestCase):
    def config(self):
        return {'baseline': {'sha256': 'a' * 64},
                'runtime_manifest': {'sha256': 'b' * 64},
                'scenario': {'sha256': 'c' * 64}}

    def request(self):
        return {'schema_version': 1, 'protocol': VERIFIER_PROTOCOL,
            'attempt_id': 'd' * 32, 'timeout_seconds': 600,
            'config_sha256': 'e' * 64, 'baseline_sha256': 'a' * 64,
            'runtime_manifest_sha256': 'b' * 64,
            'scenario_sha256': 'c' * 64}

    def test_request_is_exactly_bound_to_config_and_600_seconds(self):
        value = self.request()
        self.assertIs(runner.request_value(value,
            {'path': '/private/config.json', 'sha256': 'e' * 64},
            self.config()), value)
        for changed in (value | {'timeout_seconds': 601},
                        value | {'baseline_sha256': 'f' * 64},
                        value | {'extra': True}):
            with self.subTest(changed=changed), \
                    self.assertRaises(runner.RunnerError):
                runner.request_value(changed,
                    {'path': '/private/config.json', 'sha256': 'e' * 64},
                    self.config())

    def test_guard_launch_passes_only_two_inherited_descriptors(self):
        process = mock.Mock()
        process.wait.return_value = 0
        with mock.patch.object(runner.subprocess, 'Popen', return_value=process) as popen:
            runner.launch_guard(Path('/private/runner.py'),
                {'path': '/private/config.json', 'sha256': 'a' * 64},
                {'path': '/private/request.json', 'sha256': 'b' * 64}, [7, 8])
        argv = popen.call_args.args[0]
        self.assertEqual(argv[2], '_adapter_guard')
        self.assertEqual(argv[-2:], [str(runner.os.getpid()), '7,8'])
        self.assertEqual(popen.call_args.kwargs['pass_fds'], (7, 8))
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        process.wait.assert_called_once_with(timeout=610)

    def test_timeout_kills_guard_process_group_and_never_reissues(self):
        process = mock.Mock(pid=123)
        process.wait.side_effect = [runner.subprocess.TimeoutExpired('guard', 600), 0]
        with mock.patch.object(runner.subprocess, 'Popen', return_value=process) as popen, \
                mock.patch.object(runner.os, 'killpg') as kill, \
                self.assertRaisesRegex(runner.RunnerError,
                                       'hero_native_guard_timeout'):
            runner.launch_guard(Path('/private/runner.py'),
                {'path': '/private/config.json', 'sha256': 'a' * 64},
                {'path': '/private/request.json', 'sha256': 'b' * 64}, [7, 8])
        self.assertEqual(popen.call_count, 1)
        kill.assert_called_once_with(123, runner.signal.SIGKILL)

    def test_initial_state_is_private_unqualified_and_clean_false(self):
        reference = {'path': '/private/native-input.json', 'sha256': 'a' * 64}
        value = runner._initial_state('b' * 32, reference)
        self.assertFalse(value['clean'])
        self.assertFalse(value['publication_eligible'])
        self.assertEqual(value['maintenance_protocol'], VERIFIER_PROTOCOL)
        self.assertEqual(value['native_input_reference'], reference)
        self.assertEqual(value['intents'], [])


if __name__ == '__main__':
    unittest.main()
