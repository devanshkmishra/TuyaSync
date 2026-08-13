"""Atomic ownership of the single physical Tuya light."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable

from screensync.modes.base import LightingMode


class ModeTransitionError(RuntimeError):
    pass


class ModeManager:
    VALID_MODES = ("off", "screen", "music", "album_art", "scenes")

    def __init__(
        self,
        modes: Iterable[LightingMode] = (),
        clear_output: Callable[[], None] | None = None,
    ):
        self._lock = threading.RLock()
        self._modes = {mode.name: mode for mode in modes}
        self._clear_output = clear_output or (lambda: None)
        self._active_mode = "off"
        self._last_non_off = "screen"

    @property
    def active_mode(self) -> str:
        with self._lock:
            return self._active_mode

    @property
    def last_non_off_mode(self) -> str:
        with self._lock:
            return self._last_non_off

    def register(self, mode: LightingMode) -> None:
        if mode.name not in self.VALID_MODES or mode.name == "off":
            raise ValueError(f"Unsupported mode: {mode.name}")
        with self._lock:
            if mode.name == self._active_mode:
                raise ModeTransitionError(f"Cannot replace active mode: {mode.name}")
            self._modes[mode.name] = mode

    def switch_to(self, name: str) -> None:
        if name not in self.VALID_MODES:
            raise ValueError(f"Unsupported mode: {name}")
        with self._lock:
            if name == self._active_mode:
                return
            previous_name = self._active_mode
            previous = self._modes.get(previous_name)
            if previous is not None:
                previous.stop()
                if previous.is_running():
                    raise ModeTransitionError(f"{previous_name} did not stop cleanly")
            self._clear_output()
            self._active_mode = "off"
            if name == "off":
                return
            target = self._modes.get(name)
            if target is None:
                raise ModeTransitionError(f"Mode is unavailable: {name}")
            reset = getattr(target, "reset_mode_state", None)
            if reset:
                reset()
            try:
                target.start()
            except Exception as error:
                try:
                    target.stop()
                finally:
                    self._clear_output()
                raise ModeTransitionError(f"Could not start {name}: {error}") from error
            if not target.is_running():
                self._clear_output()
                raise ModeTransitionError(f"{name} did not enter its running state")
            self._active_mode = name
            self._last_non_off = name

    def stop(self) -> None:
        self.switch_to("off")
