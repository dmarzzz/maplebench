# Final program slot candidate (not deployed)

`final_slot_cohort_protocol(profile)` explicitly opts into the frozen
`final-program-slot-v1` horizon policy. Existing presets, defaults, prompts and
historical horizon policies are unchanged. The transport remains the adaptive
pilot envelope; the policy, prompt and scenario hashes distinguish this version.
Do not merge its results into prior protocol cohorts.

The total wall clock remains 300 seconds including model latency, observations,
program execution and passive waits. Limits remain at most 12 requests, 240,000
tokens and the declared aggregate action/SDK budgets. There are no retries or
fallback inputs. The provider timeout stays 50 seconds; SDK holds and complete
3-second RPC admission are unchanged.

Ordinary programs remain 20 seconds. An ordinary request requires 150 seconds
remaining, preserving a conservative final-request reserve. At 150 seconds or
less, or on the final allowed request, the input declares one final execution
slot with a maximum of `min(145, remaining_at_offer - 5)` seconds. After inference
and evidence writes, its actual execution is clamped to the declared maximum
and the original deadline minus five seconds. It executes once. Early return or
an invalid final response leaves a truthful passive tail, never automatic replay.
Budget exhaustion, cancellation, death and uncertainty retain their existing
stop semantics. If persistence closes an unsent request window, no provider call
is charged or started; passive observation records that condition.

This can replace a long mandatory passive tail with model-authored execution,
but is not a promise of continuous input or higher XP. The final program may run
for up to 145 seconds using SDK observations without another LLM replan. That is
a meaningful responsiveness tradeoff and must be disclosed. A token reservation
limit can still prevent a final request; budgets are never enlarged to guarantee
that slot. No model-specific scheduler tuning is applied.

New cycle evidence binds the offered slot, its admission reserve, and effective
execution budget/deadline. Offline validation recomputes the offer from the
request, checks serial final-slot use and clamps, and rejects substitution into
an old frozen policy. The unchanged executor already accepts the supplied
per-program seconds and absolute deadline; its RPC and Docker limits remain
unchanged. A deployment still needs composed Linux/actual sandbox qualification
and a fresh cohort; local fake-clock tests are not live acceptance.
