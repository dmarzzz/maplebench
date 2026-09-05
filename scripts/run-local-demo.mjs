import { spawn } from 'node:child_process';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const children = [];
function run(command, args, env = {}) {
  const child = spawn(command, args, { cwd:root, env:{...process.env,...env}, stdio:'inherit' });
  children.push(child); return child;
}
function stop(){ for(const child of children) if(!child.killed) child.kill('SIGTERM'); }
process.on('SIGINT',()=>{stop();process.exit(0)}); process.on('SIGTERM',()=>{stop();process.exit(0)});

run(process.execPath, ['scripts/mock-cosmic.mjs']);
run(process.execPath, ['scripts/serve-ui.mjs']);
setTimeout(() => run(process.execPath, ['examples/demo-agent.mjs'], { MAPLEBENCH_URL:'http://127.0.0.1:8790' }), 900);

console.log('\nOpen http://127.0.0.1:8787 — the demo agent will start automatically. Ctrl-C stops the servers.\n');
await new Promise(() => {});
