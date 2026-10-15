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


def test_playlist_job_duration_computation():
    t1 = SpotifyTrack(id="1", title="Track 1", artist="Artist", duration_ms=3600000, duration_str="60:00")
    t2 = SpotifyTrack(id="2", title="Track 2", artist="Artist", duration_ms=1800000, duration_str="30:00")
    t3 = SpotifyTrack(id="3", title="Track 3", artist="Artist", duration_ms=120000, duration_str="02:00")

    job = PlaylistJob(
        playlist_id="pl_dur",
        playlist_name="Long Playlist",
        playlist_url="https://open.spotify.com/playlist/pl_dur",
        tracks=[
            TrackState(spotify_track=t1),
            TrackState(spotify_track=t2),
            TrackState(spotify_track=t3)
        ]
    )

    assert job.total_duration_ms == 5520000
    assert job.total_duration_str == "1 hr 32 min"

    # Test short playlist (< 1 hr)
    short_job = PlaylistJob(
        playlist_id="pl_short",
        playlist_name="Short Playlist",
        playlist_url="https://open.spotify.com/playlist/pl_short",
        tracks=[TrackState(spotify_track=t3)]
    )
    assert short_job.total_duration_ms == 120000
    assert short_job.total_duration_str == "2 min"


def test_tag_mp3_metadata_preserves_cover_when_playlist_image(tmp_path, monkeypatch):
    from downloader import tag_mp3_metadata
    from unittest.mock import MagicMock, patch

    track = SpotifyTrack(
        id="t_art",
        title="Sample",
        artist="DJ",
        duration_ms=200000,
        image_url="https://img.spotify.com/playlist_cover.jpg"
    )

    fake_file = tmp_path / "test.mp3"
    fake_file.write_bytes(b"dummy mp3 content")

    mock_id3 = MagicMock()
    mock_id3.getall.return_value = ["existing_apic"]

    with patch("downloader.EasyID3", return_value=MagicMock()) as mock_easy, \
         patch("mutagen.id3.ID3", return_value=mock_id3), \
         patch("requests.get") as mock_get:
        
        # When playlist_image matches track.image_url, requests.get MUST NOT be called!
        res = tag_mp3_metadata(fake_file, track, playlist_image="https://img.spotify.com/playlist_cover.jpg")
        assert res is True
        mock_get.assert_not_called()
        mock_id3.delall.assert_not_called()

