import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';

// Inspect the index, including newly staged files. No file contents or secrets are logged.
const args = ['ls-files', '-z'];
if (process.argv.includes('--include-untracked')) args.push('--cached', '--others', '--exclude-standard');
const files = [...new Set(execFileSync('git', args, { encoding: 'utf8' }).split('\0').filter(Boolean))];
const manifestPath = 'examples/full-client-benchmark/recording-manifest.json';
const recordingRoot = 'examples/full-client-benchmark/recordings/';
const maxRecordingBytes = 32 * 1024 * 1024;
const maxManifestBytes = 16 * 1024;
const allowedRecordings = new Set();

function require(condition, code) {
  if (!condition) throw new Error(code);
}

function exactFields(value, fields) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === fields.length && fields.every(key => Object.hasOwn(value, key));
}

// An unstaged manifest or working-tree edit must never authorize staged bytes.
// Read object IDs from the index and use immutable Git objects throughout.
function curatedRecordings() {
  const index = new Map();
  for (const row of execFileSync('git', ['ls-files', '--stage', '-z'], { encoding: 'utf8' }).split('\0').filter(Boolean)) {
    const tab = row.indexOf('\t');
    const [mode, object, stage] = row.slice(0, tab).split(' ');
    const path = row.slice(tab + 1);
    if (path === manifestPath || path.startsWith(recordingRoot)) {
      require(tab > 0 && stage === '0' && !index.has(path), 'curated_index_conflict');
      index.set(path, { mode, object });
    }
  }
  function stagedBlob(path, maximum) {
    const entry = index.get(path);
    require(entry && entry.mode === '100644', 'curated_file_not_staged_regular');
    const sizeText = execFileSync('git', ['cat-file', '-s', entry.object], { encoding: 'utf8' }).trim();
    require(/^[0-9]+$/.test(sizeText), 'curated_blob_size_invalid');
    const size = Number(sizeText);
    require(Number.isSafeInteger(size) && size > 0 && size <= maximum, 'curated_blob_size_limit');
    const bytes = execFileSync('git', ['cat-file', 'blob', entry.object], { maxBuffer: maximum + 1 });
    require(bytes.length === size, 'curated_blob_size_changed');
    return bytes;
  }
  const raw = stagedBlob(manifestPath, maxManifestBytes);
  let manifest;
  try { manifest = JSON.parse(raw.toString('utf8')); }
  catch { throw new Error('curated_manifest_invalid_json'); }
  require(exactFields(manifest, ['schema_version', 'entries']) && manifest.schema_version === 1
    && Array.isArray(manifest.entries) && manifest.entries.length >= 1 && manifest.entries.length <= 10,
  'curated_manifest_invalid_schema');
  for (const entry of manifest.entries) {
    require(exactFields(entry, ['path', 'bytes', 'sha256']) && typeof entry.path === 'string'
      && /^[a-f0-9]{32}\.webm$/.test(entry.path) && Number.isSafeInteger(entry.bytes)
      && entry.bytes >= 1 && entry.bytes <= maxRecordingBytes && typeof entry.sha256 === 'string'
      && /^[a-f0-9]{64}$/.test(entry.sha256), 'curated_manifest_invalid_entry');
    const path = recordingRoot + entry.path;
    require(!allowedRecordings.has(path), 'curated_manifest_duplicate_entry');
    const bytes = stagedBlob(path, maxRecordingBytes);
    require(bytes.length === entry.bytes && createHash('sha256').update(bytes).digest('hex') === entry.sha256,
      'curated_recording_bytes_mismatch');
    allowedRecordings.add(path);
  }
}

if (files.includes(manifestPath) || files.some(path => path.startsWith(recordingRoot))) {
  try { curatedRecordings(); }
  catch (error) {
    // Git/process errors may contain arbitrary data; only our fixed codes are printed.
    const code = /^curated_[a-z_]+$/.test(error?.message) ? error.message : 'curated_index_read_failed';
    console.error(`Refusing curated recordings: ${code}`);
    process.exit(1);
  }
}
const forbidden = /(^|\/)(?:\.env(?:\..+)?|id_(?:rsa|ed25519)|credentials(?:\..+)?|secrets|private|assets|baked|shots|artifacts|recordings|runtime[^/]*|server-data|upstream)(?:\/|$)|\.(?:pem|key|p12|pfx|wz|exe|sqlite\d*|db|zip|bundle)$/i;
const runtimeArtifacts = /\.(?:mp4|webm|mov|mkv|mp3|wav|cab|7z|tar|gz|class|jar)$/i;
const runtimeNames = /(?:^|\/)(?:baseline|snapshot|database-dump)\.sql$|(?:^|\/)demo-account\.json$/i;
const blocked = files.filter(file => !allowedRecordings.has(file) && ((forbidden.test(file) && file !== '.env.example')
  || runtimeArtifacts.test(file) || runtimeNames.test(file) || /(^|\/)\._/.test(file)));
if (blocked.length) {
  console.error('Refusing to commit runtime data or sensitive file types:\n' + blocked.join('\n'));
  process.exit(1);
}
console.log(`Checked ${files.length} tracked paths: ${allowedRecordings.size} verified curated recordings; no other runtime or sensitive files.`);
