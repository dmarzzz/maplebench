import { execFileSync } from 'node:child_process';

// Inspect the index, including newly staged files. No file contents or secrets are logged.
const files = execFileSync('git', ['ls-files', '-z'], { encoding: 'utf8' }).split('\0').filter(Boolean);
const forbidden = /(^|\/)(?:\.env(?:\..+)?|id_(?:rsa|ed25519)|credentials(?:\..+)?|secrets|private|assets|baked|shots|artifacts|recordings|runtime[^/]*|server-data|upstream)(?:\/|$)|\.(?:pem|key|p12|pfx|wz|exe|sqlite\d*|db|zip|bundle)$/i;
const blocked = files.filter(file => (forbidden.test(file) && file !== '.env.example') || /(^|\/)\._/.test(file));
if (blocked.length) {
  console.error('Refusing to commit runtime data or sensitive file types:\n' + blocked.join('\n'));
  process.exit(1);
}
console.log(`Checked ${files.length} tracked paths: no runtime or sensitive files.`);
