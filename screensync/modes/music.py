"""Adaptive, palette-based system-audio lighting mode."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import asdict, dataclass, replace

import numpy as np

from screensync.audio.base import AudioFrame
from screensync.light_service import DesiredLightState, LightService
from screensync.screen_sync.perceptual import distance, oklab_to_rgb, rgb_to_oklab, smooth


PALETTES = {
    "Full Spectrum": ((255, 25, 45), (255, 175, 20), (35, 225, 95), (20, 180, 255), (125, 55, 255), (255, 35, 185)),
    "Vaporwave": ((255, 35, 165), (142, 45, 255), (38, 215, 255), (95, 35, 210)),
    "Aurora": ((5, 95, 105), (15, 210, 125), (30, 225, 225), (125, 75, 235)),
    "Sunset": ((255, 170, 35), (255, 90, 35), (245, 65, 105), (150, 35, 180)),
    "Cyberpunk": ((15, 50, 225), (130, 35, 255), (255, 25, 155), (25, 210, 255)),
}
DEFAULT_PALETTE = "Full Spectrum"


@dataclass
class MusicSettings:
    palette: str = DEFAULT_PALETTE
    colour_response: str = "Immediate flash"
    intensity: float = 0.85
    reactivity: float = 0.65
    # Kept under the old serialized name so existing preferences continue to
    # load.  In the UI and runtime this is the strength of the beat pulse.
    bass_impact: float = 0.45
    minimum_brightness: float = 0.12
    maximum_brightness: float = 0.90
    silence_hold_seconds: float = 4.0


@dataclass(frozen=True)
class MusicAnalysis:
    rms: float
    normalized_energy: float
    bass: float
    mid: float
    treble: float
    onset: float
    palette_position: float
    brightness: float
    beat: bool = False
    beat_strength: float = 0.0
    beat_index: int = 0


def palette_colour(name: str, position: float) -> tuple[float, float, float]:
    colours = PALETTES.get(name, PALETTES[DEFAULT_PALETTE])
    return interpolate_palette_colour(colours, position)


def interpolate_palette_colour(colours, position: float) -> tuple[float, float, float]:
    if len(colours) == 1:
        return tuple(map(float, colours[0]))
    scaled = max(0.0, min(1.0, position)) * (len(colours) - 1)
    index = min(len(colours) - 2, int(scaled))
    amount = scaled - index
    left, right = rgb_to_oklab(colours[index]), rgb_to_oklab(colours[index + 1])
    return oklab_to_rgb(tuple(a + (b - a) * amount for a, b in zip(left, right)))


class MusicAnalyzer:
    def __init__(self, settings: MusicSettings | None = None):
        self.settings = settings or MusicSettings()
        self.noise_floor = 0.0005
        self.peak = 0.02
        self._peak_at = float("-inf")
        self.previous_energy = 0.0
        self.previous_normalized = 0.0
        self.smoothed_energy = 0.0
        self._clock = 0.0
        self._last_beat_at = float("-inf")
        self.beat_index = 0

    def reset(self) -> None:
        self.noise_floor = 0.0005
        self.peak = 0.02
        self._peak_at = float("-inf")
        self.previous_energy = 0.0
        self.previous_normalized = 0.0
        self.smoothed_energy = 0.0
        self._clock = 0.0
        self._last_beat_at = float("-inf")
        self.beat_index = 0

    def _frame_time(self, frame: AudioFrame, sample_count: int) -> float:
        """Return a monotonic analysis clock, including for synthetic frames."""
        duration = sample_count / max(1, frame.sample_rate)
        timestamp = float(frame.timestamp)
        if timestamp > self._clock:
            self._clock = timestamp
        else:
            self._clock += duration
        return self._clock

    def brightness_for(self, normalized_energy: float, beat_strength: float = 0.0) -> float:
        minimum = min(self.settings.minimum_brightness, self.settings.maximum_brightness)
        maximum = max(self.settings.minimum_brightness, self.settings.maximum_brightness)
        ceiling = max(minimum, min(maximum, maximum * self.settings.intensity))
        energy = float(np.clip(normalized_energy, 0.0, 1.0))
        span = ceiling - minimum
        # Keep the continuous music level deliberately restrained. The beat
        # is the event that should make the room noticeably brighter, rather
        # than a small additive nudge on top of an already-bright baseline.
        resting = minimum + span * 0.42 * energy ** 1.35
        pulse_fraction = float(np.clip(beat_strength, 0.0, 1.0))
        # Audio onsets are often detected at partial strength even when they
        # are musically obvious. Boost the event so a normal beat still
        # reaches the bright end of the range instead of looking like a tiny
        # volume adjustment.
        pulse_fraction *= max(0.0, self.settings.bass_impact) * 2.60
        return float(np.clip(resting + (ceiling - resting) * min(1.0, pulse_fraction), minimum, ceiling))

    def analyze(self, frame: AudioFrame) -> MusicAnalysis:
        samples = np.asarray(frame.samples, dtype=np.float32)
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        if samples.size < 16:
            samples = np.pad(samples, (0, 16 - samples.size))
        samples = np.nan_to_num(samples, copy=False)
        now = self._frame_time(frame, samples.size)
        duration = samples.size / max(1, frame.sample_rate)
        rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
        self.noise_floor += (0.08 if rms < self.noise_floor else 0.0008) * (rms - self.noise_floor)
        if rms >= self.peak:
            self.peak = rms
            self._peak_at = now
        elif now - self._peak_at >= 0.35:
            # Hold a recent loud transient long enough for the following
            # quieter frame to establish an onset. A fast-decaying peak can
            # normalize a sustained loud song to 100%, erasing later beats.
            self.peak = max(rms, self.peak * math.exp(-duration / 4.0))
        span = max(0.004, self.peak - self.noise_floor)
        normalized = float(np.clip((rms - self.noise_floor) / span, 0.0, 1.0))
        normalized = math.sqrt(normalized)
        attack = 0.78 + self.settings.reactivity * 0.18
        release = 0.20 + self.settings.reactivity * 0.15
        alpha = attack if normalized > self.smoothed_energy else release
        self.smoothed_energy += alpha * (normalized - self.smoothed_energy)
        raw_rise = max(0.0, normalized - self.previous_normalized)
        smoothed_rise = max(0.0, self.smoothed_energy - self.previous_energy)
        onset = max(raw_rise, smoothed_rise)
        self.previous_normalized = normalized
        self.previous_energy = self.smoothed_energy

        # Beat detection intentionally uses only the full-band energy envelope.
        # The refractory period prevents one sustained hit from retriggering,
        # while the short gate keeps legitimate fast beats visible.
        threshold = max(0.045, 0.10 - self.smoothed_energy * 0.03)
        beat = (
            raw_rise >= threshold
            and normalized >= 0.10
            and now - self._last_beat_at >= 0.12
        )
        beat_strength = float(np.clip(raw_rise / 0.22, 0.0, 1.0)) if beat else 0.0
        if beat:
            self._last_beat_at = now
            self.beat_index += 1

        brightness = self.brightness_for(self.smoothed_energy, beat_strength)
        return MusicAnalysis(
            rms,
            self.smoothed_energy,
            0.0,
            0.0,
            0.0,
            onset,
            0.0,
            brightness,
            beat,
            beat_strength,
            self.beat_index,
        )


@dataclass(frozen=True)
class PaletteRuntime:
    colour: tuple[float, float, float]
    palette_index: int = 0
    palette_position: float = 0.0
    beat_flash: float = 0.0
    beat_count: int = 0
    silence_since: float | None = None


@dataclass(frozen=True)
class PaletteResponse:
    runtime: PaletteRuntime
    target: tuple[float, float, float]
    brightness: float
    urgency: float


def render_palette_response(
    settings: MusicSettings,
    analyzer: MusicAnalyzer,
    runtime: PaletteRuntime,
    palette,
    analysis: MusicAnalysis,
    dt: float,
    now: float,
) -> PaletteResponse:
    """Render one beat-reactive frame for either Music or Album Art mode."""
    palette = tuple(palette) or ((128, 128, 128),)
    colour = runtime.colour
    palette_index = runtime.palette_index
    palette_position = runtime.palette_position
    beat_flash = runtime.beat_flash
    beat_count = runtime.beat_count
    silence_since = runtime.silence_since

    if analysis.beat:
        beat_count += 1
        beat_flash = max(beat_flash, analysis.beat_strength)

    energy = analysis.normalized_energy
    if energy > 0.02:
        speed = (0.025 + 0.18 * energy) * (0.35 + 0.65 * settings.reactivity)
        palette_position = (palette_position + dt * speed) % 1.0

    if analysis.beat and len(palette) > 1:
        palette_index = (palette_index + 1) % len(palette)
        palette_position = palette_index / max(1, len(palette) - 1)
        target = tuple(map(float, palette[palette_index]))
        if settings.colour_response == "Immediate flash":
            colour = target
        else:
            time_constant = 0.12 + (1.0 - settings.reactivity) * 0.12
            colour = smooth(colour, target, dt, time_constant)
    else:
        scaled_position = palette_position * (len(palette) - 1)
        palette_index = min(len(palette) - 1, int(scaled_position))
        target = interpolate_palette_colour(palette, palette_position)
        time_constant = 0.045 + (1.0 - settings.reactivity) * 0.14
        colour = smooth(colour, target, dt, time_constant)

    beat_flash *= math.exp(-dt / (0.24 + (1.0 - settings.reactivity) * 0.10))
    if analysis.rms < max(0.0008, analyzer.noise_floor * 1.2):
        silence_since = silence_since or now
    else:
        silence_since = None
    brightness = analyzer.brightness_for(analysis.normalized_energy, beat_flash)
    if silence_since and now - silence_since >= settings.silence_hold_seconds:
        brightness = settings.minimum_brightness
    urgency = max(0.70 if analysis.beat else 0.0, distance(colour, target))
    return PaletteResponse(
        PaletteRuntime(colour, palette_index, palette_position, beat_flash, beat_count, silence_since),
        target,
        brightness,
        urgency,
    )


class MusicMode:
    name = "music"

    def __init__(self, light_service: LightService, backend, settings: MusicSettings | None = None):
        self.light_service = light_service
        self.backend = backend
        self.settings = settings or MusicSettings()
        self.analyzer = MusicAnalyzer(self.settings)
        self._lock = threading.RLock()
        self._running = False
        self._last_colour = tuple(map(float, PALETTES.get(self.settings.palette, PALETTES[DEFAULT_PALETTE])[0]))
        self._last_frame_at = time.monotonic()
        self._last_analysis = MusicAnalysis(0, 0, 0, 0, 0, 0, 0, self.settings.minimum_brightness)
        self._silence_since: float | None = None
        self._error = ""
        self._palette_index = 0
        self._palette_position = 0.0
        self._beat_flash = 0.0
        self._beat_count = 0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        try:
            self.backend.start(self._on_audio)
        except Exception:
            self._running = False
            raise

    def stop(self) -> None:
        self._running = False
        self.backend.stop()

    def is_running(self) -> bool:
        return self._running and self.backend.is_running()

    def reset_mode_state(self) -> None:
        self.analyzer.reset()
        self._last_colour = tuple(map(float, PALETTES.get(self.settings.palette, PALETTES[DEFAULT_PALETTE])[0]))
        self._last_frame_at = time.monotonic()
        self._silence_since = None
        self._error = ""
        self._palette_index = 0
        self._palette_position = 0.0
        self._beat_flash = 0.0
        self._beat_count = 0

    def update_settings(self, settings: MusicSettings) -> None:
        with self._lock:
            palette_changed = settings.palette != self.settings.palette
            self.settings = settings
            self.analyzer.settings = settings
            if palette_changed:
                self._palette_position = 0.0
                self._palette_index = 0
                self._last_colour = tuple(map(float, PALETTES.get(settings.palette, PALETTES[DEFAULT_PALETTE])[0]))

    def diagnostics(self) -> dict[str, object]:
        with self._lock:
            return {
                **self.backend.status(),
                **asdict(self._last_analysis),
                "beat_count": self._beat_count,
                "palette_index": self._palette_index,
                "palette_position": self._palette_position,
                "colour_driver": (
                    "instant palette step on beat + continuous drift + brightness pulse"
                    if self.settings.colour_response == "Immediate flash"
                    else "smooth palette step on beat + continuous drift + brightness pulse"
                ),
                "error": self._error,
            }

    def _on_audio(self, frame: AudioFrame) -> None:
        if not self._running:
            return
        try:
            with self._lock:
                analysis = self.analyzer.analyze(frame)
                now = frame.timestamp
                dt = max(0.001, now - self._last_frame_at)
                self._last_frame_at = now
                palette = PALETTES.get(self.settings.palette, PALETTES[DEFAULT_PALETTE])
                response = render_palette_response(
                    self.settings,
                    self.analyzer,
                    PaletteRuntime(
                        self._last_colour,
                        self._palette_index,
                        self._palette_position,
                        self._beat_flash,
                        self._beat_count,
                        self._silence_since,
                    ),
                    palette,
                    analysis,
                    dt,
                    now,
                )
                self._last_colour = response.runtime.colour
                self._palette_index = response.runtime.palette_index
                self._palette_position = response.runtime.palette_position
                self._beat_flash = response.runtime.beat_flash
                self._beat_count = response.runtime.beat_count
                self._silence_since = response.runtime.silence_since
                self._last_analysis = replace(analysis, palette_position=self._palette_position, brightness=response.brightness)
            self.light_service.publish(DesiredLightState(
                rgb=self._last_colour,
                brightness=response.brightness,
                urgency=response.urgency,
            ))
        except Exception as error:
            self._error = str(error)
