import unittest
from io import BytesIO
import math
import time
from pathlib import Path

import numpy as np
from PIL import Image

from screensync.audio.base import AudioFrame
from screensync.modes.album_art import AlbumArtMode, AlbumArtSettings, extract_art_colour, extract_art_palette
from screensync.now_playing.base import NowPlaying
from screensync.screen_sync.perceptual import distance


def png(array):
    output = BytesIO()
    Image.fromarray(np.asarray(array, dtype=np.uint8), "RGB").save(output, format="PNG")
    return output.getvalue()


class TestAlbumArt(unittest.TestCase):
    def test_colourful_art_is_vibrant(self):
        image = np.zeros((60, 60, 3), dtype=np.uint8)
        image[:, :30] = (230, 20, 160)
        image[:, 30:] = (30, 40, 220)
        colour = extract_art_colour(png(image))
        self.assertGreater(colour[2], 100)
        self.assertGreater(colour[0], 70)

    def test_palette_returns_separated_dominant_colours(self):
        image = np.zeros((60, 60, 3), dtype=np.uint8)
        image[:, :20] = (230, 20, 160)
        image[:, 20:40] = (30, 40, 220)
        image[:, 40:] = (20, 210, 100)
        palette = extract_art_palette(png(image), 3)
        self.assertEqual(len(palette), 3)
        self.assertTrue(any(colour[0] > 150 for colour in palette))
        self.assertTrue(any(colour[1] > 150 for colour in palette))
        self.assertTrue(any(colour[2] > 150 for colour in palette))

    def test_grayscale_art_stays_neutral(self):
        image = np.full((50, 50, 3), 150, dtype=np.uint8)
        colour = extract_art_colour(png(image))
        self.assertLess(max(colour) - min(colour), 12)

    def test_dark_art_does_not_become_black(self):
        image = np.full((50, 50, 3), 3, dtype=np.uint8)
        colour = extract_art_colour(png(image))
        self.assertGreaterEqual(max(colour), 80)

    def test_reactive_album_art_can_flash_or_smooth_palette_changes(self):
        class Backend:
            name = "test"

        class Light:
            def publish(self, _state):
                pass

        def run(response):
            mode = AlbumArtMode(
                Light(),
                Backend(),
                Path("."),
                settings=AlbumArtSettings(
                    palette_mode="Two colors",
                    music_reactive=True,
                    colour_response=response,
                ),
            )
            mode._running = True
            mode._current = NowPlaying("test", title="Track", is_playing=True, track_id_or_stable_key="track")
            mode._palette = ((255, 0, 0), (0, 0, 255))
            mode._colour = (255.0, 0.0, 0.0)
            mode._last_rgb = (255, 0, 0)
            start = time.monotonic()
            silence = np.zeros(960, dtype=np.float32)
            hit = (np.sin(np.arange(960) / 48000 * 95 * math.tau) * 0.8).astype(np.float32)
            mode._on_audio(AudioFrame(silence, 48000, 1, start))
            before = mode._colour
            mode._on_audio(AudioFrame(hit, 48000, 1, start + 0.02))
            return before, mode

        before, immediate = run("Immediate flash")
        self.assertEqual(immediate._palette_index, 1)
        self.assertEqual(tuple(round(value) for value in immediate._colour), (0, 0, 255))

        before, smooth = run("Smooth blend")
        direct_target = (0, 0, 255)
        self.assertEqual(smooth._palette_index, 1)
        self.assertGreater(distance(before, smooth._colour), 0.0)
        self.assertLess(distance(before, smooth._colour), distance(before, direct_target))
        self.assertNotEqual(tuple(round(value) for value in smooth._colour), direct_target)


if __name__ == "__main__":
    unittest.main()
