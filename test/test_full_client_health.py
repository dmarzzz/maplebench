import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from full_client_health import assess, duration_seconds, validate_config


class HealthTest(unittest.TestCase):
    def setUp(self):
        self.config = {'schema_version': 1, 'services': {k: 'test-' + k for k in ['world', 'web', 'cosmic', 'worker']},
                       'world_lock': '/private/world.lock', 'queue_lock': '/private/queue.lock',
                       'ports': [8484, 7575, 8840], 'base_url': 'http://127.0.0.1:8840'}
        self.services = {name: {'ActiveState': 'active', 'SubState': 'running', 'MainPID': '50'} for name in ['world', 'web', 'cosmic']}
        self.services['world'].update(MainPID='42', ActiveEnterTimestampMonotonic='100000000', RuntimeMaxUSec='1h 30min')
        self.services['worker'] = {'ActiveState': 'inactive'}
        self.locks = [{'path': '/private/world.lock', 'pid': 42}, {'path': '/private/queue.lock', 'pid': 42}]
        self.ports = {str(p): True for p in self.config['ports']}
        self.relay = {'fresh': True, 'run': {'status': 'completed'}}

    def result(self, **kw):
        args = dict(config=self.config, services=self.services, locks=self.locks, ports=self.ports,
                    available_mib=4096, now_boot_seconds=200, relay=self.relay)
        args.update(kw)
        return assess(**args)

    def test_ready_requires_actual_world_client_and_locks(self):
        self.assertTrue(self.result()['ready'])
        self.services['world'].update(ActiveState='failed', Result='timeout')
        result = self.result()
        self.assertFalse(result['ready'])
        self.assertIn('world_inactive', result['checks'])
        self.assertEqual(result['services']['world']['Result'], 'timeout')

    def test_missing_or_wrong_lock_owner_refuses_ready(self):
        self.assertFalse(self.result(locks=self.locks[:1])['ready'])
        changed = copy.deepcopy(self.locks)
        changed[1]['pid'] = 99
        self.assertFalse(self.result(locks=changed)['ready'])

    def test_active_exited_unit_is_not_a_live_server(self):
        self.services['cosmic'].update(SubState='exited', MainPID='0')
        self.assertIn('cosmic_inactive', self.result()['checks'])

    def test_lease_expiry_and_memory_cannot_be_hidden_by_http(self):
        result = self.result(now_boot_seconds=5550, available_mib=100)
        self.assertEqual(result['lease_remaining_seconds'], 0)
        self.assertIn('lease_insufficient', result['checks'])
        self.assertIn('memory_insufficient', result['checks'])

    def test_stale_client_and_busy_controller_are_separate(self):
        self.assertTrue(self.result(relay=None)['infrastructure_ready'])
        self.assertFalse(self.result(relay=None)['client_ready'])
        self.assertIn('controller_busy', self.result(relay={'fresh': True, 'run': {'status': 'running'}})['checks'])

    def test_unknown_and_unlimited_lease_refused(self):
        self.assertIsNone(duration_seconds('infinity'))
        self.assertIsNone(duration_seconds('1h unsafe'))
        self.assertEqual(duration_seconds('1min 3s 4ms'), 63.004)

    def test_completion_waits_for_recording_and_evidence(self):
        run = {'id': 'attempt-1', 'status': 'completed', 'recordingStatus': 'pending', 'evidenceStatus': 'saved'}
        self.assertIn('run_artifacts_incomplete', self.result(relay={'fresh': True, 'run': run})['checks'])
        run['recordingStatus'] = 'saved'
        self.assertTrue(self.result(relay={'fresh': True, 'run': run})['ready'])
        run['evidenceStatus'] = 'failed'
        self.assertFalse(self.result(relay={'fresh': True, 'run': run})['ready'])
        run['status'] = 'unknown'
        self.assertFalse(self.result(relay={'fresh': True, 'run': run})['controller_idle'])

    def test_only_loopback_config_accepted(self):
        validate_config(self.config)
        for url in ['http://example.com:80', 'http://127.0.0.1:80@evil.test', 'http://localhost:80/path', 'http://localhost:80?x=y']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_config(self.config | {'base_url': url})


if __name__ == '__main__':
    unittest.main()
