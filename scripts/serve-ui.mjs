import { createReadStream } from 'node:fs';
import { open, stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const root = normalize(join(repoRoot, 'ui'));
const episodePath = normalize(process.env.MAPLEBENCH_EPISODE || join(repoRoot, 'artifacts/live/episode.jsonl'));
const port = Number(process.env.PORT || 8787);
const contentTypes = { '.html':'text/html; charset=utf-8', '.js':'text/javascript; charset=utf-8', '.css':'text/css; charset=utf-8', '.json':'application/json; charset=utf-8' };

function startEpisodeStream(req, res) {
  res.writeHead(200, {
    'content-type': 'text/event-stream; charset=utf-8',
    'cache-control': 'no-cache, no-transform',
    'connection': 'keep-alive',
    'x-accel-buffering': 'no'
  });
  res.write(': maplebench live tail\n\n');

  let offset = 0;
  let remainder = '';
  let closed = false;
  let reading = false;

  const poll = async () => {
    if (closed || reading) return;
    reading = true;
    try {
      const info = await stat(episodePath);
      if (info.size < offset) { offset = 0; remainder = ''; }
      if (info.size > offset) {
        const length = info.size - offset;
        const handle = await open(episodePath, 'r');
        const buffer = Buffer.alloc(length);
        try { await handle.read(buffer, 0, length, offset); } finally { await handle.close(); }
        offset = info.size;
        const text = remainder + buffer.toString('utf8');
        const lines = text.split(/\r?\n/);
        remainder = lines.pop() || '';
        for (const raw of lines) {
          const line = raw.trim();
          if (!line) continue;
          try {
            JSON.parse(line);
            res.write(`event: episode\ndata: ${line}\n\n`);
          } catch {
            res.write(`event: warning\ndata: ${JSON.stringify({error:'invalid_jsonl_line'})}\n\n`);
          }
        }
      }
    } catch (error) {
      if (error?.code !== 'ENOENT') res.write(`event: warning\ndata: ${JSON.stringify({error:String(error?.message || error)})}\n\n`);
    } finally {
      reading = false;
    }
  };

  const timer = setInterval(poll, 250);
  const heartbeat = setInterval(() => { if (!closed) res.write(': heartbeat\n\n'); }, 15000);
  poll();
  req.on('close', () => { closed = true; clearInterval(timer); clearInterval(heartbeat); });
}

createServer(async (req, res) => {
  const raw = decodeURIComponent((req.url || '/').split('?')[0]);
  if (raw === '/events') return startEpisodeStream(req, res);
  if (raw === '/api/health') {
    res.writeHead(200, { 'content-type':'application/json; charset=utf-8', 'cache-control':'no-store' });
    return res.end(JSON.stringify({ ok:true, episodePath }));
  }

  const rel = raw === '/' ? 'index.html' : raw.replace(/^\/+/, '');
  const path = normalize(join(root, rel));
  if (!path.startsWith(root)) { res.writeHead(403); return res.end('forbidden'); }
  try {
    const info = await stat(path);
    if (!info.isFile()) throw new Error('not file');
    res.writeHead(200, { 'content-type': contentTypes[extname(path)] || 'application/octet-stream', 'cache-control':'no-store' });
    createReadStream(path).pipe(res);
  } catch {
    res.writeHead(404, { 'content-type':'text/plain; charset=utf-8' });
    res.end('not found');
  }
}).listen(port, '127.0.0.1', () => {
  console.log(`MapleBench viewer: http://127.0.0.1:${port}`);
  console.log(`Live episode tail: ${episodePath}`);
});
