"""
Unit tests for Audio & Harmonic Key Analyzer.
"""

from audio_analyzer import pitch_and_mode_to_key, PITCH_CLASSES, CAMELOT_MAJOR, CAMELOT_MINOR
from models import SpotifyTrack
from downloader import tag_mp3_metadata
from pathlib import Path


def test_pitch_and_mode_major_keys():
    # 0 = C Major -> 8B
    mus, cam = pitch_and_mode_to_key(0, 1)
    assert mus == "C Major"
    assert cam == "8B"

    # 9 = A Major -> 11B
    mus, cam = pitch_and_mode_to_key(9, 1)
    assert mus == "A Major"
    assert cam == "11B"


def test_pitch_and_mode_minor_keys():
    # 9 = A Minor -> 8A
    mus, cam = pitch_and_mode_to_key(9, 0)
    assert mus == "A Minor"
    assert cam == "8A"

    # 0 = C Minor -> 5A
    mus, cam = pitch_and_mode_to_key(0, 0)
    assert mus == "C Minor"
    assert cam == "5A"

    # 11 = B Minor -> 10A
    mus, cam = pitch_and_mode_to_key(11, 0)
    assert mus == "B Minor"
    assert cam == "10A"


def test_pitch_and_mode_invalid():
    mus, cam = pitch_and_mode_to_key(-1, 0)
    assert mus is None
    assert cam is None

    mus, cam = pitch_and_mode_to_key(None, None)
    assert mus is None
    assert cam is None


def test_spotify_track_with_dj_attributes():
    track = SpotifyTrack(
        id="test_dj_track",
        title="Midnight City",
        artist="M83",
        album="Hurry Up, We're Dreaming",
        bpm=105,
        musical_key="B Minor",
        camelot_key="10A",
        energy=0.75,
        danceability=0.55
    )
    assert track.bpm == 105
    assert track.camelot_key == "10A"
    assert track.musical_key == "B Minor"
