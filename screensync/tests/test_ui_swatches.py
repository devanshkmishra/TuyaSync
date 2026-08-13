import tkinter as tk
import unittest

from screensync.ui import ALGORITHM_GUIDE, RESPONSE_GUIDE, _colour_swatch, _rgb_hex


class TestColourSwatches(unittest.TestCase):
    def test_swatch_uses_a_painted_canvas(self):
        root = tk.Tk()
        try:
            swatch = _colour_swatch(root, (35, 165, 255), lambda: None)
            self.assertIsInstance(swatch, tk.Canvas)
            self.assertEqual(swatch.itemcget(1, "fill"), _rgb_hex((35, 165, 255)))
        finally:
            root.destroy()

    def test_screen_choice_copy_explains_recommendations(self):
        self.assertIn("Recommended", ALGORITHM_GUIDE["Saturated"][0])
        self.assertIn("Recommended", RESPONSE_GUIDE["Balanced"][0])
        self.assertEqual(set(ALGORITHM_GUIDE), {"Legacy", "Saturated", "Edge", "Vibrant"})
        self.assertEqual(set(RESPONSE_GUIDE), {"Responsive", "Balanced", "Cinematic"})


if __name__ == "__main__":
    unittest.main()
