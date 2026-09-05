# Programmable OpenAI controller

`scripts/maple_agent.py` lets each OpenAI model write a short JavaScript program,
observe its effects, and revise it on the next turn. All inference uses the
OpenAI Responses API with `store: false`; no inference runs on the game host.
Programs choose their own targets, skills, movement, and timing. There is no
automatic targeting or grinding policy underneath the controller.

The queue resets the scenario, starts observation recording, calls `run_agent`,
then reads canonical game events to score and render the trial. The controller
does not reset the game or compute the authoritative score.

```python
from maple_agent import run_agent

result = run_agent(
    model="gpt-6-astra",
    scenario={
        "id": "henesys-slimes-warrior-v1",
        "objective": "Defeat the three Slimes while staying alive.",
        "allowed_skills": [1001004],
        "allowed_items": [],
    },
    base_url="http://127.0.0.1:8790",
    api_key=key_from_external_runtime_file,
    output_dir="artifacts/trial-001",
    max_calls=12,
    max_output_tokens=1800,
    max_total_tokens=30000,
    wall_seconds=90,
    program_seconds=15,
    max_actions=500,
    stop_when=lambda obs: not any(m["alive"] for m in obs["monsters"]),
    on_decision=account_for_batch_usage,
)
```

Use no `stop_when` callback for a respawning map that should run until its time
budget. The game continues during model requests, and API latency counts toward
the wall-clock limit. Compare the same scenario and limits across models.

The four permitted model IDs are `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`,
and `gpt-5.6-luna`. Model requests use low reasoning effort and strict structured
output containing `{note, code}`. The note describes intended actions; it does
not request private reasoning.

## Program SDK

Every method is asynchronous. Coordinates are integers; target IDs come from
observations. Movement returns an action receipt before the character arrives.

| Method | Effect |
| --- | --- |
| `sdk.observe()` | Read current game state. |
| `sdk.moveTo(x, y)` | Request ordinary physics-based navigation. |
| `sdk.attack(targetId)` | Request a basic attack on the selected target. |
| `sdk.useSkill(skillId, targetId)` | Request a scenario-approved skill. |
| `sdk.useItem(itemId)` | Consume a scenario-approved inventory item, if the game bridge supports it. |
| `sdk.wait(ms)` | Wait between 1 and 3,000 ms. |

For example, a model may write:

```js
for (let i = 0; i < 8; i++) {
  const observation = await sdk.observe();
  const target = observation.monsters.find(monster => monster.alive);
  if (!target || !observation.character.alive) break;
  const position = observation.character.position;
  if (Math.abs(target.position.x - position.x) > 50) {
    await sdk.moveTo(target.position.x, target.position.y);
  } else {
    await sdk.useSkill(1001004, target.objectId);
  }
  await sdk.wait(500);
}
```

This is an illustration, not a fallback policy. The controller executes only
the program returned by the selected API model. Programs receive no shell,
administration, reset, stat editing, or arbitrary HTTP proxy method.

## Isolation and limits

Download the Docker image on the remote runner before starting a batch. The
default is `node:22.19.0-bookworm-slim`. The runner uses `--pull=never` so trials
cannot trigger surprise downloads. A worker may pass a digest-pinned image using
`docker_image`. If the dedicated operator uses passwordless sudo for Docker, set
`MAPLEBENCH_DOCKER_COMMAND='sudo -n docker'` in its external service configuration.

Each program gets a fresh Docker container with no network, no host bind mounts,
no inherited credentials, a read-only root, an unprivileged UID, no Linux
capabilities, and no-new-privileges. Memory is capped at 256 MiB, CPU at 0.5,
processes at 32, and Node's old-space heap at 96 MiB. The SDK bootstrap is passed
as a Node command argument and model code arrives on stdin. Docker, rather than
JavaScript `AsyncFunction`, provides the security boundary.

The host proxies JSON-lines requests over stdin/stdout. It validates the exact
envelope, method, argument count, integer types, coordinate bounds, action
allowlist, skill IDs, and item IDs. The proxy has only two fixed game routes:
`/v1/observe` and `/v1/action`. Each program is limited to 100 SDK requests,
128 KiB output, 16 KiB protocol lines, and its execution deadline. Action limits
count attempted server mutations, including rejected attacks, across programs.

An independent GNU `timeout` inside the container also kills CPU-bound programs.
Stdin EOF handles worker disconnects; the independent timeout covers programs
that block Node's event loop. Normal cleanup explicitly removes the named
container and its children. A Docker daemon outage can delay cleanup; the
container's independent deadline remains active. Cleanup may add up to a few
seconds after gameplay stops. HTTP calls run in a bounded trusted Python helper
so a slow network read cannot hold the controller indefinitely. A cancelled API
request may still be billed by the provider; its outcome is unknown if no
response arrived.

API call count, output tokens per call, total accounted tokens, action count,
and wall time are bounded. Before a request, a conservative UTF-8 byte estimate
reserves input and maximum output tokens. Actual returned usage replaces the
estimate; missing usage is charged conservatively. This is an operational token
budget, not an exact dollar cap. The batch runner should account for usage in
`on_decision`; returning `False` or raising `BudgetLimit` stops the trial with
`budget_limit`, preserving its records.

The result's `usage_complete` flag is false if any started API request has no
returned usage, including a request interrupted at the overall time limit. The
queue must retain the trial's reservation in that case; a `time_limit` outcome
does not by itself prove that provider usage is fully known.

Model logs and completion messages are untrusted presentation data. They cannot
award XP or prove task success. Scores must use the game server's event log.

## Records and verification

The controller writes `controller.json`, `prompt.txt`, atomic `decisions.json`,
flushed `steps.jsonl`, and `agent-result.json` inside the ignored trial output
directory. Decisions include code, response model identity, token usage, latency,
execution outcome, and bounded logs. SDK steps retain server observations and
receipts. Endpoint failure bodies and Docker stderr are deliberately omitted
because they may contain private runtime details. API credentials are never
written to artifacts or passed to a generated-code container.

Run the ordinary protocol and budget tests without Docker:

```sh
python3 -m unittest discover -s test -p 'test_maple_agent.py'
```

On the remote runner, also exercise the real isolation boundary:

```sh
MAPLEBENCH_TEST_DOCKER=1 MAPLEBENCH_DOCKER_COMMAND='sudo -n docker' \
  python3 -m unittest discover -s test -p 'test_maple_agent.py'
```

The Docker checks use a fake game endpoint in the trusted Python parent. They
verify actual SDK round trips, credential separation, rejection of unapproved
skills and forged privileged requests, action limits, and termination of an
infinite JavaScript loop. They do not mutate a running game.
