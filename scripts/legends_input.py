#!/usr/bin/env python3
"""Real key events for the live MapleLegends client, via Quartz.

cliclick was the first implementation and it cannot express this adapter's
most important action: holding a direction. Its kd:/ku: pair accepts only
modifiers, so arrows can be tapped but never held, and a character that
cannot hold an arrow cannot walk. Since walking is the difference between
"attacks whatever wanders past" and "goes to the monsters", the input layer
posts CGEvents directly instead.

Events are posted to the session event tap, so they land in whatever is
focused. Callers must confirm the client is frontmost first.

Needs pyobjc-framework-Quartz (see .venv-legends) and Accessibility
permission for whatever runs it.
"""
import time

import Quartz

# US layout virtual key codes. Only the ones this adapter binds.
KEY_CODES = {
    'a': 0, 's': 1, 'd': 2, 'f': 3, 'h': 4, 'g': 5, 'z': 6, 'x': 7,
    'c': 8, 'v': 9, 'b': 11, 'q': 12, 'w': 13, 'e': 14, 'r': 15,
    'y': 16, 't': 17, '1': 18, '2': 19, '3': 20, '4': 21, '6': 22,
    '5': 23, '9': 25, '7': 26, '8': 28, '0': 29, 'o': 31, 'u': 32,
    'i': 34, 'p': 35, 'l': 37, 'j': 38, 'k': 40, 'n': 45, 'm': 46,
    'return': 36, 'tab': 48, 'space': 49, 'delete': 51, 'esc': 53,
    # 'fn' (63) is deliberately absent. Pressing it twice is the macOS
    # Dictation shortcut, and release_all() iterating every code did exactly
    # that -- putting a system modal on top of the client that swallowed all
    # further input, including the clicks trying to dismiss it.
    'ctrl': 59, 'shift': 56, 'alt': 58, 'cmd': 55,
    'arrow-left': 123, 'arrow-right': 124, 'arrow-down': 125, 'arrow-up': 126,
    'end': 119, 'home': 115, 'page-up': 116, 'page-down': 121,
    'insert': 114, 'f1': 122, 'f2': 120, 'f3': 99, 'f4': 118,
}


class InputError(RuntimeError):
    pass


def code_for(key):
    try:
        return KEY_CODES[key]
    except KeyError:
        raise InputError('no virtual key code for %r' % key)


# When set, events go to this pid instead of the focused application. That is
# what lets the bot run while the client sits on another Space or behind other
# windows: CGEventPost delivers to whatever has focus, so a background client
# would otherwise receive nothing and the keystrokes would land in the user's
# actual foreground app.
_target_pid = None


def target_pid(pid):
    global _target_pid
    _target_pid = pid


def _post(code, down):
    event = Quartz.CGEventCreateKeyboardEvent(None, code, down)
    if _target_pid is not None:
        Quartz.CGEventPostToPid(_target_pid, event)
    else:
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def key_down(key):
    _post(code_for(key), True)


def key_up(key):
    _post(code_for(key), False)


def tap(key, hold_ms=45):
    code = code_for(key)
    _post(code, True)
    time.sleep(hold_ms / 1000.0)
    _post(code, False)


def hold(key, duration_ms):
    """Hold any key down for a while. This is what walking needs."""
    code = code_for(key)
    _post(code, True)
    try:
        time.sleep(duration_ms / 1000.0)
    finally:
        _post(code, False)


def release_all():
    """Release every key this adapter can press.

    Called on every exit path. A key left down after a crash keeps the
    character walking into a wall, or worse, holds a modifier over the
    desktop.
    """
    for key in KEY_CODES:
        try:
            key_up(key)
        except InputError:
            pass


def click(x, y):
    """Left-click at a screen point.

    Used to move keyboard focus out of the client's chat input. While that
    field has focus every keystroke becomes a public chat message rather than
    an action, so a bot tapping its hotkeys spams world chat.
    """
    point = Quartz.CGPointMake(x, y)
    # Move the cursor before pressing. The client tracks mouse position and
    # ignores a down/up pair that arrives at a point the cursor never visited,
    # so a click without the move is silently dropped -- which is how the
    # first attempt to dismiss the revive dialog did nothing.
    for kind in (Quartz.kCGEventMouseMoved,):
        Quartz.CGEventPost(
            Quartz.kCGHIDEventTap,
            Quartz.CGEventCreateMouseEvent(
                None, kind, point, Quartz.kCGMouseButtonLeft))
        time.sleep(0.12)
    for kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        Quartz.CGEventPost(
            Quartz.kCGHIDEventTap,
            Quartz.CGEventCreateMouseEvent(
                None, kind, point, Quartz.kCGMouseButtonLeft))
        time.sleep(0.09)


def walk(direction, duration_ms, attack_key=None, swing_every_ms=None):
    """Walk left or right, optionally swinging while moving.

    Movement and attack are interleaved here rather than sequenced because
    the client accepts both at once, and a stationary swing cycle wastes most
    of an episode's wall clock.
    """
    if direction not in ('arrow-left', 'arrow-right'):
        raise InputError('walk direction must be an arrow key, got %r' % direction)
    code = code_for(direction)
    _post(code, True)
    started = time.time()
    last_swing = 0.0
    try:
        while (time.time() - started) * 1000 < duration_ms:
            if attack_key and swing_every_ms:
                now = time.time()
                if (now - last_swing) * 1000 >= swing_every_ms:
                    tap(attack_key, 40)
                    last_swing = now
            time.sleep(0.02)
    finally:
        _post(code, False)


if __name__ == '__main__':
    print('key codes available:', len(KEY_CODES))
    release_all()
    print('released all keys')
