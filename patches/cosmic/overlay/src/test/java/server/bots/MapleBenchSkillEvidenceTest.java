package server.bots;

import client.BuffStat;
import client.Character;
import client.Job;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.awt.Point;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/** Native observations with mocked actor state, not native gameplay success. */
class MapleBenchSkillEvidenceTest {
    @TempDir Path temp;
    MapleBenchSkillLedger.Journal bound;

    Map<String,String> config(String name) {
        var env=new HashMap<String,String>();
        env.put("MAPLEBENCH_TRIAL_ID","a".repeat(32));
        env.put("MAPLEBENCH_SERVER_INSTANCE_ID","b".repeat(32));
        env.put("MAPLEBENCH_PERSIST_CHARACTER_ID","7");
        env.put("MAPLEBENCH_PERSIST_ACCOUNT_ID","9");
        env.put("MAPLEBENCH_SKILL_JOURNAL",temp.resolve(name).toString());
        env.put("MAPLEBENCH_SKILL_TASK_ID","hero-180-toolkit-qualification-v1");
        env.put("MAPLEBENCH_SKILL_BINDING_SHA256","c".repeat(64));
        env.put("MAPLEBENCH_SKILL_RUNTIME_SHA256","d".repeat(64));
        env.put("MAPLEBENCH_SKILL_DURATION_MS","120000");
        return env;
    }
    MapleBenchSkillLedger.Journal open(String name) {
        return MapleBenchSkillLedger.Journal.open(config(name));
    }
    void bind(String name) throws Exception {
        bound=open(name);
        var field=MapleBenchSkillLedger.class.getDeclaredField("journal");
        field.setAccessible(true);assertNull(field.get(null));field.set(null,bound);
    }
    @AfterEach void unbind() throws Exception {
        if(bound!=null) {
            var field=MapleBenchSkillLedger.class.getDeclaredField("journal");
            field.setAccessible(true);field.set(null,null);bound.close();
            var current=MapleBenchSkillLedger.class.getDeclaredField("CURRENT");
            current.setAccessible(true);((ThreadLocal<?>)current.get(null)).remove();
        }
    }
    List<String> lines(String name) throws Exception {return Files.readAllLines(temp.resolve(name));}
    String event(List<String> rows,String kind) {
        return rows.stream().filter(row->row.contains("\"kind\":\""+kind+"\"")).findFirst().orElseThrow();
    }

    @Test void disabledAndIncompleteOrWrongProtocolConfiguration() {
        assertNull(MapleBenchSkillLedger.Journal.open(Map.of()));
        assertThrows(IllegalArgumentException.class,()->MapleBenchSkillLedger.Journal.open(Map.of("MAPLEBENCH_SKILL_JOURNAL","x")));
        for(var change:List.of(Map.entry("MAPLEBENCH_SKILL_TASK_ID","invented"),
                Map.entry("MAPLEBENCH_SKILL_DURATION_MS","120001"),
                Map.entry("MAPLEBENCH_SKILL_BINDING_SHA256","not-a-hash"),
                Map.entry("MAPLEBENCH_PERSIST_CHARACTER_ID","0"))) {
            var env=config("bad");env.put(change.getKey(),change.getValue());
            assertThrows(IllegalArgumentException.class,()->MapleBenchSkillLedger.Journal.open(env));
        }
        assertFalse(Files.exists(temp.resolve("bad")));
    }

    @Test void privateCreateOnceAndSymlinkRefusal() throws Exception {
        try(var journal=open("once")) {assertFalse(journal.accepts());}
        assertEquals("rw-------",PosixFilePermissions.toString(Files.getPosixFilePermissions(temp.resolve("once"))));
        assertThrows(IllegalStateException.class,()->open("once"));
        Files.createSymbolicLink(temp.resolve("link"),temp);
        var env=config("ignored");env.put("MAPLEBENCH_SKILL_JOURNAL",temp.resolve("link/new").toString());
        assertThrows(IllegalArgumentException.class,()->MapleBenchSkillLedger.Journal.open(env));
    }

    @Test void actualBytesAreHashChainedAndSealHasNoQualificationClaim() throws Exception {
        try(var journal=open("chain")) {
            journal.start(1000,1000000000,Map.of("snapshot_atomic",false));
            journal.emit("observed",Map.of("value",9),1010,1010000000);
            journal.seal(1020,1020000000,Map.of("snapshot_atomic",false));
            assertTrue(journal.sealed);assertNull(journal.emit("late",Map.of(),1030,1030000000));
            assertThrows(IllegalStateException.class,()->journal.start(1040,1040000000));
        }
        var rows=lines("chain");assertEquals(3,rows.size());String previous="0".repeat(64);
        for(int sequence=0;sequence<rows.size();sequence++) {
            String line=rows.get(sequence);
            assertTrue(line.contains("\"sequence\":"+sequence));
            assertTrue(line.contains("\"previous_sha256\":\""+previous+"\""));
            previous=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest((line+"\n").getBytes(StandardCharsets.UTF_8)));
        }
        assertTrue(rows.get(2).contains("\"qualification_claim\":false"));
    }

    @Test void clockEventByteAndDeadlineFailuresCannotSeal() throws Exception {
        for(String fault:List.of("clock","events","bytes","deadline","open")) {
            try(var journal=open(fault)) {
                journal.start(1000,1000000000);
                if(fault.equals("events"))journal.sequence=MapleBenchSkillLedger.Journal.MAX_EVENTS;
                if(fault.equals("bytes"))journal.bytes=MapleBenchSkillLedger.Journal.MAX_BYTES;
                if(fault.equals("open"))journal.openTransactions=1;
                else if(fault.equals("deadline"))journal.emit("observed",Map.of(),121001,121001000000L);
                else journal.emit("observed",Map.of(),fault.equals("clock")?2000:1010,1010000000);
                assertThrows(IllegalStateException.class,()->journal.seal(122000,122000000000L));
                assertFalse(journal.sealed);assertFalse(journal.failure.isEmpty());
            }
            assertFalse(Files.readString(temp.resolve(fault)).contains("\"kind\":\"terminal\""));
        }
    }

    @Test void terminalGraceIsBoundedToFiveSeconds() throws Exception {
        try(var journal=open("grace")) {
            journal.start(1000,1000000000);journal.seal(126000,126000000000L);assertTrue(journal.sealed);
        }
        try(var journal=open("expired")) {
            journal.start(1000,1000000000);
            assertThrows(IllegalStateException.class,()->journal.seal(126001,126001000000L));
            assertEquals("duration_limit",journal.failure);
        }
    }

    Character actor(AtomicInteger hp,AtomicInteger mp,Map<BuffStat,Integer> buffs,Map<BuffStat,Integer> sources) {
        Character c=mock(Character.class);
        when(c.getId()).thenReturn(7);when(c.getAccountID()).thenReturn(9);
        when(c.getJob()).thenReturn(Job.HERO);when(c.getLevel()).thenReturn(180);
        when(c.getMapId()).thenReturn(240040511);when(c.getPosition()).thenReturn(new Point(10,20));
        when(c.getHp()).thenAnswer(call->hp.get());when(c.getMp()).thenAnswer(call->mp.get());
        when(c.getCurrentMaxHp()).thenReturn(12000);when(c.getCurrentMaxMp()).thenReturn(6000);
        when(c.getBuffedValue(any(BuffStat.class))).thenAnswer(call->buffs.get(call.getArgument(0)));
        when(c.getBuffSource(any(BuffStat.class))).thenAnswer(call->sources.getOrDefault(call.getArgument(0),-1));
        when(c.getTotalStr()).thenReturn(900);when(c.getTotalDex()).thenReturn(100);
        when(c.getTotalWatk()).thenReturn(100);when(c.getTotalWdef()).thenReturn(500);
        when(c.isAlive()).thenAnswer(call->hp.get()>0);when(c.isLoggedinWorld()).thenReturn(true);
        return c;
    }

    @Test void buffObservationBindsActualResourcesStateAndChildIds() throws Exception {
        bind("buff");var hp=new AtomicInteger(12000);var mp=new AtomicInteger(6000);
        var buffs=new EnumMap<BuffStat,Integer>(BuffStat.class);var sources=new EnumMap<BuffStat,Integer>(BuffStat.class);
        var c=actor(hp,mp,buffs,sources);MapleBenchSkillHooks.startWindow(c);
        MapleBenchSkillHooks.resource(c,12000,6000,12000,6000); // Unrelated to any cast.
        var use=MapleBenchSkillHooks.skillBegin(c,1101004,20);
        hp.set(11990);mp.set(5980);MapleBenchSkillHooks.resource(c,12000,6000,11990,5980);
        buffs.put(BuffStat.BOOSTER,-2);sources.put(BuffStat.BOOSTER,1101004);
        MapleBenchSkillHooks.skillEnd(c,use,1101004,20,true);MapleBenchSkillHooks.sealWindow(c);
        var rows=lines("buff");assertEquals(6,rows.size());
        String summary=event(rows,"skill_commit");
        assertTrue(summary.contains("\"resource_event_ids\":[\"e00000002\"]"));
        assertTrue(summary.contains("\"active_buffs_after\":[[1101004,-2]]"));
        assertTrue(summary.contains("\"endpoint_snapshots_atomic\":false"));
        assertTrue(summary.contains("\"hp_before\":12000"));assertTrue(summary.contains("\"hp_after\":11990"));
        assertTrue(summary.contains("\"route\":\"special_move_apply_to\""));
        assertTrue(event(rows,"resource_transaction").contains("\"transaction_id\":\"e00000001\""));
        verify(c,never()).addMP(anyInt());verify(c,never()).addHP(anyInt());
    }

    @Test void attackRequiresActualCostAndDamageKeepsNativeLoss() throws Exception {
        bind("attack");var hp=new AtomicInteger(12000);var mp=new AtomicInteger(6000);
        var buffs=new EnumMap<BuffStat,Integer>(BuffStat.class);var sources=new EnumMap<BuffStat,Integer>(BuffStat.class);
        var c=actor(hp,mp,buffs,sources);MapleBenchSkillHooks.startWindow(c);
        buffs.put(BuffStat.COMBO,2);sources.put(BuffStat.COMBO,1111002);
        var use=MapleBenchSkillHooks.attackBegin(c,1111005,30);
        mp.set(5990);MapleBenchSkillHooks.resource(c,12000,6000,12000,5990);
        MapleBenchSkillHooks.attackCostApplied(c,1111005,true);
        MapleBenchSkillHooks.monsterDamage(c,81,1000,0,true);buffs.put(BuffStat.COMBO,1);
        MapleBenchSkillHooks.attackEnd(c,use,true);MapleBenchSkillHooks.sealWindow(c);
        var rows=lines("attack");assertEquals(7,rows.size());String summary=event(rows,"skill_commit");
        assertTrue(summary.contains("\"committed\":true"));
        assertTrue(summary.contains("\"combo_orbs_before\":1"));assertTrue(summary.contains("\"combo_orbs_after\":0"));
        assertTrue(summary.contains("\"damage_event_ids\":[\"e00000003\"]"));
        assertTrue(event(rows,"monster_damage").contains("\"hp_loss\":1000"));
        assertTrue(event(rows,"monster_damage").contains("\"killed\":true"));
    }

    @Test void wrongSkillCostAndUnscopedOrWrongActorDamageNeverQualify() throws Exception {
        bind("rejected");var c=actor(new AtomicInteger(12000),new AtomicInteger(6000),new EnumMap<>(BuffStat.class),new EnumMap<>(BuffStat.class));
        MapleBenchSkillHooks.startWindow(c);
        assertNull(MapleBenchSkillHooks.attackBegin(c,0,0));MapleBenchSkillHooks.monsterDamage(c,1,50,0,true);
        var use=MapleBenchSkillHooks.attackBegin(c,1121008,30);
        MapleBenchSkillHooks.attackCostApplied(c,1121006,true);
        var other=mock(Character.class);when(other.getId()).thenReturn(8);when(other.getAccountID()).thenReturn(9);
        MapleBenchSkillHooks.monsterDamage(other,1,50,0,true);
        MapleBenchSkillHooks.attackEnd(c,use,true);MapleBenchSkillHooks.sealWindow(c);
        var rows=lines("rejected");assertEquals(5,rows.size());
        assertTrue(event(rows,"skill_commit").contains("\"committed\":false"));
        assertTrue(rows.stream().noneMatch(row->row.contains("\"kind\":\"monster_damage\"")));
    }

    @Test void wrongOwnerAndMismatchedHookEndpointsFailClosed() throws Exception {
        bind("mismatch");var c=actor(new AtomicInteger(12000),new AtomicInteger(6000),new EnumMap<>(BuffStat.class),new EnumMap<>(BuffStat.class));
        assertThrows(IllegalStateException.class,()->MapleBenchSkillLedger.startWindow(8,9,Map.of()));
        MapleBenchSkillHooks.startWindow(c);assertNull(MapleBenchSkillLedger.begin(8,9,"skill_apply",1121008,30));
        var use=MapleBenchSkillHooks.skillBegin(c,1111002,30);
        MapleBenchSkillHooks.skillEnd(c,use,1111002,29,true);
        assertThrows(IllegalStateException.class,()->MapleBenchSkillHooks.sealWindow(c));
        assertFalse(Files.readString(temp.resolve("mismatch")).contains("\"kind\":\"terminal\""));
    }
}
