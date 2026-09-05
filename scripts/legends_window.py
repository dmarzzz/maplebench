#!/usr/bin/env python3
"""Window capture and synthetic input for a live MapleLegends client.

This adapter drives an ordinary client through the same screen and keyboard a
person uses: it reads pixels and posts key events. It does not patch the
client, read or write its memory, or touch the network protocol. Every
observation here is inferred from the rendered frame and is therefore
lower-fidelity than the server-authoritative Cosmic path; scores from this
adapter are never comparable to benchmark scores.

Runtime calibration lives in runtime-legends/ and is not tracked.
"""
import json
import os
from pathlib import Path
import subprocess
import time

REPO = Path(__file__).resolve().parent.parent
RUNTIME = REPO / 'runtime-legends'
CALIBRATION = RUNTIME / 'calibration.json'
PROCESS = 'MapleLegends.exe'
CLICLICK = '/opt/homebrew/bin/cliclick'


class WindowError(RuntimeError):
    pass


def _osascript(script, attempts=3, pause=0.7):
    """Run an AppleScript, retrying transient Accessibility failures.

    During a map transition the client's window briefly disappears from the
    Accessibility tree and System Events reports "Can't get window 1 ...
    Invalid index (-1719)". That is transient and recovers within about a
    second, so a single failure must not be treated as the window being gone.
    """
    last = 'osascript failed'
    for attempt in range(attempts):
        done = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if done.returncode == 0:
            return done.stdout.strip()
        last = done.stderr.strip() or last
        if attempt + 1 < attempts:
            time.sleep(pause)
    raise WindowError(last)


def window_bounds():
    """Return (x, y, width, height) of the client window in screen points."""
    script = (
        'tell application "System Events" to tell process "%s"\n'
        '  set w to window 1\n'
        '  set {x, y} to position of w\n'
        '  set {ww, hh} to size of w\n'
        '  return (x as string) & "," & (y as string) & "," '
        '& (ww as string) & "," & (hh as string)\n'
        'end tell' % PROCESS
    )
    raw = _osascript(script)
    x, y, width, height = (int(part) for part in raw.split(','))
    if width < 320 or height < 240:
        # The 344x110 box is the "Failed in finding proper screen mode for
        # Gr2D" dialog, not the game. Treat it as a hard error so callers do
        # not calibrate or act against an error box.
        raise WindowError('window is %dx%d; client is showing a dialog, not the game' % (width, height))
    return x, y, width, height


def is_running():
    return subprocess.run(['pgrep', '-f', PROCESS], capture_output=True).returncode == 0


def frontmost_process():
    """Name of the frontmost application, or '' if it cannot be determined."""
    try:
        return _osascript(
            'tell application "System Events" to return name of first process '
            'whose frontmost is true')
    except WindowError:
        return ''


def is_frontmost():
    return frontmost_process() == PROCESS


def focus():
    """Raise the client. Synthetic key events only reach the focused window."""
    _osascript(
        'tell application "System Events" to tell process "%s"\n'
        '  set frontmost to true\n'
        '  perform action "AXRaise" of window 1\n'
        'end tell' % PROCESS
    )


def window_id():
    """CGWindowID of the client's game window.

    Picking the largest on-screen window owned by the process skips the
    Gr2D error dialog and any tooltip panels.
    """
    try:
        import Quartz
    except ImportError:
        return None
    listing = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID) or []
    best = None
    for entry in listing:
        if entry.get('kCGWindowOwnerName') != PROCESS:
            continue
        bounds = entry.get('kCGWindowBounds') or {}
        area = bounds.get('Width', 0) * bounds.get('Height', 0)
        if area < 320 * 240:
            continue
        if best is None or area > best[0]:
            best = (area, entry.get('kCGWindowNumber'))
    return best[1] if best else None


def window_pid():
    """PID owning the client's game window, for targeted event delivery."""
    try:
        import Quartz
    except ImportError:
        return None
    listing = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID) or []
    best = None
    for entry in listing:
        if entry.get('kCGWindowOwnerName') != PROCESS:
            continue
        bounds = entry.get('kCGWindowBounds') or {}
        area = bounds.get('Width', 0) * bounds.get('Height', 0)
        if area < 320 * 240:
            continue
        if best is None or area > best[0]:
            best = (area, entry.get('kCGWindowOwnerPID'))
    return best[1] if best else None


def capture(path=None):
    """Capture the client window to a PNG and return the path.

    Captures the window's own buffer via Quartz rather than a screen region.
    This matters more than it sounds: `screencapture -R` grabs whatever is
    composited at those screen coordinates on the *current* Space, so once the
    client is on another desktop -- or simply behind another window -- region
    capture silently returns someone else's pixels and every reading built on
    it is fiction. Window capture is immune to occlusion and Spaces, and it
    means perception does not require stealing focus. Only input does.

    Falls back to region capture when Quartz is unavailable, which carries the
    occlusion caveat above.
    """
    if path is None:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        path = RUNTIME / 'frame.png'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    identifier = window_id()
    if identifier is not None:
        import Quartz
        from Quartz import CoreGraphics
        image = Quartz.CGWindowListCreateImage(
            CoreGraphics.CGRectNull,
            Quartz.kCGWindowListOptionIncludingWindow,
            identifier,
            # Best (Retina) resolution: the gauge detector's run-length and
            # profile thresholds were measured at 2x, and at 1x the shorter
            # runs let UI chrome outscore the real gauges.
            Quartz.kCGWindowImageBoundsIgnoreFraming
            | Quartz.kCGWindowImageBestResolution)
        if image is not None:
            url = CoreGraphics.CFURLCreateWithFileSystemPath(
                None, str(path), CoreGraphics.kCFURLPOSIXPathStyle, False)
            destination = Quartz.CGImageDestinationCreateWithURL(
                url, 'public.png', 1, None)
            if destination is not None:
                Quartz.CGImageDestinationAddImage(destination, image, None)
                if Quartz.CGImageDestinationFinalize(destination):
                    return path
        raise WindowError('window capture failed for id %s' % identifier)

    x, y, width, height = window_bounds()
    done = subprocess.run(
        ['screencapture', '-x', '-R', '%d,%d,%d,%d' % (x, y, width, height), str(path)],
        capture_output=True, text=True,
    )
    if done.returncode != 0:
        raise WindowError(done.stderr.strip() or 'screencapture failed')
    return path


def load_calibration():
    if not CALIBRATION.exists():
        raise WindowError('no calibration; run scripts/legends_calibrate.py with the game in-game')
    return json.loads(CALIBRATION.read_text())


def save_calibration(value):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    CALIBRATION.write_text(json.dumps(value, indent=2) + '\n')
    return CALIBRATION


# --- synthetic input -------------------------------------------------------
# cliclick posts events to the focused application. Keys are held explicitly
# rather than tapped because the client reads key state for movement.

def _cliclick(*args):
    done = subprocess.run([CLICLICK, *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise WindowError(done.stderr.strip() or 'cliclick failed')


# cliclick's vocabulary is narrower than it looks: kd:/ku: accept *only*
# modifiers, so a key can be held down only if it is one of these. Everything
# else -- arrows included -- can be tapped with kp: but never held.
MODIFIERS = {'alt', 'cmd', 'ctrl', 'fn', 'shift'}
SPECIAL_KEYS = {
    'arrow-down', 'arrow-left', 'arrow-right', 'arrow-up', 'delete', 'end',
    'enter', 'esc', 'fwd-delete', 'home', 'num-0', 'num-1', 'num-2', 'num-3',
    'num-4', 'num-5', 'num-6', 'num-7', 'num-8', 'num-9', 'page-down',
    'page-up', 'return', 'space', 'tab',
}


def hold(key, duration_ms):
    """Hold a modifier down for a while. Only modifiers can be held."""
    if key not in MODIFIERS:
        raise WindowError('%s cannot be held; cliclick holds modifiers only' % key)
    _cliclick('kd:%s' % key)
    time.sleep(duration_ms / 1000.0)
    _cliclick('ku:%s' % key)


def tap(key, hold_ms=40):
    if key in MODIFIERS:
        hold(key, hold_ms)
    elif key in SPECIAL_KEYS:
        _cliclick('kp:%s' % key)
        time.sleep(hold_ms / 1000.0)
    else:
        raise WindowError('unknown key %r' % key)


def release_modifiers():
    """Release every modifier, so a kill mid-tap cannot leave one stuck down.

    Only modifiers need this: nothing else is ever held.
    """
    for key in sorted(MODIFIERS):
        try:
            _cliclick('ku:%s' % key)
        except WindowError:
            pass


def press_key(spec, hold_ms=40):
    """Press one key, whether it is a named key or a printable character."""
    if spec in MODIFIERS or spec in SPECIAL_KEYS:
        tap(spec, hold_ms)
    else:
        _cliclick('t:%s' % spec)
        time.sleep(hold_ms / 1000.0)


if __name__ == '__main__':
    if not is_running():
        raise SystemExit('client is not running; open /Applications/MapleLegends.app')
    print('bounds:', window_bounds())
    focus()
    time.sleep(1.0)
    print('captured:', capture())
