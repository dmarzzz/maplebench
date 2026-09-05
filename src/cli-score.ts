#!/usr/bin/env node
import { readEpisodeJsonl } from "./episode.js";
import { peakXpRate } from "./scoring.js";

const path = process.argv[2];
const windowSeconds = Number(process.argv[3] ?? "60");

if (!path) {
  console.error("usage: node dist/src/cli-score.js <episode.jsonl> [windowSeconds]");
  process.exit(2);
}

const events = await readEpisodeJsonl(path);
const score = peakXpRate(events, windowSeconds * 1000);
console.log(JSON.stringify(score, null, 2));
