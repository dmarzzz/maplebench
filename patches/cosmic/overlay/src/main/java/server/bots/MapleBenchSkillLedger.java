package server.bots;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.*;

/** Independent, disabled-by-default native skill evidence. A sealed byte stream is
 * not a physics certificate. Missing native coverage remains explicitly unknown.
 * Runtime admission owns startWindow/sealWindow; neither sends gameplay input. */
public final class MapleBenchSkillLedger {
    private static volatile Journal journal;
    private static final ThreadLocal<Transaction> CURRENT = new ThreadLocal<>();
    private MapleBenchSkillLedger() {}

    public static synchronized void initializeFromEnvironment() {
        if (journal != null) throw new IllegalStateException("skill_ledger_already_initialized");
        journal = Journal.open(System.getenv());
    }
    public static synchronized String status() {
        if(journal==null) throw new IllegalStateException("skill_ledger_disabled");
        return journal.status();
    }
    public static synchronized boolean configured() { return journal!=null; }
    static synchronized String startWindow(int character,int account,Map<String,Object> initial) {
        if (journal == null) throw new IllegalStateException("skill_ledger_disabled");
        if(!journal.matches(character,account)) throw new IllegalStateException("skill_ledger_arm_identity");
        journal.start(System.currentTimeMillis(), System.nanoTime(),initial);
        return journal.status();
    }
    static synchronized String sealWindow(int character,int account,Map<String,Object> terminal) {
        if (journal == null) throw new IllegalStateException("skill_ledger_disabled");
        if(!journal.matches(character,account)) throw new IllegalStateException("skill_ledger_seal_identity");
        journal.seal(System.currentTimeMillis(), System.nanoTime(),terminal);
        return journal.status();
    }
    public static boolean enabled(int character, int account) {
        Journal j = journal;
        return j != null && j.matches(character, account) && j.accepts();
    }
    public static final class Transaction {
        final Transaction parent;
        final String id;
        final int character, account;
        final int subject;
        final String kind;
        boolean skillCostApplied;
        final List<String> resourceEvents=new ArrayList<>(), inventoryEvents=new ArrayList<>(), damageEvents=new ArrayList<>();
        private Transaction(Transaction parent, String id, int character, int account, String kind, int subject) {
            this.parent=parent; this.id=id; this.character=character; this.account=account;
            this.kind=kind; this.subject=subject;
        }
    }
    public static Transaction begin(int character, int account, String kind, int subject, int level) {
        if (!enabled(character, account)) return null;
        Journal j=journal;
        synchronized(j) {
            Transaction parent=CURRENT.get();
            String id=j.emit("transaction_begin", Map.of("transaction_kind",kind,"subject_id",subject,
                "skill_level",level,"parent_transaction_id",parent==null ? "" : parent.id),
                System.currentTimeMillis(),System.nanoTime());
            if(id==null) return null;
            Transaction t=new Transaction(parent,id,character,account,kind,subject); CURRENT.set(t); j.openTransactions++;
            return t;
        }
    }
    public static void end(Transaction t, boolean committed) {
        if(t==null) return;
        Journal j=journal;
        synchronized(j) {
            if(CURRENT.get()!=t) { j.invalidate("transaction_stack_mismatch"); return; }
            CURRENT.set(t.parent); j.openTransactions--;
            j.emit("transaction_end",Map.of("transaction_id",t.id,"committed",committed),
                System.currentTimeMillis(),System.nanoTime());
        }
    }
    public static String event(int character,int account,String kind,Map<String,Object> fields) {
        if(!enabled(character,account)) return null;
        try {
            Map<String,Object> payload=new TreeMap<>(fields);
            Transaction t=CURRENT.get();
            payload.put("transaction_id",t!=null && t.character==character && t.account==account ? t.id : "");
            String id=journal.emit(kind,payload,System.currentTimeMillis(),System.nanoTime());
            if(id!=null && t!=null && t.character==character && t.account==account) {
                if(kind.equals("resource_transaction")) t.resourceEvents.add(id);
                if(kind.equals("inventory_transaction")) t.inventoryEvents.add(id);
                if(kind.equals("monster_damage")) t.damageEvents.add(id);
            }
            return id;
        } catch(RuntimeException e) { journal.invalidate("hook_failure"); return null; }
    }
    static Transaction current(int character,int account) {
        Transaction t=CURRENT.get();
        return t!=null && t.character==character && t.account==account ? t : null;
    }
    public static void invalidate(int character,int account) {
        if(enabled(character,account)) journal.invalidate("hook_failure");
    }

    static final class Journal implements AutoCloseable {
        static final long MAX_BYTES=16L*1024*1024, MAX_EVENTS=100000;
        final FileChannel channel;
        final Map<String,Object> identity;
        final int character,account;
        final long durationNs;
        long originNs,originWall,lastElapsed=-1,sequence,bytes,openTransactions;
        String previous="0".repeat(64), failure="";
        boolean started,sealed;
        Journal(FileChannel channel,Map<String,Object> identity,int character,int account,long durationNs) {
            this.channel=channel;this.identity=Map.copyOf(identity);this.character=character;this.account=account;this.durationNs=durationNs;
        }
        static Journal open(Map<String,String> env) {
            String[] keys={"MAPLEBENCH_SKILL_JOURNAL","MAPLEBENCH_SKILL_TASK_ID","MAPLEBENCH_SKILL_BINDING_SHA256","MAPLEBENCH_SKILL_RUNTIME_SHA256","MAPLEBENCH_SKILL_DURATION_MS"};
            int present=0;for(String key:keys) if(env.containsKey(key)) present++;
            if(present==0) return null;
            if(present!=keys.length) throw new IllegalArgumentException("skill_ledger_incomplete_config");
            String run=env.get("MAPLEBENCH_TRIAL_ID"),instance=env.get("MAPLEBENCH_SERVER_INSTANCE_ID");
            if(run==null || !run.matches("[a-f0-9]{32}") || instance==null || !instance.matches("[a-f0-9]{32}")) throw new IllegalArgumentException("skill_ledger_identity");
            String binding=env.get(keys[2]),runtime=env.get(keys[3]),task=env.get(keys[1]);
            if(!binding.matches("[a-f0-9]{64}") || !runtime.matches("[a-f0-9]{64}") ||
                !task.equals("hero-180-toolkit-qualification-v1")) throw new IllegalArgumentException("skill_ledger_binding");
            int character=Integer.parseInt(env.get("MAPLEBENCH_PERSIST_CHARACTER_ID"));
            int account=Integer.parseInt(env.get("MAPLEBENCH_PERSIST_ACCOUNT_ID"));
            long duration=Long.parseLong(env.get(keys[4]));
            if(character<1 || account<1 || duration!=120000) throw new IllegalArgumentException("skill_ledger_bounds");
            Path path=Path.of(env.get(keys[0]));
            if(!path.isAbsolute() || !path.equals(path.normalize())) throw new IllegalArgumentException("skill_ledger_path");
            for(Path parent=path.getParent();parent!=null;parent=parent.getParent()) if(Files.isSymbolicLink(parent)) throw new IllegalArgumentException("skill_ledger_symlink");
            try {
                FileChannel channel=FileChannel.open(path,Set.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS),
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
                return new Journal(channel,Map.of("run_id",run,"server_instance_id",instance,"character_id",character,"account_id",account,
                    "task_id",task,"binding_sha256",binding,"runtime_sha256",runtime),character,account,duration*1000000);
            } catch(IOException e) { throw new IllegalStateException("skill_ledger_open_failed"); }
        }
        boolean matches(int c,int a) { return c==character && a==account; }
        synchronized boolean accepts() { return started && !sealed && failure.isEmpty(); }
        synchronized void start(long wall,long nano) { start(wall,nano,Map.of()); }
        synchronized void start(long wall,long nano,Map<String,Object> initial) {
            if(started || sealed || !failure.isEmpty()) throw new IllegalStateException("skill_ledger_start_reuse");
            started=true;originNs=nano;originWall=wall;
            emit("header",Map.of("start_monotonic_ns",nano,"deadline_elapsed_ns",durationNs,
                "movement_physics_validated",false,"teleport_causal_link_supported",false,
                "coverage_source","ordinary_hero_skill_handlers","initial",initial,
                "resource_coverage","apply_hp_mp_change_only","inventory_coverage","not_collected"),wall,nano);
            if(!failure.isEmpty()) throw new IllegalStateException("skill_ledger_start_failed");
        }
        synchronized void invalidate(String reason) { if(failure.isEmpty()) failure=reason; }
        synchronized String emit(String kind,Map<String,?> fields,long wall,long nano) {
            if(!accepts()) return null;
            long elapsed=nano-originNs;
            if(elapsed<0 || elapsed<lastElapsed || Math.abs((wall-originWall)-elapsed/1000000)>250) { invalidate("clock_discontinuity"); return null; }
            if(elapsed>durationNs+(kind.equals("terminal")?5000000000L:0)) { invalidate("duration_limit"); return null; }
            if(sequence>=MAX_EVENTS) { invalidate("event_limit"); return null; }
            Map<String,Object> row=new TreeMap<>(identity);
            row.put("schema_version",1);row.put("source","cosmic_native_skill_ledger");row.put("kind",kind);
            row.put("sequence",sequence);row.put("event_id",String.format("e%08d",sequence));
            row.put("elapsed_ns",elapsed);row.put("wall_ms",wall);row.put("previous_sha256",previous);row.put("data",fields);
            byte[] raw=(json(row)+"\n").getBytes(StandardCharsets.UTF_8);
            if(bytes+raw.length>MAX_BYTES) { invalidate("byte_limit"); return null; }
            try {
                ByteBuffer b=ByteBuffer.wrap(raw);while(b.hasRemaining()) channel.write(b);channel.force(true);
                previous=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(raw));
                bytes+=raw.length;sequence++;lastElapsed=elapsed;return (String)row.get("event_id");
            } catch(Exception e) { invalidate("journal_write_failed");return null; }
        }
        synchronized void seal(long wall,long nano) { seal(wall,nano,Map.of()); }
        synchronized void seal(long wall,long nano,Map<String,Object> terminal) {
            if(!accepts() || openTransactions!=0) { invalidate("seal_with_open_or_failed_state"); throw new IllegalStateException("skill_ledger_seal_failed"); }
            String id=emit("terminal",Map.of("complete",true,"event_count_before_terminal",sequence,
                "qualification_claim",false,"actor",terminal),wall,nano);
            if(id==null) throw new IllegalStateException("skill_ledger_seal_failed");
            sealed=true;
        }
        synchronized String status() { return json(Map.of("started",started,"sealed",sealed,"failure",failure,
            "events",sequence,"bytes",bytes,"sha256_last_line",previous,"start_monotonic_ns",originNs,"start_wall_ms",originWall,"duration_ns",durationNs)); }
        @Override public synchronized void close() throws IOException { channel.close(); }
    }
    static String json(Object value) {
        if(value==null) return "null";
        if(value instanceof String s) return MapleBenchJson.quote(s);
        if(value instanceof Boolean || value instanceof Integer || value instanceof Long || value instanceof Short || value instanceof Byte) return value.toString();
        if(value instanceof Map<?,?> m) {
            StringJoiner j=new StringJoiner(",","{","}");
            for(var entry:new TreeMap<>(m).entrySet()) j.add(json(entry.getKey())+":"+json(entry.getValue()));
            return j.toString();
        }
        if(value instanceof Iterable<?> values) { StringJoiner j=new StringJoiner(",","[","]");for(Object v:values) j.add(json(v));return j.toString(); }
        throw new IllegalArgumentException("unsupported_skill_ledger_value");
    }
}
