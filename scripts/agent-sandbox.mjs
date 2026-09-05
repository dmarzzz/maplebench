// This bootstrap runs ONLY inside the disposable, networkless Docker container.
// Docker is the security boundary; AsyncFunction is only a convenient JS entrypoint.
import readline from 'node:readline';

const output = process.stdout.write.bind(process.stdout);
const send = message => output(JSON.stringify(message) + '\n');
const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
const pending = new Map();
let nextId = 0;
let initialized = false;
let logCount = 0;

function rpc(method, args) {
  if (pending.size >= 8) return Promise.reject(new Error('Too many pending SDK requests'));
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    send({ type: 'rpc', id, method, args });
  });
}

const sdk = Object.freeze({
  observe: () => rpc('observe', []),
  moveTo: (x, y) => rpc('moveTo', [x, y]),
  attack: targetId => rpc('attack', [targetId]),
  useSkill: (skillId, targetId) => rpc('useSkill', [skillId, targetId]),
  useItem: itemId => rpc('useItem', [itemId]),
  wait: milliseconds => rpc('wait', [milliseconds]),
});
const log = (...values) => {
  if (++logCount > 16) return;
  send({ type: 'log', text: values.map(value => String(value).slice(0, 256)).join(' ').slice(0, 1024) });
};
const safeConsole = Object.freeze({ log, info: log, warn: log, error: log });

input.on('line', async line => {
  if (Buffer.byteLength(line) > 1024 * 1024) process.exit(2);
  let message;
  try { message = JSON.parse(line); } catch { process.exit(2); }
  if (!initialized) {
    initialized = true;
    if (message.type !== 'init' || typeof message.code !== 'string' || message.code.length > 12000) process.exit(2);
    // A second timer outside Node (GNU timeout) also bounds CPU-bound programs.
    setTimeout(() => process.exit(124), message.timeoutMs).unref();
    try {
      const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
      const execute = new AsyncFunction('sdk', 'console', '"use strict";\n' + message.code);
      await execute(sdk, safeConsole);
      send({ type: 'done', ok: true });
      process.exit(0);
    } catch (error) {
      send({ type: 'done', ok: false, error: String(error?.message || 'Program failed').slice(0, 512) });
      process.exit(0);
    }
    return;
  }
  const waiter = pending.get(message.id);
  if (!waiter) return;
  pending.delete(message.id);
  if (message.ok === true) waiter.resolve(message.result);
  else waiter.reject(new Error(String(message.error || 'SDK request rejected').slice(0, 256)));
});

// A worker crash closes the Docker client's stdin. The outer GNU timeout covers
// programs that block this event loop and therefore cannot process EOF.
input.on('close', () => process.exit(0));
