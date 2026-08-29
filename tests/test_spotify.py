import pytest
from spotify_service import SpotifyService
from models import SpotifyTrack


def test_extract_playlist_id_url():
    url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=12345abcdef"
    assert SpotifyService.extract_playlist_id(url) == "37i9dQZF1DXcBWIGoYBM5M"


def test_extract_playlist_id_uri():
    uri = "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
    assert SpotifyService.extract_playlist_id(uri) == "37i9dQZF1DXcBWIGoYBM5M"


def test_extract_playlist_id_raw():
    raw_id = "37i9dQZF1DXcBWIGoYBM5M"
    assert SpotifyService.extract_playlist_id(raw_id) == "37i9dQZF1DXcBWIGoYBM5M"


def test_format_duration():
    assert SpotifyService.format_duration(215000) == "03:35"
    assert SpotifyService.format_duration(60000) == "01:00"
    assert SpotifyService.format_duration(45000) == "00:45"


def test_spotify_track_clean_query():
    track = SpotifyTrack(
        id="test1",
        title="One More Time (feat. Romanthony) - Radio Edit",
        artist="Daft Punk",
        album="Discovery",
        duration_ms=320000,
        duration_str="05:20"
    )
    clean = track.clean_search_query
    assert "Daft Punk" in clean
    assert "One More Time" in clean
    assert "feat." not in clean
