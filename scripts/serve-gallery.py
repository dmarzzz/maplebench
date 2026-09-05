#!/usr/bin/env python3
"""Serve only public batch evidence on localhost, including MP4 byte ranges."""
import argparse
from functools import partial
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit


BATCH_FILES = {'index.html', 'summary.json'}
TRIAL_FILES = {'score.json', 'controller.json', 'scenario.json', 'provenance.json',
               'steps.jsonl', 'steps.json', 'decisions.json', 'episode.jsonl',
               'observations.json', 'observations.jsonl', 'prompt.txt'}
VIDEO_FILES = {'henesys-overlay.mp4', 'henesys-first.mp4', 'poster.jpg', 'poster.png'}
CONTENT_TYPES = {'.html': 'text/html; charset=utf-8', '.json': 'application/json; charset=utf-8',
                 '.jsonl': 'text/plain; charset=utf-8', '.txt': 'text/plain; charset=utf-8',
                 '.mp4': 'video/mp4', '.jpg': 'image/jpeg', '.png': 'image/png'}


def authorized_file(root, request_path):
    """A URL can expose only an allowlisted artifact in the exact batch layout."""
    try:
        raw = urlsplit(request_path).path
        if re.search(r'%(?![0-9a-fA-F]{2})', raw):
            return None
        decoded = unquote(raw, encoding='utf-8', errors='strict')
        if not decoded.startswith('/') or decoded.startswith('//') or '\\' in decoded or '\x00' in decoded:
            return None
        parts = decoded[1:].split('/')
        if any(not part or part.startswith(('.', '_')) for part in parts):
            return None
        if len(parts) == 2:
            allowed = parts[-1] in BATCH_FILES
        elif len(parts) == 5:
            allowed = (parts[1] == 'trials' and re.fullmatch(r'attempt-\d+', parts[3])
                       and parts[-1] in TRIAL_FILES)
        elif len(parts) == 6:
            allowed = (parts[1] == 'trials' and re.fullmatch(r'attempt-\d+', parts[3])
                       and parts[4] == 'video' and parts[-1] in VIDEO_FILES)
        else:
            allowed = False
        if not allowed:
            return None
        path = root.joinpath(*parts).resolve(strict=True)
        resolved_parts = path.relative_to(root).parts
        # Do not let a harmless filename symlink to a database snapshot or source.
        if any(part.startswith(('.', '_')) for part in resolved_parts) or resolved_parts != tuple(parts):
            return None
        return path if path.is_file() else None
    except (ValueError, OSError, UnicodeError, RuntimeError):
        return None


def parse_range(value, size):
    """Return inclusive bounds for one byte range; reject malformed/multi ranges."""
    if not value:
        return 0, size - 1
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
    if not match or not any(match.groups()) or size <= 0:
        raise ValueError('Unsatisfiable range')
    start, end = match.groups()
    if not start:
        length = int(end)
        if length <= 0:
            raise ValueError('Unsatisfiable range')
        return max(0, size - length), size - 1
    start = int(start)
    end = int(end) if end else size - 1
    if start >= size or end < start:
        raise ValueError('Unsatisfiable range')
    return start, min(end, size - 1)


class GalleryHandler(BaseHTTPRequestHandler):
    server_version = 'MapleBenchGallery/1'

    def __init__(self, *args, root, **kwargs):
        self.root = Path(root).resolve()
        super().__init__(*args, **kwargs)

    def log_message(self, *_):
        # No query strings, local paths, or run content in access logs.
        pass

    def _headers(self, status, content_type, length, *, extra=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Cache-Control', 'no-store' if content_type.startswith(('text/html', 'application/json')) else 'private, max-age=60')
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()

    def _navigation(self):
        entries = []
        for batch in sorted(self.root.iterdir(), key=lambda path: path.name, reverse=True):
            if batch.name.startswith(('.', '_')) or batch.is_symlink() or not batch.is_dir():
                continue
            if not authorized_file(self.root, '/' + quote(batch.name, safe='') + '/index.html'):
                continue
            title, state = batch.name, ''
            summary = authorized_file(self.root, '/' + quote(batch.name, safe='') + '/summary.json')
            try:
                if summary and summary.stat().st_size <= 16 * 1024 * 1024:
                    data = json.loads(summary.read_text(encoding='utf-8')).get('batch', {})
                    title = str(data.get('name') or data.get('id') or title)[:500]
                    state = str(data.get('status') or '')[:80]
            except (OSError, ValueError, AttributeError):
                pass
            entries.append('<li><a href="' + quote(batch.name, safe='') + '/index.html">' +
                           html.escape(title) + '</a><span>' + html.escape(state) + '</span></li>')
        body = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>MapleBench batches</title><style>body{max-width:850px;margin:50px auto;padding:0 24px;background:#f2f6f9;color:#16354e;'
                'font:17px/1.5 "Avenir Next","Trebuchet MS",sans-serif}h1{font-size:36px}ul{padding:0;list-style:none}li{padding:18px 0;border-bottom:1px solid #c4d5e2;display:flex;gap:20px;justify-content:space-between}a{color:#155c8e;overflow-wrap:anywhere}a:focus-visible{outline:3px solid #006bc2;outline-offset:4px}span{color:#586c7b;font-size:14px}</style>'
                '<h1>MapleBench batches</h1><p>Choose a batch to watch its runs and inspect the evidence.</p><ul>' +
                ''.join(entries) + '</ul>' + ('' if entries else '<p>No published batches yet. Results appear here when the queue publishes its first batch.</p>') + '</html>').encode('utf-8')
        return body

    def _serve(self, head=False):
        if not re.fullmatch(r'(?:127\.0\.0\.1|localhost)(?::\d+)?', self.headers.get('Host', '').lower()):
            self.send_error(403, 'Localhost access required')
            return
        if urlsplit(self.path).path == '/':
            content = self._navigation()
            self._headers(200, 'text/html; charset=utf-8', len(content))
            if not head:
                self.wfile.write(content)
            return
        path = authorized_file(self.root, self.path)
        if path is None:
            self.send_error(404, 'Artifact not available')
            return
        try:
            with path.open('rb') as stream:
                size = path.stat().st_size
                range_value = self.headers.get('Range')
                try:
                    start, end = parse_range(range_value, size)
                except ValueError:
                    self._headers(416, 'text/plain; charset=utf-8', 0,
                                  extra={'Content-Range': f'bytes */{size}'})
                    return
                length = end - start + 1
                extra = {'Accept-Ranges': 'bytes'}
                if range_value:
                    extra['Content-Range'] = f'bytes {start}-{end}/{size}'
                self._headers(206 if range_value else 200, CONTENT_TYPES.get(path.suffix, 'application/octet-stream'), length, extra=extra)
                if not head:
                    stream.seek(start)
                    while length:
                        chunk = stream.read(min(length, 256 * 1024))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        length -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError:
            self.send_error(404, 'Artifact not available')

    def do_GET(self):
        self._serve()

    def do_HEAD(self):
        self._serve(head=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='artifacts/batches', type=Path)
    parser.add_argument('--port', default=8848, type=int)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(GalleryHandler, root=args.root))
    print(f'MapleBench gallery listening on http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
