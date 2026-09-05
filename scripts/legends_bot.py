#!/usr/bin/env python3
"""Unattended grind loop for a live MapleLegends client.

Drives a flat, mob-dense map: face a direction, swing, pick up drops, drink
when the HP gauge drops, turn around periodically. There is no pathing and no
map awareness, because neither is readable from the frame; put the character
somewhere it can survive standing still before starting this.

The loop is written to stop rather than to keep going. Any state it cannot
positively identify as "alive, in a map, gauges readable" halts the run and
releases every key. An unattended bot that presses keys into a state it does
not understand is how accounts and characters get destroyed.

Runtime config and the episode log live in runtime-legends/ and are untracked.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time

import legends_state as state
import legends_window as window

RUNTIME = window.RUNTIME
CONFIG = RUNTIME / 'config.json'
STOP_FILE = RUNTIME / 'STOP'
EPISODE = RUNTIME / 'episode.jsonl'

DEFAULTS = {
    'attack_key': 'ctrl',     # v83 default basic attack
    'pickup_key': 'z',        # v83 default loot key
    'hp_potion_key': 'd',
    'mp_potion_key': 'f',
    'hp_floor': 0.55,         # drink below this fraction
    'mp_floor': 0.25,
    'hp_abort': 0.12,         # below this, stop instead of trusting the potion
    'attack_interval_ms': 620,
    'pickup_every': 6,        # ticks between loot sweeps
    'turn_every': 40,         # ticks between direction flips
    'max_minutes': 480,
    'poll_ms': 260,
}


def load_config():
    values = dict(DEFAULTS)
    if CONFIG.exists():
        values.update(json.loads(CONFIG.read_text()))
    return values


def write_default_config():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if not CONFIG.exists():
        CONFIG.write_text(json.dumps(DEFAULTS, indent=2) + '\n')
    return CONFIG


class Episode:
    """Append-only event log shaped like MapleBench EpisodeEvent."""

    def __init__(self, path=EPISODE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seq = 0
        self.started = time.time()

    def emit(self, kind, **fields):
        self.seq += 1
        event = {'seq': self.seq, 'tMs': int((time.time() - self.started) * 1000),
                 'kind': kind, **fields}
        with self.path.open('a') as handle:
            handle.write(json.dumps(event) + '\n')
        return event


class Runner:
    def __init__(self, config, episode, dry_run=False):
        self.config = config
        self.episode = episode
        self.dry_run = dry_run
        self.calibration = window.load_calibration()
        self.stop_reason = None
        self.tick = 0
        self.unreadable = 0
        self.last_signature = None
        self.static_frames = 0
        self.refocus_failures = 0

    # -- guards ------------------------------------------------------------
    def check_stop_file(self):
        if STOP_FILE.exists():
            self.stop_reason = 'stop file present'
            return True
        return False

    def check_deadline(self, deadline):
        if time.time() >= deadline:
            self.stop_reason = 'reached max_minutes'
            return True
        return False

    def check_window(self):
        if not window.is_running():
            self.stop_reason = 'client exited'
            return True
        try:
            window.window_bounds()
        except window.WindowError as error:
            # Covers both a vanished window and the Gr2D error dialog.
            self.stop_reason = 'window unusable: %s' % error
            return True
        return False

    def check_vitals(self, vitals):
        if not vitals['readable']:
            self.unreadable += 1
            if self.unreadable >= 4:
                self.stop_reason = 'HP gauge unreadable for 4 consecutive polls'
                return True
            return False
        self.unreadable = 0
        if vitals['hp'] is not None and vitals['hp'] <= self.config['hp_abort']:
            self.stop_reason = 'HP below abort floor (%.0f%%)' % (vitals['hp'] * 100)
            return True
        return False

    def check_focus(self):
        """Refuse to send keys unless the client is actually frontmost.

        Without this, anything that steals focus overnight -- a notification,
        an update prompt, another app -- redirects a stream of synthetic Ctrl
        and Z presses into whatever is in front instead. One recovery attempt,
        then stop.
        """
        if window.is_frontmost():
            self.refocus_failures = 0
            return False
        try:
            window.focus()
            time.sleep(0.6)
        except window.WindowError as error:
            self.stop_reason = 'lost focus and could not refocus: %s' % error
            return True
        if window.is_frontmost():
            self.refocus_failures = 0
            self.episode.emit('refocused', tick=self.tick)
            return False
        self.refocus_failures += 1
        if self.refocus_failures >= 3:
            self.stop_reason = ('client would not come to the front (%s is); '
                                'refusing to send keys elsewhere'
                                % (window.frontmost_process() or 'unknown'))
            return True
        return False

    def check_liveness(self, frame_path):
        """Halt if the frame stops changing.

        A frozen frame means logged out, disconnected, or sitting in a modal.
        Continuing to hammer keys into that is worthless at best.
        """
        signature = os.path.getsize(frame_path)
        if signature == self.last_signature:
            self.static_frames += 1
            if self.static_frames >= 20:
                self.stop_reason = 'frame unchanged for 20 polls (disconnected or modal)'
                return True
        else:
            self.static_frames = 0
        self.last_signature = signature
        return False

    # -- actions -----------------------------------------------------------
    def press(self, key):
        if self.dry_run:
            return
        window.press_key(key)

    def swing(self):
        self.press(self.config['attack_key'])

    def loot(self):
        self.press(self.config['pickup_key'])

    def drink(self, which):
        self.press(self.config['%s_potion_key' % which])
        self.episode.emit('action', action={'type': 'use_item', 'itemId': which}, accepted=True)

    def turn(self):
        """Flip which way the character faces.

        A single arrow tap turns the character in place, which is all a
        stationary grind needs. Arrows cannot be held through cliclick, so
        walking is not available to this adapter.
        """
        if self.dry_run:
            return
        key = 'arrow-left' if (self.tick // self.config['turn_every']) % 2 else 'arrow-right'
        window.press_key(key)

    # -- main loop ---------------------------------------------------------
    def run(self):
        config = self.config
        deadline = time.time() + config['max_minutes'] * 60
        self.episode.emit('episode_start', taskId='legends-grind', seed='live',
                          note='live client adapter; observations are screen-derived')
        window.focus()
        time.sleep(1.0)

        while True:
            self.tick += 1
            if self.check_stop_file() or self.check_deadline(deadline) or self.check_window():
                break
            if not self.dry_run and self.check_focus():
                break

            try:
                frame = window.capture()
            except window.WindowError as error:
                self.stop_reason = 'capture failed: %s' % error
                break

            if self.check_liveness(frame):
                break

            vitals = state.read(frame, self.calibration)
            if self.check_vitals(vitals):
                break

            if vitals['readable']:
                if vitals['hp'] is not None and vitals['hp'] < config['hp_floor']:
                    self.drink('hp')
                if vitals['mp'] is not None and vitals['mp'] < config['mp_floor']:
                    self.drink('mp')

            self.swing()
            if self.tick % config['pickup_every'] == 0:
                self.loot()
            if self.tick % config['turn_every'] == 0:
                self.turn()

            if self.tick % 40 == 0:
                self.episode.emit('vitals', hp=vitals['hp'], mp=vitals['mp'], tick=self.tick)

            time.sleep(config['poll_ms'] / 1000.0)

        self.episode.emit('episode_end', reason=self.stop_reason or 'agent_exit', ticks=self.tick)
        return self.stop_reason


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true',
                        help='read and log vitals but send no key events')
    parser.add_argument('--minutes', type=float, default=None)
    parser.add_argument('--init', action='store_true',
                        help='write a default runtime-legends/config.json and exit')
    args = parser.parse_args()

    if args.init:
        print('wrote', write_default_config())
        return 0

    if not window.is_running():
        raise SystemExit('client is not running; open /Applications/MapleLegends.app')

    config = load_config()
    if args.minutes is not None:
        config['max_minutes'] = args.minutes

    STOP_FILE.unlink(missing_ok=True)
    episode = Episode()
    runner = Runner(config, episode, dry_run=args.dry_run)

    def bail(signum, frame):
        runner.stop_reason = 'signal %d' % signum
        window.release_modifiers()
        episode.emit('episode_end', reason=runner.stop_reason, ticks=runner.tick)
        sys.exit(130)

    signal.signal(signal.SIGINT, bail)
    signal.signal(signal.SIGTERM, bail)

    try:
        reason = runner.run()
    finally:
        window.release_modifiers()
    print('stopped:', reason or 'clean exit')
    print('episode log:', episode.path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
