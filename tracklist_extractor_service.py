"""
Tracklist Extractor Service for Spotify2Muzpa Studio.
Extracts tracks from images (using native macOS Apple Vision OCR or fallback OCR)
or from copied text lists (social media, 1001tracklists, YouTube descriptions, notes),
normalizes metadata, and prepares jobs for Muzpa crawler downloads.
"""

import re
import os
import sys
import base64
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime

from models import ExtractedTrackItem, SpotifyTrack, TrackState, PlaylistJob

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OCR Extraction Engine (Native Apple Vision on macOS, PyTesseract fallback)
# ---------------------------------------------------------------------------

def is_macos_vision_available() -> bool:
    """Checks whether Apple Vision framework can be loaded via PyObjC."""
    if sys.platform != "darwin":
        return False
    try:
        import objc
        Vision = objc.loadBundle("Vision", globals(), bundle_path="/System/Library/Frameworks/Vision.framework")
        return Vision is not None
    except Exception:
        return False


def extract_text_with_apple_vision(image_bytes: bytes) -> str:
    """
    Extracts text from image bytes using macOS Apple Vision framework (VNRecognizeTextRequest).
    Maintains top-to-bottom reading order by sorting bounding boxes by Y-coordinate.
    """
    import objc
    from Foundation import NSData
    from Quartz import CGImageSourceCreateWithData, CGImageSourceCreateImageAtIndex

    objc.loadBundle("Vision", globals(), bundle_path="/System/Library/Frameworks/Vision.framework")
    VNRecognizeTextRequest = objc.lookUpClass("VNRecognizeTextRequest")
    VNImageRequestHandler = objc.lookUpClass("VNImageRequestHandler")

    ns_data = NSData.dataWithBytes_length_(image_bytes, len(image_bytes))
    source = CGImageSourceCreateWithData(ns_data, None)
    if not source:
        raise ValueError("Failed to create image source from provided image bytes.")

    cg_image = CGImageSourceCreateImageAtIndex(source, 0, None)
    if not cg_image:
        raise ValueError("Could not decode image data into a valid graphic format.")

    req = VNRecognizeTextRequest.alloc().init()
    # 1 = VNRequestTextRecognitionLevelAccurate
    req.setRecognitionLevel_(1)
    req.setUsesLanguageCorrection_(True)

    handler = VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, {})
    success = handler.performRequests_error_([req], None)
    if not success:
        raise RuntimeError("Apple Vision text recognition request failed.")

    obs_list = req.results() or []
    if not obs_list:
        return ""

    # In Apple Vision, (0,0) is bottom-left, so larger y is closer to top of image.
    # Sorting descending by origin.y yields true top-to-bottom line order.
    sorted_obs = sorted(obs_list, key=lambda o: -o.boundingBox().origin.y)

    lines: List[str] = []
    for obs in sorted_obs:
        top_candidates = obs.topCandidates_(1)
        if top_candidates:
            text = str(top_candidates[0].string()).strip()
            if text:
                lines.append(text)

    return "\n".join(lines)


def extract_text_with_pytesseract(image_bytes: bytes) -> str:
    """Fallback OCR using pytesseract if installed."""
    try:
        import pytesseract
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(img)
    except ImportError:
        raise RuntimeError(
            "OCR on non-macOS systems requires 'pytesseract' and 'Pillow'. "
            "Please install them via pip install pytesseract pillow."
        )


def extract_text_from_image(
    image_bytes: Optional[bytes] = None,
    image_path: Optional[str] = None,
    base64_data: Optional[str] = None
) -> str:
    """
    Extracts raw text lines from an image provided as bytes, local file path, or base64 string.
    """
    data: Optional[bytes] = None

    if base64_data:
        # Strip data URI header if present e.g. "data:image/png;base64,..."
        clean_b64 = base64_data.split(",", 1)[1] if "," in base64_data else base64_data
        data = base64.b64decode(clean_b64)
    elif image_path:
        p = Path(image_path)
        if not p.is_file():
            raise FileNotFoundError(f"Image file not found: {image_path}")
        data = p.read_bytes()
    elif image_bytes:
        data = image_bytes

    if not data:
        raise ValueError("No image data provided for text extraction.")

    if is_macos_vision_available():
        return extract_text_with_apple_vision(data)
    else:
        return extract_text_with_pytesseract(data)


# ---------------------------------------------------------------------------
# Tracklist Text Parser & Normalizer
# ---------------------------------------------------------------------------

IGNORED_HEADER_KEYWORDS = [
    "tracklist", "playlist", "setlist", "track list", "set list",
    "mixed by", "dj set", "recorded at", "recorded live",
    "listen on", "soundcloud", "spotify", "youtube", "instagram",
    "follow me", "subscribe", "all rights reserved", "download link",
    "free download", "enjoy the music", "enjoy the set", "release date", "genres:",
    "thanks for listening", "track id", "link in bio"
]


def is_ignored_header_line(line: str) -> bool:
    """Checks if a line is metadata header/footer clutter rather than a music track."""
    l_lower = line.strip().lower()
    if not l_lower or len(l_lower) < 2:
        return True
    if l_lower.startswith(("#", "//", "http://", "https://", "www.", "@", "fb.com", "ig:")):
        return True
    for kw in IGNORED_HEADER_KEYWORDS:
        if l_lower.startswith(kw) or kw in l_lower or l_lower == kw:
            return True
    return False


def parse_single_trackline(raw_line: str) -> Optional[Tuple[str, str]]:
    """
    Parses a single trackline into (artist, title).
    Handles:
      - 1 - Artist - Title
      - 01. Artist - Title
      - [01] Artist - Title
      - - Artist - Title (bullet)
      - 7 . Artist . Title (OCR spaced dot)
      - Artist : Title
      - Artist | Title
      - Title by Artist
      - Artist - Title (Remix)
      - Artist - Title [Label]
    """
    s = raw_line.strip()
    if is_ignored_header_line(s):
        return None

    # Track if line had an explicit track number or timestamp prefix
    had_number_prefix = bool(re.search(r"^[\s\(\[\#]*\d{1,3}\s*[\.\)\:\-\–\—\]\s]+", s))
    had_timestamp_prefix = bool(re.search(r"^[\[\(]?\d{1,2}:\d{2}(?::\d{2})?[\]\)]?", s))
    had_track_prefix = had_number_prefix or had_timestamp_prefix

    # 1. Strip leading timestamps: [01:23:45], 12:34, (01:23)
    s = re.sub(r"^[\[\(]?\d{1,2}:\d{2}(?::\d{2})?[\]\)]?\s*[-–—:]?\s*", "", s).strip()

    # 2. Strip leading track numbering: '1 - ', '1. ', '01. ', '[01] ', '(1) ', '#1 ', '1 . '
    s = re.sub(r"^[\s\(\[\#]*\d{1,3}\s*[\.\)\:\-\–\—\]\s]+\s*", "", s).strip()

    # 3. Strip leading bullets / list markers: '- ', '• ', '* ', '— ', '– ', '+ ', '> '
    s = re.sub(r"^[\s\-\*\•\–\—\>\|\+]+\s*", "", s).strip()

    # 4. Strip trailing timestamps / durations: '[05:20]', '(03:45)', '5:20'
    s = re.sub(r"\s*[\[\(]?\d{1,2}:\d{2}(?::\d{2})?[\]\)]?\s*$", "", s).strip()

    # 5. Extract label if wrapped in brackets at end: e.g. "Artist - Title [Lost & Found]"
    label_match = re.search(r"\s+\[([^\]]+)\]\s*$", s)
    if label_match:
        cand = label_match.group(1).lower()
        if not any(k in cand for k in ["remix", "mix", "edit", "version", "dub"]):
            s = re.sub(r"\s+\[[^\]]+\]\s*$", "", s).strip()

    if not s or len(s) < 3:
        return None

    artist = ""
    title = ""

    # Delimiter Strategy:
    # A) Standard Dash: ' - ', ' – ', ' — ', or '--'
    dash_match = re.split(r"\s+[-–—]+\s+|\s+--\s+", s)
    if len(dash_match) >= 2:
        artist = dash_match[0].strip()
        if len(dash_match) == 2:
            title = dash_match[1].strip()
        else:
            # Multi-dash: e.g. "Artist - Title - Guy J Remix"
            part3 = dash_match[2].strip()
            if any(k in part3.lower() for k in ["remix", "mix", "edit", "dub", "version", "cut"]):
                title = f"{dash_match[1].strip()} ({part3})"
            else:
                title = " - ".join(dash_match[1:]).strip()

    # B) Spaced Dot: ' . ' (common in OCR like '7 . LUCIANO FICARRA . GONE')
    if not artist:
        dot_parts = re.split(r"\s+\.\s+", s)
        if len(dot_parts) >= 2:
            artist = dot_parts[0].strip()
            title = " - ".join(dot_parts[1:]).strip()

    # C) Colon or Pipe or Slash: ' : ', ' | ', ' / '
    if not artist:
        col_parts = re.split(r"\s+[:|/]\s+", s)
        if len(col_parts) >= 2:
            artist = col_parts[0].strip()
            title = col_parts[1].strip()

    # D) "by": 'Title by Artist'
    if not artist:
        by_match = re.split(r"\s+by\s+", s, flags=re.IGNORECASE)
        if len(by_match) == 2:
            title = by_match[0].strip()
            artist = by_match[1].strip()

    # E) Tab-separated (e.g. copied from Excel / Rekordbox)
    if not artist and "\t" in s:
        tab_parts = [p.strip() for p in s.split("\t") if p.strip()]
        if len(tab_parts) >= 2:
            artist = tab_parts[0]
            title = tab_parts[1]

    # Fallback: only if line had an explicit track prefix or number
    if not artist:
        # Check if comma separator e.g. "Artist, Title"
        comma_parts = s.split(",", 1)
        if len(comma_parts) == 2 and not any(c.isdigit() for c in s):
            artist = comma_parts[0].strip()
            title = comma_parts[1].strip()
        elif had_track_prefix and not s.endswith(("!", "?", ".")):
            artist = "Unknown Artist"
            title = s.strip()
        else:
            # Casual text line without delimiters or numbering
            return None

    # Clean surrounding quotes
    artist = artist.strip("\"' \t\r\n")
    title = title.strip("\"' \t\r\n")

    if not title:
        return None

    return artist, title


def parse_tracklist_lines(raw_text: str) -> List[ExtractedTrackItem]:
    """
    Parses full raw text (from OCR or pasted list) into structured ExtractedTrackItem objects.
    """
    results: List[ExtractedTrackItem] = []
    if not raw_text:
        return results

    lines = raw_text.splitlines()
    order = 1

    for line in lines:
        cleaned_line = line.strip()
        if not cleaned_line:
            continue

        parsed = parse_single_trackline(cleaned_line)
        if not parsed:
            continue

        artist, title = parsed
        item = ExtractedTrackItem(
            index=order,
            artist=artist,
            title=title,
            raw_line=cleaned_line,
            duration_str="0:00"
        )
        results.append(item)
        order += 1

    return results


# ---------------------------------------------------------------------------
# Spotify Enrichment & Job Conversion
# ---------------------------------------------------------------------------

async def enrich_extracted_tracks_via_spotify(
    tracks: List[ExtractedTrackItem],
    spotify_service: Any
) -> List[ExtractedTrackItem]:
    """
    Attempts to search Spotify for each track to fetch official artwork, duration,
    BPM, Camelot key, and Spotify URL if Spotify API is initialized.
    """
    if not tracks:
        return []

    sp_client = getattr(spotify_service, "_sp", None) if spotify_service else None

    for item in tracks:
        if not sp_client:
            continue

        q = f"{item.artist} {item.title}".strip()
        try:
            res = sp_client.search(q=q, type="track", limit=1)
            found_items = res.get("tracks", {}).get("items", [])
            if found_items:
                t = found_items[0]
                item.spotify_id = t.get("id")
                item.spotify_url = t.get("external_urls", {}).get("spotify", "")
                item.duration_ms = t.get("duration_ms", 0)
                sec = item.duration_ms // 1000
                item.duration_str = f"{sec // 60}:{sec % 60:02d}"

                album_data = t.get("album", {})
                images = album_data.get("images", [])
                if images:
                    item.image_url = images[0].get("url")
        except Exception as e:
            logger.debug(f"Spotify search notice for '{q}': {e}")

    return tracks


def convert_extracted_to_spotify_tracks(
    tracks: List[ExtractedTrackItem],
    default_album: str = "Extracted Tracklist"
) -> List[SpotifyTrack]:
    """
    Converts ExtractedTrackItem models to domain SpotifyTrack models ready for Muzpa download.
    """
    spotify_tracks: List[SpotifyTrack] = []
    timestamp = int(datetime.utcnow().timestamp())

    for item in tracks:
        track_id = item.spotify_id or f"extract_{item.index}_{timestamp}_{abs(hash(item.title)) % 10000}"
        st = SpotifyTrack(
            id=track_id,
            title=item.title,
            artist=item.artist,
            album=default_album,
            duration_ms=item.duration_ms,
            duration_str=item.duration_str,
            spotify_url=item.spotify_url or "",
            image_url=item.image_url,
            bpm=item.bpm,
            musical_key=item.musical_key,
            camelot_key=item.camelot_key
        )
        spotify_tracks.append(st)

    return spotify_tracks


def create_playlist_job_from_extracted(
    tracks: List[ExtractedTrackItem],
    playlist_name: str = "Extracted Tracklist",
    auto_mode: bool = False,
    similarity_threshold: float = 75.0
) -> PlaylistJob:
    """
    Wraps extracted tracks into an executable PlaylistJob ready for DownloadOrchestrator.
    """
    if not tracks:
        raise ValueError("Cannot create download job with empty tracklist.")

    sp_tracks = convert_extracted_to_spotify_tracks(tracks, default_album=playlist_name)
    track_states = [TrackState(spotify_track=t) for t in sp_tracks]
    clean_name = playlist_name.strip() or "Extracted Tracklist"
    pl_id = f"extract_{abs(hash(clean_name))}_{int(datetime.utcnow().timestamp())}"

    return PlaylistJob(
        playlist_id=pl_id,
        playlist_name=clean_name,
        playlist_url=f"custom://extracted/{pl_id}",
        tracks=track_states,
        auto_mode=auto_mode,
        similarity_threshold=similarity_threshold
    )
