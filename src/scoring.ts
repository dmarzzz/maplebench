import type { EpisodeEvent, XpGainEvent } from "./protocol.js";

export interface XpScore {
  totalXp: number;
  peakXpPerMinute: number;
  peakWindowStartMs: number | null;
  peakWindowEndMs: number | null;
  windowMs: number;
}

function xpEvents(events: EpisodeEvent[]): XpGainEvent[] {
  return events
    .filter((event): event is XpGainEvent => event.kind === "xp_gain")
    .filter((event) => Number.isFinite(event.amount) && event.amount > 0)
    .sort((a, b) => a.tMs - b.tMs || a.seq - b.seq);
}

export function totalXp(events: EpisodeEvent[]): number {
  return xpEvents(events).reduce((sum, event) => sum + event.amount, 0);
}

/**
 * Compute the best XP/min over an exact rolling window.
 *
 * Window semantics: (start, end], so events exactly at end are counted and an
 * event exactly windowMs before end is excluded. This avoids double-counting
 * boundary events when comparing adjacent windows.
 */
export function peakXpRate(events: EpisodeEvent[], windowMs = 60_000): XpScore {
  if (!Number.isFinite(windowMs) || windowMs <= 0) {
    throw new Error("windowMs must be a positive finite number");
  }

  const xp = xpEvents(events);
  const total = xp.reduce((sum, event) => sum + event.amount, 0);
  if (xp.length === 0) {
    return {
      totalXp: 0,
      peakXpPerMinute: 0,
      peakWindowStartMs: null,
      peakWindowEndMs: null,
      windowMs,
    };
  }

  let left = 0;
  let rolling = 0;
  let best = 0;
  let bestEnd: number | null = null;

  for (let right = 0; right < xp.length; right += 1) {
    const end = xp[right].tMs;
    rolling += xp[right].amount;

    while (left <= right && xp[left].tMs <= end - windowMs) {
      rolling -= xp[left].amount;
      left += 1;
    }

    if (rolling > best) {
      best = rolling;
      bestEnd = end;
    }
  }

  return {
    totalXp: total,
    peakXpPerMinute: best * (60_000 / windowMs),
    peakWindowStartMs: bestEnd === null ? null : bestEnd - windowMs,
    peakWindowEndMs: bestEnd,
    windowMs,
  };
}
