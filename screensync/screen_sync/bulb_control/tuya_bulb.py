"""Resilient local-LAN Tuya controller with discovery and connection state."""

from __future__ import annotations

import math
import colorsys
import threading
import time

import tinytuya

from .abstract_bulb_control import AbstractBulbControl
from screensync.scenes import encode_scene_data
from screensync.screen_sync.stats import runtime_stats


class TuyaBulbControl(AbstractBulbControl):
    def __init__(
        self,
        device_id,
        local_key,
        ip,
        rate_limiter,
        placement="center",
        version=3.5,
        on_ip_changed=None,
    ):
        self.device_id = device_id
        self.local_key = local_key
        self.ip = ip or ""
        self.version = version
        self.bulb = None
        self.rate_limiter = rate_limiter
        self.last_color = None
        self.last_white = None
        self.color_deadband = 6.0
        self.transport = "DP24"
        self.dp28_transition = "gradient"
        self.placement = placement
        self._on_ip_changed = on_ip_changed
        self.type = "Tuya"
        self._lock = threading.RLock()
        self._state = "disconnected"
        self._message = "Not connected"
        self._last_error = ""
        self._failure_count = 0
        self._next_retry_at = 0.0
        self._last_connected_at = 0.0
        self._ever_connected = False
        self._reconnect_count = 0

    def _set_state(self, state: str, message: str) -> None:
        self._state, self._message = state, message

    def connection_snapshot(self) -> dict[str, object]:
        with self._lock:
            retry_in = max(0.0, self._next_retry_at - time.monotonic())
            return {
                "state": self._state,
                "connected": self._state == "connected",
                "message": self._message,
                "last_error": self._last_error,
                "failure_count": self._failure_count,
                "reconnect_count": self._reconnect_count,
                "retry_in": retry_in,
                "ip": self.ip or "—",
                "protocol": str(self.version),
                "device_id": self.device_id,
            }

    @staticmethod
    def _device_id(record: dict) -> str:
        return str(record.get("gwId") or record.get("id") or record.get("devId") or "")

    def discover(self) -> str | None:
        with self._lock:
            self._set_state("discovering", "Looking for the light on this LAN…")
        try:
            devices = tinytuya.deviceScan(verbose=False, maxretry=2, color=False, poll=False, byID=True)
            for key, record in devices.items():
                if not isinstance(record, dict) or self._device_id(record) != self.device_id:
                    continue
                address = record.get("ip") or (key if isinstance(key, str) and "." in key else None)
                if address:
                    changed = False
                    with self._lock:
                        changed = self.ip != str(address)
                        self.ip = str(address)
                        discovered_version = record.get("version")
                        if discovered_version:
                            self.version = float(discovered_version)
                        self._set_state("discovered", f"Found at {self.ip}")
                    if changed and self._on_ip_changed:
                        try:
                            self._on_ip_changed(self.ip)
                        except Exception as error:
                            # Discovery still succeeded if metadata persistence
                            # is temporarily unavailable.
                            with self._lock:
                                self._last_error = f"Profile update: {error}"
                    return self.ip
        except Exception as error:
            with self._lock:
                self._last_error = f"Discovery: {error}"
        with self._lock:
            self._set_state("disconnected", "Light was not found on this LAN")
        return None

    @staticmethod
    def _is_error(response) -> bool:
        return isinstance(response, dict) and ("Error" in response or "Err" in response)

    def _new_device(self):
        device = tinytuya.BulbDevice(
            self.device_id, self.ip, self.local_key, version=self.version, persist=True,
            connection_timeout=2, connection_retry_limit=1, connection_retry_delay=0.25,
        )
        device.set_socketRetryLimit(1)
        device.set_socketTimeout(2)
        device.set_retry(retry=False)
        device.set_socketPersistent(True)
        return device

    def _mark_failure(self, error: Exception | str) -> None:
        self.bulb = None
        self.last_color = self.last_white = None
        self._failure_count += 1
        delay = min(30.0, 2.0 ** min(self._failure_count - 1, 5))
        self._next_retry_at = time.monotonic() + delay
        self._last_error = str(error)
        self._set_state("backoff", f"Reconnect in {delay:.0f}s")

    def connect(self, force_discovery: bool = False):
        with self._lock:
            if force_discovery or not self.ip:
                self.discover()
            if not self.ip:
                self._mark_failure("No LAN address found")
                return False
            self._set_state("connecting", f"Connecting to {self.ip}…")
            try:
                self._connect_current_ip()
            except Exception as first_error:
                if not force_discovery:
                    found = self.discover()
                    if found:
                        try:
                            self._connect_current_ip()
                            return True
                        except Exception as rediscovered_error:
                            first_error = rediscovered_error
                self._mark_failure(first_error)
                return False
            return True

    def _connect_current_ip(self) -> None:
        self._set_state("connecting", f"Connecting to {self.ip}…")
        device = self._new_device()
        status = device.status()
        if status is None or self._is_error(status):
            raise ConnectionError(str(status))
        self.bulb = device
        self._last_status = status.get("dps", {})
        if self._ever_connected:
            self._reconnect_count += 1
        self._ever_connected = True
        self._failure_count = 0
        self._next_retry_at = 0.0
        self._last_error = ""
        self._last_connected_at = time.time()
        self._set_state("connected", f"Connected at {self.ip}")

    def _ensure_connected(self) -> str:
        if self.bulb is not None and self._state == "connected":
            return "connected"
        if time.monotonic() < self._next_retry_at:
            return "unavailable"
        return "connected" if self.connect(force_discovery=self._failure_count > 0) else "failed"

    def _command(self, operation) -> str:
        with self._lock:
            state = self._ensure_connected()
            if state != "connected":
                return state
            try:
                response = operation(self.bulb)
                if self._is_error(response):
                    raise ConnectionError(str(response))
                self._set_state("connected", f"Connected at {self.ip}")
                return "sent"
            except Exception as error:
                self._mark_failure(error)
                return "failed"

    @runtime_stats.timed_function("update_tuya_bulb")
    def set_color(self, r, g, b):
        new_color = (int(r), int(g), int(b))
        if self.last_color is not None and math.dist(new_color, self.last_color) < self.color_deadband:
            return "skipped_deadband"
        if not self.rate_limiter.is_allowed():
            return "skipped_rate_limit"
        if self.transport == "DP28":
            outcome = self._command(
                lambda bulb: self._send_control_data(bulb, self.control_payload(new_color, self.dp28_transition))
            )
        else:
            outcome = self._command(lambda bulb: bulb.set_colour(*new_color, nowait=False))
        if outcome == "sent":
            self.last_color, self.last_white = new_color, None
        return outcome

    def set_white(self, brightness, colourtemp):
        new_white = (int(brightness), int(colourtemp))
        if self.last_white and abs(new_white[0] - self.last_white[0]) < 8 and abs(new_white[1] - self.last_white[1]) < 12:
            return "skipped_deadband"
        if not self.rate_limiter.is_allowed():
            return "skipped_rate_limit"
        outcome = self._command(lambda bulb: bulb.set_white(*new_white, nowait=False))
        if outcome == "sent":
            self.last_white, self.last_color = new_white, None
        return outcome

    def set_update_rate(self, updates_per_second):
        self.rate_limiter.set_rate(updates_per_second)

    def set_color_deadband(self, value):
        self.color_deadband = max(0.0, float(value))

    def set_transport(self, transport: str, transition: str = "gradient") -> None:
        self.transport = "DP28" if str(transport).upper() == "DP28" else "DP24"
        self.dp28_transition = "direct" if transition == "direct" else "gradient"
        self.last_color = None

    def _send_control_data(self, bulb, payload: str):
        if self.last_white is not None:
            response = bulb.set_value(21, "colour", nowait=False)
            if self._is_error(response):
                return response
        # The DS22000 is more reliable when the realtime write is
        # acknowledged.  The output worker remains serialized, so this does
        # not create a command backlog.
        return bulb.set_value(28, payload, nowait=False)

    @staticmethod
    def control_payload(rgb: tuple[int, int, int], transition: str = "gradient") -> str:
        hue, saturation, value = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))
        mode = 0 if transition == "direct" else 1
        return f"{mode:x}{int(hue * 360):04x}{int(saturation * 1000):04x}{int(value * 1000):04x}00000000"

    def turn_off(self):
        return self._command(lambda bulb: bulb.turn_off(nowait=False))

    def turn_on(self):
        return self._command(lambda bulb: bulb.turn_on(nowait=False))

    def set_scene(self, scene_data: dict) -> str:
        payload = encode_scene_data(scene_data)

        def apply_scene(bulb):
            # The DS22000 may acknowledge a combined DP21/DP25 packet while
            # retaining its previous scene.  Keep the writes serialized and
            # explicit: wake the batten, leave the old scene, store the new
            # packed DP25 scene string, then enter scene mode.  A work-mode write alone does
            # not power on a DS22000 that was previously off.
            response = bulb.turn_on(nowait=False)
            if self._is_error(response):
                return response
            for index, value in ((21, "colour"), (25, payload), (21, "scene")):
                response = bulb.set_value(index, value, nowait=False)
                if self._is_error(response):
                    return response
            return response

        return self._command(apply_scene)

    def set_work_mode(self, mode: str) -> str:
        allowed = {"white", "colour", "scene", "music"}
        if mode not in allowed:
            raise ValueError(f"Unsupported DS22000 work mode: {mode}")
        return self._command(lambda bulb: bulb.set_value(21, mode, nowait=False))

    def status(self):
        with self._lock:
            if self._ensure_connected() != "connected":
                return None
            try:
                response = self.bulb.status()
                if response is None or self._is_error(response):
                    raise ConnectionError(str(response))
                return response
            except Exception as error:
                self._mark_failure(error)
                return None
