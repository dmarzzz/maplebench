package server.bots;

import client.Character;
import client.SkillFactory;
import client.inventory.InventoryType;
import client.inventory.Item;
import constants.id.ItemId;
import constants.skills.Warrior;
import constants.skills.Crusader;
import constants.skills.Fighter;
import constants.skills.Hero;
import net.server.Server;
import server.ItemInformationProvider;
import java.awt.Point;
import java.util.ArrayList;
import java.util.Locale;

/** Opt-in startup for a character already seeded in the dedicated experiment database. */
public final class MapleBenchRuntime {
    private MapleBenchRuntime() {}

    private enum Preset {
        WARRIOR(100, 1302000), CRUSADER(111, 1402037), HERO(112, 1402037);

        final int jobId;
        final int weaponId;

        Preset(int jobId, int weaponId) {
            this.jobId = jobId;
            this.weaponId = weaponId;
        }
    }

    private static Point configuredSpawn(boolean demoMobs, int mapId) {
        String x = System.getenv("MAPLEBENCH_SPAWN_X");
        String y = System.getenv("MAPLEBENCH_SPAWN_Y");
        if (x != null || y != null) {
            if (x == null || y == null) throw new IllegalArgumentException("Both spawn coordinates are required");
            return new Point(Integer.parseInt(x), Integer.parseInt(y));
        }
        return demoMobs && mapId == 100000000 ? new Point(1473, 260) : null;
    }

    private static int potionCount(String key, boolean demoMobs) {
        int count = Integer.parseInt(System.getenv().getOrDefault(key, demoMobs ? "0" : "100"));
        if (count < 0 || count > 100) throw new IllegalArgumentException(key + " must be between 0 and 100");
        return count;
    }

    private static void setSkill(Character bot, int id, int level) {
        var skill = SkillFactory.getSkill(id);
        if (skill == null) throw new IllegalArgumentException("Missing preset skill: " + id);
        bot.changeSkillLevel(skill, (byte) level, id == Hero.BRANDISH ? level : 0, -1);
    }

    private static void seedConsumables(Character bot, int hpPotions, int mpPotions) {
        var inventory = bot.getInventory(InventoryType.USE);
        // Each fresh trial starts with exactly this finite supply, including after a persisted save.
        for (Item item : new ArrayList<>(inventory.list())) inventory.removeSlot(item.getPosition());
        if (hpPotions > 0) inventory.addItemFromDB(new Item(ItemId.WHITE_POTION, (short) 1, (short) hpPotions));
        if (mpPotions > 0) inventory.addItemFromDB(new Item(ItemId.BLUE_POTION, (short) 2, (short) mpPotions));
    }

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
            Preset preset = Preset.valueOf(System.getenv().getOrDefault("MAPLEBENCH_PRESET", "warrior").toUpperCase(Locale.ROOT));
            boolean advanced = preset != Preset.WARRIOR;
            boolean demoMobs = "true".equalsIgnoreCase(System.getenv("MAPLEBENCH_DEMO_MOBS"));
            if (demoMobs && mapId != 100000000) throw new IllegalArgumentException("Town fixtures require Henesys; use natural spawns on hunting maps");
            Point spawn = configuredSpawn(demoMobs, mapId);
            if (spawn == null && map.getPortal(0) != null) spawn = map.getPortal(0).getPosition();
            int hpPotions = potionCount("MAPLEBENCH_HP_POTIONS", demoMobs);
            int mpPotions = potionCount("MAPLEBENCH_MP_POTIONS", demoMobs);
            Character bot = manager.loadOfflineBot(Integer.parseInt(id), 0, 1, map, spawn);
            if (!isControlled(bot)) throw new IllegalArgumentException("Seeded character name does not match MAPLEBENCH_BOT_NAME");
            if (bot.getJob().getId() != preset.jobId) throw new IllegalArgumentException("Seeded character job does not match preset " + preset);
            // The upstream offline loader sets mapid but can retain the map object from the DB.
            // Complete the normal map transition before registering mechanics or spawning fixtures.
            if (bot.getMap() != map) {
                Point destination = manager.resolveSpawnPosition(map, spawn != null ? spawn : bot.getPosition());
                bot.changeMap(map, destination);
            }

            // Seed equipment before the episode begins. Runtime actions use normal game handlers.
            int[] equipment = {1040036, 1060026, 1072001, preset.weaponId};
            short[] slots = {-5, -6, -7, -11};
            // No equipment from an earlier trial survives the preset reset.
            var equipped = bot.getInventory(InventoryType.EQUIPPED);
            for (Item item : new ArrayList<>(equipped.list())) equipped.removeSlot(item.getPosition());
            for (int i = 0; i < equipment.length; i++) {
                Item item = ItemInformationProvider.getInstance().getEquipById(equipment[i]);
                if (item == null) throw new IllegalArgumentException("Missing preset equipment: " + equipment[i]);
                item.setPosition(slots[i]);
                equipped.addItemFromDB(item);
            }
            setSkill(bot, Warrior.POWER_STRIKE, advanced ? 20 : 1);
            setSkill(bot, Warrior.SLASH_BLAST, advanced ? 20 : 0);
            setSkill(bot, Fighter.SWORD_MASTERY, advanced ? 20 : 0);
            setSkill(bot, Hero.BRANDISH, preset == Preset.HERO ? 30 : 0);
            // Shout has not passed a separate live skill validation; keep it out of scored trials.
            setSkill(bot, Crusader.SHOUT, 0);
            seedConsumables(bot, hpPotions, mpPotions);
            // addItemFromDB does not invalidate the character's cached equipment stats.
            // Use the normal equipment-change path so a new character has its real weapon attack.
            bot.equipChanged();
            if (bot.getTotalWatk() <= 0) throw new IllegalStateException("Preset weapon attack was not applied");
            BotEntry entry = manager.registerSpawnedBot(bot.getId(), null, bot);
            entry.following = false;
            entry.grinding = false;
            if (demoMobs) {
                // Explicit town combat fixture; these are ordinary server monsters with normal HP/XP.
                Point p = bot.getPosition();
                int[] offsets = advanced ? new int[]{100, 160, 220} : new int[]{140, 260, 380};
                for (int offset : offsets) {
                    map.spawnMonsterOnGroundBelow(advanced ? 5100000 : 210100, p.x + offset, p.y - 20);
                }
            }
            MapleBenchEventSink.ensureStarted(bot);
            System.out.println("MapleBench seeded character ready: " + bot.getName() + " map=" + mapId
                    + " preset=" + preset.name().toLowerCase(Locale.ROOT) + " demoMobs=" + demoMobs
                    + " naturalSpawnPoints=" + map.getMonsterSpawn().size()
                    + " weaponAttack=" + bot.getTotalWatk()
                    + " hpPotions=" + hpPotions + " mpPotions=" + mpPotions);
        } catch (Exception e) {
            throw new IllegalStateException("Could not spawn the seeded MapleBench character", e);
        }
    }
}
