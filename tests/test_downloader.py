import pytest
from pathlib import Path
from downloader import sanitize_filename, StateManager
from models import PlaylistJob, TrackState, SpotifyTrack, TrackStatus


def test_sanitize_filename():
    assert sanitize_filename("Artist / Title: Special ? <Mix>") == "Artist _ Title_ Special _ _Mix_"
    assert sanitize_filename('AC/DC - Back in Black') == 'AC_DC - Back in Black'
    assert sanitize_filename("...Leading and Trailing Dots...") == "Leading and Trailing Dots"
    assert len(sanitize_filename("A" * 300)) == 200


def test_state_manager_save_and_load(tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "STATE_DIR", tmp_path)

    track = SpotifyTrack(
        id="t1",
        title="Test Song",
        artist="Test Artist",
        duration_ms=180000,
        duration_str="03:00"
    )
    job = PlaylistJob(
        playlist_id="test_pl_123",
        playlist_name="My Test Playlist",
        playlist_url="https://open.spotify.com/playlist/test_pl_123",
        tracks=[TrackState(spotify_track=track, status=TrackStatus.COMPLETED)]
    )

    # Save
    StateManager.save_job(job)
    
    # Load
    loaded = StateManager.load_job("test_pl_123")
    assert loaded is not None
    assert loaded.playlist_id == "test_pl_123"
    assert loaded.playlist_name == "My Test Playlist"
    assert len(loaded.tracks) == 1
    assert loaded.tracks[0].status == TrackStatus.COMPLETED
    assert loaded.tracks[0].spotify_track.title == "Test Song"
