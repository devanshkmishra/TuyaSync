"""Windows WASAPI loopback backend, isolated from the shared Music engine."""

from __future__ import annotations

import threading
import time

import numpy as np

from screensync.audio.base import AudioCaptureError, AudioFrame


class WindowsSystemAudioBackend:
    name = "WASAPI default-output loopback"

    def __init__(self, sample_rate: int = 48000, block_size: int = 960):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._blocks = 0
        self._started_at = 0.0
        self._last_error = ""

    def start(self, callback) -> None:
        if self.is_running():
            return
        try:
            import soundcard
        except ImportError as error:
            raise AudioCaptureError("Windows WASAPI support requires the soundcard package") from error
        speaker = soundcard.default_speaker()
        if speaker is None:
            raise AudioCaptureError("Windows has no default audio output device")
        loopback = soundcard.get_microphone(speaker.id, include_loopback=True)
        if loopback is None:
            raise AudioCaptureError("WASAPI loopback is unavailable for the default output device")
        self._stop_event.clear()
        self._blocks = 0
        self._started_at = time.monotonic()

        def capture():
            try:
                with loopback.recorder(samplerate=self.sample_rate, channels=2, blocksize=self.block_size) as recorder:
                    while not self._stop_event.is_set():
                        stereo = recorder.record(numframes=self.block_size)
                        mono = np.asarray(stereo, dtype=np.float32).mean(axis=1)
                        self._blocks += 1
                        callback(AudioFrame(mono, self.sample_rate, 1, time.monotonic()))
            except Exception as error:
                self._last_error = str(error)

        self._worker = threading.Thread(target=capture, name="WASAPILoopback", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        worker = self._worker
        if worker:
            worker.join(5)
            if worker.is_alive():
                raise AudioCaptureError("The Windows audio-capture worker did not stop")
        self._worker = None

    def is_running(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    def status(self) -> dict[str, object]:
        elapsed = max(0.001, time.monotonic() - self._started_at) if self._started_at else 0.0
        return {
            "backend": self.name,
            "sample_rate": self.sample_rate,
            "channels": 1,
            "block_rate": self._blocks / elapsed if elapsed else 0.0,
            "last_error": self._last_error,
        }
