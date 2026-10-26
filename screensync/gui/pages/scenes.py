"""Scenes: colour sequences the light plays on its own."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QMessageBox, QVBoxLayout

from screensync.gui.controller import AppController
from screensync.gui.dialogs import SceneEditor
from screensync.gui.icons import icon
from screensync.gui.pages.common import ModeHero, pct
from screensync.gui.widgets import Card, Page, PaletteStrip, SliderRow, button, label, repolish, tokens
from screensync.scenes import ScenePreset, SceneStop


class SceneTile(QFrame):
    def __init__(self, scene: ScenePreset, on_pick):
        super().__init__()
        self.scene = scene
        self.setProperty("inset", True)
        self.setProperty("clickable", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(PaletteStrip([stop.color for stop in scene.stops], height=54))
        row = QHBoxLayout()
        row.addWidget(label(scene.name, "value"), 1)
        if not scene.builtin:
            badge = label("Custom")
            badge.setProperty("badge", True)
            row.addWidget(badge)
        layout.addLayout(row)
        self._on_pick = on_pick

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_pick(self.scene.name)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._on_pick(self.scene.name, play=True)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        repolish(self)


class NewSceneTile(QFrame):
    def __init__(self, on_click):
        super().__init__()
        self.setProperty("inset", True)
        self.setProperty("clickable", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        plus = label()
        plus.setPixmap(icon("plus", tokens().secondary, 26).pixmap(26, 26))
        plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(plus)
        text = label("New scene", "hint")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text)
        layout.addStretch(1)
        self._on_click = on_click

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click()


class ScenesPage(Page):
    def __init__(self, controller: AppController):
        super().__init__("Scenes", "Moods the light plays by itself. Your computer doesn't need to stay busy while a scene runs.")
        self.controller = controller
        self._cycle = 0

        self.hero = ModeHero(controller, "scenes")
        self.add(self.hero)
        if controller.scenes_mode is None:
            self.hero.action.setEnabled(False)

        library = Card("Library", "Click to choose, double-click to play. Changing scenes while one is playing switches straight away.")
        self.grid = QGridLayout()
        self.grid.setSpacing(12)
        library.body.addLayout(self.grid)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.edit_button = button("Edit", None, self._edit)
        self.delete_button = button("Delete", "danger", self._delete)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        library.body.addLayout(actions)
        self.add(library)

        tuning = Card()
        self.brightness = SliderRow("Maximum brightness", "Ceiling applied to every colour in the scene.", 10, 100, controller.scene_brightness, 5, pct)
        self.brightness.committed.connect(controller.set_scene_brightness)
        tuning.add(self.brightness)
        self.add(tuning)
        self.finish()

        self.tiles: dict[str, SceneTile] = {}
        self._build_tiles()
        controller.scenesChanged.connect(self._build_tiles)
        controller.sceneSelected.connect(lambda _name: self._mark())

    def _build_tiles(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.tiles = {}
        columns = 3
        for index, scene in enumerate(self.controller.scenes):
            tile = SceneTile(scene, self._pick)
            self.tiles[scene.name] = tile
            self.grid.addWidget(tile, index // columns, index % columns)
        count = len(self.controller.scenes)
        self.grid.addWidget(NewSceneTile(self._new), count // columns, count % columns)
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)
        self._mark()

    def _mark(self) -> None:
        for name, tile in self.tiles.items():
            tile.set_selected(name == self.controller.scene_name)
        scene = self.controller.selected_scene()
        self.edit_button.setEnabled(scene is not None)
        self.edit_button.setText("Customise a copy" if scene is not None and scene.builtin else "Edit")
        self.delete_button.setVisible(scene is not None and not scene.builtin)

    def _pick(self, name: str, play: bool = False) -> None:
        self.controller.select_scene(name)
        self._mark()
        if play and self.controller.active_mode != "scenes":
            self.controller.switch_mode("scenes")

    def _new(self) -> None:
        scene = ScenePreset(self.controller.unique_scene_name("My scene"), [SceneStop((255, 70, 160), 700, 4, 0), SceneStop((60, 120, 255), 700, 4, 0)], loop=True, builtin=False)
        self._open_editor(scene, None)

    def _edit(self) -> None:
        scene = self.controller.selected_scene()
        if scene is None:
            return
        if scene.builtin:
            copy = ScenePreset(self.controller.unique_scene_name(f"My {scene.name}"), list(scene.stops), scene.loop, builtin=False)
            self._open_editor(copy, None)
        else:
            self._open_editor(ScenePreset(scene.name, list(scene.stops), scene.loop, builtin=False), scene.name)

    def _open_editor(self, scene: ScenePreset, previous_name: str | None) -> None:
        editor = SceneEditor(scene, self.controller.preview_scene, self.window())
        if editor.exec():
            self.controller.save_scene(editor.result_scene(), previous_name)

    def _delete(self) -> None:
        scene = self.controller.selected_scene()
        if scene is None or scene.builtin:
            return
        answer = QMessageBox.question(self.window(), "Delete scene", f"Delete “{scene.name}”? This can't be undone.")
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.delete_scene(scene.name)

    def on_mode(self, mode: str) -> None:
        self.hero.set_running(mode == "scenes")

    def refresh(self, _snapshot: dict, _info: dict) -> None:
        if not self.isVisible():
            return
        running = self.controller.active_mode == "scenes"
        scene = self.controller.selected_scene()
        playing = getattr(self.controller.scenes_mode, "scene", None) if running else None
        shown = playing or scene
        if shown is None:
            self.hero.orb.set_state(None, 0.0, False)
            self.hero.set_text("No scene selected", "Pick one from the library below.")
            return
        self._cycle = (self._cycle + 1) % (len(shown.stops) * 8)
        stop = shown.stops[self._cycle // 8]
        self.hero.orb.set_state(stop.color, 0.35 + 0.65 * stop.brightness / 1000, True)
        loop = "loops on the light" if shown.loop else "plays once"
        if running:
            self.hero.set_text(f"Playing {shown.name}", f"{len(shown.stops)} colours · {loop} · up to {self.controller.scene_brightness:.0f}% brightness")
        else:
            self.hero.set_text(shown.name, f"{len(shown.stops)} colours · {loop}")
