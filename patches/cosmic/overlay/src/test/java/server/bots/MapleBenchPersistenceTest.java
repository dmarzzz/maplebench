package server.bots;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.HashMap;
import java.util.Map;
import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.io.IOException;
import static org.junit.jupiter.api.Assertions.*;

class MapleBenchPersistenceTest {
    @TempDir Path temp;

    private Map<String, String> config(Path path) {
        return Map.of("MAPLEBENCH_TRIAL_ID", "attempt-1",
                "MAPLEBENCH_SERVER_INSTANCE_ID", "instance-1",
                "MAPLEBENCH_PERSIST_CHARACTER_ID", "7", "MAPLEBENCH_PERSIST_ACCOUNT_ID", "3",
                "MAPLEBENCH_SAVE_JOURNAL", path.toString());
    }

    @Test void disabledByDefaultAndPartialConfigurationRefused() {
        assertNull(MapleBenchPersistence.Journal.open(Map.of()));
        assertThrows(IllegalArgumentException.class,
                () -> MapleBenchPersistence.Journal.open(Map.of("MAPLEBENCH_TRIAL_ID", "one")));
    }

    @Test void recordsOnlyConfiguredIdentityWithCommitAndFailureDistinguished() throws Exception {
        Path path = temp.resolve("save.jsonl");
        try (var journal = MapleBenchPersistence.Journal.open(config(path))) {
            journal.record("save_committed", 8, 3, 100);
            journal.record("save_committed", 7, 4, 100);
            journal.record("save_committed", 7, 3, 200);
            journal.record("save_failed", 7, 3, 300);
        }
        var lines = Files.readAllLines(path);
        assertEquals(2, lines.size());
        assertTrue(lines.get(0).contains("\"committed_at_ms\":200"));
        assertTrue(lines.get(1).contains("\"kind\":\"save_failed\""));
        assertEquals("rw-------", PosixFilePermissions.toString(Files.getPosixFilePermissions(path)));
        assertThrows(IllegalStateException.class, () -> MapleBenchPersistence.Journal.open(config(path)));
    }

    @Test void refusesInjectedIdsAndSymlinkAncestors() throws Exception {
        var invalid = new HashMap<>(config(temp.resolve("bad.jsonl")));
        invalid.put("MAPLEBENCH_TRIAL_ID", "bad\"id");
        assertThrows(IllegalArgumentException.class, () -> MapleBenchPersistence.Journal.open(invalid));
        Path link = temp.resolve("link");
        Files.createSymbolicLink(link, temp);
        assertThrows(IllegalStateException.class,
                () -> MapleBenchPersistence.Journal.open(config(link.resolve("save.jsonl"))));
    }

    @Test void writeFailureDoesNotMasqueradeAsCommittedReceiptOrBreakGameSave() throws Exception {
        Path path = temp.resolve("save.jsonl");
        var journal = MapleBenchPersistence.Journal.open(config(path));
        journal.close();
        assertDoesNotThrow(() -> journal.record("save_committed", 7, 3, 200));
        assertEquals(0, Files.size(path));
    }

    @Test void syncFailureAfterWriteEmitsMandatoryInvalidationMarker() throws Exception {
        Path path = temp.resolve("save.jsonl");
        var captured = new ByteArrayOutputStream();
        var oldError = System.err;
        try (var journal = MapleBenchPersistence.Journal.open(config(path), channel -> {
            throw new IOException("injected sync failure");
        })) {
            System.setErr(new PrintStream(captured));
            journal.record("save_committed", 7, 3, 200);
            journal.record("save_committed", 7, 3, 300);
        } finally {
            System.setErr(oldError);
        }
        assertEquals(1, Files.readAllLines(path).size());
        assertTrue(captured.toString().contains("MapleBench persistence journal failed"));
        assertFalse(captured.toString().contains("injected sync failure"));
    }
}
