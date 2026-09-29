"""Dollar admission ledger tests; no provider request, model, or game is used.

These exercise the durable reservation authority only. A reservation here is an
admission ceiling, not a billed cost and not evidence that a trial ran.
"""
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import full_client_skill_budget as budget
from full_client_skill_budget import BudgetError

MANIFEST = 'a' * 64
RECONCILIATION = 'b' * 64


def private(root, name='budget.sqlite'):
    # The ledger refuses symlinked ancestors, so resolve the temporary root
    # (on macOS /var/folders is itself a symlink into /private).
    directory = Path(root).resolve(strict=True) / 'private'
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory / name


def policy(authorized=50_000_000, prior=0):
    return budget.policy(authorized_microdollars=authorized,
                         prior_reserved_microdollars=prior,
                         reconciliation_sha256=RECONCILIATION)


def ledger(root, **kwargs):
    return budget.Budget(private(root), policy(**kwargs))


class RequestCeiling(unittest.TestCase):
    def test_published_rates_are_microdollar_tenths(self):
        # $10/M input at the conservative 1.25x cache-write rate is 12.5
        # microdollars per token; output carries no cache-write multiplier.
        self.assertEqual(budget.RATES_TENTHS['gpt-6-astra'], (125, 500))
        self.assertEqual(budget.RATES_TENTHS['gpt-5.6-sol'], (50, 200))
        self.assertEqual(budget.RATES_TENTHS['gpt-5.6-terra'], (25, 120))

    def test_luna_input_rate_rounds_up_and_never_down(self):
        # 0.20/M at 1.25x is 0.25 microdollars; the pinned rate rounds upward.
        self.assertEqual(budget.RATES_TENTHS['gpt-5.6-luna'][0], 3)
        self.assertGreater(budget.RATES_TENTHS['gpt-5.6-luna'][0], 2.5)

    def test_ceiling_is_exact_for_pinned_rates(self):
        self.assertEqual(budget.request_ceiling('gpt-6-astra', 21000, 3000), 412_500)
        self.assertEqual(budget.request_ceiling('gpt-5.6-terra', 21000, 3000), 88_500)

    def test_partial_tenths_round_up_at_the_request_boundary(self):
        # 1 Luna input token is 0.3 microdollars and must not floor to zero.
        self.assertEqual(budget.request_ceiling('gpt-5.6-luna', 1, 1), 2)

    def test_unknown_model_and_out_of_range_bounds_are_refused(self):
        for model, inputs, outputs in (('gpt-9', 10, 10), ('gpt-6-astra', 0, 10),
                                       ('gpt-6-astra', 10, 0), ('gpt-6-astra', 240001, 10),
                                       ('gpt-6-astra', 10, 3001), ('gpt-6-astra', True, 10)):
            with self.assertRaises(BudgetError):
                budget.request_ceiling(model, inputs, outputs)


class Policy(unittest.TestCase):
    def test_authorization_cannot_exceed_the_standing_cap(self):
        with self.assertRaises(BudgetError):
            budget.policy(authorized_microdollars=budget.MAX_AUTHORIZED_MICRODOLLARS + 1,
                          prior_reserved_microdollars=0, reconciliation_sha256=RECONCILIATION)

    def test_prior_spend_cannot_exceed_authorization(self):
        with self.assertRaises(BudgetError):
            budget.policy(authorized_microdollars=1000, prior_reserved_microdollars=1001,
                          reconciliation_sha256=RECONCILIATION)

    def test_reconciliation_digest_is_required(self):
        with self.assertRaises(BudgetError):
            budget.policy(authorized_microdollars=1000, prior_reserved_microdollars=0,
                          reconciliation_sha256='not-a-digest')

    def test_policy_pins_price_date_and_refuses_reservation_reuse(self):
        value = policy()
        self.assertEqual(value['price_date'], budget.PRICE_DATE)
        self.assertEqual(value['service_tier'], 'default')
        self.assertIs(value['reuse_reservations'], False)


class LedgerFile(unittest.TestCase):
    def test_created_private_and_reopened(self):
        with tempfile.TemporaryDirectory() as root:
            path = private(root)
            ledger(root)
            self.assertEqual(stat.S_IMODE(path.lstat().st_mode), 0o600)
            ledger(root).snapshot()

    def test_group_or_world_readable_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root).resolve(strict=True) / 'private'
            directory.mkdir(mode=0o755)
            with self.assertRaises(BudgetError) as caught:
                budget.Budget(directory / 'budget.sqlite', policy())
            self.assertEqual(str(caught.exception), 'skill_budget_private_directory_required')

    def test_relative_path_is_refused(self):
        with self.assertRaises(BudgetError):
            budget.Budget('budget.sqlite', policy())

    def test_symlinked_ledger_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root).resolve(strict=True) / 'private'
            directory.mkdir(mode=0o700)
            target = directory / 'elsewhere.sqlite'
            target.touch(mode=0o600)
            (directory / 'budget.sqlite').symlink_to(target)
            with self.assertRaises(BudgetError):
                budget.Budget(directory / 'budget.sqlite', policy())

    def test_policy_change_on_an_existing_ledger_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            ledger(root)
            with self.assertRaises(BudgetError) as caught:
                ledger(root, authorized=40_000_000)
            self.assertEqual(str(caught.exception), 'skill_budget_policy_changed')

    def test_reservations_without_a_policy_row_are_refused(self):
        with tempfile.TemporaryDirectory() as root:
            path = private(root)
            ledger(root).reserve_request(
                plan_entry_id='e1', execution_manifest_sha256=MANIFEST, cycle=0,
                model='gpt-5.6-luna', input_token_upper_bound=10, output_token_upper_bound=10)
            with sqlite3.connect(path) as db:
                db.execute('DELETE FROM policy')
                db.commit()
            with self.assertRaises(BudgetError) as caught:
                ledger(root)
            self.assertEqual(str(caught.exception), 'skill_budget_policy_missing')


class Reservations(unittest.TestCase):
    def reserve(self, book, entry='e1', cycle=0, model='gpt-6-astra',
                inputs=21000, outputs=3000):
        return book.reserve_request(
            plan_entry_id=entry, execution_manifest_sha256=MANIFEST, cycle=cycle,
            model=model, input_token_upper_bound=inputs, output_token_upper_bound=outputs)

    def test_reservation_returns_the_pinned_ceiling(self):
        with tempfile.TemporaryDirectory() as root:
            receipt = self.reserve(ledger(root))
            self.assertEqual(receipt['reserved_microdollars'], 412_500)
            self.assertEqual(receipt['pricing_date'], budget.PRICE_DATE)
            self.assertEqual(receipt['service_tier'], 'default')

    def test_replay_of_the_same_entry_and_cycle_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            book = ledger(root)
            first = self.reserve(book)
            with self.assertRaises(BudgetError) as caught:
                self.reserve(book)
            self.assertEqual(str(caught.exception), 'skill_request_reservation_replay_refused')
            # The original charge is retained rather than recycled.
            self.assertEqual(book.snapshot()['reserved_microdollars'],
                             first['reserved_microdollars'])

    def test_replay_is_refused_across_independent_handles(self):
        with tempfile.TemporaryDirectory() as root:
            self.reserve(ledger(root))
            with self.assertRaises(BudgetError):
                self.reserve(ledger(root))

    def test_distinct_cycles_and_entries_each_reserve(self):
        with tempfile.TemporaryDirectory() as root:
            book = ledger(root)
            self.reserve(book, cycle=0)
            self.reserve(book, cycle=1)
            self.reserve(book, entry='e2', cycle=0)
            self.assertEqual(book.snapshot()['reservations'], 3)

    def test_exhaustion_refuses_and_charges_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            book = ledger(root, authorized=500_000)
            self.reserve(book, cycle=0)
            with self.assertRaises(BudgetError) as caught:
                self.reserve(book, cycle=1)
            self.assertEqual(str(caught.exception), 'skill_dollar_budget_exhausted')
            self.assertEqual(book.snapshot()['reservations'], 1)

    def test_prior_spend_reduces_available_authorization(self):
        with tempfile.TemporaryDirectory() as root:
            book = ledger(root, authorized=500_000, prior=200_000)
            self.assertEqual(book.snapshot()['remaining_microdollars'], 300_000)
            with self.assertRaises(BudgetError):
                self.reserve(book)

    def test_snapshot_excludes_prior_spend_from_reserved_total(self):
        with tempfile.TemporaryDirectory() as root:
            book = ledger(root, prior=1_000_000)
            self.reserve(book, model='gpt-5.6-luna', inputs=21000, outputs=3000)
            snapshot = book.snapshot()
            self.assertEqual(snapshot['prior_reserved_microdollars'], 1_000_000)
            self.assertEqual(snapshot['reserved_microdollars'], 9_900)
            self.assertEqual(snapshot['remaining_microdollars'],
                             50_000_000 - 1_000_000 - 9_900)

    def test_malformed_identity_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            book = ledger(root)
            for entry, manifest, cycle in (('E1', MANIFEST, 0), ('e1', 'short', 0),
                                           ('e1', MANIFEST, -1), ('e1', MANIFEST, 12),
                                           ('', MANIFEST, 0)):
                with self.assertRaises(BudgetError):
                    book.reserve_request(
                        plan_entry_id=entry, execution_manifest_sha256=manifest, cycle=cycle,
                        model='gpt-5.6-luna', input_token_upper_bound=10,
                        output_token_upper_bound=10)
            self.assertEqual(book.snapshot()['reservations'], 0)


class ShortTaskEnvelope(unittest.TestCase):
    """The frozen 120-second contract permits four cycles inside 96,000 tokens."""

    def test_full_short_task_trial_ceiling_per_model(self):
        expected = {'gpt-6-astra': 1_650_000, 'gpt-5.6-sol': 660_000,
                    'gpt-5.6-terra': 354_000, 'gpt-5.6-luna': 39_600}
        for model, microdollars in expected.items():
            trial = sum(budget.request_ceiling(model, 21000, 3000) for _ in range(4))
            self.assertEqual(trial, microdollars)

    def test_development_pilot_worst_case_exceeds_the_standing_cap(self):
        # 96 planned entries are 24 per model. At the full token ceiling the
        # conservative reservation total does not fit in the $50 authorization.
        total = sum(sum(budget.request_ceiling(model, 21000, 3000) for _ in range(4)) * 24
                    for model in ('gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna'))
        self.assertEqual(total, 64_886_400)
        self.assertGreater(total, budget.MAX_AUTHORIZED_MICRODOLLARS)


if __name__ == '__main__':
    unittest.main()
