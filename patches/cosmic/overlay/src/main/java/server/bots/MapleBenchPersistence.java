package server.bots;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Map;

/**
 * Positive receipts from the real character-save transaction. Disabled unless a
 * trusted trial launcher supplies every setting. No names, passwords, or game
 * state are logged. A journal failure cannot undo a committed game transaction;
 * it makes the trial's persistence evidence incomplete instead.
 */
public final class MapleBenchPersistence {
    private static Journal journal;
    private static boolean initialized;

    private MapleBenchPersistence() {}

    public static synchronized void initializeFromEnvironment() {
        if (initialized) return;
        journal = Journal.open(System.getenv());
        initialized = true;
        if (journal != null) System.err.println("MapleBench persistence journal initialized");
    }

    public static synchronized void committed(int characterId, int accountId) {
        record("save_committed", characterId, accountId);
    }

    public static synchronized void committed(int characterId, int accountId, int level, int exp, int worldExpRate) {
        long wall = System.currentTimeMillis(), nano = System.nanoTime();
        if (initialized && journal != null) journal.record("save_committed", characterId, accountId, wall);
        MapleBenchXpLedger.committed(characterId, accountId, level, exp, worldExpRate, wall, nano);
    }

    public static synchronized void failed(int characterId, int accountId) {
        record("save_failed", characterId, accountId);
    }

    private static void record(String kind, int characterId, int accountId) {
        // Initialization happens before the server accepts logins. Never enable
        // evidence collection midway through an already running server session.
        if (!initialized || journal == null) return;
        journal.record(kind, characterId, accountId, System.currentTimeMillis());
    }

    static final class Journal implements AutoCloseable {
        private final String runId;
        private final String instanceId;
        private final int characterId;
        private final int accountId;
        private final FileChannel channel;
        private boolean broken;
        private final Sync sync;

        @FunctionalInterface interface Sync { void force(FileChannel channel) throws IOException; }

        private Journal(String runId, String instanceId, int characterId, int accountId,
                        FileChannel channel, Sync sync) {
            this.runId = runId;
            this.instanceId = instanceId;
            this.characterId = characterId;
            this.accountId = accountId;
            this.channel = channel;
            this.sync = sync;
        }

        static Journal open(Map<String, String> env) {
            return open(env, channel -> channel.force(true));
        }

        static Journal open(Map<String, String> env, Sync sync) {
            String[] names = {"MAPLEBENCH_TRIAL_ID", "MAPLEBENCH_SERVER_INSTANCE_ID",
                    "MAPLEBENCH_PERSIST_CHARACTER_ID", "MAPLEBENCH_PERSIST_ACCOUNT_ID", "MAPLEBENCH_SAVE_JOURNAL"};
            int present = 0;
            for (String name : names) if (env.containsKey(name)) present++;
            if (present == 0) return null;
            if (present != names.length) throw new IllegalArgumentException("Incomplete MapleBench persistence configuration");
            String run = env.get(names[0]);
            String instance = env.get(names[1]);
            if (!identifier(run) || !identifier(instance)) {
                throw new IllegalArgumentException("Invalid MapleBench persistence identifiers");
            }
            try {
                int character = Integer.parseInt(env.get(names[2]));
                int account = Integer.parseInt(env.get(names[3]));
                if (character <= 0 || account <= 0) throw new IllegalArgumentException();
                Path path = Path.of(env.get(names[4]));
                if (!path.isAbsolute() || !path.normalize().equals(path)) throw new IllegalArgumentException();
                // The launcher creates a private attempt directory. Reject
                // symlink ancestors and reusing another server's journal.
                for (Path parent = path.getParent(); parent != null; parent = parent.getParent()) {
                    if (Files.isSymbolicLink(parent)) throw new IllegalArgumentException();
                }
                FileChannel channel = FileChannel.open(path,
                        java.util.Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE,
                                LinkOption.NOFOLLOW_LINKS),
                        PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
                return new Journal(run, instance, character, account, channel, sync);
            } catch (IOException | IllegalArgumentException error) {
                // Configuration paths and OS errors can contain private data.
                throw new IllegalStateException("Cannot initialize MapleBench persistence journal");
            }
        }

        private static boolean identifier(String value) {
            return value != null && value.matches("[A-Za-z0-9][A-Za-z0-9_.-]{0,127}");
        }

        synchronized void record(String kind, int character, int account, long atMs) {
            if (broken || character != characterId || account != accountId) return;
            String timeField = kind.equals("save_committed") ? "committed_at_ms" : "at_ms";
            String line = "{\"schema_version\":1,\"source\":\"cosmic_persisted_character\",\"kind\":\""
                    + kind + "\",\"run_id\":\"" + runId + "\",\"server_instance_id\":\"" + instanceId
                    + "\",\"character_id\":" + characterId + ",\"account_id\":" + accountId
                    + ",\"" + timeField + "\":" + atMs + "}\n";
            try {
                ByteBuffer buffer = StandardCharsets.UTF_8.encode(line);
                while (buffer.hasRemaining()) channel.write(buffer);
                sync.force(channel);
            } catch (IOException error) {
                broken = true;
                System.err.println("MapleBench persistence journal failed; trial evidence is invalid");
            }
        }

        @Override public synchronized void close() throws IOException {
            channel.close();
        }
    }
}
