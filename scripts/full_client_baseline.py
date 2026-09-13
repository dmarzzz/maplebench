"""Permanent ordinary-replanning baseline; no runtime I/O or class admission.

The optional policy uses the existing adaptive execution/evidence path. Changing
its prompt, cadence, history or controls requires a new policy identity. A class
toolkit must be supplied explicitly; source validation is not live qualification.
"""
import copy
import hashlib
import json

from full_client_skill_toolkit import profile, prompt_reference, validate_toolkit

POLICY_ID = 'full-client-adaptive-baseline-v1'
_POLICY = {
    'schema_version': 1, 'id': POLICY_ID,
    'objective': 'maximize_signed_native_net_xp',
    'feedback': 'fresh_observation_and_recent_execution',
    'recent_programs': 2, 'recent_sdk_receipts_per_program': 5,
    'explicit_reflection': False, 'candidate_search': False,
    'cross_run_memory': False,
}
_BASE_KEYS = ('LEFT', 'RIGHT', 'UP', 'DOWN', 'JUMP', 'ATTACK',
              'HP_POTION', 'MP_POTION')


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode()


def policy():
    return copy.deepcopy(_POLICY)


def _binding(kit):
    # Literal values keep v1 independent of later changes to convenience presets.
    kit = validate_toolkit(kit)
    return {
        'schema_version': 1, 'id': 'full-client-adaptive-pilot-v1',
        'wall_seconds': 300, 'program_seconds': 20,
        'max_api_requests': 12, 'max_output_tokens': 3000,
        'max_total_tokens': 240000, 'max_actions': 1600,
        'max_sdk_requests': 6000, 'max_evidence_bytes': 4194304,
        'profile': profile(kit), 'skill_toolkit': kit,
        'horizon_policy': {
            'id': 'full-horizon-reserve-v1', 'request_timeout_seconds': 50,
            'settlement_reserve_seconds': 5,
            'passive_observation_interval_ms': 1000,
        },
        'capture_duration_policy': {
            'id': 'post-render-encoded-frame-v1', 'max_endpoint_gap_ms': 250,
            'max_wall_drift_ms': 5, 'timestamp_slack_ms': 2,
            'max_frame_gap_ms': 1000, 'max_frames': 20000,
        },
        'baseline_policy': policy(),
    }


def validate_binding(value):
    """Reject mixed budgets, horizons, profiles, history and policy versions."""
    try:
        expected = _binding(value['skill_toolkit'])
        if _encoded(value) != _encoded(expected):
            raise ValueError()
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError('invalid_baseline_protocol') from None
    return expected


def protocol(skill_toolkit):
    """Prepare one explicit toolkit binding; never select or qualify a class."""
    # Deferred import avoids a cycle: adaptive validation calls validate_binding.
    from full_client_adaptive import validate_protocol
    return validate_protocol(_binding(skill_toolkit))


def fingerprint(value):
    return hashlib.sha256(_encoded(validate_binding(value))).hexdigest()


def prompt(value):
    value = validate_binding(value)
    kit = value['skill_toolkit']
    keys = list(_BASE_KEYS) + [skill['slot'] for skill in kit['skills']]
    return f'''You control a level 180 {value['profile']['class_name']} in the MapleStory v83 full client.
Agent policy: {POLICY_ID}. This is the permanent five-minute ordinary-replanning baseline.
Objective: maximize verified signed native net XP earned during this run while
keeping the character alive. Native losses count; zero and negative outcomes are
retained. Client XP is diagnostic, not an authoritative score. A skill is useful
when it helps this objective; you do not need to demonstrate every available skill.

Each request supplies fresh observed state, remaining budgets, and at most two
recent programs with execution outcomes and their last five SDK receipts. Choose
and execute the next bounded program from that feedback. There is no separate
critique/reflection call, candidate population, search evaluator or cross-run memory.
Local variables do not survive between responses. Programs run unchanged once;
there is no human repair, automatic replay or hidden combat policy.

Return JSON {{note,code}}: a brief intention and a JavaScript async function BODY.
Use top-level await; defining a helper alone does nothing, so await its call.
Use only these SDK methods:
  sdk.observe(): current character {{x,y,hp,maxHp,mp,maxMp,exp,alive,mapId,level}}
    and nearby monsters [{{objectId,x,y}}]. No monster HP, terrain geometry,
    cast-success flag or cooldown state is promised.
  sdk.pressKeys(keys,milliseconds): hold 1..3 named controls for 30..1500ms.
  sdk.wait(milliseconds): wait 1..3000ms.
Complete allowed sdk.pressKeys controls: {json.dumps(keys)}.
Use those exact names. Browser letters, keyboard codes, numeric skill IDs and
skill names are not SDK controls. For example:
  const state = await sdk.observe();
  await sdk.pressKeys(['PRIMARY_SKILL'], 100);
  await sdk.wait(1500);
  const after = await sdk.observe();
Coordinates increase rightward/downward. Use fresh observations inside loops.
Ordinary facing, distance and platform alignment matter. A key acknowledgement
proves delivery, not a cast or hit; observe actual position and resources before
deciding the next action. Allow casting time: about 2500ms after buffs and 1500ms
after attacks, then observe. Mapped native movement skills use the same controls;
there is no moveTo, target-by-ID, useSkill, stat edit, refill or asset access.

The original wall deadline is 300 seconds, including inference, programs and
waits. The world stays live during inference. Each program gets at most 20 seconds
and the remaining aggregate budget; return before its deadline. At most 12 model
requests, 3000 output tokens per response, 240000 aggregate reserved/actual tokens,
1600 attempted actions and 6000 SDK requests are allowed. The model uses low
reasoning effort. No extra reflection request or token allowance is supplied.
A new request requires 75 seconds remaining: 50 for inference, 20 for execution,
and 5 for settlement. Once that window or a confirmed aggregate budget closes,
the controller only observes until the original deadline; it performs no combat.
Death, cancellation, stale observations or uncertain input/provider receipts stop
the run. The original failed operation is never replayed.
''' + prompt_reference(kit, include_physical_keys=False)
