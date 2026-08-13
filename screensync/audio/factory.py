from __future__ import annotations

import sys


def system_audio_backend():
    if sys.platform == "darwin":
        from screensync.audio.macos import MacOSSystemAudioBackend
        return MacOSSystemAudioBackend()
    if sys.platform == "win32":
        from screensync.audio.windows import WindowsSystemAudioBackend
        return WindowsSystemAudioBackend()
    raise RuntimeError("System-audio capture is currently supported on macOS and Windows")
