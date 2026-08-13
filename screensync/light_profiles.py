"""Readable local storage and transfer for TuyaSync light profiles."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ProfileStoreError(RuntimeError):
    """Raised when a light profile cannot be safely read or written."""


@dataclass(frozen=True)
class LightProfile:
    profile_id: str
    name: str
    device_id: str
    ip_address: str = ""
    protocol: float = 3.5
    placement: str = "center"
    updated_at: str = ""
    local_key: str = field(default="", repr=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "device_id": self.device_id,
            "ip_address": self.ip_address,
            "protocol": self.protocol,
            "placement": self.placement,
            "updated_at": self.updated_at,
            "local_key": self.local_key,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LightProfile":
        try:
            profile_id = str(data["profile_id"]).strip()
            name = str(data.get("name") or "Tuya light").strip()
            device_id = str(data["device_id"]).strip()
            ip_address = str(data.get("ip_address") or "").strip()
            protocol = float(data.get("protocol", 3.5))
            placement = str(data.get("placement") or "center").strip()
            updated_at = str(data.get("updated_at") or "")
            local_key = str(data.get("local_key") or "")
        except (KeyError, TypeError, ValueError) as error:
            raise ProfileStoreError("A saved TuyaSync light profile is invalid.") from error
        if not profile_id or not device_id:
            raise ProfileStoreError("A saved TuyaSync light profile is missing its identifier.")
        return cls(profile_id, name, device_id, ip_address, protocol, placement, updated_at, local_key)


class LightProfileStore:
    """Keep the complete light profile in a readable local JSON file."""

    METADATA_VERSION = 1
    PROFILE_FORMAT = "tuyasync-light-profile"
    EXPORT_VERSION = 2

    def __init__(self, data_dir: str | os.PathLike[str]):
        self.data_dir = Path(data_dir)
        self.metadata_path = self.data_dir / "light-profiles.json"
        self._profiles = self._load_profiles()

    @staticmethod
    def profile_id_for_device(device_id: str) -> str:
        digest = hashlib.sha256(device_id.strip().encode("utf-8")).hexdigest()[:20]
        return "tuya-" + digest

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _validate_ip(ip_address: str) -> str:
        value = str(ip_address or "").strip()
        if value:
            try:
                ipaddress.ip_address(value)
            except ValueError as error:
                raise ProfileStoreError("The LAN address must be a valid IPv4 or IPv6 address.") from error
        return value

    @staticmethod
    def _validate_identity(device_id: str, local_key: str) -> tuple[str, str]:
        clean_device_id = str(device_id or "").strip()
        clean_local_key = str(local_key or "")
        if not clean_device_id:
            raise ProfileStoreError("Enter the Tuya Device ID.")
        if not clean_local_key.strip():
            raise ProfileStoreError("Enter the Tuya Local Key.")
        return clean_device_id, clean_local_key

    def _load_profiles(self) -> list[LightProfile]:
        if not self.metadata_path.exists():
            return []
        try:
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("profiles", []), list):
                raise ValueError("invalid metadata shape")
            if int(payload.get("version", 0)) != self.METADATA_VERSION:
                raise ValueError("unsupported metadata version")
            return [LightProfile.from_dict(item) for item in payload.get("profiles", [])]
        except (OSError, AttributeError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ProfileStoreError("TuyaSync light-profile metadata could not be read.") from error

    def _write_profiles(self, profiles: list[LightProfile]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.METADATA_VERSION,
            "profiles": [profile.to_dict() for profile in profiles],
        }
        temporary = self.metadata_path.with_suffix(".json.tmp")
        try:
            temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            os.replace(temporary, self.metadata_path)
            if os.name != "nt":
                os.chmod(self.metadata_path, 0o600)
        except OSError as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise ProfileStoreError("TuyaSync could not save light-profile metadata.") from error
        self._profiles = list(profiles)

    def list_profiles(self) -> list[LightProfile]:
        return list(self._profiles)

    def get_profile(self, profile_id: str) -> LightProfile | None:
        return next((profile for profile in self._profiles if profile.profile_id == profile_id), None)

    def profile_for_device(self, device_id: str) -> LightProfile | None:
        return next((profile for profile in self._profiles if profile.device_id == device_id), None)

    def get_local_key(self, profile_id: str) -> str:
        profile = self.get_profile(profile_id)
        if profile is None:
            raise ProfileStoreError("That TuyaSync light profile no longer exists.")
        if not profile.local_key:
            raise ProfileStoreError("The Local Key is missing from this light profile.")
        return profile.local_key

    def save_profile(
        self,
        name: str,
        device_id: str,
        local_key: str,
        ip_address: str = "",
        protocol: float = 3.5,
        placement: str = "center",
    ) -> LightProfile:
        device_id, local_key = self._validate_identity(device_id, local_key)
        ip_address = self._validate_ip(ip_address)
        try:
            protocol = float(protocol)
        except (TypeError, ValueError) as error:
            raise ProfileStoreError("The Tuya protocol version must be a number such as 3.5.") from error
        if not 1.0 <= protocol <= 5.0:
            raise ProfileStoreError("The Tuya protocol version is outside the supported range.")

        profile_id = self.profile_id_for_device(device_id)
        previous = self.get_profile(profile_id)
        profile = LightProfile(
            profile_id=profile_id,
            name=str(name or "").strip() or (previous.name if previous else "Tuya light"),
            device_id=device_id,
            ip_address=ip_address,
            protocol=protocol,
            placement=str(placement or "center").strip() or "center",
            updated_at=self._timestamp(),
            local_key=local_key,
        )
        profiles = [item for item in self._profiles if item.profile_id != profile_id]
        profiles.append(profile)
        self._write_profiles(profiles)
        return profile

    def update_ip(self, profile_id: str, ip_address: str) -> LightProfile | None:
        profile = self.get_profile(profile_id)
        if profile is None:
            return None
        ip_address = self._validate_ip(ip_address)
        if profile.ip_address == ip_address:
            return profile
        updated = replace(profile, ip_address=ip_address, updated_at=self._timestamp())
        self._write_profiles([updated if item.profile_id == profile_id else item for item in self._profiles])
        return updated

    def remove_profile(self, profile_id: str) -> None:
        if self.get_profile(profile_id):
            self._write_profiles([item for item in self._profiles if item.profile_id != profile_id])

    def export_profile(self, profile_id: str, destination: str | os.PathLike[str]) -> Path:
        profile = self.get_profile(profile_id)
        if profile is None:
            raise ProfileStoreError("That TuyaSync light profile no longer exists.")
        destination = Path(destination)
        payload = {
            "format": self.PROFILE_FORMAT,
            "version": self.EXPORT_VERSION,
            "profile": profile.to_dict(),
        }
        try:
            destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            if os.name != "nt":
                os.chmod(destination, 0o600)
        except OSError as error:
            raise ProfileStoreError("TuyaSync could not write the light-profile export.") from error
        return destination

    def import_profile(self, source: str | os.PathLike[str]) -> LightProfile:
        try:
            payload = json.loads(Path(source).read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("invalid profile shape")
            if payload.get("format") != self.PROFILE_FORMAT or int(payload.get("version", 0)) != self.EXPORT_VERSION:
                raise ValueError("unsupported profile format")
            profile_data = dict(payload["profile"])
            profile = LightProfile.from_dict(profile_data)
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
            raise ProfileStoreError("This is not a valid TuyaSync light-profile export.") from error

        return self.save_profile(
            name=profile.name,
            device_id=profile.device_id,
            local_key=profile.local_key,
            ip_address=profile.ip_address,
            protocol=profile.protocol,
            placement=profile.placement,
        )

    def migrate_config(self, config_manager) -> list[LightProfile]:
        """Migrate legacy raw Local Keys into the readable profile file."""
        migrated = []
        changed = False
        config = config_manager.config
        for section_name in list(config.sections()):
            if not section_name.startswith("BulbTuya"):
                continue
            section = config[section_name]
            local_key = section.get("local_key", "")
            if not local_key:
                continue
            profile = self.save_profile(
                name=section.get("name", "Tuya light"),
                device_id=section.get("device_id", ""),
                local_key=local_key,
                ip_address=section.get("ip_address", ""),
                protocol=section.get("protocol", "3.5"),
                placement=section.get("placement", "center"),
            )
            section["profile_id"] = profile.profile_id
            section.pop("local_key", None)
            section["device_id"] = profile.device_id
            section["ip_address"] = profile.ip_address
            section["protocol"] = str(profile.protocol)
            changed = True
            migrated.append(profile)
        if changed:
            config_manager.save_config()
        return migrated
