"""Offline tests for the frozen adaptive scenario builder.

Synthetic and pure: no services, no provider calls, no private baselines.
Passing these does not authorize a trial.
"""
import ast
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, 'scripts')
SCRIPT = os.path.join(SCRIPTS, 'full_client_scenario_freeze.py')
sys.path.insert(0, SCRIPTS)

import full_client_scenario_freeze as freeze  # noqa: E402
import model_providers as providers  # noqa: E402
from full_client_adaptive import DEFAULT_PROTOCOL, PROTOCOL  # noqa: E402


def runtime_settlement_policy():
    """Read the runtime's literal without importing its root/Linux host checks."""
    with open(os.path.join(SCRIPTS, 'full_client_runtime.py'), encoding='utf-8') as handle:
        source = handle.read()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == 'SETTLEMENT_POLICY'):
            return ast.literal_eval(node.value)
    raise AssertionError('SETTLEMENT_POLICY not found in full_client_runtime.py')


class ScenarioFreezeTest(unittest.TestCase):
    def profile(self, **overrides):
        values = {'profile_id': 'hero-150', 'class_name': 'Hero', 'level': 150,
                  'skill_keys': {'PRIMARY_SKILL': 'Brandish', 'SECONDARY_SKILL': 'Combo Attack',
                                 'BUFF_1': 'Booster', 'BUFF_2': 'Rage'}}
        values.update(overrides)
        return freeze.build_profile(values['profile_id'], values['class_name'],
                                    values['level'], values['skill_keys'])

    def scenario(self, **overrides):
        protocol = freeze.build_protocol(self.profile())
        return freeze.build_scenario(overrides.pop('scenario_id', 'hero-cave-v1-pilot'),
                                     protocol, overrides.pop('expected_map_id', 240050300),
                                     **overrides)

    def test_default_profile_is_the_accepted_hero_180_cohort_profile(self):
        """v1 reuses the profile the accepted five-minute runs actually used."""
        self.assertEqual(DEFAULT_PROTOCOL['profile'],
                         {'id': 'hero-180', 'class_name': 'Hero', 'level': 180,
                          'skill_keys': {'PRIMARY_SKILL': 'Brandish',
                                         'SECONDARY_SKILL': 'Combo Attack',
                                         'BUFF_1': 'Booster', 'BUFF_2': 'Maple Warrior'}})

    def test_encoded_recipe_reproduces_the_accepted_cohort_policies(self):
        protocol = freeze.build_protocol(DEFAULT_PROTOCOL['profile'], recipe='encoded')
        self.assertEqual(protocol['max_total_tokens'], 240000)
        self.assertEqual(protocol['horizon_policy']['id'], 'full-horizon-reserve-v1')
        self.assertEqual(protocol['capture_duration_policy']['id'], 'post-render-encoded-frame-v1')

    def test_bare_recipe_carries_no_optional_policies(self):
        protocol = freeze.build_protocol(DEFAULT_PROTOCOL['profile'], recipe='bare')
        self.assertNotIn('horizon_policy', protocol)
        self.assertNotIn('capture_duration_policy', protocol)
        self.assertEqual(protocol['max_total_tokens'], 120000)

    def test_unknown_recipe_is_refused(self):
        with self.assertRaises(freeze.ScenarioError) as caught:
            freeze.build_protocol(DEFAULT_PROTOCOL['profile'], recipe='future')
        self.assertEqual(str(caught.exception), 'invalid_cohort_recipe')

    def test_settlement_policy_matches_the_runtime(self):
        """The duplicated constant must not drift from full_client_runtime."""
        self.assertEqual(freeze.SETTLEMENT_POLICY, runtime_settlement_policy())

    def test_built_scenario_passes_its_own_check(self):
        scenario = self.scenario()
        self.assertIs(freeze.check_scenario(scenario), scenario)
        self.assertEqual(scenario['protocol'], PROTOCOL)
        self.assertEqual(scenario['program_seconds'], 300)
        self.assertEqual(scenario['reasoning'], {'effort': providers.REASONING_EFFORT})
        self.assertIn(providers.REASONING_EFFORT, providers.EFFORT_VALUES)

    def test_reasoning_effort_is_symmetric_across_providers(self):
        """A cohort must not compare a high-effort OpenAI run against a low-effort Claude one."""
        scenario = self.scenario()
        declared = scenario['reasoning']['effort']
        seen = {}
        for model in ('gpt-6-astra', 'claude-opus-5'):
            _, body = providers.program_request(model, 'instructions', '{}', 1000)
            effort = (body.get('reasoning') or {}).get('effort') or body['output_config']['effort']
            seen[model] = effort
        self.assertEqual(set(seen.values()), {declared}, seen)

    def test_bridge_budgets_use_the_adaptive_run_reserve_not_the_legacy_rule(self):
        budgets = self.scenario()['budgets']
        self.assertEqual(budgets, {'api_requests': 12, 'output_tokens': 36000,
                                   'total_tokens': 240000, 'program_ms': 300000,
                                   'run_ms': 335000, 'actions': 1600, 'sdk_requests': 6000})
        # (300 + 35) * 1000, never the one-shot (program_seconds + 63) * 1000.
        self.assertNotEqual(budgets['run_ms'], (300 + 63) * 1000)

    def test_trial_budgets_mirror_the_protocol_and_reserve_settlement(self):
        trial = self.scenario()['trial_budgets']
        self.assertEqual(trial['controller_seconds'], 300)
        self.assertEqual(trial['operation_seconds'], 360)
        self.assertEqual(trial['total_seconds'], 1200)
        self.assertEqual(trial['max_output_tokens'], 36000)
        self.assertEqual(trial['max_api_requests'], 12)
        self.assertEqual(trial['max_total_tokens'], 240000)

    def test_total_seconds_below_the_operation_envelope_is_refused(self):
        with self.assertRaises(freeze.ScenarioError):
            self.scenario(total_seconds=359)
        self.assertEqual(self.scenario(total_seconds=360)['trial_budgets']['total_seconds'], 360)

    def test_readiness_policy_is_frozen_and_map_bound(self):
        policy = self.scenario(expected_map_id=240050300)['readiness_policy']
        self.assertEqual(policy, {'schema_version': 1, 'expected_map_id': 240050300,
                                  'min_monsters': 1, 'min_samples': 3,
                                  'min_span_ms': 1000, 'timeout_ms': 10000})
        with self.assertRaises(freeze.ScenarioError):
            self.scenario(expected_map_id=-1)
        with self.assertRaises(freeze.ScenarioError):
            self.scenario(expected_map_id=True)

    def test_defaults_are_never_mutated(self):
        before = copy.deepcopy(DEFAULT_PROTOCOL)
        self.scenario()
        self.assertEqual(DEFAULT_PROTOCOL, before)
        self.assertEqual(DEFAULT_PROTOCOL['profile']['level'], 180)

    def test_profile_changes_change_the_frozen_prompt_hash(self):
        """The prompt embeds the profile, so a different build is a different freeze."""
        hero150 = freeze.build_protocol(self.profile())
        hero180 = freeze.build_protocol(self.profile(profile_id='hero-180', level=180))
        self.assertNotEqual(freeze.instructions_sha256(hero150)[0],
                            freeze.instructions_sha256(hero180)[0])

    def test_knowledge_equipped_freeze_binds_pack_timeline_and_fixture(self):
        reference = freeze.knowledge_reference()
        protocol = freeze.build_protocol(DEFAULT_PROTOCOL['profile'],
                                         knowledge_pack=reference)
        self.assertEqual(protocol['knowledge_pack'], reference)
        self.assertEqual(len(protocol['skill_toolkit']['skills']), 17)
        self.assertEqual(protocol['profile']['id'], 'hero-180-expanded-v1')
        self.assertEqual(protocol['profile']['skill_keys']['SKILL_10'], 'Power Guard')
        self.assertEqual(protocol['input_timeline_policy'],
                         freeze.INPUT_TIMELINE_POLICY)
        self.assertEqual(protocol['max_total_tokens'], 500000)
        scenario = freeze.build_scenario(freeze.KNOWLEDGE_SCENARIO_ID, protocol, 240040511)
        self.assertIs(freeze.check_scenario(scenario), scenario)
        with self.assertRaises(freeze.ScenarioError) as caught:
            freeze.build_scenario('wrong-map', protocol, 240050300)
        self.assertEqual(str(caught.exception), 'knowledge_pack_fixture_mismatch')

    def test_500k_token_budget_requires_exact_knowledge_toolkit_axis(self):
        protocol = freeze.build_protocol(DEFAULT_PROTOCOL['profile'])
        protocol['max_total_tokens'] = 500000
        with self.assertRaisesRegex(Exception, 'invalid_adaptive_limits'):
            freeze.validate_protocol(protocol)

    def test_legacy_protocol_and_prompt_remain_knowledge_free(self):
        protocol = freeze.build_protocol(DEFAULT_PROTOCOL['profile'])
        self.assertNotIn('knowledge_pack', protocol)
        self.assertNotIn('input_timeline_policy', protocol)
        self.assertNotIn('Frozen optional knowledge axis', freeze.prompt(protocol))

    def test_invalid_profiles_are_refused(self):
        for bad in ({'profile_id': 'Hero_150'}, {'class_name': ''}, {'level': 0},
                    {'level': 256}, {'skill_keys': {'NOT_A_KEY': 'Brandish'}}):
            with self.assertRaises(freeze.ScenarioError):
                self.profile(**bad)

    def test_scenario_id_must_be_a_trimmed_bounded_string(self):
        protocol = freeze.build_protocol(self.profile())
        for bad in ('', ' leading', 'trailing ', 'x' * 129):
            with self.assertRaises(freeze.ScenarioError):
                freeze.build_scenario(bad, protocol, 240050300)

    def test_check_rejects_every_tampered_computed_field(self):
        mutations = [
            ('instructions_sha256', '1' * 64, 'frozen_prompt_mismatch'),
            ('program_seconds', 22, 'invalid_program_seconds'),
            ('reasoning', {'effort': 'high'}, 'invalid_reasoning'),
            ('protocol', 'full-client-one-shot', 'invalid_frozen_scenario'),
            ('schema_version', 2, 'invalid_frozen_scenario'),
        ]
        for key, value, code in mutations:
            scenario = self.scenario()
            scenario[key] = value
            with self.assertRaises(freeze.ScenarioError) as caught:
                freeze.check_scenario(scenario)
            self.assertEqual(str(caught.exception), code, key)

    def test_check_rejects_edited_budget_blocks(self):
        for key, field, value in (('budgets', 'run_ms', 363000),
                                  ('budgets', 'output_tokens', 3000),
                                  ('trial_budgets', 'controller_seconds', 22),
                                  ('trial_budgets', 'operation_seconds', 300)):
            scenario = self.scenario()
            scenario[key][field] = value
            with self.assertRaises(freeze.ScenarioError):
                freeze.check_scenario(scenario)

    def test_check_rejects_a_weakened_readiness_policy_and_settlement_policy(self):
        scenario = self.scenario()
        scenario['readiness_policy']['min_monsters'] = 0
        with self.assertRaises(freeze.ScenarioError):
            freeze.check_scenario(scenario)

        scenario = self.scenario()
        scenario['settlement_policy']['capture_tail_ms'] = 1
        with self.assertRaises(freeze.ScenarioError) as caught:
            freeze.check_scenario(scenario)
        self.assertEqual(str(caught.exception), 'invalid_settlement_policy')

    def test_check_rejects_extra_and_missing_keys(self):
        scenario = self.scenario()
        scenario['extra'] = 1
        with self.assertRaises(freeze.ScenarioError):
            freeze.check_scenario(scenario)
        scenario = self.scenario()
        del scenario['readiness_policy']
        with self.assertRaises(freeze.ScenarioError):
            freeze.check_scenario(scenario)

    def test_check_rejects_a_relaxed_wall_clock(self):
        scenario = self.scenario()
        scenario['adaptive_protocol']['wall_seconds'] = 1800
        with self.assertRaises(Exception):
            freeze.check_scenario(scenario)

    def test_cli_hash_is_deterministic_and_reports_prompt_size(self):
        first = subprocess.run([sys.executable, SCRIPT, 'hash'], capture_output=True, text=True)
        second = subprocess.run([sys.executable, SCRIPT, 'hash'], capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn('instructions_sha256 ', first.stdout)
        self.assertIn('prompt_bytes ', first.stdout)

    def test_cli_build_writes_once_and_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            out = os.path.join(root, 'scenario.json')
            argv = [sys.executable, SCRIPT, 'build', '--id', 'hero-cave-v1-pilot',
                    '--expected-map-id', '240050300', '--profile-id', 'hero-150',
                    '--class', 'Hero', '--level', '150', '--buff2', 'Rage', '--output', out]
            first = subprocess.run(argv, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            with open(out, encoding='utf-8') as handle:
                scenario = json.load(handle)
            self.assertEqual(scenario['id'], 'hero-cave-v1-pilot')
            self.assertEqual(scenario['readiness_policy']['expected_map_id'], 240050300)

            again = subprocess.run(argv, capture_output=True, text=True)
            self.assertEqual(again.returncode, 2)

            checked = subprocess.run([sys.executable, SCRIPT, 'check', out],
                                     capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(checked.stdout.strip(), 'ok')

    def test_cli_check_reports_invalid_and_unreadable_separately(self):
        with tempfile.TemporaryDirectory() as root:
            bad = os.path.join(root, 'bad.json')
            with open(bad, 'w', encoding='utf-8') as handle:
                json.dump({'schema_version': 1}, handle)
            self.assertEqual(subprocess.run([sys.executable, SCRIPT, 'check', bad],
                                            capture_output=True).returncode, 1)
            self.assertEqual(
                subprocess.run([sys.executable, SCRIPT, 'check', os.path.join(root, 'nope.json')],
                               capture_output=True).returncode, 2)

    def test_accepted_live_scenario_structure_still_validates_when_available(self):
        """Regression against a real accepted freeze, when the operator supplies one.

        Set MAPLEBENCH_FROZEN_SCENARIO to a private accepted scenario path. The file
        is never committed; this guards the builder's budget and structure
        derivations against drifting away from what actually ran.

        The prompt hash is deliberately not compared: a historical freeze was made
        against an earlier prompt version and keeps its own recorded bytes. Only
        the derivations that must stay stable across prompt versions are checked.
        """
        path = os.environ.get('MAPLEBENCH_FROZEN_SCENARIO')
        if not path or not os.path.isfile(path):
            self.skipTest('MAPLEBENCH_FROZEN_SCENARIO not supplied')
        with open(path, encoding='utf-8') as handle:
            accepted = json.load(handle)
        freeze.check_scenario(accepted, verify_prompt=False)

    def test_verify_prompt_false_still_rejects_a_malformed_hash(self):
        scenario = self.scenario()
        scenario['instructions_sha256'] = 'not-a-hash'
        with self.assertRaises(freeze.ScenarioError) as caught:
            freeze.check_scenario(scenario, verify_prompt=False)
        self.assertEqual(str(caught.exception), 'invalid_instructions_sha256')

    def test_verify_prompt_false_accepts_an_earlier_prompt_version(self):
        scenario = self.scenario()
        scenario['instructions_sha256'] = 'a' * 64
        freeze.check_scenario(scenario, verify_prompt=False)
        with self.assertRaises(freeze.ScenarioError) as caught:
            freeze.check_scenario(scenario)
        self.assertEqual(str(caught.exception), 'frozen_prompt_mismatch')


if __name__ == '__main__':
    unittest.main()
