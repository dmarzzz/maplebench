package server.bots;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;

/** Local-only HTTP control plane consumed by MapleBench's TypeScript SDK. */
public final class MapleBenchControlServer {
    private static volatile HttpServer server;

    private MapleBenchControlServer() {}

    public static void startFromEnvironment() {
        if (!truthy(System.getenv("MAPLEBENCH_ENABLED"))) return;
        String botName = System.getenv("MAPLEBENCH_BOT_NAME");
        if (botName == null || botName.isBlank()) {
            throw new IllegalStateException("MAPLEBENCH_ENABLED requires MAPLEBENCH_BOT_NAME");
        }
        int port = parsePort(System.getenv("MAPLEBENCH_CONTROL_PORT"), 8790);
        MapleBenchEventSink.configureFromEnvironment();
        MapleBenchRuntime.spawnFromEnvironment();
        start(botName, port);
    }

    static synchronized void start(String botName, int port) {
        if (server != null) return;
        try {
            MapleBenchController controller = new MapleBenchController(botName);
            HttpServer next = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
            next.createContext("/v1/observe", exchange -> handleObserve(exchange, controller));
            next.createContext("/v1/action", exchange -> handleAction(exchange, controller));
            next.createContext("/v1/events", MapleBenchControlServer::handleEvents);
            next.createContext("/health", MapleBenchControlServer::handleHealth);
            next.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
            next.start();
            server = next;
            System.out.println("MapleBench control plane: http://127.0.0.1:" + port + " (bot=" + botName + ")");
        } catch (IOException e) {
            throw new IllegalStateException("Could not start MapleBench control plane", e);
        }
    }

    private static void handleObserve(HttpExchange exchange, MapleBenchController controller) throws IOException {
        if (!"GET".equals(exchange.getRequestMethod())) {
            send(exchange, 405, "{\"error\":\"method not allowed\"}");
            return;
        }
        try {
            send(exchange, 200, controller.observeJson());
        } catch (RuntimeException e) {
            send(exchange, 503, errorJson(e));
        }
    }

    private static void handleAction(HttpExchange exchange, MapleBenchController controller) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            send(exchange, 405, "{\"error\":\"method not allowed\"}");
            return;
        }
        String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        if (body.length() > 64_000) {
            send(exchange, 413, "{\"error\":\"action body too large\"}");
            return;
        }
        long startedAt = MapleBenchEventSink.elapsedMs();
        try {
            MapleBenchController.Result result = controller.act(body);
            MapleBenchEventSink.recordAction(body, result.accepted());
            String observation = controller.observeJson();
            String response = "{\"accepted\":" + result.accepted()
                    + ",\"startedAtMs\":" + startedAt
                    + ",\"completedAtMs\":" + MapleBenchEventSink.elapsedMs()
                    + (result.error() == null ? "" : ",\"error\":" + MapleBenchJson.quote(result.error()))
                    + ",\"observation\":" + observation + "}";
            send(exchange, 200, response);
        } catch (RuntimeException e) {
            MapleBenchEventSink.recordAction(body, false);
            send(exchange, 503, errorJson(e));
        }
    }

    private static void handleEvents(HttpExchange exchange) throws IOException {
        if (!"GET".equals(exchange.getRequestMethod())) {
            send(exchange, 405, "{\"error\":\"method not allowed\"}");
            return;
        }
        long since = 0;
        String query = exchange.getRequestURI().getRawQuery();
        if (query != null) {
            for (String part : query.split("&")) {
                String[] kv = part.split("=", 2);
                if (kv.length == 2 && "since_seq".equals(kv[0])) {
                    try { since = Math.max(0, Long.parseLong(kv[1])); } catch (NumberFormatException ignored) {}
                }
            }
        }
        send(exchange, 200, MapleBenchEventSink.eventsSince(since));
    }

    private static void handleHealth(HttpExchange exchange) throws IOException {
        send(exchange, 200, "{\"ok\":true,\"backend\":\"cosmic-v83\"}");
    }

    private static void send(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.getResponseHeaders().set("Cache-Control", "no-store");
        exchange.getResponseHeaders().set("Access-Control-Allow-Origin", "*");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }

    private static String errorJson(Throwable error) {
        String message = error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage();
        return "{\"error\":" + MapleBenchJson.quote(message) + "}";
    }

    private static boolean truthy(String value) {
        if (value == null) return false;
        return value.equalsIgnoreCase("1") || value.equalsIgnoreCase("true") || value.equalsIgnoreCase("yes");
    }

    private static int parsePort(String value, int fallback) {
        if (value == null || value.isBlank()) return fallback;
        try {
            int port = Integer.parseInt(value);
            if (port < 1 || port > 65535) throw new NumberFormatException();
            return port;
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("Invalid MAPLEBENCH_CONTROL_PORT: " + value);
        }
    }
}
