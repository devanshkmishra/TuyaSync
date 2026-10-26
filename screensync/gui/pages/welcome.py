"""First run: connect a light."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from screensync.gui.dialogs import SetupSteps
from screensync.gui.widgets import Card, button, label, link_button

ICON_PATH = Path(__file__).resolve().parents[2] / "assets" / "tuyasync-app-icon.png"


class Choice(QFrame):
    def __init__(self, title: str, body: str, action: str, on_click, primary: bool = False):
        super().__init__()
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(8)
        layout.addWidget(label(title, "title"))
        layout.addWidget(label(body, "hint", wrap=True), 1)
        layout.addSpacing(6)
        layout.addWidget(button(action, "primary" if primary else None, on_click), 0, Qt.AlignmentFlag.AlignLeft)


class WelcomePage(QWidget):
    def __init__(self, add_light, import_profile, skip):
        super().__init__()
        self.setObjectName("Content")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.addStretch(1)
        column_widget = QWidget()
        column_widget.setMaximumWidth(760)
        column = QVBoxLayout(column_widget)
        column.setSpacing(18)
        column.addStretch(1)

        logo = label()
        pixmap = QPixmap(str(ICON_PATH))
        if not pixmap.isNull():
            ratio = self.devicePixelRatioF() or 1.0
            scaled = pixmap.scaled(int(72 * ratio), int(72 * ratio), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(ratio)
            logo.setPixmap(scaled)
        column.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)
        title = label("Welcome to TuyaSync", "display")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(title)
        subtitle = label("Let's connect your light. You only do this once; after that TuyaSync talks to it directly over your network.", "subtitle", wrap=True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(subtitle)
        column.addSpacing(10)

        choices = QHBoxLayout()
        choices.setSpacing(16)
        choices.addWidget(Choice(
            "I have the Device ID and Local Key",
            "Enter the two values for your light. The LAN address is optional.",
            "Add light",
            add_light,
            primary=True,
        ), 1)
        choices.addWidget(Choice(
            "I set it up on another computer",
            "Import the .tuyasync-profile.json file you exported there. No Tuya setup needed.",
            "Import profile…",
            import_profile,
        ), 1)
        column.addLayout(choices)

        steps = Card("Need the Device ID and Local Key?", "A one-time step for each new physical light.", spacing=12)
        steps.add(SetupSteps())
        column.addWidget(steps)
        skip_link = link_button("Set up later", skip)
        column.addWidget(skip_link, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(1)
        outer.addWidget(column_widget, 4)
        outer.addStretch(1)
