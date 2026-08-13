import unittest
from collections import deque

import numpy as np

from screensync.screen_sync.ambient import ProcessingResult, RuntimeMetrics, ScreenProcessor, SyncSettings
from screensync.screen_sync.coordinator import Coordinator


class TestAmbientProcessing(unittest.TestCase):
    def test_runtime_rate_is_accurate_during_startup(self):
        self.assertAlmostEqual(RuntimeMetrics._rate(deque((9.0, 9.5, 10.0)), 10.0), 2.0)

    def test_black_bar_crop(self):
        frame = np.full((100, 200, 3), 80, dtype=np.uint8)
        frame[:20] = 0
        frame[-20:] = 0
        cropped, bbox = ScreenProcessor.crop_black_bars(frame, 12)
        self.assertEqual(cropped.shape[:2], (60, 200))
        self.assertEqual(bbox, (0, 20, 200, 80))

    def test_textured_dark_edges_are_not_treated_as_black_bars(self):
        frame = np.full((100, 200, 3), 80, dtype=np.uint8)
        frame[:20, ::2] = 0
        frame[:20, 1::2] = 20
        frame[-20:, ::2] = 0
        frame[-20:, 1::2] = 20
        cropped, bbox = ScreenProcessor.crop_black_bars(frame, 12)
        self.assertEqual(cropped.shape[:2], (100, 200))
        self.assertEqual(bbox, (0, 0, 200, 100))

    def test_saturation_boost_preserves_hue(self):
        result = ScreenProcessor.boost_saturation((128, 96, 96), 2.0)
        self.assertGreater(result[0] - result[1], 0)
        self.assertGreater(result[0] - result[2], 0)

    def test_settings_round_trip(self):
        settings = SyncSettings(update_rate=7.0, turn_off_on_black=True, analysis_width=64, color_deadband=9)
        restored = SyncSettings.from_dict(settings.to_dict())
        self.assertEqual(restored.update_rate, 7.0)
        self.assertTrue(restored.turn_off_on_black)
        self.assertEqual(restored.analysis_width, 64)
        self.assertEqual(restored.color_deadband, 9)

    def test_capture_is_immediately_downsampled(self):
        class Shot:
            width, height, size = 192, 108, (192, 108)
            rgb = np.full((108, 192, 3), 127, dtype=np.uint8).tobytes()

        class Capture:
            monitors = ({}, {"width": 192, "height": 108})

            def grab(self, _monitor):
                return Shot()

        processor = object.__new__(ScreenProcessor)
        processor._sct = Capture()
        frame, source = processor._capture(1, 64)
        self.assertEqual(frame.shape, (36, 64, 3))
        self.assertEqual(source, (192, 108))

    def test_small_white_subtitle_is_downweighted(self):
        region = np.full((20, 20, 3), (20, 45, 150), dtype=np.uint8)
        region[-3:, 6:14] = 255
        settings = SyncSettings(white_background_weight=0.02, reduce_static_ui=False)
        weights = ScreenProcessor._content_weights(region, None, settings)
        rgb = ScreenProcessor._representative_rgb(region, "Saturated", weights)
        self.assertGreater(rgb[2], rgb[0] * 3)
        self.assertGreater(rgb[2], rgb[1] * 2)

    def test_mostly_white_scene_is_still_recognised_as_neutral(self):
        region = np.full((20, 20, 3), 245, dtype=np.uint8)
        region[:, :3] = (210, 60, 40)
        settings = SyncSettings(white_background_weight=0.02, reduce_static_ui=False)
        weights = ScreenProcessor._content_weights(region, None, settings)
        rgb = ScreenProcessor._representative_rgb(region, "Saturated", weights)
        self.assertGreater(min(rgb), 170)
        self.assertLess(max(rgb) - min(rgb), 70)

    def test_black_bars_require_temporal_confirmation(self):
        processor = object.__new__(ScreenProcessor)
        processor._bar_candidate = None
        processor._bar_candidate_frames = 0
        processor._confirmed_bars = None
        full = (0, 0, 96, 54)
        bars = (0, 7, 96, 47)
        self.assertEqual(processor._confirmed_bar_region(bars, full), full)
        self.assertEqual(processor._confirmed_bar_region(bars, full), full)
        self.assertEqual(processor._confirmed_bar_region(bars, full), full)
        self.assertEqual(processor._confirmed_bar_region(bars, full), full)
        self.assertEqual(processor._confirmed_bar_region(bars, full), bars)
        self.assertEqual(processor._confirmed_bar_region(full, full), full)

    def test_white_mode_uses_hysteresis(self):
        class Bulb:
            def __init__(self):
                self.calls = []

            def set_white(self, *_args):
                self.calls.append("white")
                return "sent"

            def set_color(self, *_args):
                self.calls.append("color")
                return "sent"

        bulb = Bulb()
        coordinator = Coordinator([bulb])
        methods = []
        coordinator.light_service.start()
        coordinator.light_service.publish = lambda state: methods.append("set_white" if state.white_temperature is not None else "set_color")
        coordinator._brightness = 1.0
        coordinator._smoothed_rgb = (150.0, 150.0, 150.0)
        settings = SyncSettings(use_dedicated_white=True, white_enter_saturation=0.10, white_exit_saturation=0.18, white_enter_delay=0, white_exit_delay=0, brightness_attack=0, brightness_release=0)

        def result(saturation):
            return ProcessingResult((150, 150, 150), (0, 0, 96, 54), (1920, 1080), (96, 54), False, saturation, 0.6)

        coordinator._output(result(0.05), settings, 0.1)
        coordinator._output(result(0.14), settings, 0.1)
        coordinator._output(result(0.22), settings, 0.1)
        coordinator.light_service.stop()
        self.assertEqual(methods, ["set_white", "set_white", "set_color"])

    def test_black_recovery_requests_power_on(self):
        coordinator = Coordinator([])
        states = []
        coordinator.light_service.start()
        coordinator.light_service.publish = states.append
        coordinator._off_sent = True
        coordinator._smoothed_rgb = (100.0, 20.0, 10.0)
        settings = SyncSettings(brightness_attack=0, brightness_release=0)
        result = ProcessingResult((100, 20, 10), (0, 0, 96, 54), (1920, 1080), (96, 54), False, 0.9, 0.4)
        coordinator._output(result, settings, 0.1)
        coordinator.light_service.stop()
        self.assertTrue(states[-1].ensure_on)


if __name__ == "__main__":
    unittest.main()
