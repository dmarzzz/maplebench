import { readFile } from "node:fs/promises";
import type { EpisodeEvent } from "./protocol.js";

export async function readEpisodeJsonl(path: string): Promise<EpisodeEvent[]> {
  const content = await readFile(path, "utf8");
  const events: EpisodeEvent[] = [];

  for (const [index, rawLine] of content.split(/\r?\n/).entries()) {
    const line = rawLine.trim();
    if (!line) continue;
    try {
      events.push(JSON.parse(line) as EpisodeEvent);
    } catch (error) {
      throw new Error(`Invalid JSONL at ${path}:${index + 1}: ${(error as Error).message}`);
    }
  }

  return events;
}
