"""Pieces shared by the mode pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from screensync.gui.controller import MODE_LABELS, AppController
from screensync.gui.widgets import Card, LightOrb, button, label, repolish


class ModeHero(Card):
    """Live preview plus the one button that starts or stops a mode."""

    def __init__(self, controller: AppController, mode: str, visual: QWidget | None = None):
        super().__init__()
        self.controller = controller
        self.mode = mode
        self.body.setContentsMargins(26, 22, 30, 22)
        row = QHBoxLayout()
        row.setSpacing(26)
        self.orb = LightOrb(132)
        row.addWidget(visual or self.orb, 0, Qt.AlignmentFlag.AlignVCenter)

        copy = QVBoxLayout()
        copy.setSpacing(6)
        copy.addStretch(1)
        self.badge = QLabel()
        self.badge.setAlignment(Qt.AlignmentFlag.AlignLeft)
        badge_row = QHBoxLayout()
        badge_row.addWidget(self.badge)
        badge_row.addStretch(1)
        copy.addLayout(badge_row)
        self.headline = label("", "title", wrap=True)
        self.headline.setStyleSheet("font-size: 20px;")
        copy.addWidget(self.headline)
        self.detail = label("", "subtitle", wrap=True)
        copy.addWidget(self.detail)
        self.extra = QVBoxLayout()
        self.extra.setSpacing(8)
        copy.addLayout(self.extra)
        copy.addSpacing(10)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.action = button("", "hero", self._toggle)
        self.action.setMinimumWidth(170)
        actions.addWidget(self.action)
        self.secondary_actions = actions
        actions.addStretch(1)
        copy.addLayout(actions)
        copy.addStretch(1)
        row.addLayout(copy, 1)
        self.side = QVBoxLayout()
        row.addLayout(self.side)
        self.body.addLayout(row)
        self.set_running(False)

    def _toggle(self) -> None:
        self.controller.toggle_mode(self.mode)

    def set_running(self, running: bool) -> None:
        name = MODE_LABELS[self.mode]
        self.badge.setText("● LIVE" if running else "OFF")
        self.badge.setProperty("badge", "live" if running else True)
        repolish(self.badge)
        self.action.setText(f"Stop {name}" if running else f"Start {name}")
        self.action.setProperty("running", running)
        repolish(self.action)

    def set_text(self, headline: str, detail: str) -> None:
        if self.headline.text() != headline:
            self.headline.setText(headline)
        if self.detail.text() != detail:
            self.detail.setText(detail)


def pct(value: float) -> str:
    return f"{value:.0f}%"
