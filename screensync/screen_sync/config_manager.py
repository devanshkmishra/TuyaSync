"""Small non-secret configuration file for TuyaSync."""

from __future__ import annotations

import configparser
import os


class ConfigManager:
    """Store app preferences and non-secret light-profile references.

    The Device ID and Local Key live together in ``light-profiles.json``.
    This INI file only keeps the profile reference and last-known address
    needed to make existing installations compatible with older versions.
    """

    def __init__(self, config_file: str):
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        self.load_config()

    def get_config_by_section(self, section: str) -> dict[str, str]:
        return dict(self.config.items(section))

    def create_default_config(self) -> None:
        self.config["General"] = {"saturation_factor": "1.5"}
        self.config["TuyaSettings"] = {"update_frequency": "50"}
        self.save_config()

    def load_config(self) -> None:
        if not os.path.exists(self.config_file):
            self.create_default_config()
        else:
            self.config.read(self.config_file)

    def save_config(self) -> None:
        directory = os.path.dirname(self.config_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.config_file, "w", encoding="utf-8") as file:
            self.config.write(file)
        try:
            os.chmod(self.config_file, 0o600)
        except OSError:
            pass

    def get_general_settings(self) -> dict[str, float]:
        general = self.config["General"]
        return {"saturation_factor": general.getfloat("saturation_factor", 1.5)}

    def get_section_by_device_id(self, device_id: str) -> str | None:
        for section in self.config.sections():
            if self.config[section].get("device_id") == device_id:
                return section
        return None

    def get_section_by_profile_id(self, profile_id: str) -> str | None:
        for section in self.config.sections():
            if self.config[section].get("profile_id") == profile_id:
                return section
        return None

    def get_bulbs(self, profile_store=None) -> list[dict[str, object]]:
        """Resolve Tuya light profiles into controller configuration."""
        bulbs: list[dict[str, object]] = []
        for section_name in self.config.sections():
            if not section_name.startswith("BulbTuya"):
                continue
            section = self.config[section_name]
            profile_id = section.get("profile_id", "")
            if profile_store is not None:
                if not profile_id:
                    continue
                profile = profile_store.get_profile(profile_id)
                if profile is None:
                    continue
                device_id = profile.device_id
                local_key = profile_store.get_local_key(profile_id)
                ip_address = profile.ip_address
                placement = profile.placement
                protocol = profile.protocol
                name = profile.name
            else:
                device_id = section.get("device_id", "")
                local_key = section.get("local_key", "")
                ip_address = section.get("ip_address", "")
                placement = section.get("placement", "center")
                protocol = section.getfloat("protocol", 3.5)
                name = section.get("name", "Tuya light")
            if not device_id or not local_key:
                continue
            bulbs.append(
                {
                    "type": "Tuya",
                    "device_id": device_id,
                    "local_key": local_key,
                    "ip_address": ip_address,
                    "placement": placement,
                    "protocol": protocol,
                    "name": name,
                    "profile_id": profile_id,
                    "config_id": section_name,
                }
            )
        return bulbs

    def add_bulb(self, bulb_type: str, **kwargs) -> None:
        """Keep the old one-time migration entry point for Tuya lights only."""
        if bulb_type != "Tuya":
            raise ValueError("TuyaSync supports Tuya lights only.")
        tuya_count = len([name for name in self.config.sections() if name.startswith("BulbTuya")])
        section_name = f"BulbTuya{tuya_count + 1}"
        self.config[section_name] = {
            "device_id": str(kwargs.get("device_id", "")),
            "local_key": str(kwargs.get("local_key", "")),
            "ip_address": str(kwargs.get("ip_address", "")),
            "placement": str(kwargs.get("placement", "center")),
            "protocol": str(kwargs.get("protocol", 3.5)),
            "name": str(kwargs.get("name", "Tuya light")),
        }
        self.save_config()

    def add_tuya_profile(self, profile) -> str:
        """Add or update the non-secret reference for a light profile."""
        def value(name: str, default=""):
            if isinstance(profile, dict):
                return profile.get(name, default)
            return getattr(profile, name, default)

        profile_id = str(value("profile_id", ""))
        device_id = str(value("device_id", ""))
        values = {
            "profile_id": profile_id,
            "name": str(value("name", "Tuya light")),
            "device_id": device_id,
            "ip_address": str(value("ip_address", "")),
            "protocol": str(value("protocol", 3.5)),
            "placement": str(value("placement", "center")),
        }
        section_name = self.get_section_by_profile_id(profile_id) or self.get_section_by_device_id(device_id)
        if section_name is None:
            tuya_count = len([name for name in self.config.sections() if name.startswith("BulbTuya")])
            section_name = f"BulbTuya{tuya_count + 1}"
        self.config[section_name] = values
        self.save_config()
        return section_name

    def update_tuya_ip(self, profile_id: str, ip_address: str) -> None:
        section_name = self.get_section_by_profile_id(profile_id)
        if section_name is None:
            return
        self.config[section_name]["ip_address"] = str(ip_address or "")
        self.save_config()

    def remove_profile(self, profile_id: str) -> None:
        section_name = self.get_section_by_profile_id(profile_id)
        if section_name is not None:
            self.remove_bulb(section_name)

    def get_update_frequency(self, bulb_type: str = "Tuya") -> float:
        section = f"{bulb_type}Settings"
        return self.config.getfloat(section, "update_frequency", fallback=50.0)

    def set_update_frequency(self, bulb_type: str, frequency: float) -> None:
        section = f"{bulb_type}Settings"
        if section not in self.config:
            self.config.add_section(section)
        self.config[section]["update_frequency"] = str(frequency)
        self.save_config()

    def remove_bulb(self, config_section: str) -> None:
        if config_section in self.config.sections():
            self.config.remove_section(config_section)
            self.save_config()
