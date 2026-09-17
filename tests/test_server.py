import pytest
from fastapi.testclient import TestClient
from server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Spotify to Muzpa" in response.text


def test_get_state_empty(client):
    response = client.get("/api/state")
    assert response.status_code == 200
    data = response.json()
    assert "active" in data
    assert "job" in data


def test_update_config(client):
    response = client.post("/api/config", json={"auto_mode": True, "similarity_threshold": 85.0})
    assert response.status_code == 200
    assert response.json() == {"status": "updated"}


def test_browser_list(client):
    response = client.get("/api/browser/list")
    assert response.status_code == 200
    data = response.json()
    assert "current" in data
    assert "browsers" in data


def test_muzpa_credentials_flow(client):
    # Test GET
    get_res = client.get("/api/muzpa/credentials")
    assert get_res.status_code == 200
    assert "configured" in get_res.json()

    # Test POST
    post_res = client.post("/api/muzpa/credentials", json={"email": "test@example.com", "password": "secretpassword", "auto_submit": False})
    assert post_res.status_code == 200
    assert post_res.json()["status"] == "saved"


def test_track_decision_endpoints(client):
    # Test confirm endpoint
    conf_res = client.post("/api/track/confirm", json={"track_id": "test_track_1", "candidate_id": "cand_1"})
    assert conf_res.status_code == 200
    assert conf_res.json()["status"] == "confirmed"

    # Test skip endpoint
    skip_res = client.post("/api/track/skip", json={"track_id": "test_track_1"})
    assert skip_res.status_code == 200
    assert skip_res.json()["status"] == "skipped"

    # Test search custom endpoint
    search_res = client.post("/api/track/search", json={"track_id": "test_track_1", "custom_query": "Artist - Custom Song"})
    assert search_res.status_code == 200
    assert search_res.json()["status"] == "searching"

    # Test decide endpoint
    decide_res = client.post("/api/track/decide", json={"track_id": "test_track_1", "action": "CONFIRM", "candidate_id": "cand_1"})
    assert decide_res.status_code == 200
    assert decide_res.json()["status"] == "decision_received"


def test_jump_to_track(client):
    from server import orchestrator
    from models import PlaylistJob, TrackState, SpotifyTrack

    job = PlaylistJob(
        playlist_id="test_pl_jump",
        playlist_name="Test Jump",
        playlist_url="https://open.spotify.com/playlist/test_pl_jump",
        tracks=[
            TrackState(spotify_track=SpotifyTrack(id="t1", title="Song 1", artist="Artist 1")),
            TrackState(spotify_track=SpotifyTrack(id="t2", title="Song 2", artist="Artist 2")),
            TrackState(spotify_track=SpotifyTrack(id="t3", title="Song 3", artist="Artist 3")),
        ]
    )
    orchestrator.current_job = job

    # Jump to track 3 (id: t3)
    jump_res = client.post("/api/track/jump", json={"track_id": "t3"})
    assert jump_res.status_code == 200
    assert jump_res.json()["status"] == "jumped"
    assert orchestrator.current_job.current_track_index == 2

    # Clean up
    if orchestrator._worker_task:
        orchestrator._worker_task.cancel()
    orchestrator.current_job = None


def test_load_playlist_force_fresh(client, monkeypatch):
    from server import spotify_service, orchestrator
    from models import SpotifyTrack

    # Mock spotify fetch
    monkeypatch.setattr(
        spotify_service,
        "fetch_playlist",
        lambda url: ("Mock Playlist", "https://img.jpg", [
            SpotifyTrack(id="mock_t1", title="Mock Track 1", artist="Mock Artist"),
            SpotifyTrack(id="mock_t2", title="Mock Track 2", artist="Mock Artist"),
        ])
    )

    res = client.post("/api/playlist/load", json={"playlist_url": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", "force_fresh": True})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["reloaded_fresh"] is True
    assert len(data["job"]["tracks"]) == 2

    # Clean up
    if orchestrator._worker_task:
        orchestrator._worker_task.cancel()
    orchestrator.current_job = None


def test_djset_endpoints(client, monkeypatch):
    from server import dj_set_service, orchestrator
    from models import DJSetTrackItem, DJSetJob

    # Seed a completed mock job
    mock_job = DJSetJob(
        job_id="test_set_999",
        source_url="https://www.youtube.com/watch?v=mock_video",
        title="Mock Festival Set 2026",
        duration_seconds=3600,
        status="complete",
        tracks=[
            DJSetTrackItem(
                id="track_1",
                timestamp="00:00",
                artist="Camelphat",
                title="Cola",
                spotify_id="spotify_cola_1"
            )
        ]
    )
    dj_set_service.active_jobs["test_set_999"] = mock_job

    # 1. Test get status
    res = client.get("/api/djset/status/test_set_999")
    assert res.status_code == 200
    assert res.json()["job"]["title"] == "Mock Festival Set 2026"
    assert len(res.json()["job"]["tracks"]) == 1

    # 2. Test export spotify endpoint
    res = client.post("/api/djset/export-spotify", json={"job_id": "test_set_999"})
    assert res.status_code == 200
    assert res.json()["matched_tracks"] == 1

    # 3. Test to-playlist conversion
    res = client.post("/api/djset/to-playlist", json={
        "job_id": "test_set_999",
        "playlist_name": "My Converted DJ Set",
        "auto_mode": True,
        "similarity_threshold": 80.0
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["job"]["playlist_name"] == "My Converted DJ Set"
    assert len(data["job"]["tracks"]) == 1

    # Clean up
    if orchestrator._worker_task:
        orchestrator._worker_task.cancel()
    orchestrator.current_job = None


def test_spotify_auth_and_export_endpoints(client, monkeypatch):
    from server import spotify_service, dj_set_service
    from models import DJSetJob, DJSetTrackItem

    # Mock spotify_service auth methods
    monkeypatch.setattr(spotify_service, "get_user_auth_url", lambda: "https://accounts.spotify.com/authorize?mock=1")
    monkeypatch.setattr(spotify_service, "is_user_authenticated", lambda: False)
    monkeypatch.setattr(spotify_service, "handle_auth_callback", lambda code: code == "valid_code")

    # 1. Auth URL
    res = client.get("/api/spotify/auth-url")
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert "https://accounts.spotify.com" in res.json()["auth_url"]

    # 2. Status
    res = client.get("/api/spotify/status")
    assert res.status_code == 200
    assert res.json()["is_authenticated"] is False

    # 3. Callback with valid code
    res = client.get("/api/spotify/callback?code=valid_code")
    assert res.status_code == 200
    assert "Connected to Spotify" in res.text

    # 4. Callback with error
    res = client.get("/api/spotify/callback?error=access_denied")
    assert res.status_code == 200
    assert "Authorization Failed" in res.text

    # 5. Export to Spotify when user not yet authenticated
    job = DJSetJob(
        job_id="test_exp_job",
        source_url="https://youtube.com/watch?v=123",
        title="Live Mix",
        tracks=[DJSetTrackItem(id="t1", timestamp="0:00", artist="Artist", title="Song", spotify_id="sp123")]
    )
    dj_set_service.active_jobs["test_exp_job"] = job

    res = client.post("/api/djset/export-spotify", json={"job_id": "test_exp_job"})
    assert res.status_code == 200
    assert res.json()["status"] == "auth_required"
    assert res.json()["created"] is False
    assert len(res.json()["track_uris"]) == 1

    # 6. Export to Spotify when user authenticated
    monkeypatch.setattr(spotify_service, "is_user_authenticated", lambda: True)
    monkeypatch.setattr(spotify_service, "create_user_playlist", lambda name, description, track_ids_or_uris: {
        "playlist_id": "pl_created_456",
        "playlist_url": "https://open.spotify.com/playlist/pl_created_456",
        "playlist_uri": "spotify:playlist:pl_created_456",
        "name": name,
        "tracks_added": len(track_ids_or_uris)
    })

    res = client.post("/api/djset/export-spotify", json={"job_id": "test_exp_job"})
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert res.json()["created"] is True
    assert res.json()["playlist_id"] == "pl_created_456"

    # 7. Export to YouTube endpoint
    async def mock_resolve(target_id):
        return {
            "status": "success",
            "playlist_name": "Live Mix",
            "total_tracks": 1,
            "resolved_tracks": 1,
            "video_ids": ["vid_123"],
            "playlist_url": "https://www.youtube.com/watch_videos?video_ids=vid_123",
            "tracklist_text": "1. Artist - Song"
        }
    monkeypatch.setattr(dj_set_service, "resolve_youtube_playlist", mock_resolve)

    res = client.post("/api/djset/export-youtube", json={"job_id": "test_exp_job"})
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert "https://www.youtube.com/watch_videos?video_ids=vid_123" == res.json()["playlist_url"]

