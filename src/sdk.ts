import type {
  ActionResult,
  EntityId,
  ItemId,
  MapleAction,
  MapleTransport,
  Observation,
  Position,
  SkillId,
  EpisodeEvent,
} from "./protocol.js";

/**
 * Thin agent-facing SDK. High-level policy helpers like grind(), train(),
 * completeQuest(), or optimizeGear() are intentionally absent.
 */
export class MapleClient {
  constructor(private readonly transport: MapleTransport) {}

  observe(): Promise<Observation> {
    return this.transport.observe();
  }

  events(sinceSeq?: number): Promise<EpisodeEvent[]> {
    return this.transport.events(sinceSeq);
  }

  moveTo(position: Position): Promise<ActionResult> {
    return this.act({ type: "move_to", position });
  }

  attack(targetId?: EntityId): Promise<ActionResult> {
    return this.act({ type: "basic_attack", targetId });
  }

  useSkill(skillId: SkillId, targetId?: EntityId): Promise<ActionResult> {
    return this.act({ type: "use_skill", skillId, targetId });
  }

  loot(dropId: EntityId): Promise<ActionResult> {
    return this.act({ type: "loot", dropId });
  }

  useItem(itemId: ItemId): Promise<ActionResult> {
    return this.act({ type: "use_item", itemId });
  }

  enterPortal(portalId: number): Promise<ActionResult> {
    return this.act({ type: "enter_portal", portalId });
  }

  allocateAp(stat: "str" | "dex" | "int" | "luk" | "hp" | "mp", points = 1): Promise<ActionResult> {
    return this.act({ type: "allocate_ap", stat, points });
  }

  allocateSp(skillId: SkillId, points = 1): Promise<ActionResult> {
    return this.act({ type: "allocate_sp", skillId, points });
  }

  say(message: string): Promise<ActionResult> {
    return this.act({ type: "say", message });
  }

  act(action: MapleAction): Promise<ActionResult> {
    return this.transport.act(action);
  }
}

export class HttpMapleTransport implements MapleTransport {
  constructor(
    private readonly baseUrl = process.env.MAPLEBENCH_URL ?? "http://127.0.0.1:8790",
    private readonly token = process.env.MAPLEBENCH_TOKEN,
  ) {}

  private headers(): HeadersInit {
    return {
      "content-type": "application/json",
      ...(this.token ? { authorization: `Bearer ${this.token}` } : {}),
    };
  }

  async observe(): Promise<Observation> {
    const response = await fetch(`${this.baseUrl}/v1/observe`, { headers: this.headers() });
    if (!response.ok) throw new Error(`observe failed: ${response.status} ${await response.text()}`);
    return response.json() as Promise<Observation>;
  }

  async act(action: MapleAction): Promise<ActionResult> {
    const response = await fetch(`${this.baseUrl}/v1/action`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify(action),
    });
    if (!response.ok) throw new Error(`action failed: ${response.status} ${await response.text()}`);
    return response.json() as Promise<ActionResult>;
  }

  async events(sinceSeq = 0): Promise<EpisodeEvent[]> {
    const response = await fetch(`${this.baseUrl}/v1/events?since_seq=${encodeURIComponent(sinceSeq)}`, {
      headers: this.headers(),
    });
    if (!response.ok) throw new Error(`events failed: ${response.status} ${await response.text()}`);
    return response.json() as Promise<EpisodeEvent[]>;
  }
}
