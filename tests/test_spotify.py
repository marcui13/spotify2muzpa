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


def test_spotify_oauth_helpers():
    from unittest.mock import MagicMock
    service = SpotifyService(client_id="dummy_id", client_secret="dummy_secret")
    service._oauth_manager = MagicMock()
    service._oauth_manager.get_authorize_url.return_value = "https://accounts.spotify.com/authorize?client_id=dummy"
    assert service.get_user_auth_url() == "https://accounts.spotify.com/authorize?client_id=dummy"

    service._oauth_manager.get_access_token.return_value = {"access_token": "mock_token"}
    assert service.handle_auth_callback("test_code") is True

    service._oauth_manager.cache_handler.get_cached_token.return_value = {"access_token": "cached"}
    service._oauth_manager.validate_token.return_value = {"access_token": "valid"}
    user_sp = service.get_user_client()
    assert user_sp is not None
    assert service.is_user_authenticated() is True


def test_spotify_create_user_playlist():
    from unittest.mock import MagicMock, patch
    service = SpotifyService(client_id="dummy_id", client_secret="dummy_secret")
    mock_sp = MagicMock()
    mock_sp.current_user.return_value = {"id": "test_user_123"}
    mock_sp.user_playlist_create.return_value = {
        "id": "pl_123",
        "name": "My DJ Set",
        "external_urls": {"spotify": "https://open.spotify.com/playlist/pl_123"}
    }

    with patch.object(service, "get_user_client", return_value=mock_sp):
        res = service.create_user_playlist(
            name="My DJ Set",
            description="Test Set",
            track_ids_or_uris=["spotify:track:abc", "def"]
        )
        assert res is not None
        assert res["playlist_id"] == "pl_123"
        assert res["playlist_uri"] == "spotify:playlist:pl_123"
        assert res["tracks_added"] == 2
        mock_sp.playlist_add_items.assert_called_once_with("pl_123", ["spotify:track:abc", "spotify:track:def"])

