import json
import tempfile
import unittest
from pathlib import Path

from screensync.light_profiles import LightProfileStore, ProfileStoreError
from screensync.screen_sync.config_manager import ConfigManager


class TestLightProfileStore(unittest.TestCase):
    def make_store(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return directory, LightProfileStore(directory.name)

    def test_local_key_is_written_to_readable_local_metadata(self):
        directory, store = self.make_store()
        profile = store.save_profile("Living room", "device-123", "secret-local-key", "192.0.2.15")

        metadata = Path(directory.name, "light-profiles.json").read_text()
        self.assertIn("secret-local-key", metadata)
        self.assertEqual(store.get_local_key(profile.profile_id), "secret-local-key")
        self.assertEqual(store.list_profiles()[0].ip_address, "192.0.2.15")

    def test_plain_export_round_trips_between_stores(self):
        directory, store = self.make_store()
        profile = store.save_profile("Living room", "device-123", "secret-local-key")
        export_path = Path(directory.name, "moving-light.tuyasync-profile.json")

        store.export_profile(profile.profile_id, export_path)
        payload = json.loads(export_path.read_text())
        self.assertEqual(payload["format"], "tuyasync-light-profile")
        self.assertEqual(payload["profile"]["local_key"], "secret-local-key")

        imported = LightProfileStore(directory.name + "-imported")
        result = imported.import_profile(export_path)
        self.assertEqual(result.device_id, "device-123")
        self.assertEqual(imported.get_local_key(result.profile_id), "secret-local-key")

    def test_legacy_config_is_migrated_to_readable_profile_storage(self):
        directory, store = self.make_store()
        config_path = Path(directory.name, "config.ini")
        manager = ConfigManager(str(config_path))
        manager.add_bulb(
            "Tuya",
            device_id="device-123",
            local_key="secret-local-key",
            ip_address="192.0.2.15",
            placement="center",
        )

        migrated = store.migrate_config(manager)

        self.assertEqual(len(migrated), 1)
        self.assertNotIn("local_key", manager.config["BulbTuya1"])
        self.assertIn("profile_id", manager.config["BulbTuya1"])
        self.assertNotIn("secret-local-key", config_path.read_text())
        self.assertIn("secret-local-key", Path(directory.name, "light-profiles.json").read_text())
        bulbs = manager.get_bulbs(store)
        self.assertEqual(bulbs[0]["device_id"], "device-123")
        self.assertEqual(bulbs[0]["local_key"], "secret-local-key")

    def test_ip_update_is_persisted_without_touching_credential(self):
        directory, store = self.make_store()
        profile = store.save_profile("Living room", "device-123", "secret-local-key", "192.0.2.15")

        store.update_ip(profile.profile_id, "192.0.2.16")

        self.assertEqual(store.get_profile(profile.profile_id).ip_address, "192.0.2.16")
        self.assertEqual(store.get_local_key(profile.profile_id), "secret-local-key")

    def test_invalid_profile_metadata_is_rejected(self):
        directory, _store = self.make_store()
        Path(directory.name, "light-profiles.json").write_text(json.dumps({"version": 99, "profiles": []}))
        with self.assertRaises(ProfileStoreError):
            LightProfileStore(directory.name)


if __name__ == "__main__":
    unittest.main()
