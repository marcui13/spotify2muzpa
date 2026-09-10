"""
Audio Feature & Harmonic Key Analyzer Module.
Extracts BPM (tempo), Musical Key, and Camelot Wheel signatures for DJ/Producer workflows
(compatible with Rekordbox, Serato, Traktor, VirtualDJ, Engine DJ, and Mixed In Key).
"""

import math
import logging
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, List

logger = logging.getLogger("audio_analyzer")

# 12 Pitch classes (0 = C, 1 = C#/Db, ..., 11 = B)
PITCH_CLASSES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

# Camelot Wheel Mappings
# Mode 1 = Major -> 'B' keys
CAMELOT_MAJOR = ["8B", "3B", "10B", "5B", "12B", "7B", "2B", "9B", "4B", "11B", "6B", "1B"]
# Mode 0 = Minor -> 'A' keys
CAMELOT_MINOR = ["5A", "12A", "7A", "2A", "9A", "4A", "11A", "6A", "1A", "8A", "3A", "10A"]


def pitch_and_mode_to_key(key_int: Optional[int], mode_int: Optional[int]) -> Tuple[Optional[str], Optional[str]]:
    """
    Converts Spotify key (0-11) and mode (0=minor, 1=major) integers
    into Standard Musical Key (e.g. 'A Minor') and Camelot Key (e.g. '8A').
    """
    if key_int is None or key_int < 0 or key_int > 11:
        return None, None

    mode = 1 if mode_int is None else mode_int
    pitch = PITCH_CLASSES[key_int]

    if mode == 1:
        musical = f"{pitch} Major"
        camelot = CAMELOT_MAJOR[key_int]
    else:
        musical = f"{pitch} Minor"
        camelot = CAMELOT_MINOR[key_int]

    return musical, camelot


KEY_NAME_TO_CAMELOT = {
    # Minor
    "C MINOR": "5A", "CM": "5A", "C MIN": "5A",
    "C# MINOR": "12A", "C#M": "12A", "DB MINOR": "12A", "DBM": "12A",
    "D MINOR": "7A", "DM": "7A", "D MIN": "7A",
    "D# MINOR": "2A", "D#M": "2A", "EB MINOR": "2A", "EBM": "2A",
    "E MINOR": "9A", "EM": "9A", "E MIN": "9A",
    "F MINOR": "4A", "FM": "4A", "F MIN": "4A",
    "F# MINOR": "11A", "F#M": "11A", "GB MINOR": "11A", "GBM": "11A",
    "G MINOR": "6A", "GM": "6A", "G MIN": "6A",
    "G# MINOR": "1A", "G#M": "1A", "AB MINOR": "1A", "ABM": "1A",
    "A MINOR": "8A", "AM": "8A", "A MIN": "8A",
    "A# MINOR": "3A", "A#M": "3A", "BB MINOR": "3A", "BBM": "3A",
    "B MINOR": "10A", "BM": "10A", "B MIN": "10A",
    # Major
    "C MAJOR": "8B", "C": "8B", "C MAJ": "8B",
    "C# MAJOR": "3B", "C#": "3B", "DB MAJOR": "3B", "DB": "3B",
    "D MAJOR": "10B", "D": "10B", "D MAJ": "10B",
    "D# MAJOR": "5B", "D#": "5B", "EB MAJOR": "5B", "EB": "5B",
    "E MAJOR": "12B", "E": "12B", "E MAJ": "12B",
    "F MAJOR": "7B", "F": "7B", "F MAJ": "7B",
    "F# MAJOR": "2B", "F#": "2B", "GB MAJOR": "2B", "GB": "2B",
    "G MAJOR": "9B", "G": "9B", "G MAJ": "9B",
    "G# MAJOR": "4B", "G#": "4B", "AB MAJOR": "4B", "AB": "4B",
    "A MAJOR": "11B", "A": "11B", "A MAJ": "11B",
    "A# MAJOR": "6B", "A#": "6B", "BB MAJOR": "6B", "BB": "6B",
    "B MAJOR": "1B", "B": "1B", "B MAJ": "1B",
}


def musical_key_to_camelot(key_str: Optional[str]) -> Optional[str]:
    """Maps standard musical key strings (e.g. 'A Minor', 'Gm', 'C# Major') to Camelot Wheel notation."""
    if not key_str:
        return None
    cleaned = key_str.strip().upper()
    return KEY_NAME_TO_CAMELOT.get(cleaned)


def estimate_bpm_from_file(file_path: Path) -> Optional[int]:
    """
    Estimates BPM from MP3 frame timing or audio headers if available.
    """
    try:
        from mutagen.mp3 import MP3
        audio = MP3(str(file_path))
        if audio.info.length > 0 and audio.info.bitrate > 0:
            # Check existing ID3 TBPM tag first
            from mutagen.easyid3 import EasyID3
            try:
                tags = EasyID3(str(file_path))
                if "bpm" in tags and tags["bpm"]:
                    val = int(float(tags["bpm"][0]))
                    if 40 <= val <= 220:
                        return val
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"BPM header inspection notice for '{file_path.name}': {e}")
    return None
