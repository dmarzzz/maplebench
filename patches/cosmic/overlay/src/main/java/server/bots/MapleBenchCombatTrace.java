package server.bots;

import client.Character;
import net.server.channel.handlers.AbstractDealDamageHandler.AttackInfo;
import net.server.channel.handlers.AbstractDealDamageHandler.AttackTarget;
import server.life.Monster;

import java.awt.Point;
import java.util.List;

/** Read-only hooks around ordinary combat. No damage, timing, or movement simulation. */
public final class MapleBenchCombatTrace {
    private record AttackContext(long id, int characterId, AttackInfo attack) {}
    private static final ThreadLocal<AttackContext> CURRENT = new ThreadLocal<>();

    private MapleBenchCombatTrace() {}

    static void beginAttack(BotEntry entry, BotCombatManager.AttackPlan plan, AttackInfo attack) {
        if (!MapleBenchEventSink.records(entry.bot)) return;
        entry.mapleBenchAction = plan.mapleBenchAction;
        entry.mapleBenchAttackAtMs = MapleBenchEventSink.elapsedMs();
        long id = MapleBenchEventSink.appendPayload("\"kind\":\"combat_attack\",\"characterId\":" + entry.bot.getId()
                + ",\"mapId\":" + entry.bot.getMapId() + ",\"skillId\":" + plan.skillId
                + ",\"actionName\":" + MapleBenchJson.quote(plan.mapleBenchAction)
                + ",\"cooldownMs\":" + plan.cooldownMs + ",\"hitDelayMs\":" + plan.hitDelayMs
                + ",\"speed\":" + plan.speed + ",\"facingLeft\":" + ((plan.stance & 1) != 0));
        CURRENT.set(new AttackContext(id, entry.bot.getId(), attack));
    }

    static void endAttack() { CURRENT.remove(); }

    /** Called immediately after MapleMap applies damage, before object disposal or XP. */
    public static void monsterHit(Character source, Monster target, int damage, int hpBefore, boolean killed) {
        if (!MapleBenchEventSink.records(source)) return;
        AttackContext context = CURRENT.get();
        AttackTarget rolls = context != null && context.characterId == source.getId()
                ? context.attack.targets.get(target.getObjectId()) : null;
        long attackId = rolls == null ? -1 : context.id;
        MapleBenchEventSink.appendPayload(monsterPayload(source.getId(), source.getMapId(), target,
                damage, hpBefore, killed, attackId, rolls));
    }

    static String monsterPayload(int characterId, int mapId, Monster target, int damage, int hpBefore,
                                 boolean killed, long attackId, AttackTarget rolls) {
        int hpAfter = Math.max(0, target.getHp());
        // Damage lines are the packet's rolls, including overkill. HP loss is measured separately.
        List<Integer> lines = rolls == null ? List.of() : rolls.damageLines();
        List<Integer> critical = rolls == null ? List.of() : rolls.critLineIndices().stream().sorted().toList();
        return "\"kind\":\"monster_hit\",\"characterId\":" + characterId + ",\"mapId\":" + mapId
                + ",\"attackId\":" + attackId + ",\"objectId\":" + target.getObjectId()
                + ",\"monsterId\":" + target.getId() + ",\"position\":" + point(target.getPosition())
                + ",\"damage\":" + damage + ",\"damageLines\":" + lines + ",\"criticalLines\":" + critical
                + ",\"hpBefore\":" + hpBefore + ",\"hpAfter\":" + hpAfter
                + ",\"hpLoss\":" + Math.max(0, hpBefore - hpAfter) + ",\"killed\":" + killed;
    }

    static void playerHit(BotEntry entry, String source, Monster mob, int damage, int hpBefore,
                          Point position, boolean knockedBack) {
        if (!MapleBenchEventSink.records(entry.bot)) return;
        MapleBenchEventSink.appendPayload(playerPayload(entry, source, mob, damage, hpBefore, position, knockedBack));
    }

    static String playerPayload(BotEntry entry, String source, Monster mob, int damage, int hpBefore,
                                Point position, boolean knockedBack) {
        return "\"kind\":\"player_hit\",\"characterId\":" + entry.bot.getId()
                + ",\"mapId\":" + entry.bot.getMapId() + ",\"source\":" + MapleBenchJson.quote(source)
                + ",\"objectId\":" + (mob == null ? 0 : mob.getObjectId())
                + ",\"monsterId\":" + (mob == null ? 0 : mob.getId())
                + ",\"position\":" + point(position) + ",\"damage\":" + Math.max(0, damage)
                + ",\"hpBefore\":" + hpBefore + ",\"hpAfter\":" + entry.bot.getHp()
                + ",\"miss\":" + (damage <= 0) + ",\"knockback\":" + knockedBack
                + ",\"hurtCooldownMs\":" + Math.max(0, entry.mobHitCooldownMs);
    }

    static String motionJson(BotEntry entry) {
        return "{\"inAir\":" + entry.inAir + ",\"climbing\":" + entry.climbing
                + ",\"swimming\":" + entry.swimming + ",\"crouching\":" + entry.crouching
                + ",\"facingLeft\":" + (entry.facingDir < 0) + ",\"moving\":" + entry.wasMovingX
                + ",\"moveIntent\":" + entry.moveDir
                + ",\"attackCooldownMs\":" + Math.max(0, entry.attackCooldownMs)
                + ",\"hurtCooldownMs\":" + Math.max(0, entry.mobHitCooldownMs)
                + ",\"actionName\":" + MapleBenchJson.quote(entry.mapleBenchAction)
                + ",\"attackAtMs\":" + entry.mapleBenchAttackAtMs + "}";
    }

    private static String point(Point p) { return "{\"x\":" + p.x + ",\"y\":" + p.y + "}"; }
}
