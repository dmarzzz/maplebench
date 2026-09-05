package server.bots;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class MapleBenchStartGateTest {
    @Test void stagedOpeningReleasesOnceAndCannotRestage() {
        var gate = new MapleBenchStartGate(true);
        assertTrue(gate.isStaged());
        gate.startAction();
        assertFalse(gate.isStaged());
        gate.startAction();
        assertFalse(gate.isStaged());
    }
    @Test void existingLiveEpisodesBeginImmediately() {
        var gate = new MapleBenchStartGate(false);
        assertFalse(gate.isStaged());
    }
}
