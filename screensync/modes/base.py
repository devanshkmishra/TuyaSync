"""Small lifecycle contract shared by TuyaSync lighting modes."""

from __future__ import annotations

from typing import Protocol


class LightingMode(Protocol):
    name: str

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def is_running(self) -> bool: ...

    def reset_mode_state(self) -> None: ...
