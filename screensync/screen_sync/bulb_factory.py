"""Construct the Tuya controller used by every TuyaSync mode."""

from __future__ import annotations

from screensync.screen_sync.bulb_control.tuya_bulb import TuyaBulbControl
from screensync.screen_sync.rate_limiter import RateLimiter


class BulbFactory:
    def __init__(self, config_manager, profile_store=None):
        self.config_manager = config_manager
        self.profile_store = profile_store

    def create_bulbs(self) -> list[TuyaBulbControl]:
        bulbs = []
        for bulb_config in self.config_manager.get_bulbs(self.profile_store):
            if bulb_config.get("type") != "Tuya":
                continue
            try:
                profile_id = bulb_config.get("profile_id")
                kwargs = {"version": bulb_config.get("protocol", 3.5)}
                if self.profile_store is not None and profile_id:
                    kwargs["on_ip_changed"] = self._ip_changed(str(profile_id))
                bulb = TuyaBulbControl(
                    str(bulb_config["device_id"]),
                    str(bulb_config["local_key"]),
                    str(bulb_config.get("ip_address", "")),
                    RateLimiter(self.config_manager.get_update_frequency("Tuya")),
                    str(bulb_config.get("placement", "center")),
                    **kwargs,
                )
                # The controller handles an empty address through LAN
                # discovery and remains usable while a light is offline.
                bulb.connect()
                bulbs.append(bulb)
            except Exception as error:
                print(f"TuyaSync could not add a light: {error}", flush=True)
        return bulbs

    def _ip_changed(self, profile_id: str):
        def persist(ip_address: str) -> None:
            self.profile_store.update_ip(profile_id, ip_address)
            self.config_manager.update_tuya_ip(profile_id, ip_address)

        return persist
