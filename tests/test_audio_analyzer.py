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


def test_extract_bpm_and_key_from_text():
    from audio_analyzer import extract_bpm_and_key_from_text

    # Test Camelot and BPM
    b, m, c = extract_bpm_and_key_from_text("01 - 8A - 128 - Fisher - Losing It.mp3")
    assert b == 128
    assert c == "8A"
    assert m == "A Minor"

    # Test explicit BPM in brackets and Camelot key
    b2, m2, c2 = extract_bpm_and_key_from_text("Track Name [124 BPM] (11B).flac")
    assert b2 == 124
    assert c2 == "11B"

    # Test musical key token
    b3, m3, c3 = extract_bpm_and_key_from_text("Artist - Song [126BPM] [F#m].mp3")
    assert b3 == 126
    assert c3 == "11A"


def test_estimate_bpm_and_key_from_pcm_synthesized():
    from audio_analyzer import estimate_bpm_and_key_from_pcm
    import math

    sr = 11025
    num_samples = sr * 8
    samples = [0] * num_samples
    beat_samples = int(sr * 60.0 / 128.0)
    for i in range(num_samples):
        # A Minor chord (A + C + E)
        tone = (math.sin(2 * math.pi * 440.0 * i / sr) + 0.7 * math.sin(2 * math.pi * 523.25 * i / sr) + 0.7 * math.sin(2 * math.pi * 659.25 * i / sr)) * 0.2
        pos = i % beat_samples
        if pos < sr * 0.05:
            env = math.exp(-pos / (sr * 0.015))
            tone += env * math.sin(2 * math.pi * 90.0 * i / sr) * 0.8
        samples[i] = int(max(-32767, min(32767, tone * 32767)))

    bpm, mus_key, camelot = estimate_bpm_and_key_from_pcm(sr, samples)
    assert bpm == 128
    assert camelot == "8A"
    assert "Minor" in mus_key


def test_enrich_track_audio_features():
    from audio_analyzer import enrich_track_audio_features

    tr = SpotifyTrack(
        id="t_enrich_test",
        title="Losing It (125 BPM - 8A)",
        artist="Fisher",
        album="Losing It"
    )
    assert tr.bpm is None
    assert tr.camelot_key is None

    updated = enrich_track_audio_features(tr, allow_network=False)
    assert updated is True
    assert tr.bpm == 125
    assert tr.camelot_key == "8A"

