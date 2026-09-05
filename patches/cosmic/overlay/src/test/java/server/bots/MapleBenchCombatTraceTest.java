package server.bots;

import client.Character;
import net.server.channel.handlers.AbstractDealDamageHandler.AttackTarget;
import org.junit.jupiter.api.Test;
import server.life.Monster;

import java.awt.Point;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class MapleBenchCombatTraceTest {
    @Test void retainsIndividualRollsWithoutConfusingOverkillWithHpLoss() {
        Monster mob = mock(Monster.class);
        when(mob.getPosition()).thenReturn(new Point(12, 167));
        when(mob.getHp()).thenReturn(0);
        String payload = MapleBenchCombatTrace.monsterPayload(4, 261020300, mob,
                8100, 4400, true, 8, new AttackTarget((short) 250, List.of(3900, 4200), Set.of(1)));
        assertTrue(payload.contains("\"damageLines\":[3900, 4200]"));
        assertTrue(payload.contains("\"criticalLines\":[1]"));
        assertTrue(payload.contains("\"hpLoss\":4400"));
        assertTrue(payload.contains("\"killed\":true"));
    }

    @Test void doesNotInventDamageLinesForUnattributedOrDelayedDamage() {
        Monster mob = mock(Monster.class);
        when(mob.getPosition()).thenReturn(new Point(12, 167));
        when(mob.getHp()).thenReturn(90);
        String payload = MapleBenchCombatTrace.monsterPayload(4, 1, mob, 10, 100, false, -1, null);
        assertTrue(payload.contains("\"damageLines\":[]"));
        assertTrue(payload.contains("\"hpLoss\":10"));
        assertTrue(payload.contains("\"killed\":false"));
    }

    @Test void preservesMissAndStanceOutcomeRatherThanInferringKnockbackFromDamage() {
        Character bot = mock(Character.class);
        BotEntry entry = new BotEntry(bot, null, null);
        when(bot.getHp()).thenReturn(8000);
        entry.mobHitCooldownMs = 1400;
        String miss = MapleBenchCombatTrace.playerPayload(entry, "touch", null, 0, 8000, new Point(), false);
        assertTrue(miss.contains("\"miss\":true"));
        assertTrue(miss.contains("\"knockback\":false"));
        when(bot.getHp()).thenReturn(7950); // Net HP can differ from the roll (e.g. ordinary autopot).
        String hit = MapleBenchCombatTrace.playerPayload(entry, "touch", null, 250, 8000, new Point(), false);
        assertTrue(hit.contains("\"damage\":250"));
        assertTrue(hit.contains("\"hpAfter\":7950"));
        assertTrue(hit.contains("\"knockback\":false"));
        assertTrue(hit.contains("\"hurtCooldownMs\":1400"));
    }

    @Test void airborneRecoilKeepsAuthoritativeFacingAndInterruptedAttackLock() {
        BotEntry entry = new BotEntry(mock(Character.class), null, null);
        entry.inAir = true;
        entry.facingDir = -1;
        entry.mapleBenchAction = "brandish1";
        entry.attackCooldownMs = 0;
        String motion = MapleBenchCombatTrace.motionJson(entry);
        assertTrue(motion.contains("\"inAir\":true"));
        assertTrue(motion.contains("\"facingLeft\":true"));
        assertTrue(motion.contains("\"attackCooldownMs\":0"));
    }
}
