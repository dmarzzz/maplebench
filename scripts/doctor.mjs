import { spawnSync } from 'node:child_process';

const checks = [
  ['git', ['--version'], true],
  ['docker', ['--version'], true],
  ['java', ['-version'], true],
  ['mvn', ['-version'], false],
  ['cargo', ['--version'], true],
  ['rustc', ['--version'], true],
  ['wasm-bindgen', ['--version'], false],
];

let hardFailures = 0;
for (const [cmd, args, required] of checks) {
  const r = spawnSync(cmd, args, { encoding: 'utf8' });
  const ok = !r.error && r.status === 0;
  const first = ((r.stdout || r.stderr || '').trim().split(/\r?\n/)[0] || '').trim();
  console.log(`${ok ? '✓' : required ? '✗' : '·'} ${cmd.padEnd(13)} ${ok ? first : required ? 'missing (required)' : 'missing (install when needed)'}`);
  if (!ok && required) hardFailures++;
}

const wasm = spawnSync('rustup', ['target', 'list', '--installed'], { encoding: 'utf8' });
if (!wasm.error && wasm.status === 0) {
  const installed = wasm.stdout.includes('wasm32-unknown-unknown');
  console.log(`${installed ? '✓' : '·'} wasm target    ${installed ? 'wasm32-unknown-unknown installed' : 'install for browser client: rustup target add wasm32-unknown-unknown'}`);
}

if (hardFailures) process.exitCode = 1;
