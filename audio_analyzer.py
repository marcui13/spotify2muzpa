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
