package server.bots;

import client.Character;
import client.Skill;
import client.SkillFactory;
import constants.skills.DarkKnight;
import constants.skills.Hero;
import constants.skills.Paladin;

/** The learned Achilles modifier normally applied by the player's TakeDamageHandler. */
final class MapleBenchDefense {
    private MapleBenchDefense() {}

    static int achillesDamagePermille(Character bot) {
        int skillId = switch (bot.getJob()) {
            case HERO -> Hero.ACHILLES;
            case PALADIN -> Paladin.ACHILLES;
            case DARKKNIGHT -> DarkKnight.ACHILLES;
            default -> 0;
        };
        if (skillId == 0) return 1000;
        Skill skill = SkillFactory.getSkill(skillId);
        int level = bot.getSkillLevel(skill);
        return level > 0 ? skill.getEffect(level).getX() : 1000;
    }

    static int contactDamage(Character bot, int damage) {
        if (damage <= 0 || !MapleBenchRuntime.isControlled(bot)) return damage;
        // Match TakeDamageHandler's compound assignment: multiply then truncate to int.
        return (int) (damage * (achillesDamagePermille(bot) / 1000.0));
    }
}
