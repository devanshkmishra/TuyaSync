"""Reusable building blocks for the TuyaSync interface."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from screensync.gui import theme


Rgb = tuple[int, int, int]


def rgb_hex(rgb: Sequence[float]) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(value))) for value in rgb)


def rgb_text(rgb: Sequence[float]) -> str:
    return "%d, %d, %d" % tuple(int(value) for value in rgb)


def tokens() -> theme.Tokens:
    return theme.current_tokens()


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    if wrap:
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return widget


def button(text: str, kind: str | None = None, on_click: Callable[[], object] | None = None) -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if kind:
        widget.setProperty("kind", kind)
    if on_click is not None:
        widget.clicked.connect(lambda _checked=False: on_click())
    return widget


def link_button(text: str, on_click: Callable[[], object]) -> QPushButton:
    widget = QPushButton(text)
    widget.setProperty("link", True)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(lambda _checked=False: on_click())
    return widget


def divider() -> QFrame:
    line = QFrame()
    line.setProperty("divider", True)
    return line


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class Card(QFrame):
    """A rounded surface with an optional title and subtitle."""

    def __init__(self, title: str | None = None, subtitle: str | None = None, inset: bool = False, spacing: int = 14):
        super().__init__()
        self.setProperty("inset" if inset else "card", True)
        self.body = QVBoxLayout(self)
        margin = 16 if inset else 22
        self.body.setContentsMargins(margin, margin, margin, margin)
        self.body.setSpacing(spacing)
        if title:
            header = QVBoxLayout()
            header.setSpacing(3)
            header.addWidget(label(title, "title"))
            if subtitle:
                header.addWidget(label(subtitle, "subtitle", wrap=True))
            self.body.addLayout(header)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body.addWidget(widget, stretch)
        return widget


class Page(QScrollArea):
    """A scrolling page with a large heading and a column of content."""

    def __init__(self, title: str, subtitle: str, max_width: int = 860):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("Content")
        outer = QHBoxLayout(host)
        outer.setContentsMargins(36, 30, 36, 36)
        column = QWidget()
        column.setMaximumWidth(max_width)
        self.column = QVBoxLayout(column)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(18)
        outer.addStretch(0)
        outer.addWidget(column, 1)
        outer.addStretch(0)
        self.header = QHBoxLayout()
        self.header.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(label(title, "display"))
        self.subtitle_label = label(subtitle, "subtitle", wrap=True)
        titles.addWidget(self.subtitle_label)
        self.header.addLayout(titles, 1)
        self.column.addLayout(self.header)
        self.column.addSpacing(4)
        self.setWidget(host)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.column.addWidget(widget, stretch)
        return widget

    def finish(self) -> None:
        self.column.addStretch(1)


class Toggle(QAbstractButton):
    """An animated on/off switch."""

    def __init__(self, checked: bool = False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 26)
        self._offset = 1.0 if checked else 0.0
        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(160)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt naming
        super().setChecked(checked)
        if not hasattr(self, "_animation") or not self.isVisible():
            self._offset = 1.0 if checked else 0.0
            self.update()

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(46, 26)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        off = QColor(t.surface_hover if t.dark else "#D5D8E3")
        on = QColor(t.accent)
        mix = self._offset
        track = QColor(
            round(off.red() + (on.red() - off.red()) * mix),
            round(off.green() + (on.green() - off.green()) * mix),
            round(off.blue() + (on.blue() - off.blue()) * mix),
        )
        if not self.isEnabled():
            track.setAlpha(110)
        rect = QRectF(0, 0, self.width(), self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        knob = rect.height() - 6
        x = 3 + (rect.width() - knob - 6) * mix
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(x, 3, knob, knob))


class Segmented(QFrame):
    """A row of mutually exclusive options."""

    changed = Signal(str)

    def __init__(self, options: Sequence[str] | Sequence[tuple[str, str]], value: str | None = None):
        super().__init__()
        self.setObjectName("SegmentTrack")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for option in options:
            key, text = option if isinstance(option, tuple) else (option, option)
            item = QPushButton(text)
            item.setCheckable(True)
            item.setProperty("segment", True)
            item.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(item)
            self._buttons[key] = item
            layout.addWidget(item, 1)
            item.clicked.connect(lambda _checked=False, k=key: self.changed.emit(k))
        if value is not None:
            self.set_value(value)

    def value(self) -> str | None:
        for key, item in self._buttons.items():
            if item.isChecked():
                return key
        return None

    def set_value(self, value: str) -> None:
        if value in self._buttons:
            self._buttons[value].setChecked(True)


class Row(QWidget):
    """A labelled setting row: copy on the left, control on the right."""

    def __init__(self, title: str, description: str | None, control: QWidget, stacked: bool = False):
        super().__init__()
        layout = QVBoxLayout(self) if stacked else QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8 if stacked else 18)
        copy = QVBoxLayout()
        copy.setSpacing(2)
        copy.addWidget(label(title, "heading"))
        self.description = None
        if description:
            self.description = label(description, "hint", wrap=True)
            copy.addWidget(self.description)
        layout.addLayout(copy, 1)
        layout.addWidget(control, 0 if not stacked else 0)
        if not stacked:
            layout.setAlignment(control, Qt.AlignmentFlag.AlignVCenter)


class SliderRow(QWidget):
    """A labelled slider that displays its formatted value."""

    valueChanged = Signal(float)
    committed = Signal(float)

    def __init__(
        self,
        title: str,
        description: str | None,
        minimum: float,
        maximum: float,
        value: float,
        step: float = 1.0,
        fmt: Callable[[float], str] | str = "{:.0f}%",
    ):
        super().__init__()
        self._step = step
        self._minimum = minimum
        self._fmt = fmt
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        copy = QVBoxLayout()
        copy.setSpacing(2)
        copy.addWidget(label(title, "heading"))
        if description:
            copy.addWidget(label(description, "hint", wrap=True))
        top.addLayout(copy, 1)
        self.value_label = label("", "value")
        self.value_label.setMinimumWidth(56)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.value_label, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slider.setRange(0, max(1, round((maximum - minimum) / step)))
        self.slider.setPageStep(max(1, self.slider.maximum() // 10))
        layout.addWidget(self.slider)
        self.set_value(value)
        self.slider.valueChanged.connect(self._changed)
        self.slider.sliderReleased.connect(lambda: self.committed.emit(self.value()))
        self.slider.actionTriggered.connect(self._action)

    def _action(self, action) -> None:
        # Keyboard and page clicks change the value without a release event.
        if action not in (QSlider.SliderAction.SliderMove, QSlider.SliderAction.SliderNoAction):
            QTimer.singleShot(0, lambda: self.committed.emit(self.value()))

    def value(self) -> float:
        return round(self._minimum + self.slider.value() * self._step, 6)

    def set_value(self, value: float) -> None:
        blocked = self.slider.blockSignals(True)
        self.slider.setValue(round((float(value) - self._minimum) / self._step))
        self.slider.blockSignals(blocked)
        self._update_label()

    def _update_label(self) -> None:
        value = self.value()
        self.value_label.setText(self._fmt(value) if callable(self._fmt) else self._fmt.format(value))

    def _changed(self, _raw: int) -> None:
        self._update_label()
        self.valueChanged.emit(self.value())


class ToggleRow(Row):
    toggled = Signal(bool)

    def __init__(self, title: str, description: str | None, checked: bool):
        self.toggle = Toggle(checked)
        super().__init__(title, description, self.toggle)
        self.toggle.toggled.connect(self.toggled.emit)

    def set_checked(self, checked: bool) -> None:
        blocked = self.toggle.blockSignals(True)
        self.toggle.setChecked(checked)
        self.toggle.blockSignals(blocked)


class ChoiceRow(Row):
    changed = Signal(str)

    def __init__(self, title: str, description: str | None, options: Sequence[str], value: str):
        self.combo = QComboBox()
        self.combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo.addItems([str(option) for option in options])
        self.combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        super().__init__(title, description, self.combo)
        self.set_value(value)
        self.combo.currentTextChanged.connect(self.changed.emit)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt naming
        event.ignore()

    def set_value(self, value: str) -> None:
        blocked = self.combo.blockSignals(True)
        index = self.combo.findText(str(value))
        if index >= 0:
            self.combo.setCurrentIndex(index)
        self.combo.blockSignals(blocked)


class SegmentRow(QWidget):
    """A segmented choice with a description that follows the selection."""

    changed = Signal(str)

    def __init__(self, title: str, options: Sequence[tuple[str, str]], value: str, explain: Callable[[str], str] | None = None):
        super().__init__()
        self._explain = explain
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)
        layout.addWidget(label(title, "heading"))
        self.segments = Segmented(options, value)
        layout.addWidget(self.segments)
        self.hint = label("", "hint", wrap=True)
        layout.addWidget(self.hint)
        self.hint.setVisible(explain is not None)
        self.segments.changed.connect(self._changed)
        self._update_hint(value)

    def _changed(self, value: str) -> None:
        self._update_hint(value)
        self.changed.emit(value)

    def _update_hint(self, value: str) -> None:
        if self._explain:
            self.hint.setText(self._explain(value))

    def set_value(self, value: str) -> None:
        self.segments.set_value(value)
        self._update_hint(value)


class Section(QFrame):
    """A collapsible card for detail controls."""

    def __init__(self, title: str, subtitle: str = "", expanded: bool = False):
        super().__init__()
        self.setProperty("card", True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 14, 22, 14)
        outer.setSpacing(0)
        header = QHBoxLayout()
        self.toggle_button = QPushButton()
        self.toggle_button.setProperty("section", True)
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._title = title
        header.addWidget(self.toggle_button, 1)
        outer.addLayout(header)
        self.subtitle = label(subtitle, "hint", wrap=True) if subtitle else None
        if self.subtitle:
            outer.addWidget(self.subtitle)
        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 14, 0, 6)
        self.body.setSpacing(16)
        outer.addWidget(self.content)
        self.toggle_button.clicked.connect(lambda: self.set_expanded(not self.content.isVisible()))
        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool) -> None:
        self.content.setVisible(expanded)
        self.toggle_button.setText(("▾  " if expanded else "▸  ") + self._title)

    def add(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget)
        return widget


class Glow:
    """Colour helpers shared by painted widgets."""

    @staticmethod
    def blend(a: QColor, b: QColor, amount: float) -> QColor:
        amount = max(0.0, min(1.0, amount))
        return QColor(
            round(a.red() + (b.red() - a.red()) * amount),
            round(a.green() + (b.green() - a.green()) * amount),
            round(a.blue() + (b.blue() - a.blue()) * amount),
        )


class LightOrb(QWidget):
    """A glowing preview of what the physical light is showing right now."""

    def __init__(self, diameter: int = 150):
        super().__init__()
        self._diameter = diameter
        self.setFixedSize(diameter + 60, diameter + 60)
        self._colour = QColor(70, 76, 110)
        self._target = QColor(self._colour)
        self._level = 0.0
        self._target_level = 0.0
        self._active = False
        self._pulse = 0.0
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._step)
        self._timer.start()

    def set_state(self, rgb: Sequence[float] | None, level: float, active: bool) -> None:
        self._active = active
        if rgb is not None:
            self._target = QColor(*[max(0, min(255, int(value))) for value in rgb])
        self._target_level = max(0.0, min(1.0, float(level)))

    def pulse(self, amount: float) -> None:
        self._pulse = max(self._pulse, max(0.0, min(1.0, amount)))

    def _step(self) -> None:
        if not self.isVisible():
            return
        self._colour = Glow.blend(self._colour, self._target, 0.18)
        self._level += (self._target_level - self._level) * 0.18
        self._pulse *= 0.86
        self._phase = (self._phase + 0.025) % (2 * math.pi)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = QPointF(self.width() / 2, self.height() / 2)
        radius = self._diameter / 2
        level = self._level if self._active else 0.0
        breathing = 0.04 * math.sin(self._phase) if self._active else 0.0
        glow_strength = min(1.0, 0.25 + level * 0.75 + self._pulse * 0.4)

        if self._active and level > 0.01:
            halo = QRadialGradient(centre, radius * (1.35 + breathing + self._pulse * 0.12))
            core = QColor(self._colour)
            core.setAlpha(int(150 * glow_strength))
            fade = QColor(self._colour)
            fade.setAlpha(0)
            halo.setColorAt(0.55, core)
            halo.setColorAt(1.0, fade)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(halo))
            painter.drawEllipse(centre, radius * 1.4, radius * 1.4)

        base = QColor(t.surface_alt)
        fill = Glow.blend(base, self._colour, 0.25 + 0.75 * level) if self._active else base
        body = QRadialGradient(QPointF(centre.x() - radius * 0.3, centre.y() - radius * 0.35), radius * 1.4)
        body.setColorAt(0.0, fill.lighter(135 if self._active else 108))
        body.setColorAt(1.0, fill.darker(115))
        painter.setBrush(QBrush(body))
        ring = QColor(t.border) if not self._active else QColor(255, 255, 255, 40)
        painter.setPen(QPen(ring, 1.2))
        painter.drawEllipse(centre, radius, radius)

        if not self._active:
            painter.setPen(QPen(QColor(t.tertiary), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            r = radius * 0.28
            painter.drawArc(QRectF(centre.x() - r, centre.y() - r, r * 2, r * 2), 120 * 16, 300 * 16)
            painter.drawLine(QPointF(centre.x(), centre.y() - r * 1.15), QPointF(centre.x(), centre.y() - r * 0.2))


class Meter(QWidget):
    """A rounded vertical level meter."""

    def __init__(self, colour: str, title: str):
        super().__init__()
        self._colour = QColor(colour)
        self._value = 0.0
        self._target = 0.0
        self._title = title
        self.setMinimumSize(54, 150)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._step)
        self._timer.start()

    def set_value(self, value: float) -> None:
        self._target = max(0.0, min(1.0, float(value)))

    def _step(self) -> None:
        if not self.isVisible():
            return
        rate = 0.45 if self._target > self._value else 0.12
        self._value += (self._target - self._value) * rate
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text_height = 34
        width = min(22.0, self.width() * 0.5)
        track = QRectF((self.width() - width) / 2, 4, width, self.height() - text_height - 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.surface_hover))
        painter.drawRoundedRect(track, width / 2, width / 2)
        height = max(width, track.height() * self._value)
        fill = QRectF(track.left(), track.bottom() - height, width, height)
        gradient = QLinearGradient(fill.bottomLeft(), fill.topLeft())
        gradient.setColorAt(0, self._colour.darker(130))
        gradient.setColorAt(1, self._colour.lighter(115))
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(fill, width / 2, width / 2)
        painter.setPen(QColor(t.secondary))
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        painter.drawText(QRectF(0, self.height() - text_height, self.width(), 16), Qt.AlignmentFlag.AlignCenter, self._title)
        painter.setPen(QColor(t.text))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(0, self.height() - 17, self.width(), 16), Qt.AlignmentFlag.AlignCenter, f"{self._value * 100:.0f}%")


class PaletteStrip(QWidget):
    """A rounded gradient through a list of colours."""

    def __init__(self, colours: Sequence[Rgb] = (), height: int = 10, smooth: bool = True):
        super().__init__()
        self._colours = list(colours)
        self._smooth = smooth
        self.setFixedHeight(height)
        self.setMinimumWidth(40)

    def set_colours(self, colours: Sequence[Rgb]) -> None:
        self._colours = list(colours)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        radius = min(rect.height() / 2, 10)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)
        colours = self._colours or [(90, 96, 128)]
        if self._smooth:
            gradient = QLinearGradient(rect.topLeft(), rect.topRight())
            if len(colours) == 1:
                gradient.setColorAt(0, QColor(*colours[0]))
                gradient.setColorAt(1, QColor(*colours[0]))
            for index, colour in enumerate(colours):
                gradient.setColorAt(index / max(1, len(colours) - 1), QColor(*colour))
            painter.fillRect(rect, QBrush(gradient))
        else:
            width = rect.width() / len(colours)
            for index, colour in enumerate(colours):
                painter.fillRect(QRectF(rect.left() + index * width, rect.top(), width + 1, rect.height()), QColor(*colour))


class Swatch(QAbstractButton):
    """A round colour button."""

    def __init__(self, rgb: Rgb, size: int = 34, checkable: bool = True):
        super().__init__()
        self.rgb = tuple(int(value) for value in rgb)
        self.setCheckable(checkable)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("#" + rgb_hex(self.rgb)[1:].upper())

    def set_rgb(self, rgb: Rgb) -> None:
        self.rgb = tuple(int(value) for value in rgb)
        self.setToolTip("#" + rgb_hex(self.rgb)[1:].upper())
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if self.isChecked():
            painter.setPen(QPen(QColor(t.text), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
            rect = rect.adjusted(2, 2, -2, -2)
        painter.setPen(QPen(QColor(t.border), 1))
        painter.setBrush(QColor(*self.rgb))
        painter.drawEllipse(rect)


class StatusDot(QWidget):
    def __init__(self, size: int = 9):
        super().__init__()
        self._colour = QColor(tokens().tertiary)
        self.setFixedSize(size + 6, size + 6)

    def set_colour(self, colour: str) -> None:
        self._colour = QColor(colour)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        halo = QColor(self._colour)
        halo.setAlpha(60)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(QRectF(self.rect()))
        painter.setBrush(self._colour)
        painter.drawEllipse(QRectF(self.rect()).adjusted(3, 3, -3, -3))


class ValueGrid(QWidget):
    """Two-column key/value readout used by diagnostics."""

    def __init__(self, rows: Sequence[tuple[str, str]], columns: int = 2):
        super().__init__()
        from PySide6.QtWidgets import QGridLayout

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(10)
        self.values: dict[str, QLabel] = {}
        per_column = math.ceil(len(rows) / columns)
        for index, (key, title) in enumerate(rows):
            column, row = divmod(index, per_column)
            name = label(title, "hint")
            value = label("—", "value")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(name, row, column * 2)
            grid.addWidget(value, row, column * 2 + 1)
            grid.setColumnStretch(column * 2 + 1, 1)
            self.values[key] = value

    def set(self, key: str, text: str) -> None:
        if key in self.values:
            self.values[key].setText(text)


def hbox(*widgets: QWidget | None, spacing: int = 10, stretch_last: bool = False) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        if widget is None:
            layout.addStretch(1)
        else:
            layout.addWidget(widget)
    if stretch_last:
        layout.addStretch(1)
    return holder

