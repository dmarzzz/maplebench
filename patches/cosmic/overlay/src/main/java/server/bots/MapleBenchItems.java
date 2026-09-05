package server.bots;

import constants.id.ItemId;

/** Explicit finite consumables; every use still goes through Cosmic's ordinary handler. */
final class MapleBenchItems {
    static final int ICE_CREAM_POP = 2001001;
    private MapleBenchItems() {}

    static boolean supported(int id) {
        return id == ItemId.WHITE_POTION || id == ItemId.BLUE_POTION
                || id == ItemId.MANA_ELIXIR || id == ICE_CREAM_POP;
    }

    static int configured(String key, int fallback, boolean hp) {
        int id = Integer.parseInt(System.getenv().getOrDefault(key, Integer.toString(fallback)));
        boolean allowed = hp ? id == ItemId.WHITE_POTION || id == ICE_CREAM_POP
                : id == ItemId.BLUE_POTION || id == ItemId.MANA_ELIXIR;
        if (!allowed) throw new IllegalArgumentException("Unsupported benchmark potion role");
        return id;
    }
}
