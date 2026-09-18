#!/usr/bin/env python3
"""Targeted grind loop: travel to a populated map, then hunt what moves.

Improves on legends_play.py in two ways that matter for XP rate:

* **Travel.** A character parked in a town earns nothing no matter how good
  the policy is. This walks map to map, detecting the change by hashing the
  map-name region, until it finds somewhere with moving things in it.
* **Targeting.** Instead of swinging on a timer while walking blind, it
  differences frames to find what moved and walks toward the nearest one.

Both are still screen-only: no object ids, no coordinates, no monster health.
"lives here and moved" is the strongest evidence of a monster available from
pixels, and it also matches other players and some NPCs. The policy tolerates
that -- swinging at a player wastes a second and nothing else.

Run under .venv-legends/bin/python.
"""
import argparse
import json
from pathlib import Path
import signal
import sys
import time

import legends_input as keys
import legends_state as state
import legends_vision as vision
import legends_window as window

RUNTIME = window.RUNTIME
STOP_FILE = RUNTIME / 'STOP'
LOG = RUNTIME / 'grind-episode.jsonl'

DEFAULTS = {
    'attack_key': 'ctrl',
    'pickup_key': 'z',
    'hp_potion_key': 'd',
    # The character holds two healing items total and has 38 mesos, so there
    # is no potion strategy: survival is disengage-and-regenerate. hp_floor is
    # 0 so the loop never presses an unbound potion key, and the retreat
    # threshold is high because regeneration is slow and being wrong is fatal.
    'hp_floor': 0.0,
    'hp_rest': 0.72,
    'hp_resume': 0.97,
    'hp_abort': 0.0,          # death is handled by revive, not by aborting
    'max_deaths': 4,
    'rest_poll_s': 8.0,
    'approach_ms': 460,       # one step toward a target before re-observing
    'swing_ms': 520,
    'swings_per_target': 2,   # do not stand and tank a swarm
    'travel_leg_ms': 2000,
    'travel_legs': 8,         # legs before giving up on this direction
    'min_target_pixels': 500,  # ignore cloud parallax and UI shimmer
    'focus_wait_s': 240.0,    # tolerate this much lost foreground before giving up
    'xp_stall_s': 100.0,      # no XP for this long => leave, whatever is on screen
    'centre_deadzone': 90,    # px; inside this, attack instead of walking
}


class Episode:
    def __init__(self, path=LOG):
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


class Grinder:
    def __init__(self, config, episode, target_levels, minutes):
        self.config = config
        self.episode = episode
        self.target_levels = target_levels
        self.minutes = minutes
        self.calibration = window.load_calibration()
        self.levelups = 0
        self.last_exp = None
        self.exp_gained = 0.0
        self.kills_attempted = 0
        self.travels = 0
        self.potions = 0
        self.deaths = 0
        self.rests = 0
        self.stalls = 0
        self.retreat_dir = 'arrow-right'
        self.last_xp_change = time.time()
        self.stop_reason = None
        self.frame_width = self.calibration['frame_size'][0]

    # -- perception --------------------------------------------------------
    def vitals(self):
        return state.read(window.capture(), self.calibration)

    def track_exp(self, vitals):
        """Accumulate XP across level-ups, which wrap the bar back to zero."""
        if not vitals['readable'] or vitals['exp'] is None:
            return
        current = vitals['exp']
        if self.last_exp is not None:
            delta = current - self.last_exp
            if delta < -0.2:
                self.levelups += 1
                delta = (1.0 - self.last_exp) + current
                self.episode.emit('level_up', levelups=self.levelups)
            if abs(delta) > 1e-9:
                self.last_xp_change = time.time()
            self.exp_gained += max(0.0, delta)
        self.last_exp = current

    def revive(self):
        """Dismiss the death dialog.

        HP reading exactly 0.0 means dead: the absent-gauge case returns None,
        so zero here is a real zero. Below level 30 MapleLegends takes no XP
        for a death, so reviving and continuing costs only the walk back.
        """
        x, y, width, height = window.window_bounds()
        # OK sits at these fractions of the window; measured on the live dialog.
        keys.click(x + int(width * 0.534), y + int(height * 0.313))
        time.sleep(3.0)
        self.deaths += 1
        self.episode.emit('death', deaths=self.deaths)
        # Revive drops the character in a safe town, which by definition has
        # nothing to kill. Force the next iteration to travel rather than
        # burning the whole stall timer standing in a market.
        self.last_xp_change = 0.0
        return state.read(window.capture(), self.calibration)

    def rest(self, deadline):
        """Stand still until HP recovers.

        The character has no potions, so the only healing available is idle
        regeneration. Fighting on through it is what killed it the first time.
        """
        self.rests += 1
        self.episode.emit('rest_start', rests=self.rests)
        # Break contact first. Regeneration cannot outpace a monster that is
        # still hitting you, and the first attempt at this rested in place
        # next to a snail until it died.
        keys.walk('arrow-right' if self.retreat_dir == 'arrow-right' else 'arrow-left', 2400)
        self.retreat_dir = ('arrow-left' if self.retreat_dir == 'arrow-right'
                            else 'arrow-right')
        while time.time() < deadline:
            time.sleep(self.config['rest_poll_s'])
            vitals = state.read(window.capture(), self.calibration)
            if not vitals['readable'] or vitals['hp'] is None:
                continue
            if vitals['hp'] == 0.0:
                return vitals
            if vitals['hp'] >= self.config['hp_resume']:
                self.episode.emit('rest_end', hp=vitals['hp'])
                return vitals
            if STOP_FILE.exists():
                return vitals
        return state.read(window.capture(), self.calibration)

    def targets(self):
        """Moving things worth swinging at, nearest first."""
        frames = vision.capture_burst(2, 0.26)
        blobs = vision.moving_blobs(frames)
        centre = self.frame_width // 2
        found = [b for b in blobs if b['pixels'] >= self.config['min_target_pixels']]
        found.sort(key=lambda b: abs(b['x'] - centre))
        return found

    # -- guards ------------------------------------------------------------
    def keep_going(self, deadline):
        if STOP_FILE.exists():
            self.stop_reason = 'stop file'
            return False
        if time.time() >= deadline:
            self.stop_reason = 'deadline'
            return False
        if self.levelups >= self.target_levels:
            self.stop_reason = 'reached %d level-ups' % self.levelups
            return False
        if not window.is_running():
            self.stop_reason = 'client exited'
            return False
        if not window.is_frontmost():
            # The client only accepts input while focused: measured, a walk
            # moves the frame 3.3x more than ambient animation when focused
            # and 0.8x (i.e. not at all) when not. CGEventPostToPid does not
            # reach this Wine app, so background play is not available and
            # regaining the foreground is mandatory, not cosmetic.
            # Be patient rather than fatal. On a shared desktop the foreground
            # is lost routinely -- a notification, another app, the operator
            # running a command -- and aborting a two-hour run over a few
            # seconds of lost focus is how run 4 ended after 40 seconds.
            waited = 0.0
            budget = self.config['focus_wait_s']
            while waited < budget:
                if STOP_FILE.exists():
                    self.stop_reason = 'stop file'
                    return False
                try:
                    window.focus()
                except window.WindowError:
                    pass
                time.sleep(2.0)
                waited += 2.0
                if window.is_frontmost():
                    if waited > 4.0:
                        self.episode.emit('focus_regained', seconds=round(waited))
                    break
            else:
                self.stop_reason = ('client would not come to front for %ds (%s has it)'
                                    % (budget, window.frontmost_process() or 'unknown'))
                return False
        return True

    # -- behaviour ---------------------------------------------------------
    def engage(self, target):
        """Close on a target and swing at it."""
        centre = self.frame_width // 2
        offset = target['x'] - centre
        if abs(offset) > self.config['centre_deadzone']:
            direction = 'arrow-right' if offset > 0 else 'arrow-left'
            keys.walk(direction, self.config['approach_ms'],
                      attack_key=self.config['attack_key'],
                      swing_every_ms=self.config['swing_ms'])
        # Held, not tapped: repeated Control taps trigger macOS Dictation.
        keys.attack_hold(self.config['attack_key'],
                         self.config['swings_per_target'] * self.config['swing_ms'])
        keys.tap(self.config['pickup_key'])
        self.kills_attempted += 1

    def travel(self, direction):
        """Walk until the map name changes. Returns True on a map change."""
        before = vision.map_signature()
        for leg in range(self.config['travel_legs']):
            keys.walk(direction, self.config['travel_leg_ms'],
                      attack_key=self.config['attack_key'],
                      swing_every_ms=self.config['swing_ms'])
            keys.tap('arrow-up')   # take a portal if standing on one
            time.sleep(0.5)
            if vision.map_signature() != before:
                self.travels += 1
                self.episode.emit('map_change', direction=direction, leg=leg)
                time.sleep(1.2)    # let the new map finish loading
                return True
        return False

    def run(self):
        deadline = time.time() + self.minutes * 60
        window.focus()
        time.sleep(1.0)
        x, y, width, height = window.window_bounds()
        keys.click(x + width // 2, y + int(height * 0.45))
        time.sleep(0.3)

        self.episode.emit('episode_start', target_levels=self.target_levels)
        direction = 'arrow-left'
        barren = 0

        while self.keep_going(deadline):
            vitals = self.vitals()
            self.track_exp(vitals)
            if vitals['readable'] and vitals['hp'] is not None:
                if vitals['hp'] == 0.0:
                    if self.deaths >= self.config['max_deaths']:
                        self.stop_reason = 'died %d times' % self.deaths
                        break
                    vitals = self.revive()
                    self.track_exp(vitals)
                    continue
                if vitals['hp'] < self.config['hp_floor']:
                    keys.tap(self.config['hp_potion_key'])
                    self.potions += 1
                if vitals['hp'] < self.config['hp_rest']:
                    vitals = self.rest(deadline)
                    continue

            # Gate on the objective, not on what is visible. Other players and
            # their pets animate exactly like monsters, so a town full of
            # people reads as target-rich forever and the bot farms a bystander
            # while the barren counter never advances. XP is the only
            # unambiguous evidence that this map is worth standing in.
            stalled = (time.time() - self.last_xp_change) > self.config['xp_stall_s']
            if stalled:
                self.stalls += 1
                self.episode.emit('xp_stall', stalls=self.stalls,
                                  seconds=round(time.time() - self.last_xp_change))
                self.last_xp_change = time.time()
                if not self.travel(direction):
                    direction = ('arrow-right' if direction == 'arrow-left'
                                 else 'arrow-left')
                continue

            found = self.targets()
            if found:
                barren = 0
                self.engage(found[0])
                continue

            barren += 1
            if barren >= 3:
                # Nothing has moved here for three sweeps. Move on rather than
                # swinging at scenery for the rest of the episode.
                barren = 0
                if not self.travel(direction):
                    direction = ('arrow-right' if direction == 'arrow-left'
                                 else 'arrow-left')
            else:
                keys.walk(direction, self.config['travel_leg_ms'],
                          attack_key=self.config['attack_key'],
                          swing_every_ms=self.config['swing_ms'])

        summary = {
            'levelups': self.levelups,
            'exp_bars_gained': round(self.exp_gained, 4),
            'targets_engaged': self.kills_attempted,
            'map_changes': self.travels,
            'potion_presses': self.potions,
            'deaths': self.deaths,
            'rests': self.rests,
            'xp_stalls': self.stalls,
            'stop_reason': self.stop_reason or 'unknown',
        }
        self.episode.emit('episode_end', **summary)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--levels', type=int, default=2)
    parser.add_argument('--minutes', type=float, default=90.0)
    args = parser.parse_args()

    if not window.is_running():
        raise SystemExit('client is not running')
    STOP_FILE.unlink(missing_ok=True)
    grinder = Grinder(DEFAULTS, Episode(), args.levels, args.minutes)

    def bail(signum, frame):
        keys.release_all()
        sys.exit(130)

    signal.signal(signal.SIGINT, bail)
    signal.signal(signal.SIGTERM, bail)

    try:
        summary = grinder.run()
    finally:
        keys.release_all()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
