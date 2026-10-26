"""The main window: a sidebar of modes beside the selected page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from screensync.gui import icons
from screensync.gui.controller import MODE_LABELS, AppController
from screensync.gui.dialogs import LightDialog
from screensync.gui.pages.album_art import AlbumArtPage
from screensync.gui.pages.manual import ManualPage
from screensync.gui.pages.music import MusicPage
from screensync.gui.pages.scenes import ScenesPage
from screensync.gui.pages.screen import ScreenPage
from screensync.gui.pages.settings import PROFILE_FILTER, SettingsPage
from screensync.gui.pages.welcome import WelcomePage
from screensync.gui.widgets import StatusDot, button, label, repolish, tokens
from screensync.light_profiles import ProfileStoreError

ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "tuyasync-app-icon.png"
NAV_ORDER = ("off", "screen", "music", "album_art", "scenes")
NAV_HINTS = {
    "off": "Pick a colour yourself",
    "screen": "Follow your display",
    "music": "Move with your audio",
    "album_art": "Colours from Spotify",
    "scenes": "Moods on the light",
    "settings": "Light, calibration, more",
}


class NavButton(QAbstractButton):
    """A sidebar entry with an icon, a hint, and a live indicator."""

    def __init__(self, key: str, title: str):
        super().__init__()
        self.key = key
        self.title = title
        self.live = False
        self.available = True
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(52)
        self.setToolTip(NAV_HINTS.get(key, ""))
        self._hover = False

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(220, 52)

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def set_live(self, live: bool) -> None:
        self.live = live
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0, 2, 0, -2)
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t.surface_hover if t.dark else t.surface))
            painter.drawRoundedRect(rect, 12, 12)
            painter.setBrush(QColor(t.accent))
            painter.drawRoundedRect(QRectF(rect.left(), rect.top() + 12, 3.5, rect.height() - 24), 2, 2)
        elif self._hover:
            painter.setPen(Qt.PenStyle.NoPen)
            hover = QColor(t.surface_hover)
            hover.setAlpha(150)
            painter.setBrush(hover)
            painter.drawRoundedRect(rect, 12, 12)

        colour = t.text if self.isChecked() else t.secondary
        if not self.available:
            colour = t.tertiary
        painter.drawPixmap(16, int(rect.center().y() - 10), icons.pixmap(self.key, colour, 20))

        font = QFont(self.font())
        font.setPixelSize(14)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(t.text if self.isChecked() else t.text if self._hover else t.secondary))
        painter.drawText(QRectF(48, rect.top() + 7, rect.width() - 80, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.title)
        small = QFont(self.font())
        small.setPixelSize(11)
        painter.setFont(small)
        painter.setPen(QColor(t.tertiary))
        hint = NAV_HINTS.get(self.key, "") if self.available else "Unavailable on this computer"
        painter.drawText(QRectF(48, rect.top() + 26, rect.width() - 80, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, hint)

        if self.live:
            centre = QRectF(rect.right() - 24, rect.center().y() - 5, 10, 10)
            halo = QColor(t.success)
            halo.setAlpha(70)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(centre.adjusted(-4, -4, 4, 4))
            painter.setBrush(QColor(t.success))
            painter.drawEllipse(centre)


class LightStatus(QFrame):
    """Connection status and power buttons at the foot of the sidebar."""

    def __init__(self, controller: AppController, open_settings):
        super().__init__()
        self.controller = controller
        self.setProperty("inset", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.dot = StatusDot(9)
        top.addWidget(self.dot)
        copy = QVBoxLayout()
        copy.setSpacing(1)
        self.name = label("No light", "heading")
        self.detail = label("", "hint")
        copy.addWidget(self.name)
        copy.addWidget(self.detail)
        top.addLayout(copy, 1)
        layout.addLayout(top)
        self.power_row = QHBoxLayout()
        self.power_row.setSpacing(6)
        self.on_button = button("On", None, lambda: controller.power(True))
        self.on_button.setIcon(icons.icon("power", tokens().secondary, 14))
        self.off_button = button("Off", None, lambda: controller.power(False))
        self.add_button = button("Add a light", "primary", open_settings)
        self.power_row.addWidget(self.on_button, 1)
        self.power_row.addWidget(self.off_button, 1)
        self.power_row.addWidget(self.add_button, 1)
        layout.addLayout(self.power_row)

    def refresh(self, info: dict) -> None:
        t = tokens()
        has_light = self.controller.has_light()
        profiles = self.controller.profiles()
        self.on_button.setVisible(has_light)
        self.off_button.setVisible(has_light)
        self.add_button.setVisible(not has_light)
        if not has_light:
            self.dot.set_colour(t.tertiary)
            self.name.setText("No light connected")
            self.detail.setText("Add one to get started")
            return
        self.name.setText(profiles[0].name if profiles else "Tuya light")
        connected = bool(info.get("connected"))
        state = str(info.get("state", "")).lower()
        if connected:
            self.dot.set_colour(t.success)
            self.detail.setText(f"Connected · {info.get('ip', '')}")
        elif state in {"connecting", "discovering", "reconnecting"}:
            self.dot.set_colour(t.warning)
            self.detail.setText(state.title() + "…")
        else:
            self.dot.set_colour(t.danger)
            self.detail.setText("Not connected")
        self.setToolTip(str(info.get("message", "")))


class Toast(QLabel):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setWordWrap(True)
        self.setMaximumWidth(520)
        self.hide()
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(220)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._hide)
        self._fade.finished.connect(self._faded)

    def show_message(self, text: str, level: str = "info") -> None:
        self.setText(text)
        self.setProperty("level", level)
        repolish(self)
        self.adjustSize()
        self.place()
        start = 0.0 if self.isHidden() else self._effect.opacity()
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(start)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(6000 if level == "error" else 3500)

    def _hide(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _faded(self) -> None:
        if self._fade.endValue() == 0.0:
            self.hide()

    def mousePressEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        self._timer.stop()
        self._hide()

    def place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - 24
        self.move(max(16, x), y)


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController):
        super().__init__()
        self.controller = controller
        self.tray = None
        self._quitting = False
        self.setWindowTitle("TuyaSync")
        self.resize(1120, 800)
        self.setMinimumSize(920, 640)

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.sidebar = self._build_sidebar()
        root_layout.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack, 1)

        self.pages = {
            "off": ManualPage(controller),
            "screen": ScreenPage(controller),
            "music": MusicPage(controller),
            "album_art": AlbumArtPage(controller),
            "scenes": ScenesPage(controller),
            "settings": SettingsPage(controller, self.quit_app),
        }
        for page in self.pages.values():
            self.stack.addWidget(page)

        self.outer = QStackedWidget()
        self.outer.addWidget(root)
        welcome = QScrollArea()
        welcome.setWidgetResizable(True)
        welcome.setFrameShape(QFrame.Shape.NoFrame)
        welcome.setWidget(WelcomePage(self.add_light, self.import_profile, self.show_main))
        self.outer.addWidget(welcome)
        self.setCentralWidget(self.outer)
        self.toast = Toast(self.outer)

        controller.modeChanged.connect(self.on_mode)
        controller.notice.connect(self.toast.show_message)
        controller.tick.connect(self.refresh)
        controller.profilesChanged.connect(self._profiles_changed)

        start = controller.active_mode
        self.navigate("screen" if start == "off" else start)
        self.on_mode(start)
        if controller.profile_store is not None and not controller.profiles():
            self.outer.setCurrentIndex(1)
        if controller.startup_error:
            QTimer.singleShot(400, lambda: self.toast.show_message(controller.startup_error, "error"))

    # ----------------------------------------------------------- structure

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar.setFixedWidth(256)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 22, 16, 16)
        layout.setSpacing(4)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        pixmap = QPixmap(str(ICON_PATH))
        if not pixmap.isNull():
            ratio = self.devicePixelRatioF() or 1.0
            scaled = pixmap.scaled(int(30 * ratio), int(30 * ratio), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(ratio)
            logo.setPixmap(scaled)
        brand.addWidget(logo)
        brand.addWidget(label("TuyaSync", "brand"))
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addSpacing(22)
        layout.addWidget(label("MODES", "caption"))
        layout.addSpacing(4)

        self.nav: dict[str, NavButton] = {}
        for key in NAV_ORDER:
            item = NavButton(key, MODE_LABELS[key])
            item.available = self.controller.mode_available(key)
            item.clicked.connect(lambda _checked=False, k=key: self.navigate(k))
            self.nav[key] = item
            layout.addWidget(item)
        layout.addStretch(1)
        settings = NavButton("settings", "Settings")
        settings.clicked.connect(lambda _checked=False: self.navigate("settings"))
        self.nav["settings"] = settings
        layout.addWidget(settings)
        layout.addSpacing(10)
        self.light_status = LightStatus(self.controller, lambda: self.open_settings("light"))
        layout.addWidget(self.light_status)
        return sidebar

    # ------------------------------------------------------------ behaviour

    def navigate(self, key: str) -> None:
        for name, item in self.nav.items():
            item.setChecked(name == key)
        self.stack.setCurrentWidget(self.pages[key])

    def open_settings(self, tab: str = "light") -> None:
        self.show_main()
        self.navigate("settings")
        self.pages["settings"].show_tab(tab)

    def show_main(self) -> None:
        self.outer.setCurrentIndex(0)

    def on_mode(self, mode: str) -> None:
        for name, item in self.nav.items():
            item.set_live(name == mode and mode != "off")
        for page in self.pages.values():
            page.on_mode(mode)
        if self.tray:
            self.tray.refresh()

    def refresh(self, snapshot: dict, info: dict) -> None:
        self.light_status.refresh(info)
        page = self.stack.currentWidget()
        if self.isVisible() and self.outer.currentIndex() == 0:
            page.refresh(snapshot, info)

    def _profiles_changed(self) -> None:
        if self.controller.profiles() and self.outer.currentIndex() == 1:
            self.show_main()
            self.navigate("screen")

    def add_light(self) -> None:
        def save(fields):
            profile = self.controller.add_profile(**fields)
            self.controller.notice.emit(f"Saved {profile.name}. Connecting over your network…", "success")

        LightDialog(save, self).exec()

    def import_profile(self) -> None:
        source, _ = QFileDialog.getOpenFileName(self, "Import a TuyaSync light profile", "", PROFILE_FILTER)
        if not source:
            return
        try:
            profile = self.controller.import_profile(source)
        except ProfileStoreError as error:
            QMessageBox.warning(self, "Couldn't import the light", str(error))
            return
        self.controller.notice.emit(f"{profile.name} is ready on this computer.", "success")

    def bring_to_front(self) -> None:
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        if self.toast.isVisible():
            self.toast.place()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._quitting or self.tray is None:
            self._quitting = True
            self.controller.shutdown()
            event.accept()
            return
        event.ignore()
        self.hide()
        self.tray.notify_hidden()

    def quit_app(self) -> None:
        self._quitting = True
        if self.tray:
            self.tray.hide()
        self.close()
        from PySide6.QtWidgets import QApplication

        QApplication.quit()
