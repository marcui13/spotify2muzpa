"""
Tests for DJ Set Tracklist Identification Service.
"""

import pytest
from dj_set_service import DJSetService
from models import DJSetTrackItem, DJSetJob


def test_seconds_to_timestamp_and_reverse():
    assert DJSetService.seconds_to_timestamp(0) == "00:00"
    assert DJSetService.seconds_to_timestamp(195) == "03:15"
    assert DJSetService.seconds_to_timestamp(3665) == "01:01:05"

    assert DJSetService.timestamp_to_seconds("00:00") == 0
    assert DJSetService.timestamp_to_seconds("03:15") == 195
    assert DJSetService.timestamp_to_seconds("01:01:05") == 3665


def test_is_ignored_title():
    assert DJSetService.is_ignored_title("Intro") is True
    assert DJSetService.is_ignored_title("00:00 Intro") is True
    assert DJSetService.is_ignored_title("OUTRO") is True
    assert DJSetService.is_ignored_title("Subscribe to our channel") is True
    assert DJSetService.is_ignored_title("Bicep - Glue") is False


def test_parse_tracklist_text_various_formats():
    sample_description = """
    Tracklist:
    00:00 Intro
    03:15 Bicep - Glue
    [07:45] Four Tet - Baby (Extended)
    (12:30) Tale Of Us - Endless
    15:45 - Stephan Bodzin - Power
    Peggy Gou - Naná [22:15]
    Solomun - Customer Is King (30:00)
    01:05:20 Maceo Plex - Mutant Romance
    01:45:00 Outro & Thanks for watching
    """
    results = DJSetService.parse_tracklist_text(sample_description)
    assert len(results) >= 6

    # Verify order and extraction
    # 03:15 -> 195s
    assert results[0][0] == 195
    assert "Bicep" in results[0][1]
    assert "Glue" in results[0][2]

    # 07:45 -> 465s
    assert results[1][0] == 465
    assert "Four Tet" in results[1][1]

    # 01:05:20 -> 3920s
    last_track = [r for r in results if r[0] == 3920]
    assert len(last_track) == 1
    assert "Maceo Plex" in last_track[0][1]
    assert "Mutant Romance" in last_track[0][2]


def test_parse_chapters():
    chapters = [
        {"start_time": 0.0, "end_time": 180.0, "title": "Intro"},
        {"start_time": 180.0, "end_time": 420.0, "title": "Bicep - Glue"},
        {"start_time": 420.0, "end_time": 720.0, "title": "Four Tet – Baby"},
        {"start_time": 720.0, "end_time": 900.0, "title": "Outro"}
    ]
    results = DJSetService.parse_chapters(chapters)
    assert len(results) == 2
    assert results[0] == (180, "Bicep", "Glue")
    assert results[1] == (420, "Four Tet", "Baby")


def test_deduplicate_tracks():
    # Simulating acoustic detections every 90s where a track spans multiple slices
    raw = [
        (180, "Bicep", "Glue"),
        (270, "Bicep", "Glue (Original Mix)"),
        (360, "Bicep", "Glue"),
        (450, "Four Tet", "Baby"),
        (540, "Four Tet", "Baby"),
        (630, "Stephan Bodzin", "Power")
    ]
    deduped = DJSetService.deduplicate_tracks(raw)
    assert len(deduped) == 3

    # First track: Bicep - Glue spanning from 03:00 to 06:00
    assert deduped[0].artist == "Bicep"
    assert "Glue" in deduped[0].title
    assert deduped[0].timestamp == "03:00"
    assert deduped[0].end_timestamp == "06:00"

    # Second track: Four Tet - Baby spanning from 07:30 to 09:00
    assert deduped[1].artist == "Four Tet"
    assert deduped[1].timestamp == "07:30"
    assert deduped[1].end_timestamp == "09:00"

    # Third track: Stephan Bodzin - Power
    assert deduped[2].artist == "Stephan Bodzin"
    assert deduped[2].timestamp == "10:30"


def test_convert_to_playlist_job():
    service = DJSetService()
    job = DJSetJob(
        job_id="test_job_123",
        source_url="https://www.youtube.com/watch?v=sample",
        title="Afterlife Tulum 2026",
        duration_seconds=7200,
        tracks=[
            DJSetTrackItem(
                id="track_1",
                timestamp="00:03:00",
                artist="Tale Of Us",
                title="Endless",
                spotify_id="spotify_111",
                bpm=124,
                camelot_key="8A"
            ),
            DJSetTrackItem(
                id="track_2",
                timestamp="00:08:30",
                artist="Bicep",
                title="Glue",
                spotify_id="spotify_222",
                bpm=130,
                camelot_key="11B"
            )
        ]
    )
    service.active_jobs["test_job_123"] = job

    playlist_job = service.convert_to_playlist_job("test_job_123")
    assert playlist_job.playlist_id == "djset_test_job_123"
    assert "Afterlife Tulum 2026" in playlist_job.playlist_name
    assert len(playlist_job.tracks) == 2
    assert playlist_job.tracks[0].spotify_track.artist == "Tale Of Us"
    assert playlist_job.tracks[0].spotify_track.bpm == 124
    assert playlist_job.tracks[0].spotify_track.camelot_key == "8A"
    assert playlist_job.tracks[1].spotify_track.title == "Glue"


def test_clean_source_url():
    sc_dirty = "https://soundcloud.com/simonvuarambon/metropolitano2026?utm_source=clipboard&utm_medium=text&utm_campaign=social_sharing"
    assert DJSetService.clean_source_url(sc_dirty) == "https://soundcloud.com/simonvuarambon/metropolitano2026"

    yt_dirty = "https://www.youtube.com/watch?v=gCYcHz2k5x0&utm_source=test&si=12345"
    assert DJSetService.clean_source_url(yt_dirty) == "https://www.youtube.com/watch?v=gCYcHz2k5x0"


@pytest.mark.asyncio
async def test_shazam_retry_on_429(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock, MagicMock
    from dj_set_service import ShazamRecognitionClient

    client = ShazamRecognitionClient()

    # Create dummy dummy audio slice file
    test_slice = tmp_path / "test_slice.wav"
    test_slice.write_bytes(b"RIFF" + b"\x00" * 2000)

    # Mock recognizer
    mock_sig = MagicMock()
    mock_sig.signature.uri = "data:audio/vnd.shazam.sig;base64,AAA"
    mock_sig.signature.samples = 10000
    mock_sig.timestamp = 1000

    mock_rec = AsyncMock()
    mock_rec.recognize_path.return_value = mock_sig
    client.recognizer = mock_rec

    # Simulate httpx returning 429 first, then 200 with track
    call_count = 0

    class MockResponse:
        def __init__(self, status_code, json_data=None, headers=None):
            self.status_code = status_code
            self._json = json_data or {}
            self.headers = headers or {}

        def json(self):
            return self._json

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MockResponse(429, headers={"Retry-After": "0.01"})
        return MockResponse(200, json_data={"track": {"title": "Papta Swing", "subtitle": "Earful Soul"}})

    # Patch httpx.AsyncClient.post
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    track = await client.recognize_slice(str(test_slice), max_retries=3, retry_backoff=0.01)
    assert track is not None
    assert track["title"] == "Papta Swing"
    assert call_count == 2


@pytest.mark.asyncio
async def test_djset_resolve_youtube_playlist(monkeypatch):
    from dj_set_service import DJSetService
    from models import DJSetJob, DJSetTrackItem

    service = DJSetService()
    job = DJSetJob(
        job_id="job_yt_test",
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Rick Astley Live Set",
        tracks=[
            DJSetTrackItem(id="t1", timestamp="00:00", artist="Rick Astley", title="Never Gonna Give You Up"),
            DJSetTrackItem(id="t2", timestamp="03:30", artist="Rick Astley", title="Together Forever", youtube_id="y6120QOlsfU")
        ]
    )
    service.active_jobs["job_yt_test"] = job

    class MockYDL:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, query, download=False):
            return {"entries": [{"id": "dQw4w9WgXcQ", "title": "Never Gonna Give You Up"}]}

    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYDL)

    res = await service.resolve_youtube_playlist("job_yt_test")
    assert res["status"] == "success"
    assert res["total_tracks"] == 2
    assert res["resolved_tracks"] == 2
    assert "dQw4w9WgXcQ" in res["video_ids"]
    assert "y6120QOlsfU" in res["video_ids"]
    assert "https://www.youtube.com/watch_videos?video_ids=" in res["playlist_url"]
    assert "dQw4w9WgXcQ" in res["playlist_url"]
    assert "y6120QOlsfU" in res["playlist_url"]


