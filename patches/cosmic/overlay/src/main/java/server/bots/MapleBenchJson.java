package server.bots;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Minimal JSON helpers for MapleBench's intentionally tiny v0 control protocol. */
final class MapleBenchJson {
    private MapleBenchJson() {}

    static String escape(String value) {
        if (value == null) return "";
        StringBuilder out = new StringBuilder(value.length() + 16);
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\b' -> out.append("\\b");
                case '\f' -> out.append("\\f");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> {
                    if (c < 0x20) out.append(String.format("\\u%04x", (int) c));
                    else out.append(c);
                }
            }
        }
        return out.toString();
    }

    static String quote(String value) {
        return "\"" + escape(value) + "\"";
    }

    static String stringField(String json, String field) {
        Matcher m = Pattern.compile("\\\"" + Pattern.quote(field) + "\\\"\\s*:\\s*\\\"((?:\\\\.|[^\\\"\\\\])*)\\\"").matcher(json);
        if (!m.find()) return null;
        return unescapeBasic(m.group(1));
    }

    static Long longField(String json, String field) {
        Matcher m = Pattern.compile("\\\"" + Pattern.quote(field) + "\\\"\\s*:\\s*(-?\\d+)").matcher(json);
        if (!m.find()) return null;
        try {
            return Long.parseLong(m.group(1));
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private static String unescapeBasic(String value) {
        StringBuilder out = new StringBuilder(value.length());
        boolean escape = false;
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (!escape) {
                if (c == '\\') escape = true;
                else out.append(c);
                continue;
            }
            escape = false;
            switch (c) {
                case 'n' -> out.append('\n');
                case 'r' -> out.append('\r');
                case 't' -> out.append('\t');
                case 'b' -> out.append('\b');
                case 'f' -> out.append('\f');
                case '"' -> out.append('"');
                case '\\' -> out.append('\\');
                default -> out.append(c);
            }
        }
        if (escape) out.append('\\');
        return out.toString();
    }
}
