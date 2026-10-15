"""
Playlist Filter Service.
Enables intelligent filtering and sub-playlist creation from Spotify playlists.
Supports normalized text matching, fuzzy artist/remixer matching (e.g., 'guyj' -> 'Guy J'),
musical key / BPM filtering, and natural language prompt parsing.
"""

import re
import unicodedata
from typing import List, Tuple, Optional, Dict, Any
from rapidfuzz import fuzz

from models import SpotifyTrack


def normalize_text(text: str) -> str:
    """
    Normalizes string by removing accents/diacritics, punctuation, spaces,
    and converting to lowercase for robust fuzzy/token matching.
    e.g., 'Guy J' -> 'guyj', 'Hernán Cattáneo' -> 'hernancattaneo'.
    """
    if not text:
        return ""
    # Decompose unicode characters to strip diacritics
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join([c for c in nfkd if not unicodedata.combining(c)])
    # Remove all non-alphanumeric characters and lowercase
    return re.sub(r"[^a-zA-Z0-9]", "", stripped).lower()


def parse_filter_prompt(text: str) -> Tuple[Optional[str], str]:
    """
    Parses a combined natural language prompt or link.
    e.g.: 'quiero hacer una playlist con todos los tracks de guyj que hay acá https://open.spotify.com/playlist/1lGxW0cD0ijTo5BJESD5eW?si=...'
    Returns: (url, query)
    """
    if not text:
        return None, ""

    url_match = re.search(r"(https?://open\.spotify\.com/(?:playlist|album|track)/[a-zA-Z0-9]+(?:\?[^\s]*)?)", text)
    url = url_match.group(1) if url_match else None

    clean_text = text
    if url:
        clean_text = clean_text.replace(url, "").strip()

    # Strip conversational prompt framing in Spanish and English
    patterns = [
        r"^(?:quiero\s+hacer\s+una\s+playlist\s+con\s+(?:todos\s+los\s+)?tracks\s+de\s+|filtrar\s+tracks\s+de\s+|tracks\s+de\s+|canciones\s+de\s+|temas\s+de\s+|musica\s+de\s+|de\s+)",
        r"^(?:i\s+want\s+(?:a\s+playlist\s+with\s+)?(?:all\s+)?tracks\s+by\s+|filter\s+by\s+|tracks\s+by\s+|songs\s+by\s+|by\s+)",
        r"(?:\s+que\s+hay\s+ac[aá].*|\s+in\s+this\s+playlist.*|\s+from\s+this\s+playlist.*)$"
    ]
    query = clean_text
    for p in patterns:
        query = re.sub(p, "", query, flags=re.IGNORECASE).strip()

    query = query.strip("'\"“”` \t\n\r")
    return url, query


def matches_query(target: str, query: str, min_score: float = 75.0) -> bool:
    """
    Checks if query matches target via:
    1. Direct case-insensitive substring
    2. Normalized alphanumeric substring ('guyj' in 'guy j')
    3. RapidFuzz partial_ratio for typo tolerance
    """
    if not query:
        return True
    if not target:
        return False

    q_lower = query.lower().strip()
    t_lower = target.lower().strip()

    # 1. Exact substring
    if q_lower in t_lower:
        return True

    # 2. Normalized alphanumeric match
    norm_q = normalize_text(query)
    norm_t = normalize_text(target)
    if norm_q and norm_q in norm_t:
        return True

    # 3. Fuzzy partial ratio
    score = fuzz.partial_ratio(q_lower, t_lower)
    if score >= min_score:
        return True

    # Token set ratio for multi-word out-of-order matches
    if len(q_lower.split()) > 1:
        if fuzz.token_set_ratio(q_lower, t_lower) >= min_score:
            return True

    return False


def match_track(
    track: SpotifyTrack,
    query: str = "",
    filter_by: str = "all",
    min_score: float = 75.0,
    min_bpm: Optional[int] = None,
    max_bpm: Optional[int] = None,
    camelot_key: Optional[str] = None
) -> bool:
    """
    Determines if a SpotifyTrack satisfies text query and musical constraints.
    filter_by options: 'all', 'artist', 'title', 'key', 'bpm'.
    """
    # 1. Check BPM constraint if specified
    if min_bpm is not None and (not track.bpm or track.bpm < min_bpm):
        return False
    if max_bpm is not None and (not track.bpm or track.bpm > max_bpm):
        return False

    # 2. Check Camelot Key constraint if specified
    if camelot_key:
        ck = camelot_key.upper().strip()
        track_ck = (track.camelot_key or "").upper().strip()
        if ck != track_ck:
            return False

    # 3. Check text query
    if not query or not query.strip():
        return True

    q = query.strip()
    f_by = (filter_by or "all").lower()

    if f_by == "artist":
        # Check artist field or remixer mention in title
        if matches_query(track.artist, q, min_score):
            return True
        # Check if artist is named in Remix suffix (e.g. 'Song (Guy J Remix)')
        remix_match = re.search(r"[\(\[][^\)\]]*(?:remix|mix|edit|dub|rework)[^\)\]]*[\)\]]", track.title, re.IGNORECASE)
        if remix_match and matches_query(remix_match.group(0), q, min_score):
            return True
        return False

    elif f_by == "title":
        return matches_query(track.title, q, min_score)

    elif f_by in ("key", "bpm"):
        # Text query already verified or not required
        return True

    else: # 'all'
        # Matches if present in artist, title, or album
        if matches_query(track.artist, q, min_score):
            return True
        if matches_query(track.title, q, min_score):
            return True
        if matches_query(track.album, q, min_score):
            return True
        return False


def filter_tracks(
    tracks: List[SpotifyTrack],
    query: str = "",
    filter_by: str = "all",
    min_score: float = 75.0,
    min_bpm: Optional[int] = None,
    max_bpm: Optional[int] = None,
    camelot_key: Optional[str] = None
) -> List[SpotifyTrack]:
    """Filters a list of SpotifyTrack items against query and DJ attributes."""
    if not tracks:
        return []

    return [
        t for t in tracks
        if match_track(
            track=t,
            query=query,
            filter_by=filter_by,
            min_score=min_score,
            min_bpm=min_bpm,
            max_bpm=max_bpm,
            camelot_key=camelot_key
        )
    ]
