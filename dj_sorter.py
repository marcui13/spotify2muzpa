"""
Intelligent DJ Harmonic Playlist Sorter Module.
Applies professional harmonic mixing techniques (Camelot Wheel, modal interchange,
energy boosts, BPM smoothing, and halftime/double-time transitions) to reorder tracklists
for seamless DJ live mixing and recording.
"""

import re
from typing import List, Optional, Tuple, Dict, Any
from models import TrackState, SpotifyTrack


def parse_camelot(key_str: Optional[str]) -> Optional[Tuple[int, str]]:
    """
    Parses a Camelot wheel key notation (e.g. '8A', '11B', '4a') into (number, letter).
    Returns None if unparseable.
    """
    if not key_str:
        return None
    match = re.match(r"^(\d{1,2})([ABab])$", str(key_str).strip())
    if not match:
        return None
    num = int(match.group(1))
    letter = match.group(2).upper()
    if 1 <= num <= 12 and letter in ("A", "B"):
        return (num, letter)
    return None


def calculate_bpm_cost(bpm1: Optional[float], bpm2: Optional[float], mode: str = "harmonic_flow") -> Tuple[float, str]:
    """
    Calculates tempo transition penalty and transition description.
    Supports halftime / double-time detection (e.g. 70 BPM <-> 140 BPM, 87 BPM <-> 174 BPM).
    """
    if not bpm1 or not bpm2 or bpm1 <= 0 or bpm2 <= 0:
        return (10.0, "Unknown BPM")

    delta_direct = abs(bpm2 - bpm1)
    delta_double = abs(bpm2 - (bpm1 * 2.0))
    delta_half = abs((bpm2 * 2.0) - bpm1)

    is_halftime = delta_half <= 5.0 and bpm1 > 110.0
    is_doubletime = delta_double <= 5.0 and bpm2 > 110.0

    if is_halftime:
        return (8.0, f"Halftime Switch ({round(bpm1)} ➔ {round(bpm2)} BPM)")
    if is_doubletime:
        return (8.0, f"Doubletime Switch ({round(bpm1)} ➔ {round(bpm2)} BPM)")

    delta = delta_direct
    sign = "+" if bpm2 >= bpm1 else "-"
    bpm_note = f"{sign}{round(delta, 1)} BPM ({round(bpm1)} ➔ {round(bpm2)})"

    if mode == "bpm_climb":
        # Heavily penalize BPM drops in climb mode
        if bpm2 < bpm1:
            cost = 40.0 + (delta * 15.0)
        else:
            cost = delta * 3.0
    else:
        if delta <= 1.5:
            cost = delta * 2.0
        elif delta <= 4.0:
            cost = 3.0 + (delta - 1.5) * 6.0
        elif delta <= 8.0:
            cost = 18.0 + (delta - 4.0) * 12.0
        else:
            cost = 66.0 + (delta - 8.0) * 20.0

    return (cost, bpm_note)


def calculate_camelot_cost(k1: Optional[Tuple[int, str]], k2: Optional[Tuple[int, str]], mode: str = "harmonic_flow") -> Tuple[float, str, str]:
    """
    Calculates harmonic transition penalty, quality label, and technique description.
    """
    if not k1 or not k2:
        return (25.0, "Neutral", "Key Unanalyzed")

    n1, l1 = k1
    n2, l2 = k2

    diff = (n2 - n1) % 12  # Clockwise distance
    rev_diff = (n1 - n2) % 12  # Counter-clockwise distance
    circ_dist = min(diff, rev_diff)
    same_mode = (l1 == l2)

    k1_str = f"{n1}{l1}"
    k2_str = f"{n2}{l2}"

    # 1. Exact Match (8A -> 8A)
    if n1 == n2 and l1 == l2:
        return (0.0, "Flawless", f"Same Key ({k1_str} ➔ {k2_str})")

    # 2. Relative Major / Minor (8A -> 8B, 11B -> 11A)
    if n1 == n2 and l1 != l2:
        rel_type = "Minor to Major" if l1 == "A" else "Major to Minor"
        return (8.0, "Smooth", f"Relative {rel_type} ({k1_str} ➔ {k2_str})")

    # 3. Adjacent Steps (Clockwise +1 / Counter-clockwise -1)
    if same_mode:
        if diff == 1:
            return (10.0, "Harmonic Lift", f"+1 Energy Lift ({k1_str} ➔ {k2_str})")
        elif rev_diff == 1:
            return (14.0, "Harmonic Ground", f"-1 Deepening ({k1_str} ➔ {k2_str})")

        # 4. Energy Boost Transitions (+2 Steps or +7 Steps / Semitone shift)
        if diff == 2:
            return (22.0, "Energy Surge", f"+2 Energy Boost ({k1_str} ➔ {k2_str})")
        elif diff == 7:
            return (26.0, "Key Lift", f"+7 Transposition Lift ({k1_str} ➔ {k2_str})")
        elif rev_diff == 2:
            return (32.0, "Energy Dip", f"-2 Step Drop ({k1_str} ➔ {k2_str})")

    # 5. Diagonal Transitions (8A -> 9B, 8B -> 7A)
    if not same_mode:
        if diff == 1 or rev_diff == 1:
            return (28.0, "Color Shift", f"Diagonal Shift ({k1_str} ➔ {k2_str})")

    # 6. Distant / Clashing Keys
    clash_penalty = 60.0 + (circ_dist * 15.0)
    return (clash_penalty, "Key Clash", f"Distant Shift ({k1_str} ➔ {k2_str})")


def compute_transition_score(t1: SpotifyTrack, t2: SpotifyTrack, mode: str = "harmonic_flow") -> Tuple[float, str, str]:
    """
    Computes total transition cost and qualitative explanation between two consecutive tracks.
    Returns: (total_cost, quality_rating, transition_badge_text)
    """
    k1 = parse_camelot(t1.camelot_key)
    k2 = parse_camelot(t2.camelot_key)

    key_cost, quality, key_desc = calculate_camelot_cost(k1, k2, mode)
    bpm_cost, bpm_desc = calculate_bpm_cost(t1.bpm, t2.bpm, mode)

    # Total weighted transition cost
    if mode == "bpm_climb":
        total_cost = (bpm_cost * 1.5) + key_cost
    elif mode == "camelot_ladder":
        total_cost = (key_cost * 1.5) + bpm_cost
    else:
        # Standard harmonic flow balance
        total_cost = (key_cost * 1.2) + (bpm_cost * 0.8)

    # Format human-friendly summary badge
    transition_badge = f"{key_desc} · {bpm_desc}"
    return (total_cost, quality, transition_badge)


def optimize_dj_sequence(
    tracks: List[TrackState],
    start_track_id: Optional[str] = None,
    mode: str = "harmonic_flow"
) -> List[TrackState]:
    """
    Finds the optimal harmonic DJ sequence for the given playlist using
    Greedy Nearest Neighbor path generation and 2-Opt local search refinement.
    """
    if len(tracks) <= 2:
        return list(tracks)

    track_list = list(tracks)

    # 1. Determine starting track
    start_idx = 0
    if start_track_id:
        found_idx = next((i for i, t in enumerate(track_list) if t.spotify_track.id == start_track_id), None)
        if found_idx is not None:
            start_idx = found_idx

    # Move starting track to front
    start_item = track_list.pop(start_idx)
    ordered: List[TrackState] = [start_item]
    unvisited: List[TrackState] = track_list

    # 2. Greedy Nearest Neighbor Chain
    while unvisited:
        current = ordered[-1].spotify_track
        best_idx = 0
        best_score = float("inf")

        for idx, candidate in enumerate(unvisited):
            cand_track = candidate.spotify_track
            score, _, _ = compute_transition_score(current, cand_track, mode)
            if score < best_score:
                best_score = score
                best_idx = idx

        ordered.append(unvisited.pop(best_idx))

    # 3. 2-Opt Local Search Optimization to eliminate cross-suboptimal transitions
    n = len(ordered)
    if n >= 4:
        improved = True
        iterations = 0
        max_iterations = 40

        while improved and iterations < max_iterations:
            improved = False
            iterations += 1

            for i in range(1, n - 2):
                for j in range(i + 1, n - 1):
                    t_i_prev = ordered[i - 1].spotify_track
                    t_i = ordered[i].spotify_track
                    t_j = ordered[j].spotify_track
                    t_j_next = ordered[j + 1].spotify_track

                    current_cost = (
                        compute_transition_score(t_i_prev, t_i, mode)[0] +
                        compute_transition_score(t_j, t_j_next, mode)[0]
                    )
                    new_cost = (
                        compute_transition_score(t_i_prev, t_j, mode)[0] +
                        compute_transition_score(t_i, t_j_next, mode)[0]
                    )

                    if new_cost < current_cost - 0.5:
                        # Reverse slice between i and j
                        ordered[i:j + 1] = reversed(ordered[i:j + 1])
                        improved = True
                        break
                if improved:
                    break

    # 4. Attach transition annotations to each consecutive track state
    for i in range(len(ordered)):
        if i == 0:
            ordered[i].transition_quality = "Opening Track"
            ordered[i].transition_note = "Set Opener"
        else:
            _, quality, note = compute_transition_score(
                ordered[i - 1].spotify_track,
                ordered[i].spotify_track,
                mode
            )
            ordered[i].transition_quality = quality
            ordered[i].transition_note = note

    return ordered


def analyze_set_flow(tracks: List[TrackState]) -> Dict[str, Any]:
    """
    Analyzes the overall harmonic and BPM flow of a playlist.
    """
    if not tracks:
        return {"total_tracks": 0, "compatibility_score": 100.0, "transitions": []}

    transitions = []
    flawless_count = 0
    smooth_count = 0
    clash_count = 0
    total_cost = 0.0

    for i in range(1, len(tracks)):
        t_prev = tracks[i - 1].spotify_track
        t_curr = tracks[i].spotify_track
        cost, quality, note = compute_transition_score(t_prev, t_curr)
        total_cost += cost

        if quality in ("Flawless", "Smooth", "Harmonic Lift", "Harmonic Ground"):
            flawless_count += 1
        elif quality in ("Energy Surge", "Key Lift", "Color Shift", "Neutral"):
            smooth_count += 1
        else:
            clash_count += 1

        transitions.append({
            "from_track_id": t_prev.id,
            "to_track_id": t_curr.id,
            "from_title": f"{t_prev.artist} - {t_prev.title}",
            "to_title": f"{t_curr.artist} - {t_curr.title}",
            "quality": quality,
            "note": note,
            "cost": round(cost, 1)
        })

    num_transitions = max(1, len(tracks) - 1)
    avg_cost = total_cost / num_transitions
    # Convert cost to 0-100% compatibility score (cost of 0 -> 100%, cost >= 100 -> 0%)
    compat_score = max(0.0, min(100.0, round(100.0 - (avg_cost * 0.8), 1)))

    return {
        "total_tracks": len(tracks),
        "total_transitions": num_transitions,
        "compatibility_score": compat_score,
        "harmonic_count": flawless_count,
        "smooth_count": smooth_count,
        "clash_count": clash_count,
        "transitions": transitions
    }
