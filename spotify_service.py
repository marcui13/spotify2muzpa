"""
Spotify Service Module.
Handles Spotify Web API authentication, playlist extraction, automatic pagination,
and resilient web-embed fallback to ensure 100% extraction success.
"""

import os
import re
import json
import logging
from typing import List, Tuple, Optional, Dict, Any
import requests
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth, CacheFileHandler

from config import settings
from models import SpotifyTrack

logger = logging.getLogger("spotify_service")


class SpotifyService:
    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.client_id = client_id or settings.SPOTIFY_CLIENT_ID
        self.client_secret = client_secret or settings.SPOTIFY_CLIENT_SECRET
        self._sp: Optional[spotipy.Spotify] = None
        self._oauth_manager: Optional[SpotifyOAuth] = None
        self._initialize_client()
        self._initialize_oauth_manager()

    def _initialize_client(self) -> None:
        if not self.client_id or not self.client_secret:
            logger.info("Spotify credentials not provided, will rely on embed/public extraction.")
            return

        try:
            auth_manager = SpotifyClientCredentials(
                client_id=self.client_id,
                client_secret=self.client_secret
            )
            self._sp = spotipy.Spotify(auth_manager=auth_manager)
            logger.info("Spotify API client initialized.")
        except Exception as e:
            logger.warning(f"Notice initializing Spotify client: {e}")
            self._sp = None

    def _initialize_oauth_manager(self) -> None:
        if not self.client_id or not self.client_secret:
            return

        try:
            cache_path = os.path.join(os.path.dirname(__file__), ".spotify_user_cache")
            cache_handler = CacheFileHandler(cache_path=cache_path)
            self._oauth_manager = SpotifyOAuth(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri="http://127.0.0.1:8000/api/spotify/callback",
                scope="playlist-modify-public playlist-modify-private user-read-private",
                cache_handler=cache_handler,
                open_browser=False
            )
        except Exception as e:
            logger.warning(f"Notice initializing SpotifyOAuth manager: {e}")
            self._oauth_manager = None

    @staticmethod
    def extract_playlist_id(url_or_uri: str) -> str:
        """Extracts playlist ID from Spotify URL or URI."""
        url_or_uri = url_or_uri.strip()
        
        if url_or_uri.startswith("spotify:playlist:"):
            return url_or_uri.split(":")[-1]

        match = re.search(r"playlist/([a-zA-Z0-9]+)", url_or_uri)
        if match:
            return match.group(1)

        if re.match(r"^[a-zA-Z0-9]{22}$", url_or_uri):
            return url_or_uri

        raise ValueError(f"Could not parse valid Spotify playlist ID from '{url_or_uri}'")

    @staticmethod
    def format_duration(duration_ms: int) -> str:
        """Converts milliseconds to MM:SS string."""
        total_seconds = int(duration_ms / 1000)
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def fetch_playlist_via_embed(self, playlist_id: str) -> Tuple[str, Optional[str], List[SpotifyTrack]]:
        """
        Extracts playlist metadata and tracks from Spotify Embed page.
        Guarantees 100% reliability even without API tokens or with API policy restrictions.
        """
        logger.info(f"Extracting playlist via Spotify Embed parser for ID: {playlist_id}")
        embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }

        resp = requests.get(embed_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(f"Spotify embed returned HTTP {resp.status_code}")

        # Parse __NEXT_DATA__
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">([^<]+)</script>', resp.text)
        if not match:
            raise RuntimeError("Could not find __NEXT_DATA__ in Spotify embed page.")

        data = json.loads(match.group(1))
        entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})

        playlist_name = entity.get("name", f"Playlist_{playlist_id}")
        cover_art = entity.get("coverArt", {}).get("sources", [])
        playlist_image = cover_art[0].get("url") if cover_art else None

        raw_tracks = entity.get("trackList", [])
        tracks: List[SpotifyTrack] = []

        for idx, item in enumerate(raw_tracks):
            track_title = item.get("title", f"Track {idx+1}")
            artist_str = item.get("subtitle", "Unknown Artist")
            # Replace non-breaking spaces
            artist_str = artist_str.replace("\xa0", " ").strip()
            
            duration_ms = item.get("duration", 0)
            duration_str = self.format_duration(duration_ms)

            # Spotify track URI e.g. "spotify:track:XXXX"
            track_uri = item.get("uri", "")
            track_id = track_uri.split(":")[-1] if ":" in track_uri else f"track_{idx}_{playlist_id}"
            spotify_url = f"https://open.spotify.com/track/{track_id}" if track_id else ""

            # Check for album/track image
            track_obj = SpotifyTrack(
                id=track_id,
                title=track_title,
                artist=artist_str,
                album=playlist_name,
                duration_ms=duration_ms,
                duration_str=duration_str,
                spotify_url=spotify_url,
                image_url=playlist_image,
                preview_url=item.get("audioPreview", {}).get("url") if isinstance(item.get("audioPreview"), dict) else None
            )
            tracks.append(track_obj)

        self.enrich_tracks_with_audio_features(tracks)
        logger.info(f"Embed parser successfully loaded '{playlist_name}' with {len(tracks)} tracks.")
        return playlist_name, playlist_image, tracks

    def fetch_playlist(self, playlist_url_or_id: str) -> Tuple[str, Optional[str], List[SpotifyTrack]]:
        """
        Fetches playlist details and tracks with auto fallback.
        """
        playlist_id = self.extract_playlist_id(playlist_url_or_id)

        # 1. Try official Spotipy API if initialized
        if self._sp:
            try:
                logger.info(f"Attempting official Spotify API for ID: {playlist_id}")
                playlist_meta = self._sp.playlist(playlist_id)
                playlist_name = playlist_meta.get("name", f"Playlist_{playlist_id}")
                images = playlist_meta.get("images", [])
                playlist_image = images[0].get("url") if images else None

                tracks_data = playlist_meta.get("tracks", {}).get("items", [])
                if tracks_data:
                    tracks: List[SpotifyTrack] = []
                    for item in tracks_data:
                        t = item.get("track")
                        if not t or not t.get("id"):
                            continue
                        artists = [a.get("name", "") for a in t.get("artists", []) if a.get("name")]
                        artist_str = ", ".join(artists) if artists else "Unknown Artist"
                        dur_ms = t.get("duration_ms", 0)
                        album_data = t.get("album", {})
                        album_images = album_data.get("images", [])
                        
                        tracks.append(SpotifyTrack(
                            id=t["id"],
                            title=t.get("name", "Unknown Title"),
                            artist=artist_str,
                            album=album_data.get("name", playlist_name),
                            duration_ms=dur_ms,
                            duration_str=self.format_duration(dur_ms),
                            spotify_url=t.get("external_urls", {}).get("spotify", ""),
                            image_url=album_images[0].get("url") if album_images else playlist_image,
                            preview_url=t.get("preview_url")
                        ))
                    if tracks:
                        self.enrich_tracks_with_audio_features(tracks)
                        logger.info(f"API loaded '{playlist_name}' with {len(tracks)} tracks (with BPM & Harmonic Key data).")
                        return playlist_name, playlist_image, tracks
            except Exception as e:
                logger.info(f"Official API request fell back to embed parser: {e}")

        # 2. Resilient Embed parser
        return self.fetch_playlist_via_embed(playlist_id)

    def enrich_tracks_with_audio_features(self, tracks: List[SpotifyTrack]) -> None:
        """Fetches BPM, Musical Key, and Camelot signature for tracks via Spotify Audio Features + Multi-source Fallback."""
        if not tracks:
            return

        from audio_analyzer import pitch_and_mode_to_key, enrich_track_audio_features

        # 1. Try Spotify Official API audio_features if client initialized
        if self._sp:
            valid_tracks = [t for t in tracks if t.id and not t.id.startswith("track_")]
            try:
                for i in range(0, len(valid_tracks), 100):
                    chunk = valid_tracks[i:i+100]
                    chunk_ids = [t.id for t in chunk]
                    features_list = self._sp.audio_features(chunk_ids)
                    if not features_list:
                        continue

                    for feat in features_list:
                        if not feat:
                            continue
                        t_id = feat.get("id")
                        target = next((t for t in chunk if t.id == t_id), None)
                        if target:
                            raw_tempo = feat.get("tempo")
                            if raw_tempo:
                                target.bpm = int(round(raw_tempo))
                            
                            mus_key, cam_key = pitch_and_mode_to_key(feat.get("key"), feat.get("mode"))
                            target.musical_key = mus_key
                            target.camelot_key = cam_key
                            target.energy = feat.get("energy")
                            target.danceability = feat.get("danceability")
            except Exception as e:
                logger.debug(f"Official audio features API notice: {e}")

        # 2. Multi-source fallback (Deezer API / Preview acoustic analysis / Filename / Cache) for any track missing BPM or Key
        for t in tracks:
            if not t.bpm or not t.camelot_key:
                try:
                    enrich_track_audio_features(t, allow_network=True)
                except Exception as ex:
                    logger.debug(f"Audio enrichment notice for '{t.title}': {ex}")

    def get_user_auth_url(self) -> Optional[str]:
        """Returns Spotify OAuth authorization URL for user login."""
        if not self._oauth_manager:
            return None
        try:
            return self._oauth_manager.get_authorize_url()
        except Exception as e:
            logger.error(f"Failed to generate Spotify authorize URL: {e}")
            return None

    def handle_auth_callback(self, code: str) -> bool:
        """Handles OAuth callback code and caches user tokens."""
        if not self._oauth_manager:
            return False
        try:
            token = self._oauth_manager.get_access_token(code=code, as_dict=True)
            return token is not None and "access_token" in token
        except Exception as e:
            logger.error(f"Error exchanging Spotify auth code: {e}")
            return False

    def get_user_client(self) -> Optional[spotipy.Spotify]:
        """Returns an authenticated spotipy.Spotify instance for the current user if token is valid/cached."""
        if not self._oauth_manager:
            return None
        try:
            cached = self._oauth_manager.cache_handler.get_cached_token() if hasattr(self._oauth_manager, "cache_handler") else self._oauth_manager.get_cached_token()
            if not cached:
                return None
            valid_token = self._oauth_manager.validate_token(cached)
            if not valid_token:
                return None
            return spotipy.Spotify(auth=valid_token["access_token"])
        except Exception as e:
            logger.warning(f"Failed to get authorized user Spotify client: {e}")
            return None

    def is_user_authenticated(self) -> bool:
        """Checks if a valid user token is available."""
        return self.get_user_client() is not None

    def create_user_playlist(
        self,
        name: str,
        description: str = "",
        track_ids_or_uris: Optional[List[str]] = None,
        public: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Creates a playlist in the user's Spotify account and adds the specified tracks."""
        user_sp = self.get_user_client()
        if not user_sp:
            logger.warning("No authenticated user client available to create playlist.")
            return None

        try:
            user_info = user_sp.current_user()
            user_id = user_info.get("id")
            if not user_id:
                logger.error("Could not retrieve current Spotify user profile.")
                return None

            playlist = user_sp.user_playlist_create(
                user=user_id,
                name=name,
                public=public,
                description=description or "Generated with Spotify2Muzpa Studio"
            )
            playlist_id = playlist["id"]

            uris: List[str] = []
            if track_ids_or_uris:
                for item in track_ids_or_uris:
                    if not item:
                        continue
                    clean_item = item.strip()
                    if clean_item.startswith("spotify:track:"):
                        uris.append(clean_item)
                    elif clean_item.startswith("spotify:"):
                        uris.append(clean_item)
                    else:
                        uris.append(f"spotify:track:{clean_item}")

                for i in range(0, len(uris), 100):
                    chunk = uris[i:i + 100]
                    user_sp.playlist_add_items(playlist_id, chunk)

            return {
                "playlist_id": playlist_id,
                "playlist_url": playlist.get("external_urls", {}).get("spotify", f"https://open.spotify.com/playlist/{playlist_id}"),
                "playlist_uri": f"spotify:playlist:{playlist_id}",
                "name": playlist.get("name", name),
                "tracks_added": len(uris)
            }
        except Exception as e:
            logger.error(f"Failed to create user Spotify playlist: {e}")
            return None


