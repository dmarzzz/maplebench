package server.bots;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.PrintStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

class MapleBenchXpLedgerTest {
    @TempDir Path temp;
    int[] table() { int[] values=new int[199]; Arrays.fill(values,1000); return values; }
    Map<String,String> config(String name) {
        var env=new HashMap<String,String>();
        env.put("MAPLEBENCH_TRIAL_ID","a".repeat(32));env.put("MAPLEBENCH_SERVER_INSTANCE_ID","b".repeat(32));
        env.put("MAPLEBENCH_PERSIST_CHARACTER_ID","7");env.put("MAPLEBENCH_PERSIST_ACCOUNT_ID","9");
        env.put("MAPLEBENCH_XP_JOURNAL",temp.resolve(name).toString());
        env.put("MAPLEBENCH_XP_BASELINE_LEVEL","1");env.put("MAPLEBENCH_XP_BASELINE_EXP","900");
        env.put("MAPLEBENCH_XP_SERVER_NUMERATOR","1");env.put("MAPLEBENCH_XP_SERVER_DENOMINATOR","1");
        env.put("MAPLEBENCH_XP_SIMULATION_NUMERATOR","1");env.put("MAPLEBENCH_XP_SIMULATION_DENOMINATOR","1");
        return env;
    }
    MapleBenchXpLedger.Journal open(String name) {
        return MapleBenchXpLedger.Journal.open(config(name),table(),channel->channel.force(true),1000,1000000000);
    }
    @Test void disabledByDefaultAndPartialConfigurationRefused() {
        assertNull(MapleBenchXpLedger.Journal.open(Map.of(),table()));
        assertThrows(IllegalArgumentException.class,()->MapleBenchXpLedger.Journal.open(Map.of("MAPLEBENCH_XP_JOURNAL","x"),table()));
    }
    @Test void levelTransitionAndDeathLossAreActualProgressionNotRawGrant() throws Exception {
        try(var journal=open("ledger.jsonl")) {
            journal.transition("xp_transaction",1,900,2,100,1,2000,2000000000);
            journal.transition("xp_transaction",2,100,2,0,1,3000,3000000000L);
            journal.committed(2,0,1,4000,4000000000L);
        }
        var rows=Files.readAllLines(temp.resolve("ledger.jsonl"));
        assertEquals(4,rows.size());assertTrue(rows.get(1).contains("\"delta_xp\":200"));
        assertTrue(rows.get(2).contains("\"delta_xp\":-100"));
        assertTrue(rows.get(3).contains("\"kind\":\"save_committed\""));
        assertTrue(rows.get(3).contains("\"sequence\":3"));
        assertEquals("rw-------",PosixFilePermissions.toString(Files.getPosixFilePermissions(temp.resolve("ledger.jsonl"))));
    }
    @Test void wrongRateMissingMutationAndClockJumpCannotReachCompleteFooter() throws Exception {
        for(String fault:new String[]{"rate","state","clock"}) {
            try(var journal=open(fault)) {
                journal.transition("xp_transaction",1,fault.equals("state")?899:900,1,950,
                    fault.equals("rate")?2:1,fault.equals("clock")?5000:2000,2000000000);
                journal.committed(1,950,1,6000,6000000000L);
            }
            assertEquals(1,Files.readAllLines(temp.resolve(fault)).size());
        }
    }
    @Test void journalsAreNeverReusedAndSymlinkAncestorsRefused() throws Exception {
        try(var ignored=open("once")) {}
        assertThrows(IllegalStateException.class,()->open("once"));
        Files.createSymbolicLink(temp.resolve("link"),temp);
        assertThrows(IllegalStateException.class,()->open("link/other"));
    }
    @Test void syncFailureProducesInvalidationEvenIfBytesWereWritten() throws Exception {
        var captured=new ByteArrayOutputStream();var previous=System.err;
        try {
            System.setErr(new PrintStream(captured));
            try(var journal=MapleBenchXpLedger.Journal.open(config("broken"),table(),channel->{throw new IOException("private path");},1000,1000000000)) {
                journal.committed(1,900,1,2000,2000000000);
            }
        } finally {System.setErr(previous);}
        assertTrue(captured.toString().contains("MapleBench XP ledger failed"));
        assertFalse(captured.toString().contains("private path"));
        assertEquals(1,Files.readAllLines(temp.resolve("broken")).size());
    }
    @Test void nestedLevelUpIsCountedOnceByTheOuterTransaction() throws Exception {
        var field=MapleBenchXpLedger.class.getDeclaredField("journal");field.setAccessible(true);
        Object previous=field.get(null);
        try(var journal=MapleBenchXpLedger.Journal.open(config("nested"),table())) {
            field.set(null,journal);
            var outer=MapleBenchXpLedger.begin(7,9,1,900,"xp_transaction");
            var inner=MapleBenchXpLedger.begin(7,9,1,1100,"level_up");
            MapleBenchXpLedger.end(inner,2,100,1);
            MapleBenchXpLedger.end(outer,2,100,1);
            assertNull(MapleBenchXpLedger.begin(8,9,1,0,"xp_transaction"));
        } finally {field.set(null,previous);}
        var rows=Files.readAllLines(temp.resolve("nested"));
        assertEquals(2,rows.size());assertTrue(rows.get(1).contains("\"delta_xp\":200"));
    }
    @Test void capTruncationAndZeroGainArePreserved() throws Exception {
        var env=config("cap");env.put("MAPLEBENCH_XP_BASELINE_LEVEL","199");
        try(var journal=MapleBenchXpLedger.Journal.open(env,table(),channel->channel.force(true),1000,1000000000)) {
            journal.transition("xp_transaction",199,900,200,0,1,2000,2000000000);
            journal.transition("xp_transaction",200,0,200,0,1,3000,3000000000L);
        }
        var rows=Files.readAllLines(temp.resolve("cap"));
        assertTrue(rows.get(1).contains("\"delta_xp\":100"));assertTrue(rows.get(2).contains("\"delta_xp\":0"));
    }
}
