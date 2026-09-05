"""Exercise gauge detection and fill measurement on synthetic frames.

The live adapter cannot be tested against a real client in CI, so the pixel
math is pinned here instead: a frame with gauges at known fill levels must
calibrate to the right rows and read back the right fractions.

Colours are the ones measured off an actual MapleLegends frame -- fill
(238, 0, 0) and (0, 159, 238), empty track (190, 190, 190), UI chrome
(45, 51, 57). The empty track being *lighter* than the chrome is the detail
an earlier version of the detector guessed backwards, so it is pinned here.
"""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is optional for the TS suite
    Image = None

CHROME = (45, 51, 57)
EMPTY = (190, 190, 190)
HP_FILL = (238, 0, 0)
MP_FILL = (0, 159, 238)


@unittest.skipUnless(Image is not None, 'Pillow is required for gauge tests')
class GaugeTest(unittest.TestCase):
    WIDTH = 2048
    HEIGHT = 1566
    TRACK_X = 440
    TRACK_LEN = 210
    MP_X = 900
    ROW = 1543

    def frame(self, hp_fraction, mp_fraction, noise=True):
        """Build a frame with gauge tracks at known fill fractions."""
        image = Image.new('RGB', (self.WIDTH, self.HEIGHT), CHROME)
        pixels = image.load()
        if noise:
            # Map art and UI accents must not be mistaken for a gauge: these
            # blobs are red and blue but shorter than MIN_RUN.
            for x in range(1200, 1225):
                for y in range(300, 320):
                    pixels[x, y] = (230, 40, 40)
                    pixels[x, y + 40] = (40, 60, 240)
            # A light UI panel butted against the end of the MP track. The
            # extension must not walk into it.
            for x in range(self.MP_X + self.TRACK_LEN, self.MP_X + self.TRACK_LEN + 300):
                for y in range(self.ROW - 8, self.ROW + 8):
                    pixels[x, y] = (250, 250, 252)
        for origin, fraction, fill in (
            (self.TRACK_X, hp_fraction, HP_FILL),
            (self.MP_X, mp_fraction, MP_FILL),
        ):
            filled = int(self.TRACK_LEN * fraction)
            for index in range(self.TRACK_LEN):
                x = origin + index
                colour = fill if index < filled else EMPTY
                for dy in (-3, -2, -1, 0, 1, 2, 3):
                    pixels[x, self.ROW + dy] = colour
        return image

    def calibrate_on(self, image):
        import legends_calibrate as calibrate
        return calibrate.measure_tracks(image)

    def test_finds_both_gauges_and_ignores_map_art(self):
        hp, mp = self.calibrate_on(self.frame(1.0, 1.0))
        self.assertIsNotNone(hp)
        self.assertIsNotNone(mp)
        # The gauge band is several pixels tall; calibration samples its middle.
        self.assertLessEqual(abs(hp['y'] - self.ROW), 3)
        self.assertEqual(hp['x'], self.TRACK_X)
        self.assertEqual(hp['length'], self.TRACK_LEN)
        self.assertEqual(mp['length'], self.TRACK_LEN)

    def test_measures_full_track_from_a_partly_filled_gauge(self):
        """Calibration must not require the character to be at full HP."""
        hp, _ = self.calibrate_on(self.frame(0.4, 1.0))
        self.assertEqual(hp['filled_at_calibration'], int(self.TRACK_LEN * 0.4))
        self.assertEqual(hp['length'], self.TRACK_LEN)

    def test_extension_stops_at_a_light_panel(self):
        """A bright UI panel abutting a full gauge must not inflate the track."""
        _, mp = self.calibrate_on(self.frame(1.0, 1.0))
        self.assertEqual(mp['length'], self.TRACK_LEN)

    def test_reads_partial_fill(self):
        import legends_state as state
        hp, mp = self.calibrate_on(self.frame(1.0, 1.0))
        calibration = {'frame_size': [self.WIDTH, self.HEIGHT], 'hp': hp, 'mp': mp}
        for expected in (1.0, 0.75, 0.5, 0.25, 0.0):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'frame.png'
                self.frame(expected, expected).save(path)
                reading = state.read(path, calibration)
            self.assertTrue(reading['readable'])
            self.assertAlmostEqual(reading['hp'], expected, delta=0.03)
            self.assertAlmostEqual(reading['mp'], expected, delta=0.03)

    def test_absent_status_bar_is_unreadable_not_zero_hp(self):
        """A map transition draws no status bar; that is not 0% HP.

        Reporting it as zero made the bot trip its HP abort floor and stop on
        every portal.
        """
        import legends_state as state
        hp, mp = self.calibrate_on(self.frame(1.0, 1.0))
        calibration = {'frame_size': [self.WIDTH, self.HEIGHT], 'hp': hp, 'mp': mp}
        blank = Image.new('RGB', (self.WIDTH, self.HEIGHT), (0, 0, 0))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'frame.png'
            blank.save(path)
            reading = state.read(path, calibration)
        self.assertFalse(reading['readable'])
        self.assertIsNone(reading['hp'])

    def test_genuinely_empty_gauge_still_reads_zero(self):
        """An empty-but-present gauge must read 0.0, not None."""
        import legends_state as state
        hp, mp = self.calibrate_on(self.frame(1.0, 1.0))
        calibration = {'frame_size': [self.WIDTH, self.HEIGHT], 'hp': hp, 'mp': mp}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'frame.png'
            self.frame(0.0, 1.0).save(path)
            reading = state.read(path, calibration)
        self.assertTrue(reading['readable'])
        self.assertEqual(reading['hp'], 0.0)

    def test_consistency_check_flags_mismatched_tracks(self):
        import legends_calibrate as calibrate
        self.assertIsNone(calibrate.check_consistent(
            {'length': 210}, {'length': 212}))
        self.assertIsNotNone(calibrate.check_consistent(
            {'length': 132}, {'length': 210}))

    def test_rejects_resized_frame(self):
        import legends_state as state
        hp, mp = self.calibrate_on(self.frame(1.0, 1.0))
        calibration = {'frame_size': [800, 600], 'hp': hp, 'mp': mp}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'frame.png'
            self.frame(1.0, 1.0).save(path)
            reading = state.read(path, calibration)
        self.assertFalse(reading['readable'])
        self.assertIn('calibrated for', reading['error'])


if __name__ == '__main__':
    unittest.main()
