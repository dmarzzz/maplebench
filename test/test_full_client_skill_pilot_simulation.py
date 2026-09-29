"""Projection tests; no world, provider request, or trial outcome is produced."""
import csv
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import full_client_skill_pilot_simulation as projection
from full_client_skill_pilot_simulation import ProjectionError

ROOT = Path(__file__).resolve().parents[1]
SCHEDULE = ROOT / 'docs/plans/skill-suite-v1-schedule.csv'
COLUMNS = ('plan_entry_id', 'phase', 'block', 'task_id', 'variant', 'repetition', 'model',
           'admission_slot', 'worker_lane', 'wall_seconds', 'max_api_requests', 'token_ceiling',
           'execution_status', 'fixture_binding')
RECONCILIATION = '0' * 64


def schedule(rows, path):
    with Path(path).open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for index, (model, task_id) in enumerate(rows):
            writer.writerow({
                'plan_entry_id': f'e{index:03d}-{task_id}-{model}', 'phase': 'skill-development',
                'block': f'b{index // 4:03d}', 'task_id': task_id, 'variant': 1,
                'repetition': index // 4 + 1, 'model': model, 'admission_slot': index % 4 + 1,
                'worker_lane': 'ABC'[index % 3], 'wall_seconds': 120, 'max_api_requests': 4,
                'token_ceiling': 96000, 'execution_status': 'not_authorized',
                'fixture_binding': 'UNBOUND'})
    return path


def rounds(count, task_id='potion-use-v1'):
    models = ('gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna')
    return [(model, task_id) for _ in range(count) for model in models]


def run(rows, authorized, prior=0, **kwargs):
    return projection.project(rows, authorized_microdollars=authorized,
                              prior_reserved_microdollars=prior,
                              reconciliation_sha256=RECONCILIATION, **kwargs)


def loaded(pairs):
    with tempfile.TemporaryDirectory() as root:
        return projection.load_schedule(schedule(pairs, Path(root) / 's.csv'), 'skill-development')


class Envelope(unittest.TestCase):
    def test_short_task_shape_matches_the_frozen_contract(self):
        shape = projection.envelope('potion-use-v1')
        self.assertEqual(shape['cycles'], 4)
        self.assertEqual(shape['output_tokens_per_cycle'], 3000)
        self.assertEqual(shape['input_tokens_per_cycle'], 21000)
        self.assertEqual(shape['token_ceiling'], 96000)
        self.assertEqual(shape['wall_seconds'], 120)

    def test_extended_task_shape_matches_the_frozen_contract(self):
        shape = projection.envelope('buff-upkeep-v1')
        self.assertEqual(shape['cycles'], 12)
        self.assertEqual(shape['input_tokens_per_cycle'], 17000)
        self.assertEqual(shape['wall_seconds'], 300)

    def test_full_envelope_never_exceeds_the_token_ceiling(self):
        for task_id in ('platforming-v1', 'native-teleport-v1', 'potion-use-v1',
                        'buff-upkeep-v1', 'portal-navigation-v1', 'return-to-hunt-v1'):
            shape = projection.envelope(task_id)
            reserved = shape['cycles'] * (shape['input_tokens_per_cycle']
                                          + shape['output_tokens_per_cycle'])
            self.assertLessEqual(reserved, shape['token_ceiling'])

    def test_unknown_task_is_refused(self):
        with self.assertRaises(Exception):
            projection.envelope('not-a-task')


class TrialCeiling(unittest.TestCase):
    def test_short_task_ceiling_per_model(self):
        expected = {'gpt-6-astra': 1_650_000, 'gpt-5.6-sol': 660_000,
                    'gpt-5.6-terra': 354_000, 'gpt-5.6-luna': 39_600}
        for model, microdollars in expected.items():
            self.assertEqual(projection.trial_ceiling(model, 'potion-use-v1'), microdollars)

    def test_smaller_envelope_reserves_strictly_less(self):
        full = projection.trial_ceiling('gpt-6-astra', 'potion-use-v1')
        small = projection.trial_ceiling('gpt-6-astra', 'potion-use-v1',
                                         input_tokens_per_cycle=1000)
        self.assertLess(small, full)

    def test_envelope_above_the_contract_ceiling_is_refused(self):
        with self.assertRaises(ProjectionError):
            projection.trial_ceiling('gpt-6-astra', 'potion-use-v1',
                                     input_tokens_per_cycle=21001)


class LoadSchedule(unittest.TestCase):
    def test_file_order_is_preserved_and_indexed(self):
        rows = loaded(rounds(2))
        self.assertEqual([row['dispatch_index'] for row in rows], list(range(8)))
        self.assertEqual(rows[0]['model'], 'gpt-6-astra')
        self.assertEqual(rows[1]['model'], 'gpt-5.6-sol')

    def test_rotation_slots_repeat_without_being_treated_as_a_rank(self):
        rows = loaded(rounds(2))
        self.assertEqual([int(row['admission_slot']) for row in rows],
                         [1, 2, 3, 4, 1, 2, 3, 4])

    def test_duplicate_plan_entry_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            path = schedule(rounds(1), Path(root) / 's.csv')
            body = path.read_text().splitlines()
            path.write_text('\n'.join(body + [body[1]]) + '\n')
            with self.assertRaises(ProjectionError) as caught:
                projection.load_schedule(path, 'skill-development')
            self.assertEqual(str(caught.exception), 'skill_projection_duplicate_plan_entry')

    def test_absent_phase_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            path = schedule(rounds(1), Path(root) / 's.csv')
            with self.assertRaises(ProjectionError) as caught:
                projection.load_schedule(path, 'skill-comparative')
            self.assertEqual(str(caught.exception), 'skill_projection_phase_not_in_schedule')


class Project(unittest.TestCase):
    def test_reports_itself_as_a_dry_run_with_no_outcomes(self):
        report = run(loaded(rounds(1)), 50_000_000)
        self.assertIs(report['is_dry_run'], True)
        self.assertEqual(report['dispatched_requests'], 0)
        self.assertIsNone(report['trial_outcomes'])

    def test_sufficient_authorization_admits_every_entry(self):
        report = run(loaded(rounds(1)), 50_000_000)
        self.assertEqual(report['admitted_entries'], 4)
        self.assertEqual(report['uncovered_entries'], 0)
        self.assertIs(report['fits_within_authorization'], True)
        self.assertEqual(report['reserved_microdollars'], 2_703_600)

    def test_exhaustion_leaves_entries_uncovered_rather_than_dropped(self):
        report = run(loaded(rounds(2)), 3_000_000)
        self.assertEqual(report['coverage_denominator'], 8)
        self.assertEqual(report['admitted_entries'] + report['uncovered_entries'], 8)
        self.assertGreater(report['uncovered_entries'], 0)
        self.assertIs(report['fits_within_authorization'], False)

    def test_uncovered_entry_records_its_stranded_reservation(self):
        # Astra needs four cycles; a cap that funds only some of them strands
        # the reserved ones, because reservations are never recycled.
        report = run(loaded([('gpt-6-astra', 'potion-use-v1')]), 1_000_000)
        self.assertEqual(report['uncovered_entries'], 1)
        stranded = report['uncovered'][0]['stranded_microdollars']
        self.assertEqual(stranded, 825_000)
        self.assertEqual(report['reserved_microdollars'], stranded)

    def test_first_uncovered_entry_is_identified_by_dispatch_index(self):
        report = run(loaded(rounds(2)), 3_000_000)
        first = report['uncovered'][0]
        self.assertEqual(report['first_uncovered_dispatch_index'], first['dispatch_index'])
        self.assertEqual(report['first_uncovered_plan_entry_id'], first['plan_entry_id'])

    def test_prior_spend_reduces_coverage(self):
        rows = loaded(rounds(1))
        self.assertEqual(run(rows, 50_000_000)['uncovered_entries'], 0)
        self.assertGreater(run(rows, 50_000_000, prior=49_000_000)['uncovered_entries'], 0)

    def test_every_planned_model_appears_even_with_zero_coverage(self):
        report = run(loaded(rounds(1)), 100_000)
        self.assertEqual(sorted(report['by_model']),
                         ['gpt-5.6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-6-astra'])
        for counts in report['by_model'].values():
            self.assertEqual(counts['planned'], 1)

    def test_projection_is_deterministic(self):
        rows = loaded(rounds(2))
        self.assertEqual(run(rows, 5_000_000), run(rows, 5_000_000))

    def test_smaller_envelope_admits_at_least_as_many_entries(self):
        rows = loaded(rounds(2))
        full = run(rows, 5_000_000)
        small = run(rows, 5_000_000, input_tokens_per_cycle=1000)
        self.assertGreaterEqual(small['admitted_entries'], full['admitted_entries'])


class BalancedCapacity(unittest.TestCase):
    def capacity(self, rows, authorized, **kwargs):
        return projection.balanced_capacity(rows, authorized_microdollars=authorized,
                                            prior_reserved_microdollars=0, **kwargs)

    def test_one_round_costs_the_sum_of_every_model_cell(self):
        balance = self.capacity(loaded(rounds(1)), 50_000_000)
        self.assertEqual(balance['cells_per_round'], 4)
        self.assertEqual(balance['round_microdollars'], 2_703_600)
        self.assertEqual(balance['planned_rounds'], 1)

    def test_admitted_rounds_never_exceed_planned_rounds(self):
        balance = self.capacity(loaded(rounds(2)), 50_000_000)
        self.assertEqual(balance['planned_rounds'], 2)
        self.assertEqual(balance['admitted_rounds'], 2)
        self.assertIs(balance['balanced'], True)

    def test_insufficient_authorization_drops_whole_rounds(self):
        # $10 funds three full rounds of the four models at $2.7036 each.
        balance = self.capacity(loaded(rounds(8)), 10_000_000)
        self.assertEqual(balance['admitted_rounds'], 3)
        self.assertEqual(balance['planned_rounds'], 8)
        self.assertEqual(balance['admitted_entries'], 12)
        self.assertIs(balance['balanced'], False)

    def test_capacity_beyond_the_plan_is_capped_at_planned_rounds(self):
        balance = self.capacity(loaded(rounds(8)), 50_000_000)
        self.assertEqual(balance['admitted_rounds'], 8)
        self.assertIs(balance['balanced'], True)

    def test_unbalanced_phase_is_refused(self):
        rows = loaded([('gpt-6-astra', 'potion-use-v1'), ('gpt-6-astra', 'potion-use-v1'),
                       ('gpt-5.6-luna', 'potion-use-v1')])
        with self.assertRaises(ProjectionError) as caught:
            self.capacity(rows, 50_000_000)
        self.assertEqual(str(caught.exception), 'skill_projection_phase_not_model_balanced')


class LargestFittingEnvelope(unittest.TestCase):
    def solve(self, rows, authorized):
        return projection.largest_fitting_envelope(
            rows, authorized_microdollars=authorized, prior_reserved_microdollars=0,
            reconciliation_sha256=RECONCILIATION)

    def test_generous_authorization_solves_to_the_contract_ceiling(self):
        self.assertEqual(self.solve(loaded(rounds(1)), 50_000_000), 21000)

    def test_solved_envelope_admits_every_entry_and_one_more_token_does_not(self):
        rows = loaded(rounds(4))
        solved = self.solve(rows, 6_000_000)
        self.assertIsNotNone(solved)
        self.assertLess(solved, 21000)
        self.assertEqual(run(rows, 6_000_000, input_tokens_per_cycle=solved)['uncovered_entries'], 0)
        self.assertGreater(
            run(rows, 6_000_000, input_tokens_per_cycle=solved + 1)['uncovered_entries'], 0)

    def test_structurally_unaffordable_phase_solves_to_none(self):
        self.assertIsNone(self.solve(loaded(rounds(1)), 1_000))


class FrozenDevelopmentPhase(unittest.TestCase):
    """The shipped 96-entry pilot against the standing $50 authorization."""

    @classmethod
    def setUpClass(cls):
        cls.rows = projection.load_schedule(SCHEDULE, 'skill-development')

    def test_phase_is_96_entries_balanced_across_four_models(self):
        self.assertEqual(len(self.rows), 96)
        counts = {model: sum(1 for row in self.rows if row['model'] == model)
                  for model in set(row['model'] for row in self.rows)}
        self.assertEqual(set(counts.values()), {24})

    def test_worst_case_pilot_does_not_fit_the_standing_authorization(self):
        report = run(self.rows, 50_000_000)
        self.assertIs(report['fits_within_authorization'], False)
        self.assertEqual(report['admitted_entries'], 76)
        self.assertEqual(report['uncovered_entries'], 20)

    def test_greedy_admission_leaves_model_coverage_unbalanced(self):
        # The declared analysis pairs models within a variant, so this walk
        # cannot be used as a reduced cohort even though it spends the cap.
        report = run(self.rows, 50_000_000)
        admitted = {model: counts['admitted'] for model, counts in report['by_model'].items()}
        self.assertGreater(len(set(admitted.values())), 1)

    def test_balanced_reduction_fits_at_72_entries(self):
        balance = projection.balanced_capacity(
            self.rows, authorized_microdollars=50_000_000, prior_reserved_microdollars=0)
        self.assertEqual(balance['admitted_rounds'], 6)
        self.assertEqual(balance['planned_rounds'], 8)
        self.assertEqual(balance['admitted_entries'], 72)
        self.assertLessEqual(balance['reserved_microdollars'], 50_000_000)


if __name__ == '__main__':
    unittest.main()
