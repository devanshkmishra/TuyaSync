import math
import time
import unittest

import numpy as np

from screensync.audio.base import AudioFrame
from screensync.modes.music import (
    DEFAULT_PALETTE,
    MusicAnalysis,
    MusicAnalyzer,
    MusicMode,
    MusicSettings,
    PALETTES,
    PaletteRuntime,
    palette_colour,
    render_palette_response,
)
from screensync.screen_sync.perceptual import distance


RATE = 48000


def tone(frequency, amplitude=0.2, duration=0.1):
    times = np.arange(int(RATE * duration)) / RATE
    return AudioFrame((np.sin(times * frequency * math.tau) * amplitude).astype(np.float32), RATE, 1, 1.0)


class TestMusicAnalysis(unittest.TestCase):
    def test_default_palette_is_full_spectrum(self):
        self.assertEqual(DEFAULT_PALETTE, "Full Spectrum")
        self.assertEqual(MusicSettings().palette, DEFAULT_PALETTE)

    def test_silence_stays_at_minimum_brightness(self):
        settings = MusicSettings(minimum_brightness=0.15, maximum_brightness=0.8)
        result = MusicAnalyzer(settings).analyze(AudioFrame(np.zeros(960, dtype=np.float32), RATE, 1, 1.0))
        self.assertEqual(result.normalized_energy, 0)
        self.assertAlmostEqual(result.brightness, 0.15)

    def test_adaptive_normalization_handles_quiet_and_loud_material(self):
        analyzer = MusicAnalyzer()
        quiet = [analyzer.analyze(tone(440, 0.01)).normalized_energy for _ in range(30)][-1]
        analyzer.reset()
        loud = [analyzer.analyze(tone(440, 0.7)).normalized_energy for _ in range(30)][-1]
        self.assertGreater(quiet, 0.65)
        self.assertGreater(loud, 0.65)

    def test_beat_detection_uses_full_band_energy_only(self):
        analyzer = MusicAnalyzer()
        bass = analyzer.analyze(tone(90))
        analyzer.reset()
        treble = analyzer.analyze(tone(6000))
        self.assertTrue(bass.beat)
        self.assertTrue(treble.beat)
        self.assertEqual((bass.bass, bass.mid, bass.treble, bass.palette_position), (0.0, 0.0, 0.0, 0.0))
        self.assertEqual((treble.bass, treble.mid, treble.treble, treble.palette_position), (0.0, 0.0, 0.0, 0.0))

    def test_onset_reacts_to_energy_increase(self):
        analyzer = MusicAnalyzer()
        analyzer.analyze(AudioFrame(np.zeros(4800, dtype=np.float32), RATE, 1, 1.0))
        onset = analyzer.analyze(tone(120, 0.8)).onset
        self.assertGreater(onset, 0.2)

    def test_beats_are_discrete_and_not_band_driven(self):
        analyzer = MusicAnalyzer()
        silence = np.zeros(960, dtype=np.float32)
        hit = (np.sin(np.arange(960) / RATE * 120 * math.tau) * 0.8).astype(np.float32)
        results = [
            analyzer.analyze(AudioFrame(silence, RATE, 1, 1.00)),
            analyzer.analyze(AudioFrame(hit, RATE, 1, 1.02)),
            analyzer.analyze(AudioFrame(hit, RATE, 1, 1.04)),
            analyzer.analyze(AudioFrame(silence, RATE, 1, 1.06)),
        ]
        self.assertTrue(results[1].beat)
        self.assertFalse(results[2].beat)
        self.assertFalse(results[3].beat)
        self.assertEqual(results[1].beat_index, 1)
        self.assertEqual(results[2].beat_index, 1)

    def test_beat_detection_survives_loud_song_after_warmup(self):
        analyzer = MusicAnalyzer()
        block = 960
        frames = 1000
        envelope = np.repeat(
            [0.50 if (index * 0.02) % 0.50 < 0.08 else 0.40 for index in range(frames)],
            block,
        )
        samples = (np.sin(np.arange(frames * block) / RATE * 440 * math.tau) * envelope).astype(np.float32)
        beats = []
        for index in range(frames):
            result = analyzer.analyze(AudioFrame(samples[index * block:(index + 1) * block], RATE, 1, index * 0.02))
            if result.beat:
                beats.append(index * 0.02)
        self.assertGreaterEqual(sum(timestamp >= 10.0 for timestamp in beats), 8)

    def test_music_mode_flashes_next_palette_colour_on_a_beat(self):
        class Backend:
            name = "test"

            def start(self, _callback):
                pass

            def stop(self):
                pass

            def is_running(self):
                return True

            def status(self):
                return {}

        class Light:
            def __init__(self):
                self.states = []

            def publish(self, state):
                self.states.append(state)

        light = Light()
        mode = MusicMode(light, Backend())
        mode._running = True
        start = time.monotonic()
        silence = np.zeros(960, dtype=np.float32)
        hit = (np.sin(np.arange(960) / RATE * 95 * math.tau) * 0.8).astype(np.float32)
        mode._on_audio(AudioFrame(silence, RATE, 1, start))
        before = mode._last_colour
        mode._on_audio(AudioFrame(hit, RATE, 1, start + 0.02))
        self.assertEqual(mode._beat_count, 1)
        self.assertEqual(mode._palette_index, 1)
        self.assertEqual(tuple(round(value) for value in mode._last_colour), PALETTES[DEFAULT_PALETTE][1])
        self.assertGreater(distance(before, mode._last_colour), 0.12)
        self.assertGreater(light.states[-1].brightness, light.states[0].brightness)

    def test_music_mode_can_smooth_palette_colour_on_a_beat(self):
        class Backend:
            name = "test"

            def start(self, _callback):
                pass

            def stop(self):
                pass

            def is_running(self):
                return True

            def status(self):
                return {}

        class Light:
            def publish(self, _state):
                pass

        settings = MusicSettings(colour_response="Smooth blend")
        mode = MusicMode(Light(), Backend(), settings=settings)
        mode._running = True
        start = time.monotonic()
        silence = np.zeros(960, dtype=np.float32)
        hit = (np.sin(np.arange(960) / RATE * 95 * math.tau) * 0.8).astype(np.float32)
        mode._on_audio(AudioFrame(silence, RATE, 1, start))
        before = mode._last_colour
        mode._on_audio(AudioFrame(hit, RATE, 1, start + 0.02))
        direct_target = PALETTES[DEFAULT_PALETTE][1]
        self.assertTrue(mode._last_analysis.beat)
        self.assertGreater(distance(before, mode._last_colour), 0.0)
        self.assertLess(distance(before, mode._last_colour), distance(before, direct_target))
        self.assertNotEqual(tuple(round(value) for value in mode._last_colour), direct_target)

    def test_brightness_is_bounded(self):
        settings = MusicSettings(minimum_brightness=0.2, maximum_brightness=0.75, bass_impact=1.0)
        analyzer = MusicAnalyzer(settings)
        for amplitude in (0, 0.001, 0.1, 1.0):
            result = analyzer.analyze(tone(80, amplitude))
            self.assertGreaterEqual(result.brightness, 0.2)
            self.assertLessEqual(result.brightness, 0.75)

    def test_beat_pulse_is_visible_at_moderate_energy(self):
        settings = MusicSettings(
            intensity=0.85,
            reactivity=0.65,
            bass_impact=0.65,
            minimum_brightness=0.10,
            maximum_brightness=0.90,
        )
        analyzer = MusicAnalyzer(settings)
        analysis = MusicAnalysis(0.1, 0.42, 0, 0, 0, 0, 0, 0, True, 0.8, 1)
        response = render_palette_response(
            settings,
            analyzer,
            PaletteRuntime((80.0, 150.0, 220.0)),
            ((80, 150, 220),),
            analysis,
            0.02,
            1.0,
        )
        self.assertGreaterEqual(response.brightness, 0.70)

    def test_beat_pulse_keeps_headroom_at_high_energy(self):
        settings = MusicSettings(
            intensity=0.78,
            bass_impact=0.65,
            minimum_brightness=0.10,
            maximum_brightness=0.90,
        )
        analyzer = MusicAnalyzer(settings)
        palette = ((80, 150, 220),)
        resting = render_palette_response(
            settings,
            analyzer,
            PaletteRuntime((80.0, 150.0, 220.0)),
            palette,
            MusicAnalysis(0.4, 1.0, 0, 0, 0, 0, 0, 0),
            0.02,
            1.0,
        )
        beat = render_palette_response(
            settings,
            analyzer,
            PaletteRuntime((80.0, 150.0, 220.0)),
            palette,
            MusicAnalysis(0.4, 1.0, 0, 0, 0, 0, 0, 0, True, 1.0, 1),
            0.02,
            1.0,
        )
        self.assertLessEqual(resting.brightness, 0.40)
        self.assertGreaterEqual(beat.brightness, 0.68)
        self.assertGreaterEqual(beat.brightness - resting.brightness, 0.25)

    def test_every_palette_interpolates_within_rgb_bounds(self):
        for name in PALETTES:
            for position in (0, 0.25, 0.5, 0.75, 1):
                colour = palette_colour(name, position)
                self.assertTrue(all(0 <= channel <= 255 for channel in colour))


if __name__ == "__main__":
    unittest.main()
