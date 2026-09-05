"""Localhost-only host wrapper around the upstream full client services."""
from pathlib import Path
import asyncio
import http.server
import hashlib
import json
import os
import re
import shutil
import sys
import threading
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
from full_client_bridge import FullClientBridge
BRIDGE = FullClientBridge(OUTPUT/'runs', os.environ.get('MAPLEBENCH_API_KEY_FILE'))

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
        super().end_headers()

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == '/demo-session':
            auth = json.loads(DEMO_ACCOUNT.read_text())
            data = json.dumps(dict(auth, enabled=True)).encode()
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == '/web/index.html':
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
        super().do_GET()

    def log_message(self, format, *args):
        if self.path != '/control/frame': super().log_message(format, *args)

    def do_HEAD(self):
        self.send_error(405)

    def do_POST(self):
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
            self.send_error(403); return
        if self.path in {'/control/frame', '/control/start'}:
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 70000: raise ValueError('Invalid request size')
                self.connection.settimeout(5)
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict): raise ValueError('Invalid request')
                value = BRIDGE.frame(body) if self.path == '/control/frame' else BRIDGE.start(body.get('mode'), body.get('model'))
                data = json.dumps(value).encode()
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers(); self.wfile.write(data)
            except (ValueError, KeyError):
                self.send_error(409)
            return
        if self.path != '/demo-recording':
            self.send_error(404); return
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 < size <= 100*1024*1024:
            self.send_error(413); return
        destination = OUTPUT/'full-client-demo.webm'
        self.connection.settimeout(60)
        with destination.with_suffix('.part').open('wb') as out:
            remaining=size
            while remaining:
                chunk=self.rfile.read(min(1024*1024,remaining))
                if not chunk: raise EOFError('truncated recording')
                out.write(chunk);remaining-=len(chunk)
        destination.with_suffix('.part').replace(destination)
        run_id = self.headers.get('X-MapleBench-Run', '')
        if re.fullmatch('[a-f0-9]{32}', run_id) and run_id == BRIDGE.run.get('id'):
            run_dir = OUTPUT/'runs'/run_id
            if run_dir.is_dir():
                video = run_dir/'video.webm'
                shutil.copyfile(destination, video)
                # A completed upload is not visual review or scoring evidence.
                manifest = run_dir/'publication.json'
                if manifest.is_file():
                    value = json.loads(manifest.read_text())
                    value['video'] = {'path':'video.webm', 'sha256':hashlib.sha256(video.read_bytes()).hexdigest(),
                                      'status':'completed', 'reviewed':False, 'interrupted':None,
                                      'start_ms':None, 'end_ms':None, 'duration_ms':None,
                                      'overlay':{'controller_id':run_id, 'mode':BRIDGE.run.get('mode'),
                                                 'model':BRIDGE.run.get('model')}}
                    temporary = manifest.with_suffix('.tmp')
                    temporary.write_text(json.dumps(value, indent=2)+'\n')
                    temporary.replace(manifest)
        self.send_response(204);self.end_headers()

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

async def main():
    asset = assets_server.AssetServer(str(ROOT / 'assets'))
    proxy = ws_proxy.MapleStoryProxy()
    async def connect(ws):
        await proxy.handle_client(GuardedConnection(ws))
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 8840), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    async with websockets.serve(connect, '127.0.0.1', 8841), websockets.serve(
        asset.handler, '127.0.0.1', 8842, max_size=50*1024*1024, compression=None
    ):
        print('Full client: HTTP 8840 / game 8841 / assets 8842, localhost only', flush=True)
        await asyncio.Future()

asyncio.run(main())
