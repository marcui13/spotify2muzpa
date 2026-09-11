"""
Audio Feature & Harmonic Key Analyzer Module.
Extracts BPM (tempo), Musical Key, and Camelot Wheel signatures for DJ/Producer workflows
(compatible with Rekordbox, Serato, Traktor, VirtualDJ, Engine DJ, and Mixed In Key).

Features:
- Multi-source extraction: ID3 Tags, Filename Regex, macOS Native Acoustic Waveform Analysis (afconvert PCM), Online Search (Deezer API + Preview Analysis).
- Persistent JSON caching for sub-millisecond repeated queries.
- Camelot Wheel (1A-12B) and Standard Musical Key mapping.
"""

import os
import re
import math
import json
import struct
import shutil
import logging
import tempfile
import subprocess
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, List, Union
import requests

from models import SpotifyTrack

logger = logging.getLogger("audio_analyzer")

# 12 Pitch classes (0 = C, 1 = C#/Db, ..., 11 = B)
PITCH_CLASSES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

# Krumhansl-Schmuckler Key Profiles (Major and Minor)
MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

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
    "C MINOR": "5A", "CM": "5A", "C MIN": "5A", "C-": "5A",
    "C# MINOR": "12A", "C#M": "12A", "C# MIN": "12A", "DB MINOR": "12A", "DBM": "12A", "DB MIN": "12A",
    "D MINOR": "7A", "DM": "7A", "D MIN": "7A", "D-": "7A",
    "D# MINOR": "2A", "D#M": "2A", "D# MIN": "2A", "EB MINOR": "2A", "EBM": "2A", "EB MIN": "2A",
    "E MINOR": "9A", "EM": "9A", "E MIN": "9A", "E-": "9A",
    "F MINOR": "4A", "FM": "4A", "F MIN": "4A", "F-": "4A",
    "F# MINOR": "11A", "F#M": "11A", "F# MIN": "11A", "GB MINOR": "11A", "GBM": "11A", "GB MIN": "11A",
    "G MINOR": "6A", "GM": "6A", "G MIN": "6A", "G-": "6A",
    "G# MINOR": "1A", "G#M": "1A", "G# MIN": "1A", "AB MINOR": "1A", "ABM": "1A", "AB MIN": "1A",
    "A MINOR": "8A", "AM": "8A", "A MIN": "8A", "A-": "8A",
    "A# MINOR": "3A", "A#M": "3A", "A# MIN": "3A", "BB MINOR": "3A", "BBM": "3A", "BB MIN": "3A",
    "B MINOR": "10A", "BM": "10A", "B MIN": "10A", "B-": "10A",
    # Major
    "C MAJOR": "8B", "C": "8B", "C MAJ": "8B", "C+": "8B",
    "C# MAJOR": "3B", "C#": "3B", "C# MAJ": "3B", "DB MAJOR": "3B", "DB": "3B", "DB MAJ": "3B",
    "D MAJOR": "10B", "D": "10B", "D MAJ": "10B", "D+": "10B",
    "D# MAJOR": "5B", "D#": "5B", "D# MAJ": "5B", "EB MAJOR": "5B", "EB": "5B", "EB MAJ": "5B",
    "E MAJOR": "12B", "E": "12B", "E MAJ": "12B", "E+": "12B",
    "F MAJOR": "7B", "F": "7B", "F MAJ": "7B", "F+": "7B",
    "F# MAJOR": "2B", "F#": "2B", "F# MAJ": "2B", "GB MAJOR": "2B", "GB": "2B", "GB MAJ": "2B",
    "G MAJOR": "9B", "G": "9B", "G MAJ": "9B", "G+": "9B",
    "G# MAJOR": "4B", "G#": "4B", "G# MAJ": "4B", "AB MAJOR": "4B", "AB": "4B", "AB MAJ": "4B",
    "A MAJOR": "11B", "A": "11B", "A MAJ": "11B", "A+": "11B",
    "A# MAJOR": "6B", "A#": "6B", "A# MAJ": "6B", "BB MAJOR": "6B", "BB": "6B", "BB MAJ": "6B",
    "B MAJOR": "1B", "B": "1B", "B MAJ": "1B", "B+": "1B",
}


def musical_key_to_camelot(key_str: Optional[str]) -> Optional[str]:
    """Maps standard musical key strings (e.g. 'A Minor', 'Gm', 'C# Major') to Camelot Wheel notation."""
    if not key_str:
        return None
    cleaned = key_str.strip().upper()
    return KEY_NAME_TO_CAMELOT.get(cleaned)


def extract_bpm_and_key_from_text(text: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Extracts BPM and Camelot/Musical key from a string (e.g. filename, track title, tags).
    Examples:
    - "124 - 8A - Track Name" -> (124, "A Minor", "8A")
    - "Track (128 BPM - 11B)" -> (128, "A Major", "11B")
    - "Artist - Song [126BPM] [F#m]" -> (126, "F# Minor", "11A")
    """
    if not text:
        return None, None, None

    bpm: Optional[int] = None
    camelot_key: Optional[str] = None
    musical_key: Optional[str] = None

    # 1. Look for Camelot Key pattern: 1A-12A, 1B-12B
    cam_match = re.search(r"(?:^|[\s\.\-_\[\(\/,])(1[0-2]|[1-9])([ABab])(?:$|[\s\.\-_\]\)\/,])", text)
    if cam_match:
        num = int(cam_match.group(1))
        letter = cam_match.group(2).upper()
        camelot_key = f"{num}{letter}"
        # Reverse map to musical key
        for k_name, c_val in KEY_NAME_TO_CAMELOT.items():
            if c_val == camelot_key and ("MINOR" in k_name or "MAJOR" in k_name):
                musical_key = k_name.title()
                break

    # 2. Look for explicit BPM e.g. "128 BPM", "124bpm", or "[128]"
    bpm_match = re.search(r"(?:^|[\s\.\-_\[\(\/,])(\d{2,3})\s*(?:bpm|BPM)(?:$|[\s\.\-_\]\)\/,])", text, re.IGNORECASE)
    if bpm_match:
        try:
            val = int(bpm_match.group(1))
            if 50 <= val <= 230:
                bpm = val
        except ValueError:
            pass

    # 3. If BPM not found with explicit label, look for standalone 2-3 digit numbers in common tempo range
    if not bpm:
        for num_str in re.findall(r"(?:^|[\s\.\-_\[\(\/,])(6[0-9]|[7-9][0-9]|1[0-9]{2}|2[0-1][0-9])(?:$|[\s\.\-_\]\)\/,])", text):
            try:
                val = int(num_str)
                # Ignore common track numbers like 01, 02, etc. unless > 50
                if 60 <= val <= 200:
                    bpm = val
                    break
            except ValueError:
                pass

    # 4. If Camelot not found, check musical key tokens e.g. "F#m", "Am", "Cmaj", "D# Minor"
    if not camelot_key:
        for word in re.split(r"[\s\.\-_\[\(\]\/,]+", text):
            w_up = word.upper()
            if w_up in KEY_NAME_TO_CAMELOT:
                camelot_key = KEY_NAME_TO_CAMELOT[w_up]
                musical_key = w_up.title()
                break

    return bpm, musical_key, camelot_key


# ==========================================
# Acoustic Audio Waveform Signal Analyzer
# ==========================================

def estimate_bpm_and_key_from_pcm(sr: int, samples: Union[List[int], Tuple[int, ...]]) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Computes BPM and Musical Key / Camelot Key from raw mono PCM samples (16-bit).
    Uses Energy Onset Flux Autocorrelation for BPM and Chromagram Pitch Class Profile correlation for Key.
    """
    if not samples or sr <= 0 or len(samples) < sr:
        return None, None, None

    # -------------------------------------------------------------
    # 1. BPM via Multi-band Energy Onset Envelope & Autocorrelation
    # -------------------------------------------------------------
    hop_size = int(sr * 0.02)  # 20ms hops -> 50 hops/sec
    envelope: List[float] = []
    prev_energy = 0.0

    for i in range(0, len(samples) - hop_size, hop_size):
        chunk = samples[i:i+hop_size]
        energy = sum(s * s for s in chunk) / len(chunk)
        flux = max(0.0, energy - prev_energy)
        envelope.append(flux)
        prev_energy = energy

    if not envelope:
        return None, None, None

    # Subtract local moving average
    win = 15
    smoothed: List[float] = []
    env_len = len(envelope)
    for i in range(env_len):
        start_idx = max(0, i - win)
        end_idx = min(env_len, i + win + 1)
        mean_val = sum(envelope[start_idx:end_idx]) / (end_idx - start_idx)
        smoothed.append(max(0.0, envelope[i] - mean_val))

    hops_per_sec = float(sr) / hop_size
    best_bpm: Optional[int] = None
    best_bpm_score = -1.0

    for bpm_cand in range(70, 175):
        lag = int(round(hops_per_sec * 60.0 / bpm_cand))
        if lag >= len(smoothed) or lag < 2:
            continue
        corr = sum(smoothed[j] * smoothed[j + lag] for j in range(len(smoothed) - lag))
        # Prioritize standard electronic music tempo (124-128 BPM) slightly if near equal
        tempo_prior = 1.0 - (abs(bpm_cand - 124.0) / 400.0)
        score = corr * tempo_prior
        if score > best_bpm_score:
            best_bpm_score = score
            best_bpm = bpm_cand

    # -------------------------------------------------------------
    # 2. Key Estimation via Chroma Pitch Class Profile (PCP)
    # -------------------------------------------------------------
    chroma = [0.0] * 12
    step = int(sr * 0.1)  # 100ms analysis window
    a4 = 440.0
    max_frames = min(len(samples) - step, sr * 25)

    for i in range(0, max_frames, step):
        chunk = samples[i:i+step]
        for semitone in range(12):
            for octave in [2, 3, 4, 5]:
                midi_note = (octave + 1) * 12 + semitone
                freq = a4 * (2.0 ** ((midi_note - 69) / 12.0))
                omega = 2.0 * math.pi * freq / sr
                re_val = sum(chunk[n] * math.cos(omega * n) for n in range(0, len(chunk), 2))
                im_val = sum(chunk[n] * math.sin(omega * n) for n in range(0, len(chunk), 2))
                chroma[semitone] += math.sqrt(re_val * re_val + im_val * im_val)

    chroma_sum = sum(chroma) or 1.0
    norm_chroma = [c / chroma_sum for c in chroma]

    best_key_name: Optional[str] = None
    best_camelot: Optional[str] = None
    best_corr_val = -999.0

    for root in range(12):
        # Major correlation
        rotated = norm_chroma[root:] + norm_chroma[:root]
        mean_c = sum(rotated) / 12.0
        mean_maj = sum(MAJOR_PROFILE) / 12.0
        cov_maj = sum((rotated[k] - mean_c) * (MAJOR_PROFILE[k] - mean_maj) for k in range(12))
        std_c = math.sqrt(sum((rotated[k] - mean_c)**2 for k in range(12)) or 1e-6)
        std_maj = math.sqrt(sum((MAJOR_PROFILE[k] - mean_maj)**2 for k in range(12)))
        r_maj = cov_maj / (std_c * std_maj)

        if r_maj > best_corr_val:
            best_corr_val = r_maj
            best_key_name = f"{PITCH_CLASSES[root]} Major"
            best_camelot = CAMELOT_MAJOR[root]

        # Minor correlation
        mean_min = sum(MINOR_PROFILE) / 12.0
        cov_min = sum((rotated[k] - mean_c) * (MINOR_PROFILE[k] - mean_min) for k in range(12))
        std_min = math.sqrt(sum((MINOR_PROFILE[k] - mean_min)**2 for k in range(12)))
        r_min = cov_min / (std_c * std_min)

        if r_min > best_corr_val:
            best_corr_val = r_min
            best_key_name = f"{PITCH_CLASSES[root]} Minor"
            best_camelot = CAMELOT_MINOR[root]

    return best_bpm, best_key_name, best_camelot


def estimate_bpm_and_key_from_audio_file(file_path: Union[str, Path], duration_sec: int = 25) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Decodes audio file (MP3, WAV, FLAC, M4A, AIFF) and computes BPM and Harmonic Key.
    Uses macOS built-in /usr/bin/afconvert or Python wave module.
    """
    p = Path(file_path)
    if not p.exists() or p.stat().st_size == 0:
        return None, None, None

    # If it's standard PCM WAV already
    if p.suffix.lower() == ".wav":
        try:
            import wave
            with wave.open(str(p), "rb") as wf:
                if wf.getnchannels() in (1, 2) and wf.getsampwidth() == 2:
                    sr = wf.getframerate()
                    n_frames = min(wf.getnframes(), int(duration_sec * sr))
                    frames = wf.readframes(n_frames)
                    if wf.getnchannels() == 1:
                        samples = struct.unpack(f"<{len(frames)//2}h", frames)
                    else:
                        stereo = struct.unpack(f"<{len(frames)//2}h", frames)
                        samples = [stereo[i] for i in range(0, len(stereo), 2)]
                    return estimate_bpm_and_key_from_pcm(sr, samples)
        except Exception as e:
            logger.debug(f"Direct WAV reading notice: {e}")

    # Use macOS built-in afconvert
    if os.path.exists("/usr/bin/afconvert"):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            out_wav = tf.name
        try:
            cmd = [
                "/usr/bin/afconvert",
                "-f", "WAVE",
                "-d", "LEI16@11025",
                "-c", "1",
                str(p),
                out_wav
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12)
            if res.returncode == 0 and os.path.exists(out_wav):
                import wave
                with wave.open(out_wav, "rb") as wf:
                    sr = wf.getframerate()
                    n_frames = min(wf.getnframes(), int(duration_sec * sr))
                    frames = wf.readframes(n_frames)
                    samples = struct.unpack(f"<{len(frames)//2}h", frames)
                    return estimate_bpm_and_key_from_pcm(sr, samples)
        except Exception as err:
            logger.debug(f"afconvert inspection notice for '{p.name}': {err}")
        finally:
            if os.path.exists(out_wav):
                try:
                    os.remove(out_wav)
                except Exception:
                    pass

    return None, None, None


# ==========================================
# Online Track BPM & Key Lookup Engine
# ==========================================

def lookup_bpm_and_key_online(artist: str, title: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Looks up BPM and Harmonic Key from public music APIs (Deezer Search + Preview Audio Analysis).
    """
    clean_artist = re.sub(r"\(feat\..*?\)", "", artist, flags=re.IGNORECASE).strip()
    clean_title = re.sub(r"\(feat\..*?\)", "", title, flags=re.IGNORECASE).strip()
    query = f"{clean_artist} {clean_title}".strip()
    if not query:
        return None, None, None

    try:
        url = f"https://api.deezer.com/search?q={requests.utils.quote(query)}"
        resp = requests.get(url, timeout=6)
        if resp.status_code != 200:
            return None, None, None

        data = resp.json()
        items = data.get("data", [])
        if not items:
            return None, None, None

        best_item = items[0]
        track_id = best_item.get("id")
        preview_url = best_item.get("preview")
        bpm: Optional[int] = None
        mus_key: Optional[str] = None
        camelot: Optional[str] = None

        # Fetch track detail for BPM
        if track_id:
            try:
                r_det = requests.get(f"https://api.deezer.com/track/{track_id}", timeout=6)
                if r_det.status_code == 200:
                    d = r_det.json()
                    raw_bpm = d.get("bpm")
                    if raw_bpm and float(raw_bpm) > 30:
                        bpm = int(round(float(raw_bpm)))
            except Exception:
                pass

        # If we have a preview MP3 URL and need Camelot key: analyze preview audio
        if preview_url and not camelot:
            try:
                r_prev = requests.get(preview_url, timeout=8)
                if r_prev.status_code == 200 and len(r_prev.content) > 1000:
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
                        tf.write(r_prev.content)
                        prev_path = tf.name
                    try:
                        p_bpm, p_mus, p_cam = estimate_bpm_and_key_from_audio_file(prev_path, duration_sec=25)
                        if not bpm and p_bpm:
                            bpm = p_bpm
                        if p_cam:
                            camelot = p_cam
                            mus_key = p_mus
                    finally:
                        if os.path.exists(prev_path):
                            try:
                                os.remove(prev_path)
                            except Exception:
                                pass
            except Exception as e:
                logger.debug(f"Preview acoustic analysis notice: {e}")

        return bpm, mus_key, camelot
    except Exception as e:
        logger.debug(f"Online track feature lookup notice for '{query}': {e}")
        return None, None, None


# ==========================================
# Persistent Disk Cache for BPM & Key
# ==========================================

class AudioFeaturesCache:
    _instance = None
    CACHE_FILE = Path.home() / ".cache" / "spotify2muzpa" / "audio_features_cache.json"

    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self):
        try:
            if self.CACHE_FILE.exists():
                with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
        except Exception as e:
            logger.debug(f"Notice loading audio features cache: {e}")
            self._data = {}

    def _save(self):
        try:
            self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            logger.debug(f"Notice saving audio features cache: {e}")

    def _make_key(self, artist: str, title: str) -> str:
        clean = f"{artist.lower().strip()}|||{title.lower().strip()}"
        return re.sub(r"[^\w\|]+", "", clean)

    def get(self, artist: str, title: str) -> Optional[Dict[str, Any]]:
        k = self._make_key(artist, title)
        return self._data.get(k)

    def set(self, artist: str, title: str, bpm: Optional[int], musical_key: Optional[str], camelot_key: Optional[str]):
        if not bpm and not camelot_key:
            return
        k = self._make_key(artist, title)
        self._data[k] = {
            "bpm": bpm,
            "musical_key": musical_key,
            "camelot_key": camelot_key
        }
        self._save()


# ==========================================
# Unified Track Enrichment Orchestrator
# ==========================================

def enrich_track_audio_features(track: SpotifyTrack, local_path: Optional[Path] = None, allow_network: bool = True) -> bool:
    """
    Enriches a SpotifyTrack object with BPM, musical key, and Camelot key notation.
    Orchestrates: Cache -> Filename/Text -> Audio Waveform Analysis -> Online Web APIs.
    Returns True if features were found/updated.
    """
    # 1. Already complete?
    if track.bpm and track.camelot_key:
        return True

    cache = AudioFeaturesCache.get_instance()

    # 2. Check persistent cache
    cached = cache.get(track.artist, track.title)
    if cached:
        if not track.bpm and cached.get("bpm"):
            track.bpm = cached["bpm"]
        if not track.camelot_key and cached.get("camelot_key"):
            track.camelot_key = cached["camelot_key"]
            track.musical_key = cached.get("musical_key")
        if track.bpm and track.camelot_key:
            return True

    # 3. Check filename / title text regex
    check_text = f"{track.title} {track.album or ''}"
    if local_path:
        check_text = f"{local_path.name} {check_text}"

    t_bpm, t_mus, t_cam = extract_bpm_and_key_from_text(check_text)
    if not track.bpm and t_bpm:
        track.bpm = t_bpm
    if not track.camelot_key and t_cam:
        track.camelot_key = t_cam
        track.musical_key = t_mus

    if track.bpm and track.camelot_key:
        cache.set(track.artist, track.title, track.bpm, track.musical_key, track.camelot_key)
        return True

    # 4. If local file exists, analyze audio waveform
    if local_path and Path(local_path).exists():
        try:
            f_bpm, f_mus, f_cam = estimate_bpm_and_key_from_audio_file(local_path)
            if not track.bpm and f_bpm:
                track.bpm = f_bpm
            if not track.camelot_key and f_cam:
                track.camelot_key = f_cam
                track.musical_key = f_mus
        except Exception as e:
            logger.debug(f"Acoustic analysis error for '{local_path.name}': {e}")

    if track.bpm and track.camelot_key:
        cache.set(track.artist, track.title, track.bpm, track.musical_key, track.camelot_key)
        return True

    # 5. Online lookup fallback (Deezer API + Preview Audio Analysis)
    if allow_network and (not track.bpm or not track.camelot_key):
        o_bpm, o_mus, o_cam = lookup_bpm_and_key_online(track.artist, track.title)
        if not track.bpm and o_bpm:
            track.bpm = o_bpm
        if not track.camelot_key and o_cam:
            track.camelot_key = o_cam
            track.musical_key = o_mus

    if track.bpm or track.camelot_key:
        cache.set(track.artist, track.title, track.bpm, track.musical_key, track.camelot_key)
        return True

    return False

