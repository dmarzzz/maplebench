#!/usr/bin/env python3
"""A measured play session against the live client, for benchmark research.

This is not the unattended grinder (legends_bot.py). It runs a fixed-length
episode with a simple walk-and-swing policy, samples the EXP gauge
throughout, and writes a summary: XP gained as a fraction of the level bar,
XP per minute, how much wall clock went to perception versus action, and how
often the screen was unreadable.

The point is to find out what a screen-only agent can and cannot perceive, so
the MapleBench observation contract can be judged against something real
rather than against the Cosmic adapter alone.

Run under .venv-legends/bin/python (needs Quartz).
"""
import argparse
import json
from pathlib import Path
import signal
import sys
import time

import legends_input as keys
import legends_state as state
import legends_window as window

RUNTIME = window.RUNTIME
STOP_FILE = RUNTIME / 'STOP'


class Session:
    def __init__(self, config, minutes):
        self.config = config
        self.minutes = minutes
        self.calibration = window.load_calibration()
        self.samples = []
        self.unreadable = 0
        self.reads = 0
        self.perception_ms = 0.0
        self.action_ms = 0.0
        self.swings = 0
        self.potions = 0
        self.turns = 0
        self.stop_reason = None
        self.levelups = 0

    def defocus_chat(self):
        """Click the middle of the viewport to leave the chat input.

        The client keeps a chat field at the bottom of the window. If it holds
        keyboard focus, hotkeys are typed into world chat instead of being
        played, so this runs before the episode and after any refocus.
        """
        x, y, width, height = window.window_bounds()
        keys.click(x + width // 2, y + int(height * 0.45))
        time.sleep(0.3)

    def verify_actuation(self):
        """Confirm keys actually reach the game before trusting the episode.

        Walk briefly and require the frame to change. If it does not, input is
        going somewhere else -- a focused chat field, a modal, another app --
        and every later measurement would be fiction.
        """
        before = window.capture(RUNTIME / 'actuation-a.png')
        before_bytes = Path(before).read_bytes()
        keys.walk('arrow-right', 700)
        time.sleep(0.25)
        after = window.capture(RUNTIME / 'actuation-b.png')
        return Path(after).read_bytes() != before_bytes

    def observe(self):
        started = time.time()
        frame = window.capture()
        vitals = state.read(frame, self.calibration)
        self.perception_ms += (time.time() - started) * 1000
        self.reads += 1
        if not vitals['readable']:
            self.unreadable += 1
        return vitals

    def act(self, direction, vitals):
        started = time.time()
        config = self.config
        if vitals['readable'] and vitals['hp'] is not None \
                and vitals['hp'] < config['hp_floor']:
            keys.tap(config['hp_potion_key'])
            self.potions += 1
        # Walking and swinging together: a stationary swing cycle spends the
        # episode waiting for monsters to wander into range.
        keys.walk(direction, config['leg_ms'], attack_key=config['attack_key'],
                  swing_every_ms=config['swing_every_ms'])
        self.swings += max(1, config['leg_ms'] // config['swing_every_ms'])
        keys.tap(config['pickup_key'])
        self.action_ms += (time.time() - started) * 1000

    def run(self):
        deadline = time.time() + self.minutes * 60
        window.focus()
        time.sleep(1.0)
        self.defocus_chat()
        if not self.verify_actuation():
            self.stop_reason = ('keys are not reaching the game (chat field '
                                'focused, a modal is open, or another app has focus)')
            return self.summary()
        direction = 'arrow-right'
        leg = 0
        while time.time() < deadline:
            if STOP_FILE.exists():
                self.stop_reason = 'stop file'
                break
            if not window.is_running():
                self.stop_reason = 'client exited'
                break
            if not window.is_frontmost():
                try:
                    window.focus()
                    time.sleep(0.5)
                except window.WindowError as error:
                    self.stop_reason = 'cannot focus: %s' % error
                    break
                if not window.is_frontmost():
                    self.stop_reason = 'client will not come to front'
                    break

            vitals = self.observe()
            if vitals['readable'] and vitals['exp'] is not None:
                self.samples.append((time.time(), vitals['exp'], vitals['hp']))
            if vitals['readable'] and vitals['hp'] is not None \
                    and vitals['hp'] <= self.config['hp_abort']:
                self.stop_reason = 'HP below abort floor'
                break

            self.act(direction, vitals)
            leg += 1
            if leg % self.config['legs_per_turn'] == 0:
                direction = ('arrow-left' if direction == 'arrow-right'
                             else 'arrow-right')
                self.turns += 1
        return self.summary()

    def summary(self):
        gained = 0.0
        if len(self.samples) >= 2:
            previous = self.samples[0][1]
            for _, exp, _ in self.samples[1:]:
                delta = exp - previous
                if delta < -0.2:
                    # The bar wrapped: a level-up. Count the remainder of the
                    # old level plus the new bar's progress.
                    self.levelups += 1
                    delta = (1.0 - previous) + exp
                gained += max(0.0, delta)
                previous = exp
        elapsed = 0.0
        if self.samples:
            elapsed = self.samples[-1][0] - self.samples[0][0]
        minutes = elapsed / 60.0 if elapsed else 0.0
        return {
            'minutes': round(minutes, 2),
            'exp_bars_gained': round(gained, 4),
            'exp_bars_per_minute': round(gained / minutes, 4) if minutes else None,
            'levelups': self.levelups,
            'reads': self.reads,
            'unreadable_reads': self.unreadable,
            'unreadable_pct': round(100.0 * self.unreadable / self.reads, 1) if self.reads else None,
            'perception_ms_total': round(self.perception_ms),
            'action_ms_total': round(self.action_ms),
            'perception_share_pct': round(
                100.0 * self.perception_ms / (self.perception_ms + self.action_ms), 1)
            if (self.perception_ms + self.action_ms) else None,
            'swings': self.swings,
            'potions': self.potions,
            'turns': self.turns,
            'stop_reason': self.stop_reason or 'deadline',
        }


DEFAULTS = {
    'attack_key': 'ctrl',
    'pickup_key': 'z',
    'hp_potion_key': 'd',
    'hp_floor': 0.5,
    'hp_abort': 0.12,
    'leg_ms': 2200,
    'swing_every_ms': 600,
    'legs_per_turn': 3,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minutes', type=float, default=5.0)
    parser.add_argument('--out', default=str(RUNTIME / 'play-summary.json'))
    args = parser.parse_args()

    if not window.is_running():
        raise SystemExit('client is not running')
    STOP_FILE.unlink(missing_ok=True)
    session = Session(DEFAULTS, args.minutes)

    def bail(signum, frame):
        keys.release_all()
        sys.exit(130)

    signal.signal(signal.SIGINT, bail)
    signal.signal(signal.SIGTERM, bail)

    try:
        summary = session.run()
    finally:
        keys.release_all()
    Path(args.out).write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
