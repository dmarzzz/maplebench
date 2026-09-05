#!/usr/bin/env python3
"""Scene perception for the live MapleLegends client.

Two capabilities the gauge reader does not provide:

* **Moving objects.** Monsters animate and walk; scenery does not. Differencing
  consecutive frames while the character stands still isolates them without
  needing a sprite library. Other players and NPCs also move, so this returns
  "things that moved", not "monsters" -- the caller filters.
* **Map identity.** The map name is rendered top-left. Hashing that region
  detects a map change without OCR, which is all navigation needs.

Coordinates are frame pixels (Retina scale), origin top-left.

Run under .venv-legends/bin/python (needs numpy).
"""
import hashlib
import time

import numpy as np
from PIL import Image

import legends_window as window

# Regions to ignore when looking for movement, as fractions of frame size.
# The chat log, status bar and quest helper all animate constantly and would
# otherwise dominate every difference image.
PLAY_TOP = 0.06
PLAY_BOTTOM = 0.78
MAP_NAME_BOX = (0.0, 0.035, 0.24, 0.062)   # left, top, right, bottom

DIFF_THRESHOLD = 34      # per-pixel intensity change counted as motion
MIN_BLOB_PIXELS = 260    # smaller than a monster sprite at this resolution
CELL = 32                # motion is accumulated into cells this many px wide


def _region(image, box):
    width, height = image.size
    left, top, right, bottom = box
    return image.crop((int(left * width), int(top * height),
                       int(right * width), int(bottom * height)))


def map_signature(frame_path=None):
    """Stable hash of the map-name region; changes when the map changes."""
    frame_path = frame_path or window.capture()
    image = Image.open(frame_path).convert('RGB')
    patch = _region(image, MAP_NAME_BOX).resize((160, 18))
    return hashlib.sha1(patch.tobytes()).hexdigest()[:16]


def capture_burst(count=3, interval=0.30):
    """Capture consecutive frames for differencing."""
    frames = []
    for index in range(count):
        path = window.RUNTIME / ('burst-%d.png' % index)
        frames.append(np.asarray(
            Image.open(window.capture(path)).convert('L'), dtype=np.int16))
        if index + 1 < count:
            time.sleep(interval)
    return frames


def motion_mask(frames):
    """Pixels that changed across every consecutive pair.

    Requiring change in *all* pairs rather than any one of them suppresses
    single-frame artefacts: a damage number popping up, a chat line arriving,
    a cloud sprite ticking one step.
    """
    if len(frames) < 2:
        raise ValueError('need at least two frames')
    mask = None
    for earlier, later in zip(frames, frames[1:]):
        changed = np.abs(later - earlier) > DIFF_THRESHOLD
        mask = changed if mask is None else (mask & changed)
    return mask


def _blank_ui(mask):
    """Zero out the regions that always move."""
    height, width = mask.shape
    out = np.zeros_like(mask)
    top = int(height * PLAY_TOP)
    bottom = int(height * PLAY_BOTTOM)
    out[top:bottom, :] = mask[top:bottom, :]
    return out


def moving_blobs(frames):
    """Return [{'x','y','pixels'}] for clusters of motion, strongest first.

    Motion is accumulated into a coarse grid rather than flood-filled: sprite
    animation produces speckled, disconnected pixels that connected-component
    labelling splits into dozens of fragments, while a grid keeps a monster as
    one cell cluster.
    """
    mask = _blank_ui(motion_mask(frames))
    height, width = mask.shape
    rows, cols = height // CELL, width // CELL
    trimmed = mask[:rows * CELL, :cols * CELL]
    grid = trimmed.reshape(rows, CELL, cols, CELL).sum(axis=(1, 3))

    blobs = []
    visited = np.zeros_like(grid, dtype=bool)
    active = grid > (CELL * CELL * 0.045)
    for row in range(rows):
        for col in range(cols):
            if not active[row, col] or visited[row, col]:
                continue
            stack = [(row, col)]
            visited[row, col] = True
            cells = []
            while stack:
                r, c = stack.pop()
                cells.append((r, c))
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols \
                            and active[nr, nc] and not visited[nr, nc]:
                        visited[nr, nc] = True
                        stack.append((nr, nc))
            pixels = int(sum(grid[r, c] for r, c in cells))
            if pixels < MIN_BLOB_PIXELS:
                continue
            mean_r = sum(r for r, _ in cells) / float(len(cells))
            mean_c = sum(c for _, c in cells) / float(len(cells))
            blobs.append({'x': int((mean_c + 0.5) * CELL),
                          'y': int((mean_r + 0.5) * CELL),
                          'pixels': pixels,
                          'cells': len(cells)})
    blobs.sort(key=lambda blob: -blob['pixels'])
    return blobs


def annotate(frame_path, blobs, out_path, character_x=None):
    """Draw detected blobs for eyeballing. Detection is not trusted unseen."""
    from PIL import ImageDraw
    image = Image.open(frame_path).convert('RGB')
    draw = ImageDraw.Draw(image)
    for index, blob in enumerate(blobs):
        x, y = blob['x'], blob['y']
        colour = (255, 0, 255) if index else (0, 255, 0)
        draw.rectangle([x - 44, y - 44, x + 44, y + 44], outline=colour, width=4)
        draw.text((x - 40, y - 62), '%d px' % blob['pixels'], fill=colour)
    if character_x is not None:
        draw.line([character_x, 0, character_x, image.size[1]],
                  fill=(0, 200, 255), width=2)
    image.save(out_path)
    return out_path


if __name__ == '__main__':
    import json
    window.focus()
    time.sleep(1.0)
    frames = capture_burst()
    found = moving_blobs(frames)
    print('map signature:', map_signature())
    print(json.dumps(found[:8], indent=2))
    print('annotated:', annotate(window.RUNTIME / 'burst-0.png', found,
                                 window.RUNTIME / 'vision-check.png'))
