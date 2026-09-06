"""Localhost-only host wrapper around the upstream full client services."""
from pathlib import Path
import asyncio
import base64
import http.server
import hashlib
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.parse

ROOT = Path(os.environ['MAPLEBENCH_CLIENT_ROOT']).resolve()
OUTPUT = Path(os.environ.get('MAPLEBENCH_CLIENT_OUTPUT', 'artifacts/full-client')).resolve()
OUTPUT.mkdir(parents=True, exist_ok=True)
DEMO_ACCOUNT = Path(os.environ['MAPLEBENCH_DEMO_ACCOUNT_FILE'])
CONTROLS = Path(__file__).resolve().parents[1]/'ui/full-client/controller.js'
sys.path.insert(0, str(ROOT / 'web'))
import assets_server
import websockets
import ws_proxy
from full_client_bridge import FullClientBridge, read_private_file, validate_private_file
validate_private_file(DEMO_ACCOUNT)
BRIDGE = FullClientBridge(OUTPUT/'runs', os.environ.get('MAPLEBENCH_API_KEY_FILE'))
ADMIN_SOCKET = os.environ.get('MAPLEBENCH_ADMIN_SOCKET')
from full_client_session import AdminServer, SessionCoordinator
SESSION = SessionCoordinator(BRIDGE,lock_paths={
    'world':os.environ.get('MAPLEBENCH_WORLD_LOCK_FILE'),
    'queue':os.environ.get('MAPLEBENCH_QUEUE_LOCK_FILE')}) if ADMIN_SOCKET else None
UPLOAD_SLOT = threading.BoundedSemaphore(1)
MAX_UPLOAD_BYTES = 100*1024*1024


def loopback_authority(authority):
    try:
        value = urllib.parse.urlsplit('//' + authority)
        return (value.hostname in {'localhost','127.0.0.1','::1'} and not value.username
                and not value.password and not value.path and not value.query and not value.fragment
                and (value.port is None or 1 <= value.port <= 65535))
    except (TypeError, ValueError):
        return False

CONFIG = {
    'AssetsServerIP': '127.0.0.1', 'AssetsServerPort': 8842,
    'AssetsServerProtocol': 'ws', 'ProxyIP': '127.0.0.1', 'ProxyPort': 8841,
    'MapleStoryServerIp': '127.0.0.1', 'MapleStoryServerPort': 8484,
}

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        super().end_headers()

    def trusted_request(self):
        hosts = self.headers.get_all('Host', [])
        origin = self.headers.get('Origin')
        # Browser-driven reloads may label this navigation cross-site. Only the
        # inert waiting document can be entered that way; control/credential
        # endpoints and embedded resources retain their same-origin requirement.
        waiting_navigation = (self.command == 'GET' and self.path.partition('?')[0] == '/control/wait'
            and origin is None and self.headers.get('Sec-Fetch-Mode') == 'navigate'
            and self.headers.get('Sec-Fetch-Dest') == 'document')
        if (len(hosts) != 1 or not loopback_authority(hosts[0])
                or self.headers.get('Sec-Fetch-Site') in {'cross-site','same-site'} and not waiting_navigation
                or (origin is not None and origin != 'http://' + hosts[0])):
            self.close_connection = True
            self.send_error(403)
            return False
        return True

    def json_response(self, value):
        data = json.dumps(value, allow_nan=False).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body_size(self, maximum):
        lengths = self.headers.get_all('Content-Length', [])
        if self.headers.get('Transfer-Encoding') or len(lengths) != 1 or not re.fullmatch('[0-9]+', lengths[0]):
            raise ValueError('Invalid content length')
        size = int(lengths[0])
        if not 0 < size <= maximum:
            raise OverflowError('Invalid request size')
        return size

    def do_GET(self):
        if not self.trusted_request():
            return
        path = urllib.parse.urlsplit(self.path).path
        if path == '/control/status':
            self.json_response(BRIDGE.status())
            return
        if path == '/control/wait' and SESSION is not None:
            data = (CONTROLS.parent/'waiting.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers(); self.wfile.write(data)
            return
        if path == '/demo-session':
            auth = json.loads(read_private_file(DEMO_ACCOUNT,16384))
            data = json.dumps(dict(auth, enabled=True)).encode()
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == '/web/index.html':
            if not (ROOT/'web/index.html').resolve().is_relative_to(ROOT):
                self.send_error(404)
                return
            data = (ROOT/'web/index.html').read_text().replace('</body>', '<script src="/full-client-demo.js"></script></body>').encode()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == '/full-client-demo.js':
            data = CONTROLS.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','application/javascript')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == '/':
            self.send_response(302)
            self.send_header('Location', '/web/index.html')
            self.end_headers()
            return
        if path == '/web/config.json':
            data = json.dumps(CONFIG).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path not in {'/web/index.html', '/build/JourneyClient.js', '/build/JourneyClient.wasm'}:
            self.send_error(404)
            return
        # The allowlist must also survive symlinks in a supplied build checkout.
        if not (ROOT/path.lstrip('/')).resolve().is_relative_to(ROOT):
            self.send_error(404)
            return
        super().do_GET()

    def log_message(self, format, *args):
        if self.path != '/control/frame': super().log_message(format, *args)

    def do_HEAD(self):
        self.send_error(405)

    def do_POST(self):
        if not self.trusted_request():
            return
        if self.path in {'/control/frame', '/control/start'}:
            try:
                if self.headers.get_content_type() != 'application/json':
                    self.send_error(415); return
                size = self.body_size(70000)
                self.connection.settimeout(5)
                raw = self.rfile.read(size)
                if len(raw) != size: raise ValueError('Incomplete body')
                body = json.loads(raw)
                if not isinstance(body, dict): raise ValueError('Invalid request')
                if self.path == '/control/start' and self.headers.get('Origin') and not body.get('client'):
                    raise ValueError('Missing renderer owner')
                if self.path == '/control/frame':
                    with BRIDGE.lock:
                        if SESSION is not None: SESSION.validate_frame(body)
                        value = BRIDGE.frame(body)
                        if SESSION is not None: value.update(SESSION.frame(body))
                else:
                    value = BRIDGE.start(body.get('mode'),body.get('model'),body.get('durationSeconds',22),client=body.get('client'))
                self.json_response(value)
            except (ValueError, KeyError, UnicodeError, RecursionError):
                self.send_error(409)
            except OverflowError:
                self.send_error(413)
            except (TimeoutError, socket.timeout):
                self.send_error(408)
            except OSError:
                self.send_error(503)
            return
        if self.path != '/demo-recording':
            self.send_error(404); return
        if not UPLOAD_SLOT.acquire(blocking=False):
            self.send_error(429); return
        temporary = None
        try:
            if self.headers.get_content_type() != 'video/webm':
                self.send_error(415); return
            size = self.body_size(MAX_UPLOAD_BYTES)
            run_id, client = self.headers.get('X-MapleBench-Run'), self.headers.get('X-MapleBench-Client')
            capture=None
            encoded_capture=self.headers.get('X-MapleBench-Capture')
            if encoded_capture is not None:
                if len(encoded_capture)>8000: raise ValueError('Capture metadata oversized')
                capture=json.loads(base64.b64decode(encoded_capture,validate=True))
            if run_id:
                if self.headers.get('Origin') and not client:
                    raise ValueError('Missing recording owner')
                BRIDGE.recording_owner(run_id, client)
            if shutil.disk_usage(OUTPUT).free < size + 64*1024*1024:
                self.send_error(507); return
            descriptor, name = tempfile.mkstemp(prefix='.recording-',suffix='.part',dir=OUTPUT)
            temporary = Path(name)
            digest = hashlib.sha256()
            deadline = time.monotonic()+60
            self.connection.settimeout(10)
            with os.fdopen(descriptor,'wb') as out:
                remaining = size
                while remaining:
                    if time.monotonic() >= deadline: raise TimeoutError('Upload deadline')
                    chunk = self.rfile.read(min(1024*1024,remaining))
                    if not chunk: raise ValueError('Incomplete recording')
                    if remaining == size and not chunk.startswith(b'\x1a\x45\xdf\xa3'):
                        raise ValueError('Invalid WebM header')
                    out.write(chunk); digest.update(chunk); remaining -= len(chunk)
                out.flush(); os.fsync(out.fileno())
            if run_id:
                BRIDGE.attach_recording(run_id,temporary,digest.hexdigest(),client,capture)
                temporary.unlink(missing_ok=True)
                # Retain the compatibility alias without exposing a partially copied file.
                descriptor, name = tempfile.mkstemp(prefix='.recording-',suffix='.part',dir=OUTPUT)
                os.close(descriptor)
                temporary = Path(name)
                shutil.copyfile(OUTPUT/'runs'/run_id/'video.webm',temporary)
            temporary.replace(OUTPUT/'full-client-demo.webm')
            self.json_response({'status':'saved','runId':run_id,'sha256':digest.hexdigest()})
        except OverflowError:
            self.send_error(413)
        except (ValueError, KeyError, RecursionError):
            self.send_error(409)
        except (TimeoutError, socket.timeout):
            self.send_error(408)
        except OSError:
            self.send_error(503)
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)
            UPLOAD_SLOT.release()


class BoundedHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try: request.sendall(b'HTTP/1.1 503 Busy\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
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

class GuardedConnection:
    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __aiter__(self):
        return self.connection.__aiter__()

    async def recv(self):
        message = await self.connection.recv()
        text = message.decode() if isinstance(message, bytes) else message
        if text not in {'127.0.0.1:8484', '127.0.0.1:7575', '127.0.0.1:7576'}:
            raise ValueError('Target is not a configured local game port')
        return message


def trusted_websocket(connection):
    headers = getattr(connection, 'request_headers', None)
    if headers is None:
        headers = getattr(getattr(connection, 'request', None), 'headers', None)
    if headers is None:
        return False
    try:
        origin = urllib.parse.urlsplit(headers.get('Origin', ''))
        return (loopback_authority(headers.get('Host', '')) and origin.scheme == 'http'
                and loopback_authority(origin.netloc) and not origin.path and not origin.query and not origin.fragment)
    except (ValueError, TypeError):
        return False

async def main():
    asset = assets_server.AssetServer(str(ROOT / 'assets'))
    proxy = ws_proxy.MapleStoryProxy()
    async def connect(ws):
        if not trusted_websocket(ws):
            await ws.close(code=1008,reason='Local browser origin required')
            return
        await proxy.handle_client(GuardedConnection(ws))
    async def assets(ws):
        if not trusted_websocket(ws):
            await ws.close(code=1008,reason='Local browser origin required')
            return
        await asset.handler(ws)
    admin = AdminServer(ADMIN_SOCKET,SESSION) if ADMIN_SOCKET else None
    httpd = None
    admin_started = http_started = False
    try:
        httpd = BoundedHTTPServer(('127.0.0.1', 8840), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        http_started = True
        if admin is not None:
            threading.Thread(target=admin.serve_forever,daemon=True).start()
            admin_started = True
        async with websockets.serve(connect, '127.0.0.1', 8841), websockets.serve(
            assets, '127.0.0.1', 8842, max_size=50*1024*1024, compression=None
        ):
            print('Full client: HTTP 8840 / game 8841 / assets 8842, localhost only', flush=True)
            await asyncio.Future()
    finally:
        if admin is not None:
            if admin_started: admin.shutdown()
            admin.server_close()
        if httpd is not None:
            if http_started: httpd.shutdown()
            httpd.server_close()

if __name__ == '__main__':
    asyncio.run(main())
