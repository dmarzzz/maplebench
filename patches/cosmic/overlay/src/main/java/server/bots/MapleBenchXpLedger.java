package server.bots;

import constants.game.ExpTable;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Map;

/** Disabled-by-default, identity-scoped journal of settled XP transactions.
 * Nested level-up/overflow arithmetic belongs to its outer XP transaction. The
 * ledger records actual before/after progression, not the nominal XP grant.
 * File/clock/state failures invalidate evidence without rolling back gameplay.
 */
public final class MapleBenchXpLedger {
    private static Journal journal;
    private static boolean initialized;
    private static final ThreadLocal<Integer> DEPTH = ThreadLocal.withInitial(() -> 0);
    private MapleBenchXpLedger() {}

    public static synchronized void initializeFromEnvironment() {
        if (initialized) return;
        int[] thresholds = new int[199];
        for (int i = 0; i < thresholds.length; i++) thresholds[i] = ExpTable.getExpNeededForLevel(i + 1);
        journal = Journal.open(System.getenv(), thresholds);
        initialized = true;
        if (journal != null) System.err.println("MapleBench XP ledger initialized");
    }

    public static final class Mutation {
        private final int level, exp, depth;
        private final String kind;
        private Mutation(int level, int exp, int depth, String kind) {
            this.level = level; this.exp = exp; this.depth = depth; this.kind = kind;
        }
    }

    public static Mutation begin(int character, int account, int level, int exp, String kind) {
        Journal active = journal;
        if (active == null || !active.matches(character, account)) return null;
        int depth = DEPTH.get() + 1;
        DEPTH.set(depth);
        return new Mutation(level, exp, depth, kind);
    }

    public static void end(Mutation mutation, int level, int exp, int worldExpRate) {
        if (mutation == null) return;
        int depth = DEPTH.get();
        DEPTH.set(Math.max(0, depth - 1));
        if (depth != mutation.depth) { journal.invalidate(); return; }
        if (depth == 1) journal.transition(mutation.kind, mutation.level, mutation.exp, level, exp,
                                         worldExpRate, System.currentTimeMillis(), System.nanoTime());
    }

    public static void committed(int character, int account, int level, int exp, int worldExpRate,
                                 long wallMs, long monotonicNs) {
        Journal active = journal;
        if (active != null && active.matches(character, account))
            active.committed(level, exp, worldExpRate, wallMs, monotonicNs);
    }

    static final class Journal implements AutoCloseable {
        @FunctionalInterface interface Sync { void force(FileChannel channel) throws IOException; }
        private final FileChannel channel;
        private final Sync sync;
        private final String identity;
        private final int character, account;
        private final int[] thresholds;
        private final long originNs, originMs, serverNumerator, serverDenominator;
        private long sequence, bytes, lastNs, lastWall;
        private String previous = "0".repeat(64);
        private int level, exp;
        private boolean broken;

        private Journal(FileChannel channel, Sync sync, String run, String instance, int character, int account,
                        int level, int exp, int[] thresholds, long wall, long nano,
                        long serverNum, long serverDen, long simulationNum, long simulationDen) {
            this.channel = channel; this.sync = sync; this.character = character; this.account = account;
            this.level = level; this.exp = exp; this.thresholds = thresholds.clone();
            this.originMs = wall; this.originNs = nano; this.lastWall = wall;
            this.serverNumerator = serverNum; this.serverDenominator = serverDen;
            identity = "\"run_id\":\"" + run + "\",\"server_instance_id\":\"" + instance
                + "\",\"character_id\":" + character + ",\"account_id\":" + account;
            StringBuilder table = new StringBuilder("[");
            for (int i = 0; i < thresholds.length; i++) { if (i > 0) table.append(','); table.append(thresholds[i]); }
            table.append(']');
            write("header", "\"level\":" + level + ",\"exp\":" + exp + ",\"thresholds\":" + table
                + ",\"server_xp_multiplier\":{\"numerator\":" + serverNum + ",\"denominator\":" + serverDen
                + "},\"simulation_speed_multiplier\":{\"numerator\":" + simulationNum + ",\"denominator\":" + simulationDen + "}", wall, nano);
        }

        static Journal open(Map<String,String> env, int[] thresholds) {
            return open(env, thresholds, channel -> channel.force(true), System.currentTimeMillis(), System.nanoTime());
        }

        static Journal open(Map<String,String> env, int[] thresholds, Sync sync, long wall, long nano) {
            String[] extra = {"MAPLEBENCH_XP_JOURNAL", "MAPLEBENCH_XP_BASELINE_LEVEL", "MAPLEBENCH_XP_BASELINE_EXP",
                "MAPLEBENCH_XP_SERVER_NUMERATOR", "MAPLEBENCH_XP_SERVER_DENOMINATOR",
                "MAPLEBENCH_XP_SIMULATION_NUMERATOR", "MAPLEBENCH_XP_SIMULATION_DENOMINATOR"};
            int present = 0;
            for (String key : extra) if (env.containsKey(key)) present++;
            if (present == 0) return null;
            if (present != extra.length) throw new IllegalArgumentException("Incomplete MapleBench XP configuration");
            String run = env.get("MAPLEBENCH_TRIAL_ID"), instance = env.get("MAPLEBENCH_SERVER_INSTANCE_ID");
            if (run == null || instance == null || !run.matches("[a-f0-9]{32}") || !instance.matches("[a-f0-9]{32}"))
                throw new IllegalArgumentException("Invalid MapleBench XP identity");
            try {
                int character = Integer.parseInt(env.get("MAPLEBENCH_PERSIST_CHARACTER_ID"));
                int account = Integer.parseInt(env.get("MAPLEBENCH_PERSIST_ACCOUNT_ID"));
                int level = Integer.parseInt(env.get(extra[1])), exp = Integer.parseInt(env.get(extra[2]));
                long[] multipliers = new long[4];
                for (int i = 0; i < 4; i++) {
                    multipliers[i] = Long.parseLong(env.get(extra[i+3]));
                    if (multipliers[i] < 1 || multipliers[i] > 1000000) throw new IllegalArgumentException();
                }
                if (character < 1 || account < 1 || thresholds.length != 199 || level < 1 || level > 200
                    || exp < 0 || level == 200 && exp != 0) throw new IllegalArgumentException();
                for (int threshold : thresholds) if (threshold <= 0) throw new IllegalArgumentException();
                if (level < 200 && exp >= thresholds[level-1]) throw new IllegalArgumentException();
                Path path = Path.of(env.get(extra[0]));
                if (!path.isAbsolute() || !path.normalize().equals(path)) throw new IllegalArgumentException();
                for (Path parent = path.getParent(); parent != null; parent = parent.getParent())
                    if (Files.isSymbolicLink(parent)) throw new IllegalArgumentException();
                FileChannel channel = FileChannel.open(path, java.util.Set.of(StandardOpenOption.CREATE_NEW,
                    StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS),
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
                return new Journal(channel, sync, run, instance, character, account, level, exp, thresholds,
                                   wall, nano, multipliers[0], multipliers[1], multipliers[2], multipliers[3]);
            } catch (IOException | IllegalArgumentException error) {
                throw new IllegalStateException("Cannot initialize MapleBench XP ledger");
            }
        }

        boolean matches(int character, int account) { return this.character == character && this.account == account; }
        private long progression(int level, int exp) {
            if (level < 1 || level > 200 || exp < 0 || level == 200 && exp != 0
                || level < 200 && exp >= thresholds[level-1]) throw new IllegalArgumentException();
            long total = exp;
            for (int i = 0; i < level-1; i++) total += thresholds[i];
            return total;
        }
        synchronized void transition(String kind, int beforeLevel, int beforeExp, int afterLevel, int afterExp,
                                     int rate, long wall, long nano) {
            if (broken) return;
            try {
                if (beforeLevel != level || beforeExp != exp || rate * serverDenominator != serverNumerator
                    || !(kind.equals("xp_transaction") || kind.equals("level_up") || kind.equals("set_exp") || kind.equals("set_level")))
                    throw new IllegalArgumentException();
                if (afterLevel < beforeLevel) throw new IllegalArgumentException();
                long delta = progression(afterLevel, afterExp) - progression(beforeLevel, beforeExp);
                write("xp_transaction", "\"cause\":\"" + kind + "\",\"before_level\":" + beforeLevel
                    + ",\"before_exp\":" + beforeExp + ",\"after_level\":" + afterLevel + ",\"after_exp\":" + afterExp
                    + ",\"delta_xp\":" + delta + ",\"world_exp_rate\":" + rate, wall, nano);
                level = afterLevel; exp = afterExp;
            } catch (IllegalArgumentException error) { invalidate(); }
        }
        synchronized void committed(int level, int exp, int rate, long wall, long nano) {
            if (broken) return;
            if (this.level != level || this.exp != exp || rate * serverDenominator != serverNumerator) { invalidate(); return; }
            write("save_committed", "\"level\":" + level + ",\"exp\":" + exp + ",\"world_exp_rate\":" + rate, wall, nano);
        }
        synchronized void invalidate() {
            if (!broken) System.err.println("MapleBench XP ledger failed; window evidence is invalid");
            broken = true;
        }
        private void write(String kind, String fields, long wall, long nano) {
            if (broken) return;
            long elapsed = nano - originNs;
            if (elapsed < lastNs || wall < lastWall || Math.abs((wall-originMs) - elapsed/1000000) > 25
                || sequence >= 100000) { invalidate(); return; }
            String line = "{\"schema_version\":1,\"source\":\"cosmic_native_xp_ledger\",\"kind\":\"" + kind + "\","
                + identity + ",\"sequence\":" + sequence + ",\"wall_ms\":" + wall + ",\"elapsed_ns\":" + elapsed
                + ",\"previous_sha256\":\"" + previous + "\"," + fields + "}\n";
            byte[] raw = line.getBytes(StandardCharsets.UTF_8);
            if (bytes + raw.length > 64*1024*1024) { invalidate(); return; }
            try {
                ByteBuffer buffer = ByteBuffer.wrap(raw);
                while (buffer.hasRemaining()) channel.write(buffer);
                sync.force(channel);
                previous = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(raw));
                sequence++; bytes += raw.length; lastNs = elapsed; lastWall = wall;
            } catch (IOException | NoSuchAlgorithmException error) { invalidate(); }
        }
        @Override public synchronized void close() throws IOException { channel.close(); }
    }
}
