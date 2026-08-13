from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np


class AudioCaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioFrame:
    samples: np.ndarray
    sample_rate: int
    channels: int
    timestamp: float


class AudioBackend(Protocol):
    name: str

    def start(self, callback: Callable[[AudioFrame], None]) -> None: ...

    def stop(self) -> None: ...

    def is_running(self) -> bool: ...

    def status(self) -> dict[str, object]: ...
