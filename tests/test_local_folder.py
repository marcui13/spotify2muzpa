import pytest
from pathlib import Path
from models import SpotifyTrack, TrackState, PlaylistJob
from local_folder_service import (
    parse_filename_metadata,
    scan_folder_tracks,
    rename_files_with_order,
    export_m3u8
)


def test_parse_filename_metadata():
    assert parse_filename_metadata("01 - Fisher - Losing It.mp3") == ("Fisher", "Losing It")
    assert parse_filename_metadata("02. CamelPhat - Cola (Original Mix).flac") == ("CamelPhat", "Cola (Original Mix)")
    assert parse_filename_metadata("Meduza - Piece Of Your Heart.wav") == ("Meduza", "Piece Of Your Heart")
    assert parse_filename_metadata("SoloTrack.mp3") == ("Local Track", "SoloTrack")


def test_scan_folder_and_export_m3u8(tmp_path):
    # Create fake audio files
    file1 = tmp_path / "Artist One - Track Alpha.mp3"
    file2 = tmp_path / "Artist Two - Track Beta.mp3"
    file1.write_bytes(b"ID3" + b"\x00" * 1024)
    file2.write_bytes(b"ID3" + b"\x00" * 1024)

    folder_name, tracks = scan_folder_tracks(str(tmp_path))
    assert folder_name == tmp_path.name
    assert len(tracks) == 2
    assert tracks[0].spotify_track.title in ("Track Alpha", "Track Beta")

    job = PlaylistJob(
        playlist_id="test_local_job",
        playlist_name="My DJ Set",
        playlist_url=str(tmp_path),
        tracks=tracks
    )

    # Test M3U8 export
    m3u8_path = export_m3u8(job, output_dir=tmp_path)
    assert m3u8_path.exists()
    content = m3u8_path.read_text(encoding="utf-8")
    assert "#EXTM3U" in content
    assert "Track Alpha" in content or "Track Beta" in content


def test_rename_files_with_order(tmp_path):
    f1 = tmp_path / "Artist - Track A.mp3"
    f2 = tmp_path / "Artist - Track B.mp3"
    f1.write_bytes(b"fake mp3 data 1")
    f2.write_bytes(b"fake mp3 data 2")

    tracks = [
        TrackState(spotify_track=SpotifyTrack(id="t1", title="Track A", artist="Artist"), downloaded_file_path=str(f1)),
        TrackState(spotify_track=SpotifyTrack(id="t2", title="Track B", artist="Artist"), downloaded_file_path=str(f2))
    ]

    job = PlaylistJob(
        playlist_id="test_rename_job",
        playlist_name="Test Renaming",
        playlist_url=str(tmp_path),
        tracks=tracks
    )

    renamed = rename_files_with_order(job)
    assert len(renamed) == 2
    assert (tmp_path / "01 - Artist - Track A.mp3").exists()
    assert (tmp_path / "02 - Artist - Track B.mp3").exists()


def test_folder_api_endpoints(client, tmp_path):
    from server import orchestrator

    f1 = tmp_path / "DJ Guy - Banger.mp3"
    f1.write_bytes(b"ID3" + b"\x00" * 1024)

    # 1. Test POST /api/folder/load
    res = client.post("/api/folder/load", json={"folder_path": str(tmp_path)})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert len(data["job"]["tracks"]) == 1

    # 2. Test POST /api/folder/rename-order
    rename_res = client.post("/api/folder/rename-order")
    assert rename_res.status_code == 200
    assert rename_res.json()["status"] == "renamed"

    # 3. Test POST /api/folder/export-m3u
    export_res = client.post("/api/folder/export-m3u")
    assert export_res.status_code == 200
    assert export_res.json()["status"] == "exported"

    # Clean up
    orchestrator.current_job = None
