package server.bots;

import client.Character;
import server.life.Monster;

import java.awt.Point;
import java.util.Comparator;
import java.util.List;

/** Policy-neutral adapter from MapleBench actions to ordinary Cosmic bot mechanics. */
final class MapleBenchController {
    record Result(boolean accepted, String error) {}

    private final String botName;
    private final BotManager botManager = BotManager.getInstance();

    MapleBenchController(String botName) {
        this.botName = botName;
    }

    BotEntry entry() {
        return botManager.findActiveBotEntry(botName);
    }

    String observeJson() {
        BotEntry entry = requireEntry();
        Character bot = entry.bot;
        MapleBenchEventSink.ensureStarted(bot);

        Point p = bot.getPosition();
        StringBuilder out = new StringBuilder(2048);
        out.append("{\"nowMs\":").append(MapleBenchEventSink.elapsedMs())
                .append(",\"character\":{")
                .append("\"id\":").append(bot.getId())
                .append(",\"name\":").append(MapleBenchJson.quote(bot.getName()))
                .append(",\"level\":").append(bot.getLevel())
                .append(",\"jobId\":").append(bot.getJob().getId())
                .append(",\"exp\":").append(bot.getExp())
                .append(",\"hp\":").append(bot.getHp())
                .append(",\"maxHp\":").append(bot.getCurrentMaxHp())
                .append(",\"mp\":").append(bot.getMp())
                .append(",\"maxMp\":").append(bot.getCurrentMaxMp())
                .append(",\"mesos\":").append(bot.getMeso())
                .append(",\"mapId\":").append(bot.getMapId())
                .append(",\"position\":{\"x\":").append(p.x).append(",\"y\":").append(p.y).append('}')
                .append(",\"alive\":").append(bot.isAlive())
                .append("},\"monsters\":[");

        List<Monster> monsters = bot.getMap().getAllMonsters().stream()
                .sorted(Comparator.comparingInt(Monster::getObjectId))
                .toList();
        boolean first = true;
        for (Monster mob : monsters) {
            Point mp = mob.getPosition();
            if (!first) out.append(',');
            first = false;
            out.append('{')
                    .append("\"objectId\":").append(mob.getObjectId())
                    .append(",\"monsterId\":").append(mob.getId())
                    .append(",\"hp\":").append(mob.getHp())
                    .append(",\"maxHp\":").append(mob.getMaxHp())
                    .append(",\"position\":{\"x\":").append(mp.x).append(",\"y\":").append(mp.y).append('}')
                    .append(",\"alive\":").append(mob.isAlive())
                    .append('}');
        }
        return out.append("],\"drops\":[]}").toString();
    }

    Result act(String body) {
        BotEntry entry = requireEntry();
        Character bot = entry.bot;
        MapleBenchEventSink.ensureStarted(bot);

        String type = MapleBenchJson.stringField(body, "type");
        if (type == null) return new Result(false, "missing action type");

        return switch (type) {
            case "move_to" -> moveTo(entry, body);
            case "basic_attack" -> attack(entry, body, 0);
            case "use_skill" -> {
                Long skillId = MapleBenchJson.longField(body, "skillId");
                if (skillId == null || skillId <= 0 || skillId > Integer.MAX_VALUE) {
                    yield new Result(false, "invalid skillId");
                }
                yield attack(entry, body, skillId.intValue());
            }
            default -> new Result(false, "action not implemented by Cosmic v0 bridge: " + type);
        };
    }

    private Result moveTo(BotEntry entry, String body) {
        Long x = MapleBenchJson.longField(body, "x");
        Long y = MapleBenchJson.longField(body, "y");
        if (x == null || y == null || x < Integer.MIN_VALUE || x > Integer.MAX_VALUE
                || y < Integer.MIN_VALUE || y > Integer.MAX_VALUE) {
            return new Result(false, "invalid move_to position");
        }
        botManager.issueMoveTo(entry, new Point(x.intValue(), y.intValue()), true);
        return new Result(true, null);
    }

    private Result attack(BotEntry entry, String body, int skillId) {
        Long targetId = MapleBenchJson.longField(body, "targetId");
        if (targetId == null || targetId <= 0 || targetId > Integer.MAX_VALUE) {
            return new Result(false, "targetId is required for benchmark attacks");
        }
        Monster target = findMonster(entry.bot, targetId.intValue());
        if (target == null || !target.isAlive()) return new Result(false, "target not alive/visible");
        boolean accepted = BotCombatManager.tryRequestedAttack(entry, entry.bot, target, skillId);
        return accepted ? new Result(true, null) : new Result(false, "attack not currently legal");
    }

    private Monster findMonster(Character bot, int objectId) {
        for (Monster monster : bot.getMap().getAllMonsters()) {
            if (monster.getObjectId() == objectId) return monster;
        }
        return null;
    }

    private BotEntry requireEntry() {
        BotEntry entry = entry();
        if (entry == null || entry.bot == null) {
            throw new IllegalStateException("MapleBench bot '" + botName + "' is not active; spawn/register it first");
        }
        return entry;
    }
}
