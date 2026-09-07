import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const checker = fileURLToPath(new URL('../scripts/check-tracked-files.mjs', import.meta.url));
const manifestPath = 'examples/full-client-benchmark/recording-manifest.json';
const recordingRoot = 'examples/full-client-benchmark/recordings/';
const name = 'a'.repeat(32) + '.webm';
const bytes = Buffer.from('Synthetic guard fixture; not a real game recording.');
const entry = (path = name, data = bytes) => ({ path, bytes: data.length, sha256: createHash('sha256').update(data).digest('hex') });

function repository(t) {
  const root = mkdtempSync(join(tmpdir(), 'maplebench-tracked-guard-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const env = { ...process.env, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null' };
  for (const key of ['GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES']) delete env[key];
  const git = (...args) => execFileSync('git', args, { cwd: root, env, stdio: ['pipe', 'pipe', 'pipe'] });
  git('init', '--quiet');
  git('config', 'core.autocrlf', 'false');
  const write = (path, data, stage = true) => {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), data);
    if (stage) git('add', '--', path);
  };
  const manifest = (entries = [entry()], stage = true) => write(manifestPath, JSON.stringify({ schema_version: 1, entries }), stage);
  const run = (...args) => spawnSync(process.execPath, [checker, ...args], { cwd: root, env, encoding: 'utf8' });
  const curated = () => { write(recordingRoot + name, bytes); manifest(); };
  return { root, env, git, write, manifest, run, curated };
}

function refused(result, pattern) {
  assert.equal(result.status, 1, result.stdout + result.stderr);
  if (pattern) assert.match(result.stderr, pattern);
}

test('ordinary source files and env example remain allowed', t => {
  const repo = repository(t);
  repo.write('src/example.js', 'export const example = true;');
  repo.write('.env.example', 'PLACEHOLDER=');
  assert.equal(repo.run().status, 0);
});

test('original sensitive, runtime, asset and recording exclusions remain blocked', t => {
  const repo = repository(t);
  const paths = ['.env', 'private/notes.txt', 'assets/map.txt', 'artifacts/result.json',
    'runtime-output/result.json', 'recordings/sample.webm', 'examples/movie.mp4', 'map.wz',
    'data.sqlite', 'baseline.sql', 'demo-account.json', '._metadata'];
  for (const path of paths) repo.write(path, 'synthetic');
  const result = repo.run();
  refused(result);
  for (const path of paths) assert.ok(result.stderr.includes(path), path);
});

test('listed exact staged recording bytes pass', t => {
  const repo = repository(t);
  repo.curated();
  const result = repo.run();
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /1 verified curated recordings/);
});

test('missing or merely unstaged manifest cannot authorize a recording', t => {
  const repo = repository(t);
  repo.write(recordingRoot + name, bytes);
  refused(repo.run(), /curated_file_not_staged_regular/);
  repo.manifest([entry()], false);
  refused(repo.run(), /curated_file_not_staged_regular/);
});

test('unlisted recordings and untracked recordings stay blocked', t => {
  const repo = repository(t);
  repo.curated();
  const extra = recordingRoot + 'b'.repeat(32) + '.webm';
  repo.write(extra, bytes, false);
  assert.equal(repo.run().status, 0);
  refused(repo.run('--include-untracked'), /bbbbbbbb/);
  repo.git('add', '--', extra);
  refused(repo.run(), /bbbbbbbb/);
});

test('manifest path traversal, other locations and formats cannot expand the exception', t => {
  const repo = repository(t);
  repo.curated();
  for (const path of ['../' + name, recordingRoot + name, '/tmp/' + name,
    'a'.repeat(32) + '.mp4', 'A'.repeat(32) + '.webm', '.env']) {
    repo.manifest([entry(path)]);
    refused(repo.run(), /curated_manifest_invalid_entry/);
  }
});

test('corrupt hashes, sizes and JSON are refused without echoing manifest contents', t => {
  const repo = repository(t);
  repo.curated();
  repo.manifest([{ ...entry(), sha256: '0'.repeat(64) }]);
  refused(repo.run(), /curated_recording_bytes_mismatch/);
  repo.manifest([{ ...entry(), bytes: bytes.length + 1 }]);
  refused(repo.run(), /curated_recording_bytes_mismatch/);
  repo.write(manifestPath, '{DO_NOT_ECHO_PRIVATE_CONTENT');
  const result = repo.run();
  refused(result, /curated_manifest_invalid_json/);
  assert.ok(!result.stderr.includes('DO_NOT_ECHO_PRIVATE_CONTENT'));
});

test('exact schema, duplicate entries and ten-file limit are enforced', t => {
  const repo = repository(t);
  repo.curated();
  for (const value of [{ schema_version: 2, entries: [entry()] },
    { schema_version: 1, entries: [entry()], extra: true },
    { schema_version: 1, entries: [] },
    { schema_version: 1, entries: Array.from({ length: 11 }, () => entry()) }]) {
    repo.write(manifestPath, JSON.stringify(value));
    refused(repo.run(), /curated_manifest_invalid_schema/);
  }
  repo.manifest([entry(), entry()]);
  refused(repo.run(), /curated_manifest_duplicate_entry/);
  repo.manifest([{ ...entry(), bytes: true }]);
  refused(repo.run(), /curated_manifest_invalid_entry/);
});

test('staged and declared oversize recordings and oversized manifests are refused', t => {
  const repo = repository(t);
  repo.curated();
  repo.manifest([{ ...entry(), bytes: 32 * 1024 * 1024 + 1 }]);
  refused(repo.run(), /curated_manifest_invalid_entry/);
  repo.manifest();
  repo.write(recordingRoot + name, Buffer.alloc(32 * 1024 * 1024 + 1));
  refused(repo.run(), /curated_blob_size_limit/);
  repo.write(manifestPath, ' '.repeat(16 * 1024 + 1));
  refused(repo.run(), /curated_blob_size_limit/);
});

test('verification uses index contents even when worktree bytes disagree', t => {
  const repo = repository(t);
  repo.curated();
  repo.write(recordingRoot + name, 'different unstaged video', false);
  repo.write(manifestPath, '{invalid unstaged manifest', false);
  assert.equal(repo.run().status, 0);
  repo.git('add', '--', recordingRoot + name);
  repo.write(recordingRoot + name, bytes, false);
  refused(repo.run(), /curated_recording_bytes_mismatch/);
});

test('listed but unstaged, removed or symlink recording is refused', t => {
  const repo = repository(t);
  repo.manifest();
  repo.write(recordingRoot + name, bytes, false);
  refused(repo.run(), /curated_file_not_staged_regular/);
  repo.git('add', '--', recordingRoot + name);
  repo.git('rm', '--cached', '--', recordingRoot + name);
  refused(repo.run(), /curated_file_not_staged_regular/);
  rmSync(join(repo.root, recordingRoot + name));
  symlinkSync('../../../elsewhere.webm', join(repo.root, recordingRoot + name));
  repo.git('add', '--', recordingRoot + name);
  refused(repo.run(), /curated_file_not_staged_regular/);
});

test('unmerged index and symlink manifest cannot authorize recordings', t => {
  const repo = repository(t);
  repo.curated();
  const object = repo.git('hash-object', '--', manifestPath).toString().trim();
  repo.git('update-index', '--force-remove', '--', manifestPath);
  execFileSync('git', ['update-index', '--index-info'], { cwd: repo.root, env: repo.env,
    input: `100644 ${object} 1\t${manifestPath}\n100644 ${object} 2\t${manifestPath}\n` });
  refused(repo.run(), /curated_index_conflict/);
  repo.git('update-index', '--force-remove', '--', manifestPath);
  rmSync(join(repo.root, manifestPath));
  symlinkSync('somewhere.json', join(repo.root, manifestPath));
  repo.git('add', '--', manifestPath);
  refused(repo.run(), /curated_file_not_staged_regular/);
});
