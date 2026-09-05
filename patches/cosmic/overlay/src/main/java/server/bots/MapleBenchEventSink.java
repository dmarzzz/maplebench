package server.bots;

import client.Character;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Append-only, server-authoritative MapleBench episode trace.
 *
 * The scorer consumes this file; the viewer tails the same file. The sink only
 * records the configured benchmark character so unrelated players cannot affect
 * an episode score.
 */
public final class MapleBenchEventSink {
    private record Stored(long seq, String json) {}

    private static final Object LOCK = new Object();
    private static final AtomicLong NEXT_SEQ = new AtomicLong(0);
    private static final List<Stored> EVENTS = new ArrayList<>();

    private static volatile boolean configured = false;
    private static volatile boolean started = false;
    private static volatile String botName = "";
    private static volatile String taskId = "maximize-xp-10m";
    private static volatile String seed = "cosmic-v0";
    private static volatile Path outputPath = Path.of("logs", "maplebench", "episode.jsonl");
    private static volatile long startedAtMs = 0L;
    private static volatile int characterId = 0;

    private MapleBenchEventSink() {}

    public static void configureFromEnvironment() {
        synchronized (LOCK) {
            if (configured) return;
            botName = env("MAPLEBENCH_BOT_NAME", "");
            taskId = env("MAPLEBENCH_TASK_ID", "maximize-xp-10m");
            seed = env("MAPLEBENCH_SEED", "cosmic-v0");
            outputPath = Path.of(env("MAPLEBENCH_EPISODE", "logs/maplebench/episode.jsonl"));
            configured = true;
        }
    }

    public static boolean matchesConfiguredBot(Character chr) {
        if (chr == null) return false;
        configureFromEnvironment();
        return !botName.isBlank() && botName.equalsIgnoreCase(chr.getName());
    }

    public static void ensureStarted(Character chr) {
        if (chr == null || !matchesConfiguredBot(chr)) return;
        synchronized (LOCK) {
            if (started) return;
            try {
                Path parent = outputPath.toAbsolutePath().getParent();
                if (parent != null) Files.createDirectories(parent);
                Files.writeString(outputPath, "", StandardCharsets.UTF_8,
                        StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
            } catch (IOException e) {
                throw new IllegalStateException("Could not initialize MapleBench episode log: " + outputPath, e);
            }
            NEXT_SEQ.set(0);
            EVENTS.clear();
            startedAtMs = System.currentTimeMillis();
            characterId = chr.getId();
            started = true;
            appendPayload("\"kind\":\"episode_start\",\"taskId\":" + MapleBenchJson.quote(taskId)
                    + ",\"seed\":" + MapleBenchJson.quote(seed)
                    + ",\"characterId\":" + chr.getId());
        }
    }

    public static long elapsedMs() {
        return started ? Math.max(0L, System.currentTimeMillis() - startedAtMs) : 0L;
    }

    /** Called after Character has applied the exact EXP delta to its authoritative counter. */
    public static void recordXpGain(Character chr, long actualAmount) {
        if (chr == null || actualAmount == 0 || !started || chr.getId() != characterId) return;
        // v0 labels the source as "other" because Character.gainExpInternal is the
        // authoritative aggregation point. Source attribution can be enriched later
        // without changing scoring, which depends only on amount and timestamp.
        appendPayload("\"kind\":\"xp_gain\",\"amount\":" + actualAmount + ",\"source\":\"other\"");
    }

    public static void recordAction(String actionJson, boolean accepted) {
        if (!started) return;
        String safeAction = actionJson == null || actionJson.isBlank() ? "{}" : actionJson.trim();
        appendPayload("\"kind\":\"action\",\"action\":" + safeAction + ",\"accepted\":" + accepted);
    }

    public static String eventsSince(long sinceSeq) {
        synchronized (LOCK) {
            StringBuilder out = new StringBuilder("[");
            boolean first = true;
            for (Stored event : EVENTS) {
                if (event.seq < sinceSeq) continue;
                if (!first) out.append(',');
                out.append(event.json);
                first = false;
            }
            return out.append(']').toString();
        }
    }

    static boolean records(Character chr) {
        return started && chr != null && chr.getId() == characterId;
    }

    static long appendPayload(String payload) {
        synchronized (LOCK) {
            if (!started) return -1;
            long seq = NEXT_SEQ.getAndIncrement();
            String json = "{\"seq\":" + seq + ",\"tMs\":" + elapsedMs() + "," + payload + "}";
            EVENTS.add(new Stored(seq, json));
            try {
                Files.writeString(outputPath, json + System.lineSeparator(), StandardCharsets.UTF_8,
                        StandardOpenOption.CREATE, StandardOpenOption.APPEND);
            } catch (IOException e) {
                throw new IllegalStateException("Could not append MapleBench episode event", e);
            }
            return seq;
        }
    }

    private static String env(String name, String fallback) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? fallback : value;
    }
}
