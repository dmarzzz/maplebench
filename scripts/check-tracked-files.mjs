import { execFileSync } from 'node:child_process';

// Inspect the index, including newly staged files. No file contents or secrets are logged.
const args = ['ls-files', '-z'];
if (process.argv.includes('--include-untracked')) args.push('--cached', '--others', '--exclude-standard');
const files = [...new Set(execFileSync('git', args, { encoding: 'utf8' }).split('\0').filter(Boolean))];
const forbidden = /(^|\/)(?:\.env(?:\..+)?|id_(?:rsa|ed25519)|credentials(?:\..+)?|secrets|private|assets|baked|shots|artifacts|recordings|runtime[^/]*|server-data|upstream)(?:\/|$)|\.(?:pem|key|p12|pfx|wz|exe|sqlite\d*|db|zip|bundle)$/i;
const runtimeArtifacts = /\.(?:mp4|webm|mov|mkv|mp3|wav|cab|7z|tar|gz|class|jar)$/i;
const runtimeNames = /(?:^|\/)(?:baseline|snapshot|database-dump)\.sql$|(?:^|\/)demo-account\.json$/i;
const blocked = files.filter(file => (forbidden.test(file) && file !== '.env.example')
  || runtimeArtifacts.test(file) || runtimeNames.test(file) || /(^|\/)\._/.test(file));
if (blocked.length) {
  console.error('Refusing to commit runtime data or sensitive file types:\n' + blocked.join('\n'));
  process.exit(1);
}
console.log(`Checked ${files.length} tracked paths: no runtime or sensitive files.`);
