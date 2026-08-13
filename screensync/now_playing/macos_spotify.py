"""Local Spotify metadata through its AppleScript dictionary; no Spotify API."""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable

from screensync.now_playing.base import NowPlaying


SCRIPT = r'''tell application "Spotify"
if it is running then
  if player state is stopped then return ""
  set t to current track
  return (id of t) & linefeed & (name of t) & linefeed & (artist of t) & linefeed & (album of t) & linefeed & (artwork url of t) & linefeed & (player state as text)
end if
return ""
end tell'''


class SpotifyMacBackend:
    name = "Spotify local AppleScript"

    def __init__(self, interval: float = 1.0):
        self.interval = max(0.5, interval)
        self._callback: Callable[[NowPlaying], None] | None = None
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._last = NowPlaying(self.name)
        self._last_refresh = 0.0
        self._last_error = ""
        self._polls = 0

    def start(self, callback: Callable[[NowPlaying], None]) -> None:
        if self.is_running():
            return
        self._callback = callback
        self._stop.clear()
        self._worker = threading.Thread(target=self._run, name="SpotifyNowPlaying", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.join(3)
            if self._worker.is_alive():
                raise RuntimeError("Spotify metadata worker did not stop")
        self._worker = None
        self._callback = None

    def is_running(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    def status(self) -> dict[str, object]:
        return {
            "source": self.name,
            "metadata_refresh": self._last_refresh,
            "polls": self._polls,
            "last_error": self._last_error,
            "track": self._last.title,
        }

    def poll_once(self) -> NowPlaying:
        try:
            result = subprocess.run(
                ["osascript", "-e", SCRIPT],
                check=False,
                capture_output=True,
                text=True,
                timeout=4,
            )
            self._polls += 1
            self._last_refresh = time.time()
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Spotify AppleScript query failed")
            values = result.stdout.rstrip("\n").split("\n")
            if not values or not values[0]:
                current = NowPlaying(self.name, refreshed_at=self._last_refresh)
            else:
                values += [""] * (6 - len(values))
                state = values[5].strip().lower()
                current = NowPlaying(
                    source=self.name,
                    title=values[1].strip(),
                    artist=values[2].strip(),
                    album=values[3].strip(),
                    artwork_url=values[4].strip(),
                    is_playing=state == "playing",
                    track_id_or_stable_key=values[0].strip(),
                    refreshed_at=self._last_refresh,
                )
            self._last = current
            self._last_error = ""
            return current
        except Exception as error:
            self._last_error = str(error)
            return NowPlaying(self.name, refreshed_at=time.time())

    def _run(self) -> None:
        while not self._stop.is_set():
            current = self.poll_once()
            if self._callback:
                self._callback(current)
            self._stop.wait(self.interval)
