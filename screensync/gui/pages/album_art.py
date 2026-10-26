"""Album Art: the light takes its colours from the current Spotify cover."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget

from screensync.gui.controller import ALBUM_PALETTES, COLOUR_RESPONSES, AppController
from screensync.gui.pages.common import ModeHero, pct
from screensync.gui.widgets import Card, Page, PaletteStrip, Section, SegmentRow, SliderRow, ToggleRow, tokens

PALETTE_NAMES = {"Single color": "One colour", "Two colors": "Two colours", "Three colors": "Three colours"}


class Artwork(QWidget):
    """Cover art with a soft glow in the colour the light is showing."""

    def __init__(self, size: int = 150):
        super().__init__()
        self._size = size
        self.setFixedSize(size + 40, size + 40)
        self._pixmap: QPixmap | None = None
        self._glow = QColor(0, 0, 0, 0)
        self._key = None

    def set_artwork(self, data: bytes | None) -> None:
        key = hash(data) if data else None
        if key == self._key:
            return
        self._key = key
        self._pixmap = None
        if data:
            image = QImage.fromData(data)
            if not image.isNull():
                self._pixmap = QPixmap.fromImage(image)
        self.update()

    def set_glow(self, rgb, active: bool) -> None:
        colour = QColor(*[max(0, min(255, int(v))) for v in rgb])
        colour.setAlpha(140 if active else 0)
        self._glow = colour
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(20, 20, self._size, self._size)
        if self._glow.alpha():
            for spread in range(18, 0, -2):
                alpha = int(self._glow.alpha() * 0.09 * (1 - spread / 20))
                colour = QColor(self._glow)
                colour.setAlpha(alpha)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(colour)
                painter.drawRoundedRect(rect.adjusted(-spread, -spread, spread, spread), 18 + spread, 18 + spread)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        painter.setClipPath(path)
        if self._pixmap is None:
            painter.fillRect(rect, QColor(t.surface_alt))
            painter.setPen(QColor(t.tertiary))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No artwork")
        else:
            scaled = self._pixmap.scaled(
                int(rect.width() * self.devicePixelRatioF()),
                int(rect.height() * self.devicePixelRatioF()),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(self.devicePixelRatioF())
            painter.drawPixmap(rect.topLeft(), scaled)


class AlbumArtPage(Page):
    def __init__(self, controller: AppController):
        super().__init__("Album Art", "The light takes its colours from the cover of whatever Spotify is playing. No Spotify sign-in needed.")
        self.controller = controller
        settings = controller.album

        self.artwork = Artwork(150)
        self.hero = ModeHero(controller, "album_art", visual=self.artwork)
        self.palette_strip = PaletteStrip((), height=12, smooth=False)
        self.palette_strip.setMaximumWidth(220)
        self.hero.extra.addWidget(self.palette_strip)
        self.add(self.hero)
        if controller.album_art_mode is None:
            self.hero.action.setEnabled(False)

        colours = Card("Colours")
        self.palette = SegmentRow(
            "Colours from the cover",
            [(key, PALETTE_NAMES[key]) for key in ALBUM_PALETTES],
            settings.palette_mode,
            lambda key: "Holds the cover's main colour." if key == "Single color" else "Moves between the cover's main colours.",
        )
        self.palette.changed.connect(lambda value: controller.update_album(palette_mode=value))
        colours.add(self.palette)
        self.intensity = self._slider(colours, "intensity", "Intensity", "Overall light level while a track plays.", 10, 100)
        self.add(colours)

        beats = Card("Beat reaction", "Optionally use system audio to pulse with the music.")
        self.reactive = ToggleRow("React to beats", "Drift through the palette and add short brightness accents.", settings.music_reactive)
        self.reactive.toggled.connect(self._reactive)
        beats.add(self.reactive)
        self.response = SegmentRow("On each beat", [(key, key) for key in COLOUR_RESPONSES], settings.colour_response)
        self.response.changed.connect(lambda value: controller.update_album(colour_response=value))
        beats.add(self.response)
        self.reactivity = self._slider(beats, "reactivity", "Responsiveness", "How quickly beats and brightness changes show.", 10, 100)
        self.beat = self._slider(beats, "beat_impact", "Beat impact", "How much brighter each beat makes the light.", 0, 100)
        self.add(beats)

        brightness = Section("Brightness", "Floor, ceiling, and the level held while Spotify is paused.")
        self._slider(brightness, "minimum_brightness", "Minimum brightness", None, 0, 80)
        self._slider(brightness, "maximum_brightness", "Maximum brightness", None, 10, 100)
        self._slider(brightness, "paused_intensity", "While paused", "Level held when the track is paused.", 0, 100)
        self.add(brightness)
        self.finish()
        self._reactive_enabled(settings.music_reactive)

    def _slider(self, parent, key, title, description, minimum, maximum) -> SliderRow:
        row = SliderRow(title, description, minimum, maximum, getattr(self.controller.album, key) * 100, 1, pct)
        row.valueChanged.connect(lambda value, k=key: self.controller.update_album(**{k: value / 100}))
        parent.add(row)
        return row

    def _reactive(self, checked: bool) -> None:
        self.controller.update_album(music_reactive=checked)
        self._reactive_enabled(checked)

    def _reactive_enabled(self, enabled: bool) -> None:
        for widget in (self.response, self.reactivity, self.beat):
            widget.setEnabled(enabled)

    def on_mode(self, mode: str) -> None:
        self.hero.set_running(mode == "album_art")

    def refresh(self, _snapshot: dict, _info: dict) -> None:
        if not self.isVisible():
            return
        mode = self.controller.album_art_mode
        if mode is None:
            self.hero.set_text("Album Art is unavailable", "TuyaSync couldn't read Spotify's local now-playing data on this computer.")
            return
        running = self.controller.active_mode == "album_art"
        current = mode.current()
        diagnostics = mode.diagnostics()
        rgb = tuple(int(v) for v in diagnostics.get("current_rgb", diagnostics.get("extracted_rgb", (128, 128, 128))))
        palette = [tuple(int(c) for c in colour) for colour in diagnostics.get("extracted_palette", (rgb,))]
        self.palette_strip.set_colours(palette)
        self.palette_strip.setVisible(current.has_track)
        self.artwork.set_glow(rgb, running and current.has_track)
        try:
            self.artwork.set_artwork(mode.artwork() if current.has_track else None)
        except Exception:
            self.artwork.set_artwork(None)
        if current.has_track:
            meta = " · ".join(part for part in (current.artist, current.album) if part)
            if not current.is_playing:
                state = "Paused · holding the colour at a lower brightness"
            elif not running:
                state = "Start Album Art to light the room with this cover"
            elif mode.settings.music_reactive:
                state = "Playing · reacting to beats"
            else:
                state = "Playing"
            self.hero.set_text(current.title or "Untitled track", f"{meta}\n{state}" if meta else state)
        else:
            self.hero.set_text("Nothing playing", "Play something in the Spotify desktop app and the cover will appear here.")
