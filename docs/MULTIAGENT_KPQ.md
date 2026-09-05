# Multi-agent Kerning Party Quest roadmap

The first multi-agent target should be Kerning PQ because it naturally decomposes into resource acquisition, communication, combinatorial coordination, and cooperative combat.

## Experimental unit

Four characters enter a fresh isolated PQ instance. Depending on the experimental condition, each character is controlled by a distinct agent process or one agent controls multiple characters.

## Primary metrics

- completion (binary)
- completion time
- stage completion times
- deaths
- invalid/failed stage checks
- communication tokens/messages
- redundant movement/actions
- per-agent contribution (kills, coupons/passes, stage interactions)

## Core conditions

### Full communication

All agents can party-chat with one another.

### Leader topology

Only the leader can communicate with all agents; non-leaders cannot directly communicate with each other.

### No communication

Agents share only environmental consequences, not messages.

### Shared controller

One model instance controls all four characters. This is an important control: if it strongly outperforms four independent copies of the same model, the gap measures distributed coordination overhead rather than pure game competence.

## Scientific questions

1. How does task performance scale with communication bandwidth?
2. Does a centralized leader improve or bottleneck coordination?
3. Can agents spontaneously invent efficient protocols for platform-combination stages?
4. How much is lost when private observations/memory are not shared?
5. Are heterogeneous model teams better than homogeneous teams at fixed inference cost?
6. Does prior single-agent game competence predict multi-agent PQ competence?
7. What failure modes emerge from partial plans, stale beliefs, duplicated work, or agents waiting on each other?

## Implementation order

Do not build KPQ until single-agent XP is end-to-end and recorded. The same episode, event, observer, and SDK infrastructure should generalize to N characters first; then add chat topology controls and PQ-specific verifier events.
