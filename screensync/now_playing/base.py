from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NowPlaying:
    source: str
    title: str = ""
    artist: str = ""
    album: str = ""
    artwork_url: str = ""
    artwork: bytes | None = None
    is_playing: bool = False
    track_id_or_stable_key: str = ""
    refreshed_at: float = 0.0

    @property
    def has_track(self) -> bool:
        return bool(self.track_id_or_stable_key or self.title)
