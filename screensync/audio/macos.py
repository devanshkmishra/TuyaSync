"""Native macOS system-audio capture using ScreenCaptureKit."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np

from screensync.audio.base import AudioCaptureError, AudioFrame

try:
    import objc
    import CoreMedia
    import ScreenCaptureKit
    from Foundation import NSObject
except ImportError as error:  # pragma: no cover - exercised on non-macOS systems
    objc = CoreMedia = ScreenCaptureKit = NSObject = None
    _IMPORT_ERROR = error
else:
    _IMPORT_ERROR = None


if NSObject is not None:
    class _StreamOutput(NSObject, protocols=[objc.protocolNamed("SCStreamOutput")]):
        def initWithOwner_(self, owner):
            self = objc.super(_StreamOutput, self).init()
            if self is not None:
                self.owner = owner
            return self

        def stream_didOutputSampleBuffer_ofType_(self, _stream, sample_buffer, output_type):
            if output_type == ScreenCaptureKit.SCStreamOutputTypeAudio:
                self.owner._handle_sample(sample_buffer)


class MacOSSystemAudioBackend:
    name = "ScreenCaptureKit system audio"

    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        self.channels = 1
        self._callback: Callable[[AudioFrame], None] | None = None
        self._stream = self._output = self._filter = None
        self._running = False
        self._blocks = 0
        self._started_at = 0.0
        self._last_error = ""

    def start(self, callback: Callable[[AudioFrame], None]) -> None:
        if self._running:
            return
        if _IMPORT_ERROR:
            raise AudioCaptureError(f"ScreenCaptureKit bindings are unavailable: {_IMPORT_ERROR}")
        self._callback = callback
        content = self._shareable_content()
        displays = list(content.displays())
        if not displays:
            raise AudioCaptureError("No active display is available for system-audio capture")
        self._filter = ScreenCaptureKit.SCContentFilter.alloc().initWithDisplay_excludingApplications_exceptingWindows_(
            displays[0], [], []
        )
        configuration = ScreenCaptureKit.SCStreamConfiguration.alloc().init()
        configuration.setCapturesAudio_(True)
        configuration.setExcludesCurrentProcessAudio_(True)
        configuration.setSampleRate_(self.sample_rate)
        configuration.setChannelCount_(self.channels)
        configuration.setWidth_(2)
        configuration.setHeight_(2)
        self._output = _StreamOutput.alloc().initWithOwner_(self)
        self._stream = ScreenCaptureKit.SCStream.alloc().initWithFilter_configuration_delegate_(
            self._filter, configuration, None
        )
        added, error = self._stream.addStreamOutput_type_sampleHandlerQueue_error_(
            self._output, ScreenCaptureKit.SCStreamOutputTypeAudio, None, None
        )
        if not added:
            raise AudioCaptureError(self._friendly_error(error))
        completed, result = threading.Event(), {}

        def started(error):
            result["error"] = error
            completed.set()

        self._stream.startCaptureWithCompletionHandler_(started)
        if not completed.wait(5):
            raise AudioCaptureError("Timed out while starting macOS system-audio capture")
        if result.get("error"):
            raise AudioCaptureError(self._friendly_error(result["error"]))
        self._blocks = 0
        self._started_at = time.monotonic()
        self._last_error = ""
        self._running = True

    def stop(self) -> None:
        stream = self._stream
        self._running = False
        if stream is not None:
            completed = threading.Event()
            stream.stopCaptureWithCompletionHandler_(lambda _error: completed.set())
            completed.wait(5)
        self._callback = None
        self._stream = self._output = self._filter = None

    def is_running(self) -> bool:
        return self._running

    def status(self) -> dict[str, object]:
        elapsed = max(0.001, time.monotonic() - self._started_at) if self._started_at else 0.0
        return {
            "backend": self.name,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "block_rate": self._blocks / elapsed if elapsed else 0.0,
            "last_error": self._last_error,
        }

    def _shareable_content(self):
        completed, result = threading.Event(), {}

        def received(content, error):
            result.update(content=content, error=error)
            completed.set()

        ScreenCaptureKit.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
            False, True, received
        )
        if not completed.wait(5):
            raise AudioCaptureError("Timed out while requesting macOS capture permission")
        if result.get("error") or result.get("content") is None:
            raise AudioCaptureError(self._friendly_error(result.get("error")))
        return result["content"]

    def _handle_sample(self, sample_buffer) -> None:
        if not self._running or self._callback is None or not sample_buffer:
            return
        try:
            block = CoreMedia.CMSampleBufferGetDataBuffer(sample_buffer)
            length = CoreMedia.CMBlockBufferGetDataLength(block)
            status, data = CoreMedia.CMBlockBufferCopyDataBytes(block, 0, length, None)
            if status != 0 or not data:
                return
            samples = np.frombuffer(data, dtype=np.float32).copy()
            self._blocks += 1
            self._callback(AudioFrame(samples, self.sample_rate, self.channels, time.monotonic()))
        except Exception as error:
            self._last_error = str(error)

    @staticmethod
    def _friendly_error(error) -> str:
        detail = str(error or "Capture access was denied")
        return (
            "System-audio capture could not start. Enable TuyaSync under "
            f"System Settings → Privacy & Security → Screen & System Audio Recording. ({detail})"
        )
