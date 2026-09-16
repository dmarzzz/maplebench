package server.bots;

import client.Character;
import client.inventory.InventoryType;
import server.maps.Foothold;
import server.movement.AbsoluteLifeMovement;
import server.movement.LifeMovementFragment;
import java.awt.Point;
import java.util.*;

/** Observes ordinary native handlers; never grants a skill, item, position or XP.
 * Handler success and causal child mutations are recorded separately. */
public final class MapleBenchSkillHooks {
    private MapleBenchSkillHooks() {}
    public static String startWindow(Character c) {
        // The trusted runtime passes the actual bound character, never endpoint-supplied stats.
        return MapleBenchSkillLedger.startWindow(c.getId(),c.getAccountID(),snapshot(c,2000005));
    }
    public static String sealWindow(Character c) {
        return MapleBenchSkillLedger.sealWindow(c.getId(),c.getAccountID(),snapshot(c,2000005));
    }
    public static final class ItemUse {
        final MapleBenchSkillLedger.Transaction transaction;
        final Map<String,Object> before;
        final int item;
        final String route;
        ItemUse(MapleBenchSkillLedger.Transaction t,Map<String,Object> b,int item,String route) {
            this.transaction=t;this.before=b;this.item=item;this.route=route;
        }
    }
    public static ItemUse itemBegin(Character c,int item,String route) {
        if(!MapleBenchSkillLedger.enabled(c.getId(),c.getAccountID())) return null;
        try {
            var before=snapshot(c,item);
            var t=MapleBenchSkillLedger.begin(c.getId(),c.getAccountID(),"item_use",item,0);
            return t==null ? null : new ItemUse(t,before,item,route);
        } catch(RuntimeException e) { MapleBenchSkillLedger.invalidate(c.getId(),c.getAccountID());return null; }
    }
    public static void itemEnd(Character c,ItemUse use,boolean committed) {
        if(use==null) return;
        try {
            Map<String,Object> after=snapshot(c,use.item), out=new TreeMap<>();
            out.put("item_id",use.item);out.put("route",use.route);out.put("committed",committed);
            for(String key:List.of("quantity","hp","mp")) {
                out.put(key+"_before",use.before.get(key));out.put(key+"_after",after.get(key));
            }
            out.put("max_hp",after.get("max_hp"));out.put("max_mp",after.get("max_mp"));out.put("alive",after.get("alive"));
            out.put("resource_event_ids",List.copyOf(use.transaction.resourceEvents));
            out.put("inventory_event_ids",List.copyOf(use.transaction.inventoryEvents));
            out.put("endpoint_snapshots_atomic",false);
            MapleBenchSkillLedger.event(c.getId(),c.getAccountID(),"item_transaction",out);
        } catch(RuntimeException e) { MapleBenchSkillLedger.invalidate(c.getId(),c.getAccountID()); }
        finally { MapleBenchSkillLedger.end(use.transaction,committed); }
    }
    private static Map<String,Object> snapshot(Character c,int item) {
        return Map.of("quantity",c.getInventory(InventoryType.USE).countById(item),"hp",c.getHp(),"mp",c.getMp(),
            "max_hp",c.getCurrentMaxHp(),"max_mp",c.getCurrentMaxMp(),"alive",c.isAlive(),
            "online",c.isLoggedinWorld(),"snapshot_atomic",false,"item_id",item);
    }
    public static void itemEffect(Character c,int item,boolean applied) {
        MapleBenchSkillLedger.event(c.getId(),c.getAccountID(),"item_effect_result",Map.of("item_id",item,"applied",applied,"route","item_stat_effect_apply_to"));
    }
    public static void resource(Character c,int hpBefore,int mpBefore,int hpAfter,int mpAfter) {
        MapleBenchSkillLedger.event(c.getId(),c.getAccountID(),"resource_transaction",Map.of(
            "hp_before",hpBefore,"mp_before",mpBefore,"hp_after",hpAfter,"mp_after",mpAfter,
            "max_hp",c.getCurrentMaxHp(),"max_mp",c.getCurrentMaxMp(),"route","apply_hp_mp_change",
            "native_stat_lock_held",true));
    }
    public static void inventory(Character c,InventoryType type,int slot,int item,int before,int after) {
        if(c==null) return;
        MapleBenchSkillLedger.event(c.getId(),c.getAccountID(),"inventory_transaction",Map.of(
            "inventory_type",type.name(),"slot",slot,"item_id",item,"slot_quantity_before",before,
            "slot_quantity_after",after,"route","inventory_remove_item","native_inventory_lock_held",false));
    }
    public static MapleBenchSkillLedger.Transaction skillBegin(Character c,int skill,int level) {
        return MapleBenchSkillLedger.begin(c.getId(),c.getAccountID(),"skill_apply",skill,level);
    }
    public static void skillEnd(Character c,MapleBenchSkillLedger.Transaction t,int skill,int level,boolean committed) {
        if(t==null) return;
        try {
            MapleBenchSkillLedger.event(c.getId(),c.getAccountID(),"skill_commit",Map.of("skill_id",skill,"skill_level",level,
                "committed",committed,"route","special_move_apply_to","resource_event_ids",List.copyOf(t.resourceEvents),
                "movement_event_id","","causal_displacement_link",false));
        } finally { MapleBenchSkillLedger.end(t,committed); }
    }
    public static void movement(Character c,List<LifeMovementFragment> fragments) {
        if(!MapleBenchSkillLedger.enabled(c.getId(),c.getAccountID())) return;
        try {
            List<Object> rows=new ArrayList<>();
            for(var fragment:fragments) {
                if(!(fragment instanceof AbsoluteLifeMovement absolute)) continue;
                Point p=absolute.getPosition();
                Foothold found=null;
                for(var f:c.getMap().getFootholds().getAllFootholds()) if(f.getId()==absolute.getFh()) { found=f;break; }
                Map<String,Object> row=new TreeMap<>();
                row.put("x",p.x);row.put("y",p.y);row.put("foothold",absolute.getFh());row.put("fragment_type",absolute.getType());
                row.put("stance",absolute.getNewstate());row.put("client_duration_ms",absolute.getDuration());
                row.put("geometry_present",found!=null);
                if(found!=null) {
                    row.put("geometry",List.of(found.getX1(),found.getY1(),found.getX2(),found.getY2()));
                    row.put("on_foothold_line",onLine(p.x,p.y,found.getX1(),found.getY1(),found.getX2(),found.getY2()));
                }
                rows.add(row);
            }
            MapleBenchSkillLedger.event(c.getId(),c.getAccountID(),"movement_accepted",Map.of(
                "map_id",c.getMapId(),"accepted_x",c.getPosition().x,"accepted_y",c.getPosition().y,
                "alive",c.isAlive(),"absolute_fragments",rows,"physics_validated",false,
                "coverage_source","fresh_packet_receipt"));
        } catch(RuntimeException e) { MapleBenchSkillLedger.invalidate(c.getId(),c.getAccountID()); }
    }
    static boolean onLine(int x,int y,int x1,int y1,int x2,int y2) {
        if(x1==x2 || x<Math.min(x1,x2) || x>Math.max(x1,x2)) return false;
        return (long)(y-y1)*(x2-x1)==(long)(y2-y1)*(x-x1);
    }
}
