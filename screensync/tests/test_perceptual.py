import unittest

from screensync.screen_sync.perceptual import adaptive_time_constant, distance, oklab_to_rgb, rgb_to_oklab, smooth


class TestPerceptualColour(unittest.TestCase):
    def test_round_trip(self):
        for colour in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (49, 63, 95), (255, 255, 255)):
            restored = oklab_to_rgb(rgb_to_oklab(colour))
            self.assertTrue(all(abs(left - right) < 0.1 for left, right in zip(colour, restored)))

    def test_scene_cut_gets_faster_smoothing(self):
        small = distance((100, 100, 100), (105, 103, 101))
        large = distance((255, 0, 0), (0, 255, 255))
        self.assertGreater(adaptive_time_constant(small, "Balanced"), adaptive_time_constant(large, "Balanced"))

    def test_smoothing_moves_toward_target(self):
        result = smooth((255, 0, 0), (0, 255, 255), 0.05, 0.15)
        self.assertLess(result[0], 255)
        self.assertGreater(result[1], 0)
        self.assertGreater(result[2], 0)


if __name__ == "__main__":
    unittest.main()
