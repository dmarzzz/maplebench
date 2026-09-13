# Baseline release checklist

The first reference condition is five minutes of ordinary observe/act/replan,
with no separate reflection pass, candidate search, or memory across trials.
Keep its exact policy and results permanently. Subsequent methods receive new
identities and matched evaluation budgets; they do not replace this baseline.

Initial matrix: Astra, Sol, Terra and Luna on Hero, Bowmaster,
Ice/Lightning Arch Mage and Night Lord. Compare models within each frozen class
fixture. A first matrix is a pilot; repeated, randomized trials are needed for
reliable performance estimates. Preserve unsuccessful attempts and distinguish
model failures from environment/recording failures.

## Completed source work

- [x] Versioned baseline prompt and execution path, with exact named controls.
- [x] Frozen budgets/history, unchanged execution of returned programs, no replay.
- [x] Runtime and admission bind the new baseline source dependency.
- [x] Separate zero-model productive and no-input controls; neither qualifies a class.
- [x] Source regression and candidate repair for ignored magic attack/spell power.
- [x] Source regression and candidate repair for Bow Expert mastery/weapon attack.
- [x] Source regression and candidate repair for Arrow Bomb's missing `damage`
  field: the pinned definition stores 130% in `x`.
- [x] Source regression and repair for learned Critical Shot/Throw, physical
  skill/defense order, and Lucky Seven/Triple Throw's LUK-based range.
- [x] Source-only `0013` repair for Shadow Stars' zero-valued buff recognition
  and asset-derived upfront star-cost admission; not built or live-qualified.

## Completed native preparation

- [x] Build the combined patched client and retain source/binary fingerprints.
- [x] Mage productive control: 91 input actions, +14,000 saved XP, ordinary logout.
- [x] Mage no-input control: zero input actions, 0 saved XP, ordinary logout.
- [x] Both Mage controls have verified captures and restore the same character,
  gameplay attack/jump bindings and USE inventory; original evidence is backed up.
- [x] Bowmaster productive control: 84 input actions, +4,750 saved XP, ordinary logout.
- [x] Bowmaster no-input control: zero input actions, 0 saved XP, ordinary logout.
- [x] Both Bowmaster controls have verified captures and restore the same
  character, keymap and USE inventory; original evidence is backed up.
- [x] Hero productive control: 91 input actions, +13,750 saved XP, ordinary logout.
- [x] Hero no-input control: zero input actions, 0 saved XP, ordinary logout.
- [x] Both Hero controls restore character, keymap and USE inventory, with
  captures and original evidence backed up.
- [x] Night Lord productive control: 85 input actions, +13,750 saved XP,
  ordinary logout and restored baseline; 87 persisted stars consumed and restored.
- [x] Night Lord no-input control: zero input actions, 0 saved XP, ordinary logout.
- [x] Both Night Lord controls have captures and original evidence backed up;
  character, keymap and USE inventory restored, with no idle star consumption.

The [native readiness record](NATIVE_BASELINE_READINESS.md) gives exact run IDs,
counts, durations and build hashes. These are scripted controls with no model
and zero API calls. All four pairs are complete; they do not establish full
skill behavior, potion use or model performance, or qualify the separate native
XP-window ledger.

## Before model admission

- [ ] Verify actual native attacks, movement, buffs and resources on each fixture.
- [x] Every class's productive control earns positive native XP and saves it
  through ordinary logout.
- [x] Every class's no-input control has no unexplained earned XP and both
  controls restore the same baseline.
- [ ] Resolve the declared skill set. Mapped keys and learned skill rows do not prove implemented effects.
- [ ] Freeze exact fixtures, model IDs/settings, prompt, run order, failure rules,
  cost limits and comparison identity.
- [ ] Execute the first matched four-model trials and publish original evidence
  after each completed, independently checked attempt.
- [ ] Complete all four classes, then repetitions and uncertainty estimates.

## Skill-set decision remains material

The current expanded toolkit is provisional. It is **not the complete canonical
class kit**. The audit found these remaining groups of work:

| Class | Important remaining mechanics |
| --- | --- |
| Hero | Combo/Advanced Combo damage semantics; Monster Magnet target route; full status/effect qualification |
| Bowmaster | Continuous Hurricane, Sharp Eyes stacking, Puppet/Hawk/Phoenix; full status/effect qualification |
| Ice/Lightning | Charged Big Bang, Ifrit, full elemental/status semantics; all advertised buffs/effects need native proof |
| Night Lord | Flash Jump, Shadow Partner damage lines, Shadow Stars upfront-cost/buff and consumption verification, Shadow Web/Ninja Ambush; full status/effect qualification |

Critical Shot and Critical Throw were also absent in the audited client. Their
repair is now in the combined build; source tests and productive controls do not
isolate native critical behavior on Bowmaster or Night Lord.
Shadow Stars' per-attack ammunition exemption is already server-owned. The
[0013 client repair](FULL_CLIENT_SHADOW_STARS.md) preserves real projectile
requirements and server-owned inventory changes; it still needs a new build,
fixture/policy identity, and live cost, consumption, cancellation and save proof.
Night Lord's Flash Jump skill assets contain MP costs but no movement impulse.
An unverified movement approximation must not be presented as canonical behavior.

Shipping an explicitly limited, verified toolkit is a different scope from
shipping all class skills. Neither a productive scripted control nor successful
model gameplay resolves the full-kit requirement. The website must describe the
actual frozen environment rather than infer completeness from skill counts.

The fixed-level baseline also retains the existing fail-closed level-change rule.
Current measured Mage starts are level 180 with EXP 73,250; equal starts do not
require EXP zero. A progression-enabled successor must use the independently
verified native ledger, not subtract wrapped per-level XP values.

See [the permanent agent policy](FULL_CLIENT_BASELINE_V1.md),
[experiment design](BASELINE_EXPERIMENT_DESIGN.md), and
[spell repair](FULL_CLIENT_SPELL_DAMAGE.md). These checkboxes describe release
work; they are not benchmark results.
