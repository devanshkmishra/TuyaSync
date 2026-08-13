"""Shared latest-value output and serialized access to the physical light."""

from __future__ import annotations

import colorsys
import threading
import time
from dataclasses import dataclass, replace

from screensync.screen_sync.ambient import RuntimeMetrics, SyncSettings


@dataclass(frozen=True)
class DesiredLightState:
    rgb: tuple[float, float, float] | None = None
    brightness: float = 1.0
    white_temperature: int | None = None
    power: bool | None = None
    ensure_on: bool = False
    urgency: float = 0.0


class LightService:
    def __init__(self, bulbs, metrics: RuntimeMetrics | None = None, settings: SyncSettings | None = None):
        self.bulbs = bulbs
        self.metrics = metrics or RuntimeMetrics()
        self._settings = settings or SyncSettings()
        self._settings_lock = threading.RLock()
        self._condition = threading.Condition()
        self._send_lock = threading.RLock()
        self._pending: DesiredLightState | None = None
        self._worker: threading.Thread | None = None
        self._running = False
        self._last_send_at = 0.0

    def configure(self, settings: SyncSettings) -> None:
        with self._settings_lock:
            self._settings = replace(settings)
        for bulb in self.bulbs:
            if hasattr(bulb, "set_update_rate"):
                bulb.set_update_rate(settings.update_rate)
            if hasattr(bulb, "set_color_deadband"):
                bulb.set_color_deadband(settings.color_deadband)
            if hasattr(bulb, "set_transport"):
                bulb.set_transport(settings.output_transport, settings.dp28_transition)

    def update_bulbs(self, bulbs) -> None:
        with self._send_lock:
            self.clear()
            self.bulbs = bulbs
            self.configure(self._get_settings())

    def start(self) -> None:
        if self._running:
            return
        if self._worker and self._worker.is_alive():
            raise RuntimeError("The previous light-output worker is still stopping")
        self.configure(self._settings)
        self._running = True
        self._worker = threading.Thread(target=self._run, name="LightOutput", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._running = False
        self.clear()
        worker = self._worker
        if worker and worker is not threading.current_thread():
            worker.join(timeout=5)
            if worker.is_alive():
                raise RuntimeError("The light-output worker did not stop")
        self._worker = None

    def is_running(self) -> bool:
        return self._running

    def clear(self) -> None:
        with self._condition:
            self._pending = None
            self._condition.notify_all()

    def publish(self, state: DesiredLightState) -> None:
        if not self._running:
            raise RuntimeError("LightService is not running")
        with self._condition:
            if self._pending is not None:
                self.metrics.record_overwrite()
                state = replace(state, urgency=max(state.urgency, self._pending.urgency))
            self._pending = state
            self._condition.notify()

    def execute(self, method: str, *args) -> list[str]:
        """Run a non-realtime command without competing with the output worker."""
        self.clear()
        with self._send_lock:
            return [self._send(bulb, method, *args) for bulb in self.bulbs]

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: not self._running or self._pending is not None)
                if not self._running:
                    return
                while self._running:
                    state = self._pending
                    if state is None:
                        break
                    due = self._last_send_at + 1.0 / self._target_hz(state)
                    remaining = due - time.monotonic()
                    if remaining <= 0:
                        self._pending = None
                        break
                    self._condition.wait(timeout=remaining)
                if not self._running:
                    return
            if state is None:
                continue
            with self._send_lock:
                self._transmit(state)
            self._last_send_at = time.monotonic()

    def _transmit(self, state: DesiredLightState) -> None:
        if state.power is not None:
            method = "turn_on" if state.power else "turn_off"
            for bulb in self.bulbs:
                self._send(bulb, method)
            return
        if state.rgb is None and state.white_temperature is None:
            return
        brightness = max(0.0, min(1.0, state.brightness))
        if state.white_temperature is None:
            final = self._calibrate(self._scale_rgb(state.rgb, brightness), self._get_settings())
            self.metrics.record_output(tuple(map(int, state.rgb)), final, brightness)
            method, args = "set_color", final
        else:
            final = self._scale_rgb(state.rgb or (255, 255, 255), brightness)
            self.metrics.record_output(tuple(map(int, state.rgb or (255, 255, 255))), final, brightness)
            method = "set_white"
            args = (int(round(brightness * 1000)), max(0, min(1000, int(state.white_temperature))))
        for bulb in self.bulbs:
            if state.ensure_on:
                self._send(bulb, "turn_on")
            if method == "set_white" and not hasattr(bulb, "set_white"):
                continue
            self._send(bulb, method, *args)

    def _get_settings(self) -> SyncSettings:
        with self._settings_lock:
            return replace(self._settings)

    def _target_hz(self, state: DesiredLightState) -> float:
        maximum = max(1.0, min(15.0, self._get_settings().update_rate))
        if state.power is not None or state.urgency >= 0.24:
            return maximum
        if state.urgency >= 0.08:
            return min(maximum, 8.0)
        if state.urgency >= 0.025:
            return min(maximum, 5.0)
        return min(maximum, 3.0)

    def _send(self, bulb, method: str, *args) -> str:
        started = time.monotonic()
        try:
            outcome = getattr(bulb, method)(*args) or "sent"
            self.metrics.record_command(outcome, (time.monotonic() - started) * 1000)
            return outcome
        except Exception as error:
            self.metrics.record_command("failed")
            print(f"TuyaSync command error: {error}", flush=True)
            return "failed"

    @staticmethod
    def _scale_rgb(rgb, brightness: float) -> tuple[int, int, int]:
        peak = max(rgb)
        if peak <= 0 or brightness <= 0:
            return (0, 0, 0)
        scale = brightness * 255.0 / peak
        return tuple(max(0, min(255, int(round(value * scale)))) for value in rgb)

    @staticmethod
    def _calibrate(rgb: tuple[int, int, int], settings: SyncSettings) -> tuple[int, int, int]:
        red, green, blue = (max(0.0, min(1.0, value / 255.0)) for value in rgb)
        hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
        saturation = max(0.0, min(1.0, saturation * settings.output_saturation))
        value = value ** max(0.05, settings.output_gamma)
        channels = colorsys.hsv_to_rgb(hue, saturation, value)
        gains = (settings.red_gain, settings.green_gain, settings.blue_gain)
        return tuple(max(0, min(255, round(channel * gain * 255))) for channel, gain in zip(channels, gains))
