"""
Domain Models and Type Definitions for Spotify to Muzpa Downloader.
"""

from enum import Enum
from typing import List, Optional, Dict, Any
import re
from pydantic import BaseModel, Field
from datetime import datetime


def clean_track_title(title: str) -> str:
    """
    Cleans track titles of common release, DJ mix, and metadata noise:
    - DJ mix / continuous mix indicators: ' - Mixed', '(Mixed)', '[Mixed]',
      '- Continuous Mix', '(Continuous Mix)', '(DJ Mix)', '- Mixed Cut', etc.
    - Standard generic suffixes: '- Original Mix', '- Radio Edit', '- Album Version', '- Single Version'
    - Remaster tags: '- Remastered 2021', '(2011 Remaster)', '(Digital Remaster)', '- Deluxe Edition'
    - Featuring clutter: '(feat. X)', '[ft. Y]', '- feat. Z', '(with W)'
    - Bonus & format tags: '- Bonus Track', '(Bonus Track)', '(Mono)', '(Stereo Version)', '(Explicit)'
    - Preserves genuine titles ('Mixed Signals', 'Mixed Emotions') and remix names ('(ARTBAT Remix)', '(Club Mix)').
    """
    if not title:
        return ""
    t = title.strip()

    # 1. Feat / Ft / Featuring / With in parentheses or brackets
    t = re.sub(r"[\(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s+[^()\]]+[\)\]]", "", t, flags=re.IGNORECASE)
    # Suffix: ' - feat. Artist' or ' - ft. Artist'
    t = re.sub(r"\s+[-–—]\s+(?:feat\.?|ft\.?|featuring)\s+.*$", "", t, flags=re.IGNORECASE)

    # 2. Mixed / Continuous Mix / DJ Mix / Mix Cut
    # In brackets or parentheses:
    t = re.sub(
        r"[\(\[]\s*(?:(?:Continuous\s+(?:DJ\s+)?|DJ\s+)?Mix(?:ed)?(?:\s*(?:Cut|Version|Edit|Tracks))?|(?:Live|Edit)\s*[/,]\s*Mix(?:ed)?)\s*[\)\]]",
        "",
        t,
        flags=re.IGNORECASE
    )

    # As a dash/slash suffix at end or followed by another delimiter:
    t = re.sub(
        r"\s*[-–—/]\s*(?:Continuous\s+(?:DJ\s+)?Mix|DJ\s+Mix|Mix(?:ed)?\s*(?:Cut|Version|Edit|Tracks)?|Mixed)\b.*$",
        "",
        t,
        flags=re.IGNORECASE
    )

    # 3. Standard clutter: Radio Edit, Original Mix, Album/Single Version, Full Version
    t = re.sub(r"[\(\[]\s*(?:Original\s+Mix|Radio\s+Edit|Album\s+Version|Single\s+Version|Original\s+Version|Full\s+Version)\s*[\)\]]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*[-–—]\s*(?:Original\s+Mix|Radio\s+Edit|Album\s+Version|Single\s+Version|Original\s+Version|Full\s+Version)\b.*$", "", t, flags=re.IGNORECASE)

    # 4. Remaster, Anniversary, Deluxe, Edition tags
    t = re.sub(r"[\(\[]\s*(?:\d{4}\s+)?(?:Digital\s+)?Remaster(?:ed)?(?:\s+\d{4})?(?:\s+Version)?\s*[\)\]]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*[-–—]\s*(?:\d{4}\s+)?(?:Digital\s+)?Remaster(?:ed)?(?:\s+\d{4})?(?:\s+Version)?\b.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"[\(\[]\s*(?:\d+(?:th|st|nd|rd)\s+)?(?:Anniversary|Deluxe|Special|Expanded|Legacy|Collector\'?s?)\s+(?:Edition|Version|Release)\s*[\)\]]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*[-–—]\s*(?:\d+(?:th|st|nd|rd)\s+)?(?:Anniversary|Deluxe|Special|Expanded|Legacy|Collector\'?s?)\s+(?:Edition|Version|Release)\b.*$", "", t, flags=re.IGNORECASE)

    # 5. Live at / Live Version clutter
    t = re.sub(r"[\(\[]\s*Live(?:\s+(?:at|Version|from|\/\s*\d{4}))[^\)\]]*[\)\]]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*[-–—]\s*Live(?:\s+(?:at|Version|from|\/\s*\d{4}))\b.*$", "", t, flags=re.IGNORECASE)

    # 6. Bonus Track, Mono, Stereo, Explicit tags
    t = re.sub(r"[\(\[]\s*(?:Bonus\s+Track|Mono(?:\s+Version)?|Stereo(?:\s+Version)?|Explicit|Clean)\s*[\)\]]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*[-–—]\s*(?:Bonus\s+Track|Mono(?:\s+Version)?|Stereo(?:\s+Version)?)\b.*$", "", t, flags=re.IGNORECASE)

    # 7. Cleanup empty brackets, double spaces, trailing hyphens/slashes
    t = re.sub(r"[\(\[]\s*[\)\]]", "", t)
    t = re.sub(r"\s*[-–—/]\s*$", "", t)
    t = re.sub(r"\s+", " ", t).strip()

    # Safety: if cleaning completely emptied the title, fallback to original stripped
    return t if t else title.strip()


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
    def clean_title(self) -> str:
        """Returns track title cleaned of mixed indicators, remasters, standard edits, and feat noise."""
        return clean_track_title(self.title)

    @property
    def primary_artist(self) -> str:
        """Returns the primary artist when multiple artists are present."""
        if not self.artist:
            return ""
        parts = [p.strip() for p in self.artist.split(",") if p.strip()]
        return parts[0] if parts else self.artist.strip()

    @property
    def clean_search_query(self) -> str:
        """Returns the primary clean query optimized for search engine lookups."""
        p_artist = self.primary_artist or self.artist.strip()
        c_title = self.clean_title
        if p_artist and c_title:
            return f"{p_artist} - {c_title}".strip()
        return f"{self.artist} - {self.title}".strip()

    @property
    def search_queries(self) -> List[str]:
        """Returns prioritized list of candidate queries to try in Muzpa."""
        queries: List[str] = []
        p_artist = self.primary_artist.strip()
        full_artist = self.artist.strip()
        c_title = self.clean_title.strip()

        # 1. Primary artist + clean title (cleanest, highest hit-rate on Muzpa)
        if p_artist and c_title:
            queries.append(f"{p_artist} - {c_title}")

        # 2. Full artist string + clean title (if multi-artist and different from #1)
        if full_artist and full_artist != p_artist and c_title:
            q = f"{full_artist} - {c_title}"
            if q not in queries:
                queries.append(q)

        # 3. Clean title alone (if >= 4 chars, useful when artist format differs completely)
        if len(c_title) >= 4 and c_title not in queries:
            queries.append(c_title)

        return queries or [f"{self.artist} - {self.title}"]


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


class DJSetTrackItem(BaseModel):
    id: str = Field(description="Track candidate identifier or index")
    timestamp: str = Field(description="Start timestamp in set (HH:MM:SS or MM:SS)")
    end_timestamp: Optional[str] = Field(default=None, description="End timestamp in set")
    artist: str = Field(description="Artist name")
    title: str = Field(description="Track title")
    confidence: Optional[str] = Field(default="high", description="Source or confidence e.g. chapter, description, acoustic")
    spotify_id: Optional[str] = Field(default=None, description="Matched Spotify Track ID")
    spotify_url: Optional[str] = Field(default=None, description="Spotify Track URL")
    image_url: Optional[str] = Field(default=None, description="Album artwork URL")
    duration_ms: int = Field(default=0, description="Duration in ms")
    duration_str: str = Field(default="0:00", description="Formatted duration MM:SS")
    bpm: Optional[int] = Field(default=None, description="Tempo in BPM")
    musical_key: Optional[str] = Field(default=None, description="Musical key e.g. A Minor")
    camelot_key: Optional[str] = Field(default=None, description="Camelot key e.g. 8A, 11B")
    preview_url: Optional[str] = Field(default=None, description="30s preview URL")
    youtube_id: Optional[str] = Field(default=None, description="Matched YouTube video ID")
    youtube_url: Optional[str] = Field(default=None, description="Direct or search YouTube URL")



class DJSetJob(BaseModel):
    job_id: str
    source_url: str
    title: str = Field(default="DJ Set")
    uploader: Optional[str] = None
    duration_seconds: int = Field(default=0)
    duration_str: str = Field(default="0:00")
    thumbnail: Optional[str] = None
    status: str = Field(default="pending", description="pending, extracting_info, downloading_audio, analyzing, complete, error, cancelled")
    progress: Dict[str, Any] = Field(default_factory=lambda: {"current": 0, "total": 0, "percent": 0, "eta": ""})
    tracks: List[DJSetTrackItem] = Field(default_factory=list)
    error_message: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class DJSetAnalyzeRequest(BaseModel):
    url: str
    sample_interval: int = Field(default=90, description="Interval in seconds between acoustic samples")
    snippet_duration: int = Field(default=12, description="Duration of snippet in seconds to fingerprint")
    force_acoustic: bool = Field(default=False, description="Force acoustic fingerprinting even if description/chapters exist")


class DJSetToPlaylistRequest(BaseModel):
    job_id: str
    playlist_name: Optional[str] = None
    selected_indices: Optional[List[int]] = None
    auto_mode: bool = Field(default=False)
    similarity_threshold: float = Field(default=75.0)
