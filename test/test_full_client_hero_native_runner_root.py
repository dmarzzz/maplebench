"""Linux-root process-tree proof for the native Hero ownership contract."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


PROBE_SOURCE = textwrap.dedent('''
    import fcntl, hashlib, os
    from pathlib import Path
    import sys, time

    source=Path('__SOURCE_ROOT__');sys.path.insert(0,str(source))
    import full_client_hero_native_runner as runner
    from full_client_runtime import CosmicRuntime, Host, RuntimeErrorCode
    script=Path(__file__).resolve()
    def ref():
        return {'path':str(script),'sha256':hashlib.sha256(script.read_bytes()).hexdigest()}
    def runtime(owner,guard,paths):
        value=CosmicRuntime.__new__(CosmicRuntime);value.host=Host()
        value.host.deadline=time.monotonic()+20
        value.config={'orchestrator':ref(),'world_lock':paths[0],'queue_lock':paths[1]}
        value.context={'lock_owner_pid':owner,'guard_pid':guard,
            'guard_parent_pid':owner,'lock_paths':{'world':paths[0],'queue':paths[1]}}
        return value
    mode=sys.argv[1]
    if mode=='root':
        paths=sys.argv[2:4];fds=[]
        for path in paths:
            fd=os.open(path,os.O_RDWR);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);fds.append(fd)
        empty={'path':str(script),'sha256':'0'*64}
        runner.launch_guard(script,empty,empty,fds)
        raise SystemExit(0)
    if mode=='_adapter_guard':
        owner=int(sys.argv[6]);fds=[int(value) for value in sys.argv[7].split(',')]
        paths=[os.readlink('/proc/self/fd/%d' % fd) for fd in fds]
        # The old two-level arrangement must fail the real production check.
        failed=False
        try:CosmicRuntime.ownership(runtime(owner,os.getpid(),paths))
        except RuntimeErrorCode as error:failed=str(error)=='guard_ancestry_mismatch'
        if not failed:raise SystemExit(20)
        empty={'path':str(script),'sha256':'0'*64}
        runner.launch_owned(script,empty,empty,owner,fds)
        sys.stdout.write(runner._message('adapter_guard_completed'))
        raise SystemExit(0)
    if mode=='_owned_runtime':
        owner,guard=int(sys.argv[6]),int(sys.argv[7])
        fds=[int(value) for value in sys.argv[8].split(',')]
        paths=[os.readlink('/proc/self/fd/%d' % fd) for fd in fds]
        runner.validate_owned_ancestry(owner,guard)
        CosmicRuntime.ownership(runtime(owner,guard,paths))
        sys.stdout.write(runner._message('owned_runtime_completed'))
        raise SystemExit(0)
    raise SystemExit(30)
''').lstrip('\n')
compile(PROBE_SOURCE, 'hero-native-ancestry-probe', 'exec')


@unittest.skipUnless(sys.platform.startswith('linux') and os.geteuid() == 0,
                     'Linux root required for real /proc and flock ownership proof')
class HeroNativeRunnerRootTests(unittest.TestCase):
    def test_production_launchers_create_required_root_guard_worker_tree(self):
        source = Path(__file__).resolve().parents[1] / 'scripts'
        with tempfile.TemporaryDirectory(prefix='hero-native-ancestry-') as raw:
            root = Path(raw)
            script = root / 'ancestry.py'
            program = PROBE_SOURCE.replace("'__SOURCE_ROOT__'", repr(str(source)))
            compile(program, str(script), 'exec')
            script.write_text(program)
            script.chmod(0o600)
            locks = [root / 'world.lock', root / 'queue.lock']
            for path in locks:
                path.write_bytes(b'')
                path.chmod(0o600)
            result = subprocess.run([sys.executable, str(script), 'root',
                *(str(path) for path in locks)], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C',
                     'PYTHONDONTWRITEBYTECODE': '1'}, check=False)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))


if __name__ == '__main__':
    unittest.main()
