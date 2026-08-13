import threading
import unittest

from screensync.modes.manager import ModeManager, ModeTransitionError


class FakeMode:
    def __init__(self, name, fail_start=False, refuse_stop=False):
        self.name = name
        self.running = False
        self.fail_start = fail_start
        self.refuse_stop = refuse_stop
        self.events = []

    def start(self):
        self.events.append("start")
        if self.fail_start:
            raise RuntimeError("startup failed")
        self.running = True

    def stop(self):
        self.events.append("stop")
        if not self.refuse_stop:
            self.running = False

    def is_running(self):
        return self.running

    def reset_mode_state(self):
        self.events.append("reset")


class WorkerMode(FakeMode):
    def __init__(self, name):
        super().__init__(name)
        self.stop_event = threading.Event()
        self.worker = None

    def start(self):
        self.events.append("start")
        self.stop_event.clear()
        self.running = True
        self.worker = threading.Thread(target=self.stop_event.wait)
        self.worker.start()

    def stop(self):
        self.events.append("stop")
        self.stop_event.set()
        if self.worker:
            self.worker.join(1)
        self.running = bool(self.worker and self.worker.is_alive())


class TestModeManager(unittest.TestCase):
    def test_only_one_mode_is_active_and_handoff_is_ordered(self):
        screen, music = FakeMode("screen"), FakeMode("music")
        clears = []
        manager = ModeManager((screen, music), lambda: clears.append("clear"))
        manager.switch_to("screen")
        manager.switch_to("music")
        self.assertFalse(screen.running)
        self.assertTrue(music.running)
        self.assertEqual(screen.events, ["reset", "start", "stop"])
        self.assertEqual(music.events, ["reset", "start"])
        self.assertEqual(clears, ["clear", "clear"])

    def test_off_stops_mode_without_changing_light(self):
        screen = FakeMode("screen")
        manager = ModeManager((screen,))
        manager.switch_to("screen")
        manager.switch_to("off")
        self.assertEqual(manager.active_mode, "off")
        self.assertFalse(screen.running)

    def test_failed_start_returns_to_off(self):
        music = FakeMode("music", fail_start=True)
        manager = ModeManager((music,))
        with self.assertRaises(ModeTransitionError):
            manager.switch_to("music")
        self.assertEqual(manager.active_mode, "off")
        self.assertFalse(music.running)

    def test_refuses_handoff_when_previous_mode_does_not_stop(self):
        screen, music = FakeMode("screen", refuse_stop=True), FakeMode("music")
        manager = ModeManager((screen, music))
        manager.switch_to("screen")
        with self.assertRaises(ModeTransitionError):
            manager.switch_to("music")
        self.assertEqual(manager.active_mode, "screen")
        self.assertFalse(music.running)

    def test_worker_is_joined_before_ownership_moves(self):
        screen, music = WorkerMode("screen"), FakeMode("music")
        manager = ModeManager((screen, music))
        manager.switch_to("screen")
        worker = screen.worker
        manager.switch_to("music")
        self.assertFalse(worker.is_alive())
        self.assertEqual(manager.active_mode, "music")


if __name__ == "__main__":
    unittest.main()
