"""Private, optional trial coordination for one ordinary full-client browser.

No HTTP admin methods, arbitrary evaluation, database operations, or native game
shortcuts are provided here. Navigation acknowledgment is not proof of logout;
the trusted trial backend must independently verify Cosmic's persisted state.
"""
import fcntl
import array
import json
import os
from pathlib import Path
import re
import socket
import socketserver
import stat
import threading
import time
import uuid

from full_client_bridge import ControlError


def validate_guard_descriptors(descriptors, requested_paths, configured_paths):
    if (len(descriptors)!=2 or not isinstance(requested_paths,dict)
            or set(requested_paths)!={'world','queue'} or not configured_paths
            or set(configured_paths)!={'world','queue'}):
        raise ControlError('trial_requires_two_configured_guard_locks')
    identities = set()
    for descriptor,role in zip(descriptors,('world','queue')):
        if not isinstance(requested_paths[role],str) or not isinstance(configured_paths[role],str):
            raise ControlError('invalid_guard_lock_path')
        expected = Path(configured_paths[role])
        requested = Path(requested_paths[role])
        if not expected.is_absolute() or requested!=expected:
            raise ControlError('guard_lock_path_mismatch')
        target = expected.lstat()
        actual = os.fstat(descriptor)
        identity = (actual.st_dev,actual.st_ino)
        if (not stat.S_ISREG(target.st_mode) or not stat.S_ISREG(actual.st_mode)
                or identity!=(target.st_dev,target.st_ino) or identity in identities):
            raise ControlError('guard_lock_descriptor_mismatch')
        identities.add(identity)
        # This is a Linux runtime contract: inspect the kernel's lock for this
        # received open-file description. Do not acquire or unlock world locks.
        info = Path(f'/proc/self/fdinfo/{descriptor}')
        if not info.is_file() or not re.search(r'\bFLOCK\s+ADVISORY\s+WRITE\b',info.read_text()):
            raise ControlError('guard_descriptor_is_not_exclusively_locked')


class SessionCoordinator:
    def __init__(self, bridge, lock_paths=None):
        self.bridge = bridge
        self.lock_paths = lock_paths
        self.owner = None
        self.page = None
        self.desired = None
        self.transition = None
        self.acknowledged = False
        self.last_seen = None
        self.capture_state = None

    def _active(self):
        return (self.bridge.run.get('status') in ('requesting','running')
                or self.bridge.run.get('workerActive') or self.bridge.run.get('leaseReleasePending')
                or self.bridge.pending is not None)

    def _settled(self):
        run = self.bridge.run
        return (not self._active() and (not run.get('id') or run.get('failureAcknowledged') is True
                or run.get('status')=='completed' and run.get('evidenceStatus')=='saved'
                and (self.bridge.output/run['id']/'recording.json').is_file()))

    def _fresh_browser(self):
        return self.last_seen is not None and time.monotonic()-self.last_seen < 3

    def status(self):
        with self.bridge.lock:
            state = 'unknown' if self.page is None else ('waiting' if self.page=='waiting' else 'connected')
            if self.transition and not self.acknowledged:
                state = 'transitioning'
            return {'state':state,'desiredPage':self.desired,'transitionId':self.transition,
                    'pinned':self.owner is not None,'fresh':self._fresh_browser(),
                    'clientSeenMs':round((time.monotonic()-self.last_seen)*1000) if self.last_seen is not None else None,
                    'captureState':self.capture_state,'artifactsSettled':self._settled()}

    def validate_frame(self, body):
        if self.owner is not None and body.get('client') != self.owner:
            raise ControlError('trial_renderer_is_pinned')
        if body.get('page') not in ('game','waiting') or body.get('captureState') not in ('idle','recording','saving','failed'):
            raise ControlError('invalid_browser_session_state')

    def frame(self, body):
        """Called atomically with bridge.frame under the bridge's reentrant lock."""
        with self.bridge.lock:
            self.validate_frame(body)
            self.page = body['page']
            self.last_seen = time.monotonic()
            self.capture_state = body['captureState']
            if self.transition and body.get('sessionAck') == self.transition and self.page == self.desired:
                self.acknowledged = True
            if self.owner is None or self.transition is None or self.acknowledged:
                return {'session':self.status(), 'navigation':None}
            # A navigation goal can request finishing capture, but never drop an
            # upload. Only a settled browser receives the actual navigation URL.
            navigation = None
            if not self._active() and self.capture_state=='idle' and self._settled():
                target = '/control/wait' if self.desired=='waiting' else '/web/index.html'
                navigation = {'id':self.transition,'page':self.desired,'url':target+'?transition='+self.transition}
            return {'session':self.status(),'navigation':navigation}

    def navigate(self, desired):
        with self.bridge.lock:
            if self._active():
                raise ControlError('run_is_active')
            if not self._fresh_browser() or self.bridge.client is None:
                raise ControlError('browser_session_unavailable')
            if desired=='game' and (self.owner is None or self.page!='waiting'):
                if self.owner is not None and self.desired=='game':
                    return self.status()
                raise ControlError('browser_must_be_waiting')
            if self.owner is None:
                self.owner = self.bridge.client
            if self.bridge.client != self.owner:
                raise ControlError('trial_renderer_is_pinned')
            if self.desired == desired and self.transition is not None:
                return self.status()
            self.desired = desired
            self.transition = uuid.uuid4().hex
            self.acknowledged = False
            return self.status()

    def dispatch(self, request, descriptors=()):
        if not isinstance(request,dict):
            raise ControlError('invalid_admin_request')
        operation = request.get('op')
        if descriptors and (operation!='start' or request.get('trial_context') is None):
            raise ControlError('unexpected_guard_descriptors')
        if operation=='status':
            with self.bridge.lock:
                return {'bridge':self.bridge.status(),'session':self.status(),
                        'observation':self.bridge._snapshot() if self.bridge.fresh() else None}
        if operation in ('prepare_wait','disconnect'):
            return self.navigate('waiting')
        if operation=='connect':
            return self.navigate('game')
        if operation=='release_failed_run':
            self.bridge.release_failed_run(request.get('run_id'))
            return self.dispatch({'op':'status'})
        if operation=='cancel':
            return self.bridge.cancel(request.get('run_id'))
        if operation=='start':
            run_id, request_id = request.get('run_id'), request.get('request_id')
            if not all(isinstance(value,str) and re.fullmatch('[a-f0-9]{32}',value) for value in (run_id,request_id)):
                raise ControlError('invalid_run_identity')
            if request.get('trial_context') is not None:
                validate_guard_descriptors(descriptors,request.get('lock_paths'),self.lock_paths)
            with self.bridge.lock:
                existing = (self.bridge.output/run_id).exists() or (self.bridge.output/'requests'/f'{request_id}.json').exists()
                if not existing and (self.owner is None or self.page!='game' or self.desired!='game'
                        or not self.acknowledged or not self._fresh_browser()):
                    raise ControlError('trial_renderer_not_connected')
                return self.bridge.start('api',request.get('model'),request.get('duration_seconds',22),
                    client=self.owner,run_id=run_id,request_id=request_id,
                    total_token_limit=request.get('total_token_limit'),trial_context=request.get('trial_context'),
                    docker_image_id=request.get('docker_image_id'),lease_fds=descriptors)
        raise ControlError('unknown_admin_operation')


class _AdminHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(5)
        descriptors = []
        try:
            raw = b''
            while b'\n' not in raw and len(raw)<=16384:
                chunk,ancillary,flags,_ = self.connection.recvmsg(16385-len(raw),socket.CMSG_SPACE(2*array.array('i').itemsize),
                    getattr(socket,'MSG_CMSG_CLOEXEC',0))
                for level,kind,value in ancillary:
                    if level!=socket.SOL_SOCKET or kind!=socket.SCM_RIGHTS:
                        raise ControlError('invalid_admin_ancillary_data')
                    received=array.array('i'); received.frombytes(value[:len(value)-len(value)%received.itemsize])
                    descriptors.extend(received)
                    for descriptor in received: os.set_inheritable(descriptor,False)
                if flags & getattr(socket,'MSG_CTRUNC',0) or len(descriptors)>2:
                    raise ControlError('too_many_guard_descriptors')
                if not chunk: break
                raw += chunk
            if not raw.endswith(b'\n') or len(raw)>16384:
                raise ControlError('invalid_admin_request_size')
            value = self.server.coordinator.dispatch(json.loads(raw),tuple(descriptors))
            response = {'ok':True,'result':value}
        except ControlError as error:
            response = {'ok':False,'error':error.code}
        except (ValueError, UnicodeError, RecursionError, TimeoutError):
            response = {'ok':False,'error':'invalid_admin_request'}
        except Exception:
            response = {'ok':False,'error':'admin_operation_failed'}
        finally:
            # Bridge.start duplicates an accepted lease. Every redundant, invalid,
            # or merely inspected incoming descriptor is closed in this handler.
            for descriptor in descriptors: os.close(descriptor)
        self.wfile.write(json.dumps(response,allow_nan=False).encode()+b'\n')


class AdminServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    request_queue_size = 4

    def __init__(self, path, coordinator):
        path = Path(path)
        if not path.is_absolute() or len(os.fsencode(path))>100:
            raise ControlError('invalid_admin_socket_path')
        parent = path.parent
        value = parent.lstat()
        if (parent.resolve()!=parent or not stat.S_ISDIR(value.st_mode) or value.st_uid!=os.geteuid()
                or stat.S_IMODE(value.st_mode)!=0o700):
            raise ControlError('admin_socket_parent_requires_mode_0700')
        self.coordinator = coordinator
        self.slots = threading.BoundedSemaphore(4)
        self.path = path
        self._lock_fd = os.open(str(path)+'.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        self._socket_identity = None
        try:
            lock_stat = os.fstat(self._lock_fd)
            if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_uid!=os.geteuid() or stat.S_IMODE(lock_stat.st_mode)!=0o600:
                raise ControlError('invalid_admin_socket_lock')
            try:
                fcntl.flock(self._lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise ControlError('admin_socket_already_owned') from None
            if path.exists() or path.is_symlink():
                previous = path.lstat()
                if not stat.S_ISSOCK(previous.st_mode) or previous.st_uid!=os.geteuid():
                    raise ControlError('admin_socket_path_conflict')
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as probe:
                    probe.settimeout(0.5)
                    try:
                        probe.connect(str(path))
                    except ConnectionRefusedError:
                        path.unlink()
                    else:
                        raise ControlError('admin_socket_already_owned')
            super().__init__(str(path),_AdminHandler)
            path.chmod(0o600)
            bound = path.lstat()
            self._socket_identity = (bound.st_dev,bound.st_ino)
        except Exception:
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None
            raise

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try: request.sendall(b'{"ok":false,"error":"admin_busy"}\n')
            finally: self.shutdown_request(request)
            return
        try:
            super().process_request(request,client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try: super().process_request_thread(request,client_address)
        finally: self.slots.release()

    def server_close(self):
        super().server_close()
        if self._socket_identity is not None:
            try:
                current = self.path.lstat()
                if (current.st_dev,current.st_ino)==self._socket_identity:
                    self.path.unlink()
            except FileNotFoundError:
                pass
            self._socket_identity = None
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
