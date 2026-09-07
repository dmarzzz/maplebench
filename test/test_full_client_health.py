import copy
from contextlib import contextmanager, ExitStack
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import struct
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from full_client_health import assess, duration_seconds, validate_config
import full_client_health as health


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


class NormalWorkerHealthTests(unittest.TestCase):
    def setUp(self):
        self.config = {'schema_version': 2, 'mode': 'normal-worker',
            'services': {role: 'test-' + role for role in ('world', 'worker', 'web', 'cosmic')},
            'world_lock': '/private/world.lock', 'queue_lock': '/private/queue.lock',
            'queue_database': '/private/queue.sqlite3', 'admin_socket': '/private/admin/control.sock',
            'game_ports': [8484, 7575], 'base_url': 'http://127.0.0.1:8840',
            'processes': {role: {'executable': '/usr/bin/example', 'argv': ['example', role],
                'uid': 1000, 'working_directory': '/runtime/' + role} for role in ('worker', 'web', 'cosmic')}}
        self.processes = {role: {'pid': pid, 'start_ticks': 123, 'uids': [1000] * 4}
                          for role, pid in (('worker', 42), ('web', 50), ('cosmic', 60))}
        self.services = {role: {'ActiveState': 'active', 'SubState': 'running', 'MainPID': str(value['pid']),
            'Result': 'success', 'LoadState': 'loaded', 'NeedDaemonReload': 'no', 'InvocationID': 'a' * 32}
            for role, value in self.processes.items()}
        self.services['world'] = {'ActiveState': 'inactive', 'SubState': 'dead', 'MainPID': '0'}
        self.locks = {'world': [42], 'queue': [42]}
        self.ports = {'8484': True, '7575': True, '8840': True}
        self.relay = {'run': {'status': 'idle', 'workerActive': False, 'leaseReleasePending': False},
            'fresh': False, 'rendererConnected': True, 'browserReleasePending': False, 'quarantinedRuns': []}
        self.admin = {'bridge': copy.deepcopy(self.relay), 'observation': None,
            'session': {'state': 'waiting', 'fresh': True, 'clientSeenMs': 10,
                        'artifactsSettled': True, 'captureState': 'idle'}}

    def result(self, **changes):
        values = dict(config=self.config, services=self.services, processes=self.processes,
            locks=self.locks, ports=self.ports, available_mib=8192, queue_count=0,
            relay=self.relay, admin=self.admin)
        values.update(changes)
        return health.assess_normal(**values)

    def test_mode_is_explicit_and_durable_trial_health_is_not_inferred(self):
        validate_config(self.config)
        result = self.result()
        self.assertTrue(result['ready'])
        self.assertEqual(result['mode'], 'normal-worker')
        self.assertEqual(result['durable_trial_readiness'], 'unsupported_without_trusted_runner_account_and_ownership_context')
        for change in ({'mode': 'durable-trial'}, {'mode': 'leased-preview'}, {'schema_version': 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_config(self.config | change)
        legacy = HealthTest(); legacy.setUp()
        validate_config(legacy.config | {'mode': 'leased-preview'})
        with self.assertRaises(ValueError):
            validate_config(legacy.config | {'mode': 'normal-worker'})

    def test_normal_bindings_require_working_directory_and_owned_port_roles(self):
        for change in (lambda c:c['processes']['worker'].pop('working_directory'),
                       lambda c:c['processes']['web'].update(uid=True),
                       lambda c:c['processes']['web'].update(argv='example'),
                       lambda c:c.update(game_ports=[8840]),
                       lambda c:c.update(base_url='http://localhost:8840'),
                       lambda c:c.update(queue_database='../queue.sqlite3')):
            config=copy.deepcopy(self.config); change(config)
            with self.assertRaises(ValueError): validate_config(config)

    def test_healthy_waiting_is_distinct_from_stale_rendering(self):
        result = self.result()
        self.assertTrue(result['ready'])
        self.assertEqual(result['browser_state'], 'healthy_waiting')
        self.assertFalse(result['renderer_active'])
        self.admin['session']['state'] = 'connected'
        self.assertFalse(self.result()['ready'])
        self.admin['bridge']['fresh'] = True
        self.admin['observation'] = {'ready': True, 'ageMs': 10, 'renderAgeMs': 10}
        self.assertEqual(self.result()['browser_state'], 'healthy_rendering')
        self.assertFalse(self.result(status_age_ms=1490)['ready'])
        self.admin['session']['state'] = 'waiting'
        self.assertFalse(self.result(status_age_ms=2990)['ready'])
        self.admin['session']['state'] = 'transitioning'
        self.assertFalse(self.result()['ready'])

    def test_terminal_controller_cannot_hide_worker_lease_release_or_unsettled_capture(self):
        for section, key, value in (('run','workerActive',True), ('run','leaseReleasePending',True),
            ('bridge','browserReleasePending',True), ('bridge','quarantinedRuns',['a'*32]),
            ('session','artifactsSettled',False), ('session','captureState','saving')):
            with self.subTest(section=section, key=key):
                admin=copy.deepcopy(self.admin)
                target=admin['bridge']['run'] if section=='run' else admin[section]
                target[key]=value
                self.assertIn('controller_quiescence_unproven',self.result(admin=admin)['checks'])
        for key in ('workerActive','leaseReleasePending'):
            admin=copy.deepcopy(self.admin); admin['bridge']['run'].pop(key)
            self.assertFalse(self.result(admin=admin)['ready'])
        self.assertIn('private_quiescence_unavailable',self.result(admin=None)['checks'])
        relay=copy.deepcopy(self.relay); relay['run']['workerActive']=0
        self.assertIn('web_admin_state_mismatch',self.result(relay=relay)['checks'])

    def test_normal_service_lock_and_queue_checks_do_not_reuse_legacy_lease_readiness(self):
        self.services['world'].update(ActiveState='active',MainPID='42',RuntimeMaxUSec='infinity')
        self.assertIn('legacy_world_not_stopped',self.result()['checks'])
        self.services['world'].update(ActiveState='inactive',MainPID='0')
        self.services['world'].update(ActiveState='failed',Result='timeout')
        self.assertTrue(self.result()['ready'])  # Expired legacy lease, with no live helper PID.
        self.services['world'].update(ActiveState='inactive')
        for role in ('worker','web','cosmic'):
            changed=copy.deepcopy(self.services); changed[role]['MainPID']='999'
            self.assertIn(role+'_identity_unverified',self.result(services=changed)['checks'])
        for locks in ({'world':[42],'queue':[]}, {'world':[42],'queue':[60]}, {'world':[42,99],'queue':[42]}):
            self.assertIn('worker_lock_ownership_mismatch',self.result(locks=locks)['checks'])
        for count in (1,True,None):
            self.assertFalse(self.result(queue_count=count)['queue_idle'])
            self.assertFalse(self.result(queue_count=count)['ready'])
        self.assertIn('native_listener_unowned',self.result(ports=self.ports|{'8484':False})['checks'])
        self.assertIn('web_listener_unowned',self.result(ports=self.ports|{'8840':False})['checks'])

    @contextmanager
    def mocked_probes(self):
        ids={'world':(0,1,7),'queue':(0,1,8)}
        table=b'1: FLOCK ADVISORY WRITE 42 00:01:7 0 EOF\n2: FLOCK ADVISORY WRITE 42 00:01:8 0 EOF\n'
        with ExitStack() as stack:
            stack.enter_context(patch.object(health.sys,'platform','linux'))
            unit=stack.enter_context(patch.object(health,'unit_states',return_value=self.services))
            stack.enter_context(patch.object(health,'process_identity',side_effect=lambda service,binding:
                next(value for value in self.processes.values() if str(value['pid'])==service['MainPID'])))
            identity=stack.enter_context(patch.object(health,'lock_identities',return_value=ids))
            stack.enter_context(patch.object(health,'read_limited',side_effect=lambda path,limit:
                b'MemAvailable: 8388608 kB\n' if str(path).endswith('meminfo') else table))
            stack.enter_context(patch.object(health,'owned_listeners',side_effect=lambda pid:{8484,7575} if pid==60 else {8840}))
            queue=stack.enter_context(patch.object(health,'queue_pending',return_value=0))
            stack.enter_context(patch.object(health,'public_status',return_value=self.relay))
            stack.enter_context(patch.object(health,'admin_status',return_value=self.admin))
            started=stack.enter_context(patch.object(health,'process_start',return_value=123))
            yield unit,identity,queue,started

    def test_probe_window_rechecks_unit_invocation_lock_inode_pid_start_and_queue(self):
        with self.mocked_probes():
            self.assertTrue(health.check(self.config)['ready'])
        for change in ('unit','lock','pid','queue'):
            with self.subTest(change=change), self.mocked_probes() as probes:
                unit,identity,queue,started=probes
                if change=='unit':
                    different=copy.deepcopy(self.services); different['cosmic']['InvocationID']='b'*32
                    unit.side_effect=[self.services,different]
                elif change=='lock': identity.side_effect=[{'world':(0,1,7),'queue':(0,1,8)}, {'world':(0,1,9),'queue':(0,1,8)}]
                elif change=='pid': started.return_value=124
                else: queue.side_effect=[0,1]
                with self.assertRaises(health.HealthError): health.check(self.config)


class NormalHealthProbeTests(unittest.TestCase):
    def test_process_binding_checks_exact_argv_executable_uid_cwd_and_start_ticks(self):
        binding={'argv':['worker','--watch'],'executable':'/usr/bin/python3.12','uid':1000,'working_directory':'/runtime'}
        def read(path,limit):
            return b'worker\0--watch\0' if str(path).endswith('cmdline') else b'Uid:\t1000\t1000\t1000\t1000\n'
        def link(path): return '/usr/bin/python3.12' if str(path).endswith('exe') else '/runtime'
        with patch.object(health,'read_limited',side_effect=read), patch.object(health.os,'readlink',side_effect=link), \
             patch.object(health,'process_start',return_value=123) as started:
            self.assertEqual(health.process_identity({'MainPID':'42'},binding)['start_ticks'],123)
            for key,value in [('argv',['worker']),('executable','/wrong'),('uid',0),('working_directory','/wrong')]:
                with self.subTest(key=key), self.assertRaisesRegex(health.HealthError,'process_binding_mismatch'):
                    health.process_identity({'MainPID':'42'},binding|{key:value})
            started.side_effect=[123,124]
            with self.assertRaisesRegex(health.HealthError,'process_identity_changed'):
                health.process_identity({'MainPID':'42'},binding)

    def test_native_listener_requires_a_listening_socket_inode_owned_by_exact_pid(self):
        entries=MagicMock(); entries.__enter__.return_value=iter([SimpleNamespace(path='/proc/60/fd/1')])
        table=(b'header\n0: 00000000:2124 00000000:0000 0A 0 0 0 1000 0 123\n'
               b'1: 00000000:270F 00000000:0000 0A 0 0 0 1000 0 999\n'
               b'2: 00000000:1D97 00000000:0000 01 0 0 0 1000 0 123\n')
        with patch.object(health.os,'scandir',return_value=entries), patch.object(health.os,'readlink',return_value='socket:[123]'), \
             patch.object(health,'read_limited',return_value=table):
            self.assertEqual(health.owned_listeners(60),{8484})
        entries=MagicMock(); entries.__enter__.return_value=iter([SimpleNamespace(path='one'),SimpleNamespace(path='two')])
        with patch.object(health,'MAX_FDS',1), patch.object(health.os,'scandir',return_value=entries), \
             patch.object(health.os,'readlink',return_value='socket:[123]'):
            with self.assertRaisesRegex(health.HealthError,'process_fd_limit'): health.owned_listeners(60)

    def test_kernel_locks_are_inode_bound_exclusive_and_not_waiter_claims(self):
        ids={'world':(0,1,7),'queue':(0,1,8)}
        raw=b'1: FLOCK ADVISORY WRITE 42 00:01:7 0 EOF\n1: -> FLOCK ADVISORY WRITE 99 00:01:7 0 EOF\n2: FLOCK ADVISORY WRITE 42 00:01:8 0 EOF\n'
        self.assertEqual(health.kernel_lock_owners(raw,ids),{'world':[42],'queue':[42]})
        self.assertEqual(health.kernel_lock_owners(raw,{'world':(0,1,9),'queue':(0,1,8)})['world'],[])
        with self.assertRaisesRegex(health.HealthError,'unexpected_world_lock_kind'):
            health.kernel_lock_owners(raw.replace(b'FLOCK ADVISORY WRITE',b'POSIX ADVISORY WRITE'),ids)

    def test_queue_probe_uses_read_only_connection_and_never_creates_missing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'queue.sqlite3'
            with sqlite3.connect(path) as database:
                database.execute('CREATE TABLE trials(status TEXT)')
                database.executemany('INSERT INTO trials VALUES (?)',[(s,) for s in ('completed','queued','running','rendering')])
            real_connect=sqlite3.connect
            connections=[]; statements=[]
            def connect(database_uri,**options):
                self.assertTrue(database_uri.endswith('?mode=ro')); self.assertIs(options['uri'],True)
                connection=real_connect(database_uri,**options); connection.set_trace_callback(statements.append)
                connections.append(connection); return connection
            with patch.object(health.sqlite3,'connect',side_effect=connect):
                self.assertEqual(health.queue_pending(str(path),time.monotonic()+3),3)
            self.assertIn('PRAGMA query_only=ON',statements)
            self.assertFalse(any(command.startswith(('INSERT','UPDATE','DELETE')) for command in statements))
            with self.assertRaises(sqlite3.ProgrammingError): connections[0].execute('SELECT 1')
            missing=Path(directory)/'missing.sqlite3'
            with self.assertRaises(FileNotFoundError): health.queue_pending(str(missing),time.monotonic()+3)
            self.assertFalse(missing.exists())

    def test_admin_status_binds_peer_pid_uid_and_only_sends_read_only_status(self):
        path=Path('/private/admin/control.sock')
        def info(value):
            return SimpleNamespace(st_dev=1,st_ino=7,st_uid=1000,
                st_mode=(stat.S_IFSOCK|0o600) if value==path else (stat.S_IFDIR|0o700))
        client=MagicMock(); client.__enter__.return_value=client
        client.getsockopt.return_value=struct.pack('3i',50,1000,1000)
        client.recv.return_value=b'{"ok":true,"result":{"bridge":{},"session":{}}}\n'
        with patch.object(Path,'lstat',info), patch.object(Path,'resolve',lambda value,strict=False:value), \
             patch.object(health.socket,'SO_PEERCRED',17,create=True), patch.object(health.socket,'socket',return_value=client):
            value=health.admin_status(path,{'pid':50,'uids':[1000]*4},time.monotonic()+3)
            self.assertEqual(value,{'bridge':{},'session':{}})
            client.sendall.assert_called_once_with(b'{"op":"status"}\n')
            for peer in ((51,1000,1000),(50,0,0)):
                client.getsockopt.return_value=struct.pack('3i',*peer)
                with self.assertRaisesRegex(health.HealthError,'admin_peer_mismatch'):
                    health.admin_status(path,{'pid':50,'uids':[1000]*4},time.monotonic()+3)

    def test_probe_reads_are_bounded_and_failures_never_echo_private_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input'; path.write_bytes(b'x'*20)
            with self.assertRaisesRegex(health.HealthError,'probe_read_limit'): health.read_limited(path,10)
            path.write_text('{}')
            output=io.StringIO()
            with patch.object(health,'check',side_effect=sqlite3.OperationalError('private credential')), patch('sys.stdout',output):
                self.assertEqual(health.main(['--config',str(path)]),1)
            self.assertNotIn('private credential',output.getvalue())
            self.assertEqual(json.loads(output.getvalue())['checks'],['health_probe_failed'])


if __name__ == '__main__':
    unittest.main()
