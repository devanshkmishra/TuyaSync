"""Low-resolution screen analysis, ambient-light settings, and runtime metrics."""

from __future__ import annotations

import colorsys
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, fields
from typing import Any

import mss
import numpy as np
from PIL import Image


ALGORITHMS = (
    "Legacy",
    "Saturated",
    "Edge",
    "Vibrant",
    "Saturated Average",
    "Edge Ambient",
    "Dominant",
    "Average",
    "Cinematic",
    "Intensity",
)


@dataclass
class SyncSettings:
    algorithm: str = "Saturated"
    monitor_index: int = 1
    capture_fps: float = 30.0
    update_rate: float = 10.0
    output_transport: str = "DP28"
    dp28_transition: str = "gradient"
    analysis_width: int = 96
    color_smoothing: float = 0.22
    responsiveness: float = 70.0
    response_profile: str = "Balanced"
    saturation_boost: float = 1.25
    color_deadband: float = 6.0
    minimum_brightness: float = 8.0
    maximum_brightness: float = 100.0
    brightness_gamma: float = 1.0
    black_scene_threshold: float = 12.0
    black_bar_threshold: float = 14.0
    ignore_black_bars: bool = True
    reduce_static_ui: bool = True
    static_ui_weight: float = 0.25
    white_background_weight: float = 0.18
    use_dedicated_white: bool = False
    white_enter_saturation: float = 0.10
    white_exit_saturation: float = 0.18
    white_enter_delay: float = 0.70
    white_exit_delay: float = 0.35
    turn_off_on_black: bool = False
    black_off_delay: float = 4.0
    brightness_attack: float = 0.12
    brightness_release: float = 0.40
    red_gain: float = 1.0
    green_gain: float = 1.0
    blue_gain: float = 1.0
    output_saturation: float = 1.0
    output_gamma: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "SyncSettings":
        allowed = {field.name for field in fields(cls)}
        clean = {key: value for key, value in values.items() if key in allowed}
        result = cls(**clean)
        if result.algorithm not in ALGORITHMS:
            result.algorithm = cls.algorithm
        result.analysis_width = 64 if int(result.analysis_width) <= 64 else 96
        return result


@dataclass
class ProcessingResult:
    raw_rgb: tuple[int, int, int]
    selected_region: tuple[int, int, int, int]
    source_size: tuple[int, int]
    analysis_size: tuple[int, int]
    is_black: bool
    saturation: float
    value: float


def _clip_rgb(rgb: np.ndarray | tuple[float, float, float]) -> tuple[int, int, int]:
    values = np.clip(np.asarray(rgb, dtype=float), 0, 255).astype(int)
    return int(values[0]), int(values[1]), int(values[2])


def _hsv_stats(pixels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    values = pixels.astype(np.float32) / 255.0
    maximum = values.max(axis=1)
    minimum = values.min(axis=1)
    saturation = np.divide(maximum - minimum, maximum, out=np.zeros_like(maximum), where=maximum > 0)
    return saturation, maximum


class ScreenProcessor:
    """Capture a monitor and immediately reduce it to a private analysis grid."""

    def __init__(self, settings: SyncSettings | None = None):
        self.settings = settings or SyncSettings()
        self._lock = threading.RLock()
        self._sct = mss.MSS()
        self._previous_frame: np.ndarray | None = None
        self._bar_candidate: tuple[int, int, int, int] | None = None
        self._bar_candidate_frames = 0
        self._confirmed_bars: tuple[int, int, int, int] | None = None

    @staticmethod
    def monitor_options() -> list[tuple[int, str]]:
        with mss.MSS() as sct:
            return [
                (index, f"Display {index} — {monitor['width']}×{monitor['height']}")
                for index, monitor in enumerate(sct.monitors[1:], start=1)
            ]

    def set_settings(self, settings: SyncSettings) -> None:
        with self._lock:
            if settings.monitor_index != self.settings.monitor_index or settings.analysis_width != self.settings.analysis_width:
                self._previous_frame = None
                self._bar_candidate = self._confirmed_bars = None
                self._bar_candidate_frames = 0
            self.settings = settings

    def _capture(self, monitor_index: int, analysis_width: int) -> tuple[np.ndarray, tuple[int, int]]:
        monitors = self._sct.monitors
        if len(monitors) <= 1 or monitors[1].get("width", 0) <= 0 or monitors[1].get("height", 0) <= 0:
            raise RuntimeError("No active display is available for screen capture")
        index = monitor_index if 0 < monitor_index < len(monitors) else 1
        shot = self._sct.grab(monitors[index])
        width = 64 if analysis_width <= 64 else 96
        height = 36 if width == 64 else 54
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        tiny = np.asarray(image.resize((width, height), Image.Resampling.BOX)).copy()
        return tiny, (shot.width, shot.height)

    @staticmethod
    def crop_black_bars(frame: np.ndarray, threshold: float) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        height, width = frame.shape[:2]
        if height < 10 or width < 10:
            return frame, (0, 0, width, height)
        gray = frame.mean(axis=2)
        row_dark = gray.mean(axis=1) <= threshold
        col_dark = gray.mean(axis=0) <= threshold
        top = next((i for i, dark in enumerate(row_dark) if not dark), height)
        bottom = next((i for i in range(height - 1, -1, -1) if not row_dark[i]), -1) + 1
        left = next((i for i, dark in enumerate(col_dark) if not dark), width)
        right = next((i for i in range(width - 1, -1, -1) if not col_dark[i]), -1) + 1
        top_size, bottom_size = top, height - bottom
        if top_size or bottom_size:
            balanced = top_size >= 2 and bottom_size >= 2 and abs(top_size - bottom_size) <= max(2, int(height * 0.05))
            uniform = (
                float(np.mean(gray[:top_size] <= threshold * 1.5)) >= 0.92
                and float(np.mean(gray[bottom:] <= threshold * 1.5)) >= 0.92
            ) if balanced else False
            if not uniform:
                top, bottom = 0, height
        left_size, right_size = left, width - right
        if left_size or right_size:
            balanced = left_size >= 2 and right_size >= 2 and abs(left_size - right_size) <= max(2, int(width * 0.05))
            uniform = (
                float(np.mean(gray[:, :left_size] <= threshold * 1.5)) >= 0.92
                and float(np.mean(gray[:, right:] <= threshold * 1.5)) >= 0.92
            ) if balanced else False
            if not uniform:
                left, right = 0, width
        if top == height or (bottom - top) < height * 0.55:
            top, bottom = 0, height
        if left == width or (right - left) < width * 0.55:
            left, right = 0, width
        return frame[top:bottom, left:right], (left, top, right, bottom)

    @staticmethod
    def _edge_values(region: np.ndarray, weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        height, width = region.shape[:2]
        band_y = max(1, int(height * 0.20))
        band_x = max(1, int(width * 0.20))
        pixels = np.concatenate((region[:band_y].reshape(-1, 3), region[-band_y:].reshape(-1, 3), region[:, :band_x].reshape(-1, 3), region[:, -band_x:].reshape(-1, 3)))
        selected_weights = np.concatenate((weights[:band_y].ravel(), weights[-band_y:].ravel(), weights[:, :band_x].ravel(), weights[:, -band_x:].ravel()))
        return pixels, selected_weights

    @staticmethod
    def _content_weights(region: np.ndarray, previous: np.ndarray | None, settings: SyncSettings, legacy: bool = False) -> np.ndarray:
        pixels = region.reshape(-1, 3).astype(np.float32)
        saturation, value = _hsv_stats(pixels)
        weights = np.ones(len(pixels), dtype=np.float32)
        bright_neutral = (saturation < 0.13) & (value > 0.72)
        white_fraction = float(np.mean(bright_neutral))
        mostly_white = float(np.clip((white_fraction - 0.35) / 0.40, 0.0, 1.0))
        neutral_weight = (
            settings.white_background_weight
            if legacy
            else settings.white_background_weight + (4.0 - settings.white_background_weight) * mostly_white
        )
        weights[bright_neutral] *= max(0.02, neutral_weight)
        if settings.reduce_static_ui and previous is not None and previous.shape == region.shape:
            delta = np.abs(region.astype(np.float32) - previous.astype(np.float32)).mean(axis=2).ravel() / 255.0
            motion = np.clip(delta / 0.10, 0.0, 1.0)
            weights *= settings.static_ui_weight + (1.0 - settings.static_ui_weight) * motion
        weights[value < 0.025] *= 0.08
        return weights.reshape(region.shape[:2])

    @staticmethod
    def _representative_rgb(region: np.ndarray, algorithm: str, content_weights: np.ndarray | None = None) -> tuple[int, int, int]:
        weights_2d = content_weights if content_weights is not None else np.ones(region.shape[:2], dtype=np.float32)
        height, width = region.shape[:2]
        if algorithm in {"Edge Ambient", "Edge"}:
            pixels, content = ScreenProcessor._edge_values(region, weights_2d)
        elif algorithm == "Cinematic":
            y1, y2 = int(height * 0.10), max(int(height * 0.90), 1)
            x1, x2 = int(width * 0.08), max(int(width * 0.92), 1)
            pixels = region[y1:y2, x1:x2].reshape(-1, 3)
            content = weights_2d[y1:y2, x1:x2].ravel()
        else:
            pixels = region.reshape(-1, 3)
            content = weights_2d.ravel()
        pixels = pixels.astype(np.float32)
        saturation, value = _hsv_stats(pixels)
        if algorithm == "Average":
            rgb = pixels.mean(axis=0)
        elif algorithm == "Intensity":
            rgb = np.average(pixels, axis=0, weights=content * (0.2 + value))
        elif algorithm in {"Dominant", "Vibrant"}:
            quantized = (pixels // 32) * 32 + 16
            colours, inverse = np.unique(quantized.astype(np.uint8), axis=0, return_inverse=True)
            totals = np.bincount(inverse, weights=content * (0.2 + saturation) * (0.25 + value), minlength=len(colours))
            rgb = colours[int(np.argmax(totals))]
        else:
            weights = content * (0.15 + np.power(saturation, 1.65)) * (0.25 + value)
            rgb = np.average(pixels, axis=0, weights=weights)
        return _clip_rgb(rgb)

    @staticmethod
    def _same_bars(first, second, tolerance: int = 2) -> bool:
        return all(abs(left - right) <= tolerance for left, right in zip(first, second))

    def _confirmed_bar_region(self, detected, full) -> tuple[int, int, int, int]:
        if detected == full:
            self._bar_candidate = self._confirmed_bars = None
            self._bar_candidate_frames = 0
            return full
        if self._bar_candidate and self._same_bars(self._bar_candidate, detected):
            self._bar_candidate_frames += 1
        else:
            self._bar_candidate = detected
            self._bar_candidate_frames = 1
        if self._bar_candidate_frames >= 5:
            self._confirmed_bars = detected
        return self._confirmed_bars or full

    @staticmethod
    def boost_saturation(rgb: tuple[int, int, int], boost: float) -> tuple[int, int, int]:
        red, green, blue = (value / 255.0 for value in rgb)
        hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
        red, green, blue = colorsys.hsv_to_rgb(hue, min(1.0, saturation * boost), value)
        return _clip_rgb((red * 255, green * 255, blue * 255))

    def process(self, settings: SyncSettings | None = None) -> ProcessingResult:
        with self._lock:
            active = settings or self.settings
        frame, source_size = self._capture(active.monitor_index, active.analysis_width)
        region = frame
        selected = (0, 0, frame.shape[1], frame.shape[0])
        if active.ignore_black_bars:
            _detected_region, detected = self.crop_black_bars(frame, active.black_bar_threshold)
            selected = self._confirmed_bar_region(detected, selected)
            left, top, right, bottom = selected
            region = frame[top:bottom, left:right]
        left, top, right, bottom = selected
        previous_region = None
        if self._previous_frame is not None and self._previous_frame.shape == frame.shape:
            previous_region = self._previous_frame[top:bottom, left:right]
        legacy = active.algorithm in {"Legacy", "Saturated Average"}
        content_weights = self._content_weights(region, previous_region, active, legacy=legacy)
        rgb = self.boost_saturation(self._representative_rgb(region, active.algorithm, content_weights), active.saturation_boost)
        self._previous_frame = frame
        red, green, blue = (value / 255.0 for value in rgb)
        _, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
        return ProcessingResult(
            raw_rgb=rgb,
            selected_region=selected,
            source_size=source_size,
            analysis_size=(frame.shape[1], frame.shape[0]),
            is_black=max(rgb) <= active.black_scene_threshold,
            saturation=saturation,
            value=value,
        )


class RuntimeMetrics:
    def __init__(self):
        self._lock = threading.RLock()
        self._capture_times: deque[float] = deque(maxlen=600)
        self._processing_times: deque[float] = deque(maxlen=600)
        self._command_times: deque[float] = deque(maxlen=300)
        self._latencies: deque[float] = deque(maxlen=100)
        self.capture_fps = self.processing_fps = self.lighting_hz = self.average_latency_ms = 0.0
        self.p95_latency_ms = 0.0
        self.deadband_skips = self.rate_limit_skips = self.overwritten_states = 0
        self.failed_commands = self.unavailable_commands = self.processing_failures = 0
        self.current_rgb = self.smoothed_rgb = self.final_rgb = self.raw_rgb = (0, 0, 0)
        self.final_brightness = self.actual_command_rate = 0.0
        self.selected_region = (0, 0, 0, 0)
        self.source_size = self.analysis_size = (0, 0)
        self.is_black = False

    @staticmethod
    def _rate(times: deque[float], now: float, window: float = 5.0) -> float:
        while times and now - times[0] > window:
            times.popleft()
        if len(times) < 2:
            return 0.0
        elapsed = max(0.001, times[-1] - times[0])
        return (len(times) - 1) / elapsed

    def record_capture(self, result: ProcessingResult) -> None:
        now = time.monotonic()
        with self._lock:
            self._capture_times.append(now)
            self.capture_fps = self._rate(self._capture_times, now)
            self.raw_rgb = self.current_rgb = result.raw_rgb
            self.selected_region = result.selected_region
            self.source_size = result.source_size
            self.analysis_size = result.analysis_size
            self.is_black = result.is_black

    def record_processing(self, duration_ms: float) -> None:
        now = time.monotonic()
        with self._lock:
            self._processing_times.append(now)
            self.processing_fps = self._rate(self._processing_times, now)

    def record_overwrite(self) -> None:
        with self._lock:
            self.overwritten_states += 1

    def record_processing_failure(self) -> None:
        with self._lock:
            self.processing_failures += 1

    def record_output(self, smoothed: tuple[int, int, int], final: tuple[int, int, int], brightness: float) -> None:
        with self._lock:
            self.smoothed_rgb, self.final_rgb, self.final_brightness = smoothed, final, brightness

    def record_command(self, outcome: str, latency_ms: float = 0.0) -> None:
        now = time.monotonic()
        with self._lock:
            if outcome == "sent":
                self._command_times.append(now)
                self._latencies.append(latency_ms)
                self.lighting_hz = self.actual_command_rate = self._rate(self._command_times, now)
                self.average_latency_ms = sum(self._latencies) / len(self._latencies)
                ordered = sorted(self._latencies)
                self.p95_latency_ms = ordered[min(len(ordered) - 1, round((len(ordered) - 1) * 0.95))]
            elif outcome == "skipped_deadband":
                self.deadband_skips += 1
            elif outcome == "skipped_rate_limit":
                self.rate_limit_skips += 1
            elif outcome == "failed":
                self.failed_commands += 1
            elif outcome == "unavailable":
                self.unavailable_commands += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "capture_fps": self.capture_fps, "processing_fps": self.processing_fps,
                "lighting_hz": self.lighting_hz, "actual_command_rate": self.actual_command_rate,
                "average_latency_ms": self.average_latency_ms, "p95_latency_ms": self.p95_latency_ms,
                "deadband_skips": self.deadband_skips, "rate_limit_skips": self.rate_limit_skips,
                "overwritten_states": self.overwritten_states, "failed_commands": self.failed_commands,
                "unavailable_commands": self.unavailable_commands, "processing_failures": self.processing_failures,
                "current_rgb": self.current_rgb, "raw_rgb": self.raw_rgb, "smoothed_rgb": self.smoothed_rgb,
                "final_rgb": self.final_rgb, "final_brightness": self.final_brightness,
                "selected_region": self.selected_region, "source_size": self.source_size,
                "analysis_size": self.analysis_size, "is_black": self.is_black,
            }
