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


def test_clean_track_title_mixed_variations():
    from models import clean_track_title

    assert clean_track_title("Glue - Mixed") == "Glue"
    assert clean_track_title("Cola (Mixed)") == "Cola"
    assert clean_track_title("Breathe [Mixed]") == "Breathe"
    assert clean_track_title("Space Diver - Continuous Mix") == "Space Diver"
    assert clean_track_title("Song [Continuous DJ Mix]") == "Song"
    assert clean_track_title("Opus (DJ Mix)") == "Opus"
    assert clean_track_title("Song Title - Mixed Cut") == "Song Title"
    assert clean_track_title("Deadmau5 - Strobe (Club Edit) [Mixed Cut]") == "Deadmau5 - Strobe (Club Edit)"
    assert clean_track_title("Track Name (Live / Mixed)") == "Track Name"
    assert clean_track_title("Energy 52 - Cafe Del Mar - Mixed") == "Energy 52 - Cafe Del Mar"
    assert clean_track_title("Another Song (Mixed Tracks)") == "Another Song"


def test_clean_track_title_preservation():
    from models import clean_track_title

    # Genuine song titles containing the word "mixed" must NOT be stripped
    assert clean_track_title("Mixed Signals") == "Mixed Signals"
    assert clean_track_title("Mixed Emotions") == "Mixed Emotions"
    assert clean_track_title("Mixed Feelings - Radio Edit") == "Mixed Feelings"
    assert clean_track_title("Mixed Up") == "Mixed Up"

    # Legitimate remixes and versions must be preserved
    assert clean_track_title("Return to Oz (ARTBAT Remix) - Mixed") == "Return to Oz (ARTBAT Remix)"
    assert clean_track_title("Cola (Club Mix)") == "Cola (Club Mix)"
    assert clean_track_title("Cola (Extended Mix)") == "Cola (Extended Mix)"
    assert clean_track_title("Opus (Four Tet Remix)") == "Opus (Four Tet Remix)"
    assert clean_track_title("Song (VIP Mix)") == "Song (VIP Mix)"
    assert clean_track_title("Song (Dub Mix)") == "Song (Dub Mix)"


def test_clean_track_title_remasters_edits_feats():
    from models import clean_track_title

    assert clean_track_title("Losing It - Radio Edit") == "Losing It"
    assert clean_track_title("One More Time - Original Mix") == "One More Time"
    assert clean_track_title("Song (Radio Edit)") == "Song"
    assert clean_track_title("Piece (Album Version)") == "Piece"
    assert clean_track_title("Pink Floyd - Time - 2011 Remastered Version") == "Pink Floyd - Time"
    assert clean_track_title("Queen - Bohemian Rhapsody - Remastered 2011") == "Queen - Bohemian Rhapsody"
    assert clean_track_title("Track (Remastered 2020)") == "Track"
    assert clean_track_title("Special (30th Anniversary Edition)") == "Special"
    assert clean_track_title("Titanium (feat. Sia)") == "Titanium"
    assert clean_track_title("Titanium [feat. Sia]") == "Titanium"
    assert clean_track_title("Titanium - feat. Sia") == "Titanium"
    assert clean_track_title("Song (with Someone)") == "Song"
    assert clean_track_title("Bonus Song - Bonus Track") == "Bonus Song"
    assert clean_track_title("Song (Explicit)") == "Song"


def test_spotify_track_mixed_properties():
    target = SpotifyTrack(
        id="t1",
        title="Glue - Mixed",
        artist="Bicep",
        duration_ms=270000,
        duration_str="04:30"
    )
    assert target.clean_title == "Glue"
    assert target.primary_artist == "Bicep"
    assert target.clean_search_query == "Bicep - Glue"
    assert "Bicep - Glue" in target.search_queries
    assert "Glue" in target.search_queries


def test_spotify_track_multi_artist_queries():
    target = SpotifyTrack(
        id="t2",
        title="Cola - Mixed",
        artist="CamelPhat, Elderbrook",
        duration_ms=210000,
        duration_str="03:30"
    )
    assert target.clean_title == "Cola"
    assert target.primary_artist == "CamelPhat"
    assert target.clean_search_query == "CamelPhat - Cola"
    queries = target.search_queries
    assert queries[0] == "CamelPhat - Cola"
    assert "CamelPhat, Elderbrook - Cola" in queries
    assert "Cola" in queries


def test_fuzzy_score_mixed_song_high_match(crawler):
    target = SpotifyTrack(
        id="t_mixed",
        title="Glue - Mixed",
        artist="Bicep",
        duration_ms=270000,
        duration_str="04:30"
    )
    # On Muzpa, the track is named 'Glue' without ' - Mixed'
    score_clean = crawler.calculate_fuzzy_score(target, "Glue", "Bicep", "04:30")
    assert score_clean >= 95.0

    # Or named 'Glue (Original Mix)'
    score_orig = crawler.calculate_fuzzy_score(target, "Glue (Original Mix)", "Bicep", "04:30")
    assert score_orig >= 95.0


