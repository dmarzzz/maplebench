# Immediate next work

## When the GitHub repo exists

Create an empty repository named `maplebench` (prefer private for the first prototype while asset/licensing boundaries are still being validated). Then either push this local git history or tell ChatGPT the repo exists; the connected GitHub integration can write commits to an existing repository.

Current local baseline commit:

```text
3e797aa8bba8dae6d2eec2e1e12b78863aa511c4  Initial MapleBench scaffold
```

A second commit adds the concrete Cosmic method map and first proposed server patch.

## Coding order

1. Pin `NDBellisario/cosmic` to a commit.
2. Apply/test `0001-expose-requested-attack-plan.patch`.
3. Add `server.bots.MapleBenchController` in the Cosmic working tree.
4. Implement only `observe`, `moveTo`, `basicAttack`, `useSkill`.
5. Manually control one spawned bot through those methods and verify another client can see it.
6. Add XP event logging at the actual EXP award path.
7. Put the controller behind localhost HTTP/JSON.
8. Point the TypeScript `HttpMapleTransport` at it.
9. Run `maximize-xp-10m` end to end.
10. Add observer video capture.

Do not build Harbor/MCP/PQ orchestration before step 9; the current SDK/task contract is enough to keep those layers unblocked.
