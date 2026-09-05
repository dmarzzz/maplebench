/**
 * MapleBench protocol types.
 *
 * The benchmark boundary is intentionally narrower than the underlying game
 * server. Agents receive observations and physical game actions, never
 * privileged server mutation primitives such as setLevel(), addExp(), warp(),
 * or the upstream bot fork's autonomous grind/quest routines.
 */

export type EntityId = number;
export type MapId = number;
export type ItemId = number;
export type SkillId = number;

export interface Position {
  x: number;
  y: number;
  foothold?: number;
}

export interface CharacterState {
  id: EntityId;
  name: string;
  level: number;
  jobId: number;
  exp: number;
  hp: number;
  maxHp: number;
  mp: number;
  maxMp: number;
  mesos: number;
  mapId: MapId;
  position: Position;
  alive: boolean;
  motion?: CharacterMotion;
}

/** Sampled mechanics, including the real attack lock and facing during recoil. */
export interface CharacterMotion {
  inAir: boolean;
  climbing: boolean;
  swimming: boolean;
  crouching: boolean;
  facingLeft: boolean;
  moving: boolean;
  moveIntent: number;
  attackCooldownMs: number;
  hurtCooldownMs: number;
  actionName: string;
  attackAtMs: number;
}

export interface MonsterState {
  objectId: EntityId;
  monsterId: number;
  name?: string;
  hp: number;
  maxHp?: number;
  level?: number;
  position: Position;
  alive: boolean;
  moving?: boolean;
  facingLeft?: boolean;
  movementMode?: string;
}

export interface DropState {
  objectId: EntityId;
  itemId?: ItemId;
  mesos?: number;
  quantity?: number;
  position: Position;
}

export interface InventoryItem {
  itemId: ItemId;
  quantity: number;
  slot: number;
}

export interface Observation {
  nowMs: number;
  character: CharacterState;
  monsters: MonsterState[];
  /** Version of the server-side replacement for an absent client mob controller. */
  monsterSimulation?: string;
  combatTrace?: "combat-v1";
  drops: DropState[];
  inventory?: InventoryItem[];
  portals?: Array<{ id: number; name?: string; position: Position; targetMapId?: MapId }>;
}

export type MapleAction =
  | { type: "move_to"; position: Position }
  | { type: "basic_attack"; targetId?: EntityId }
  | { type: "use_skill"; skillId: SkillId; targetId?: EntityId }
  | { type: "loot"; dropId: EntityId }
  | { type: "use_item"; itemId: ItemId }
  | { type: "enter_portal"; portalId: number }
  | { type: "allocate_ap"; stat: "str" | "dex" | "int" | "luk" | "hp" | "mp"; points: number }
  | { type: "allocate_sp"; skillId: SkillId; points: number }
  | { type: "say"; message: string };

export interface ActionResult {
  accepted: boolean;
  startedAtMs: number;
  completedAtMs: number;
  error?: string;
  observation?: Observation;
}

export interface MapleTransport {
  observe(): Promise<Observation>;
  act(action: MapleAction): Promise<ActionResult>;
  events(sinceSeq?: number): Promise<EpisodeEvent[]>;
}

export type EpisodeEvent =
  | EpisodeStartEvent
  | CombatAttackEvent
  | MonsterHitEvent
  | PlayerHitEvent
  | XpGainEvent
  | LevelUpEvent
  | MapChangeEvent
  | DeathEvent
  | ActionEvent
  | ChatEvent
  | EpisodeEndEvent;

export interface BaseEvent {
  seq: number;
  tMs: number;
}

export interface EpisodeStartEvent extends BaseEvent {
  kind: "episode_start";
  taskId: string;
  seed: string;
  characterId: EntityId;
}

export interface XpGainEvent extends BaseEvent {
  kind: "xp_gain";
  amount: number;
  source: "monster" | "quest" | "party" | "other";
  sourceId?: number;
}

export interface LevelUpEvent extends BaseEvent {
  kind: "level_up";
  fromLevel: number;
  toLevel: number;
}

export interface MapChangeEvent extends BaseEvent {
  kind: "map_change";
  fromMapId: MapId;
  toMapId: MapId;
}

export interface DeathEvent extends BaseEvent {
  kind: "death";
}

export interface ActionEvent extends BaseEvent {
  kind: "action";
  action: MapleAction;
  accepted: boolean;
}

export interface ChatEvent extends BaseEvent {
  kind: "chat";
  fromCharacterId: EntityId;
  channel: "map" | "party" | "direct";
  message: string;
}

export interface EpisodeEndEvent extends BaseEvent {
  kind: "episode_end";
  reason: "timeout" | "completed" | "agent_exit" | "error";
}

/**
 * How much of the world an agent is allowed to see.
 *
 * `server-authoritative` is the original contract: object ids, absolute exp,
 * exact positions, monster hp. `human-equivalent` exposes only what the game
 * renders to a player, which is what a screen-reading adapter against a real
 * client can actually supply (see docs/LIVE_CLIENT_ADAPTER.md). Without the
 * distinction, "how much of the score comes from privileged state?" is not a
 * question the benchmark can ask.
 */
export type ObservationProfile = "server-authoritative" | "human-equivalent";

/**
 * A reading that may not have been observable on a given tick.
 *
 * Absent is not zero. A client draws no status bar during a map transition,
 * and counting gauge pixels there yields zero, which is indistinguishable
 * from zero HP unless the contract can say "not observable".
 */
export type Observable<T> =
  | { observable: true; value: T }
  | { observable: false; reason: "absent" | "unreadable" | "not-in-profile" };

/**
 * What a human-equivalent adapter can supply: gauge fractions rather than
 * absolute values, and no entity identity of any kind.
 */
export interface RenderedCharacterState {
  hpFraction: Observable<number>;
  mpFraction: Observable<number>;
  expFraction: Observable<number>;
  level: Observable<number>;
  alive: Observable<boolean>;
}

/** Actions addressable without an EntityId, for the human-equivalent profile. */
export type RenderedAction =
  | { type: "walk"; direction: "left" | "right"; durationMs: number }
  | { type: "attack_facing" }
  | { type: "use_skill_facing"; skillId: SkillId }
  | { type: "loot_nearby" }
  | { type: "use_item_slot"; slot: number }
  | { type: "jump" }
  | { type: "climb"; direction: "up" | "down"; durationMs: number };

/**
 * Whether an adapter's ActionResult.accepted means anything.
 *
 * A screen adapter cannot observe acceptance; it can at best confirm that the
 * frame changed. Runs whose acceptance is best-effort are not comparable with
 * runs whose acceptance comes from the server.
 */
export type AcceptanceFidelity = "authoritative" | "best-effort";

/** Per-episode adapter disclosure, recorded alongside the score. */
export interface AdapterProfile {
  name: string;
  observation: ObservationProfile;
  acceptance: AcceptanceFidelity;
  /** Median cost of one observe() call. Two orders of magnitude between
   *  adapters, so comparing scores without it compares plumbing. */
  observationLatencyMsP50: number;
}

export interface TaskSpec {
  id: string;
  version: number;
  title: string;
  durationSeconds: number;
  seed: string;
  /** Defaults to "server-authoritative" when absent, preserving v0 tasks. */
  observationProfile?: ObservationProfile;
  /** Cap on observe() calls, so a policy cannot buy score with observation
   *  frequency that one adapter happens to make cheap. */
  maxObservations?: number;
  character: {
    level: number;
    jobId: number;
    mapId: MapId;
    mesos: number;
    inventoryPreset: string;
    equipmentPreset: string;
  };
  world: {
    server: "cosmic-v83";
    timeScale: number;
    resetPolicy: "fresh-db-snapshot" | "character-reset";
  };
  allowedActions: MapleAction["type"][];
  scoring:
    | { type: "total_xp" }
    | { type: "peak_xp_rate"; windowSeconds: number };
}

export interface CombatAttackEvent extends BaseEvent {
  kind: "combat_attack";
  characterId: EntityId;
  mapId: MapId;
  skillId: SkillId;
  actionName: string;
  cooldownMs: number;
  hitDelayMs: number;
  speed: number;
  facingLeft: boolean;
}

export interface MonsterHitEvent extends BaseEvent {
  kind: "monster_hit";
  characterId: EntityId;
  mapId: MapId;
  /** combat_attack seq, or -1 when the application has no synchronous attack context. */
  attackId: number;
  objectId: EntityId;
  monsterId: number;
  position: Position;
  damage: number;
  /** Packet rolls; their sum can exceed HP loss through overkill or shared-handler adjustments. */
  damageLines: number[];
  criticalLines: number[];
  hpBefore: number;
  hpAfter: number;
  hpLoss: number;
  killed: boolean;
}

export interface PlayerHitEvent extends BaseEvent {
  kind: "player_hit";
  characterId: EntityId;
  mapId: MapId;
  source: "touch" | "fall";
  objectId: EntityId;
  monsterId: number;
  position: Position;
  damage: number;
  hpBefore: number;
  /** After the ordinary damage/autopot path; net loss can differ from damage. */
  hpAfter: number;
  miss: boolean;
  knockback: boolean;
  hurtCooldownMs: number;
}
