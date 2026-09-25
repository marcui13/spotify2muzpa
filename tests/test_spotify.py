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


def test_parse_spotify_entity_variations():
    # Playlist
    assert SpotifyService.parse_spotify_entity("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=123") == ("playlist", "37i9dQZF1DXcBWIGoYBM5M")
    assert SpotifyService.parse_spotify_entity("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M") == ("playlist", "37i9dQZF1DXcBWIGoYBM5M")

    # Album
    assert SpotifyService.parse_spotify_entity("https://open.spotify.com/album/4m2880jivSbbyEGAKfITCa?si=test") == ("album", "4m2880jivSbbyEGAKfITCa")
    assert SpotifyService.parse_spotify_entity("spotify:album:4m2880jivSbbyEGAKfITCa") == ("album", "4m2880jivSbbyEGAKfITCa")

    # Track
    assert SpotifyService.parse_spotify_entity("https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6?si=abc") == ("track", "6rqhFgbbKwnb9MLmUQDhG6")
    assert SpotifyService.parse_spotify_entity("spotify:track:6rqhFgbbKwnb9MLmUQDhG6") == ("track", "6rqhFgbbKwnb9MLmUQDhG6")

    # Raw ID
    assert SpotifyService.parse_spotify_entity("4m2880jivSbbyEGAKfITCa") == ("playlist", "4m2880jivSbbyEGAKfITCa")

    # Invalid
    with pytest.raises(ValueError):
        SpotifyService.parse_spotify_entity("https://unknown.com/music/123")


def test_extract_playlist_id_album_and_track():
    assert SpotifyService.extract_playlist_id("https://open.spotify.com/album/4m2880jivSbbyEGAKfITCa") == "4m2880jivSbbyEGAKfITCa"
    assert SpotifyService.extract_playlist_id("https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6") == "6rqhFgbbKwnb9MLmUQDhG6"
    assert SpotifyService.extract_playlist_id("spotify:album:4m2880jivSbbyEGAKfITCa") == "4m2880jivSbbyEGAKfITCa"



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


def test_fetch_album_official_api():
    from unittest.mock import MagicMock, patch
    service = SpotifyService(client_id="dummy", client_secret="dummy")
    service._sp = MagicMock()
    service._sp.album.return_value = {
        "name": "Discovery",
        "images": [{"url": "https://img.spotify.com/album123.jpg"}],
        "tracks": {
            "items": [
                {
                    "id": "t1",
                    "name": "One More Time",
                    "artists": [{"name": "Daft Punk"}],
                    "duration_ms": 320000,
                    "external_urls": {"spotify": "https://open.spotify.com/track/t1"},
                    "preview_url": None
                }
            ]
        }
    }

    with patch.object(service, "enrich_tracks_with_audio_features"):
        name, img, tracks = service.fetch_playlist("https://open.spotify.com/album/album_123")
        assert name == "Discovery"
        assert img == "https://img.spotify.com/album123.jpg"
        assert len(tracks) == 1
        assert tracks[0].title == "One More Time"
        assert tracks[0].artist == "Daft Punk"
        assert tracks[0].album == "Discovery"


def test_fetch_track_official_api():
    from unittest.mock import MagicMock, patch
    service = SpotifyService(client_id="dummy", client_secret="dummy")
    service._sp = MagicMock()
    service._sp.track.return_value = {
        "id": "track_123",
        "name": "Harder, Better, Faster, Stronger",
        "artists": [{"name": "Daft Punk"}],
        "duration_ms": 224000,
        "album": {
            "name": "Discovery",
            "images": [{"url": "https://img.spotify.com/album123.jpg"}]
        },
        "external_urls": {"spotify": "https://open.spotify.com/track/track_123"},
        "preview_url": None
    }

    with patch.object(service, "enrich_tracks_with_audio_features"):
        name, img, tracks = service.fetch_playlist("https://open.spotify.com/track/track_123")
        assert name == "Harder, Better, Faster, Stronger"
        assert img == "https://img.spotify.com/album123.jpg"
        assert len(tracks) == 1
        assert tracks[0].title == "Harder, Better, Faster, Stronger"
        assert tracks[0].artist == "Daft Punk"
        assert tracks[0].album == "Discovery"


def test_fetch_playlist_tracks_preserve_individual_album_art():
    from unittest.mock import MagicMock, patch
    service = SpotifyService(client_id="dummy", client_secret="dummy")
    service._sp = MagicMock()
    service._sp.playlist.return_value = {
        "name": "My Top 100",
        "images": [{"url": "https://img.spotify.com/playlist_giant_cover.jpg"}],
        "tracks": {
            "items": [
                {
                    "track": {
                        "id": "t_unique_1",
                        "name": "Track A",
                        "artists": [{"name": "Artist A"}],
                        "duration_ms": 200000,
                        "album": {
                            "name": "Album A",
                            "images": [{"url": "https://img.spotify.com/album_a_art.jpg"}]
                        },
                        "external_urls": {"spotify": "https://open.spotify.com/track/t_unique_1"},
                        "preview_url": None
                    }
                },
                {
                    "track": {
                        "id": "t_unique_2",
                        "name": "Track B",
                        "artists": [{"name": "Artist B"}],
                        "duration_ms": 250000,
                        "album": {
                            "name": "Album B",
                            "images": []
                        },
                        "external_urls": {"spotify": "https://open.spotify.com/track/t_unique_2"},
                        "preview_url": None
                    }
                }
            ],
            "next": None
        }
    }

    with patch.object(service, "enrich_tracks_with_audio_features"):
        pl_name, pl_img, tracks = service.fetch_playlist("https://open.spotify.com/playlist/pl_123")
        assert pl_name == "My Top 100"
        assert pl_img == "https://img.spotify.com/playlist_giant_cover.jpg"
        assert len(tracks) == 2

        # Track 1 must have its own album cover, NEVER the playlist cover!
        assert tracks[0].image_url == "https://img.spotify.com/album_a_art.jpg"
        assert tracks[0].album == "Album A"

        # Track 2 has no album images, so its image_url must be None (NEVER the playlist cover!)
        assert tracks[1].image_url is None
        assert tracks[1].album == "Album B"



