"""Build and check a frozen adaptive trial scenario, offline.

The frozen scenario is the artifact the runtime, planner, bridge and publisher all
pin. Until now its only generator lived in private operator scripts, and there was
no way to recompute `instructions_sha256` without hand-hashing the prompt. That
made a reproducible freeze impossible to review. This module is that generator,
committed, with the runtime's own validators as the source of truth.

It is pure computation: no network, no database, no services, no browser, and it
never reads private baseline snapshots. The caller supplies `expected_map_id`,
which must equal the frozen baseline character's map id — this module cannot
verify that and does not pretend to.

    python3 scripts/full_client_scenario_freeze.py hash --level 180 --class Hero
    python3 scripts/full_client_scenario_freeze.py build \
        --id hero-cave-v1-pilot --expected-map-id 240050300 \
        --profile-id hero-150 --class Hero --level 150 \
        --primary Brandish --secondary 'Combo Attack' \
        --buff1 Booster --buff2 Rage --output scenario.json

Exit codes: 0 success, 1 invalid inputs, 2 unwritable or existing output.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import full_client_readiness as readiness
from full_client_adaptive import (DEFAULT_PROTOCOL, FULL_HORIZON_POLICY, PROTOCOL, AdaptiveError,
                                  prompt, validate_protocol)

# Mirrors full_client_runtime.SETTLEMENT_POLICY. Importing the runtime here would
# drag in its Linux/root host checks, so the value is duplicated and pinned by a
# test that compares the two.
SETTLEMENT_POLICY = {"capture_tail_ms": 2000, "upload_after_program_ms": 5000,
                     "disconnect_after_program_ms": 5000, "logout_after_disconnect_ms": 5000}

# full_client_runtime requires run_ms == (wall_seconds + RUN_RESERVE_S) * 1000 for
# the adaptive path. This is NOT the legacy one-shot rule of program_seconds + 63.
RUN_RESERVE_S = 35
SETTLEMENT_RESERVE_S = 25


class ScenarioError(ValueError):
    """Fixed, credential-free codes only."""


def require(value, code):
    if not value:
        raise ScenarioError(code)


def build_profile(profile_id, class_name, level, skill_keys):
    """Assemble and validate a profile without touching the shared default."""
    profile = {"id": profile_id, "class_name": class_name, "level": level,
               "skill_keys": dict(skill_keys)}
    protocol = copy.deepcopy(DEFAULT_PROTOCOL)
    protocol["profile"] = profile
    try:
        validate_protocol(protocol)
    except AdaptiveError as error:
        raise ScenarioError(str(error)) from None
    return profile


def build_protocol(profile, *, full_horizon=True, max_total_tokens=240000):
    """A frozen protocol for one cohort. Defaults are never mutated."""
    protocol = copy.deepcopy(DEFAULT_PROTOCOL)
    protocol["profile"] = copy.deepcopy(profile)
    protocol["max_total_tokens"] = max_total_tokens
    if full_horizon:
        protocol["horizon_policy"] = copy.deepcopy(FULL_HORIZON_POLICY)
    try:
        return validate_protocol(protocol)
    except AdaptiveError as error:
        raise ScenarioError(str(error)) from None


def instructions_sha256(protocol):
    """SHA-256 of the exact prompt bytes the runtime will re-derive and compare."""
    try:
        text = prompt(protocol)
    except AdaptiveError as error:
        raise ScenarioError(str(error)) from None
    return hashlib.sha256(text.encode()).hexdigest(), text


def budgets_for(protocol):
    """The bridge budget block the runtime checks field by field."""
    wall = protocol["wall_seconds"]
    return {"api_requests": protocol["max_api_requests"],
            "output_tokens": protocol["max_api_requests"] * protocol["max_output_tokens"],
            "total_tokens": protocol["max_total_tokens"],
            "program_ms": wall * 1000,
            "run_ms": (wall + RUN_RESERVE_S) * 1000,
            "actions": protocol["max_actions"],
            "sdk_requests": protocol["max_sdk_requests"]}


def trial_budgets_for(protocol, *, total_seconds):
    wall = protocol["wall_seconds"]
    operation_seconds = wall + RUN_RESERVE_S + SETTLEMENT_RESERVE_S
    require(type(total_seconds) is int and total_seconds >= operation_seconds,
            "invalid_trial_total_seconds")
    return {"total_seconds": total_seconds,
            "operation_seconds": operation_seconds,
            "controller_seconds": wall,
            "max_actions": protocol["max_actions"],
            "max_api_requests": protocol["max_api_requests"],
            "max_output_tokens": protocol["max_api_requests"] * protocol["max_output_tokens"],
            "max_total_tokens": protocol["max_total_tokens"]}


def build_scenario(scenario_id, protocol, expected_map_id, *, total_seconds=1200):
    """Return a complete frozen adaptive scenario object."""
    require(isinstance(scenario_id, str) and 0 < len(scenario_id) <= 128
            and scenario_id.strip() == scenario_id, "invalid_scenario_id")
    protocol = validate_protocol(protocol)
    policy = {"schema_version": 1, "expected_map_id": expected_map_id, "min_monsters": 1,
              "min_samples": 3, "min_span_ms": 1000, "timeout_ms": 10000}
    try:
        policy = readiness.validate_policy(policy, expected_map_id=expected_map_id)
    except readiness.ReadinessError as error:
        raise ScenarioError(str(error)) from None
    digest, _ = instructions_sha256(protocol)
    return {"schema_version": 1,
            "id": scenario_id,
            "protocol": PROTOCOL,
            "program_seconds": protocol["wall_seconds"],
            "adaptive_protocol": protocol,
            "instructions_sha256": digest,
            "reasoning": {"effort": "low"},
            "trial_budgets": trial_budgets_for(protocol, total_seconds=total_seconds),
            "budgets": budgets_for(protocol),
            "readiness_policy": policy,
            "settlement_policy": dict(SETTLEMENT_POLICY)}


def check_scenario(scenario):
    """Re-derive every computed field. Raises on the first disagreement.

    This is the offline half of what the runtime enforces before it will start a
    controller. Passing here does not authorize a trial and does not prove the
    baseline snapshot, runtime manifest or keymap match.
    """
    require(isinstance(scenario, dict), "invalid_frozen_scenario")
    require(set(scenario) == {"schema_version", "id", "protocol", "program_seconds",
                              "adaptive_protocol", "instructions_sha256", "reasoning",
                              "trial_budgets", "budgets", "readiness_policy",
                              "settlement_policy"}, "invalid_frozen_scenario")
    require(scenario["schema_version"] == 1 and type(scenario["schema_version"]) is int
            and scenario["protocol"] == PROTOCOL, "invalid_frozen_scenario")
    protocol = validate_protocol(scenario["adaptive_protocol"])
    require(scenario["program_seconds"] == protocol["wall_seconds"], "invalid_program_seconds")
    require(scenario["reasoning"] == {"effort": "low"}, "invalid_reasoning")
    require(scenario["settlement_policy"] == SETTLEMENT_POLICY, "invalid_settlement_policy")
    digest, _ = instructions_sha256(protocol)
    require(scenario["instructions_sha256"] == digest, "frozen_prompt_mismatch")
    require(scenario["budgets"] == budgets_for(protocol), "frozen_bridge_budgets_mismatch")
    expected_map = scenario["readiness_policy"].get("expected_map_id") \
        if isinstance(scenario["readiness_policy"], dict) else None
    try:
        readiness.validate_policy(scenario["readiness_policy"], expected_map_id=expected_map)
    except readiness.ReadinessError as error:
        raise ScenarioError(str(error)) from None
    trial = scenario["trial_budgets"]
    require(isinstance(trial, dict) and type(trial.get("total_seconds")) is int,
            "invalid_trial_budgets")
    require(trial == trial_budgets_for(protocol, total_seconds=trial["total_seconds"]),
            "invalid_trial_budgets")
    return scenario


def _write_new(path, text):
    """Never overwrite a frozen artifact; a new version gets a new file."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    with os.fdopen(os.open(path, flags, 0o644), 'w', encoding='utf-8') as handle:
        handle.write(text)


def _skill_keys(args):
    pairs = (('PRIMARY_SKILL', args.primary), ('SECONDARY_SKILL', args.secondary),
             ('BUFF_1', args.buff1), ('BUFF_2', args.buff2))
    return {key: value for key, value in pairs if value is not None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)

    def add_profile_args(target):
        target.add_argument('--profile-id', default=DEFAULT_PROTOCOL['profile']['id'])
        target.add_argument('--class', dest='class_name',
                            default=DEFAULT_PROTOCOL['profile']['class_name'])
        target.add_argument('--level', type=int, default=DEFAULT_PROTOCOL['profile']['level'])
        target.add_argument('--primary', default='Brandish')
        target.add_argument('--secondary', default='Combo Attack')
        target.add_argument('--buff1', default='Booster')
        target.add_argument('--buff2', default='Maple Warrior')
        target.add_argument('--no-full-horizon', action='store_true')
        target.add_argument('--max-total-tokens', type=int, default=240000)

    hash_cmd = sub.add_parser('hash', help='print the prompt and its frozen hash')
    add_profile_args(hash_cmd)
    hash_cmd.add_argument('--show-prompt', action='store_true')

    build_cmd = sub.add_parser('build', help='emit a complete frozen scenario')
    add_profile_args(build_cmd)
    build_cmd.add_argument('--id', required=True)
    build_cmd.add_argument('--expected-map-id', type=int, required=True)
    build_cmd.add_argument('--total-seconds', type=int, default=1200)
    build_cmd.add_argument('--output')

    check_cmd = sub.add_parser('check', help='re-derive every computed field of a scenario')
    check_cmd.add_argument('path')

    args = parser.parse_args(argv)

    try:
        if args.command == 'check':
            with open(args.path, encoding='utf-8') as handle:
                check_scenario(json.load(handle))
            sys.stdout.write('ok\n')
            return 0

        profile = build_profile(args.profile_id, args.class_name, args.level, _skill_keys(args))
        protocol = build_protocol(profile, full_horizon=not args.no_full_horizon,
                                  max_total_tokens=args.max_total_tokens)
        if args.command == 'hash':
            digest, text = instructions_sha256(protocol)
            if args.show_prompt:
                sys.stdout.write(text)
                if not text.endswith('\n'):
                    sys.stdout.write('\n')
            sys.stdout.write('instructions_sha256 %s\nprompt_bytes %d\n'
                             % (digest, len(text.encode())))
            return 0

        scenario = check_scenario(build_scenario(args.id, protocol, args.expected_map_id,
                                                total_seconds=args.total_seconds))
        text = json.dumps(scenario, indent=2, sort_keys=True) + '\n'
        if args.output:
            _write_new(args.output, text)
            sys.stdout.write('wrote %s\n' % args.output)
        else:
            sys.stdout.write(text)
        return 0
    except (ScenarioError, AdaptiveError) as error:
        sys.stderr.write('invalid: %s\n' % error)
        return 1
    except FileExistsError:
        sys.stderr.write('refusing to overwrite an existing frozen artifact\n')
        return 2
    except (OSError, json.JSONDecodeError) as error:
        sys.stderr.write('unreadable: %s\n' % error)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
