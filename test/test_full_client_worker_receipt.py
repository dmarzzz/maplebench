"""Synthetic first-idle handoffs with real files/locks; no services or API calls."""
import contextlib
import fcntl
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import maplebench


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux lifecycle receipt')
class WorkerReceiptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name).resolve()
        self.directory = self.work/'receipts'
        self.directory.mkdir(mode=0o700)
        self.queue = maplebench.Queue(self.work/'maplebench/artifacts/batches')
        self.addCleanup(self.queue.db.close)
        self.paths = [self.work/'private/maplebench-world.lock',
                      self.work/'maplebench/artifacts/.cosmic-queue.lock']
        for path in self.paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(mode=0o600)
        self.invocation = 'a'*32
        self.cosmic = {'pid': 123, 'start_ticks': '456', 'invocation_id': 'b'*32}
        self.receipt = self.directory/(self.invocation+'.json')
        self.environment = patch.dict(os.environ, {
            'MAPLEBENCH_LIFECYCLE_RECEIPT_DIR': str(self.directory),
            'INVOCATION_ID': self.invocation})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def assert_locks_released(self):
        for path in self.paths:
            with path.open('r+b') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @contextlib.contextmanager
    def held_locks(self):
        with contextlib.ExitStack() as stack:
            yield {name: stack.enter_context(maplebench.worker_existing_lock(path))
                   for name, path in zip(('world', 'queue'), self.paths)}

    def test_first_idle_receipt_precedes_sleep_and_records_actual_lock_inodes(self):
        def first_sleep(_):
            value = json.loads(self.receipt.read_text())
            self.assertEqual(value['worker']['pid'], os.getpid())
            self.assertEqual(value['worker']['invocation_id'], self.invocation)
            self.assertEqual(value['cosmic_before'], self.cosmic)
            self.assertEqual(value['cosmic_after'], self.cosmic)
            self.assertEqual(value['worker_source_sha256'], maplebench.digest(Path(maplebench.__file__)))
            self.assertEqual((value['queue_pending'], value['trials_claimed']), (0, 0))
            self.assertEqual(self.receipt.stat().st_mode & 0o777, 0o600)
            for name, path in zip(('world', 'queue'), self.paths):
                self.assertEqual(value['locks'][name], {'path': str(path),
                    'device': path.stat().st_dev, 'inode': path.stat().st_ino})
                with path.open('r+b') as stream, self.assertRaises(BlockingIOError):
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            raise StopIteration('synthetic end of watch')
        with patch.object(maplebench, 'restore_world') as restore, \
                patch.object(maplebench, 'worker_cosmic_identity', return_value=self.cosmic), \
                patch.object(maplebench.time, 'sleep', side_effect=first_sleep):
            with self.assertRaises(StopIteration):
                maplebench.worker(self.queue, None, self.work, watch=True)
            restore.assert_called_once_with()
        self.assert_locks_released()

    def test_receipt_cannot_overwrite_an_existing_invocation(self):
        with self.held_locks() as descriptors:
            maplebench.worker_first_idle_receipt(self.queue, self.work, self.cosmic, self.cosmic,
                                                 lock_fds=descriptors)
            original = self.receipt.read_bytes()
            with self.assertRaises(FileExistsError):
                maplebench.worker_first_idle_receipt(self.queue, self.work, self.cosmic, self.cosmic,
                                                     lock_fds=descriptors)
        self.assertEqual(self.receipt.read_bytes(), original)
        self.assertEqual([p.name for p in self.directory.iterdir()], [self.receipt.name])

    def test_changed_cosmic_during_restore_has_no_eligible_receipt(self):
        changed = self.cosmic | {'pid': 321}
        with patch.object(maplebench, 'restore_world'), \
                patch.object(maplebench, 'worker_cosmic_identity', side_effect=[self.cosmic, changed]):
            with self.assertRaisesRegex(RuntimeError, 'worker_receipt_cosmic_changed'):
                maplebench.worker(self.queue, None, self.work)
        self.assertFalse(self.receipt.exists())
        self.assert_locks_released()

    def test_disabled_hook_preserves_legacy_idle_behavior(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(maplebench, 'restore_world') as restore, \
                patch.object(maplebench, 'worker_cosmic_identity') as probe:
            maplebench.worker(self.queue, None, self.work)
            restore.assert_called_once_with()
            probe.assert_not_called()
        self.assertFalse(self.receipt.exists())
        self.assert_locks_released()

    def insert_trial(self, status):
        with self.queue.db:
            self.queue.db.execute('INSERT INTO batches VALUES(?,?,?,?)', ('b', '{}', 0, 'completed'))
            self.queue.db.execute('INSERT INTO trials(id,batch_id,ordinal,model,scenario,repetition,status) '
                                 'VALUES(?,?,?,?,?,?,?)', ('t', 'b', 0, 'synthetic', 'synthetic', 1, status))

    def test_pending_queue_and_nonprivate_directory_refuse_receipt(self):
        self.insert_trial('queued')
        with self.held_locks() as descriptors:
            with self.assertRaisesRegex(RuntimeError, 'worker_receipt_queue_not_idle'):
                maplebench.worker_first_idle_receipt(self.queue, self.work, self.cosmic, self.cosmic,
                                                     lock_fds=descriptors)
            self.directory.chmod(0o755)
            with self.assertRaisesRegex(RuntimeError, 'worker_receipt_private_directory_required'):
                maplebench.worker_first_idle_receipt(self.queue, self.work, self.cosmic, self.cosmic,
                                                     lock_fds=descriptors)
        self.assertFalse(self.receipt.exists())

    def test_lock_replaced_during_restore_never_emits_a_receipt(self):
        for path in self.paths:
            with self.subTest(lock=path.name):
                original = path.stat().st_ino
                def replace_lock():
                    replacement = path.with_name(path.name + '.replacement')
                    replacement.touch(mode=0o600)
                    replacement.replace(path)
                    self.assertNotEqual(path.stat().st_ino, original)
                with patch.object(maplebench, 'restore_world', side_effect=replace_lock), \
                        patch.object(maplebench, 'worker_cosmic_identity', return_value=self.cosmic):
                    with self.assertRaisesRegex(RuntimeError, 'worker_receipt_existing_lock_required'):
                        maplebench.worker(self.queue, None, self.work)
                self.assertFalse(self.receipt.exists())
                self.assertEqual(list(self.directory.iterdir()), [])
                self.assert_locks_released()

    def test_unlocked_or_duplicate_descriptors_cannot_attest_ownership(self):
        with contextlib.ExitStack() as stack:
            descriptors = {name: stack.enter_context(path.open('r+b')).fileno()
                           for name, path in zip(('world', 'queue'), self.paths)}
            with self.assertRaisesRegex(RuntimeError, 'worker_receipt_existing_lock_required'):
                maplebench.worker_first_idle_receipt(self.queue, self.work, self.cosmic, self.cosmic,
                                                     lock_fds=descriptors)
        with self.held_locks() as descriptors:
            with self.assertRaisesRegex(RuntimeError, 'worker_receipt_existing_lock_required'):
                maplebench.worker_first_idle_receipt(self.queue, self.work, self.cosmic, self.cosmic,
                    lock_fds={'world': descriptors['world'], 'queue': descriptors['world']})
        self.assertFalse(self.receipt.exists())
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_lock_change_after_receipt_write_removes_unpublished_temporary(self):
        original_fsync = os.fsync
        def replace_after_write(descriptor):
            original_fsync(descriptor)
            replacement = self.work/'replacement.lock'
            replacement.touch(mode=0o600)
            replacement.replace(self.paths[0])
        with self.held_locks() as descriptors, \
                patch.object(maplebench.os, 'fsync', side_effect=replace_after_write):
            with self.assertRaisesRegex(RuntimeError, 'worker_receipt_existing_lock_required'):
                maplebench.worker_first_idle_receipt(self.queue, self.work, self.cosmic, self.cosmic,
                                                     lock_fds=descriptors)
        self.assertFalse(self.receipt.exists())
        self.assertEqual(list(self.directory.iterdir()), [])
        self.assert_locks_released()

    def test_no_first_idle_receipt_after_claiming_any_trial(self):
        self.insert_trial('completed')
        item = {'id': 't', 'batch_id': 'b', 'attempt': 1, 'attempt_dir': 't/attempt-1'}
        with patch.object(self.queue, 'claim', side_effect=[item, None]), \
                patch.object(self.queue, 'recover'), patch.object(self.queue, 'publish'), \
                patch.object(self.queue, 'finish'), patch.object(self.queue, 'config', return_value={}), \
                patch.object(maplebench, 'recover_renders'), patch.object(maplebench, 'restore_world'), \
                patch.object(maplebench, 'worker_cosmic_identity') as probe, \
                patch.object(maplebench.subprocess, 'Popen', side_effect=RuntimeError('synthetic child refusal')), \
                contextlib.redirect_stdout(io.StringIO()):
            maplebench.worker(self.queue, None, self.work)
            probe.assert_not_called()
        self.assertFalse(self.receipt.exists())

    def test_missing_or_symlink_lock_is_never_created_or_followed(self):
        self.paths[0].unlink()
        with patch.object(self.queue, 'recover') as recover:
            with self.assertRaises(FileNotFoundError):
                maplebench.worker(self.queue, None, self.work)
            recover.assert_not_called()
        self.assertFalse(self.paths[0].exists())
        target = self.work/'unrelated.lock'; target.touch()
        self.paths[0].symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, 'worker_existing_lock_required'):
            maplebench.worker(self.queue, None, self.work)
        self.assertTrue(self.paths[0].is_symlink())


if __name__ == '__main__':
    unittest.main()
