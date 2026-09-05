package server.bots;

import client.BuffStat;
import client.Character;
import client.Job;
import client.Skill;
import client.SkillFactory;
import client.inventory.Inventory;
import client.inventory.InventoryType;
import client.inventory.Item;
import constants.skills.Crusader;
import constants.skills.Fighter;
import constants.skills.Hero;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;
import org.mockito.Mockito;
import server.StatEffect;
import server.combat.CombatFormulaProvider;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class MapleBenchSkillsTest {
    @Test void twoHandedSwordUsesLearnedSwordMastery() {
        Character bot = mock(Character.class);
        Inventory equipped = mock(Inventory.class);
        Item sword = mock(Item.class);
        when(bot.getInventory(InventoryType.EQUIPPED)).thenReturn(equipped);
        when(equipped.getItem((short) -11)).thenReturn(sword);
        when(sword.getItemId()).thenReturn(1402037);
        when(bot.getJob()).thenReturn(Job.HERO);
        when(bot.getSkillLevel(Fighter.SWORD_MASTERY)).thenReturn(20);
        Skill skill = mock(Skill.class);
        StatEffect effect = mock(StatEffect.class);
        when(skill.getEffect(20)).thenReturn(effect);
        when(effect.getMastery()).thenReturn(10);
        try (MockedStatic<SkillFactory> factory = Mockito.mockStatic(SkillFactory.class)) {
            factory.when(() -> SkillFactory.getSkill(Fighter.SWORD_MASTERY)).thenReturn(skill);
            assertEquals(.6, CombatFormulaProvider.getInstance().resolvePhysicalMastery(bot), 1e-9);
            when(bot.getSkillLevel(Fighter.SWORD_MASTERY)).thenReturn(0);
            assertEquals(.1, CombatFormulaProvider.getInstance().resolvePhysicalMastery(bot), 1e-9);
        }
    }

    @Test void finisherNeedsChargeAndCannotBypassActionLockOrCost() {
        Character bot = mock(Character.class);
        BotEntry entry = new BotEntry(bot, null, null);
        Skill skill = mock(Skill.class);
        StatEffect effect = mock(StatEffect.class);
        when(bot.isAlive()).thenReturn(true);
        when(bot.getSkillLevel(skill)).thenReturn((byte) 30);
        when(skill.getEffect(30)).thenReturn(effect);
        when(effect.canPaySkillCost(bot)).thenReturn(true);
        try (MockedStatic<SkillFactory> factory = Mockito.mockStatic(SkillFactory.class)) {
            factory.when(() -> SkillFactory.getSkill(Crusader.SWORD_COMA)).thenReturn(skill);
            when(bot.getBuffedValue(BuffStat.COMBO)).thenReturn(1);
            assertEquals("finisher requires a charged combo orb", MapleBenchSkills.blocked(entry, Crusader.SWORD_COMA));
            when(bot.getBuffedValue(BuffStat.COMBO)).thenReturn(2);
            assertNull(MapleBenchSkills.blocked(entry, Crusader.SWORD_COMA));
            entry.attackCooldownMs = 100;
            assertEquals("action animation is still locked", MapleBenchSkills.blocked(entry, Crusader.SWORD_COMA));
            entry.attackCooldownMs = 0;
            when(effect.canPaySkillCost(bot)).thenReturn(false);
            assertEquals("insufficient HP or MP", MapleBenchSkills.blocked(entry, Crusader.SWORD_COMA));
        }
    }

    @Test void selfBuffCatalogCannotExposePassiveOrUnvalidatedSkills() {
        assertTrue(MapleBenchSkills.definition(Hero.STANCE).selfBuff());
        assertTrue(MapleBenchSkills.definition(Crusader.COMBO).selfBuff());
        assertFalse(MapleBenchSkills.definition(Hero.BRANDISH).selfBuff());
        assertNull(MapleBenchSkills.definition(Hero.ADVANCED_COMBO));
        assertNull(MapleBenchSkills.definition(Hero.RUSH));
        assertNull(MapleBenchSkills.definition(9001000));
    }

    @Test void potionWhitelistKeepsLargeHpAndManaItemsFiniteAndExplicit() {
        assertTrue(MapleBenchItems.supported(MapleBenchItems.ICE_CREAM_POP));
        assertTrue(MapleBenchItems.supported(2000006));
        assertFalse(MapleBenchItems.supported(2000005));
        assertFalse(MapleBenchItems.supported(2030000));
    }
}
