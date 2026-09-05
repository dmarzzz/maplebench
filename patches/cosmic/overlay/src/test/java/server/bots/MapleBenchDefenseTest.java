package server.bots;

import client.BuffStat;
import client.Character;
import client.Job;
import client.Skill;
import client.SkillFactory;
import constants.skills.Hero;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;
import server.StatEffect;
import server.bots.combat.BotDefenseDataProvider;
import server.life.Monster;
import server.maps.MapleMap;

import java.awt.Point;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class MapleBenchDefenseTest {
    @Test void learnedAchillesUsesItsWzEffectAndPlayerRounding() {
        Character bot = mock(Character.class);
        Skill skill = mock(Skill.class);
        StatEffect effect = mock(StatEffect.class);
        when(bot.getJob()).thenReturn(Job.HERO);
        when(bot.getSkillLevel(skill)).thenReturn((byte) 30);
        when(skill.getEffect(30)).thenReturn(effect);
        when(effect.getX()).thenReturn(850);
        try (MockedStatic<SkillFactory> factory = mockStatic(SkillFactory.class);
             MockedStatic<MapleBenchRuntime> runtime = mockStatic(MapleBenchRuntime.class)) {
            factory.when(() -> SkillFactory.getSkill(Hero.ACHILLES)).thenReturn(skill);
            runtime.when(() -> MapleBenchRuntime.isControlled(bot)).thenReturn(true);
            assertEquals(850, MapleBenchDefense.achillesDamagePermille(bot));
            assertEquals(1981, MapleBenchDefense.contactDamage(bot, 2331));
            assertEquals(0, MapleBenchDefense.contactDamage(bot, 1));
            assertEquals(0, MapleBenchDefense.contactDamage(bot, 0));
            when(effect.getX()).thenReturn(925);
            assertEquals(2156, MapleBenchDefense.contactDamage(bot, 2331));
        }
    }

    @Test void unlearnedAndOtherJobsKeepTheirDamage() {
        Character bot = mock(Character.class);
        Skill skill = mock(Skill.class);
        when(bot.getJob()).thenReturn(Job.HERO);
        try (MockedStatic<SkillFactory> factory = mockStatic(SkillFactory.class);
             MockedStatic<MapleBenchRuntime> runtime = mockStatic(MapleBenchRuntime.class)) {
            factory.when(() -> SkillFactory.getSkill(Hero.ACHILLES)).thenReturn(skill);
            runtime.when(() -> MapleBenchRuntime.isControlled(bot)).thenReturn(true);
            assertEquals(1000, MapleBenchDefense.achillesDamagePermille(bot));
            assertEquals(2331, MapleBenchDefense.contactDamage(bot, 2331));
            when(bot.getJob()).thenReturn(Job.BISHOP);
            assertEquals(1000, MapleBenchDefense.achillesDamagePermille(bot));
            assertEquals(2331, MapleBenchDefense.contactDamage(bot, 2331));
            verify(skill, never()).getEffect(anyInt());
        }
    }

    @Test void ordinaryBotsStayOutsideTheBenchmarkHook() {
        Character bot = mock(Character.class);
        try (MockedStatic<MapleBenchRuntime> runtime = mockStatic(MapleBenchRuntime.class)) {
            runtime.when(() -> MapleBenchRuntime.isControlled(bot)).thenReturn(false);
            assertEquals(2331, MapleBenchDefense.contactDamage(bot, 2331));
            verify(bot, never()).getJob();
        }
    }

    @Test void contactHpAndTraceUseReducedDamageWhileFallDamageStaysUnmodified() {
        Character bot = mock(Character.class);
        Monster mob = mock(Monster.class);
        MapleMap map = mock(MapleMap.class);
        Skill skill = mock(Skill.class);
        StatEffect effect = mock(StatEffect.class);
        BotDefenseDataProvider defense = mock(BotDefenseDataProvider.class);
        AtomicInteger hp = new AtomicInteger(10000);
        BotEntry entry = new BotEntry(bot, null, null);
        when(bot.getPosition()).thenReturn(new Point(100, 260));
        when(mob.getPosition()).thenReturn(new Point(120, 260));
        when(bot.getMap()).thenReturn(map);
        when(bot.getJob()).thenReturn(Job.HERO);
        when(bot.getHp()).thenAnswer(ignored -> hp.get());
        when(bot.getBuffedValue(BuffStat.STANCE)).thenReturn(100);
        doAnswer(call -> { hp.addAndGet(call.getArgument(0)); return null; })
                .when(bot).addMPHPAndTriggerAutopot(anyInt(), anyInt());
        when(bot.getSkillLevel(skill)).thenReturn((byte) 30);
        when(skill.getEffect(30)).thenReturn(effect);
        when(effect.getX()).thenReturn(850);
        when(defense.rollPhysicalTouchDamage(bot, mob)).thenReturn(2331);
        try (MockedStatic<SkillFactory> factory = mockStatic(SkillFactory.class);
             MockedStatic<MapleBenchRuntime> runtime = mockStatic(MapleBenchRuntime.class);
             MockedStatic<BotDefenseDataProvider> provider = mockStatic(BotDefenseDataProvider.class);
             MockedStatic<BotManager> scheduling = mockStatic(BotManager.class);
             MockedStatic<MapleBenchEventSink> events = mockStatic(MapleBenchEventSink.class)) {
            factory.when(() -> SkillFactory.getSkill(Hero.ACHILLES)).thenReturn(skill);
            runtime.when(() -> MapleBenchRuntime.isControlled(bot)).thenReturn(true);
            provider.when(BotDefenseDataProvider::getInstance).thenReturn(defense);
            events.when(() -> MapleBenchEventSink.records(bot)).thenReturn(true);

            BotCombatManager.applyMobHit(entry, bot, mob);
            assertEquals(8019, hp.get());
            verify(bot).addMPHPAndTriggerAutopot(-1981, 0);
            events.verify(() -> MapleBenchEventSink.appendPayload(argThat(payload ->
                    payload.contains("\"source\":\"touch\"") && payload.contains("\"damage\":1981")
                            && payload.contains("\"hpBefore\":10000") && payload.contains("\"hpAfter\":8019"))));

            entry.mobHitCooldownMs = 0;
            int fallDamage = BotCombatManager.fallDamageFromDistance(1132);
            BotCombatManager.applyFallDamage(entry, bot, 1132);
            assertEquals(8019 - fallDamage, hp.get());
            verify(bot).addMPHPAndTriggerAutopot(-fallDamage, 0);
            events.verify(() -> MapleBenchEventSink.appendPayload(argThat(payload ->
                    payload.contains("\"source\":\"fall\"") && payload.contains("\"damage\":" + fallDamage))));
        }
    }
}
