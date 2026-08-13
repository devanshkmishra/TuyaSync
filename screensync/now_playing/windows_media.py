"""Windows system media-session backend, isolated from Album Art logic."""

from __future__ import annotations

import asyncio
import threading
import time

from screensync.now_playing.base import NowPlaying


class WindowsMediaBackend:
    name = "Windows media session"

    def __init__(self, interval: float = 1.0):
        self.interval = max(0.5, interval)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._callback = None
        self._last = NowPlaying(self.name)
        self._last_error = ""

    def start(self, callback) -> None:
        if self.is_running():
            return
        self._callback = callback
        self._stop.clear()
        self._worker = threading.Thread(target=self._run, name="WindowsNowPlaying", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.join(4)
            if self._worker.is_alive():
                raise RuntimeError("Windows media-session worker did not stop")
        self._worker = None
        self._callback = None

    def is_running(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    def status(self):
        return {"source": self.name, "last_error": self._last_error, "track": self._last.title}

    def _run(self):
        try:
            import winrt.windows.media.control as media_control
            import winrt.windows.storage.streams as storage_streams
        except ImportError as error:
            self._last_error = "Windows media sessions require winrt-Windows.Media.Control"
            return
        try:
            asyncio.run(self._poll(media_control, storage_streams))
        except Exception as error:
            self._last_error = str(error)

    async def _poll(self, media_control, storage_streams):
        manager = await media_control.GlobalSystemMediaTransportControlsSessionManager.request_async()
        while not self._stop.is_set():
            sessions = manager.get_sessions()
            current = NowPlaying(self.name)
            for session in sessions:
                if "spotify" not in (session.source_app_user_model_id or "").lower():
                    continue
                properties = await session.try_get_media_properties_async()
                playback = session.get_playback_info()
                artwork = await self._read_thumbnail(properties.thumbnail, storage_streams)
                current = NowPlaying(
                    source=self.name,
                    title=properties.title or "",
                    artist=properties.artist or "",
                    album=properties.album_title or "",
                    artwork=artwork,
                    is_playing=str(playback.playback_status).lower().endswith("playing"),
                    track_id_or_stable_key=f"{properties.artist}|{properties.title}|{properties.album_title}",
                    refreshed_at=time.time(),
                )
                break
            self._last = current
            if self._callback:
                self._callback(current)
            await asyncio.sleep(self.interval)

    @staticmethod
    async def _read_thumbnail(reference, storage_streams):
        if reference is None:
            return None
        stream = None
        reader = None
        try:
            stream = await reference.open_read_async()
            reader = storage_streams.DataReader(stream.get_input_stream_at(0))
            await reader.load_async(stream.size)
            data = bytearray(stream.size)
            reader.read_bytes(data)
            return bytes(data)
        except Exception:
            return None
        finally:
            if reader is not None:
                reader.close()
            if stream is not None:
                stream.close()
