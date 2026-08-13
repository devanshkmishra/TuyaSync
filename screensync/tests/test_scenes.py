import tempfile
import unittest
from pathlib import Path

from screensync.modes.scenes import ScenesMode
from screensync.scenes import BUILTIN_SCENES, ScenePreset, SceneStop, compile_scene, encode_scene_data, load_custom_scenes, save_custom_scenes


class TestScenes(unittest.TestCase):
    def test_scene_mode_applies_and_stops_through_the_shared_light_service(self):
        class LightService:
            def __init__(self):
                self.calls = []

            def execute(self, method, *args):
                self.calls.append((method, args))
                return ["sent"]

        service = LightService()
        mode = ScenesMode(service, BUILTIN_SCENES[0])
        mode.start()
        self.assertTrue(mode.is_running())
        self.assertEqual(service.calls[0][0], "set_scene")
        self.assertEqual(service.calls[0][1][0]["scene_num"], 1)
        mode.stop()
        self.assertFalse(mode.is_running())
        self.assertEqual(service.calls[-1], ("set_work_mode", ("colour",)))

    def test_builtin_scenes_compile_to_ds22000_ranges(self):
        for index, scene in enumerate(BUILTIN_SCENES, start=1):
            payload = compile_scene(scene, index)
            self.assertEqual(payload["scene_num"], index)
            self.assertGreaterEqual(len(payload["scene_units"]), 3)
            for unit in payload["scene_units"]:
                self.assertIn(unit["unit_change_mode"], {"static", "jump", "gradient"})
                self.assertTrue(0 <= unit["unit_switch_duration"] <= 100)
                self.assertTrue(0 <= unit["unit_gradient_duration"] <= 100)
                self.assertTrue(0 <= unit["h"] <= 360)
                self.assertTrue(0 <= unit["s"] <= 1000)
                self.assertTrue(0 <= unit["v"] <= 1000)
                self.assertTrue(0 <= unit["bright"] <= 1000)

    def test_scene_serialization_round_trip(self):
        scene = ScenePreset("Custom", [SceneStop((1, 2, 3), 450, 2.5, 1)], False, False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenes.json"
            save_custom_scenes(path, [scene])
            restored = load_custom_scenes(path)
        self.assertEqual(restored[0].name, "Custom")
        self.assertEqual(restored[0].stops[0].color, (1, 2, 3))
        self.assertFalse(restored[0].loop)

    def test_empty_scene_rejected(self):
        with self.assertRaises(ValueError):
            compile_scene(ScenePreset("Empty", []))

    def test_scene_brightness_ceiling_is_applied_to_every_stop(self):
        payload = compile_scene(BUILTIN_SCENES[0], max_brightness=420)
        self.assertTrue(all(unit["v"] <= 420 for unit in payload["scene_units"]))
        self.assertTrue(all(unit["bright"] == 0 for unit in payload["scene_units"]))

    def test_scene_data_uses_the_ds22000_packed_dp25_format(self):
        payload = compile_scene(ScenePreset("Red", [SceneStop((255, 0, 0), 800, 0, 0)]), 2)
        self.assertEqual(payload["scene_units"][0]["v"], 800)
        self.assertEqual(payload["scene_units"][0]["bright"], 0)
        self.assertEqual(payload["scene_units"][0]["temperature"], 0)
        self.assertEqual(encode_scene_data(payload), "02000000000003e8032000000000")


if __name__ == "__main__":
    unittest.main()
