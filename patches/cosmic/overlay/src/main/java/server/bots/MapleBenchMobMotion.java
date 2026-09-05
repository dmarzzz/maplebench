package server.bots;

import client.Character;
import client.status.MonsterStatus;
import provider.Data;
import provider.DataProvider;
import provider.DataProviderFactory;
import provider.DataTool;
import provider.wz.WZFiles;
import server.TimerManager;
import server.life.Monster;
import server.maps.Foothold;
import server.maps.MapleMap;

import java.awt.Point;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Explicit benchmark replacement for the absent v83 client's ground-mob controller.
 * This is a bounded simulation, not a claim of retail client AI/physics parity.
 * Normal player maps, bosses, flying mobs and immobile mobs are never taken over.
 */
final class MapleBenchMobMotion {
    static final String VERSION = "ground-patrol-v1";
    record Profile(boolean groundWalker, int speed, boolean firstAttack) {}
    record Step(double x, double y, Foothold foothold, boolean blocked) {}
    record View(boolean moving, boolean facingLeft, String mode) {}
    private static final Map<Integer, View> views = new ConcurrentHashMap<>();
    private final Map<Integer, State> states = new HashMap<>();
    private final Map<Integer, Profile> profiles = new HashMap<>();
    private final DataProvider data = DataProviderFactory.getDataProvider(WZFiles.MOB);
    private long previousNs;
    private double elapsed;

    private static final class State {
        double x;
        int hp, direction;
        double aggroUntil;
        Foothold ground;
        State(Monster mob, Foothold ground) {
            x = mob.getPosition().x;
            hp = mob.getHp();
            direction = (mob.getObjectId() & 1) == 0 ? 1 : -1;
            this.ground = ground;
        }
    }

    static void start(Character bot) {
        if (!MapleBenchRuntime.isControlled(bot)) return;
        MapleBenchMobMotion motion = new MapleBenchMobMotion();
        TimerManager.getInstance().register(() -> motion.tick(bot), 100);
    }

    static View view(Monster mob) {
        return views.getOrDefault(mob.getObjectId(), new View(false, mob.isFacingLeft(), "uncontrolled"));
    }

    private Profile profile(int id) {
        return profiles.computeIfAbsent(id, key -> {
            Data root = data.getData(String.format("%07d.img", key));
            if (root == null) throw new IllegalStateException("Missing monster movement data: " + key);
            Data info = root.getChildByPath("info");
            int link = DataTool.getIntConvert("link", info, 0);
            Data poses = link == 0 ? root : data.getData(String.format("%07d.img", link));
            boolean ground = poses != null && poses.getChildByPath("move") != null
                    && poses.getChildByPath("fly") == null;
            return new Profile(ground, DataTool.getIntConvert("speed", info, 0),
                    DataTool.getIntConvert("firstAttack", info, 0) > 0);
        });
    }

    // A declared simulation scale: 40 px/s at WZ speed 0, matching Maplewright's
    // baseline patrol speed. WZ speed and SPEED status modify it proportionally.
    static double speed(Profile profile, int status) {
        return 40.0 * Math.max(0, Math.min(200, 100 + profile.speed + status)) / 100.0;
    }

    static double groundY(Foothold ground, double x) {
        return ground.getY1() + (x - ground.getX1()) * ground.slope();
    }

    static Foothold findGround(List<Foothold> ground, Point p) {
        return ground.stream().filter(f -> !f.isWall()
                        && p.x >= Math.min(f.getX1(), f.getX2()) && p.x <= Math.max(f.getX1(), f.getX2())
                        && Math.abs(groundY(f, p.x) - p.y) <= 5)
                .min(java.util.Comparator.comparingDouble(f -> Math.abs(groundY(f, p.x) - p.y))).orElse(null);
    }

    /** Walk only through physically touching linked ground; reverse at walls/gaps/ledges. */
    static Step walk(double x, Foothold ground, double distance, Map<Integer, Foothold> footholds) {
        int direction = distance >= 0 ? 1 : -1;
        double remaining = Math.abs(distance);
        for (int hops = 0; hops < 32; hops++) {
            double edge = direction > 0 ? Math.max(ground.getX1(), ground.getX2()) : Math.min(ground.getX1(), ground.getX2());
            double available = Math.max(0, Math.abs(edge - x));
            if (remaining <= available) {
                x += direction * remaining;
                return new Step(x, groundY(ground, x), ground, false);
            }
            remaining -= available;
            x = edge;
            double y = groundY(ground, edge);
            Foothold next = null;
            for (int id : new int[]{ground.getPrev(), ground.getNext()}) {
                Foothold f = footholds.get(id);
                if (f == null || f.isWall()) continue;
                double near = direction > 0 ? Math.min(f.getX1(), f.getX2()) : Math.max(f.getX1(), f.getX2());
                double far = direction > 0 ? Math.max(f.getX1(), f.getX2()) : Math.min(f.getX1(), f.getX2());
                if (Math.abs(near - edge) < .01 && Math.abs(groundY(f, near) - y) < .01
                        && (far - edge) * direction > 0) { next = f; break; }
            }
            if (next == null) return new Step(x, y, ground, true);
            ground = next;
        }
        return new Step(x, groundY(ground, x), ground, true);
    }

    private void tick(Character bot) {
        if (MapleBenchRuntime.isStaged()) { previousNs = 0; return; }
        long now = System.nanoTime();
        double dt = previousNs == 0 ? 0 : Math.min(.2, (now - previousNs) / 1e9);
        previousNs = now;
        elapsed += dt;
        MapleMap map = bot.getMap();
        if (map == null || map.getFootholds() == null) return;
        // The normal client's ownership takes precedence whenever a real player is present.
        boolean playerPresent = map.getAllPlayers().stream().anyMatch(c -> !MapleBenchRuntime.isControlled(c));
        List<Foothold> all = map.getFootholds().getAllFootholds();
        Map<Integer, Foothold> byId = new HashMap<>();
        for (Foothold f : all) byId.put(f.getId(), f);
        var live = new HashSet<Integer>();
        for (Monster mob : map.getAllMonsters()) {
            int id = mob.getObjectId();
            live.add(id);
            if (!mob.isAlive()) continue;
            Profile p = profile(mob.getId());
            Point pos = mob.getPosition();
            State s = states.computeIfAbsent(id, ignored -> new State(mob, findGround(all, pos)));
            String mode = "patrol";
            boolean moving = false;
            if (playerPresent) { mode = "client_owned"; s.x = pos.x; s.ground = findGround(all, pos); }
            else if (!p.groundWalker || mob.isBoss() || s.ground == null) mode = "unsupported";
            else if (mob.isBuffed(MonsterStatus.STUN) || mob.isBuffed(MonsterStatus.FREEZE)
                    || mob.isBuffed(MonsterStatus.SHADOW_WEB) || mob.isBuffed(MonsterStatus.INERTMOB)) mode = "status_locked";
            else {
                if (mob.getHp() < s.hp) s.aggroUntil = elapsed + 6;
                Point target = bot.getPosition();
                double dx = target.x - s.x;
                boolean chase = bot.isAlive() && Math.abs(target.y - pos.y) < 80 && Math.abs(dx) < 480
                        && (elapsed < s.aggroUntil || p.firstAttack);
                // Offset patrol pauses by object ID so a whole map doesn't march in sync.
                boolean idle = (elapsed + Math.floorMod(id * 37, 700) / 100.0) % 7 < 1.2;
                if (chase) {
                    mode = "chase";
                    if (Math.abs(dx) > 12) s.direction = dx < 0 ? -1 : 1;
                    else idle = true;
                    if (Math.abs(dx) > 12) idle = false;
                }
                if (idle) mode = "idle";
                else {
                    var effect = mob.getStati(MonsterStatus.SPEED);
                    int modifier = effect == null ? 0 : effect.getStati().getOrDefault(MonsterStatus.SPEED, 0);
                    Step step = walk(s.x, s.ground, s.direction * speed(p, modifier) * dt, byId);
                    Point destination = new Point((int) Math.round(step.x), (int) Math.round(step.y));
                    moving = !destination.equals(pos);
                    s.x = step.x;
                    s.ground = step.foothold;
                    if (step.blocked) { s.direction *= -1; mode = "blocked"; }
                    mob.setStance((moving ? 2 : 4) + (s.direction < 0 ? 1 : 0));
                    mob.setFh(s.ground.getId());
                    map.moveMonster(mob, destination);
                }
            }
            s.hp = mob.getHp();
            views.put(id, new View(moving, mob.isFacingLeft(), mode));
        }
        states.keySet().retainAll(live);
        views.keySet().retainAll(live);
    }
}
