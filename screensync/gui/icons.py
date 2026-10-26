"""Small line icons drawn with QPainter so they follow the theme colour."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _pen(colour: QColor, width: float = 1.7) -> QPen:
    return QPen(colour, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)


def _manual(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawEllipse(QPointF(12, 10), 5.2, 5.2)
    p.drawLine(QPointF(9.5, 18), QPointF(14.5, 18))
    p.drawLine(QPointF(10.5, 20.5), QPointF(13.5, 20.5))
    p.drawLine(QPointF(10, 15.2), QPointF(10, 18))
    p.drawLine(QPointF(14, 15.2), QPointF(14, 18))


def _screen(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawRoundedRect(QRectF(3.5, 4.5, 17, 11.5), 2, 2)
    p.drawLine(QPointF(9, 20), QPointF(15, 20))
    p.drawLine(QPointF(12, 16), QPointF(12, 20))


def _music(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 2.0))
    for x, top in ((5, 11), (9.5, 6), (14, 9), (18.5, 13)):
        p.drawLine(QPointF(x, 19), QPointF(x, top))


def _album(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawRoundedRect(QRectF(3.5, 3.5, 17, 17), 3, 3)
    p.drawEllipse(QPointF(12, 12), 4.6, 4.6)
    p.drawEllipse(QPointF(12, 12), 1.0, 1.0)


def _scenes(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    path = QPainterPath()
    path.moveTo(12, 3.5)
    path.cubicTo(12.6, 8.8, 14.2, 10.6, 19.5, 11.5)
    path.cubicTo(14.2, 12.4, 12.6, 14.2, 12, 19.5)
    path.cubicTo(11.4, 14.2, 9.8, 12.4, 4.5, 11.5)
    path.cubicTo(9.8, 10.6, 11.4, 8.8, 12, 3.5)
    p.drawPath(path)
    p.drawLine(QPointF(18.5, 17.5), QPointF(18.5, 21))
    p.drawLine(QPointF(16.75, 19.25), QPointF(20.25, 19.25))


def _settings(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    for y, knob in ((6.5, 15.5), (12, 8.5), (17.5, 13.5)):
        p.drawLine(QPointF(4, y), QPointF(20, y))
        p.setBrush(QColor(0, 0, 0, 0))
        p.drawEllipse(QPointF(knob, y), 2.1, 2.1)


def _power(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 2.0))
    p.drawArc(QRectF(5, 5.5, 14, 14), 125 * 16, 290 * 16)
    p.drawLine(QPointF(12, 3.5), QPointF(12, 11))


def _plus(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 2.0))
    p.drawLine(QPointF(12, 5), QPointF(12, 19))
    p.drawLine(QPointF(5, 12), QPointF(19, 12))


_DRAW = {
    "off": _manual,
    "manual": _manual,
    "screen": _screen,
    "music": _music,
    "album_art": _album,
    "scenes": _scenes,
    "settings": _settings,
    "power": _power,
    "plus": _plus,
}


def pixmap(name: str, colour: str | QColor, size: int = 20, ratio: float = 2.0) -> QPixmap:
    image = QPixmap(round(size * ratio), round(size * ratio))
    image.fill(Qt.GlobalColor.transparent)
    image.setDevicePixelRatio(ratio)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24, size / 24)
    _DRAW[name](painter, QColor(colour))
    painter.end()
    return image


def icon(name: str, colour: str | QColor, size: int = 20) -> QIcon:
    return QIcon(pixmap(name, colour, size))
