"""Idle-worker restoration must not disrupt an already restored normal world."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import maplebench


class WorkerRestoreTest(unittest.TestCase):
    override = '/run/systemd/system/maplebench-cosmic.service.d/zz-maplebench-batch.conf'

    def restore(self, *, override_exists=False, **changes):
        state = {'LoadState': 'loaded', 'ActiveState': 'active', 'SubState': 'running',
                 'MainPID': '987', 'DropInPaths': '', 'NeedDaemonReload': 'no'}
        state.update(changes)
        raw = '\n'.join(f'{key}={value}' for key, value in state.items()) + '\n'
        with mock.patch.object(maplebench.subprocess, 'run', return_value=mock.Mock(stdout=raw)), \
                mock.patch.object(maplebench.os.path, 'lexists', return_value=override_exists):
            maplebench.restore_world()

    def test_empty_queue_startup_preserves_running_normal_world(self):
        with mock.patch.object(maplebench, 'sudo') as mutate:
            self.restore()
            mutate.assert_not_called()

    def test_real_batch_cleanup_still_restores_normal_configuration(self):
        with mock.patch.object(maplebench, 'sudo') as mutate:
            self.restore(override_exists=True)
            self.assertEqual(mutate.call_args_list, [
                mock.call('rm', '-f', self.override),
                mock.call('systemctl', 'daemon-reload'),
                mock.call('systemctl', 'restart', 'maplebench-cosmic')])

    def test_loaded_removed_batch_override_still_requires_cleanup(self):
        with mock.patch.object(maplebench, 'sudo') as mutate:
            self.restore(DropInPaths=self.override, NeedDaemonReload='yes')
            self.assertEqual(mutate.call_args_list[-1],
                             mock.call('systemctl', 'restart', 'maplebench-cosmic'))

    def test_stopped_normal_world_is_started_without_restart_or_reload(self):
        for active in ('inactive', 'failed'):
            with self.subTest(active=active), mock.patch.object(maplebench, 'sudo') as mutate:
                self.restore(ActiveState=active, SubState='dead', MainPID='0')
                mutate.assert_called_once_with('systemctl', 'start', 'maplebench-cosmic')

    def test_ambiguous_or_unrelated_service_state_is_not_mutated(self):
        for change in ({'ActiveState': 'activating', 'SubState': 'start'},
                       {'SubState': 'exited', 'MainPID': '0'},
                       {'NeedDaemonReload': 'yes'}, {'LoadState': 'not-found'},
                       {'MainPID': 'unknown'}, {'MainPID': '-1'}):
            with self.subTest(change=change), mock.patch.object(maplebench, 'sudo') as mutate:
                with self.assertRaises(RuntimeError):
                    self.restore(**change)
                mutate.assert_not_called()

    def test_failed_status_probe_never_mutates_world(self):
        with mock.patch.object(maplebench, 'sudo') as mutate, \
                mock.patch.object(maplebench.subprocess, 'run',
                                  side_effect=subprocess.TimeoutExpired('systemctl', 10)):
            with self.assertRaises(subprocess.TimeoutExpired):
                maplebench.restore_world()
            mutate.assert_not_called()

    def test_unrelated_override_is_preserved(self):
        with mock.patch.object(maplebench, 'sudo') as mutate:
            self.restore(DropInPaths='/run/systemd/system/maplebench-cosmic.service.d/seed.conf')
            mutate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
