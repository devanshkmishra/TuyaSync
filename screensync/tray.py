"""Cross-platform menu-bar/system-tray controls for TuyaSync."""

from __future__ import annotations

import sys
from pathlib import Path

import pystray
from PIL import Image, ImageDraw


ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def _icon_image() -> Image.Image:
    filename = "tuyasync-menubar-white.png" if sys.platform == "win32" else "tuyasync-menubar.png"
    try:
        with Image.open(ASSETS_DIR / filename) as image:
            return image.convert("RGBA").copy()
    except (FileNotFoundError, OSError):
        # Keep the tray usable during source checkouts where generated assets
        # have not been copied yet.
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        colour = (18, 24, 34, 255)
        draw.rounded_rectangle((11, 13, 53, 25), radius=6, fill=colour)
        draw.arc((20, 23, 44, 42), start=20, end=160, fill=colour, width=4)
        draw.arc((10, 28, 54, 57), start=20, end=160, fill=colour, width=4)
        return image


class TrayController:
    def __init__(self, app):
        self.app = app
        self.icon = pystray.Icon(
            "TuyaSync",
            _icon_image(),
            "TuyaSync",
            menu=pystray.Menu(
                pystray.MenuItem(self._status_text, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Start Screen Sync", lambda _icon, _item: app.enqueue("start"), enabled=lambda _item: app.mode_manager.active_mode == "off"),
                pystray.MenuItem("Stop Active Mode", lambda _icon, _item: app.enqueue("stop"), enabled=lambda _item: app.mode_manager.active_mode != "off"),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Lighting Mode", pystray.Menu(
                    pystray.MenuItem("Off", lambda _icon, _item: app.enqueue("mode:off"), checked=lambda _item: app.mode_manager.active_mode == "off"),
                    pystray.MenuItem("Screen", lambda _icon, _item: app.enqueue("mode:screen"), checked=lambda _item: app.mode_manager.active_mode == "screen"),
                    pystray.MenuItem("Music", lambda _icon, _item: app.enqueue("mode:music"), enabled=lambda _item: app.music_mode is not None, checked=lambda _item: app.mode_manager.active_mode == "music"),
                    pystray.MenuItem("Album Art", lambda _icon, _item: app.enqueue("mode:album_art"), enabled=lambda _item: app.album_art_mode is not None, checked=lambda _item: app.mode_manager.active_mode == "album_art"),
                    pystray.MenuItem("Scenes", lambda _icon, _item: app.enqueue("mode:scenes"), checked=lambda _item: app.mode_manager.active_mode == "scenes"),
                )),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quick Settings…", lambda _icon, _item: app.enqueue("quick"), default=True),
                pystray.MenuItem("Full Settings…", lambda _icon, _item: app.enqueue("show")),
                pystray.MenuItem("Diagnostics…", lambda _icon, _item: app.enqueue("diagnostics")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit TuyaSync", lambda _icon, _item: app.enqueue("quit")),
            ),
        )

    def _status_text(self, _item):
        info = self.app.coordinator.device_info()
        sync = self.app.MODE_LABELS.get(self.app.mode_manager.active_mode, "Off")
        connection = "Connected" if info.get("connected") else "Disconnected"
        return f"{sync} · {connection}"

    def start(self):
        self.icon.run_detached()

    def refresh(self):
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def stop(self):
        self.icon.stop()
