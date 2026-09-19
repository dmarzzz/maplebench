package server.bots;

import client.BuffStat;
import client.Character;
import java.awt.Point;
import java.util.*;

/** Read-only observations of ordinary physical Hero skill handlers.
 * No skill grant, damage rewrite, resource change, movement or input is supplied.
 * Endpoint snapshots are explicitly non-atomic; child resource/damage events
 * are captured under the native mutation locks and linked by handler scope. */
public final class MapleBenchSkillHooks {
    private MapleBenchSkillHooks() {}

    public static String startWindow(Character c) {
        return MapleBenchSkillLedger.startWindow(c.getId(),c.getAccountID(),snapshot(c));
    }
    public static String sealWindow(Character c) {
        return MapleBenchSkillLedger.sealWindow(c.getId(),c.getAccountID(),snapshot(c));
    }

    public static final class SkillUse {
        final MapleBenchSkillLedger.Transaction transaction;
        final Map<String,Object> before;
        final String route;
        final int skill,level;
        SkillUse(MapleBenchSkillLedger.Transaction transaction,Map<String,Object> before,
                 int skill,int level,String route) {
            this.transaction=transaction;this.before=before;this.skill=skill;this.level=level;this.route=route;
        }
    }

    private static Map<String,Object> snapshot(Character c) {
        Map<String,Object> state=new TreeMap<>();
        Point position=c.getPosition();
        Integer combo=c.getBuffedValue(BuffStat.COMBO);
        TreeMap<Integer,Integer> active=new TreeMap<>();
        for(BuffStat stat:BuffStat.values()) {
            Integer value=c.getBuffedValue(stat);
            int source=c.getBuffSource(stat);
            if(value!=null && source!=-1) active.putIfAbsent(source,value);
        }
        // One stable, actual value per Hero buff. Rage also has WDEF, whose
        // effect is separately visible through the authoritative total stat.
        buff(c,active,1111002,BuffStat.COMBO);
        buff(c,active,1101004,BuffStat.BOOSTER);
        buff(c,active,1121000,BuffStat.MAPLE_WARRIOR);
        buff(c,active,1121002,BuffStat.STANCE);
        buff(c,active,1101006,BuffStat.WATK);
        buff(c,active,1101007,BuffStat.POWERGUARD);
        List<List<Integer>> buffs=new ArrayList<>();
        for(var entry:active.entrySet()) buffs.add(List.of(entry.getKey(),entry.getValue()));
        state.put("job",c.getJob().getId());state.put("level",c.getLevel());state.put("map_id",c.getMapId());
        state.put("hp",c.getHp());state.put("mp",c.getMp());
        state.put("max_hp",c.getCurrentMaxHp());state.put("max_mp",c.getCurrentMaxMp());
        state.put("x",position.x);state.put("y",position.y);
        state.put("combo_orbs",combo==null?0:Math.max(0,combo-1));state.put("active_buffs",buffs);
        state.put("stats",Map.of("str",c.getTotalStr(),"dex",c.getTotalDex(),
            "weapon_attack",c.getTotalWatk(),"weapon_defense",c.getTotalWdef()));
        state.put("alive",c.isAlive());state.put("online",c.isLoggedinWorld());state.put("snapshot_atomic",false);
        return state;
    }

    private static void buff(Character c,Map<Integer,Integer> active,int skill,BuffStat stat) {
        Integer value=c.getBuffedValue(stat);
        if(value!=null && c.getBuffSource(stat)==skill) active.put(skill,value);
    }

    private static SkillUse begin(Character c,int skill,int level,String route) {
        if(skill<=0 || !MapleBenchSkillLedger.enabled(c.getId(),c.getAccountID())) return null;
        try {
            Map<String,Object> before=snapshot(c);
            var transaction=MapleBenchSkillLedger.begin(c.getId(),c.getAccountID(),"skill_apply",skill,level);
            return transaction==null?null:new SkillUse(transaction,before,skill,level,route);
        } catch(RuntimeException error) {
            MapleBenchSkillLedger.invalidate(c.getId(),c.getAccountID());return null;
        }
    }

    public static SkillUse skillBegin(Character c,int skill,int level) {
        return begin(c,skill,level,"special_move_apply_to");
    }
    public static SkillUse attackBegin(Character c,int skill,int level) {
        return begin(c,skill,level,"close_range_damage_handler");
    }
    public static void attackCostApplied(Character c,int skill,boolean applied) {
        var transaction=MapleBenchSkillLedger.current(c.getId(),c.getAccountID());
        if(transaction!=null && transaction.subject==skill) transaction.skillCostApplied=applied;
    }
    public static void attackEnd(Character c,SkillUse use,boolean returned) {
        if(use!=null) skillEnd(c,use,use.skill,use.level,returned && use.transaction.skillCostApplied);
    }
    public static void skillEnd(Character c,SkillUse use,int skill,int level,boolean committed) {
        if(use==null) return;
        try {
            if(skill!=use.skill || level!=use.level) {
                MapleBenchSkillLedger.invalidate(c.getId(),c.getAccountID());return;
            }
            Map<String,Object> after=snapshot(c),row=new TreeMap<>();
            row.put("skill_id",skill);row.put("skill_level",level);row.put("route",use.route);
            row.put("committed",committed);row.put("map_id",after.get("map_id"));
            for(String name:List.of("hp","mp","combo_orbs","active_buffs","stats")) {
                row.put(name+"_before",use.before.get(name));row.put(name+"_after",after.get(name));
            }
            row.put("position_before",Map.of("x",use.before.get("x"),"y",use.before.get("y")));
            row.put("position_after",Map.of("x",after.get("x"),"y",after.get("y")));
            row.put("resource_event_ids",List.copyOf(use.transaction.resourceEvents));
            row.put("damage_event_ids",List.copyOf(use.transaction.damageEvents));
            row.put("endpoint_snapshots_atomic",false);
            MapleBenchSkillLedger.event(c.getId(),c.getAccountID(),"skill_commit",row);
        } catch(RuntimeException error) {
            MapleBenchSkillLedger.invalidate(c.getId(),c.getAccountID());
        } finally {
            MapleBenchSkillLedger.end(use.transaction,committed);
        }
    }

    public static void resource(Character c,int hpBefore,int mpBefore,int hpAfter,int mpAfter) {
        if(!MapleBenchSkillLedger.enabled(c.getId(),c.getAccountID())) return;
        // This qualification records resources only inside the ordinary skill
        // handler whose causal transaction owns them. Unrelated regeneration
        // and damage do not become skill evidence.
        var transaction=MapleBenchSkillLedger.current(c.getId(),c.getAccountID());
        if(transaction==null || !transaction.kind.equals("skill_apply")) return;
        MapleBenchSkillLedger.event(c.getId(),c.getAccountID(),"resource_transaction",Map.of(
            "hp_before",hpBefore,"mp_before",mpBefore,"hp_after",hpAfter,"mp_after",mpAfter,
            "max_hp",c.getCurrentMaxHp(),"max_mp",c.getCurrentMaxMp(),"route","apply_hp_mp_change",
            "native_stat_lock_held",true));
    }

    public static void monsterDamage(Character c,int objectId,int hpBefore,int hpAfter,boolean killed) {
        if(c==null || !MapleBenchSkillLedger.enabled(c.getId(),c.getAccountID())) return;
        var transaction=MapleBenchSkillLedger.current(c.getId(),c.getAccountID());
        if(transaction==null || !transaction.kind.equals("skill_apply")) return;
        MapleBenchSkillLedger.event(c.getId(),c.getAccountID(),"monster_damage",Map.of(
            "skill_id",transaction.subject,"object_id",objectId,"hp_before",hpBefore,"hp_after",hpAfter,
            "hp_loss",Math.max(0L,(long)hpBefore-hpAfter),"killed",killed,"route","ordinary_monster_damage"));
    }
}
