package server.bots;

import client.Character;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import net.server.Server;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Trusted loopback-only ledger control. This endpoint sends no game actions,
 * accepts no character state and is never exposed to generated programs. */
public final class MapleBenchSkillControlServer {
    private static HttpServer server;
    private MapleBenchSkillControlServer() {}

    public static synchronized void startFromEnvironment() {
        if (System.getenv("MAPLEBENCH_SKILL_JOURNAL") == null) return;
        if (server != null) throw new IllegalStateException("skill_control_already_started");
        String token = System.getenv("MAPLEBENCH_SKILL_CONTROL_TOKEN");
        String run = System.getenv("MAPLEBENCH_TRIAL_ID");
        if (token == null || !token.matches("[a-f0-9]{64}") || run == null || !run.matches("[a-f0-9]{32}")) {
            throw new IllegalStateException("skill_control_identity_required");
        }
        int port = number("MAPLEBENCH_SKILL_CONTROL_PORT", 1024, 65535);
        int world = number("MAPLEBENCH_SKILL_WORLD_ID", 0, 255);
        int channel = number("MAPLEBENCH_SKILL_CHANNEL_ID", 1, 255);
        int character = number("MAPLEBENCH_PERSIST_CHARACTER_ID", 1, Integer.MAX_VALUE);
        int account = number("MAPLEBENCH_PERSIST_ACCOUNT_ID", 1, Integer.MAX_VALUE);
        try {
            HttpServer next = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
            next.createContext("/v1/skill-ledger/", exchange -> handle(exchange, token, run,
                world, channel, character, account));
            next.setExecutor(new ThreadPoolExecutor(1, 1, 0, TimeUnit.SECONDS,
                new ArrayBlockingQueue<>(16), runnable -> {
                Thread thread = new Thread(runnable, "maplebench-skill-control");
                thread.setDaemon(true);
                return thread;
            }, new ThreadPoolExecutor.AbortPolicy()));
            next.start();
            server = next;
        } catch (IOException error) {
            throw new IllegalStateException("skill_control_bind_failed");
        }
    }

    private static int number(String name, int min, int max) {
        try {
            int value = Integer.parseInt(System.getenv(name));
            if (value < min || value > max) throw new NumberFormatException();
            return value;
        } catch (RuntimeException error) {
            throw new IllegalArgumentException("skill_control_configuration_invalid");
        }
    }

    private static void handle(HttpExchange exchange, String token, String run,
                               int worldId, int channelId, int characterId, int accountId) throws IOException {
        String auth = exchange.getRequestHeaders().getFirst("Authorization");
        String suppliedRun = exchange.getRequestHeaders().getFirst("X-MapleBench-Run");
        if (!exchange.getRemoteAddress().getAddress().isLoopbackAddress() || auth == null
            || !MessageDigest.isEqual(auth.getBytes(StandardCharsets.UTF_8),
                ("Bearer " + token).getBytes(StandardCharsets.UTF_8)) || !run.equals(suppliedRun)) {
            send(exchange, 403, "{\"error\":\"skill_control_forbidden\"}");
            return;
        }
        String path = exchange.getRequestURI().getRawPath();
        String method = exchange.getRequestMethod();
        boolean status = path.equals("/v1/skill-ledger/status") && method.equals("GET");
        boolean arm = path.equals("/v1/skill-ledger/arm") && method.equals("POST");
        boolean seal = path.equals("/v1/skill-ledger/seal") && method.equals("POST");
        var lengths = exchange.getRequestHeaders().get("Content-Length");
        if ((!status && !arm && !seal) || exchange.getRequestURI().getRawQuery() != null
            || exchange.getRequestHeaders().containsKey("Transfer-Encoding")
            || lengths != null && (lengths.size() != 1 || !lengths.get(0).equals("0"))) {
            send(exchange, 400, "{\"error\":\"skill_control_request_invalid\"}");
            return;
        }
        try {
            if (status) {
                send(exchange, 200, MapleBenchSkillLedger.status());
                return;
            }
            var world = Server.getInstance().getWorld(worldId);
            var channel = world == null ? null : world.getChannel(channelId);
            Character character = channel == null ? null : channel.getPlayerStorage().getCharacterById(characterId);
            if (character == null || character.getId() != characterId || character.getAccountID() != accountId
                || !character.isLoggedinWorld() || character.getClient() == null || !character.getClient().isLoggedIn()) {
                send(exchange, 409, "{\"error\":\"skill_control_actor_unavailable\"}");
                return;
            }
            send(exchange, 200, arm ? MapleBenchSkillHooks.startWindow(character) : MapleBenchSkillHooks.sealWindow(character));
        } catch (RuntimeException error) {
            // A lost reply must be reconciled through status, never repeated arm.
            send(exchange, 409, "{\"error\":\"skill_control_transition_unavailable\"}");
        }
    }

    private static void send(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.getResponseHeaders().set("Cache-Control", "no-store");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
