from __future__ import annotations

import sys


def spotify_backend():
    if sys.platform == "darwin":
        from screensync.now_playing.macos_spotify import SpotifyMacBackend
        return SpotifyMacBackend()
    if sys.platform == "win32":
        from screensync.now_playing.windows_media import WindowsMediaBackend
        return WindowsMediaBackend()
    raise RuntimeError("Album Art is currently supported on macOS and Windows")
