package server.bots;

import java.util.concurrent.atomic.AtomicBoolean;

/** One-way episode staging. Only the initial controller action can release it. */
final class MapleBenchStartGate {
    private final AtomicBoolean staged;
    MapleBenchStartGate(boolean waitForAction) { staged = new AtomicBoolean(waitForAction); }
    boolean isStaged() { return staged.get(); }
    void startAction() { staged.set(false); }
}
