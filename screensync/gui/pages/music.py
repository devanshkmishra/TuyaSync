"""Music sync: the light follows audio playing on this computer."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QVBoxLayout

from screensync.gui.controller import COLOUR_RESPONSES, AppController
from screensync.gui.pages.common import ModeHero, pct
from screensync.gui.widgets import Card, Meter, Page, PaletteStrip, Section, SegmentRow, SliderRow, label, repolish
from screensync.modes.music import PALETTES

RESPONSE_COPY = {
    "Immediate flash": "Each beat jumps straight to the next palette colour.",
    "Smooth blend": "Each beat eases into the next palette colour.",
}


class PaletteTile(QFrame):
    def __init__(self, name: str, colours, on_pick):
        super().__init__()
        self.name = name
        self.setProperty("inset", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)
        layout.addWidget(PaletteStrip(colours, height=26))
        layout.addWidget(label(name, "value"))
        self._on_pick = on_pick

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_pick(self.name)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        repolish(self)


class MusicPage(Page):
    def __init__(self, controller: AppController):
        super().__init__("Music", "Colours and brightness move with whatever is playing on this computer. The microphone is never used.")
        self.controller = controller
        settings = controller.music

        self.hero = ModeHero(controller, "music")
        meters = QHBoxLayout()
        meters.setSpacing(6)
        self.meters = {
            "energy": Meter("#22D3EE", "Energy"),
            "beat": Meter("#7C5CFF", "Beat"),
            "pulse": Meter("#EC4899", "Pulse"),
        }
        for meter in self.meters.values():
            meters.addWidget(meter)
        self.hero.side.addLayout(meters)
        self.add(self.hero)
        if controller.music_mode is None:
            self.hero.action.setEnabled(False)

        palette = Card("Palette", "The colours the light moves through on each beat.")
        grid = QGridLayout()
        grid.setSpacing(10)
        self.tiles: dict[str, PaletteTile] = {}
        for index, (name, colours) in enumerate(PALETTES.items()):
            tile = PaletteTile(name, colours, self._palette)
            self.tiles[name] = tile
            grid.addWidget(tile, index // 3, index % 3)
        palette.body.addLayout(grid)
        self.response = SegmentRow("On each beat", [(key, key) for key in COLOUR_RESPONSES], settings.colour_response, RESPONSE_COPY.get)
        self.response.changed.connect(lambda value: controller.update_music(colour_response=value))
        palette.add(self.response)
        self.add(palette)

        feel = Card("Feel")
        self.intensity = self._slider(feel, "intensity", "Intensity", "Overall strength of the effect.", 10, 100)
        self.reactivity = self._slider(feel, "reactivity", "Reactivity", "How quickly colour and brightness follow the music.", 10, 100)
        self.beat = self._slider(feel, "bass_impact", "Beat impact", "How much each beat lifts the brightness.", 0, 100)
        self.add(feel)

        brightness = Section("Brightness range", "The resting level in quiet passages and the ceiling for loud ones.")
        self.minimum = self._slider(brightness, "minimum_brightness", "Minimum brightness", None, 1, 60)
        self.maximum = self._slider(brightness, "maximum_brightness", "Maximum brightness", None, 10, 100)
        self.add(brightness)
        self.finish()
        self._mark_palette(settings.palette)

    def _slider(self, parent, key, title, description, minimum, maximum) -> SliderRow:
        row = SliderRow(title, description, minimum, maximum, getattr(self.controller.music, key) * 100, 1, pct)
        row.valueChanged.connect(lambda value, k=key: self.controller.update_music(**{k: value / 100}))
        parent.add(row)
        return row

    def _palette(self, name: str) -> None:
        self.controller.update_music(palette=name)
        self._mark_palette(name)

    def _mark_palette(self, name: str) -> None:
        for key, tile in self.tiles.items():
            tile.set_selected(key == name)

    def on_mode(self, mode: str) -> None:
        self.hero.set_running(mode == "music")

    def refresh(self, _snapshot: dict, _info: dict) -> None:
        if not self.isVisible():
            return
        running = self.controller.active_mode == "music"
        if self.controller.music_mode is None:
            self.hero.set_text("System audio is unavailable", "TuyaSync couldn't open an audio capture backend on this computer.")
            return
        status = self.controller.music_status()
        error = str(status.get("error") or status.get("last_error") or "")
        energy = float(status.get("normalized_energy", 0.0)) if running else 0.0
        beat = float(status.get("beat_strength", 0.0)) if running else 0.0
        pulse = float(status.get("pulse", 0.0)) if running else 0.0
        self.meters["energy"].set_value(energy)
        self.meters["beat"].set_value(beat)
        self.meters["pulse"].set_value(pulse)
        colour = status.get("colour", (128, 128, 128))
        self.hero.orb.set_state(colour, 0.35 + 0.65 * max(energy, pulse), running)
        if status.get("beat") and running:
            self.hero.orb.pulse(1.0)
        if error:
            self.hero.set_text("Can't hear system audio", error)
        elif running:
            self.hero.set_text(
                "Listening to system audio",
                f"{status.get('backend', 'System audio')} · {int(status.get('beat_count', 0))} beats · {self.controller.music.palette}",
            )
        else:
            self.hero.set_text("Music sync is off", f"{self.controller.music.palette} palette · {self.controller.music.colour_response.lower()}")
