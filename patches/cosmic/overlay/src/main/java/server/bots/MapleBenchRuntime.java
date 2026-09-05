package server.bots;

import client.Character;
import client.SkillFactory;
import client.inventory.InventoryType;
import client.inventory.Item;
import constants.skills.Warrior;
import constants.skills.Crusader;
import net.server.Server;
import server.ItemInformationProvider;
import java.awt.Point;

/** Opt-in startup for a character already seeded in the dedicated experiment database. */
public final class MapleBenchRuntime {
    private MapleBenchRuntime() {}

    static boolean isControlled(Character bot) {
        return "true".equalsIgnoreCase(System.getenv("MAPLEBENCH_ENABLED"))
                && MapleBenchEventSink.matchesConfiguredBot(bot);
    }

    static void spawnFromEnvironment() {
        String id = System.getenv("MAPLEBENCH_CHARACTER_ID");
        if (id == null || id.isBlank()) return;
        try {
            int mapId = Integer.parseInt(System.getenv().getOrDefault("MAPLEBENCH_MAP_ID", "100000000"));
            var map = Server.getInstance().getChannel(0, 1).getMapFactory().getMap(mapId);
            BotManager manager = BotManager.getInstance();
            boolean crusader = "crusader".equalsIgnoreCase(System.getenv("MAPLEBENCH_PRESET"));
            boolean demoMobs = "true".equalsIgnoreCase(System.getenv("MAPLEBENCH_DEMO_MOBS"));
            Point spawn = demoMobs && mapId == 100000000 ? new Point(1473, 260) : null;
            Character bot = manager.loadOfflineBot(Integer.parseInt(id), 0, 1, map, spawn);
            if (!isControlled(bot)) throw new IllegalArgumentException("Seeded character name does not match MAPLEBENCH_BOT_NAME");
            // The upstream offline loader sets mapid but can retain the map object from the DB.
            // Complete the normal map transition before registering mechanics or spawning fixtures.
            if (bot.getMap() != map) {
                Point destination = manager.resolveSpawnPosition(map, spawn != null ? spawn : bot.getPosition());
                bot.changeMap(map, destination);
            }

            // Seed equipment before the episode begins. Runtime actions use normal game handlers.
            int[] equipment = {1040036, 1060026, 1072001, crusader ? 1402037 : 1302000};
            short[] slots = {-5, -6, -7, -11};
            for (int i = 0; i < equipment.length; i++) {
                if (bot.getInventory(InventoryType.EQUIPPED).getItem(slots[i]) == null) {
                    Item item = ItemInformationProvider.getInstance().getEquipById(equipment[i]);
                    item.setPosition(slots[i]);
                    bot.getInventory(InventoryType.EQUIPPED).addItemFromDB(item);
                }
            }
            bot.changeSkillLevel(SkillFactory.getSkill(Warrior.POWER_STRIKE), (byte) (crusader ? 20 : 1), 0, -1);
            if (crusader) {
                bot.changeSkillLevel(SkillFactory.getSkill(Warrior.SLASH_BLAST), (byte) 20, 0, -1);
                bot.changeSkillLevel(SkillFactory.getSkill(Crusader.SHOUT), (byte) 30, 0, -1);
            }
            bot.recalcLocalStats();
            BotEntry entry = manager.registerSpawnedBot(bot.getId(), null, bot);
            entry.following = false;
            entry.grinding = false;
            if (demoMobs) {
                // Explicit town combat fixture; these are ordinary server monsters with normal HP/XP.
                Point p = bot.getPosition();
                int[] offsets = crusader ? new int[]{100, 160, 220} : new int[]{140, 260, 380};
                for (int offset : offsets) {
                    map.spawnMonsterOnGroundBelow(crusader ? 5100000 : 210100, p.x + offset, p.y - 20);
                }
            }
            MapleBenchEventSink.ensureStarted(bot);
            System.out.println("MapleBench seeded character ready: " + bot.getName() + " map=" + mapId);
        } catch (Exception e) {
            throw new IllegalStateException("Could not spawn the seeded MapleBench character", e);
        }
    }
}
