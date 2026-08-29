import pytest
from muzpa_crawler import MuzpaCrawlerEngine
from models import SpotifyTrack


@pytest.fixture
def crawler():
    return MuzpaCrawlerEngine()


def test_fuzzy_score_exact_match(crawler):
    target = SpotifyTrack(
        id="1",
        title="Get Lucky",
        artist="Daft Punk",
        duration_ms=248000,
        duration_str="04:08"
    )
    score = crawler.calculate_fuzzy_score(target, "Get Lucky", "Daft Punk", "04:08")
    assert score >= 95.0


def test_fuzzy_score_remix_variation(crawler):
    target = SpotifyTrack(
        id="2",
        title="Titanium",
        artist="David Guetta",
        duration_ms=245000,
        duration_str="04:05"
    )
    # Match with feat Sia in title/artist
    score = crawler.calculate_fuzzy_score(target, "Titanium (feat. Sia)", "David Guetta", "04:05")
    assert score >= 80.0


def test_fuzzy_score_inverted_order(crawler):
    target = SpotifyTrack(
        id="3",
        title="Strobe",
        artist="Deadmau5",
        duration_ms=637000,
        duration_str="10:37"
    )
    score = crawler.calculate_fuzzy_score(target, "Deadmau5 - Strobe", "Deadmau5", "10:37")
    assert score >= 85.0


def test_fuzzy_score_duration_penalty(crawler):
    target = SpotifyTrack(
        id="4",
        title="Levels",
        artist="Avicii",
        duration_ms=200000, # 03:20
        duration_str="03:20"
    )
    # A preview or extended mix of completely different length (e.g. 08:00 vs 03:20)
    score_mismatched_dur = crawler.calculate_fuzzy_score(target, "Levels", "Avicii", "08:00")
    score_exact_dur = crawler.calculate_fuzzy_score(target, "Levels", "Avicii", "03:20")
    
    assert score_exact_dur > score_mismatched_dur


def test_parse_duration_string_formats():
    from muzpa_crawler import parse_duration_string

    # Standard MM:SS
    assert parse_duration_string("03:45") == "3:45"
    assert parse_duration_string("4:12") == "4:12"
    assert parse_duration_string("1:05:30") == "1:05:30"

    # Text formats with units
    assert parse_duration_string("3m 45s") == "3:45"
    assert parse_duration_string("3min 45sec") == "3:45"
    assert parse_duration_string("04:12 min") == "4:12"

    # Pure seconds and milliseconds
    assert parse_duration_string("225") == "3:45"
    assert parse_duration_string("225s") == "3:45"
    assert parse_duration_string("225000") == "3:45"

    # Extraction from raw_text with noise / timestamps
    raw = "2024-05-12 14:30 Published 320 kbps 03:20 Download"
    assert parse_duration_string(None, raw_text=raw, target_duration_ms=200000) == "3:20"

    # Empty / invalid fallback
    assert parse_duration_string(None, raw_text="no time here") == "--:--"

