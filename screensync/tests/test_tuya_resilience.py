import unittest
from unittest.mock import patch
from screensync.screen_sync.bulb_control.tuya_bulb import TuyaBulbControl
from screensync.screen_sync.rate_limiter import RateLimiter


class TestTuyaResilience(unittest.TestCase):
    def test_dp25_scene_payload_uses_scene_work_mode(self):
        class Device:
            def __init__(self):
                self.values = []

            def turn_on(self, nowait=False):
                self.values.append((20, True, nowait))
                return {"ok": True}

            def set_value(self, index, value, nowait=False):
                self.values.append((index, value, nowait))
                return {"ok": True}

        bulb = TuyaBulbControl("device", "key", "192.0.2.1", RateLimiter(1000))
        device = Device()
        bulb.bulb = device
        bulb._set_state("connected", "test")
        self.assertEqual(
            bulb.set_scene({
                "scene_num": 1,
                "scene_units": [{
                    "unit_change_mode": "static",
                    "unit_switch_duration": 0,
                    "unit_gradient_duration": 0,
                    "h": 0,
                    "s": 1000,
                    "v": 800,
                    "bright": 0,
                    "temperature": 0,
                }],
            }),
            "sent",
        )
        self.assertEqual([item[0] for item in device.values], [20, 21, 25, 21])
        self.assertTrue(all(not item[2] for item in device.values))
        self.assertTrue(device.values[0][1])
        self.assertEqual(device.values[1][1], "colour")
        self.assertTrue(device.values[2][1].startswith("01"))
        self.assertNotIn("scene_units", device.values[2][1])
        self.assertEqual(device.values[3][1], "scene")

    def test_colour_deadband_skips_small_changes(self):
        bulb = TuyaBulbControl("device", "key", "192.0.2.1", RateLimiter(1000))
        bulb.color_deadband = 10
        bulb.last_color = (100, 100, 100)
        self.assertEqual(bulb.set_color(104, 103, 102), "skipped_deadband")

    def test_dp28_payload_matches_ds22000_format(self):
        self.assertEqual(
            TuyaBulbControl.control_payload((255, 0, 0), "direct"),
            "0000003e803e800000000",
        )
        self.assertEqual(
            TuyaBulbControl.control_payload((0, 0, 255), "gradient"),
            "100f003e803e800000000",
        )

    def test_dp28_realtime_write_waits_for_device_ack(self):
        class Device:
            def __init__(self):
                self.calls = []

            def set_value(self, index, value, nowait=False):
                self.calls.append((index, value, nowait))
                return {"ok": True}

        bulb = TuyaBulbControl("device", "key", "192.0.2.1", RateLimiter(1000))
        device = Device()
        bulb.bulb = device
        bulb._set_state("connected", "test")
        bulb.set_transport("DP28", "direct")
        self.assertEqual(bulb.set_color(255, 0, 0), "sent")
        self.assertEqual(device.calls[0][0], 28)
        self.assertFalse(device.calls[0][2])

    def test_failed_connection_enters_bounded_backoff(self):
        bulb = TuyaBulbControl("device", "key", "192.0.2.1", RateLimiter(10))
        bulb._new_device = lambda: (_ for _ in ()).throw(ConnectionError("offline"))
        bulb.discover = lambda: None
        self.assertFalse(bulb.connect())
        state = bulb.connection_snapshot()
        self.assertEqual(state["state"], "backoff")
        self.assertGreater(state["retry_in"], 0)
        self.assertLessEqual(state["retry_in"], 30)

    def test_successful_reconnection_is_counted(self):
        class Device:
            def status(self):
                return {"dps": {"20": True}}

        bulb = TuyaBulbControl("device", "key", "192.0.2.1", RateLimiter(10))
        bulb._new_device = Device
        bulb._connect_current_ip()
        bulb._connect_current_ip()
        self.assertEqual(bulb.connection_snapshot()["reconnect_count"], 1)

    @patch("screensync.screen_sync.bulb_control.tuya_bulb.tinytuya.deviceScan")
    def test_discovery_persists_a_changed_ip(self, device_scan):
        device_scan.return_value = {
            "192.0.2.16": {
                "gwId": "device",
                "ip": "192.0.2.16",
                "version": "3.5",
            }
        }
        changed = []
        bulb = TuyaBulbControl(
            "device",
            "key",
            "192.0.2.15",
            RateLimiter(10),
            on_ip_changed=changed.append,
        )

        self.assertEqual(bulb.discover(), "192.0.2.16")
        self.assertEqual(changed, ["192.0.2.16"])


if __name__ == "__main__":
    unittest.main()
