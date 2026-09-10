"""
Domain Models and Type Definitions for Spotify to Muzpa Downloader.
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class TrackStatus(str, Enum):
    PENDING = "PENDING"
    SEARCHING = "SEARCHING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    DOWNLOADING = "DOWNLOADING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    NOT_FOUND = "NOT_FOUND"
    ERROR = "ERROR"


class SpotifyTrack(BaseModel):
    id: str = Field(description="Spotify unique track ID")
    title: str = Field(description="Track name")
    artist: str = Field(description="Primary artist or artists string")
    album: str = Field(default="Unknown Album", description="Album name")
    duration_ms: int = Field(default=0, description="Duration in milliseconds")
    duration_str: str = Field(default="0:00", description="Formatted duration MM:SS")
    spotify_url: str = Field(default="", description="Spotify track web URL")
    image_url: Optional[str] = Field(default=None, description="Album artwork URL")
    preview_url: Optional[str] = Field(default=None, description="Spotify 30s preview URL if available")
    bpm: Optional[int] = Field(default=None, description="Tempo in beats per minute (BPM)")
    musical_key: Optional[str] = Field(default=None, description="Musical key e.g. A Minor, C Major")
    camelot_key: Optional[str] = Field(default=None, description="Camelot Wheel Key e.g. 8A, 12B")
    energy: Optional[float] = Field(default=None, description="Energy score 0.0 to 1.0")
    danceability: Optional[float] = Field(default=None, description="Danceability score 0.0 to 1.0")

    @property
    def clean_search_query(self) -> str:
        """Returns a clean query optimized for search engine lookups."""
        import re
        # Remove common remix/feat clutter that might confuse strict searches
        clean_title = re.sub(r"\(feat\..*?\)", "", self.title, flags=re.IGNORECASE)
        clean_title = re.sub(r"\[feat\..*?\]", "", clean_title, flags=re.IGNORECASE)
        clean_title = re.sub(r"\s-\s*(Original Mix|Radio Edit)", "", clean_title, flags=re.IGNORECASE)
        return f"{self.artist} - {clean_title.strip()}".strip()


class MuzpaCandidate(BaseModel):
    id: str = Field(description="Unique candidate identifier or index")
    title: str = Field(default="", description="Track title parsed from Muzpa DOM")
    artist: str = Field(default="", description="Artist parsed from Muzpa DOM")
    duration: str = Field(default="", description="Track duration as displayed on Muzpa")
    bitrate: Optional[str] = Field(default=None, description="Bitrate if available (e.g. 320 kbps)")
    score: float = Field(default=0.0, description="Fuzzy match similarity score from 0.0 to 100.0")
    download_selector: str = Field(default="", description="CSS or JS locator to trigger the download")
    direct_href: Optional[str] = Field(default=None, description="Href attribute if present on download button")
    raw_text: Optional[str] = Field(default=None, description="Raw text snippet of the release block")


class TrackState(BaseModel):
    spotify_track: SpotifyTrack
    status: TrackStatus = Field(default=TrackStatus.PENDING)
    candidates: List[MuzpaCandidate] = Field(default_factory=list)
    selected_candidate: Optional[MuzpaCandidate] = Field(default=None)
    downloaded_file_path: Optional[str] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    retry_count: int = Field(default=0)
    transition_quality: Optional[str] = Field(default=None, description="DJ transition quality from previous track")
    transition_note: Optional[str] = Field(default=None, description="DJ transition technical note")
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class PlaylistJob(BaseModel):
    playlist_id: str
    playlist_name: str
    playlist_url: str
    playlist_image: Optional[str] = None
    tracks: List[TrackState] = Field(default_factory=list)
    current_track_index: int = Field(default=0)
    is_running: bool = Field(default=False)
    auto_mode: bool = Field(default=False)
    similarity_threshold: float = Field(default=75.0)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    @property
    def stats(self) -> Dict[str, int]:
        counts = {status.value: 0 for status in TrackStatus}
        for track in self.tracks:
            counts[track.status.value] = counts.get(track.status.value, 0) + 1
        counts["TOTAL"] = len(self.tracks)
        counts["PERCENTAGE"] = int((counts[TrackStatus.COMPLETED.value] + counts[TrackStatus.SKIPPED.value]) / max(len(self.tracks), 1) * 100)
        return counts


class DecisionRequest(BaseModel):
    track_id: str
    action: str = Field(description="'confirm', 'skip', 'custom_search', or 'retry'")
    candidate_id: Optional[str] = None
    custom_query: Optional[str] = None


class ConfigUpdateRequest(BaseModel):
    auto_mode: Optional[bool] = None
    similarity_threshold: Optional[float] = None
    rate_limit_delay: Optional[float] = None
