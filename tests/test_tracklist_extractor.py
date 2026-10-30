import os
import base64
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from models import ExtractedTrackItem
from tracklist_extractor_service import (
    parse_single_trackline,
    parse_tracklist_lines,
    extract_text_from_image,
    create_playlist_job_from_extracted,
    is_macos_vision_available
)
from unittest.mock import patch
from server import app


def test_parse_single_trackline_various_formats():
    # Numbered with dash
    p1 = parse_single_trackline("1 - JUAN DEMINICIS & CASNIK - PHASEBREAKER")
    assert p1 == ("JUAN DEMINICIS & CASNIK", "PHASEBREAKER")

    # Bullet marker with dash
    p2 = parse_single_trackline("- EMPHI - ANTHOZOA")
    assert p2 == ("EMPHI", "ANTHOZOA")

    # Number with dot and dot separator
    p3 = parse_single_trackline("7 . LUCIANO FICARRA . GONE")
    assert p3 == ("LUCIANO FICARRA", "GONE")

    # Dot numbering with remix
    p4 = parse_single_trackline("04. Guy J - Beast (Original Mix)")
    assert p4 == ("Guy J", "Beast (Original Mix)")

    # Bracket numbering with label
    p5 = parse_single_trackline("[05] Khen - Foreign Paths [Bedrock Records]")
    assert p5 == ("Khen", "Foreign Paths")

    # Reverse format: "Title by Artist"
    p6 = parse_single_trackline("Strobe by Deadmau5")
    assert p6 == ("Deadmau5", "Strobe")

    # Tab separated
    p7 = parse_single_trackline("Eric Prydz\tOpus")
    assert p7 == ("Eric Prydz", "Opus")

    # Clutter lines should return None
    assert parse_single_trackline("Tracklist:") is None
    assert parse_single_trackline("Mixed by Hernan Cattaneo") is None
    assert parse_single_trackline("https://open.spotify.com/track/123") is None
    assert parse_single_trackline("@djsunset") is None


def test_parse_tracklist_lines_full_text():
    sample_text = """
    TRACKLIST:
    1 - Juan Deminicis & Casnik - Phasebreaker
    2 - Emphi - Anthozoa
    3 - Tato Seco - Caraxes
    4 - Maze 28 - Lights On
    5 - Maze 28 & Ricky Ryan - 5am Again
    
    Enjoy the set!
    """
    tracks = parse_tracklist_lines(sample_text)
    assert len(tracks) == 5
    assert tracks[0].artist == "Juan Deminicis & Casnik"
    assert tracks[0].title == "Phasebreaker"
    assert tracks[0].index == 1
    assert tracks[4].artist == "Maze 28 & Ricky Ryan"
    assert tracks[4].title == "5am Again"
    assert tracks[4].index == 5


def test_create_playlist_job_from_extracted():
    items = [
        ExtractedTrackItem(index=1, artist="Emphi", title="Anthozoa"),
        ExtractedTrackItem(index=2, artist="Maze 28", title="Lights On")
    ]
    job = create_playlist_job_from_extracted(items, playlist_name="Test Set", auto_mode=True, similarity_threshold=80.0)
    assert job.playlist_name == "Test Set"
    assert job.auto_mode is True
    assert job.similarity_threshold == 80.0
    assert len(job.tracks) == 2
    assert job.tracks[0].spotify_track.clean_search_query == "Emphi - Anthozoa"
    assert "Emphi - Anthozoa" in job.tracks[0].spotify_track.search_queries


def test_extract_text_from_image_vision():
    sample_text = (
        "1 - DEMINICIS & CASNIK - PHASEBREAKER\n"
        "2 - EMPHI - ANTHOZOA\n"
        "3 - TATO SECO - CARAXES\n"
    )
    with patch("tracklist_extractor_service.is_macos_vision_available", return_value=True), \
         patch("tracklist_extractor_service.extract_text_with_apple_vision", return_value=sample_text):
        raw_text = extract_text_from_image(image_bytes=b"fake-image-bytes")
        assert "PHASEBREAKER" in raw_text
        assert "ANTHOZOA" in raw_text
        assert "CARAXES" in raw_text

        tracks = parse_tracklist_lines(raw_text)
        assert len(tracks) == 3
        assert "DEMINICIS" in tracks[0].artist
        assert "PHASEBREAKER" in tracks[0].title
        assert "EMPHI" in tracks[1].artist
        assert "ANTHOZOA" in tracks[1].title


def test_extract_text_from_image_pytesseract_fallback():
    sample_text = (
        "1 - FALLBACK ARTIST - FALLBACK TITLE\n"
    )
    with patch("tracklist_extractor_service.is_macos_vision_available", return_value=False), \
         patch("tracklist_extractor_service.extract_text_with_pytesseract", return_value=sample_text):
        raw_text = extract_text_from_image(image_bytes=b"fake-image-bytes")
        assert "FALLBACK ARTIST" in raw_text
        tracks = parse_tracklist_lines(raw_text)
        assert len(tracks) == 1
        assert tracks[0].artist == "FALLBACK ARTIST"
        assert tracks[0].title == "FALLBACK TITLE"


def test_server_extract_endpoints():
    client = TestClient(app)

    # 1. Text parsing endpoint
    res_text = client.post("/api/extract/parse-text", json={
        "text": "1 - Artist One - Title One\n2 - Artist Two - Title Two"
    })
    assert res_text.status_code == 200
    data_text = res_text.json()
    assert data_text["status"] == "success"
    assert len(data_text["tracks"]) == 2
    assert data_text["tracks"][0]["artist"] == "Artist One"
    assert data_text["tracks"][0]["title"] == "Title One"

    # 2. Queue to Muzpa endpoint
    res_queue = client.post("/api/extract/queue-to-muzpa", json={
        "playlist_name": "Queued OCR Set",
        "tracks": data_text["tracks"],
        "auto_mode": False,
        "similarity_threshold": 75.0
    })
    assert res_queue.status_code == 200
    data_queue = res_queue.json()
    assert data_queue["status"] == "success"
    assert data_queue["job"]["playlist_name"] == "Queued OCR Set"
    assert len(data_queue["job"]["tracks"]) == 2

    # 3. Image extraction endpoint
    sample_ocr = "1 - Deminicis - Phasebreaker\n2 - Emphi - Anthozoa"
    with patch("tracklist_extractor_service.extract_text_from_image", return_value=sample_ocr):
        b64_dummy = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY44YAAAAASUVORK5CYII="
        res_img = client.post("/api/extract/image", json={
            "image_base64": b64_dummy
        })
        assert res_img.status_code == 200
        data_img = res_img.json()
        assert data_img["status"] == "success"
        assert len(data_img["tracks"]) == 2
        assert data_img["tracks"][0]["artist"] == "Deminicis"
        assert data_img["tracks"][0]["title"] == "Phasebreaker"
