import pytest
from models import SpotifyTrack, TrackState, PlaylistJob
from dj_sorter import (
    parse_camelot,
    calculate_bpm_cost,
    calculate_camelot_cost,
    compute_transition_score,
    optimize_dj_sequence,
    analyze_set_flow
)


def test_parse_camelot():
    assert parse_camelot("8A") == (8, "A")
    assert parse_camelot("11b") == (11, "B")
    assert parse_camelot(" 1B ") == (1, "B")
    assert parse_camelot("12A") == (12, "A")
    assert parse_camelot("13A") is None
    assert parse_camelot("0A") is None
    assert parse_camelot("8C") is None
    assert parse_camelot(None) is None
    assert parse_camelot("") is None


def test_calculate_bpm_cost():
    # Direct small delta
    cost, desc = calculate_bpm_cost(124.0, 126.0)
    assert cost < 10.0
    assert "+2.0 BPM" in desc

    # Halftime transition (140 -> 70)
    cost_half, desc_half = calculate_bpm_cost(140.0, 70.0)
    assert cost_half <= 10.0
    assert "Halftime Switch" in desc_half

    # Doubletime transition (87 -> 174)
    cost_double, desc_double = calculate_bpm_cost(87.0, 174.0)
    assert cost_double <= 10.0
    assert "Doubletime Switch" in desc_double

    # Climb mode penalizing tempo drop
    cost_drop, _ = calculate_bpm_cost(128.0, 120.0, mode="bpm_climb")
    cost_rise, _ = calculate_bpm_cost(120.0, 128.0, mode="bpm_climb")
    assert cost_drop > cost_rise


def test_calculate_camelot_cost():
    # 1. Exact Match
    cost_exact, quality_exact, desc_exact = calculate_camelot_cost((8, "A"), (8, "A"))
    assert cost_exact == 0.0
    assert quality_exact == "Flawless"

    # 2. Relative Key (8A -> 8B)
    cost_rel, quality_rel, desc_rel = calculate_camelot_cost((8, "A"), (8, "B"))
    assert cost_rel < 15.0
    assert quality_rel == "Smooth"

    # 3. +1 Energy Lift (8A -> 9A)
    cost_lift, quality_lift, _ = calculate_camelot_cost((8, "A"), (9, "A"))
    assert cost_lift < 15.0
    assert quality_lift == "Harmonic Lift"

    # 4. -1 Grounding (8A -> 7A)
    cost_ground, quality_ground, _ = calculate_camelot_cost((8, "A"), (7, "A"))
    assert quality_ground == "Harmonic Ground"

    # 5. Energy Boost +2 (8A -> 10A)
    cost_boost, quality_boost, _ = calculate_camelot_cost((8, "A"), (10, "A"))
    assert quality_boost == "Energy Surge"

    # 6. +7 Semitone Transposition (8A -> 3A)
    cost_mod, quality_mod, _ = calculate_camelot_cost((8, "A"), (3, "A"))
    assert quality_mod == "Key Lift"

    # 7. Distant Clash (8A -> 2A)
    cost_clash, quality_clash, _ = calculate_camelot_cost((8, "A"), (2, "A"))
    assert cost_clash > 60.0
    assert quality_clash == "Key Clash"


def test_optimize_dj_sequence_basic():
    t1 = TrackState(spotify_track=SpotifyTrack(id="t1", title="Song 1", artist="Art", bpm=124.0, camelot_key="8A"))
    t2 = TrackState(spotify_track=SpotifyTrack(id="t2", title="Song 2", artist="Art", bpm=126.0, camelot_key="10A"))
    t3 = TrackState(spotify_track=SpotifyTrack(id="t3", title="Song 3", artist="Art", bpm=125.0, camelot_key="9A"))
    t4 = TrackState(spotify_track=SpotifyTrack(id="t4", title="Song 4", artist="Art", bpm=127.0, camelot_key="11A"))

    # Out of order: 8A -> 10A -> 9A -> 11A
    tracks = [t1, t2, t3, t4]
    sorted_tracks = optimize_dj_sequence(tracks, start_track_id="t1", mode="harmonic_flow")

    # Optimal harmonic ladder should be: 8A (t1) -> 9A (t3) -> 10A (t2) -> 11A (t4)
    order_ids = [t.spotify_track.id for t in sorted_tracks]
    assert order_ids == ["t1", "t3", "t2", "t4"]
    assert sorted_tracks[0].transition_quality == "Opening Track"
    assert sorted_tracks[1].transition_quality in ("Harmonic Lift", "Smooth", "Flawless")


def test_analyze_set_flow():
    t1 = TrackState(spotify_track=SpotifyTrack(id="t1", title="Song 1", artist="Art", bpm=124.0, camelot_key="8A"))
    t2 = TrackState(spotify_track=SpotifyTrack(id="t2", title="Song 2", artist="Art", bpm=125.0, camelot_key="8A"))
    t3 = TrackState(spotify_track=SpotifyTrack(id="t3", title="Song 3", artist="Art", bpm=125.0, camelot_key="8B"))

    analysis = analyze_set_flow([t1, t2, t3])
    assert analysis["total_tracks"] == 3
    assert analysis["total_transitions"] == 2
    assert analysis["compatibility_score"] >= 85.0
    assert len(analysis["transitions"]) == 2


def test_server_sort_endpoints(client):
    from server import orchestrator

    job = PlaylistJob(
        playlist_id="test_sort_pl",
        playlist_name="Test DJ Sort",
        playlist_url="https://open.spotify.com/playlist/test_sort_pl",
        tracks=[
            TrackState(spotify_track=SpotifyTrack(id="s1", title="Song 1", artist="Art 1", bpm=120.0, camelot_key="8A")),
            TrackState(spotify_track=SpotifyTrack(id="s2", title="Song 2", artist="Art 2", bpm=124.0, camelot_key="10A")),
            TrackState(spotify_track=SpotifyTrack(id="s3", title="Song 3", artist="Art 3", bpm=122.0, camelot_key="9A")),
        ]
    )
    orchestrator.current_job = job

    # 1. Test POST /api/playlist/sort
    res = client.post("/api/playlist/sort", json={"mode": "harmonic_flow", "start_track_id": "s1"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "sorted"
    assert data["mode"] == "harmonic_flow"
    assert data["analysis"]["compatibility_score"] > 80.0

    sorted_ids = [t["spotify_track"]["id"] for t in data["job"]["tracks"]]
    assert sorted_ids == ["s1", "s3", "s2"]

    # 2. Test GET /api/playlist/analysis
    analysis_res = client.get("/api/playlist/analysis")
    assert analysis_res.status_code == 200
    assert analysis_res.json()["total_tracks"] == 3

    # Cleanup
    if orchestrator._worker_task:
        orchestrator._worker_task.cancel()
    orchestrator.current_job = None
