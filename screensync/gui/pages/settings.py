"""Settings: lights, calibration, diagnostics, and app options."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from screensync.gui.controller import AppController
from screensync.gui.dialogs import LightDialog, SetupSteps
from screensync.gui.widgets import (
    Card,
    Page,
    Section,
    Segmented,
    SliderRow,
    StatusDot,
    Swatch,
    ValueGrid,
    button,
    label,
    rgb_text,
    tokens,
)
from screensync.light_profiles import LightProfile, ProfileStoreError

PROFILE_FILTER = "TuyaSync light profile (*.tuyasync-profile.json);;JSON files (*.json);;All files (*)"


def _times(value: float) -> str:
    return f"{value:.2f}×"


class ProfileCard(QFrame):
    def __init__(self, profile: LightProfile, on_export, on_remove):
        super().__init__()
        self.setProperty("inset", True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)
        self.dot = StatusDot(10)
        layout.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        copy = QVBoxLayout()
        copy.setSpacing(3)
        copy.addWidget(label(profile.name, "heading"))
        address = profile.ip_address or "address found automatically"
        details = label(f"{profile.device_id}  ·  {address}  ·  protocol {profile.protocol:g}", "mono", wrap=True)
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        copy.addWidget(details)
        layout.addLayout(copy, 1)
        layout.addWidget(button("Export…", None, lambda: on_export(profile)), 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(button("Remove", "danger", lambda: on_remove(profile)), 0, Qt.AlignmentFlag.AlignVCenter)


class LightTab(QWidget):
    def __init__(self, controller: AppController):
        super().__init__()
        self.controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        lights = Card("Your light", "TuyaSync talks to the light directly over your local network.")
        self.status = label("", "hint", wrap=True)
        lights.add(self.status)
        self.list = QVBoxLayout()
        self.list.setSpacing(10)
        lights.body.addLayout(self.list)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(button("Add a light…", "primary", self.add_light))
        actions.addWidget(button("Import profile…", None, self.import_profile))
        actions.addStretch(1)
        lights.body.addLayout(actions)
        layout.addWidget(lights)

        moving = Card("Moving to another computer", None)
        moving.add(label(
            "Export the profile here, copy the .tuyasync-profile.json file to the other computer, and import it there. "
            "The file contains the light's Local Key, so keep it private.",
            "hint",
            wrap=True,
        ))
        layout.addWidget(moving)

        help_section = Section("Getting a Device ID and Local Key", "A one-time step for each new physical light.")
        help_section.add(SetupSteps())
        layout.addWidget(help_section)

        self.rebuild()
        controller.profilesChanged.connect(self.rebuild)

    def rebuild(self) -> None:
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if self.controller.profile_store is None:
            self.status.setText("Light profiles aren't available in this session.")
            return
        profiles = self.controller.profiles()
        self.cards = []
        if not profiles:
            self.status.setText("No light yet. Add one with its Device ID and Local Key, or import a profile exported from another computer.")
            self.status.show()
        else:
            self.status.hide()
        for profile in profiles:
            card = ProfileCard(profile, self.export_profile, self.remove_profile)
            self.cards.append(card)
            self.list.addWidget(card)

    def refresh(self, info: dict) -> None:
        t = tokens()
        connected = bool(info.get("connected"))
        for card in getattr(self, "cards", []):
            card.dot.set_colour(t.success if connected else t.danger)

    def add_light(self) -> None:
        def save(fields):
            profile = self.controller.add_profile(**fields)
            self.controller.notice.emit(f"Saved {profile.name}. Connecting over your network…", "success")

        LightDialog(save, self.window()).exec()

    def import_profile(self) -> None:
        source, _ = QFileDialog.getOpenFileName(self.window(), "Import a TuyaSync light profile", "", PROFILE_FILTER)
        if not source:
            return
        try:
            profile = self.controller.import_profile(source)
        except ProfileStoreError as error:
            QMessageBox.warning(self.window(), "Couldn't import the light", str(error))
            return
        self.controller.notice.emit(f"{profile.name} is ready on this computer.", "success")

    def export_profile(self, profile: LightProfile) -> None:
        destination, _ = QFileDialog.getSaveFileName(self.window(), "Export light profile", f"{profile.name}.tuyasync-profile.json", PROFILE_FILTER)
        if not destination:
            return
        try:
            self.controller.export_profile(profile, destination)
        except ProfileStoreError as error:
            QMessageBox.warning(self.window(), "Couldn't export the light", str(error))
            return
        self.controller.notice.emit("Exported. Keep the file private: it contains the Local Key.", "success")

    def remove_profile(self, profile: LightProfile) -> None:
        answer = QMessageBox.question(
            self.window(),
            "Remove light",
            f"Remove {profile.name} from this computer? Its saved Local Key will be deleted.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.remove_profile(profile)
        except ProfileStoreError as error:
            QMessageBox.warning(self.window(), "Couldn't remove the light", str(error))


class CalibrationTab(QWidget):
    def __init__(self, controller: AppController):
        super().__init__()
        self.controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        gains = Card("Colour calibration", "Correct the light's own colour output. Applies to Screen sync and manual colours.")
        self.sliders: dict[str, SliderRow] = {}
        for key, title in (("red_gain", "Red"), ("green_gain", "Green"), ("blue_gain", "Blue")):
            gains.add(self._slider(key, title, None, 0.5, 1.5, 0.05, _times))
        gains.add(self._slider("output_saturation", "Saturation", "Richness of colour at the light.", 0.5, 1.5, 0.05, _times))
        gains.add(self._slider("output_gamma", "Output gamma", "Final intensity curve at the light.", 0.5, 1.8, 0.05, lambda v: f"{v:.2f}"))
        layout.addWidget(gains)

        pipeline = Card("Live pipeline", "Calculated values only. The captured screen itself is never shown or stored.")
        swatches = QHBoxLayout()
        swatches.setSpacing(18)
        self.swatches = {}
        for key, title in (("raw_rgb", "Calculated"), ("smoothed_rgb", "Smoothed"), ("final_rgb", "Sent to light")):
            column = QVBoxLayout()
            column.setSpacing(6)
            swatch = Swatch((0, 0, 0), 44, checkable=False)
            swatch.setCursor(Qt.CursorShape.ArrowCursor)
            self.swatches[key] = (swatch, label("—", "mono"))
            column.addWidget(swatch, 0, Qt.AlignmentFlag.AlignHCenter)
            column.addWidget(label(title, "hint"), 0, Qt.AlignmentFlag.AlignHCenter)
            column.addWidget(self.swatches[key][1], 0, Qt.AlignmentFlag.AlignHCenter)
            swatches.addLayout(column)
        swatches.addStretch(1)
        pipeline.body.addLayout(swatches)
        self.grid = ValueGrid((
            ("final_brightness", "Final brightness"),
            ("actual_command_rate", "Command rate"),
            ("region", "Selected region"),
            ("black", "Black scene"),
        ))
        pipeline.add(self.grid)
        layout.addWidget(pipeline)
        controller.screenSettingsChanged.connect(self.sync)

    def _slider(self, key, title, description, minimum, maximum, step, fmt) -> SliderRow:
        row = SliderRow(title, description, minimum, maximum, getattr(self.controller.screen, key), step, fmt)
        row.valueChanged.connect(lambda value, k=key: self.controller.update_screen(**{k: value}))
        self.sliders[key] = row
        return row

    def sync(self) -> None:
        for key, row in self.sliders.items():
            row.set_value(getattr(self.controller.screen, key))

    def refresh(self, snapshot: dict) -> None:
        for key, (swatch, text) in self.swatches.items():
            rgb = snapshot.get(key, (0, 0, 0))
            swatch.set_rgb(rgb)
            text.setText(rgb_text(rgb))
        self.grid.set("final_brightness", f"{snapshot.get('final_brightness', 0) * 100:.1f}%")
        self.grid.set("actual_command_rate", f"{snapshot.get('actual_command_rate', 0):.1f} Hz")
        self.grid.set("region", f"{snapshot.get('selected_region', '—')} in {snapshot.get('analysis_size', '—')} · source {snapshot.get('source_size', '—')}")
        self.grid.set("black", "Yes" if snapshot.get("is_black") else "No")


class DiagnosticsTab(QWidget):
    ROWS = (
        ("connection", "Connection"),
        ("connection_message", "Detail"),
        ("device", "Address"),
        ("retry", "Reconnects"),
        ("last_error", "Last error"),
        ("mode", "Active mode"),
        ("monitor", "Display"),
        ("transport", "Colour command"),
        ("capture_fps", "Capture"),
        ("processing_fps", "Processing"),
        ("requested_hz", "Requested max rate"),
        ("lighting_hz", "Sent rate"),
        ("average_latency_ms", "Average latency"),
        ("p95_latency_ms", "P95 latency"),
        ("deadband_skips", "Deadband skips"),
        ("rate_limit_skips", "Rate-limit skips"),
        ("overwritten_states", "Replaced stale states"),
        ("processing_failures", "Processing failures"),
        ("failed_commands", "Command failures"),
        ("final_rgb", "Final colour"),
    )

    def __init__(self, controller: AppController):
        super().__init__()
        self.controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        card = Card("Diagnostics", "A live view of the capture, connection, and command path. Skips are intentional and are not failures.")
        self.grid = ValueGrid(self.ROWS)
        card.add(self.grid)
        layout.addWidget(card)

    def refresh(self, snapshot: dict, info: dict) -> None:
        from screensync.gui.controller import MODE_LABELS

        g = self.grid
        g.set("connection", "Connected" if info.get("connected") else str(info.get("state", "disconnected")).title())
        g.set("connection_message", str(info.get("message", "—")))
        g.set("device", f"{info.get('ip', '—')} · Tuya {info.get('protocol', '—')}")
        g.set("retry", f"{info.get('reconnect_count', 0)} reconnects · {info.get('failure_count', 0)} failures · retry in {float(info.get('retry_in', 0.0)):.1f}s")
        g.set("last_error", str(info.get("last_error") or "—")[:80])
        g.set("mode", MODE_LABELS.get(self.controller.active_mode, "—"))
        g.set("monitor", self.controller.monitor_label())
        g.set("transport", self.controller.coordinator.get_settings().output_transport)
        g.set("capture_fps", f"{snapshot.get('capture_fps', 0):.1f} fps")
        g.set("processing_fps", f"{snapshot.get('processing_fps', 0):.1f} fps")
        g.set("requested_hz", f"{self.controller.screen.update_rate:.0f} Hz")
        g.set("lighting_hz", f"{snapshot.get('lighting_hz', 0):.1f} Hz")
        g.set("average_latency_ms", f"{snapshot.get('average_latency_ms', 0):.1f} ms")
        g.set("p95_latency_ms", f"{snapshot.get('p95_latency_ms', 0):.1f} ms")
        for key in ("deadband_skips", "rate_limit_skips", "overwritten_states", "processing_failures", "failed_commands"):
            g.set(key, str(snapshot.get(key, 0)))
        g.set("final_rgb", rgb_text(snapshot.get("final_rgb", (0, 0, 0))))


class GeneralTab(QWidget):
    def __init__(self, controller: AppController, quit_app):
        super().__init__()
        self.controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        saving = Card("Saving", "Changes are saved automatically. Settings files hold tuning only, never light credentials.")
        path = controller.settings_path
        saving.add(label(str(path) if path else "Not saved in this session", "mono", wrap=True))
        row = QHBoxLayout()
        row.setSpacing(8)
        if path:
            row.addWidget(button("Show in folder", None, lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))))
        row.addWidget(button("Reset Screen settings…", None, self._reset))
        row.addStretch(1)
        saving.body.addLayout(row)
        layout.addWidget(saving)

        background = Card("Running in the background", "Closing the window keeps TuyaSync running in the menu bar or system tray, so your light keeps syncing.")
        background.add(button("Quit TuyaSync", "danger", quit_app))
        background.body.itemAt(background.body.count() - 1).setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(background)

    def _reset(self) -> None:
        answer = QMessageBox.question(self.window(), "Reset Screen settings", "Put every Screen and calibration setting back to its default?")
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.reset_screen_defaults()
            self.controller.notice.emit("Screen settings reset to defaults.", "success")


class SettingsPage(Page):
    TABS = (("light", "Light"), ("calibration", "Calibration"), ("diagnostics", "Diagnostics"), ("general", "General"))

    def __init__(self, controller: AppController, quit_app):
        super().__init__("Settings", "Your light, calibration, and what's happening under the hood.")
        self.controller = controller
        self.tabs = Segmented(self.TABS, "light")
        self.tabs.setMaximumWidth(520)
        self.add(self.tabs)
        self.light = LightTab(controller)
        self.calibration = CalibrationTab(controller)
        self.diagnostics = DiagnosticsTab(controller)
        self.general = GeneralTab(controller, quit_app)
        # Plain show/hide rather than a QStackedWidget, so the page is only as
        # tall as the visible tab.
        self.tab_widgets = {"light": self.light, "calibration": self.calibration, "diagnostics": self.diagnostics, "general": self.general}
        for widget in self.tab_widgets.values():
            self.add(widget)
        self.finish()
        self.current_tab = "light"
        self.tabs.changed.connect(self.show_tab)
        self.show_tab("light")

    def show_tab(self, key: str) -> None:
        self.current_tab = key
        self.tabs.set_value(key)
        for name, widget in self.tab_widgets.items():
            widget.setVisible(name == key)
        self.verticalScrollBar().setValue(0)

    def on_mode(self, _mode: str) -> None:
        pass

    def refresh(self, snapshot: dict, info: dict) -> None:
        if not self.isVisible():
            return
        current = self.current_tab
        if current == "light":
            self.light.refresh(info)
        elif current == "calibration":
            self.calibration.refresh(snapshot)
        elif current == "diagnostics":
            self.diagnostics.refresh(snapshot, info)
