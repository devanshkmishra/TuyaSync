"""Bounded screen-to-light coordinator for a single-zone Tuya light."""

from __future__ import annotations

import threading
import time
from dataclasses import replace

from screensync.light_service import DesiredLightState, LightService
from screensync.screen_sync.ambient import ProcessingResult, RuntimeMetrics, ScreenProcessor, SyncSettings
from screensync.screen_sync.perceptual import adaptive_time_constant, distance, smooth as perceptual_smooth


class Coordinator:
    name = "screen"

    def __init__(self, bulbs, color_processing_module=None, settings: SyncSettings | None = None, light_service: LightService | None = None):
        self.bulbs = bulbs
        self.color_processing = color_processing_module
        self.settings = settings or SyncSettings()
        self.processor = ScreenProcessor(self.settings)
        self.metrics = light_service.metrics if light_service else RuntimeMetrics()
        self.light_service = light_service or LightService(bulbs, self.metrics, self.settings)
        self._owns_light_service = light_service is None
        self.running = False
        self.mode = "normal"
        self._settings_lock = threading.RLock()
        self._processing_thread: threading.Thread | None = None
        self._smoothed_rgb = (0.0, 0.0, 0.0)
        self._brightness = 0.0
        self._last_frame_at = time.monotonic()
        self._black_since: float | None = None
        self._off_sent = False
        self._white_mode = False
        self._neutral_since: float | None = None
        self._colourful_since: float | None = None
        self._last_raw_rgb = (0.0, 0.0, 0.0)
        self._last_output_target = (0, 0, 0)

    def set_mode(self, mode):
        self.mode = mode

    def get_settings(self) -> SyncSettings:
        with self._settings_lock:
            return replace(self.settings)

    def set_settings(self, settings: SyncSettings | None = None, **changes) -> None:
        with self._settings_lock:
            active = settings or replace(self.settings, **changes)
            self.settings = active
            self.processor.set_settings(active)
        self.light_service.configure(active)

    def update_bulbs(self, new_bulbs):
        was_running = self.running
        if was_running:
            self.stop()
        self.bulbs = new_bulbs
        self.light_service.update_bulbs(new_bulbs)
        if was_running:
            self.start()

    def start(self):
        if self.running:
            return
        if self._processing_thread and self._processing_thread.is_alive():
            raise RuntimeError("A previous Screen worker is still stopping")
        self.running = True
        self.light_service.configure(self.settings)
        if self._owns_light_service:
            self.light_service.start()
        self._processing_thread = threading.Thread(target=self.run_update_loop, name="ScreenProcessing", daemon=True)
        self._processing_thread.start()

    def stop(self):
        self.running = False
        self.clear_pending_output()
        worker = self._processing_thread
        if worker and worker is not threading.current_thread():
            worker.join(timeout=5)
            if worker.is_alive():
                raise RuntimeError("Screen processing worker did not stop")
        self._processing_thread = None
        if self._owns_light_service:
            self.light_service.stop()

    def is_running(self) -> bool:
        return self.running

    def clear_pending_output(self) -> None:
        self.light_service.clear()

    def reset_mode_state(self) -> None:
        self.clear_pending_output()
        self._smoothed_rgb = (0.0, 0.0, 0.0)
        self._brightness = 0.0
        self._black_since = None
        self._off_sent = False
        self._white_mode = False
        self._neutral_since = self._colourful_since = None
        self._last_raw_rgb = (0.0, 0.0, 0.0)
        self._last_output_target = (0, 0, 0)

    def update_bulb_color(self, bulb, color):
        return bulb.set_color(*color)

    @staticmethod
    def _smooth_rgb(previous, target, dt: float, time_constant: float):
        alpha = 1.0 if time_constant <= 0 else 1.0 - pow(2.718281828, -dt / time_constant)
        return tuple(previous[index] + (target[index] - previous[index]) * alpha for index in range(3))

    @staticmethod
    def _smooth_value(previous: float, target: float, dt: float, attack: float, release: float) -> float:
        time_constant = attack if target > previous else release
        alpha = 1.0 if time_constant <= 0 else 1.0 - pow(2.718281828, -dt / time_constant)
        return previous + (target - previous) * alpha

    @staticmethod
    def _white_temperature(rgb: tuple[int, int, int]) -> int:
        red, green, blue = (value / 255.0 for value in rgb)
        # Blue-heavy scenes are cooler; red-heavy scenes are warmer.
        return max(0, min(1000, int(500 + (blue - red) * 500)))

    def _output(self, result: ProcessingResult, settings: SyncSettings, dt: float) -> None:
        now = time.monotonic()
        raw = result.raw_rgb
        scene_change = distance(self._last_raw_rgb, raw)
        self._last_raw_rgb = raw
        smoothing = adaptive_time_constant(scene_change, settings.response_profile)
        self._smoothed_rgb = perceptual_smooth(self._smoothed_rgb, raw, dt, smoothing)

        if result.is_black:
            if self._black_since is None:
                self._black_since = now
            black_duration = now - self._black_since
        else:
            self._black_since = None
            black_duration = 0.0

        should_turn_off = (
            settings.turn_off_on_black
            and result.is_black
            and black_duration >= settings.black_off_delay
        )
        if should_turn_off:
            if not self._off_sent:
                self.light_service.publish(DesiredLightState(power=False, urgency=1.0))
                self._off_sent = True
            self._brightness = self._smooth_value(
                self._brightness, 0.0, dt, settings.brightness_attack, settings.brightness_release
            )
            self.metrics.record_output(tuple(map(int, self._smoothed_rgb)), (0, 0, 0), self._brightness)
            return

        ensure_on = self._off_sent
        self._off_sent = False

        peak = max(self._smoothed_rgb) / 255.0
        if result.is_black:
            target_brightness = settings.minimum_brightness / 100.0
        else:
            curved = pow(max(0.0, min(1.0, peak)), max(0.05, settings.brightness_gamma))
            target_brightness = (
                settings.minimum_brightness
                + (settings.maximum_brightness - settings.minimum_brightness) * curved
            ) / 100.0
        target_brightness = max(0.0, min(1.0, target_brightness))
        attack = min(settings.brightness_attack, 0.07) if scene_change > 0.30 else settings.brightness_attack
        release = min(settings.brightness_release, 0.12) if scene_change > 0.30 else settings.brightness_release
        self._brightness = self._smooth_value(
            self._brightness,
            target_brightness,
            dt,
            attack,
            release,
        )
        final = LightService._scale_rgb(self._smoothed_rgb, self._brightness)

        if not settings.use_dedicated_white or self._brightness <= 0:
            self._white_mode = False
            self._neutral_since = self._colourful_since = None
        elif self._white_mode:
            self._neutral_since = None
            if result.saturation >= settings.white_exit_saturation:
                self._colourful_since = self._colourful_since or now
                if now - self._colourful_since >= settings.white_exit_delay:
                    self._white_mode = False
                    self._colourful_since = None
            else:
                self._colourful_since = None
        else:
            self._colourful_since = None
            if result.saturation <= settings.white_enter_saturation:
                self._neutral_since = self._neutral_since or now
                if now - self._neutral_since >= settings.white_enter_delay:
                    self._white_mode = True
                    self._neutral_since = None
            else:
                self._neutral_since = None
        use_white = settings.use_dedicated_white and self._white_mode and self._brightness > 0
        output_change = distance(self._last_output_target, final)
        self._last_output_target = final
        urgency = max(scene_change, output_change)
        if use_white:
            self.light_service.publish(DesiredLightState(
                rgb=self._smoothed_rgb,
                brightness=self._brightness,
                white_temperature=self._white_temperature(final),
                ensure_on=ensure_on,
                urgency=urgency,
            ))
        else:
            self.light_service.publish(DesiredLightState(
                rgb=self._smoothed_rgb,
                brightness=self._brightness,
                ensure_on=ensure_on,
                urgency=urgency,
            ))

    def run_update_loop(self):
        self._last_frame_at = time.monotonic()
        while self.running:
            cycle_started = time.monotonic()
            try:
                settings = self.get_settings()
                processing_started = time.perf_counter()
                result = self.processor.process(settings)
                self.metrics.record_processing((time.perf_counter() - processing_started) * 1000)
                self.metrics.record_capture(result)
                now = time.monotonic()
                dt = max(0.001, now - self._last_frame_at)
                self._last_frame_at = now
                self._output(result, settings, dt)
            except Exception as error:
                self.metrics.record_processing_failure()
                print(f"TuyaSync update error: {error}", flush=True)
                time.sleep(0.25)

            settings = self.get_settings()
            interval = 1.0 / max(5.0, min(60.0, settings.capture_fps))
            remaining = interval - (time.monotonic() - cycle_started)
            if remaining > 0:
                time.sleep(remaining)

    def metrics_snapshot(self):
        snapshot = self.metrics.snapshot()
        snapshot["running"] = self.running
        return snapshot

    def device_info(self) -> dict[str, object]:
        bulb = self.bulbs[0] if self.bulbs else None
        info = {
            "ip": str(getattr(bulb, "ip", "—")),
            "protocol": str(getattr(bulb, "version", "—")),
            "device_id": str(getattr(bulb, "device_id", "—")),
            "state": "disconnected",
            "connected": False,
            "message": "No device configured" if bulb is None else "Not connected",
            "last_error": "",
            "failure_count": 0,
            "reconnect_count": 0,
            "retry_in": 0.0,
        }
        if bulb and hasattr(bulb, "connection_snapshot"):
            info.update(bulb.connection_snapshot())
        return info
