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
_held = set()


def target_pid(pid):
    global _target_pid
    _target_pid = pid


def _post(code, down, key=None):
    if key is not None:
        if down:
            _held.add(key)
        else:
            _held.discard(key)
    event = Quartz.CGEventCreateKeyboardEvent(None, code, down)
    if _target_pid is not None:
        Quartz.CGEventPostToPid(_target_pid, event)
    else:
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def key_down(key):
    _post(code_for(key), True, key)


def key_up(key):
    _post(code_for(key), False, key)


def tap(key, hold_ms=45):
    code = code_for(key)
    _post(code, True, key)
    time.sleep(hold_ms / 1000.0)
    _post(code, False, key)


def hold(key, duration_ms):
    """Hold any key down for a while. This is what walking needs."""
    code = code_for(key)
    _post(code, True, key)
    try:
        time.sleep(duration_ms / 1000.0)
    finally:
        _post(code, False, key)



def release_all():
    """Release only the keys this adapter actually pressed.

    It used to post a key-up for every code in the table. A key-up with no
    matching key-down should be inert, but the client treats the stray ones as
    toggles: g, s and i opened Guild, Character Stats and Item Inventory over
    the game, which blocks play entirely and left the bot swinging at a wall
    of its own UI. Tracking held keys keeps the safety property that matters
    -- nothing is left held down -- without inventing key presses.
    """
    for key in sorted(_held):
        try:
            _post(code_for(key), False)
        except InputError:
            pass
    _held.clear()


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


def attack_hold(attack_key, duration_ms):
    """Hold the attack key down instead of tapping it repeatedly.

    The client auto-repeats an attack while its key is held, so this swings at
    the same rate as tapping. It exists because the default attack key is
    Control and macOS treats *two Control presses in quick succession* as the
    Dictation shortcut. Tapping to swing therefore raised a system modal over
    the client roughly once a minute, which swallowed every subsequent key and
    click -- including the ones trying to dismiss it. One key-down per burst
    cannot trigger a double-press, whatever the key is bound to.
    """
    code = code_for(attack_key)
    _post(code, True, attack_key)
    try:
        time.sleep(duration_ms / 1000.0)
    finally:
        _post(code, False, attack_key)


def walk(direction, duration_ms, attack_key=None, swing_every_ms=None):
    """Walk left or right, holding the attack key throughout if given.

    Movement and attack overlap rather than alternating: the client accepts
    both at once, and a stationary swing cycle wastes most of an episode's
    wall clock. swing_every_ms is accepted for call compatibility and ignored
    -- the attack is held, not pulsed, for the reason in attack_hold().
    """
    if direction not in ('arrow-left', 'arrow-right'):
        raise InputError('walk direction must be an arrow key, got %r' % direction)
    code = code_for(direction)
    attack_code = code_for(attack_key) if attack_key else None
    _post(code, True, direction)
    if attack_code is not None:
        _post(attack_code, True, attack_key)
    try:
        time.sleep(duration_ms / 1000.0)
    finally:
        if attack_code is not None:
            _post(attack_code, False, attack_key)
        _post(code, False, direction)


if __name__ == '__main__':
    print('key codes available:', len(KEY_CODES))
    release_all()
    print('released all keys')
