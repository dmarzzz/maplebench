#!/usr/bin/env python3
"""Locate the HP and MP gauges in a live MapleLegends frame.

Run this once with the character standing in-game. It scans the bottom status
bar for the long horizontal runs of gauge red and gauge blue, writes
runtime-legends/calibration.json, and saves an annotated PNG so the detection
can be eyeballed before the bot is trusted with it.

Gauge fill is measured as a fraction, not read as text. Fill fraction is all
the potion logic needs and it avoids OCR entirely.
"""
import json
import sys
import time

from PIL import Image, ImageDraw

import legends_window as window

# A pixel counts as gauge red / gauge blue when one channel clearly dominates.
# The thresholds are deliberately loose; the run-length filter below is what
# actually rejects incidental red and blue in the map art and UI chrome.
MIN_RUN = 40          # a gauge is a long horizontal run, not a stray sprite
BOTTOM_STRIP = 0.22   # search only the lowest fraction of the frame


def is_red(pixel):
    r, g, b = pixel[:3]
    return r > 110 and r > g * 1.8 and r > b * 1.8


def is_blue(pixel):
    r, g, b = pixel[:3]
    return b > 110 and b > r * 1.5 and b > g * 1.25


def is_exp(pixel):
    """The EXP gauge: a yellow-green ramp with no blue.

    Measured live it runs (222,238,0) -> (159,222,0). Green-dominant with a
    dead blue channel separates it from HP red (238,0,0) and MP blue
    (0,111,222). It does not separate it from the green MARKET button, which
    is why find_exp() searches only the gauge row, right of the MP track.
    """
    r, g, b = pixel[:3]
    return g > 150 and b < 80 and r > 100


def longest_run(row, predicate):
    """Return (start, length) of the longest horizontal run matching predicate."""
    best_start, best_length = 0, 0
    start, length = 0, 0
    for x, pixel in enumerate(row):
        if predicate(pixel):
            if length == 0:
                start = x
            length += 1
            if length > best_length:
                best_start, best_length = start, length
        else:
            length = 0
    return best_start, best_length


def _vertical_centre(pixels, x, y, width, height, predicate):
    """Middle row of the contiguous band containing (x, y).

    The top and bottom rows of a gauge are border and antialiasing; sampling
    the middle is what survives a real client's rendering.
    """
    top = y
    while top - 1 >= 0 and predicate(pixels[x, top - 1]):
        top -= 1
    bottom = y
    while bottom + 1 < height and predicate(pixels[x, bottom + 1]):
        bottom += 1
    return (top + bottom) // 2


def is_track_background(pixel):
    """The unfilled part of a gauge track.

    Measured from a live client frame: the empty track is a light neutral
    grey around (190, 190, 190), against dark (45, 51, 57) UI chrome. An
    earlier version of this guessed the polarity backwards and looked for a
    dark background, which made the extension run off the end of the gauge.
    """
    r, g, b = pixel[:3]
    return min(r, g, b) > 150 and (max(r, g, b) - min(r, g, b)) < 40


PROFILE_HALF = 8       # rows sampled either side of the gauge centre line
PROFILE_TOLERANCE = 20  # mean per-row difference still considered the same widget


def _column_profile(pixels, x, y, height):
    """Vertical grey profile of the gauge column at x.

    The client draws the track as a bevelled gradient, so a single pixel
    colour or a contiguous-band height says very little: measured on a real
    frame the filled band is 10px and the empty band 12px, with the column
    stepping through 173 / 219 / 221 / 210 / 190 / 179 / 165 / 140 / 113.
    The whole column profile, however, is near-identical everywhere along the
    widget and clearly different from neighbouring chrome.
    """
    profile = []
    for offset in range(-PROFILE_HALF, PROFILE_HALF + 1):
        row = min(max(y + offset, 0), height - 1)
        r, g, b = pixels[x, row][:3]
        profile.append((r + g + b) / 3.0)
    return profile


def _profile_distance(left, right):
    return sum(abs(a - b) for a, b in zip(left, right)) / float(len(left))


def _extend_across_empty(pixels, start_x, y, width, height, cap):
    """Walk right across the unfilled remainder of a track.

    Anchored on the column profile sampled at the first unfilled position.
    Colour alone is not enough: a bright UI panel butted against a full gauge
    passes any "light and desaturated" test and would swallow hundreds of
    pixels of track. Profile similarity is what actually separates gauge
    track from adjacent chrome.

    Returns 0 for a full gauge, which is correct -- the filled run is already
    the whole track.
    """
    if start_x >= width:
        return 0
    if not is_track_background(pixels[start_x, y][:3]):
        return 0
    # Anchor a few pixels in. The first column of a track is its bevelled
    # border and does not match the track's own profile, so anchoring on it
    # made the walk stop after two pixels.
    anchor_x = min(start_x + 4, width - 1)
    anchor = _column_profile(pixels, anchor_x, y, height)
    extended = 0
    while start_x + extended < width and extended < cap:
        here = _column_profile(pixels, start_x + extended, y, height)
        if _profile_distance(anchor, here) > PROFILE_TOLERANCE:
            break
        extended += 1
    return extended


def find_gauge(image, predicate):
    """Locate a gauge and return the row and extent of its *filled* run."""
    width, height = image.size
    pixels = image.load()
    top = int(height * (1 - BOTTOM_STRIP))
    best = None
    for y in range(top, height):
        row = [pixels[x, y] for x in range(width)]
        start, length = longest_run(row, predicate)
        if length >= MIN_RUN and (best is None or length > best['length']):
            best = {'y': y, 'x': start, 'length': length}
    if best is None:
        return None
    best['y'] = _vertical_centre(pixels, best['x'], best['y'], width, height, predicate)
    best['filled_at_calibration'] = best['length']
    return best


def find_on_row(image, predicate, y, min_x=0):
    """Longest matching run on one row, at or right of min_x.

    The status bar lays HP, MP and EXP out left to right on a single row, and
    anchoring to that row is what keeps detection honest. Searching the whole
    bottom strip for "blue" instead finds a 350px UI highlight at (1690,1393)
    and prefers it over the real 210px MP gauge.
    """
    width, _ = image.size
    pixels = image.load()
    row = [pixels[x, y] if x >= min_x else (0, 0, 0) for x in range(width)]
    start, length = longest_run(row, predicate)
    if length < MIN_RUN:
        return None
    return {'y': y, 'x': start, 'length': length, 'filled_at_calibration': length}


def measure_tracks(image):
    """Return (hp, mp) gauges with lengths extended to the whole track.

    HP anchors the row -- red is the least ambiguous colour in the status bar
    -- and MP is then found on that same row, to its right.

    The HP and MP tracks are drawn the same width, so whichever gauge is
    fuller bounds how far the other may be extended. That cross-bound is what
    makes a full gauge safe: with nothing unfilled to measure, the pixels
    after it belong to neighbouring chrome, and an unbounded walk anchored on
    them swallows whatever is there. Bounding by the other gauge's filled run
    keeps the walk inside the widget without assuming either is full.
    """
    width, height = image.size
    pixels = image.load()
    hp = find_gauge(image, is_red)
    mp = None
    if hp is not None:
        mp = find_on_row(image, is_blue, hp['y'], hp['x'] + hp['length'])
    known = [g['filled_at_calibration'] for g in (hp, mp) if g]
    if not known:
        return hp, mp
    # No slack: the fullest observed run is already a hard lower bound on the
    # track, and any allowance above it is room to walk into adjacent chrome.
    # When both gauges are full this yields no extension at all, which is the
    # right answer. The cost is that calibrating with *both* gauges partly
    # drained under-measures the track; check_consistent() cannot see that
    # case, so calibrate while MP is full -- the ordinary idle state.
    ceiling = max(known)
    for gauge in (hp, mp):
        if gauge is None:
            continue
        room = max(0, ceiling - gauge['length'])
        gauge['length'] += _extend_across_empty(
            pixels, gauge['x'] + gauge['length'], gauge['y'], width, height, room)
    return hp, mp


def find_exp(image, hp, mp):
    """Locate the EXP gauge on the same row as HP/MP, right of the MP track.

    XP is the benchmark's score, so this is the one gauge whose reading is a
    result rather than a safety input. It is deliberately constrained to the
    status-bar row and to the region past MP: searching the whole bottom strip
    for "green" finds the MARKET button instead whenever XP is nearly empty.
    """
    if hp is None or mp is None:
        return None
    width, height = image.size
    pixels = image.load()
    y = hp['y']
    origin = mp['x'] + mp['length']
    gauge = find_on_row(image, is_exp, y, origin)
    if gauge is None:
        # Immediately after a level-up the bar is empty, so there is no filled
        # run to find -- and XP is the one gauge whose reading is the score.
        # Fall back to locating the empty track itself, which sits just right
        # of MP on the same row.
        # An entirely empty bar *is* one long run of track background, so
        # measure that run directly and return: there is nothing to extend
        # across, and the profile walk anchored on the track's bevelled edge
        # stops within a couple of pixels. Anything right of `origin` is past
        # the MP track, so the longest such run is the EXP track.
        empty = find_on_row(image, is_track_background, y, origin)
        if empty is None:
            return None
        # Trim the bevel. The border pixels either side of the track are also
        # light and desaturated, so the raw run overshoots by ~16px (234 for a
        # 218px track) and would bias every later XP reading low by ~7%.
        mid = pixels[empty['x'] + empty['length'] // 2, y][:3]

        def is_track_body(x):
            pixel = pixels[x, y][:3]
            return all(abs(pixel[i] - mid[i]) <= 8 for i in range(3))

        left = empty['x']
        right = empty['x'] + empty['length'] - 1
        while left < right and not is_track_body(left):
            left += 1
        while right > left and not is_track_body(right):
            right -= 1
        empty['x'] = left
        empty['length'] = right - left + 1
        empty['filled_at_calibration'] = 0
        return empty
    start, length = gauge['x'], gauge['length']
    # The EXP track is drawn slightly wider than HP/MP (218px against 210px
    # on this client), so it must not be capped at their length. It has no
    # twin to cross-check against; the bound is generous and the profile walk
    # is what actually stops it, against the dark chrome to its right.
    cap = int(max(hp['length'], mp['length']) * 1.5) - length
    gauge['length'] += _extend_across_empty(
        pixels, start + length, y, width, height, max(0, cap))
    return gauge


def check_consistent(hp, mp, tolerance=0.06):
    """Reject a calibration taken at less than full HP/MP.

    The v83 HP and MP tracks are drawn the same width, so two runs of
    noticeably different length mean at least one gauge was not full. Without
    this, a calibration taken at half HP yields a denominator half the true
    track and every later read saturates at 100% -- silently disabling the
    potion logic for the whole run.
    """
    if hp is None or mp is None:
        return None
    longer = max(hp['length'], mp['length'])
    if longer <= 0:
        return None
    drift = abs(hp['length'] - mp['length']) / float(longer)
    if drift > tolerance:
        return ('HP track is %d px and MP track is %d px (%.0f%% apart). '
                'Gauges must both be full when calibrating. Rest to full HP '
                'and MP, then run this again.' % (hp['length'], mp['length'], drift * 100))
    return None


def calibrate(frame_path):
    image = Image.open(frame_path).convert('RGB')
    hp, mp = measure_tracks(image)
    if hp is None:
        raise SystemExit(
            'no HP gauge found. Is the character actually in a map (not the '
            'login screen, world select, or a cutscene)?'
        )
    complaint = check_consistent(hp, mp)
    if complaint:
        raise SystemExit(complaint)
    result = {
        'frame_size': list(image.size),
        'hp': hp,
        'mp': mp,
        'exp': find_exp(image, hp, mp),
        'calibrated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }

    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    for gauge, colour in ((hp, (0, 255, 0)), (mp, (255, 255, 0)),
                          (result['exp'], (255, 0, 255))):
        if gauge:
            draw.rectangle(
                [gauge['x'] - 2, gauge['y'] - 6,
                 gauge['x'] + gauge['length'] + 2, gauge['y'] + 6],
                outline=colour, width=2,
            )
    out = window.RUNTIME / 'calibration-check.png'
    annotated.save(out)
    return result, out


def main():
    if not window.is_running():
        raise SystemExit('client is not running; open /Applications/MapleLegends.app')
    window.focus()
    time.sleep(1.2)
    frame = window.capture()
    result, annotated = calibrate(frame)
    path = window.save_calibration(result)
    print('HP gauge:', result['hp'])
    print('MP gauge:', result['mp'] or 'NOT FOUND (potion-only mode will skip MP)')
    print('EXP gauge:', result['exp'] or 'NOT FOUND (no XP signal this run)')
    print('wrote', path)
    print('check the boxes in', annotated)


if __name__ == '__main__':
    sys.exit(main())
