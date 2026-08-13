"""Album-art mode using local player metadata and an optional beat-reactive palette."""

from __future__ import annotations

import hashlib
import threading
import urllib.request
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from screensync.audio.base import AudioFrame
from screensync.light_service import DesiredLightState, LightService
from screensync.modes.music import MusicAnalysis, MusicAnalyzer, MusicSettings, PaletteRuntime, interpolate_palette_colour, render_palette_response
from screensync.now_playing.base import NowPlaying
from screensync.screen_sync.perceptual import distance, smooth


@dataclass
class AlbumArtSettings:
    intensity: float = 0.78
    paused_intensity: float = 0.28
    palette_mode: str = "Single color"
    music_reactive: bool = False
    reactivity: float = 0.72
    beat_impact: float = 0.65
    minimum_brightness: float = 0.10
    maximum_brightness: float = 0.90
    colour_response: str = "Immediate flash"


def extract_art_palette(image_bytes: bytes, limit: int = 3) -> tuple[tuple[int, int, int], ...]:
    """Extract up to three separated, weighted colours from album artwork."""
    image = Image.open(BytesIO(image_bytes)).convert("RGB").resize((48, 48), Image.Resampling.BOX)
    pixels = np.asarray(image, dtype=np.uint8)
    flat = pixels.reshape(-1, 3).astype(np.float32)
    maximum = flat.max(axis=1)
    minimum = flat.min(axis=1)
    saturation = np.divide(maximum - minimum, maximum, out=np.zeros_like(maximum), where=maximum > 0)
    value = maximum / 255.0
    relevant = (value > 0.045) & ~((saturation < 0.08) & (value > 0.84))
    bins: dict[tuple[int, int, int], list[float]] = {}
    for pixel, pixel_saturation, pixel_value, keep in zip(flat, saturation, value, relevant):
        if not keep:
            continue
        key = tuple((pixel.astype(int) // 24).tolist())
        weight = float(0.35 + pixel_saturation * 1.15 + pixel_value * 0.20)
        bucket = bins.setdefault(key, [0.0, 0.0, 0.0, 0.0])
        bucket[0] += weight
        bucket[1:] = [bucket[index + 1] + float(pixel[index]) * weight for index in range(3)]

    candidates = []
    for weight, red, green, blue in bins.values():
        candidates.append((weight, (round(red / weight), round(green / weight), round(blue / weight))))
    candidates.sort(key=lambda item: item[0], reverse=True)
    selected: list[tuple[int, int, int]] = []
    for _weight, colour in candidates:
        if all(distance(colour, previous) >= 0.10 for previous in selected):
            selected.append(colour)
        if len(selected) >= max(1, min(3, int(limit))):
            break

    if not selected:
        # Neutral or almost-black covers still need a visible, usable result.
        if flat.size:
            average = np.mean(flat, axis=0)
            selected = [tuple(max(80, min(190, int(round(value)))) for value in average)]
        else:
            selected = [(128, 128, 128)]
    return tuple(selected)


def extract_art_colour(image_bytes: bytes) -> tuple[int, int, int]:
    """Backward-compatible single-colour album-art extraction."""
    return extract_art_palette(image_bytes, 1)[0]


class AlbumArtMode:
    name = "album_art"

    def __init__(
        self,
        light_service: LightService,
        backend,
        cache_dir: Path,
        settings: AlbumArtSettings | None = None,
        audio_backend=None,
    ):
        self.light_service = light_service
        self.backend = backend
        self.audio_backend = audio_backend
        self.cache_dir = cache_dir
        self.settings = settings or AlbumArtSettings()
        self.analyzer = MusicAnalyzer(self._music_settings())
        self._running = False
        self._lock = threading.RLock()
        self._current = NowPlaying(self.backend.name)
        self._colour = (128.0, 128.0, 128.0)
        self._palette: tuple[tuple[int, int, int], ...] = ((128, 128, 128),)
        self._palette_index = 0
        self._palette_position = 0.0
        self._beat_flash = 0.0
        self._beat_count = 0
        self._silence_since: float | None = None
        self._last_audio_at = 0.0
        self._last_audio_brightness = self.settings.intensity
        self._analysis = MusicAnalysis(0, 0, 0, 0, 0, 0, 0, 0)
        self._last_key = ""
        self._last_published_state: tuple[str, bool] | None = None
        self._last_error = ""
        self._cache_hits = 0
        self._cache_misses = 0
        self._last_rgb = (128, 128, 128)
        self._last_artwork: bytes | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        try:
            self.backend.start(self._on_now_playing)
            if self.settings.music_reactive:
                if self.audio_backend is None:
                    raise RuntimeError("Music-reactive Album Art needs system-audio capture")
                self.audio_backend.start(self._on_audio)
        except Exception:
            try:
                self.backend.stop()
            except Exception:
                pass
            if self.audio_backend is not None:
                try:
                    self.audio_backend.stop()
                except Exception:
                    pass
            self._running = False
            raise

    def stop(self) -> None:
        self._running = False
        if self.audio_backend is not None:
            self.audio_backend.stop()
        self.backend.stop()

    def is_running(self) -> bool:
        if not self._running or not self.backend.is_running():
            return False
        return not self.settings.music_reactive or (self.audio_backend is not None and self.audio_backend.is_running())

    def reset_mode_state(self) -> None:
        self._last_key = ""
        self._last_published_state = None
        self._last_error = ""
        self._palette_index = 0
        self._palette_position = 0.0
        self._beat_flash = 0.0
        self._beat_count = 0
        self._silence_since = None
        self._last_audio_at = 0.0
        self._analysis = MusicAnalysis(0, 0, 0, 0, 0, 0, 0, 0)
        self.analyzer.reset()

    def update_settings(self, settings: AlbumArtSettings) -> None:
        previous = self.settings
        self.settings = settings
        self.analyzer.settings = self._music_settings()
        if settings.palette_mode != previous.palette_mode and self._last_artwork:
            self._palette = self._palette_from_artwork(self._last_artwork)
            self._palette_index = 0
            self._palette_position = 0.0
            self._colour = tuple(map(float, self._palette[0]))
            self._silence_since = None
        if self._running and settings.music_reactive != previous.music_reactive:
            if settings.music_reactive:
                if self.audio_backend is None:
                    self._last_error = "Music-reactive Album Art needs system-audio capture"
                    self.settings = previous
                    self.analyzer.settings = self._music_settings()
                    return
                try:
                    self.audio_backend.start(self._on_audio)
                except Exception as error:
                    self._last_error = str(error)
                    self.settings = previous
                    self.analyzer.settings = self._music_settings()
            elif self.audio_backend is not None:
                self.audio_backend.stop()

    def _music_settings(self) -> MusicSettings:
        return MusicSettings(
            intensity=self.settings.intensity,
            reactivity=self.settings.reactivity,
            bass_impact=self.settings.beat_impact,
            minimum_brightness=self.settings.minimum_brightness,
            maximum_brightness=self.settings.maximum_brightness,
            silence_hold_seconds=4.0,
            colour_response=self.settings.colour_response,
        )

    def diagnostics(self) -> dict[str, object]:
        with self._lock:
            result = {
                **self.backend.status(),
                "title": self._current.title,
                "artist": self._current.artist,
                "album": self._current.album,
                "extracted_rgb": self._last_rgb,
                "extracted_palette": self._palette,
                "palette_mode": self.settings.palette_mode,
                "music_reactive": self.settings.music_reactive,
                "colour_response": self.settings.colour_response,
                "reactivity": self.settings.reactivity,
                "minimum_brightness": self.settings.minimum_brightness,
                "maximum_brightness": self.settings.maximum_brightness,
                "current_rgb": tuple(round(value) for value in self._colour),
                "palette_index": self._palette_index,
                "palette_position": self._palette_position,
                "beat_count": self._beat_count,
                "beat": self._analysis.beat,
                "colour_driver": (
                    "instant artwork palette step on beat + brightness pulse"
                    if self.settings.colour_response == "Immediate flash"
                    else "smooth artwork palette step on beat + brightness pulse"
                ),
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
                "error": self._last_error,
            }
            if self.audio_backend is not None:
                result["audio"] = self.audio_backend.status()
            return result

    def artwork(self) -> bytes | None:
        with self._lock:
            return self._last_artwork

    def current(self) -> NowPlaying:
        with self._lock:
            return self._current

    def _on_now_playing(self, current: NowPlaying) -> None:
        if not self._running:
            return
        with self._lock:
            previous = self._current
            self._current = current
        key = current.track_id_or_stable_key or current.title
        state_changed = (key, current.is_playing) != self._last_published_state
        if key != self._last_key:
            self._last_key = key
            self.analyzer.reset()
            self._palette_index = 0
            self._palette_position = 0.0
            self._beat_flash = 0.0
            self._beat_count = 0
            self._silence_since = None
            if current.artwork_url:
                try:
                    self._palette = self._colour_for(current)
                except Exception as error:
                    self._last_error = str(error)
                    self._palette = (self._last_rgb,)
            else:
                self._palette = (self._last_rgb,)
            self._last_rgb = self._palette[0]
            self._colour = smooth(self._colour, self._last_rgb, 1.0, 0.7)
        brightness = (
            min(self.settings.intensity, self.settings.maximum_brightness)
            if current.is_playing
            else self.settings.paused_intensity
        )
        if not current.has_track:
            return
        if not state_changed:
            return
        self._last_published_state = (key, current.is_playing)
        self.light_service.publish(DesiredLightState(
            rgb=self._colour,
            brightness=brightness,
            urgency=distance(self._colour, self._last_rgb) + (0.18 if key != previous.track_id_or_stable_key else 0.0),
        ))

    def _on_audio(self, frame: AudioFrame) -> None:
        if not self._running or not self.settings.music_reactive:
            return
        try:
            with self._lock:
                if not self._current.has_track or not self._current.is_playing:
                    return
                analysis = self.analyzer.analyze(frame)
                now = float(frame.timestamp)
                if now <= self._last_audio_at:
                    now = self._last_audio_at + len(frame.samples) / max(1, frame.sample_rate)
                dt = max(0.001, now - self._last_audio_at) if self._last_audio_at else 0.04
                self._last_audio_at = now
                settings = self.analyzer.settings
                response = render_palette_response(
                    settings,
                    self.analyzer,
                    PaletteRuntime(
                        self._colour,
                        self._palette_index,
                        self._palette_position,
                        self._beat_flash,
                        self._beat_count,
                        self._silence_since,
                    ),
                    self._palette,
                    analysis,
                    dt,
                    now,
                )
                self._colour = response.runtime.colour
                self._palette_index = response.runtime.palette_index
                self._palette_position = response.runtime.palette_position
                self._beat_flash = response.runtime.beat_flash
                self._beat_count = response.runtime.beat_count
                self._silence_since = response.runtime.silence_since
                self._last_audio_brightness = response.brightness
                self._analysis = replace(analysis, palette_position=self._palette_position, brightness=response.brightness)
                state = DesiredLightState(
                    rgb=self._colour,
                    brightness=response.brightness,
                    urgency=response.urgency,
                )
            self.light_service.publish(state)
        except Exception as error:
            self._last_error = str(error)

    def _palette_from_artwork(self, data: bytes) -> tuple[tuple[int, int, int], ...]:
        limit = {"Single color": 1, "Two colors": 2, "Three colors": 3}.get(self.settings.palette_mode, 1)
        return extract_art_palette(data, limit)

    def _palette_colour(self, position: float) -> tuple[float, float, float]:
        return interpolate_palette_colour(self._palette, position)

    def _colour_for(self, current: NowPlaying) -> tuple[tuple[int, int, int], ...]:
        digest = hashlib.sha256(current.track_id_or_stable_key.encode()).hexdigest()[:24]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{digest}.img"
        if path.exists():
            data = path.read_bytes()
            self._cache_hits += 1
        else:
            if not current.artwork_url:
                return (self._last_rgb,)
            with urllib.request.urlopen(current.artwork_url, timeout=8) as response:
                data = response.read()
            path.write_bytes(data)
            self._cache_misses += 1
        self._last_artwork = data
        return self._palette_from_artwork(data)
