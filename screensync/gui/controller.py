"""The bridge between the interface and TuyaSync's lighting engine.

Widgets never talk to the coordinator, modes, or profile store directly; they
call this controller and listen to its signals.  That keeps every behaviour of
the engine in one place and lets the interface be rebuilt without touching it.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, fields, replace
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from screensync.light_profiles import LightProfile, LightProfileStore, ProfileStoreError
from screensync.light_service import LightService
from screensync.modes.album_art import AlbumArtMode, AlbumArtSettings
from screensync.modes.manager import ModeManager, ModeTransitionError
from screensync.modes.music import MusicMode, MusicSettings
from screensync.modes.scenes import ScenesMode
from screensync.scenes import BUILTIN_SCENES, ScenePreset, save_custom_scenes
from screensync.screen_sync.ambient import ScreenProcessor, SyncSettings
from screensync.screen_sync.bulb_factory import BulbFactory
from screensync.screen_sync.config_manager import ConfigManager
from screensync.screen_sync.coordinator import Coordinator


MODE_LABELS = {"off": "Manual", "screen": "Screen", "music": "Music", "album_art": "Album Art", "scenes": "Scenes"}

ALGORITHM_GUIDE = {
    "Saturated": ("Recommended", "Favours colourful scene content and down-weights grey UI, subtitles, and isolated white pixels. The best starting point for movies, games, and desktop use."),
    "Edge": ("Outer edges", "Reads mostly the outer part of the display, so centred text and app windows matter less. Feels the most like cinematic bias lighting."),
    "Vibrant": ("Dominant colour", "Picks one strong colour instead of averaging everything. Punchy for animation and colourful games; less faithful on mixed scenes."),
    "Legacy": ("Classic", "The original weighted average. Calm and familiar, but less vivid on mixed scenes."),
}
RESPONSE_GUIDE = {
    "Responsive": ("Fast", "Short transitions that follow cuts and movement closely."),
    "Balanced": ("Recommended", "Smooths small changes but speeds up on big scene cuts. The best everyday compromise."),
    "Cinematic": ("Smooth", "Long, blended transitions for films and slow content where instant changes feel distracting."),
}
PRIMARY_ALGORITHMS = tuple(ALGORITHM_GUIDE)
COLOUR_RESPONSES = ("Immediate flash", "Smooth blend")
ALBUM_PALETTES = ("Single color", "Two colors", "Three colors")


def _known(cls, values: dict) -> dict:
    allowed = {field.name for field in fields(cls)}
    return {key: value for key, value in values.items() if key in allowed}


class AppController(QObject):
    modeChanged = Signal(str)
    notice = Signal(str, str)  # message, level: info | success | error
    tick = Signal(dict, dict)  # metrics snapshot, device info
    profilesChanged = Signal()
    scenesChanged = Signal()
    sceneSelected = Signal(str)
    screenSettingsChanged = Signal()
    manualResult = Signal(bool, str)
    busyChanged = Signal(bool)

    def __init__(
        self,
        coordinator: Coordinator,
        mode_manager: ModeManager,
        music_mode: MusicMode | None = None,
        album_art_mode: AlbumArtMode | None = None,
        scenes_mode: ScenesMode | None = None,
        scenes: list[ScenePreset] | None = None,
        profile_store: LightProfileStore | None = None,
        config_manager: ConfigManager | None = None,
        bulb_factory: BulbFactory | None = None,
        settings_path: Path | None = None,
        preferences_path: Path | None = None,
        scenes_path: Path | None = None,
        startup_error: str | None = None,
        monitor_options: list[tuple[int, str]] | None = None,
    ):
        super().__init__()
        self.coordinator = coordinator
        self.mode_manager = mode_manager
        self.music_mode = music_mode
        self.album_art_mode = album_art_mode
        self.scenes_mode = scenes_mode
        self.scenes: list[ScenePreset] = list(scenes or BUILTIN_SCENES)
        self.profile_store = profile_store
        self.config_manager = config_manager
        self.bulb_factory = bulb_factory
        self.settings_path = settings_path
        self.preferences_path = preferences_path
        self.scenes_path = scenes_path
        self.startup_error = startup_error
        if monitor_options is None:
            try:
                monitor_options = ScreenProcessor.monitor_options()
            except Exception:
                monitor_options = []
        self.monitor_options = monitor_options or [(1, "Display 1")]

        settings = coordinator.get_settings()
        if settings.algorithm not in PRIMARY_ALGORITHMS:
            settings = replace(settings, algorithm="Legacy" if settings.algorithm == "Saturated Average" else "Saturated")
            coordinator.set_settings(settings)
        self.screen = settings

        self.scene_name = self.scenes[0].name if self.scenes else ""
        self.scene_brightness = 100.0
        self.manual_rgb = (255, 255, 255)
        self.manual_brightness = 100.0
        self.manual_temperature = 500.0
        self._load_preferences()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(700)
        self._save_timer.timeout.connect(self.save_now)
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self.poll)

    # ------------------------------------------------------------------ state

    @property
    def active_mode(self) -> str:
        return self.mode_manager.active_mode

    def mode_available(self, name: str) -> bool:
        return {
            "off": True,
            "screen": True,
            "music": self.music_mode is not None,
            "album_art": self.album_art_mode is not None,
            "scenes": self.scenes_mode is not None,
        }.get(name, False)

    def has_light(self) -> bool:
        return bool(self.coordinator.bulbs)

    def device_info(self) -> dict:
        return self.coordinator.device_info()

    def start_polling(self) -> None:
        self._poll.start()

    def poll(self) -> None:
        self.tick.emit(self.coordinator.metrics_snapshot(), self.coordinator.device_info())

    # ------------------------------------------------------------------ modes

    def switch_mode(self, name: str, scene_override: ScenePreset | None = None) -> bool:
        if name != "off" and not self.has_light():
            self.notice.emit("Add a light first. Open Settings → Light to connect one.", "error")
            return False
        if name == "music":
            self._apply_music()
        elif name == "album_art":
            self._apply_album_art()
        elif name == "scenes":
            scene = scene_override or self.selected_scene()
            if scene is None:
                self.notice.emit("Choose a scene first.", "error")
                return False
            if self.scenes_mode:
                self.scenes_mode.set_scene(scene, self._scene_slot(scene))
                self.scenes_mode.set_max_brightness(self.scene_brightness * 10)
                if self.active_mode == "scenes":
                    return self._reapply_scene(scene)
        elif name == "screen":
            self.coordinator.set_settings(self.screen)
        try:
            self.mode_manager.switch_to(name)
        except ModeTransitionError as error:
            self.notice.emit(str(error), "error")
            self.modeChanged.emit(self.active_mode)
            return False
        self.modeChanged.emit(self.active_mode)
        return True

    def stop(self) -> None:
        self.switch_mode("off")

    def toggle_mode(self, name: str) -> None:
        self.switch_mode("off" if self.active_mode == name else name)

    # ----------------------------------------------------------- screen sync

    def update_screen(self, **changes) -> None:
        settings = replace(self.screen, **changes)
        settings = replace(
            settings,
            capture_fps=max(15.0, float(settings.update_rate) * 3),
            maximum_brightness=max(float(settings.minimum_brightness), float(settings.maximum_brightness)),
        )
        self.screen = settings
        self.coordinator.set_settings(settings)
        self.screenSettingsChanged.emit()
        self._save_timer.start()

    def monitor_label(self, index: int | None = None) -> str:
        index = self.screen.monitor_index if index is None else index
        return next((text for value, text in self.monitor_options if value == index), self.monitor_options[0][1])

    def reset_screen_defaults(self) -> None:
        defaults = SyncSettings()
        self.screen = defaults
        self.update_screen()

    def save_now(self) -> None:
        self._save_timer.stop()
        if self.settings_path is not None:
            try:
                self.settings_path.parent.mkdir(parents=True, exist_ok=True)
                self.settings_path.write_text(json.dumps(self.screen.to_dict(), indent=2))
            except OSError as error:
                self.notice.emit(f"Could not save settings: {error}", "error")
        self._save_preferences()

    # ------------------------------------------------------------ music mode

    @property
    def music(self) -> MusicSettings:
        return self.music_mode.settings if self.music_mode else MusicSettings()

    def update_music(self, **changes) -> None:
        if not self.music_mode:
            return
        settings = replace(self.music_mode.settings, **changes)
        low, high = sorted((settings.minimum_brightness, settings.maximum_brightness))
        self.music_mode.update_settings(replace(settings, minimum_brightness=low, maximum_brightness=high))
        self._save_timer.start()

    def _apply_music(self) -> None:
        if self.music_mode:
            self.music_mode.update_settings(self.music_mode.settings)

    def music_status(self) -> dict:
        if not self.music_mode:
            return {}
        status = dict(self.music_mode.diagnostics())
        status["pulse"] = float(getattr(self.music_mode, "_beat_flash", 0.0))
        status["colour"] = tuple(getattr(self.music_mode, "_last_colour", (128, 128, 128)))
        return status

    # -------------------------------------------------------- album-art mode

    @property
    def album(self) -> AlbumArtSettings:
        return self.album_art_mode.settings if self.album_art_mode else AlbumArtSettings()

    def update_album(self, **changes) -> None:
        if not self.album_art_mode:
            return
        self.album_art_mode.update_settings(replace(self.album_art_mode.settings, **changes))
        self._save_timer.start()

    def _apply_album_art(self) -> None:
        if self.album_art_mode:
            self.album_art_mode.update_settings(self.album_art_mode.settings)

    # ---------------------------------------------------------------- scenes

    def selected_scene(self) -> ScenePreset | None:
        return next((scene for scene in self.scenes if scene.name == self.scene_name), None)

    def _scene_slot(self, scene: ScenePreset) -> int:
        try:
            return min(8, self.scenes.index(scene) + 1)
        except ValueError:
            return 8

    def _reapply_scene(self, scene: ScenePreset) -> bool:
        try:
            self.scenes_mode.apply()
        except Exception as error:
            self.notice.emit(str(error), "error")
            return False
        self.notice.emit(f"Playing {scene.name}", "info")
        return True

    def select_scene(self, name: str) -> None:
        if name == self.scene_name and self.selected_scene() is not None:
            return
        self.scene_name = name
        self.sceneSelected.emit(name)
        self._save_timer.start()
        scene = self.selected_scene()
        if scene is None or not self.scenes_mode:
            return
        self.scenes_mode.set_scene(scene, self._scene_slot(scene))
        self.scenes_mode.set_max_brightness(self.scene_brightness * 10)
        if self.active_mode == "scenes":
            self._reapply_scene(scene)

    def set_scene_brightness(self, percent: float) -> None:
        self.scene_brightness = float(percent)
        self._save_timer.start()
        scene = self.selected_scene()
        if scene is None or not self.scenes_mode:
            return
        self.scenes_mode.set_scene(scene, self._scene_slot(scene))
        self.scenes_mode.set_max_brightness(self.scene_brightness * 10)
        if self.active_mode == "scenes":
            self._reapply_scene(scene)

    def save_scene(self, scene: ScenePreset, previous_name: str | None = None) -> None:
        name = scene.name.strip() or "Custom scene"
        if any(item.builtin and item.name == name for item in self.scenes):
            name = self.unique_scene_name(name)
        scene = ScenePreset(name, list(scene.stops), bool(scene.loop), builtin=False)
        replaced = {name, previous_name}
        self.scenes = [item for item in self.scenes if item.builtin or item.name not in replaced]
        self.scenes.append(scene)
        self._persist_scenes()
        self.scenesChanged.emit()
        self.scene_name = ""
        self.select_scene(scene.name)

    def delete_scene(self, name: str) -> None:
        scene = next((item for item in self.scenes if item.name == name), None)
        if scene is None or scene.builtin:
            self.notice.emit("Built-in scenes can't be deleted.", "error")
            return
        self.scenes = [item for item in self.scenes if item.name != name]
        self._persist_scenes()
        self.scenesChanged.emit()
        if self.scene_name == name:
            self.scene_name = ""
            self.select_scene(self.scenes[0].name if self.scenes else "")

    def preview_scene(self, scene: ScenePreset) -> None:
        if not self.scenes_mode:
            return
        preview = ScenePreset(scene.name.strip() or "Preview", list(scene.stops), bool(scene.loop), builtin=False)
        self.scenes_mode.set_scene(preview, 8)
        self.scenes_mode.set_max_brightness(self.scene_brightness * 10)
        if self.switch_mode("scenes", preview):
            self.notice.emit(f"Previewing {preview.name} on the light", "info")

    def unique_scene_name(self, base: str) -> str:
        names = {scene.name for scene in self.scenes}
        if base not in names:
            return base
        index = 2
        while f"{base} {index}" in names:
            index += 1
        return f"{base} {index}"

    def _persist_scenes(self) -> None:
        if self.scenes_path is not None:
            save_custom_scenes(self.scenes_path, [item for item in self.scenes if not item.builtin])

    # ---------------------------------------------------------------- manual

    def _manual(self, method: str, *args) -> None:
        if not self.has_light():
            self.notice.emit("Add a light first. Open Settings → Light to connect one.", "error")
            return
        if self.active_mode != "off":
            self.switch_mode("off")

        def run():
            try:
                results = self.coordinator.light_service.execute(method, *args)
                ok = bool(results) and all(result == "sent" for result in results)
                detail = "" if ok else (", ".join(results) if results else "no response")
            except Exception as error:  # pragma: no cover - defensive
                ok, detail = False, str(error)
            self.manualResult.emit(ok, detail)

        threading.Thread(target=run, name="ManualCommand", daemon=True).start()

    def power(self, on: bool) -> None:
        self._manual("turn_on" if on else "turn_off")

    def set_manual_colour(self, rgb=None, brightness: float | None = None) -> None:
        if rgb is not None:
            self.manual_rgb = tuple(int(value) for value in rgb)
        if brightness is not None:
            self.manual_brightness = float(brightness)
        level = max(0.01, min(1.0, self.manual_brightness / 100))
        self._manual("set_color", *LightService._scale_rgb(self.manual_rgb, level))
        self._save_timer.start()

    def set_manual_white(self, brightness: float | None = None, temperature: float | None = None) -> None:
        if brightness is not None:
            self.manual_brightness = float(brightness)
        if temperature is not None:
            self.manual_temperature = float(temperature)
        self._manual("set_white", int(round(self.manual_brightness * 10)), int(round(self.manual_temperature)))
        self._save_timer.start()

    # -------------------------------------------------------------- profiles

    def profiles(self) -> list[LightProfile]:
        return self.profile_store.list_profiles() if self.profile_store else []

    def add_profile(self, name: str, device_id: str, local_key: str, ip_address: str = "", protocol: str = "3.5") -> LightProfile:
        if self.profile_store is None:
            raise ProfileStoreError("Light profiles are unavailable in this session.")
        profile = self.profile_store.save_profile(
            name=name, device_id=device_id, local_key=local_key, ip_address=ip_address, protocol=protocol
        )
        if self.config_manager is not None:
            self.config_manager.add_tuya_profile(profile)
        self.reload_bulbs()
        self.profilesChanged.emit()
        return profile

    def import_profile(self, source: str) -> LightProfile:
        if self.profile_store is None:
            raise ProfileStoreError("Light profiles are unavailable in this session.")
        profile = self.profile_store.import_profile(source)
        if self.config_manager is not None:
            self.config_manager.add_tuya_profile(profile)
        self.reload_bulbs()
        self.profilesChanged.emit()
        return profile

    def export_profile(self, profile: LightProfile, destination: str) -> None:
        if self.profile_store is None:
            raise ProfileStoreError("Light profiles are unavailable in this session.")
        self.profile_store.export_profile(profile.profile_id, destination)

    def remove_profile(self, profile: LightProfile) -> None:
        if self.profile_store is None:
            return
        self.profile_store.remove_profile(profile.profile_id)
        if self.config_manager is not None:
            self.config_manager.remove_profile(profile.profile_id)
        self.reload_bulbs()
        self.profilesChanged.emit()

    def reload_bulbs(self) -> None:
        if self.bulb_factory is None:
            return
        try:
            self.mode_manager.stop()
            self.modeChanged.emit(self.active_mode)
            self.coordinator.update_bulbs(self.bulb_factory.create_bulbs())
            self.startup_error = None
        except (ProfileStoreError, RuntimeError) as error:
            self.notice.emit(f"Could not connect the light: {error}", "error")

    # ----------------------------------------------------------- persistence

    def _load_preferences(self) -> None:
        if self.preferences_path is None:
            return
        try:
            data = json.loads(self.preferences_path.read_text())
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        try:
            if self.music_mode and isinstance(data.get("music"), dict):
                self.music_mode.update_settings(MusicSettings(**_known(MusicSettings, data["music"])))
            if self.album_art_mode and isinstance(data.get("album_art"), dict):
                self.album_art_mode.update_settings(AlbumArtSettings(**_known(AlbumArtSettings, data["album_art"])))
        except (TypeError, ValueError):
            pass
        scenes = data.get("scenes", {})
        if isinstance(scenes, dict):
            name = scenes.get("selected")
            if any(scene.name == name for scene in self.scenes):
                self.scene_name = name
            self.scene_brightness = float(scenes.get("max_brightness", self.scene_brightness))
        manual = data.get("manual", {})
        if isinstance(manual, dict):
            rgb = manual.get("rgb")
            if isinstance(rgb, list) and len(rgb) == 3:
                self.manual_rgb = tuple(int(max(0, min(255, value))) for value in rgb)
            self.manual_brightness = float(manual.get("brightness", self.manual_brightness))
            self.manual_temperature = float(manual.get("temperature", self.manual_temperature))
        if self.scenes_mode and self.selected_scene():
            self.scenes_mode.set_scene(self.selected_scene(), self._scene_slot(self.selected_scene()))
            self.scenes_mode.set_max_brightness(self.scene_brightness * 10)

    def _save_preferences(self) -> None:
        if self.preferences_path is None:
            return
        data = {
            "music": asdict(self.music),
            "album_art": asdict(self.album),
            "scenes": {"selected": self.scene_name, "max_brightness": self.scene_brightness},
            "manual": {"rgb": list(self.manual_rgb), "brightness": self.manual_brightness, "temperature": self.manual_temperature},
        }
        try:
            self.preferences_path.parent.mkdir(parents=True, exist_ok=True)
            self.preferences_path.write_text(json.dumps(data, indent=2))
        except OSError:
            pass

    # --------------------------------------------------------------- quitting

    def shutdown(self) -> None:
        self._poll.stop()
        self.save_now()
        try:
            self.mode_manager.stop()
            self.coordinator.light_service.stop()
        except RuntimeError as error:
            print(f"TuyaSync shutdown: {error}", flush=True)
