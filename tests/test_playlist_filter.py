import pytest
from models import SpotifyTrack
from playlist_filter_service import (
    normalize_text,
    parse_filter_prompt,
    matches_query,
    match_track,
    filter_tracks
)


def test_normalize_text():
    assert normalize_text("Guy J") == "guyj"
    assert normalize_text("Hernán Cattáneo") == "hernancattaneo"
    assert normalize_text("Daft Punk - One More Time (12\" Mix)") == "daftpunkonemoretime12mix"
    assert normalize_text("   ") == ""


def test_parse_filter_prompt():
    raw_prompt = "quiero hacer una playlist con todos los tracks de guyj que hay acá https://open.spotify.com/playlist/1lGxW0cD0ijTo5BJESD5eW?si=3323e6a0c514441b"
    url, query = parse_filter_prompt(raw_prompt)
    assert url == "https://open.spotify.com/playlist/1lGxW0cD0ijTo5BJESD5eW?si=3323e6a0c514441b"
    assert query == "guyj"

    # English prompt
    raw_en = "I want all tracks by Eric Prydz in this playlist https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
    url_en, query_en = parse_filter_prompt(raw_en)
    assert url_en == "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
    assert "eric prydz" in query_en.lower()

    # Plain URL without prompt
    url_plain, query_plain = parse_filter_prompt("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
    assert url_plain == "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
    assert query_plain == ""


def test_matches_query():
    # Exact match
    assert matches_query("Guy J", "Guy J") is True
    # Normalized match ('guyj' vs 'Guy J')
    assert matches_query("Guy J", "guyj") is True
    assert matches_query("Guy J", "GUY J") is True
    # Typo tolerance
    assert matches_query("Hernan Cattaneo", "Hernan Cataneo") is True
    # Negative match
    assert matches_query("Deadmau5", "Guy J") is False


def test_filter_tracks_artist_and_remix():
    t1 = SpotifyTrack(id="1", title="Lost & Found", artist="Guy J", album="Esperanza", duration_ms=500000)
    t2 = SpotifyTrack(id="2", title="Nirvana", artist="Khen", album="Prism", duration_ms=450000)
    t3 = SpotifyTrack(id="3", title="High & Low (Guy J Remix)", artist="Empire of the Sun", album="High & Low", duration_ms=420000)
    t4 = SpotifyTrack(id="4", title="Strobe", artist="Deadmau5", album="For Lack of a Better Name", duration_ms=600000)

    tracks = [t1, t2, t3, t4]

    # Filter with query 'guyj' (all)
    res_all = filter_tracks(tracks, query="guyj", filter_by="all")
    assert len(res_all) == 2
    assert t1 in res_all
    assert t3 in res_all

    # Filter with query 'guy j' (artist mode - should catch Guy J as artist and remixer in title)
    res_artist = filter_tracks(tracks, query="guy j", filter_by="artist")
    assert len(res_artist) == 2
    assert t1 in res_artist
    assert t3 in res_artist

    # Filter by title only
    res_title = filter_tracks(tracks, query="lost", filter_by="title")
    assert len(res_title) == 1
    assert res_title[0].id == "1"


def test_filter_tracks_bpm_and_key():
    t1 = SpotifyTrack(id="1", title="Track 1", artist="Artist A", bpm=124, camelot_key="8A")
    t2 = SpotifyTrack(id="2", title="Track 2", artist="Artist B", bpm=128, camelot_key="11B")
    t3 = SpotifyTrack(id="3", title="Track 3", artist="Artist C", bpm=124, camelot_key="11B")

    tracks = [t1, t2, t3]

    # Filter by BPM
    res_bpm = filter_tracks(tracks, min_bpm=123, max_bpm=125)
    assert len(res_bpm) == 2
    assert t1 in res_bpm
    assert t3 in res_bpm

    # Filter by Camelot Key
    res_key = filter_tracks(tracks, camelot_key="11b")
    assert len(res_key) == 2
    assert t2 in res_key
    assert t3 in res_key

    # Combined BPM and Key
    res_comb = filter_tracks(tracks, min_bpm=123, max_bpm=125, camelot_key="11B")
    assert len(res_comb) == 1
    assert res_comb[0].id == "3"


def test_server_filter_playlist_endpoint():
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from server import app

    client = TestClient(app)

    mock_tracks = [
        SpotifyTrack(id="1", title="Esperanza", artist="Guy J", album="Esperanza", duration_ms=400000),
        SpotifyTrack(id="2", title="Strobe", artist="Deadmau5", album="Random", duration_ms=600000),
        SpotifyTrack(id="3", title="Nirvana (Guy J Remix)", artist="Khen", album="Nirvana", duration_ms=450000),
    ]

    with patch("server.spotify_service.fetch_playlist", return_value=("Progressive Gems", "http://img.jpg", mock_tracks)):
        # Test 1: Combined prompt
        resp = client.post("/api/playlist/filter", json={
            "playlist_url": "quiero hacer una playlist con todos los tracks de guyj que hay acá https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "query": ""
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["total_tracks"] == 3
        assert data["matched_count"] == 2
        assert data["query"] == "guyj"
        assert len(data["tracks"]) == 2
        assert data["tracks"][0]["artist"] == "Guy J"

        # Test 2: Separate URL and Query
        resp2 = client.post("/api/playlist/filter", json={
            "playlist_url": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "query": "deadmau5"
        })
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["matched_count"] == 1
        assert data2["tracks"][0]["title"] == "Strobe"

        # Test 3: Empty query (no filter - returns all tracks)
        resp3 = client.post("/api/playlist/filter", json={
            "playlist_url": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "query": ""
        })
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert data3["matched_count"] == 3
        assert len(data3["tracks"]) == 3


def test_server_create_filtered_playlist_endpoint():
    from unittest.mock import patch, MagicMock
    from fastapi.testclient import TestClient
    from server import app

    client = TestClient(app)

    # When authenticated
    with patch("server.spotify_service.is_user_authenticated", return_value=True), \
         patch("server.spotify_service.create_user_playlist", return_value={
             "playlist_id": "pl_xyz",
             "playlist_url": "https://open.spotify.com/playlist/pl_xyz",
             "playlist_uri": "spotify:playlist:pl_xyz",
             "tracks_added": 2,
             "name": "Guy J Best"
         }):
        resp = client.post("/api/playlist/create-filtered", json={
            "playlist_name": "Guy J Best",
            "track_uris": ["spotify:track:1", "spotify:track:2"]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] is True
        assert data["playlist_id"] == "pl_xyz"
        assert data["tracks_added"] == 2

    # When not authenticated
    with patch("server.spotify_service.is_user_authenticated", return_value=False), \
         patch("server.spotify_service.get_user_auth_url", return_value="https://accounts.spotify.com/authorize?xyz"):
        resp = client.post("/api/playlist/create-filtered", json={
            "playlist_name": "Guy J Best",
            "track_uris": ["1", "2"]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] is False
        assert data["status"] == "auth_required"
        assert "auth_url" in data
        assert len(data["track_uris"]) == 2
        assert data["track_uris"][0] == "spotify:track:1"


def test_server_queue_filtered_to_muzpa():
    from fastapi.testclient import TestClient
    from server import app

    client = TestClient(app)
    sample_tracks = [
        {"id": "t1", "title": "Esperanza", "artist": "Guy J", "album": "Esperanza", "duration_ms": 400000, "duration_str": "06:40"}
    ]
    resp = client.post("/api/playlist/queue-filtered-to-muzpa", json={
        "playlist_name": "Guy J Mini",
        "tracks": sample_tracks
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

