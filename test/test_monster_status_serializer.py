"""Compile production PacketCreator status methods in an inert packet harness."""
from pathlib import Path
import os,shutil,subprocess,tempfile,unittest
from test_client_mob_lifecycle import method
ROOT=Path(__file__).resolve().parents[1];FIXTURE=ROOT/'test/fixtures/client-mob-status'
BASE=r'''
import java.io.ByteArrayOutputStream;
import java.util.*;
import java.util.Map.Entry;
public class StatusSerializerProbe {
 enum SendOpcode {APPLY_MONSTER_STATUS,CANCEL_MONSTER_STATUS}
 static class Packet {ByteArrayOutputStream data=new ByteArrayOutputStream();byte[] bytes(){return data.toByteArray();}}
 static class OutPacket extends Packet {
  static OutPacket create(SendOpcode opcode){OutPacket p=new OutPacket();p.writeShort(opcode==SendOpcode.APPLY_MONSTER_STATUS?242:243);return p;}
  void writeByte(int n){data.write(n&255);}void writeShort(int n){writeByte(n);writeByte(n>>>8);}
  void writeInt(int n){writeShort(n);writeShort(n>>>16);}void writeLong(long n){writeInt((int)n);writeInt((int)(n>>>32));}
 }
 record Skill(int id){int getId(){return id;}}
 record MobSkillType(int id){int getId(){return id;}}
 record MobSkillId(MobSkillType type,int level){}
 record MobSkill(MobSkillId id,int x,int y){MobSkillId getId(){return id;}int getX(){return x;}int getY(){return y;}}
 record MonsterStatusEffect(Map<MonsterStatus,Integer> stati,Skill skill,MobSkill mobSkill){
  Map<MonsterStatus,Integer>getStati(){return stati;}Skill getSkill(){return skill;}
  MobSkill getMobSkill(){return mobSkill;}boolean isMonsterSkill(){return mobSkill!=null;}}
'''
CHECK=r'''
 static void need(boolean ok){if(!ok)throw new AssertionError();}
 static int integer(byte[] b,int at){return (b[at]&255)|((b[at+1]&255)<<8)|((b[at+2]&255)<<16)|(b[at+3]<<24);}
 public static void main(String[] args){
  byte[] apply=null,spawn=null,cancel=null;
  List<MonsterStatus> selected=List.of(MonsterStatus.WATK,MonsterStatus.WDEF,MonsterStatus.NEUTRALISE,MonsterStatus.SPEED,MonsterStatus.STUN,MonsterStatus.FREEZE);
  for(int run=0;run<100;run++){
   List<MonsterStatus> order=new ArrayList<>(selected);Collections.shuffle(order,new Random(run));
   Map<MonsterStatus,Integer> values=new LinkedHashMap<>();for(MonsterStatus s:order)values.put(s,s.ordinal()+100);
   MonsterStatusEffect effect=new MonsterStatusEffect(values,new Skill(3121007),null);
   byte[] a=applyMonsterStatus(77,effect,null).bytes();byte[] c=cancelMonsterStatus(77,values).bytes();
   Map<MonsterStatus,MonsterStatusEffect> snapshots=new LinkedHashMap<>();for(MonsterStatus s:order)snapshots.put(s,effect);
   OutPacket p=new OutPacket();encodeTemporary(p,snapshots);byte[] b=p.bytes();
   if(run==0){apply=a;spawn=b;cancel=c;}else{need(Arrays.equals(apply,a));need(Arrays.equals(spawn,b));need(Arrays.equals(cancel,c));}
   int first=0,second=0;for(MonsterStatus s:selected){if(s.isFirst())first|=s.getValue();else second|=s.getValue();}
   need(integer(a,6)==0&&integer(a,10)==0&&integer(a,14)==first&&integer(a,18)==second);
   need(integer(c,14)==first&&integer(c,18)==second&&c.length==26);
   int offset=22;for(MonsterStatus s:selected){need((a[offset]&255)==s.ordinal()+100);need(integer(a,offset+2)==3121007);offset+=8;}
   need(a[offset]==selected.size()&&integer(a,offset+1)==0);
   need(integer(b,0)==first&&integer(b,4)==first&&integer(b,8)==(second&~3)&&integer(b,12)==(second&~3));
   offset=16;for(MonsterStatus s:selected){if(s==MonsterStatus.WATK||s==MonsterStatus.WDEF)continue;need((b[offset]&255)==s.ordinal()+100);offset+=8;}
   need(b.length==offset); // no mob-skill reflect counters in a player effect
  }
  Map<MonsterStatus,Integer> reflected=new LinkedHashMap<>();reflected.put(MonsterStatus.MAGIC_REFLECT,1);reflected.put(MonsterStatus.WEAPON_REFLECT,1);
  MobSkill mob=new MobSkill(new MobSkillId(new MobSkillType(143),7),33,44);
  MonsterStatusEffect e=new MonsterStatusEffect(reflected,null,mob);Map<MonsterStatus,MonsterStatusEffect> states=new LinkedHashMap<>();for(MonsterStatus s:reflected.keySet())states.put(s,e);
  OutPacket p=new OutPacket();encodeTemporary(p,states);byte[] b=p.bytes();need(integer(b,32)==33&&integer(b,36)==44&&integer(b,40)==100);
  need(integer(b,18)==(143|(7<<16))); // actual writeMobSkillId short/short format
  Packet empty=applyMonsterStatus(3,new MonsterStatusEffect(Map.of(),new Skill(1),null),null);need(empty.bytes().length==27);
  System.out.println("100 shuffled multi-status apply/spawn/cancel cases and mob reflection/empty cases passed");
 }
}
'''

def prepare(directory):
 root=Path(directory);dest=root/'src/main/java/tools/PacketCreator.java';dest.parent.mkdir(parents=True)
 shutil.copyfile(FIXTURE/'PacketCreator.java',dest)
 subprocess.run(['patch','-p1','--batch','--fuzz=0','-i',str(ROOT/'patches/cosmic/0002-monster-status-order.patch')],cwd=root,check=True,capture_output=True,timeout=5)
 source=dest.read_text();bodies='\n'.join(method(source,s) for s in ['    private static void writeMobSkillId','    private static void writeLongEncodeTemporaryMask','    private static void writeIntMask','    private static void encodeTemporary','    public static Packet applyMonsterStatus','    public static Packet cancelMonsterStatus'])
 enum=(FIXTURE/'MonsterStatus.java').read_text();enum=enum[enum.index('public enum MonsterStatus'):]
 out=root/'StatusSerializerProbe.java';out.write_text(BASE+enum+bodies+CHECK);return out

class MonsterStatusSerializerTest(unittest.TestCase):
 def test_actual_serializer_shuffled_maps(self):
  java_home=os.environ.get('JAVA_HOME');javac=str(Path(java_home)/'bin/javac') if java_home else shutil.which('javac')
  if not javac:self.skipTest('JDK required')
  check=subprocess.run([javac,'-version'],capture_output=True,timeout=5)
  if check.returncode:self.skipTest('functional JDK required')
  with tempfile.TemporaryDirectory() as d:
   path=prepare(d);subprocess.run([javac,'-J-Xmx128m',str(path)],check=True,capture_output=True,timeout=30)
   java=str(Path(javac).with_name('java'));subprocess.run([java,'-Xmx128m','-cp',d,'StatusSerializerProbe'],check=True,capture_output=True,timeout=10)
