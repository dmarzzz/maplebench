"""Finite XP-window admission tests; no native runtime or provider calls."""
import copy
import json
from pathlib import Path
import unittest

import test_full_client_experiment as fixtures
import full_client_adaptive as adaptive
import full_client_adaptive_evidence as adaptive_evidence
import full_client_xp_windows as xp
import maple_agent
experiment = fixtures.experiment


class WindowExperimentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExperimentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def configuration(self):
        config = self.fixture.config(models=list(experiment.MODELS))
        fixture = config['fixtures'][0]
        fixture['protocol'] = xp.PROTOCOL
        fixture['budgets'].update(total_seconds=1200, operation_seconds=360,
            controller_seconds=300, max_actions=1600, max_api_requests=12,
            max_output_tokens=36000, max_total_tokens=120000)
        config['aggregate_limits'] = {'api_requests':48,'total_tokens':480000,'wall_seconds':4820}
        scenario = json.loads(Path(fixture['scenario']['path']).read_text())
        protocol = copy.deepcopy(adaptive.DEFAULT_PROTOCOL)
        protocol['horizon_policy'] = copy.deepcopy(adaptive.FULL_HORIZON_POLICY)
        scenario.update(protocol=adaptive.PROTOCOL, adaptive_protocol=protocol,
            trial_budgets=fixture['budgets'], xp_window_protocol={
                'id':xp.PROTOCOL,'wall_seconds':300,'window_ms':15000,
                'experience_table_sha256':'e'*64,
                'normalization':{k:{'numerator':1,'denominator':1} for k in
                    ('server_xp_multiplier','simulation_speed_multiplier')}})
        fixture['scenario'] = self.fixture.write('fixture0-scenario.json',scenario)
        backend = json.loads((self.fixture.root/'fixture0-backend.json').read_text())
        backend.update(scenario=fixture['scenario'],xp_window_protocol=xp.PROTOCOL)
        self.fixture.write('fixture0-backend.json',backend)
        config['runner']['dependencies'] += [experiment.pin(Path(m.__file__).resolve())
            for m in (adaptive,adaptive_evidence,xp,maple_agent)]
        return config

    def test_four_explicit_window_requests_have_separate_scoring_identity(self):
        config = self.configuration()
        plan = experiment.build_plan(config)
        self.assertEqual(len(plan['entries']),4)
        for row in plan['entries']:
            self.assertEqual(row['spec']['schema_version'],3)
            self.assertEqual(row['spec']['protocol'],xp.PROTOCOL)
        experiment.verify_inputs(plan)

    def test_no_implicit_upgrade_or_legacy_fallback(self):
        for mode in ('absent','legacy'):
            with self.subTest(mode=mode):
                config = self.configuration()
                if mode=='absent':del config['fixtures'][0]['protocol']
                else:config['fixtures'][0]['protocol']=adaptive.PROTOCOL
                with self.assertRaisesRegex(experiment.ExperimentError,'invalid_trial_protocol'):
                    experiment.build_plan(config)

    def test_explicit_final_slot_policy_is_admitted_with_native_window_score(self):
        config = self.configuration(); fixture = config['fixtures'][0]
        scenario = json.loads(Path(fixture['scenario']['path']).read_text())
        scenario['adaptive_protocol']['horizon_policy'] = copy.deepcopy(adaptive.FINAL_SLOT_POLICY)
        fixture['scenario'] = self.fixture.write('fixture0-scenario.json', scenario)
        backend = json.loads((self.fixture.root / 'fixture0-backend.json').read_text())
        backend['scenario'] = fixture['scenario']; self.fixture.write('fixture0-backend.json', backend)
        plan = experiment.build_plan(config); experiment.verify_inputs(plan)
        self.assertTrue(all(e['spec']['schema_version'] == 3 for e in plan['entries']))
        scenario['adaptive_protocol']['horizon_policy']['final_program_max_seconds'] += 1
        fixture['scenario'] = self.fixture.write('fixture0-scenario.json', scenario)
        with self.assertRaisesRegex(experiment.ExperimentError, 'invalid_trial_protocol'):
            experiment.build_plan(config)

    def test_backend_scoring_opt_in_must_match(self):
        config = self.configuration()
        path = self.fixture.root/'fixture0-backend.json'
        backend = json.loads(path.read_text());del backend['xp_window_protocol']
        self.fixture.write(path.name,backend)
        with self.assertRaisesRegex(experiment.ExperimentError,'backend_fixture_mismatch'):
            experiment.build_plan(config)

    def test_full_horizon_and_pinned_scorer_required(self):
        config = self.configuration()
        config['runner']['dependencies'] = [ref for ref in config['runner']['dependencies']
            if Path(ref['path']).name!='full_client_xp_windows.py']
        with self.assertRaisesRegex(experiment.ExperimentError,'runner_dependencies_missing'):
            experiment.build_plan(config)
        config = self.configuration()
        fixture = config['fixtures'][0]
        scenario = json.loads(Path(fixture['scenario']['path']).read_text())
        del scenario['adaptive_protocol']['horizon_policy']
        fixture['scenario'] = self.fixture.write('fixture0-scenario.json',scenario)
        with self.assertRaisesRegex(experiment.ExperimentError,'invalid_trial_protocol'):
            experiment.build_plan(config)


if __name__=='__main__':unittest.main()
