package server.bots;

import client.BuffStat;
import client.Character;
import client.SkillFactory;
import client.inventory.InventoryType;
import constants.skills.Crusader;
import constants.skills.Fighter;
import constants.skills.Hero;
import constants.skills.Warrior;
import server.combat.CombatFormulaProvider;

import java.util.List;

/** Agent-visible skills and buff state. No autonomous casts or automatic buff renewal. */
final class MapleBenchSkills {
    record Definition(int id, String name, boolean selfBuff, boolean finisher) {}
    static final List<Definition> DEFINITIONS = List.of(
            new Definition(Warrior.POWER_STRIKE, "Power Strike", false, false),
            new Definition(Warrior.SLASH_BLAST, "Slash Blast", false, false),
            new Definition(Hero.BRANDISH, "Brandish", false, false),
            new Definition(Crusader.SWORD_PANIC, "Panic", false, true),
            new Definition(Crusader.SWORD_COMA, "Coma", false, true),
            new Definition(Crusader.COMBO, "Combo Attack", true, false),
            new Definition(Fighter.SWORD_BOOSTER, "Sword Booster", true, false),
            new Definition(Fighter.RAGE, "Rage", true, false),
            new Definition(Hero.STANCE, "Power Stance", true, false),
            new Definition(Hero.MAPLE_WARRIOR, "Maple Warrior", true, false));

    private MapleBenchSkills() {}

    static Definition definition(int id) {
        return DEFINITIONS.stream().filter(d -> d.id == id).findFirst().orElse(null);
    }

    static int comboOrbs(Character bot) {
        Integer value = bot.getBuffedValue(BuffStat.COMBO);
        return value == null ? 0 : Math.max(0, value - 1);
    }

    static boolean active(Character bot, int id) {
        return bot.getAllBuffs().stream().anyMatch(h -> h.effect.getSourceId() == id);
    }

    static String blocked(BotEntry entry, int skillId) {
        Character bot = entry.bot;
        if (!bot.isAlive()) return "character is dead";
        if (entry.attackCooldownMs > 0) return "action animation is still locked";
        if (skillId == 0) return null;
        Definition definition = definition(skillId);
        var skill = SkillFactory.getSkill(skillId);
        int level = skill == null ? 0 : bot.getSkillLevel(skill);
        if (definition == null || level <= 0) return "skill is not in the learned benchmark kit";
        if (bot.skillIsCooling(skillId)) return "skill is cooling down";
        if (!skill.getEffect(level).canPaySkillCost(bot)) return "insufficient HP or MP";
        if (definition.finisher && comboOrbs(bot) < 1) return "finisher requires a charged combo orb";
        return null;
    }

    static String characterJson(Character bot) {
        Integer combo = bot.getBuffedValue(BuffStat.COMBO);
        int advanced = bot.getSkillLevel(Hero.ADVANCED_COMBO);
        int comboLevel = bot.getSkillLevel(Crusader.COMBO);
        int maxOrbs = advanced > 0 ? SkillFactory.getSkill(Hero.ADVANCED_COMBO).getEffect(advanced).getX()
                : comboLevel > 0 ? SkillFactory.getSkill(Crusader.COMBO).getEffect(comboLevel).getX() : 0;
        return "\"combo\":{\"active\":" + (combo != null) + ",\"orbs\":" + comboOrbs(bot)
                + ",\"maxOrbs\":" + maxOrbs + "},\"combatStats\":{\"weaponAttack\":" + bot.getTotalWatk()
                + ",\"physicalMastery\":" + CombatFormulaProvider.getInstance().resolvePhysicalMastery(bot)
                + ",\"weaponDefense\":" + bot.getTotalWdef()
                + ",\"str\":" + bot.getTotalStr() + ",\"dex\":" + bot.getTotalDex()
                + ",\"achillesLevel\":" + bot.getSkillLevel(Hero.ACHILLES)
                + ",\"contactDamagePermille\":" + MapleBenchDefense.achillesDamagePermille(bot) + "},\"equipment\":"
                + bot.getInventory(InventoryType.EQUIPPED).list().stream()
                .sorted(java.util.Comparator.comparingInt(item -> item.getPosition()))
                .map(item -> "{\"itemId\":" + item.getItemId() + ",\"slot\":" + item.getPosition() + "}")
                .collect(java.util.stream.Collectors.joining(",", "[", "]"));
    }

    static String observeJson(BotEntry entry) {
        Character bot = entry.bot;
        StringBuilder out = new StringBuilder("[");
        boolean first = true;
        for (Definition d : DEFINITIONS) {
            var skill = SkillFactory.getSkill(d.id);
            int level = skill == null ? 0 : bot.getSkillLevel(skill);
            if (level <= 0) continue;
            var effect = skill.getEffect(level);
            boolean active = active(bot, d.id);
            int remaining = bot.getAllBuffs().stream().filter(h -> h.effect.getSourceId() == d.id)
                    .mapToInt(h -> Math.max(0, h.effect.getDuration() - h.usedTime)).max().orElse(0);
            if (!first) out.append(','); first = false;
            String blocked = blocked(entry, d.id);
            out.append("{\"skillId\":").append(d.id).append(",\"name\":").append(MapleBenchJson.quote(d.name))
                    .append(",\"level\":").append(level)
                    .append(",\"selfBuff\":").append(d.selfBuff).append(",\"finisher\":").append(d.finisher)
                    .append(",\"hpCost\":").append(effect.getHpCon()).append(",\"mpCost\":").append(effect.getMpCon())
                    .append(",\"maxTargets\":").append(effect.getMobCount()).append(",\"damagePercent\":").append(effect.getDamage())
                    .append(",\"active\":").append(active).append(",\"remainingMs\":").append(remaining)
                    .append(",\"ready\":").append(blocked == null)
                    .append(",\"blockedReason\":").append(blocked == null ? "null" : MapleBenchJson.quote(blocked)).append('}');
        }
        return out.append(']').toString();
    }
}
