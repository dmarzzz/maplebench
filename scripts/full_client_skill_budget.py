"""Durable, replay-refusing dollar admission for the skill-suite controller.

One trusted admission authority owns this SQLite ledger. Independent workers
must call that authority; independent copies are not a shared spending limit.
Reservations are never recycled here, even after a confirmed cheap response.
Prior spend/unknown outcomes must be carried into the policy before creation.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from maple_agent import MODELS

PRICE_DATE = '2026-09-14'
# Microdollars per token, including the conservative 1.25x cache-write input rate.
# Rational tenths avoid binary floats and round UP only at the request boundary.
RATES_TENTHS = {
    'gpt-6-astra': (125, 500), 'gpt-5.6-sol': (50, 200),
    'gpt-5.6-terra': (25, 120), 'gpt-5.6-luna': (3, 12),
}
# Luna input 0.25 microdollars is conservatively rounded upward to0.3.
MAX_AUTHORIZED_MICRODOLLARS = 50_000_000
SHA = re.compile(r'[a-f0-9]{64}\Z')


class BudgetError(ValueError):
    pass


def require(value, reason):
    if not value: raise BudgetError(reason)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def request_ceiling(model, input_tokens, output_tokens):
    require(model in MODELS and type(input_tokens) is int and 1 <= input_tokens <= 240000
            and type(output_tokens) is int and 1 <= output_tokens <= 3000, 'invalid_skill_budget_request')
    rates = RATES_TENTHS[model]
    return (input_tokens*rates[0]+output_tokens*rates[1]+9)//10


def policy(*, authorized_microdollars, prior_reserved_microdollars, reconciliation_sha256):
    require(type(authorized_microdollars) is int and 0 < authorized_microdollars <= MAX_AUTHORIZED_MICRODOLLARS
            and type(prior_reserved_microdollars) is int and 0 <= prior_reserved_microdollars <= authorized_microdollars
            and isinstance(reconciliation_sha256, str) and SHA.fullmatch(reconciliation_sha256),
            'invalid_skill_budget_policy')
    return {'schema_version': 1, 'protocol': 'skill-suite-dollar-admission-v1',
            'authorized_microdollars': authorized_microdollars,
            'prior_reserved_microdollars': prior_reserved_microdollars,
            'reconciliation_sha256': reconciliation_sha256, 'price_date': PRICE_DATE,
            'rates_tenths': {model:list(RATES_TENTHS[model]) for model in MODELS},
            'service_tier': 'default', 'reuse_reservations': False}


class Budget:
    def __init__(self, path, expected_policy):
        expected = policy(**{key:expected_policy[key] for key in (
            'authorized_microdollars','prior_reserved_microdollars','reconciliation_sha256')})
        require(encoded(expected_policy) == encoded(expected), 'skill_budget_policy_changed')
        self.path = Path(path)
        require(self.path.is_absolute() and self.path.parent.resolve(strict=True) == self.path.parent,
                'skill_budget_path_invalid')
        parent = self.path.parent.stat()
        require(parent.st_uid == os.geteuid() and not stat.S_IMODE(parent.st_mode) & 0o077,
                'skill_budget_private_directory_required')
        if not os.path.lexists(self.path):
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        info = self.path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1,
                'skill_budget_file_invalid')
        self.identity = (info.st_dev, info.st_ino)
        self.expected = expected
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS policy (singleton INTEGER PRIMARY KEY CHECK(singleton=1), body BLOB NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY, manifest TEXT NOT NULL, '
                'entry TEXT NOT NULL, cycle INTEGER NOT NULL, model TEXT NOT NULL, input_bound INTEGER NOT NULL, '
                'output_bound INTEGER NOT NULL, microdollars INTEGER NOT NULL, '
                'UNIQUE(manifest,entry,cycle))')
            row = db.execute('SELECT body FROM policy WHERE singleton=1').fetchone()
            if row is None:
                require(db.execute('SELECT count(*) FROM reservations').fetchone()[0] == 0,
                        'skill_budget_policy_missing')
                db.execute('INSERT INTO policy VALUES (1,?)', (encoded(expected),))
            else:
                require(row[0] == encoded(expected), 'skill_budget_policy_changed')
            db.commit()

    def connect(self):
        info = self.path.lstat()
        require(stat.S_ISREG(info.st_mode) and not self.path.is_symlink()
                and (info.st_dev, info.st_ino) == self.identity, 'skill_budget_file_replaced')
        db = sqlite3.connect(self.path, timeout=3)
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA synchronous=FULL')
        return db

    def reserve_request(self, *, plan_entry_id, execution_manifest_sha256, cycle, model,
                        input_token_upper_bound, output_token_upper_bound):
        require(isinstance(plan_entry_id, str) and re.fullmatch('[a-z0-9][a-z0-9_.-]{0,159}', plan_entry_id)
                and isinstance(execution_manifest_sha256, str) and SHA.fullmatch(execution_manifest_sha256)
                and type(cycle) is int and 0 <= cycle < 12, 'invalid_skill_reservation_identity')
        maximum = request_ceiling(model, input_token_upper_bound, output_token_upper_bound)
        identity = hashlib.sha256(encoded([execution_manifest_sha256, plan_entry_id, cycle])).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            require(db.execute('SELECT body FROM policy WHERE singleton=1').fetchone()[0] == encoded(self.expected),
                    'skill_budget_policy_changed')
            require(db.execute('SELECT id FROM reservations WHERE id=?', (identity,)).fetchone() is None,
                    'skill_request_reservation_replay_refused')
            reserved = db.execute('SELECT COALESCE(sum(microdollars),0) FROM reservations').fetchone()[0]
            require(self.expected['prior_reserved_microdollars']+reserved+maximum <= self.expected['authorized_microdollars'],
                    'skill_dollar_budget_exhausted')
            db.execute('INSERT INTO reservations VALUES (?,?,?,?,?,?,?,?)', (
                identity, execution_manifest_sha256, plan_entry_id, cycle, model,
                input_token_upper_bound, output_token_upper_bound, maximum))
            db.commit()
        # Returned only after the durable commit. Lost replies retain the charge.
        return {'reservation_id': identity, 'reserved_microdollars': maximum,
                'pricing_date': PRICE_DATE, 'service_tier': 'default'}

    def snapshot(self):
        with self.connect() as db:
            count, amount = db.execute('SELECT count(*),COALESCE(sum(microdollars),0) FROM reservations').fetchone()
        total = self.expected['prior_reserved_microdollars'] + amount
        return {'reservations':count, 'reserved_microdollars':amount,
                'prior_reserved_microdollars':self.expected['prior_reserved_microdollars'],
                'remaining_microdollars':self.expected['authorized_microdollars']-total}
