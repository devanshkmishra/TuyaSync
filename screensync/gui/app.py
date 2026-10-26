"""Start TuyaSync: build the lighting engine, then open the interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from platformdirs import user_data_dir

from screensync.audio.factory import system_audio_backend
from screensync.light_profiles import LightProfileStore, ProfileStoreError
from screensync.light_service import LightService
from screensync.modes.album_art import AlbumArtMode
from screensync.modes.manager import ModeManager
from screensync.modes.music import MusicMode
from screensync.modes.scenes import ScenesMode
from screensync.now_playing.factory import spotify_backend
from screensync.scenes import BUILTIN_SCENES, load_custom_scenes
from screensync.screen_sync.ambient import RuntimeMetrics, SyncSettings
from screensync.screen_sync.bulb_factory import BulbFactory
from screensync.screen_sync.config_manager import ConfigManager
from screensync.screen_sync.coordinator import Coordinator

APP_NAME = "TuyaSync"
APP_AUTHOR = "TuyaSync"
DATA_DIR = Path(user_data_dir(APP_NAME, APP_AUTHOR))
SETTINGS_PATH = DATA_DIR / "ambient-settings.json"
PREFERENCES_PATH = DATA_DIR / "ui-preferences.json"
SCENES_PATH = DATA_DIR / "scenes.json"
APP_ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "tuyasync-app-icon.png"


def load_settings(path: Path = SETTINGS_PATH) -> SyncSettings:
    try:
        return SyncSettings.from_dict(json.loads(path.read_text()))
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return SyncSettings()


def apply_theme(app) -> None:
    from screensync.gui import theme

    tokens = theme.current_tokens()
    app.setPalette(theme.palette_for(tokens))
    app.setStyleSheet(theme.stylesheet(tokens))


def main() -> int:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from screensync.gui.controller import AppController
    from screensync.gui.tray import Tray
    from screensync.gui.window import MainWindow

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    manager = ConfigManager(str(DATA_DIR / "config.ini"))
    profile_store = LightProfileStore(DATA_DIR)
    factory = BulbFactory(manager, profile_store=profile_store)
    startup_error = None
    try:
        # Older installs may still keep a raw Local Key in config.ini; move it
        # into the profile file before any controller is created.
        profile_store.migrate_config(manager)
        bulbs = factory.create_bulbs()
    except ProfileStoreError as error:
        startup_error = str(error)
        bulbs = []
    settings = load_settings()
    light_service = LightService(bulbs, RuntimeMetrics(), settings)
    light_service.start()
    coordinator = Coordinator(bulbs, settings=settings, light_service=light_service)
    music_mode = album_art_mode = None
    try:
        music_mode = MusicMode(light_service, system_audio_backend())
    except Exception as error:
        print(f"TuyaSync music backend unavailable: {error}", flush=True)
    try:
        album_art_mode = AlbumArtMode(
            light_service,
            spotify_backend(),
            DATA_DIR / "album-art-cache",
            audio_backend=system_audio_backend(),
        )
    except Exception as error:
        print(f"TuyaSync album-art backend unavailable: {error}", flush=True)
    scenes = list(BUILTIN_SCENES) + load_custom_scenes(SCENES_PATH)
    scenes_mode = ScenesMode(light_service, scenes[0] if scenes else None)
    modes = [coordinator, scenes_mode]
    if music_mode:
        modes.append(music_mode)
    if album_art_mode:
        modes.append(album_art_mode)
    mode_manager = ModeManager(modes, light_service.clear)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)
    hints = app.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda _scheme: apply_theme(app))

    controller = AppController(
        coordinator,
        mode_manager,
        music_mode,
        album_art_mode,
        scenes_mode,
        scenes,
        profile_store=profile_store,
        config_manager=manager,
        bulb_factory=factory,
        settings_path=SETTINGS_PATH,
        preferences_path=PREFERENCES_PATH,
        scenes_path=SCENES_PATH,
        startup_error=startup_error,
    )
    window = MainWindow(controller)
    if QSystemTrayIcon.isSystemTrayAvailable():
        window.tray = Tray(controller, window)
        window.tray.show()
    app.aboutToQuit.connect(lambda: None if window._quitting else controller.shutdown())
    controller.start_polling()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
