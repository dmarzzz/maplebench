"""Dollar-admission feasibility projection for the frozen skill-suite schedule.

This is a dry run. It starts no world, dispatches no provider request, and
produces no trial outcome. It walks the preserved admission order of a frozen
schedule and asks the real admission authority in
`full_client_skill_budget` how far the standing authorization actually reaches.

A projection is an upper-bound reservation study, not a billed cost, not a
forecast of realised spend, and never evidence that an entry ran. Entries that
this projection cannot admit are reported as uncovered, never dropped.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import tempfile

from full_client_skill_budget import (
    Budget, BudgetError, MAX_AUTHORIZED_MICRODOLLARS, PRICE_DATE, policy, request_ceiling)
from full_client_skill_controller import SHORT_TASKS, EXTENDED_TASKS, protocol

PROJECTION = 'skill-suite-dollar-projection-v1'


class ProjectionError(ValueError):
    pass


def require(value, reason):
    if not value:
        raise ProjectionError(reason)


def envelope(task_id):
    """The worst-case cycle structure permitted by a task's frozen contract.

    Every cycle reserves the maximum output allowance, so the token ceiling
    bounds the input the remaining cycles may reserve. This is the largest
    envelope the controller can admit, not the envelope a trial will use.
    """
    limits = protocol(task_id)
    cycles = limits['max_api_requests']
    output = limits['max_output_tokens']
    inputs = limits['max_total_tokens'] - cycles * output
    require(inputs >= cycles, 'skill_projection_token_ceiling_too_small')
    return {'cycles': cycles, 'output_tokens_per_cycle': output,
            'input_tokens_per_cycle': inputs // cycles,
            'token_ceiling': limits['max_total_tokens'],
            'wall_seconds': limits['wall_seconds']}


def trial_ceiling(model, task_id, *, input_tokens_per_cycle=None):
    """Maximum microdollars one trial of this task can reserve for this model."""
    shape = envelope(task_id)
    inputs = shape['input_tokens_per_cycle'] if input_tokens_per_cycle is None else input_tokens_per_cycle
    require(type(inputs) is int and 1 <= inputs <= shape['input_tokens_per_cycle'],
            'skill_projection_envelope_out_of_range')
    return sum(request_ceiling(model, inputs, shape['output_tokens_per_cycle'])
               for _ in range(shape['cycles']))


def load_schedule(path, phase):
    """Rows of one phase in the schedule's own preserved order.

    File order is the frozen dispatch order. `admission_slot` is the rotation
    position within a block across worker lanes, not a global rank, so it is
    retained for reporting but never used to re-sort the phase.
    """
    with Path(path).open(newline='') as handle:
        rows = [row for row in csv.DictReader(handle) if row['phase'] == phase]
    require(rows, 'skill_projection_phase_not_in_schedule')
    for index, row in enumerate(rows):
        require(row['task_id'] in SHORT_TASKS | EXTENDED_TASKS, 'skill_projection_unknown_task')
        require(row['admission_slot'].isdigit(), 'skill_projection_admission_slot_invalid')
        row['dispatch_index'] = index
    require(len(set(row['plan_entry_id'] for row in rows)) == len(rows),
            'skill_projection_duplicate_plan_entry')
    return rows


def project(rows, *, authorized_microdollars, prior_reserved_microdollars,
            reconciliation_sha256, input_tokens_per_cycle=None, ledger_directory=None):
    """Walk the preserved order, reserving each entry's worst case until exhausted.

    The walk uses the real durable authority so that replay refusal, policy
    pinning and the exhaustion boundary are the shipped ones, not restated here.
    """
    settings = policy(authorized_microdollars=authorized_microdollars,
                      prior_reserved_microdollars=prior_reserved_microdollars,
                      reconciliation_sha256=reconciliation_sha256)
    manifest = 'f' * 64
    admitted, uncovered, by_model = [], [], {}

    with tempfile.TemporaryDirectory(dir=ledger_directory) as scratch:
        directory = Path(scratch).resolve(strict=True) / 'projection'
        directory.mkdir(mode=0o700)
        book = Budget(directory / 'projection.sqlite', settings)
        shapes = {}
        for row in rows:
            task_id, model = row['task_id'], row['model']
            shape = shapes.setdefault(task_id, envelope(task_id))
            inputs = (shape['input_tokens_per_cycle'] if input_tokens_per_cycle is None
                      else min(input_tokens_per_cycle, shape['input_tokens_per_cycle']))
            before = book.snapshot()['reserved_microdollars']
            try:
                for cycle in range(shape['cycles']):
                    book.reserve_request(
                        plan_entry_id=row['plan_entry_id'], execution_manifest_sha256=manifest,
                        cycle=cycle, model=model, input_token_upper_bound=inputs,
                        output_token_upper_bound=shape['output_tokens_per_cycle'])
            except BudgetError as failure:
                require(str(failure) == 'skill_dollar_budget_exhausted', str(failure))
                # A partly reserved entry is not admissible; its cycles stay
                # charged because reservations are never recycled.
                uncovered.append({'plan_entry_id': row['plan_entry_id'], 'model': model,
                                  'task_id': task_id, 'dispatch_index': row['dispatch_index'],
                                  'admission_slot': int(row['admission_slot']),
                                  'reason': 'skill_dollar_budget_exhausted',
                                  'stranded_microdollars':
                                      book.snapshot()['reserved_microdollars'] - before})
                continue
            spent = book.snapshot()['reserved_microdollars'] - before
            admitted.append({'plan_entry_id': row['plan_entry_id'], 'model': model,
                             'task_id': task_id, 'dispatch_index': row['dispatch_index'],
                             'admission_slot': int(row['admission_slot']),
                             'reserved_microdollars': spent})
            counts = by_model.setdefault(model, {'admitted': 0, 'reserved_microdollars': 0})
            counts['admitted'] += 1
            counts['reserved_microdollars'] += spent
        final = book.snapshot()

    for model in sorted(set(row['model'] for row in rows)):
        by_model.setdefault(model, {'admitted': 0, 'reserved_microdollars': 0})
        by_model[model]['planned'] = sum(1 for row in rows if row['model'] == model)

    return {'schema_version': 1, 'projection': PROJECTION, 'price_date': PRICE_DATE,
            'is_dry_run': True, 'dispatched_requests': 0, 'trial_outcomes': None,
            'authorized_microdollars': authorized_microdollars,
            'prior_reserved_microdollars': prior_reserved_microdollars,
            'input_tokens_per_cycle': input_tokens_per_cycle,
            'planned_entries': len(rows), 'admitted_entries': len(admitted),
            'uncovered_entries': len(uncovered),
            'coverage_numerator': len(admitted), 'coverage_denominator': len(rows),
            'fits_within_authorization': not uncovered,
            'reserved_microdollars': final['reserved_microdollars'],
            'remaining_microdollars': final['remaining_microdollars'],
            'first_uncovered_dispatch_index': uncovered[0]['dispatch_index'] if uncovered else None,
            'first_uncovered_plan_entry_id': uncovered[0]['plan_entry_id'] if uncovered else None,
            'by_model': by_model, 'admitted': admitted, 'uncovered': uncovered}


def largest_fitting_envelope(rows, *, authorized_microdollars, prior_reserved_microdollars,
                             reconciliation_sha256, ledger_directory=None):
    """Largest per-cycle input bound at which every planned entry still fits.

    Returns None when even a one-token input envelope cannot cover the phase;
    the shortfall is then structural rather than a matter of prompt size.
    """
    ceiling = min(envelope(row['task_id'])['input_tokens_per_cycle'] for row in rows)
    common = dict(authorized_microdollars=authorized_microdollars,
                  prior_reserved_microdollars=prior_reserved_microdollars,
                  reconciliation_sha256=reconciliation_sha256,
                  ledger_directory=ledger_directory)
    if project(rows, input_tokens_per_cycle=1, **common)['uncovered_entries']:
        return None
    low, high = 1, ceiling
    while low < high:
        middle = (low + high + 1) // 2
        if project(rows, input_tokens_per_cycle=middle, **common)['uncovered_entries']:
            high = middle - 1
        else:
            low = middle
    return low


def balanced_capacity(rows, *, authorized_microdollars, prior_reserved_microdollars,
                      input_tokens_per_cycle=None):
    """Largest equal repetition count per model that fits at a given envelope.

    Greedy admission in preserved order exhausts the cheap models last, leaving
    unequal per-model coverage. The declared analysis pairs models within a
    variant, so a reduced cohort must drop whole balanced rounds instead.
    Returns the per-model count and the cost of one round across all models.
    """
    models = sorted(set(row['model'] for row in rows))
    tasks = sorted(set(row['task_id'] for row in rows))
    planned = {model: sum(1 for row in rows if row['model'] == model) for model in models}
    require(len(set(planned.values())) == 1, 'skill_projection_phase_not_model_balanced')

    round_cost = 0
    for model in models:
        for task_id in tasks:
            repeats = sum(1 for row in rows if row['model'] == model and row['task_id'] == task_id)
            require(repeats, 'skill_projection_phase_not_task_balanced')
            round_cost += trial_ceiling(model, task_id,
                                        input_tokens_per_cycle=input_tokens_per_cycle)
    # One round is a single repetition of every (model, task) cell in the phase.
    cells = len(models) * len(tasks)
    available = authorized_microdollars - prior_reserved_microdollars
    rounds = available // round_cost if round_cost else 0
    planned_rounds = len(rows) // cells
    admitted_rounds = min(rounds, planned_rounds)
    return {'models': models, 'tasks': tasks, 'cells_per_round': cells,
            'round_microdollars': round_cost, 'planned_rounds': planned_rounds,
            'admitted_rounds': admitted_rounds,
            'admitted_entries': admitted_rounds * cells,
            'reserved_microdollars': admitted_rounds * round_cost,
            'balanced': admitted_rounds == planned_rounds}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--schedule', required=True, type=Path)
    parser.add_argument('--phase', default='skill-development')
    parser.add_argument('--authorized-microdollars', type=int, default=MAX_AUTHORIZED_MICRODOLLARS)
    parser.add_argument('--prior-reserved-microdollars', type=int, default=0)
    parser.add_argument('--reconciliation-sha256', default='0' * 64,
                        help='digest of the reconciled prior-spend statement')
    parser.add_argument('--input-tokens-per-cycle', type=int, default=None)
    parser.add_argument('--solve-envelope', action='store_true',
                        help='also report the largest per-cycle input bound that fits')
    parser.add_argument('--balanced', action='store_true',
                        help='also report the largest model-balanced cohort that fits')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)

    rows = load_schedule(args.schedule, args.phase)
    common = dict(authorized_microdollars=args.authorized_microdollars,
                  prior_reserved_microdollars=args.prior_reserved_microdollars,
                  reconciliation_sha256=args.reconciliation_sha256)
    report = project(rows, input_tokens_per_cycle=args.input_tokens_per_cycle, **common)
    report['phase'] = args.phase
    if args.solve_envelope:
        report['largest_fitting_input_tokens_per_cycle'] = largest_fitting_envelope(rows, **common)
    if args.balanced:
        report['balanced_capacity'] = balanced_capacity(
            rows, authorized_microdollars=args.authorized_microdollars,
            prior_reserved_microdollars=args.prior_reserved_microdollars,
            input_tokens_per_cycle=args.input_tokens_per_cycle)

    if args.output:
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    dollars = lambda micro: f'${micro / 1e6:,.4f}'
    print(f"projection {PROJECTION}  phase {args.phase}  (dry run: no request dispatched)")
    print(f"  planned {report['planned_entries']}  admitted {report['admitted_entries']}"
          f"  uncovered {report['uncovered_entries']}")
    print(f"  authorized {dollars(report['authorized_microdollars'])}"
          f"  reserved {dollars(report['reserved_microdollars'])}"
          f"  remaining {dollars(report['remaining_microdollars'])}")
    for model in sorted(report['by_model']):
        counts = report['by_model'][model]
        print(f"    {model:16} {counts['admitted']:3d}/{counts['planned']:<3d}"
              f"  {dollars(counts['reserved_microdollars'])}")
    if report['uncovered_entries']:
        print(f"  first uncovered entry: #{report['first_uncovered_dispatch_index']}"
              f" {report['first_uncovered_plan_entry_id']}")
    if args.solve_envelope:
        solved = report['largest_fitting_input_tokens_per_cycle']
        print(f"  largest fitting input bound per cycle: "
              f"{'none' if solved is None else solved} tokens")
    if args.balanced:
        balance = report['balanced_capacity']
        print(f"  model-balanced cohort: {balance['admitted_rounds']}"
              f"/{balance['planned_rounds']} rounds"
              f"  = {balance['admitted_entries']} entries"
              f"  {dollars(balance['reserved_microdollars'])}"
              f"  (one round {dollars(balance['round_microdollars'])})")
    return 0 if report['fits_within_authorization'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
