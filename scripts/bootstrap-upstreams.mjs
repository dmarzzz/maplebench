import { execFileSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const lock = JSON.parse(readFileSync(join(repoRoot, 'upstream.lock.json'), 'utf8'));
const upstreamRoot = join(repoRoot, 'upstream');
mkdirSync(upstreamRoot, { recursive: true });

function git(args, cwd = repoRoot) {
  execFileSync('git', args, { cwd, stdio: 'inherit' });
}

function checkoutPinned(name, spec) {
  const dir = join(upstreamRoot, name);
  if (!existsSync(join(dir, '.git'))) {
    mkdirSync(dir, { recursive: true });
    git(['init'], dir);
    git(['remote', 'add', 'origin', spec.repository], dir);
  }
  console.log(`\n==> ${name}: ${spec.commit}`);
  git(['fetch', '--depth=1', 'origin', spec.commit], dir);
  git(['checkout', '--detach', 'FETCH_HEAD'], dir);
  return dir;
}

function replaceOnce(path, anchor, replacement, label) {
  let src = readFileSync(path, 'utf8');
  if (src.includes(replacement.trim())) {
    console.log(`==> Cosmic ${label} already present`);
    return;
  }
  const first = src.indexOf(anchor);
  if (first < 0) throw new Error(`Could not locate ${label} anchor; pinned upstream shape changed.`);
  if (src.indexOf(anchor, first + anchor.length) >= 0) throw new Error(`${label} anchor is ambiguous.`);
  src = src.slice(0, first) + replacement + src.slice(first + anchor.length);
  writeFileSync(path, src);
  console.log(`==> Applied Cosmic ${label}`);
}

function insertBeforeOnce(path, anchor, insertion, marker, label) {
  let src = readFileSync(path, 'utf8');
  if (src.includes(marker)) {
    console.log(`==> Cosmic ${label} already present`);
    return;
  }
  const first = src.indexOf(anchor);
  if (first < 0) throw new Error(`Could not locate ${label} anchor; pinned upstream shape changed.`);
  if (src.indexOf(anchor, first + anchor.length) >= 0) throw new Error(`${label} anchor is ambiguous.`);
  src = src.slice(0, first) + insertion + src.slice(first);
  writeFileSync(path, src);
  console.log(`==> Applied Cosmic ${label}`);
}

function installCosmicOverlay(cosmicDir) {
  const overlay = join(repoRoot, 'patches/cosmic/overlay/src/main/java/server/bots');
  const target = join(cosmicDir, 'src/main/java/server/bots');
  cpSync(overlay, target, { recursive: true });
  console.log('==> Installed Cosmic MapleBench control-plane sources');

  const combatPath = join(target, 'BotCombatManager.java');
  const combatAnchor = '    private static List<Integer> cachedAttackSkillIds(BotEntry entry) {';
  const combatMethod = `    /**\n     * MapleBench control primitive: execute exactly the requested attack rather\n     * than allowing the upstream bot policy to choose the highest-scoring skill.\n     * skillId == 0 means a normal/basic attack.\n     */\n    static boolean tryRequestedAttack(BotEntry entry, Character bot, Monster target, int skillId) {\n        AttackPlan attackPlan = skillId == 0\n                ? planBasicAttack(bot, target)\n                : planSkillAttack(entry, bot, target, skillId);\n        if (attackPlan == null || entry.attackCooldownMs > 0 || entry.noAmmo) return false;\n        if (!isTargetInAttackRange(attackPlan, bot, target)) return false;\n        if (attackPlan.skillId != 0 && !canUseSkill(bot, attackPlan.skillId, attackPlan.skillLevel)) return false;\n        if (!canUseAttackPlanNow(entry, BotAttackExecutionProvider.getEquippedWeaponType(bot), attackPlan)) return false;\n        attackMonster(entry, bot, attackPlan);\n        return true;\n    }\n\n`;
  insertBeforeOnce(combatPath, combatAnchor, combatMethod, 'tryRequestedAttack(', 'requested-attack hook');

  const managerPath = join(target, 'BotManager.java');
  const managerAnchor = '    public Character getBot(int ownerCharId) {';
  const managerMethod = `    /** MapleBench helper: find an already-active bot without exposing owner policy. */\n    BotEntry findActiveBotEntry(String botName) {\n        if (botName == null || botName.isBlank()) return null;\n        for (List<BotEntry> entries : bots.values()) {\n            for (BotEntry entry : entries) {\n                if (entry != null && entry.bot != null && entry.bot.getName().equalsIgnoreCase(botName)) {\n                    return entry;\n                }\n            }\n        }\n        return null;\n    }\n\n`;
  insertBeforeOnce(managerPath, managerAnchor, managerMethod, 'findActiveBotEntry(String botName)', 'active-bot lookup');

  const controlledTick = `    /** MapleBench: mechanics and requested navigation, with no autonomous policy. */
    private void tickMapleBench(BotEntry entry) {
        Character bot = entry.bot;
        if (bot == null || bot.getMap() == null || !bot.isAlive()) return;
        bot.getClient().updateLastPacket();
        BotCombatManager.tickMobDamage(entry, bot);
        BotCombatManager.tickActionLock(entry);
        if (!bot.isAlive() || tickActionLocked(entry)) return;
        if (entry.moveTarget != null) {
            tickStandaloneMoveTarget(entry, bot, consumeAiTick(entry));
        } else {
            entry.following = false;
            entry.grinding = false;
            tickIdleEntry(entry, bot);
        }
    }

`;
  insertBeforeOnce(managerPath, '    private void tickCore(BotEntry entry, int ownerCharId, int botCharId) {', controlledTick,
    'private void tickMapleBench(BotEntry entry)', 'policy-neutral mechanics tick');
  const tickAnchor = '        if (entry == null) return;\n        if (entry.airshowActive) return;';
  replaceOnce(managerPath, tickAnchor,
    '        if (entry == null) return;\n        if (MapleBenchRuntime.isControlled(entry.bot)) { tickMapleBench(entry); return; }\n        if (entry.airshowActive) return;', 'controlled-character tick dispatch');
  const chatAnchor = '        after(randMs(30_000, 31_000), () -> BotChatManager.checkBotStatus(entry, bot));';
  replaceOnce(managerPath, chatAnchor,
    '        if (!MapleBenchRuntime.isControlled(bot)) {\n    ' + chatAnchor + '\n        }', 'disable autonomous benchmark chat');

  const characterPath = join(cosmicDir, 'src/main/java/client/Character.java');
  const xpAnchor = '            totalExpGained += total;';
  const xpReplacement = `${xpAnchor}\n            server.bots.MapleBenchEventSink.recordXpGain(this, total);`;
  replaceOnce(characterPath, xpAnchor, xpReplacement, 'authoritative XP event hook');

  const serverPath = join(cosmicDir, 'src/main/java/net/server/Server.java');
  const mainAnchor = '        Server.getInstance().init();';
  const mainReplacement = `${mainAnchor}\n        server.bots.MapleBenchControlServer.startFromEnvironment();`;
  replaceOnce(serverPath, mainAnchor, mainReplacement, 'control-plane startup hook');
}

const cosmicDir = checkoutPinned('cosmic', lock.cosmic);
installCosmicOverlay(cosmicDir);
checkoutPinned('maplewright', lock.maplewright);

console.log(`\nUpstreams ready in ${upstreamRoot}`);
console.log('Cosmic bridge: MAPLEBENCH_ENABLED=true MAPLEBENCH_BOT_NAME=<bot> (port 8790 by default).');
console.log('Next visual milestone: build Maplewright with local v83 WZ files and connect its wsproxy to Cosmic.');
