"""
spotify_client.py
------------------
Shared Spotify helpers used by both app.py (the main tool) and
spotify_to_muzpa.py (the legacy standalone CSV/HTML export tool).

Credentials are read from environment variables:
    SPOTIFY_CLIENT_ID
    SPOTIFY_CLIENT_SECRET

Never hardcode these values in source files or share them in chat/commits.
If a secret is ever exposed, rotate it from the Spotify Developer Dashboard.
"""

import os
import re
import sys

import spotipy
from spotipy.oauth2 import SpotifyOAuth

SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8888/callback"
SPOTIFY_SCOPE = "playlist-read-private playlist-read-collaborative"
TOKEN_CACHE_PATH = ".spotify_token_cache"


def extract_playlist_id(playlist_url: str) -> str:
    """Extracts the playlist ID from a Spotify playlist URL or URI."""
    match = re.search(r"playlist[/:]([a-zA-Z0-9]+)", playlist_url)
    if not match:
        raise ValueError(
            "Could not extract a playlist ID from that link. "
            "Make sure it's a valid Spotify playlist URL."
        )
    return match.group(1)


def get_spotify_client() -> spotipy.Spotify:
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        sys.exit(
            "Missing Spotify credentials.\n"
            "Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET as environment "
            "variables before running this tool."
        )

    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE,
        cache_path=TOKEN_CACHE_PATH,
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def get_playlist_name(sp: spotipy.Spotify, playlist_id: str) -> str:
    try:
        info = sp.playlist(playlist_id, fields="name")
        return info.get("name") or f"playlist_{playlist_id}"
    except Exception:
        return f"playlist_{playlist_id}"


def fetch_playlist_tracks(sp: spotipy.Spotify, playlist_id: str) -> list[dict]:
    """Returns a list of dicts: {track, artist, album, duration_ms}.

    Handles both possible response shapes seen across Spotify Web API /
    spotipy versions, where the track payload may live under the "track"
    key or the "item" key depending on the endpoint version.
    """
    tracks = []
    results = sp.playlist_items(playlist_id, additional_types=["track"])

    while results:
        for entry in results["items"]:
            track = entry.get("item") or entry.get("track")
            if not track:
                continue  # episode / removed / local file without metadata
            name = (track.get("name") or "").strip()
            artists = ", ".join(a["name"] for a in track.get("artists", []))
            album = track.get("album", {}).get("name", "")
            duration_ms = track.get("duration_ms", 0)
            if name and artists:
                tracks.append(
                    {
                        "track": name,
                        "artist": artists,
                        "album": album,
                        "duration_ms": duration_ms,
                    }
                )
        results = sp.next(results) if results.get("next") else None

    return tracks


def load_playlist(playlist_url: str) -> tuple[str, list[dict]]:
    """High-level helper: takes a playlist URL, returns (playlist_name, tracks)."""
    playlist_id = extract_playlist_id(playlist_url)
    sp = get_spotify_client()
    playlist_name = get_playlist_name(sp, playlist_id)
    tracks = fetch_playlist_tracks(sp, playlist_id)
    return playlist_name, tracks
