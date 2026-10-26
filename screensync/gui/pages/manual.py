"""Manual control: the light does exactly what you pick."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QHBoxLayout

from screensync.gui.controller import MODE_LABELS, AppController
from screensync.gui.icons import icon
from screensync.gui.pages.common import ModeHero, pct
from screensync.gui.widgets import Card, Page, PaletteStrip, SliderRow, Swatch, button, hbox

PRESETS = (
    (255, 55, 55),
    (255, 120, 30),
    (255, 190, 40),
    (40, 215, 110),
    (30, 210, 220),
    (35, 120, 255),
    (130, 70, 255),
    (255, 70, 190),
    (255, 255, 255),
)


def _kelvin_preview(value: float) -> tuple[int, int, int]:
    """Approximate the white LEDs' tone for the preview (0 = warm, 1000 = cool)."""
    warm, cool = (255, 176, 92), (205, 225, 255)
    mix = max(0.0, min(1.0, value / 1000))
    return tuple(round(a + (b - a) * mix) for a, b in zip(warm, cool))


class ManualPage(Page):
    def __init__(self, controller: AppController):
        super().__init__("Manual", "No automatic mode is running. Set the light yourself, or start a mode from the sidebar.")
        self.controller = controller
        self._kind = "colour"

        self.hero = ModeHero(controller, "off")
        self.hero.action.hide()
        self.hero.badge.hide()
        on = button("  Turn on", "primary", lambda: controller.power(True))
        on.setIcon(icon("power", "#FFFFFF", 16))
        off = button("Turn off", None, lambda: controller.power(False))
        self.hero.secondary_actions.insertWidget(1, on)
        self.hero.secondary_actions.insertWidget(2, off)
        self.add(self.hero)

        colour = Card("Colour", "Picking a colour stops any running mode.")
        swatches = QHBoxLayout()
        swatches.setSpacing(8)
        self.swatches: list[Swatch] = []
        for rgb in PRESETS:
            swatch = Swatch(rgb, 36)
            swatch.clicked.connect(lambda _checked=False, value=rgb: self._pick(value))
            self.swatches.append(swatch)
            swatches.addWidget(swatch)
        swatches.addSpacing(6)
        swatches.addWidget(button("Custom…", None, self._custom))
        swatches.addStretch(1)
        colour.body.addLayout(swatches)
        self.brightness = SliderRow("Brightness", None, 1, 100, controller.manual_brightness, 1, pct)
        self.brightness.valueChanged.connect(self._preview)
        self.brightness.committed.connect(self._brightness)
        colour.add(self.brightness)
        self.add(colour)

        white = Card("White light", "Uses the dedicated white LEDs instead of mixing RGB.")
        self.temperature = SliderRow("Colour temperature", None, 0, 1000, controller.manual_temperature, 10, self._temperature_text)
        self.temperature.valueChanged.connect(lambda _value: self._preview())
        self.temperature.committed.connect(lambda value: self._white(temperature=value))
        white.add(self.temperature)
        white.add(PaletteStrip((_kelvin_preview(0), _kelvin_preview(500), _kelvin_preview(1000)), height=8))
        white.add(hbox(button("Use white light", None, lambda: self._white()), None))
        self.add(white)
        self.finish()

        controller.manualResult.connect(self._result)
        self._select_swatch(controller.manual_rgb)
        self._preview()

    @staticmethod
    def _temperature_text(value: float) -> str:
        if value < 250:
            tone = "Warm"
        elif value > 750:
            tone = "Cool"
        else:
            tone = "Neutral"
        return f"{tone} · {value:.0f}"

    def _select_swatch(self, rgb) -> None:
        for swatch in self.swatches:
            swatch.setChecked(tuple(swatch.rgb) == tuple(rgb))

    def _preview(self, *_args) -> None:
        rgb = self.controller.manual_rgb if self._kind == "colour" else _kelvin_preview(self.temperature.value())
        level = self.brightness.value() / 100
        self.hero.orb.set_state(rgb, 0.25 + 0.75 * level, True)
        if self._kind == "colour":
            text = "Colour · #%02X%02X%02X" % tuple(self.controller.manual_rgb)
        else:
            text = f"White light · {self._temperature_text(self.temperature.value())}"
        self.hero.set_text("Manual control", f"{text} · {level * 100:.0f}% brightness")

    def _pick(self, rgb) -> None:
        self._kind = "colour"
        self._select_swatch(rgb)
        self.controller.set_manual_colour(rgb, self.brightness.value())
        self._preview()

    def _custom(self) -> None:
        colour = QColorDialog.getColor(QColor(*self.controller.manual_rgb), self, "Choose a colour")
        if colour.isValid():
            self._pick((colour.red(), colour.green(), colour.blue()))

    def _brightness(self, value: float) -> None:
        if self._kind == "colour":
            self.controller.set_manual_colour(brightness=value)
        else:
            self.controller.set_manual_white(brightness=value)

    def _white(self, temperature: float | None = None) -> None:
        self._kind = "white"
        self._select_swatch((-1, -1, -1))
        self.controller.set_manual_white(self.brightness.value(), temperature if temperature is not None else self.temperature.value())
        self._preview()

    def _result(self, ok: bool, detail: str) -> None:
        if not ok:
            self.controller.notice.emit(f"The light didn't respond ({detail}).", "error")

    def refresh(self, _snapshot: dict, _info: dict) -> None:
        pass

    def on_mode(self, mode: str) -> None:
        if mode == "off":
            self.subtitle_label.setText("No automatic mode is running. Set the light yourself, or start a mode from the sidebar.")
        else:
            self.subtitle_label.setText(f"{MODE_LABELS[mode]} is running. Choosing a colour or white light here will stop it.")
