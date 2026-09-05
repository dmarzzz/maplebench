#!/usr/bin/env python3
"""Read character vitals out of a rendered MapleLegends frame.

Only what the screen actually shows is reported. There is no monster list,
no object ids, and no exp counter here: those are server-authoritative facts
the Cosmic adapter can supply and a screen reader cannot. Callers must treat
this as a partial Observation.
"""
from PIL import Image

import legends_calibrate as calibrate
import legends_window as window

# How far past the calibrated run to keep scanning for the gauge track. The
# calibrated length is whatever the gauge happened to be when calibrated, so
# the empty remainder of the track has to be discovered at read time.
# Fraction of the calibrated span that must still look like gauge widget for
# the reading to be trusted. Below this the status bar is not on screen.
TRACK_PRESENCE = 0.6


def _fill_fraction(pixels, gauge, predicate, width):
    """Fraction of the calibrated gauge track that is currently filled.

    Returns None when the gauge is not on screen at all, which is a different
    thing from an empty gauge and must not be confused with it: during a map
    transition the client draws no status bar, so the span contains zero fill
    pixels. Reporting that as 0% HP made the bot abort on every portal.

    The denominator is the track length fixed at calibration, so this is a
    straight count over a known span. Deriving the span at read time is what
    an earlier version got wrong: it stopped at the first unfilled pixel,
    which is the empty part of the gauge, and so every gauge read as full.
    """
    y = gauge['y']
    start = gauge['x']
    track = gauge['length']
    if track <= 0 or start + track > width:
        return None
    filled = 0
    present = 0
    for x in range(start, start + track):
        pixel = pixels[x, y]
        if predicate(pixel):
            filled += 1
            present += 1
        elif calibrate.is_track_background(pixel):
            present += 1
    if present / float(track) < TRACK_PRESENCE:
        return None
    return max(0.0, min(1.0, filled / float(track)))


def read(frame_path, calibration=None):
    """Return hp/mp/exp fill fractions plus a readable flag.

    exp is the fraction of the current level bar, so it jumps back to ~0 on
    level-up; callers tracking XP gain must handle that wrap.
    """
    calibration = calibration or window.load_calibration()
    image = Image.open(frame_path).convert('RGB')
    width, height = image.size
    expected = tuple(calibration['frame_size'])
    if (width, height) != expected:
        # The window was resized or the client switched resolution; the
        # calibrated coordinates no longer mean anything.
        return {'hp': None, 'mp': None, 'exp': None, 'readable': False,
                'error': 'frame is %dx%d, calibrated for %dx%d' % (width, height, *expected)}
    pixels = image.load()
    hp = _fill_fraction(pixels, calibration['hp'], calibrate.is_red, width)
    mp = None
    if calibration.get('mp'):
        mp = _fill_fraction(pixels, calibration['mp'], calibrate.is_blue, width)
    exp = None
    if calibration.get('exp'):
        exp = _fill_fraction(pixels, calibration['exp'], calibrate.is_exp, width)
    return {'hp': hp, 'mp': mp, 'exp': exp, 'readable': hp is not None}


if __name__ == '__main__':
    import json
    import time
    window.focus()
    time.sleep(0.8)
    print(json.dumps(read(window.capture()), indent=2))
