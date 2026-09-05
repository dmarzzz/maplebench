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

export interface TaskSpec {
  id: string;
  version: number;
  title: string;
  durationSeconds: number;
  seed: string;
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
