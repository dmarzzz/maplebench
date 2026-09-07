/* Log-only fixture: compile/run against the existing shaded Cosmic JAR.
 * No game classes are initialized. The caller supplies a private external
 * Log4j2 configuration using -Dlog4j.configurationFile=... . Execute twice in
 * a temporary working directory; independently verify the lifecycle prefix
 * remains intact and receives one copy of each message per invocation.
 */
import org.apache.logging.log4j.LogManager;

public final class LifecycleLogSmoke {
    public static void main(String[] args) {
        if (args.length != 1 || !args[0].matches("[A-Za-z0-9_-]{1,32}")) {
            throw new IllegalArgumentException("fixed smoke label required");
        }
        LogManager.getLogger("net.server.Server").info(
                "Cosmic is now online after 1 ms. lifecycle-smoke-{}", args[0]);
        LogManager.getLogger("net.packet.logging.LifecycleLogSmoke").debug(
                "lifecycle-packet-smoke-{}", args[0]);
        LogManager.getLogger("net.server.Server").error(
                "lifecycle-error-smoke-{}", args[0]);
        LogManager.shutdown();
    }
}
