# Cosmic bot method map

This file records concrete integration points observed in `NDBellisario/cosmic` so the adapter work starts from real server APIs rather than guessed abstractions.

## Movement

`server.bots.BotTask` already exposes a task primitive:

```java
BotTask.moveTo(Point point, boolean precise)
```

`BotScriptContext.queueMoveTo` demonstrates the intended invocation:

```java
manager.queueTask(entry, BotTask.moveTo(point, precise));
```

Because the MapleBench adapter should live in the `server.bots` Java package, it can use package-private `BotEntry` / `BotManager` helpers without widening the entire bot API.

**MapleBench mapping:**

```text
move_to(x, y)
  -> BotManager.queueTask(entry, BotTask.moveTo(new Point(x, y), true))
  -> existing navigation/physics tick
  -> normal movement broadcasts visible to clients
```

This is exactly what we want: the action specifies an intention/target point, but the existing bot navigation/physics implementation performs the actual physical traversal.

## Resolving a benchmark bot

`BotManager` is a singleton:

```java
BotManager.getInstance()
```

It stores bot entries per owner and has package-private helpers including:

```java
List<BotEntry> getBotEntries(int ownerCharId)
BotEntry getFirstBotEntry(int ownerCharId)
```

For v0, the adapter can bind an episode to `{ownerCharId, botCharId}` and retain the resolved `BotEntry` after start. We do not need to make the entire bot registry public.

## Combat

`BotCombatManager` has the useful physical execution path:

```java
AttackPlan planAttack(BotEntry entry, Character bot, Monster target)
void attackMonster(BotEntry entry, Character bot, AttackPlan attackPlan)
```

`attackMonster` builds normal `AttackInfo`, resolves damage through the existing combat formula/provider, applies the proper attack route, updates cooldowns/facing, and therefore stays visible/consistent with normal game behavior.

However, `planAttack` chooses the best attack from the bot's cached skills plus basic attack. That is **too much hidden policy for an eval**. If an agent asks for basic attack or a specific skill, the server should execute that requested action or reject it—not silently optimize for the agent.

Inside `BotCombatManager`, the desired lower-level planners already exist but are private:

```java
planBasicAttack(Character bot, Monster target)
planSkillAttack(BotEntry entry, Character bot, Monster target, int skillId)
```

So MapleBench only needs a tiny package-private wrapper (see `patches/cosmic/0001-expose-requested-attack-plan.patch`):

```java
static AttackPlan planRequestedAttack(
    BotEntry entry,
    Character bot,
    Monster target,
    int skillId
)
```

with `skillId == 0` meaning basic attack.

**MapleBench mapping:**

```text
basic_attack(targetId)
  -> find visible Monster by object id
  -> planRequestedAttack(..., 0)
  -> reject if null/out-of-range/cooldown
  -> attackMonster(...)

use_skill(skillId, targetId)
  -> find visible Monster by object id
  -> planRequestedAttack(..., skillId)
  -> reject if skill is unavailable/out-of-range/cooldown
  -> attackMonster(...)
```

## Important hidden-policy removals

The bot fork contains useful baselines, but evaluated agents must not have access to them:

- `BotTask.grind()`
- `findGrindTarget(...)`
- automatic best-attack selection (`planAttack`) as the public eval action
- automatic AP/SP assignment
- auto-equip optimization
- automatic quest completion
- PQ automation
- automatic potion/share logic unless the benchmark explicitly makes those passive mechanics part of the environment

These routines should remain available for **baseline evaluation**: hand-engineered bot vs. frontier model is a useful comparison.

## First server-side coding target

Implement `MapleBenchController` inside `server.bots` with no networking initially:

```java
Observation observe(EpisodeHandle episode)
ActionResult moveTo(EpisodeHandle episode, int x, int y)
ActionResult basicAttack(EpisodeHandle episode, int targetObjectId)
ActionResult useSkill(EpisodeHandle episode, int skillId, int targetObjectId)
```

Test those four calls from a server command/JUnit harness first. Only after they behave correctly should we add HTTP/JSON. This separates "can the benchmark safely control the game?" from networking/MCP work.
