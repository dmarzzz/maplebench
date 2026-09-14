"""Linux admission tests using real bounded parent/exec children and flock FDs.

Only temporary fixtures are changed. No world/backend/service/API is invoked.
The parent fixture is a real protected Python entry script so argv proof is not
stubbed to fit a unittest launcher. Outer test-job resource caps apply to it.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import full_client_operation_gate as gate
import full_client_operation_join as join

OPERATION = "1" * 32
ATTEMPT = "2" * 32


def write_json(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    path.write_bytes(raw)
    path.chmod(0o600)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


CHILD = r'''
import json, os, sys, time
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_bytes())
sys.path.insert(0, data['scripts'])
import full_client_operation_gate as gate
import full_client_operation_join as join
fd = data['fd']
if data.get('remap') is not None:
    os.dup2(fd, data['remap'])
    os.close(fd)
    fd = data['remap']
duplicate = os.dup(fd) if data.get('duplicate') else None
if data.get('wait_parent_death'):
    deadline = time.monotonic() + 5
    while os.getppid() == data['parent_pid'] and time.monotonic() < deadline:
        time.sleep(.01)
result = {'ok': False}
if data.get('entry_error'):
    original_create = gate.create_json
    def uncertain_entry(parent, name, value, uid):
        ref = original_create(parent, name, value, uid)
        if name.endswith('.entered.json'):
            raise OSError('synthetic lost entry response')
        return ref
    gate.create_json = uncertain_entry
try:
    with join.joined(data['attempt_root'], data['pin'], data['envelope'], fd,
                     data['binding'], owner_uid=os.geteuid()) as admitted:
        result = {'ok': True, 'admission': admitted, 'cloexec': not os.get_inheritable(fd)}
        if data.get('body_error'):
            raise OSError('synthetic caller body error')
except Exception as error:
    result = {'ok': False, 'code': str(error), 'type': type(error).__name__}
finally:
    if duplicate is not None:
        os.close(duplicate)
try:
    os.fstat(fd)
    result['fd_closed'] = False
except OSError:
    result['fd_closed'] = True
print(json.dumps(result), flush=True)
'''


PARENT = r'''
import copy, hashlib, json, os, subprocess, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_bytes())
sys.path.insert(0, data['scripts'])
import full_client_operation_gate as gate
import full_client_operation_join as join
root = Path(data['root'])
def ref(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
def save(path, value):
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(',', ':')).encode() + b'\n')
    path.chmod(0o600)
    return ref(path)
launch = {'executable': ref(Path(sys.executable).resolve()), 'script': ref(Path(__file__).resolve()),
          'argv': [str(Path(sys.executable).resolve()), str(Path(__file__).resolve()), sys.argv[1]]}
mode = data['mode']
if mode == 'launch_prefix':
    launch['argv'].append('--undeclared')
if mode == 'launch_flags':
    launch['argv'].insert(1, '-u')
if mode == 'launch_hash':
    launch['script']['sha256'] = '0' * 64
control = gate.OperationGate(data['attempt_root'], data['pin'], owner_uid=os.geteuid())
results = []
try:
    with control.locked() as lease:
        claim = lease.begin(data['operation_id'], data['kind'], data['authority'])
        dispatch_dir = Path(data['dispatch_directory'])
        if mode == 'dispatch_directory':
            dispatch_dir = root / 'wrong-dispatch'
            dispatch_dir.mkdir(mode=0o700)
        with join.prepare_join(lease, dispatch_dir, data['binding'], parent_launch=launch) as dispatch:
            exported_fd = dispatch['pass_fds'][0]
            assert len(dispatch['pass_fds']) == 1
            envelope = dispatch['envelope']
            value = json.loads(Path(envelope['path']).read_bytes())
            if mode.startswith('parent_'):
                key = mode[len('parent_'):]
                if key == 'pid': value['parent'][key] += 1
                elif key == 'uid': value['parent'][key] += 1
                elif key == 'boot_id': value['parent'][key] = '0' * 8 + '-0000-0000-0000-' + '0' * 12
                elif key == 'start_ticks': value['parent'][key] = str(int(value['parent'][key]) + 1)
                elif key == 'argv': value['parent_launch']['argv'].append('--not-actually-running')
                else: raise AssertionError('unknown mutation')
                envelope = save(Path(envelope['path']), value)
            if mode == 'envelope_hash':
                value['created_at_ms'] += 1
                save(Path(envelope['path']), value)  # Retain the original expected hash.
            if mode == 'envelope_path':
                envelope = save(root / 'copied-envelope.json', value)
            if mode == 'resource_inode':
                path = Path(data['binding']['world_lock'])
                path.rename(root / 'original-world.lock')
                path.touch(mode=0o600)
            if mode == 'claim_hash':
                changed = json.loads(Path(claim['path']).read_bytes())
                changed['created_at_ms'] += 1
                save(Path(claim['path']), changed)
            if mode == 'adapter_hash':
                save(Path(data['binding']['adapter_config']['path']), {'changed_after_dispatch': True})
            if mode == 'claim_terminal':
                save(Path(claim['path']).parent / 'terminal.json', {'synthetic': True})
            if mode == 'dispatch_inode':
                dispatch_dir.rename(root / 'old-dispatch')
                dispatch_dir.mkdir(mode=0o700)
                envelope = save(dispatch_dir / Path(envelope['path']).name, value)
            def child(index, binding=None, **changes):
                payload = {'scripts': data['scripts'], 'attempt_root': data['attempt_root'], 'pin': data['pin'],
                           'envelope': envelope, 'fd': exported_fd,
                           'binding': binding if binding is not None else data['binding'],
                           'parent_pid': os.getpid()}
                payload.update(changes)
                path = root / ('child-' + str(index) + '.json')
                save(path, payload)
                return payload, path
            if mode == 'death':
                payload, path = child(0, wait_parent_death=True)
                output = os.open(root / 'orphan-result.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    proc = subprocess.Popen([str(Path(sys.executable).resolve()), data['child_script'], str(path)],
                         pass_fds=dispatch['pass_fds'], close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=output, stderr=subprocess.DEVNULL)
                finally:
                    os.close(output)
                print(json.dumps({'orphan': proc.pid, 'claim': claim}), flush=True)
                os._exit(0)
            calls = 2 if mode in ('replay', 'mismatch_then_valid', 'entry_error_replay') else 1
            for index in range(calls):
                expected = copy.deepcopy(data['binding'])
                if mode == 'mismatch_then_valid' and index == 0:
                    expected['attempt_id'] = '3' * 32
                payload, path = child(index, expected, duplicate=(mode == 'extra_fd'), body_error=(mode == 'body_error'),
                                      entry_error=(mode == 'entry_error_replay' and index == 0))
                inherited = dispatch['pass_fds']
                independent = None
                if mode == 'independent':
                    independent = os.open(data['pin']['path'], os.O_RDWR | os.O_NOFOLLOW)
                    payload.update(fd=independent, remap=exported_fd)
                    save(path, payload)
                    inherited = (independent,)
                try:
                    output = subprocess.run([str(Path(sys.executable).resolve()), data['child_script'], str(path)],
                         pass_fds=inherited, close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=True)
                finally:
                    if independent is not None: os.close(independent)
                result = json.loads(output.stdout)
                result['entry_present'] = (dispatch_dir / (data['binding']['action'] + '-' + data['binding']['attempt_id'] + '.entered.json')).exists()
                results.append(result)
            os.fstat(exported_fd)
            try:
                with gate.OperationGate(data['attempt_root'], data['pin'], owner_uid=os.geteuid()).locked():
                    parent_still_locked = False
            except gate.GateError as error:
                assert str(error) == 'operation_busy'
                parent_still_locked = True
        try:
            os.fstat(exported_fd)
            export_closed = False
        except OSError:
            export_closed = True
        if mode == 'replay':
            try:
                with join.prepare_join(lease, dispatch_dir, data['binding'], parent_launch=launch):
                    raise AssertionError('recreated entered dispatch')
            except gate.GateError as error:
                results.append({'ok': False, 'code': str(error)})
        summary = {'results': results, 'parent_still_locked': parent_still_locked, 'export_closed': export_closed,
                   'terminal_present': (Path(claim['path']).parent / 'terminal.json').exists(), 'claim': claim}
    print(json.dumps(summary), flush=True)
except gate.GateError as error:
    print(json.dumps({'prepare_error': str(error)}), flush=True)
'''


@unittest.skipUnless(sys.platform == "linux", "verified Linux /proc and flock protocol")
class OperationJoinTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.root.chmod(0o700)
        self.attempts = self.root / "attempts"
        self.attempts.mkdir(mode=0o700)
        self.pin = gate.initialize_registry(self.attempts, owner_uid=os.geteuid())
        self.authority = write_json(self.root / "authority.json", {"kind": "offline_operation_authority"})
        dispatch_base = self.root / ".operation-dispatch"
        dispatch_base.mkdir(mode=0o700)
        self.dispatch = dispatch_base / OPERATION
        self.dispatch.mkdir(mode=0o700)
        self.binding = {"action": "trial_run", "attempt_id": ATTEMPT,
                        "request": write_json(self.root / "request.json", {"model": "offline-fixture"}),
                        "adapter_config": write_json(self.root / "adapter.json", {"backend": "never_invoked"}),
                        "state_root": str(self.attempts), "world_lock": str(self.root / "world.lock"),
                        "queue_lock": str(self.root / "queue.lock"),
                        "plan": write_json(self.root / "plan.json", {"entries": [ATTEMPT]})}
        for name in ("world_lock", "queue_lock"):
            Path(self.binding[name]).touch(mode=0o600)
        self.parent_script, self.child_script = self.root / "parent.py", self.root / "child.py"
        for path, source in ((self.parent_script, PARENT), (self.child_script, CHILD)):
            path.write_text(source)
            path.chmod(0o600)

    def run_parent(self, mode, *, kind="finite_group"):
        payload = {"root": str(self.root), "attempt_root": str(self.attempts), "pin": self.pin,
                   "authority": self.authority, "binding": self.binding, "operation_id": OPERATION,
                   "kind": kind, "dispatch_directory": str(self.dispatch), "mode": mode,
                   "scripts": str(Path(join.__file__).parent), "child_script": str(self.child_script)}
        path = self.root / "parent-input.json"
        write_json(path, payload)
        result = subprocess.run([str(Path(sys.executable).resolve()), str(self.parent_script), str(path)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                close_fds=True, timeout=30, check=True)
        return json.loads(result.stdout)

    def assert_refusal(self, mode, code):
        result = self.run_parent(mode)
        self.assertNotIn("prepare_error", result, result)
        response = result["results"][0]
        self.assertFalse(response["ok"], result)
        self.assertEqual(response["code"], code, result)
        self.assertTrue(response["fd_closed"], result)
        self.assertFalse(response["entry_present"], result)
        self.assertTrue(result["parent_still_locked"], result)
        return result

    def test_real_parent_exec_inheritance_enters_once_and_retains_close_only_locks(self):
        result = self.run_parent("success")
        self.assertNotIn("prepare_error", result, result)
        child = result["results"][0]
        self.assertTrue(child["ok"], result)
        self.assertTrue(child["cloexec"] and child["fd_closed"] and child["entry_present"])
        self.assertTrue(result["parent_still_locked"] and result["export_closed"])
        self.assertFalse(result["terminal_present"])
        admitted = child["admission"]
        self.assertEqual(admitted["binding"], self.binding)
        self.assertEqual(admitted["claim"], result["claim"])
        entry_path = Path(admitted["entry"]["path"])
        self.assertEqual(hashlib.sha256(entry_path.read_bytes()).hexdigest(), admitted["entry"]["sha256"])
        entry = json.loads(entry_path.read_bytes())
        self.assertEqual(entry["envelope"], admitted["envelope"])
        self.assertNotEqual(entry["parent"]["pid"], entry["child"]["pid"])
        with gate.OperationGate(self.attempts, self.pin, owner_uid=os.geteuid()).locked() as lease:
            with self.assertRaisesRegex(gate.GateError, "pending_operation"):
                lease.ensure_available()

    def test_same_inode_independent_descriptor_is_refused_before_entry(self):
        self.assert_refusal("independent", "join_flock_proof_missing")

    def test_more_than_one_inherited_gate_description_is_refused(self):
        self.assert_refusal("extra_fd", "join_exactly_one_gate_fd_required")

    def test_binding_mismatch_does_not_consume_the_valid_dispatch(self):
        result = self.run_parent("mismatch_then_valid")
        first, second = result["results"]
        self.assertEqual(first["code"], "join_binding_mismatch", result)
        self.assertFalse(first["entry_present"], result)
        self.assertTrue(second["ok"] and second["entry_present"], result)

    def test_entry_and_dispatch_envelope_are_never_replayed_or_recreated(self):
        result = self.run_parent("replay")
        first, second, new_envelope = result["results"]
        self.assertTrue(first["ok"], result)
        self.assertEqual(second["code"], "join_dispatch_already_entered", result)
        self.assertEqual(new_envelope["code"], "join_dispatch_already_entered", result)
        self.assertFalse(result["terminal_present"])

    def test_uncertain_entry_receipt_never_authorizes_dispatch_replay(self):
        result = self.run_parent("entry_error_replay")
        first, second = result["results"]
        self.assertFalse(first["ok"], result)
        self.assertEqual(first["code"], "join_evidence_unavailable", result)
        self.assertTrue(first["entry_present"] and first["fd_closed"], result)
        self.assertEqual(second["code"], "join_dispatch_already_entered", result)
        self.assertTrue(result["parent_still_locked"])
        self.assertFalse(result["terminal_present"])

    def test_parent_death_before_entry_refuses_despite_inherited_lock(self):
        result = self.run_parent("death")
        self.assertIn("orphan", result)
        output = self.root / "orphan-result.json"
        deadline = time.monotonic() + 10
        child = None
        while time.monotonic() < deadline:
            try:
                child = json.loads(output.read_bytes())
                break
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(.02)
        self.assertIsNotNone(child, "bounded orphan fixture did not finish")
        self.assertFalse(child["ok"], child)
        self.assertEqual(child["code"], "join_parent_not_direct", child)
        self.assertTrue(child["fd_closed"])
        self.assertFalse(list(self.dispatch.glob("*.entered.json")))

    def test_changed_parent_pid_is_refused(self):
        self.assert_refusal("parent_pid", "join_parent_not_direct")

    def test_changed_parent_start_ticks_is_refused(self):
        self.assert_refusal("parent_start_ticks", "join_parent_changed")

    def test_changed_parent_boot_is_refused(self):
        self.assert_refusal("parent_boot_id", "join_parent_changed")

    def test_changed_parent_uid_is_refused(self):
        self.assert_refusal("parent_uid", "join_invalid_parent")

    def test_changed_parent_exact_argv_is_refused(self):
        self.assert_refusal("parent_argv", "join_parent_launch_changed")

    def test_launch_prefix_match_does_not_authorize_parent(self):
        result = self.run_parent("launch_prefix")
        self.assertEqual(result, {"prepare_error": "join_parent_launch_changed"})
        self.assertFalse(list(self.dispatch.iterdir()))

    def test_interpreter_flags_are_not_accepted_as_script_semantics(self):
        result = self.run_parent("launch_flags")
        self.assertEqual(result, {"prepare_error": "join_launch_source_mismatch"})

    def test_parent_source_hash_drift_is_refused(self):
        result = self.run_parent("launch_hash")
        self.assertEqual(result, {"prepare_error": "join_source_changed"})

    def test_envelope_content_hash_drift_is_refused(self):
        self.assert_refusal("envelope_hash", "reference_changed")

    def test_copied_envelope_path_cannot_authorize_another_entry_namespace(self):
        self.assert_refusal("envelope_path", "join_envelope_path_mismatch")

    def test_changed_dispatch_directory_inode_is_refused(self):
        self.assert_refusal("dispatch_inode", "join_dispatch_directory_changed")

    def test_parent_cannot_select_an_arbitrary_dispatch_directory(self):
        result = self.run_parent("dispatch_directory")
        self.assertEqual(result, {"prepare_error": "join_dispatch_directory_mismatch"})

    def test_changed_world_lock_inode_is_refused_without_acquiring_it(self):
        self.assert_refusal("resource_inode", "join_resource_changed")

    def test_changed_claim_hash_is_refused(self):
        self.assert_refusal("claim_hash", "reference_changed")

    def test_changed_actual_adapter_config_is_refused_before_entry(self):
        self.assert_refusal("adapter_hash", "reference_changed")

    def test_nonpending_parent_claim_is_refused(self):
        self.assert_refusal("claim_terminal", "join_claim_not_pending")

    def test_recovery_binding_requires_null_request_and_standalone_plan_is_null(self):
        self.binding.update(action="trial_recover", request=None, plan=None)
        result = self.run_parent("success", kind="standalone_trial")
        self.assertTrue(result["results"][0]["ok"], result)
        self.assertIsNone(result["results"][0]["admission"]["binding"]["request"])

    def test_recovery_cannot_smuggle_a_new_run_request(self):
        self.binding.update(action="trial_recover", plan=None)
        result = self.run_parent("success", kind="standalone_trial")
        self.assertEqual(result, {"prepare_error": "join_recovery_request_forbidden"})

    def test_caller_body_errors_keep_their_provenance_after_admission(self):
        result = self.run_parent("body_error")
        child = result["results"][0]
        self.assertEqual(child["code"], "synthetic caller body error", result)
        self.assertEqual(child["type"], "OSError", result)
        self.assertTrue(child["entry_present"] and child["fd_closed"] and result["parent_still_locked"])

    def test_fdinfo_requires_exact_kernel_exclusive_flock_identity(self):
        control = gate.OperationGate(self.attempts, self.pin, owner_uid=os.geteuid())
        with control.locked() as lease:
            device = f"{os.major(self.pin['device']):02x}:{os.minor(self.pin['device']):02x}:{self.pin['inode']}"
            good = f"lock: 1: FLOCK ADVISORY WRITE {os.getpid()} {device} 0 EOF\n".encode()
            variants = ((good.replace(b"FLOCK", b"POSIX"), "join_flock_proof_missing"),
                        (good.replace(b"FLOCK", b"OFDLCK"), "join_flock_proof_missing"),
                        (good.replace(b"WRITE", b"READ"), "join_flock_proof_missing"),
                        (good.replace(device.encode(), b"00:00:0"), "join_flock_owner_mismatch"),
                        (good + good, "join_flock_proof_missing"),
                        (good.replace(str(os.getpid()).encode(), b"999999999"), "join_flock_owner_mismatch"))
            for raw, code in variants:
                with self.subTest(raw=raw), mock.patch.object(join, "_kernel", return_value=raw):
                    with self.assertRaisesRegex(join.JoinError, code):
                        join._flock(os.getpid(), lease._fd, self.pin, os.getpid(), gate.Budget())


if __name__ == "__main__":
    unittest.main()
