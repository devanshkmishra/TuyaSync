"""Menu-bar (macOS) and system-tray (Windows) controls."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from screensync.gui.controller import MODE_LABELS, AppController

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def tray_icon() -> QIcon:
    if sys.platform == "darwin":
        icon = QIcon(str(ASSETS_DIR / "tuyasync-menubar.png"))
        icon.setIsMask(True)
        return icon
    return QIcon(str(ASSETS_DIR / "tuyasync-menubar-white.png"))


class Tray(QSystemTrayIcon):
    def __init__(self, controller: AppController, window):
        super().__init__(tray_icon(), window)
        self.controller = controller
        self.window = window
        self._told_hidden = False
        self.setToolTip("TuyaSync")

        menu = QMenu()
        self.status = menu.addAction("")
        self.status.setEnabled(False)
        menu.addSeparator()
        self.modes = QActionGroup(menu)
        self.modes.setExclusive(True)
        self.mode_actions: dict[str, QAction] = {}
        for key in ("screen", "music", "album_art", "scenes", "off"):
            text = "Stop automatic modes" if key == "off" else MODE_LABELS[key]
            action = menu.addAction(text)
            action.setCheckable(key != "off")
            if key != "off":
                self.modes.addAction(action)
            action.triggered.connect(lambda _checked=False, k=key: controller.switch_mode(k))
            self.mode_actions[key] = action
        menu.addSeparator()
        menu.addAction("Turn light on", lambda: controller.power(True))
        menu.addAction("Turn light off", lambda: controller.power(False))
        menu.addSeparator()
        menu.addAction("Open TuyaSync", window.bring_to_front)
        menu.addAction("Settings…", lambda: (window.bring_to_front(), window.open_settings("light")))
        menu.addSeparator()
        menu.addAction("Quit TuyaSync", window.quit_app)
        menu.aboutToShow.connect(self.refresh)
        self._menu = menu
        self.setContextMenu(menu)
        self.activated.connect(self._activated)
        controller.modeChanged.connect(lambda _mode: self.refresh())
        self.refresh()

    def _activated(self, reason) -> None:
        # Windows: a left click opens the window; macOS always shows the menu.
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) and sys.platform != "darwin":
            self.window.bring_to_front()

    def refresh(self) -> None:
        mode = self.controller.active_mode
        info = self.controller.device_info()
        connection = "Connected" if info.get("connected") else "Not connected"
        running = MODE_LABELS.get(mode, "Manual") if mode != "off" else "No mode running"
        self.status.setText(f"{running} · {connection}")
        self.setToolTip(f"TuyaSync · {running}")
        for key, action in self.mode_actions.items():
            action.setEnabled(self.controller.mode_available(key) and (key != "off" or mode != "off"))
            if key != "off":
                action.setChecked(key == mode)
        if mode == "off":
            # QActionGroup keeps one item checked; clear it when nothing runs.
            self.modes.setExclusive(False)
            for key, action in self.mode_actions.items():
                if key != "off":
                    action.setChecked(False)
            self.modes.setExclusive(True)

    def notify_hidden(self) -> None:
        if self._told_hidden or not self.supportsMessages():
            return
        self._told_hidden = True
        where = "menu bar" if sys.platform == "darwin" else "system tray"
        self.showMessage("TuyaSync is still running", f"Your light keeps syncing. Open TuyaSync from the {where}.", self.icon(), 4000)
