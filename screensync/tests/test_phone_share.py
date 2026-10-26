import json
import tempfile
import unittest
from pathlib import Path

from screensync.light_profiles import LightProfileStore
from screensync.phone_share import main, qr_png_bytes, share_payload


class PhoneShareTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = LightProfileStore(self.directory.name)
        self.profile = self.store.save_profile(
            name="Desk batten", device_id="bf1234567890abcdefgh", local_key="0123456789abcdef", ip_address="192.168.1.40", protocol="3.5"
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_payload_is_a_compact_profile_export(self):
        payload = json.loads(share_payload(self.profile))
        self.assertEqual(payload["format"], LightProfileStore.PROFILE_FORMAT)
        self.assertEqual(payload["version"], LightProfileStore.EXPORT_VERSION)
        self.assertEqual(payload["profile"], {
            "profile_id": self.profile.profile_id, "name": "Desk batten", "device_id": "bf1234567890abcdefgh", "ip_address": "192.168.1.40", "protocol": 3.5, "local_key": "0123456789abcdef",
        })

    def test_payload_round_trips_through_desktop_import(self):
        source = Path(self.directory.name) / "shared.json"
        source.write_text(share_payload(self.profile))
        other = LightProfileStore(Path(self.directory.name) / "other")
        imported = other.import_profile(source)
        self.assertEqual((imported.device_id, imported.local_key, imported.ip_address), ("bf1234567890abcdefgh", "0123456789abcdef", "192.168.1.40"))

    def test_qr_is_a_png(self):
        self.assertTrue(qr_png_bytes(share_payload(self.profile)).startswith(b"\x89PNG"))

    def test_cli_writes_png(self):
        out = Path(self.directory.name) / "qr.png"
        self.assertEqual(main(["--data-dir", self.directory.name, "--png", str(out)]), 0)
        self.assertTrue(out.read_bytes().startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
