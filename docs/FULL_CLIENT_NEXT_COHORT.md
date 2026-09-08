# Next four-model capture cohort

`full_client_adaptive.capture_cohort_protocol(profile)` prepares the frozen
`full-horizon-capture-cohort-v1` recipe. It does not start a trial, change the
existing default protocol, or modify earlier plans.

The protocol remains `full-client-adaptive-pilot-v1`, with the existing
`full-horizon-reserve-v1` policy and the new
`post-render-frame-envelope-v1` capture contract. The conservative total-token
reservation allowance rises from120000 to240000 per trial. This is a ceiling,
not a spending target or reported provider usage. Unused reservations still are
not recycled, and actual provider usage remains recorded separately.

All four models within a class receive the same limits:

| Limit | One model | Four-model group |
|---|---:|---:|
| Model requests |12|48|
| Conservative total-token allowance |240000|960000|
| Output tokens per response |3000| — |
| Aggregate output-token ceiling |36000|144000|
| Model wall budget |300s|1200s|
| Operation deadline |360s| — |
| Whole trial deadline |1200s|4820s including20s coordinator margin |
| Input actions |1600|6400|
| SDK requests |6000|24000|

Individual model programs remain bounded to20s; fresh dispatch still requires
50s inference +20s execution +5s settlement reserve. A larger token allowance
can permit additional confirmed cycles, but it does not promise continuous
inputs until300s. The observer-only hold, failures, death, no replay rule and
exact model attribution remain unchanged. Tests demonstrate more confirmed
cycles under the higher ceiling without retries or a longer wall clock.

The private R3 preparation helper selects the new source preset and derives
trial and group budgets from it. Preparation still requires fresh attempt IDs,
an unused output/experiment directory, supplied baseline and offline snapshot,
current source/runtime pins, existing operation gate and ordinary locks. It
performs no service, database, browser or API action. Its host-specific paths and
configuration are intentionally outside Git.

Every class and this changed recipe require new scenario/protocol fingerprints.
The request shape, trace, frozen scenario and public fixture grouping keep these
results separate from older120000-token or schema-1 capture runs. The prompt text
is unchanged by these capture and reservation settings; the scenario/protocol
hashes still change. Do not reuse an earlier plan, identity or native acceptance
receipt to imply acceptance of the new capture collector.

## Native acceptance blockers

Hero has prior native movement, contact, ordinary persistence and model evidence.
That does not validate the new schema-2 capture offsets; a fresh bounded capture
must pass collection, packet/frame accounting, publication and visual checks.

Bowmaster and Ice/Lightning profiles are prepared fixtures whose reviewed
acceptance recipes are still marked unexecuted. Before model trials, each needs
its own stopped-world baseline restore, matching offline snapshot and all
native skill/equipment/passive bindings checked. The generator's snapshot check
covers character/job/level and ordinary control keys; it is not proof of class
skill activation or equipment correctness.

| Class | Required native effects before dispatch |
|---|---|
| Hero | Vertical jump displacement, attack/skill contact, verified recording and ordinary logout/save under the new frozen source. |
| Bowmaster | Job312; Soul Arrow : Bow on D **before any bow contact check** because no arrow stack is injected; Sharp Eyes on F; Hurricane on A and Arrow Rain on S hit real monsters; MP/buff behavior recorded. |
| Ice/Lightning Arch Mage | Job222; Magic Guard on D, Spell Booster on F, Chain Lightning on A hits real monsters, Teleport on S produces native displacement; HP/MP changes recorded, including passive modifiers. |

The existing bounded scripted acceptance recipe allows at most30s,12 input calls
and1.5s per hold, with no automatic retry. A key acknowledgement or empty animation
does not prove contact. Verify a suitable actual target and observe effects.
The old Bowmaster recipe orders Control before Soul Arrow; correct that ordering
in the newly frozen acceptance recipe before execution.

After acceptance, ordinary logout and native save verification must precede a
fresh restore of that class's immutable baseline and new group freeze. Compare
models within a class/fixture; declared class stats and equipment do not establish
equal difficulty across classes. This pilot still requires its frozen level and
reports signed persisted net XP. It does not adopt the separate native XP-window
or level-progression research protocol.
