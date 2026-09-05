import test from "node:test";
import assert from "node:assert/strict";
import type { EpisodeEvent } from "../src/protocol.js";
import { peakXpRate, totalXp } from "../src/scoring.js";

function xp(seq: number, tMs: number, amount: number): EpisodeEvent {
  return { seq, tMs, kind: "xp_gain", amount, source: "monster" };
}

test("totalXp sums positive server-authoritative XP events", () => {
  const events: EpisodeEvent[] = [xp(1, 1000, 10), xp(2, 2000, 25), xp(3, 3000, 5)];
  assert.equal(totalXp(events), 40);
});

test("peakXpRate finds the best rolling 60 second window", () => {
  const events: EpisodeEvent[] = [
    xp(1, 1_000, 100),
    xp(2, 31_000, 200),
    xp(3, 61_001, 400),
    xp(4, 90_000, 100),
  ];

  const score = peakXpRate(events, 60_000);
  assert.equal(score.totalXp, 800);
  // Best window ends at 90s and contains the 31s + 61.001s + 90s gains.
  assert.equal(score.peakXpPerMinute, 700);
  assert.equal(score.peakWindowEndMs, 90_000);
});

test("peakXpRate normalizes shorter windows to XP/min", () => {
  const events: EpisodeEvent[] = [xp(1, 1_000, 50), xp(2, 10_000, 50)];
  const score = peakXpRate(events, 15_000);
  assert.equal(score.peakXpPerMinute, 400);
});

test("peakXpRate returns zero for no XP", () => {
  const score = peakXpRate([], 60_000);
  assert.equal(score.totalXp, 0);
  assert.equal(score.peakXpPerMinute, 0);
  assert.equal(score.peakWindowEndMs, null);
});
