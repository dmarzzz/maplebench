package server.bots;

import org.junit.jupiter.api.Test;
import server.maps.Foothold;

import java.awt.Point;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class MapleBenchMobMotionTest {
    private Foothold ground(int id, int x1, int y1, int x2, int y2) {
        return new Foothold(new Point(x1, y1), new Point(x2, y2), id);
    }

    @Test void movesAcrossConnectedGroundWithoutLosingDistance() {
        var a = ground(1, 0, 167, 100, 167);
        var b = ground(2, 100, 167, 200, 167);
        a.setNext(2); b.setPrev(1);
        var step = MapleBenchMobMotion.walk(97, a, 8, Map.of(1, a, 2, b));
        assertEquals(105, step.x(), .001);
        assertEquals(167, step.y(), .001);
        assertSame(b, step.foothold());
        assertFalse(step.blocked());
        var reverse = MapleBenchMobMotion.walk(105, b, -8, Map.of(1, a, 2, b));
        assertEquals(97, reverse.x(), .001);
        assertSame(a, reverse.foothold());
    }

    @Test void stopsAtLedgeInsteadOfFloatingAcrossGap() {
        var a = ground(1, 0, 167, 100, 167);
        var b = ground(2, 110, 167, 200, 167);
        a.setNext(2);
        var step = MapleBenchMobMotion.walk(97, a, 8, Map.of(1, a, 2, b));
        assertEquals(100, step.x(), .001);
        assertTrue(step.blocked());
        assertSame(a, step.foothold());
    }

    @Test void stopsAtWallOrDisconnectedVerticalLevel() {
        var a = ground(1, 0, 167, 100, 167);
        var wall = ground(2, 100, 167, 100, 100);
        a.setNext(2);
        assertTrue(MapleBenchMobMotion.walk(97, a, 8, Map.of(1, a, 2, wall)).blocked());
        var upper = ground(2, 100, 100, 200, 100);
        assertTrue(MapleBenchMobMotion.walk(97, a, 8, Map.of(1, a, 2, upper)).blocked());
    }

    @Test void followsFractionalSlopesAndPreservesSubpixelMotion() {
        var slope = ground(1, 0, 100, 200, 150);
        var step = MapleBenchMobMotion.walk(20, slope, .4, Map.of(1, slope));
        assertEquals(20.4, step.x(), .0001);
        assertEquals(105.1, step.y(), .0001);
    }

    @Test void selectsActualFloorWithoutSnappingBetweenPlatforms() {
        var upper = ground(1, 0, 100, 200, 100);
        var lower = ground(2, 0, 167, 200, 167);
        assertSame(lower, MapleBenchMobMotion.findGround(List.of(upper, lower), new Point(50, 165)));
        assertNull(MapleBenchMobMotion.findGround(List.of(upper, lower), new Point(50, 130)));
    }

    @Test void appliesWzSpeedAndSlowWithoutNegativeSpeed() {
        var roid = new MapleBenchMobMotion.Profile(true, -30, false);
        assertEquals(28, MapleBenchMobMotion.speed(roid, 0), .001);
        assertEquals(12, MapleBenchMobMotion.speed(roid, -40), .001);
        assertEquals(0, MapleBenchMobMotion.speed(roid, -100), .001);
    }
}
