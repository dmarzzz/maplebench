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
  cpSync(join(repoRoot, 'patches/cosmic/overlay/src/test/java/server/bots'),
    join(cosmicDir, 'src/test/java/server/bots'), { recursive: true });
  console.log('==> Installed Cosmic MapleBench control-plane sources');

  const combatPath = join(target, 'BotCombatManager.java');
  const combatAnchor = '    private static List<Integer> cachedAttackSkillIds(BotEntry entry) {';
  const combatMethod = `    /**\n     * MapleBench control primitive: execute exactly the requested attack rather\n     * than allowing the upstream bot policy to choose the highest-scoring skill.\n     * skillId == 0 means a normal/basic attack.\n     */\n    static boolean tryRequestedAttack(BotEntry entry, Character bot, Monster target, int skillId) {\n        AttackPlan attackPlan = skillId == 0\n                ? planBasicAttack(bot, target)\n                : planSkillAttack(entry, bot, target, skillId);\n        if (attackPlan == null || entry.attackCooldownMs > 0 || entry.noAmmo) return false;\n        if (!isTargetInAttackRange(attackPlan, bot, target)) return false;\n        if (attackPlan.skillId != 0 && !canUseSkill(bot, attackPlan.skillId, attackPlan.skillLevel)) return false;\n        if (!canUseAttackPlanNow(entry, BotAttackExecutionProvider.getEquippedWeaponType(bot), attackPlan)) return false;\n        attackMonster(entry, bot, attackPlan);\n        return true;\n    }\n\n`;
  insertBeforeOnce(combatPath, combatAnchor, combatMethod, 'tryRequestedAttack(', 'requested-attack hook');

  // Read-only combat telemetry hooks; shared player attack handlers stay intact.
  const entryPath = join(target, 'BotEntry.java');
  insertBeforeOnce(entryPath, '    // Physics', `    volatile String mapleBenchAction = "";
    volatile long mapleBenchAttackAtMs = 0;

`, 'volatile String mapleBenchAction', 'combat observation fields');
  insertBeforeOnce(combatPath, '        boolean hasHitBox() {', `        String mapleBenchAction = "";
        AttackPlan withMapleBenchAction(String action) {
            this.mapleBenchAction = action;
            return this;
        }

`, 'AttackPlan withMapleBenchAction', 'selected action name');
  const basicAction = 'damageWeaponTypeForAction(0, BotAttackExecutionProvider.getEquippedWeaponType(bot), basicAttackData.action()));';
  replaceOnce(combatPath, basicAction, basicAction.slice(0, -1) + '.withMapleBenchAction(basicAttackData.action());', 'basic action metadata');
  const skillAction = 'damageWeaponTypeForAction(skillId, weaponType, action));';
  replaceOnce(combatPath, skillAction, skillAction.slice(0, -1) + '.withMapleBenchAction(action);', 'skill action metadata');
  replaceOnce(combatPath, '        BotAttackExecutionProvider.applyAttackRoute(attackPlan.route, attack, bot);',
    `        MapleBenchCombatTrace.beginAttack(entry, attackPlan, attack);
        try {
            BotAttackExecutionProvider.applyAttackRoute(attackPlan.route, attack, bot);
        } finally {
            MapleBenchCombatTrace.endAttack();
        }`, 'attack trace scope');
  const mobHit = '        applyDamage(entry, bot, dmg, -1, mob.getId(), kb.direction(), kb.airVelX());';
  replaceOnce(combatPath, '        int dmg = rollPhysicalMobDamage(bot, mob);',
    '        int dmg = MapleBenchDefense.contactDamage(bot, rollPhysicalMobDamage(bot, mob));', 'learned Achilles contact mitigation');
  replaceOnce(combatPath, mobHit, `        int hpBefore = bot.getHp();
        Point hitPosition = new Point(bot.getPosition());
        boolean knockedBack = applyDamage(entry, bot, dmg, -1, mob.getId(), kb.direction(), kb.airVelX());
        MapleBenchCombatTrace.playerHit(entry, "touch", mob, dmg, hpBefore, hitPosition, knockedBack);`, 'touch damage trace');
  const fallHit = '        applyDamage(entry, bot, dmg, -3, 0, 0, airVelX);';
  replaceOnce(combatPath, fallHit, `        int hpBefore = bot.getHp();
        Point hitPosition = new Point(bot.getPosition());
        boolean knockedBack = applyDamage(entry, bot, dmg, -3, 0, 0, airVelX);
        MapleBenchCombatTrace.playerHit(entry, "fall", null, dmg, hpBefore, hitPosition, knockedBack);`, 'fall damage trace');
  // Report the existing Stance/rope/death decision without re-rolling it.
  let combat = readFileSync(combatPath, 'utf8');
  if (!combat.includes('private static boolean applyDamage(')) {
    const begin = combat.indexOf('    private static void applyDamage(');
    const end = combat.indexOf('    private static int rollPhysicalMobDamage(', begin);
    if (begin < 0 || end < 0) throw new Error('Could not locate applyDamage result hook');
    const method = combat.slice(begin, end).replace('private static void applyDamage(', 'private static boolean applyDamage(')
      .replaceAll('            return;', '            return false;')
      .replace('        BotMovementManager.broadcastMovement(entry);', '        BotMovementManager.broadcastMovement(entry);\n        return true;');
    writeFileSync(combatPath, combat.slice(0, begin) + method + combat.slice(end));
  }
  const mapPath = join(cosmicDir, 'src/main/java/server/maps/MapleMap.java');
  replaceOnce(mapPath, '        boolean killed = monster.damage(chr, damage, false);',
    `        int mapleBenchHpBefore = monster.getHp();
        boolean killed = monster.damage(chr, damage, false);
        server.bots.MapleBenchCombatTrace.monsterHit(chr, monster, damage, mapleBenchHpBefore, killed);`, 'applied monster damage trace');

  replaceOnce(join(cosmicDir, 'src/main/java/server/maps/MapFactory.java'),
    '        AbstractLoadedLife myLife = loadLife(id, type, cy, f, fh, rx0, rx1, x, y, hide);',
    `        if ("m".equals(type) && server.bots.MapleBenchRuntime.excludeInitialSpawn(map.getId(), id, mobTime)) return;
        AbstractLoadedLife myLife = loadLife(id, type, cy, f, fh, rx0, rx1, x, y, hide);`, 'declared one-shot fixture exclusions');

  const formulaPath = join(cosmicDir, 'src/main/java/server/combat/CombatFormulaProvider.java');
  replaceOnce(formulaPath, '            case 130 -> WeaponType.SWORD1H;',
    '            case 130 -> WeaponType.SWORD1H;\n            case 140 -> WeaponType.SWORD2H;', 'two-handed sword mastery');
  insertBeforeOnce(combatPath, '    private static List<Integer> cachedAttackSkillIds(BotEntry entry) {',
    `    /** Execute one explicitly requested learned self buff through SPECIAL_MOVE. */
    static boolean tryRequestedBuff(BotEntry entry, Character bot, int skillId) {
        var definition = MapleBenchSkills.definition(skillId);
        if (definition == null || !definition.selfBuff() || MapleBenchSkills.blocked(entry, skillId) != null) return false;
        Skill skill = SkillFactory.getSkill(skillId);
        int hpBefore = bot.getHp(), mpBefore = bot.getMp();
        if (!castSupportSkill(entry, bot, skill, skill.getEffect(bot.getSkillLevel(skill)), System.currentTimeMillis())) return false;
        if (!MapleBenchSkills.active(bot, skillId)) return false;
        String action = BotAttackExecutionProvider.resolveSkillAttackAction(bot, skill, bot.getSkillLevel(skill),
                BotAttackExecutionProvider.getEquippedWeaponType(bot));
        MapleBenchCombatTrace.buffCast(entry, skillId, action, hpBefore, mpBefore);
        return true;
    }

`, 'static boolean tryRequestedBuff(', 'explicit buff control');

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
  replaceOnce(managerPath, '    private void tickMapleBench(BotEntry entry) {',
    '    private void tickMapleBench(BotEntry entry) {\n        if (MapleBenchRuntime.isStaged()) return;', 'staged episode opening');
  const tickAnchor = '        if (entry == null) return;\n        if (entry.airshowActive) return;';
  replaceOnce(managerPath, tickAnchor,
    '        if (entry == null) return;\n        if (MapleBenchRuntime.isControlled(entry.bot)) { tickMapleBench(entry); return; }\n        if (entry.airshowActive) return;', 'controlled-character tick dispatch');
  const chatAnchor = '        after(randMs(30_000, 31_000), () -> BotChatManager.checkBotStatus(entry, bot));';
  replaceOnce(managerPath, chatAnchor,
    '        if (!MapleBenchRuntime.isControlled(bot)) {\n    ' + chatAnchor + '\n        }', 'disable autonomous benchmark chat');

  const characterPath = join(cosmicDir, 'src/main/java/client/Character.java');
  const xpAnchor = '            totalExpGained += total;';
  const xpReplacement = `${xpAnchor}\n            server.bots.MapleBenchEventSink.recordXpGain(this, total);`;
  if (!readFileSync(characterPath, 'utf8').includes('MapleBenchEventSink.recordXpGain(this, total)'))
    replaceOnce(characterPath, xpAnchor, xpReplacement, 'authoritative XP event hook');

  // XP-window protocol: instrument the settled outer transaction. Recursive
  // overflow gains and level-up arithmetic are nested and cannot be double counted.
  function wrapXpMethod(signature, nextSignature, kind) {
    const source = readFileSync(characterPath, 'utf8');
    const begin = source.indexOf(signature), end = source.indexOf(nextSignature, begin + signature.length);
    if (begin < 0 || end < 0) throw new Error('Missing pinned XP method boundary');
    const block = source.slice(begin, end);
    if (block.includes('MapleBenchXpLedger.Mutation maplebenchXpMutation')) return;
    const open = block.indexOf('{'), close = block.lastIndexOf('\n    }');
    if (open < 0 || close <= open || block.slice(close + 6).trim()) throw new Error('Ambiguous pinned XP method boundary');
    const body = block.slice(open + 1, close);
    const wrapped = block.slice(0, open + 1)
      + `\n        server.bots.MapleBenchXpLedger.Mutation maplebenchXpMutation = server.bots.MapleBenchXpLedger.begin(getId(), getAccountID(), level, exp.get(), "${kind}");\n        try {`
      + body.split('\n').map(line => line ? '    ' + line : line).join('\n')
      + '\n        } finally {\n            if (maplebenchXpMutation != null) server.bots.MapleBenchXpLedger.end(maplebenchXpMutation, level, exp.get(), getWorldServer().getExpRate());\n        }'
      + block.slice(close);
    writeFileSync(characterPath, source.slice(0, begin) + wrapped + source.slice(end));
  }
  replaceOnce(characterPath, '    public void setExp(int amount) {',
    '    public synchronized void setExp(int amount) {', 'serialize XP setters with XP/save transactions');
  replaceOnce(characterPath, '    public void setLevel(int level) {',
    '    public synchronized void setLevel(int level) {', 'serialize level setters with XP/save transactions');
  wrapXpMethod('    private synchronized void gainExpInternal(', '    private Pair<Integer, Integer> applyFame(', 'xp_transaction');
  wrapXpMethod('    public synchronized void levelUp(', '    public boolean leaveParty(', 'level_up');
  wrapXpMethod('    public synchronized void setExp(', '    public void setGachaExp(', 'set_exp');
  wrapXpMethod('    public synchronized void setLevel(', '    public void setMap(', 'set_level');

  // Bind receipts to the real transaction, never a client acknowledgement or
  // the account's offline flag. The anchor is specific to saveCharToDB and must
  // not instrument character creation or an unrelated transaction.
  const saveAnchor = `                if (storage != null && usedStorage) {
                    storage.saveToDB(con);
                    usedStorage = false;
                }

                con.commit();`;
  if (readFileSync(characterPath, 'utf8').includes('server.bots.MapleBenchPersistence.committed(getId(), getAccountID());')) replaceOnce(characterPath,
    'server.bots.MapleBenchPersistence.committed(getId(), getAccountID());',
    'server.bots.MapleBenchPersistence.committed(getId(), getAccountID(), level, Math.abs(exp.get()), getWorldServer().getExpRate());',
    'XP-aware committed save receipt');
  replaceOnce(characterPath, saveAnchor,
    `${saveAnchor}\n                server.bots.MapleBenchPersistence.committed(getId(), getAccountID(), level, Math.abs(exp.get()), getWorldServer().getExpRate());`,
    'positive character-save receipt');
  const saveFailureAnchor = '            log.error("Error saving chr {}, level: {}, job: {}", name, level, job.getId(), e);';
  replaceOnce(characterPath, saveFailureAnchor,
    `${saveFailureAnchor}\n            server.bots.MapleBenchPersistence.failed(getId(), getAccountID());`,
    'failed character-save receipt');

  const serverPath = join(cosmicDir, 'src/main/java/net/server/Server.java');
  const mainAnchor = '        Server.getInstance().init();';
  const mainReplacement = `${mainAnchor}\n        server.bots.MapleBenchControlServer.startFromEnvironment();`;
  replaceOnce(serverPath, mainAnchor, mainReplacement, 'control-plane startup hook');
  const oldPersistenceStartup = `        server.bots.MapleBenchPersistence.initializeFromEnvironment();\n${mainAnchor}`;
  const xpStartup = `        server.bots.MapleBenchPersistence.initializeFromEnvironment();\n        server.bots.MapleBenchXpLedger.initializeFromEnvironment();\n${mainAnchor}`;
  replaceOnce(serverPath, readFileSync(serverPath, 'utf8').includes(oldPersistenceStartup) ? oldPersistenceStartup : mainAnchor,
    xpStartup, 'persistence and XP ledger startup');
}

const patchOnly = process.argv.includes('--patch-only');
const cosmicDir = patchOnly ? join(upstreamRoot, 'cosmic') : checkoutPinned('cosmic', lock.cosmic);
installCosmicOverlay(cosmicDir);
if (!patchOnly) checkoutPinned('maplewright', lock.maplewright);

console.log(`\nUpstreams ready in ${upstreamRoot}`);
console.log('Cosmic bridge: MAPLEBENCH_ENABLED=true MAPLEBENCH_BOT_NAME=<bot> (port 8790 by default).');
console.log('Next visual milestone: build Maplewright with local v83 WZ files and connect its wsproxy to Cosmic.');
