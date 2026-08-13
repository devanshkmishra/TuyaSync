import threading
import time
import unittest

from screensync.light_service import DesiredLightState, LightService
from screensync.screen_sync.ambient import SyncSettings


class TestLightService(unittest.TestCase):
    def test_latest_output_state_wins_and_preserves_urgency(self):
        service = LightService([])
        service._running = True
        service.publish(DesiredLightState(rgb=(1, 2, 3), urgency=0.8))
        service.publish(DesiredLightState(rgb=(7, 8, 9), urgency=0.1))
        self.assertEqual(service._pending.rgb, (7, 8, 9))
        self.assertEqual(service._pending.urgency, 0.8)
        self.assertEqual(service.metrics.snapshot()["overwritten_states"], 1)
        service._running = False

    def test_output_worker_drops_intermediate_states_and_stops(self):
        class Bulb:
            def __init__(self):
                self.calls = []
                self.started = threading.Event()
                self.release = threading.Event()

            def set_color(self, *rgb):
                self.calls.append(rgb)
                if len(self.calls) == 1:
                    self.started.set()
                    self.release.wait(1)
                return "sent"

            def set_update_rate(self, _rate): pass
            def set_color_deadband(self, _value): pass
            def set_transport(self, _transport, _transition): pass

        bulb = Bulb()
        service = LightService([bulb], settings=SyncSettings(update_rate=15))
        service.start()
        service.publish(DesiredLightState(rgb=(1, 2, 3), urgency=1))
        self.assertTrue(bulb.started.wait(1))
        service.publish(DesiredLightState(rgb=(4, 5, 6), urgency=1))
        service.publish(DesiredLightState(rgb=(7, 8, 9), urgency=1))
        bulb.release.set()
        deadline = time.monotonic() + 1
        while len(bulb.calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        worker = service._worker
        service.stop()
        self.assertEqual(bulb.calls, [(85, 170, 255), (198, 227, 255)])
        self.assertFalse(worker.is_alive())

    def test_calibration_is_applied_at_device_boundary(self):
        settings = SyncSettings(red_gain=0.5, green_gain=1.0, blue_gain=1.0, output_saturation=1.0, output_gamma=1.0)
        self.assertEqual(LightService._calibrate((200, 100, 50), settings), (100, 100, 50))


if __name__ == "__main__":
    unittest.main()
