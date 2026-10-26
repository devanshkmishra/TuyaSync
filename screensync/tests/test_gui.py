import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from screensync.gui.controller import ALGORITHM_GUIDE, RESPONSE_GUIDE, AppController
from screensync.light_profiles import LightProfileStore
from screensync.modes.manager import ModeManager
from screensync.modes.scenes import ScenesMode
from screensync.scenes import BUILTIN_SCENES, ScenePreset, SceneStop
from screensync.screen_sync.ambient import SyncSettings


class FakeLightService:
    def __init__(self):
        self.commands = []

    def execute(self, method, *args):
        self.commands.append((method, args))
        return ["sent"]

    def clear(self):
        pass

    def stop(self):
        pass


class FakeCoordinator:
    name = "screen"

    def __init__(self, bulbs=("bulb",)):
        self.bulbs = list(bulbs)
        self.light_service = FakeLightService()
        self.settings = SyncSettings()
        self.running = False

    def get_settings(self):
        return self.settings

    def set_settings(self, settings):
        self.settings = settings

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def is_running(self):
        return self.running

    def reset_mode_state(self):
        pass

    def metrics_snapshot(self):
        return {"final_rgb": (10, 20, 30), "final_brightness": 0.5, "capture_fps": 30.0, "lighting_hz": 2.0}

    def device_info(self):
        return {"connected": True, "ip": "192.168.1.3", "protocol": "3.5", "state": "connected", "message": "ok"}

    def update_bulbs(self, bulbs):
        self.bulbs = list(bulbs)


def app():
    return QApplication.instance() or QApplication([])


class ControllerTest(unittest.TestCase):
    def setUp(self):
        app()
        self.tmp = Path(tempfile.mkdtemp())
        self.coordinator = FakeCoordinator()
        self.scenes_mode = ScenesMode(self.coordinator.light_service, BUILTIN_SCENES[0])
        self.manager = ModeManager([self.coordinator, self.scenes_mode])
        self.controller = self.make_controller()

    def make_controller(self):
        return AppController(
            self.coordinator,
            self.manager,
            scenes_mode=self.scenes_mode,
            scenes=list(BUILTIN_SCENES),
            settings_path=self.tmp / "ambient-settings.json",
            preferences_path=self.tmp / "ui-preferences.json",
            scenes_path=self.tmp / "scenes.json",
            monitor_options=[(1, "Display 1"), (2, "Display 2")],
        )

    def test_guides_cover_every_choice(self):
        self.assertEqual(set(ALGORITHM_GUIDE), {"Legacy", "Saturated", "Edge", "Vibrant"})
        self.assertEqual(set(RESPONSE_GUIDE), {"Responsive", "Balanced", "Cinematic"})
        self.assertIn("Recommended", ALGORITHM_GUIDE["Saturated"][0])

    def test_switching_modes_is_exclusive(self):
        modes = []
        self.controller.modeChanged.connect(modes.append)
        self.assertTrue(self.controller.switch_mode("screen"))
        self.assertTrue(self.coordinator.running)
        self.assertTrue(self.controller.switch_mode("scenes"))
        self.assertFalse(self.coordinator.running)
        self.assertEqual(self.controller.active_mode, "scenes")
        self.controller.toggle_mode("scenes")
        self.assertEqual(self.controller.active_mode, "off")
        self.assertEqual(modes, ["screen", "scenes", "off"])

    def test_modes_need_a_light(self):
        self.coordinator.bulbs = []
        notices = []
        self.controller.notice.connect(lambda text, level: notices.append(level))
        self.assertFalse(self.controller.switch_mode("screen"))
        self.assertEqual(self.controller.active_mode, "off")
        self.assertEqual(notices, ["error"])

    def test_screen_settings_apply_live_and_save(self):
        self.controller.update_screen(update_rate=5.0, minimum_brightness=40.0, maximum_brightness=20.0)
        applied = self.coordinator.settings
        self.assertEqual(applied.capture_fps, 15.0)
        self.assertEqual(applied.maximum_brightness, 40.0)
        self.controller.save_now()
        saved = json.loads((self.tmp / "ambient-settings.json").read_text())
        self.assertEqual(saved["update_rate"], 5.0)
        self.controller.reset_screen_defaults()
        self.assertEqual(self.coordinator.settings.update_rate, SyncSettings().update_rate)

    def test_custom_scenes_save_rename_and_delete(self):
        scene = ScenePreset("Mine", [SceneStop((1, 2, 3))], loop=True, builtin=False)
        self.controller.save_scene(scene)
        self.assertEqual(self.controller.scene_name, "Mine")
        renamed = ScenePreset("Renamed", [SceneStop((4, 5, 6))], loop=False, builtin=False)
        self.controller.save_scene(renamed, previous_name="Mine")
        names = [item.name for item in self.controller.scenes]
        self.assertNotIn("Mine", names)
        self.assertIn("Renamed", names)
        stored = json.loads((self.tmp / "scenes.json").read_text())
        self.assertEqual([item["name"] for item in stored], ["Renamed"])
        self.controller.delete_scene("Renamed")
        self.assertNotIn("Renamed", [item.name for item in self.controller.scenes])

    def test_custom_scene_cannot_shadow_a_builtin(self):
        builtin = BUILTIN_SCENES[0]
        self.controller.save_scene(ScenePreset(builtin.name, list(builtin.stops), builtin=False))
        self.assertEqual(sum(item.name == builtin.name for item in self.controller.scenes), 1)
        self.assertNotEqual(self.controller.scene_name, builtin.name)

    def test_builtin_scenes_cannot_be_deleted(self):
        self.controller.delete_scene(BUILTIN_SCENES[0].name)
        self.assertIn(BUILTIN_SCENES[0].name, [item.name for item in self.controller.scenes])

    def test_preferences_round_trip(self):
        self.controller.select_scene(BUILTIN_SCENES[2].name)
        self.controller.set_scene_brightness(40)
        self.controller.manual_rgb = (1, 2, 3)
        self.controller.save_now()
        restored = self.make_controller()
        self.assertEqual(restored.scene_name, BUILTIN_SCENES[2].name)
        self.assertEqual(restored.scene_brightness, 40)
        self.assertEqual(restored.manual_rgb, (1, 2, 3))

    def test_manual_colour_stops_automatic_modes(self):
        self.controller.switch_mode("screen")
        results = []
        self.controller.manualResult.connect(lambda ok, _detail: results.append(ok))
        self.controller.set_manual_colour((255, 0, 0), 50)
        for _ in range(50):
            app().processEvents()
            if results:
                break
            import time

            time.sleep(0.02)
        self.assertEqual(self.controller.active_mode, "off")
        self.assertEqual(results, [True])
        self.assertEqual(self.coordinator.light_service.commands[-1][0], "set_color")


class WindowTest(unittest.TestCase):
    def test_window_builds_and_navigates(self):
        app()
        from screensync.gui.window import MainWindow

        tmp = Path(tempfile.mkdtemp())
        coordinator = FakeCoordinator()
        store = LightProfileStore(tmp)
        store.save_profile(name="Desk", device_id="bf12a3c45d6e7f8a9b0c1d", local_key="0123456789abcdef")
        scenes_mode = ScenesMode(coordinator.light_service, BUILTIN_SCENES[0])
        controller = AppController(
            coordinator,
            ModeManager([coordinator, scenes_mode]),
            scenes_mode=scenes_mode,
            profile_store=store,
            monitor_options=[(1, "Display 1")],
        )
        window = MainWindow(controller)
        for key in ("off", "screen", "music", "album_art", "scenes", "settings"):
            window.navigate(key)
            self.assertIs(window.stack.currentWidget(), window.pages[key])
        controller.switch_mode("screen")
        self.assertTrue(window.nav["screen"].live)
        controller.poll()
        window.close()

    def test_scene_editor_returns_edited_scene(self):
        app()
        from screensync.gui.dialogs import SceneEditor

        editor = SceneEditor(ScenePreset("Test", [SceneStop((1, 2, 3), 500, 2, 1)]), lambda _scene: None)
        editor._add()
        editor._update(color=(9, 9, 9))
        editor._move(-1)
        scene = editor.result_scene()
        self.assertEqual(len(scene.stops), 2)
        self.assertEqual(scene.stops[0].color, (9, 9, 9))
        self.assertFalse(scene.builtin)


if __name__ == "__main__":
    unittest.main()
