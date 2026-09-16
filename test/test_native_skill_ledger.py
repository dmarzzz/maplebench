"""Actual native method hooks and independent journal, compiled in inert JVMs.

No server, database, asset loader or gameplay process is started by these tests.
"""
from pathlib import Path
import os, shutil, subprocess, tempfile, unittest
from test_client_mob_lifecycle import method
ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'test/fixtures/native-skill-ledger'
OVERLAY=ROOT/'patches/cosmic/overlay/src/main/java/server/bots'

CORE=r'''
package server.bots;
import java.nio.file.*;
import java.util.*;
import java.security.MessageDigest;
public class SkillLedgerProbe {
 static void need(boolean b){if(!b)throw new AssertionError();}
 static Map<String,String> env(Path path){return Map.of(
 "MAPLEBENCH_TRIAL_ID","a".repeat(32),"MAPLEBENCH_SERVER_INSTANCE_ID","b".repeat(32),
 "MAPLEBENCH_PERSIST_CHARACTER_ID","7","MAPLEBENCH_PERSIST_ACCOUNT_ID","9",
 "MAPLEBENCH_SKILL_JOURNAL",path.toString(),"MAPLEBENCH_SKILL_TASK_ID","potion-use-v1",
 "MAPLEBENCH_SKILL_BINDING_SHA256","c".repeat(64),"MAPLEBENCH_SKILL_RUNTIME_SHA256","d".repeat(64),"MAPLEBENCH_SKILL_DURATION_MS","120000");}
 public static void main(String[] args)throws Exception{
 Path root=Path.of(args[0]);
 need(MapleBenchSkillLedger.Journal.open(Map.of())==null);
 try{MapleBenchSkillLedger.Journal.open(Map.of("MAPLEBENCH_SKILL_JOURNAL","x"));throw new AssertionError();}catch(IllegalArgumentException expected){}
 Path p=root.resolve("valid.jsonl");
 try(var j=MapleBenchSkillLedger.Journal.open(env(p))){
  need(j.emit("ignored",Map.of(),1000,1000000000)==null);
  j.start(1000,1000000000,Map.of("quantity",1,"mp",100,"max_mp",1000,"alive",true,"online",true));need(j.matches(7,9)&&!j.matches(8,9));
  need(j.emit("resource_transaction",Map.of("mp_before",100,"mp_after",1000),1010,1010000000).equals("e00000001"));
  j.seal(1020,1020000000,Map.of("quantity",0,"mp",1000,"max_mp",1000,"alive",true,"online",true));need(j.sealed);
  need(j.emit("too_late",Map.of(),1030,1030000000)==null);
  try{j.start(1040,1040000000);throw new AssertionError();}catch(IllegalStateException expected){}
 }
 List<String> rows=Files.readAllLines(p);need(rows.size()==3);
 String hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest((rows.get(0)+"\n").getBytes(java.nio.charset.StandardCharsets.UTF_8)));
 need(rows.get(1).contains("\"previous_sha256\":\""+hash+"\""));
 need(rows.get(0).contains("\"movement_physics_validated\":false"));
 need(rows.get(0).contains("\"quantity\":1"));need(rows.get(2).contains("\"quantity\":0"));need(rows.get(2).contains("\"online\":true"));
 need(rows.get(0).contains("\"teleport_causal_link_supported\":false"));
 try{MapleBenchSkillLedger.Journal.open(env(p));throw new AssertionError();}catch(IllegalStateException expected){}
 for(String cause:List.of("clock","bytes","events","transaction","io")){
  Path f=root.resolve(cause+".jsonl");
  try(var j=MapleBenchSkillLedger.Journal.open(env(f))){
   j.start(1000,1000000000);
   if(cause.equals("clock")) j.emit("backward",Map.of(),999,999000000);
   if(cause.equals("bytes")){j.bytes=j.MAX_BYTES-1;j.emit("overflow",Map.of(),1001,1001000000);}
   if(cause.equals("events")){j.sequence=j.MAX_EVENTS;j.emit("overflow",Map.of(),1001,1001000000);}
   if(cause.equals("transaction"))j.openTransactions=1;
   if(cause.equals("io")){j.channel.close();j.emit("failed",Map.of(),1001,1001000000);}
   try{j.seal(1002,1002000000);throw new AssertionError();}catch(IllegalStateException expected){}
   need(!j.sealed);
  }
  need(!Files.readString(f).contains("\"kind\":\"terminal\""));
 }
 Path link=root.resolve("link");Files.createSymbolicLink(link,root);
 try{MapleBenchSkillLedger.Journal.open(env(link.resolve("new")));throw new AssertionError();}catch(IllegalArgumentException expected){}
 // Real journal context: nested helper events cannot be attributed to its parent.
 var field=MapleBenchSkillLedger.class.getDeclaredField("journal");field.setAccessible(true);
 try(var j=MapleBenchSkillLedger.Journal.open(env(root.resolve("nested.jsonl")))){
  field.set(null,j);MapleBenchSkillLedger.startWindow(7,9,Map.of("mp",100,"max_mp",1000,"quantity",1));
  var outer=MapleBenchSkillLedger.begin(7,9,"item_use",2000005,0);
  var inner=MapleBenchSkillLedger.begin(7,9,"item_use",2000005,0);
  MapleBenchSkillLedger.event(7,9,"resource_transaction",Map.of("mp_after",1000));
  need(inner.resourceEvents.size()==1&&outer.resourceEvents.isEmpty());
  MapleBenchSkillLedger.end(inner,true);MapleBenchSkillLedger.end(outer,true);MapleBenchSkillLedger.sealWindow(7,9,Map.of("mp",1000,"max_mp",1000,"quantity",0,"alive",true,"online",true));
 }finally{field.set(null,null);}
 System.out.println("journal chain, caps, failed IO/clock/open transaction, identity, reuse, nesting passed");
 }
}
'''

HANDLERS=r'''
import java.util.*;
import java.util.concurrent.locks.*;
public class NativeHandlersProbe {
 static class PacketCreator{static Object enableActions(){return null;}}
 static class Disease{static final int DARKNESS=1,WEAKEN=2,SLOW=3,SEAL=4,CURSE=5,ZOMBIFY=6;}
 static class ItemId{static final int ALL_CURE_POTION=1,EYEDROP=2,TONIC=3,HOLY_WATER=4,HAPPY_BIRTHDAY=5;}
 static class ItemConstants{static boolean isTownScroll(int id){return false;}}
 enum InventoryType{USE}
 static class Item{int quantity,id=2000005;Item(int q){quantity=q;}int getQuantity(){return quantity;}int getItemId(){return id;}void setQuantity(short q){quantity=q;}}
 static class Inventory{
  Character owner;InventoryType type=InventoryType.USE;Item item=new Item(1);
  Item getItem(short slot){return slot==1?item:null;}void removeSlot(short slot){item=null;}
  // ACTUAL_INVENTORY
 }
 static class Client{Character character;void sendPacket(Object p){} }
 static class InventoryManipulator{static void removeFromSlot(Client c,InventoryType t,short slot,short q,boolean drop){c.character.inventory.removeItem(slot,q,false);}}
 static class StatEffect{boolean applyTo(Character c){return c.applyHpMpChange(0,0,900);} }
 static class ItemInformationProvider{static ItemInformationProvider getInstance(){return new ItemInformationProvider();}StatEffect getItemEffect(int id){return new StatEffect();}}
 static class World{List<Character> getCharacters(){return List.of();}}
 static class Character{
  int hp=1000,mp=100;boolean gm=false;Inventory inventory=new Inventory();Client client=new Client();
  Lock effLock=new ReentrantLock(),statWlock=new ReentrantLock();
  Character(){inventory.owner=this;client.character=this;}
  Client getClient(){return client;}boolean isAlive(){return hp>0;}Inventory getInventory(InventoryType t){return inventory;}
  void dispelDebuffs(){}void dispelDebuff(int d){}World getMap(){return new World();}
  boolean hasDisease(int d){return false;}boolean isGM(){return gm;}
  void updateHpMp(int h,int m){hp=Math.min(1000,h);mp=Math.min(1000,m);}
  void triggerAutopotAfterStatLoss(int h,int m){}
  // ACTUAL_RESOURCE
 }
 static class Hooks{
  static List<String> events=new ArrayList<>();static int resourceBefore,resourceAfter,inventoryBefore,inventoryAfter;static boolean committed;
  static Object itemBegin(Character c,int item,String route){events.add(route);return new Object();}
  static void itemEnd(Character c,Object t,boolean ok){committed=ok;events.add("end");}
  static void itemEffect(Character c,int id,boolean applied){events.add("effect:"+applied);}
  static void resource(Character c,int h,int m,int ha,int ma){if(!((ReentrantLock)c.statWlock).isHeldByCurrentThread())throw new AssertionError();resourceBefore=m;resourceAfter=ma;events.add("resource");}
  static void inventory(Character c,InventoryType t,int s,int id,int b,int a){inventoryBefore=b;inventoryAfter=a;events.add("inventory");}
  static void reset(){events.clear();committed=false;}
 }
 // ACTUAL_USE
 static void need(boolean b){if(!b)throw new AssertionError(Hooks.events.toString());}
 public static void main(String[] args){
  Character c=new Character();Hooks.reset();
  need(consumeUseItemObserved(c,(short)1,2000005,"ordinary_item_packet"));
  need(c.inventory.item==null&&c.mp==1000&&Hooks.committed);
  need(Hooks.events.equals(List.of("ordinary_item_packet","inventory","resource","effect:true","end")));
  need(Hooks.inventoryBefore==1&&Hooks.inventoryAfter==0&&Hooks.resourceBefore==100&&Hooks.resourceAfter==1000);
  Hooks.reset();need(!consumeUseItemObserved(c,(short)1,2000005,"ordinary_item_packet"));
  need(!Hooks.committed&&Hooks.events.equals(List.of("ordinary_item_packet","end")));
  c=new Character();c.hp=0;Hooks.reset();need(!consumeUseItem(c,(short)1,2000005));need(c.inventory.item.quantity==1&&c.mp==100);
  c=new Character();Hooks.reset();need(!consumeUseItem(c,(short)1,2000006));need(c.inventory.item.quantity==1);
  c=new Character();Hooks.reset();need(!c.applyHpMpChange(0,0,-101));need(c.mp==100&&Hooks.events.isEmpty());
  c=new Character();Hooks.reset();need(consumeUseItem(c,(short)1,2000005));need(Hooks.events.get(0).equals("native_item_helper"));
  System.out.println("actual item/resource/inventory methods: positive, empty, dead, wrong item, insufficient MP and helper route passed");
 }
}
'''

def apply_exact_hunks(root):
    # Excerpt fixtures omit unrelated thousands of Character lines. Unified-diff
    # line numbers are hints; require each complete old hunk exactly once instead.
    path=None;old=[];new=[]
    def apply():
        if not old:return
        text=path.read_text();before=''.join(old);after=''.join(new)
        if text.count(before)!=1:raise AssertionError('native patch hunk missing or ambiguous')
        path.write_text(text.replace(before,after,1))
    for line in (ROOT/'patches/cosmic/0003-native-skill-evidence.patch').read_text().splitlines(True):
        if line.startswith('--- '):apply();old=[];new=[]
        elif line.startswith('+++ '):path=root/line[6:].strip()
        elif line.startswith('@@ '):apply();old=[];new=[]
        elif line.startswith(' '):old.append(line[1:]);new.append(line[1:])
        elif line.startswith('-'):old.append(line[1:])
        elif line.startswith('+'):new.append(line[1:])
    apply()

def prepare(directory):
    root=Path(directory)
    for src in FIXTURE.rglob('*.java'):
        target=root/'src/main/java'/src.relative_to(FIXTURE);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
    apply_exact_hunks(root)
    use=(root/'src/main/java/net/server/channel/handlers/UseItemHandler.java').read_text()
    body='\n'.join(method(use,s) for s in ['    public static boolean consumeUseItem(', '    private static boolean consumeUseItemObserved(', '    private static boolean consumeUseItemImpl(', '    private static void remove('])
    inventory=method((root/'src/main/java/client/inventory/Inventory.java').read_text(),'    public void removeItem(short slot, short quantity, boolean allowZero)')
    resource=method((root/'src/main/java/client/Character.java').read_text(),'    public boolean applyHpMpChange(')
    h=HANDLERS.replace('// ACTUAL_USE',body).replace('// ACTUAL_INVENTORY',inventory).replace('// ACTUAL_RESOURCE',resource).replace('server.bots.MapleBenchSkillHooks','Hooks')
    paths=[]
    for name,contents in [('NativeHandlersProbe.java',h),('server/bots/SkillLedgerProbe.java',CORE)]:
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(contents);paths.append(p)
    for name in ['MapleBenchSkillLedger.java','MapleBenchJson.java']:
        p=root/'server/bots'/name;shutil.copyfile(OVERLAY/name,p);paths.append(p)
    return paths

class NativeSkillLedgerTest(unittest.TestCase):
    def test_patch_matches_pinned_methods(self):
        with tempfile.TemporaryDirectory() as d: prepare(d)
    def test_actual_native_methods_and_journal(self):
        home=os.environ.get('JAVA_HOME');javac=str(Path(home)/'bin/javac') if home else shutil.which('javac')
        if not javac or subprocess.run([javac,'-version'],capture_output=True,timeout=5).returncode:self.skipTest('functional JDK required')
        with tempfile.TemporaryDirectory() as d:
            paths=prepare(d)
            subprocess.run([javac,'-J-Xmx128m','-d',d,*map(str,paths)],check=True,capture_output=True,timeout=30)
            java=str(Path(javac).with_name('java'))
            for main in ['NativeHandlersProbe','server.bots.SkillLedgerProbe']:
                subprocess.run([java,'-Xmx128m','-cp',d,main,d],check=True,capture_output=True,timeout=10)

if __name__=='__main__': unittest.main()
