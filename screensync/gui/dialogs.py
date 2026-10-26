"""Modal sheets: adding a light and editing a scene."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from screensync.gui.widgets import SliderRow, ToggleRow, button, label, link_button, tokens
from screensync.scenes import ScenePreset, SceneStop

TINYTUYA_GUIDE_URL = "https://github.com/jasonacox/tinytuya#setup-wizard---getting-local-keys"
TUYA_IOT_URL = "https://iot.tuya.com"

SETUP_STEPS = (
    "Pair the light in the Smart Life or Tuya Smart phone app.",
    "Create a project at iot.tuya.com and link your app account to it.",
    "On any computer with Python, run  python -m tinytuya wizard",
    "The wizard prints each light's Device ID and Local Key. Copy those two values here.",
)


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class SetupSteps(QWidget):
    """The one-time steps for finding a light's Device ID and Local Key."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for index, step in enumerate(SETUP_STEPS, start=1):
            row = QHBoxLayout()
            row.setSpacing(10)
            number = label(str(index))
            number.setProperty("badge", True)
            number.setFixedWidth(26)
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(number, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(label(step, "hint", wrap=True), 1)
            layout.addLayout(row)
        links = QHBoxLayout()
        links.setSpacing(16)
        links.addWidget(link_button("TinyTuya setup guide ↗", lambda: open_url(TINYTUYA_GUIDE_URL)))
        links.addWidget(link_button("Open Tuya IoT ↗", lambda: open_url(TUYA_IOT_URL)))
        links.addStretch(1)
        layout.addLayout(links)
        layout.addWidget(label("TuyaSync never needs your Tuya password, and it doesn't use the cloud once the light is added.", "hint", wrap=True))


class LightDialog(QDialog):
    """Enter a new light's credentials."""

    def __init__(self, save: Callable[[dict], None], parent=None):
        super().__init__(parent)
        self._save = save
        self.setWindowTitle("Add a light")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(16)
        layout.addWidget(label("Add a light", "display"))
        layout.addWidget(label("Enter the two values for your light. They're stored only on this computer.", "subtitle", wrap=True))

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.name = QLineEdit("My Tuya light")
        self.device_id = QLineEdit()
        self.device_id.setPlaceholderText("e.g. bf12a3c45d6e7f8a9b0c1d")
        self.local_key = QLineEdit()
        self.local_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.local_key.setPlaceholderText("16 characters")
        self.show_key = button("Show", "ghost", self._toggle_key)
        key_row = QWidget()
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(6)
        key_layout.addWidget(self.local_key, 1)
        key_layout.addWidget(self.show_key)
        self.ip = QLineEdit()
        self.ip.setPlaceholderText("Leave blank to find it automatically")
        self.protocol = QLineEdit("3.5")
        form.addRow(label("Name", "heading"), self.name)
        form.addRow(label("Device ID", "heading"), self.device_id)
        form.addRow(label("Local Key", "heading"), key_row)
        form.addRow(label("LAN address", "heading"), self.ip)
        form.addRow(label("Protocol", "heading"), self.protocol)
        layout.addLayout(form)

        self.help = SetupSteps()
        self.help.hide()
        self.help_toggle = link_button("Where do I find these?", self._toggle_help)
        layout.addWidget(self.help_toggle)
        layout.addWidget(self.help)

        self.error = label("", "hint", wrap=True)
        self.error.setStyleSheet(f"color: {tokens().danger};")
        self.error.hide()
        layout.addWidget(self.error)

        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(button("Cancel", None, self.reject))
        self.submit = button("Save and connect", "primary", self._submit)
        self.submit.setDefault(True)
        actions.addWidget(self.submit)
        layout.addLayout(actions)

    def _toggle_key(self) -> None:
        hidden = self.local_key.echoMode() == QLineEdit.EchoMode.Password
        self.local_key.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self.show_key.setText("Hide" if hidden else "Show")

    def _toggle_help(self) -> None:
        self.help.setVisible(not self.help.isVisible())
        self.adjustSize()

    def _submit(self) -> None:
        fields = {
            "name": self.name.text(),
            "device_id": self.device_id.text(),
            "local_key": self.local_key.text(),
            "ip_address": self.ip.text(),
            "protocol": self.protocol.text(),
        }
        try:
            self._save(fields)
        except Exception as error:
            self.error.setText(str(error))
            self.error.show()
            return
        self.accept()


class StopStrip(QWidget):
    """Clickable timeline of a scene's colour stops."""

    picked = Signal(int)

    def __init__(self):
        super().__init__()
        self.stops: list[SceneStop] = []
        self.selected = 0
        self.setMinimumHeight(64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_stops(self, stops: list[SceneStop], selected: int) -> None:
        self.stops = stops
        self.selected = selected
        self.update()

    def _rects(self) -> list[QRectF]:
        if not self.stops:
            return []
        gap = 8.0
        width = (self.width() - gap * (len(self.stops) - 1)) / len(self.stops)
        return [QRectF(index * (width + gap), 6, width, self.height() - 12) for index in range(len(self.stops))]

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        for index, rect in enumerate(self._rects()):
            if rect.contains(event.position()):
                self.picked.emit(index)
                return

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index, (rect, stop) in enumerate(zip(self._rects(), self.stops)):
            if index == self.selected:
                painter.setPen(QPen(QColor(t.text), 2.5))
            else:
                painter.setPen(QPen(QColor(t.border), 1))
            painter.setBrush(QColor(*stop.color))
            painter.drawRoundedRect(rect, 10, 10)
            painter.setPen(QColor(255, 255, 255) if sum(stop.color) < 500 else QColor(20, 20, 20))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(index + 1))


class SceneEditor(QDialog):
    def __init__(self, scene: ScenePreset, preview: Callable[[ScenePreset], None], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scene editor")
        self.setMinimumSize(640, 560)
        self._preview = preview
        self.stops = list(scene.stops) or [SceneStop((255, 70, 160))]
        self.index = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(16)
        layout.addWidget(label("Scene editor", "display"))
        layout.addWidget(label("Build a sequence of colours. The light fades between them on its own.", "subtitle", wrap=True))
        top = QHBoxLayout()
        top.setSpacing(16)
        self.name = QLineEdit(scene.name)
        self.name.setPlaceholderText("Scene name")
        top.addWidget(self.name, 1)
        self.loop = ToggleRow("Loop", None, scene.loop)
        top.addWidget(self.loop)
        layout.addLayout(top)

        self.strip = StopStrip()
        self.strip.picked.connect(self._select)
        layout.addWidget(self.strip)
        strip_actions = QHBoxLayout()
        strip_actions.setSpacing(8)
        strip_actions.addWidget(button("Add colour", None, self._add))
        strip_actions.addWidget(button("◀", None, lambda: self._move(-1)))
        strip_actions.addWidget(button("▶", None, lambda: self._move(1)))
        strip_actions.addStretch(1)
        self.remove_button = button("Remove", "danger", self._remove)
        strip_actions.addWidget(self.remove_button)
        layout.addLayout(strip_actions)

        detail = QVBoxLayout()
        detail.setSpacing(14)
        head = QHBoxLayout()
        self.stop_title = label("", "title")
        head.addWidget(self.stop_title, 1)
        head.addWidget(button("Change colour…", None, self._colour))
        detail.addLayout(head)
        self.brightness = SliderRow("Brightness", None, 0, 100, 70, 1, lambda v: f"{v:.0f}%")
        self.brightness.valueChanged.connect(lambda v: self._update(brightness=int(round(v * 10))))
        detail.addWidget(self.brightness)
        timing = QHBoxLayout()
        timing.setSpacing(16)
        self.fade = QDoubleSpinBox()
        self.fade.setRange(0, 100)
        self.fade.setSuffix(" s")
        self.fade.setDecimals(1)
        self.fade.valueChanged.connect(lambda v: self._update(transition_duration=float(v)))
        self.hold = QDoubleSpinBox()
        self.hold.setRange(0, 100)
        self.hold.setSuffix(" s")
        self.hold.setDecimals(1)
        self.hold.valueChanged.connect(lambda v: self._update(hold_duration=float(v)))
        for title, spin in (("Fade in over", self.fade), ("Then hold for", self.hold)):
            box = QVBoxLayout()
            box.setSpacing(6)
            box.addWidget(label(title, "heading"))
            box.addWidget(spin)
            timing.addLayout(box)
        timing.addStretch(1)
        detail.addLayout(timing)
        layout.addLayout(detail)
        layout.addStretch(1)

        actions = QHBoxLayout()
        actions.addWidget(button("Preview on light", None, lambda: self._preview(self.result_scene())))
        actions.addStretch(1)
        actions.addWidget(button("Cancel", None, self.reject))
        save = button("Save scene", "primary", self.accept)
        save.setDefault(True)
        actions.addWidget(save)
        layout.addLayout(actions)
        self._select(0)

    def result_scene(self) -> ScenePreset:
        return ScenePreset(self.name.text().strip() or "Custom scene", list(self.stops), self.loop.toggle.isChecked(), builtin=False)

    def _select(self, index: int) -> None:
        self.index = max(0, min(len(self.stops) - 1, index))
        stop = self.stops[self.index]
        self.stop_title.setText(f"Colour {self.index + 1} of {len(self.stops)}")
        self.brightness.set_value(stop.brightness / 10)
        for spin, value in ((self.fade, stop.transition_duration), (self.hold, stop.hold_duration)):
            blocked = spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(blocked)
        self.remove_button.setEnabled(len(self.stops) > 1)
        self.strip.set_stops(self.stops, self.index)

    def _update(self, **changes) -> None:
        stop = self.stops[self.index]
        self.stops[self.index] = SceneStop(
            tuple(changes.get("color", stop.color)),
            int(max(0, min(1000, changes.get("brightness", stop.brightness)))),
            float(max(0.0, min(100.0, changes.get("transition_duration", stop.transition_duration)))),
            float(max(0.0, min(100.0, changes.get("hold_duration", stop.hold_duration)))),
        )
        self.strip.set_stops(self.stops, self.index)

    def _colour(self) -> None:
        colour = QColorDialog.getColor(QColor(*self.stops[self.index].color), self, "Choose a colour")
        if colour.isValid():
            self._update(color=(colour.red(), colour.green(), colour.blue()))

    def _add(self) -> None:
        current = self.stops[self.index]
        self.stops.insert(self.index + 1, SceneStop((100, 180, 255), current.brightness, current.transition_duration, current.hold_duration))
        self._select(self.index + 1)

    def _remove(self) -> None:
        if len(self.stops) > 1:
            self.stops.pop(self.index)
            self._select(self.index - 1 if self.index else 0)

    def _move(self, direction: int) -> None:
        target = self.index + direction
        if 0 <= target < len(self.stops):
            self.stops[self.index], self.stops[target] = self.stops[target], self.stops[self.index]
            self._select(target)
