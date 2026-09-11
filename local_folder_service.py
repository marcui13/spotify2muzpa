"""
Local Audio Folder Service for DJ Track Ingestion, Tag Extraction, Renaming, and M3U8 Export.
Supports MP3, FLAC, M4A, WAV, and AIFF audio files.
"""

import os
import re
import base64
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

from models import SpotifyTrack, TrackState, TrackStatus, PlaylistJob
from audio_analyzer import musical_key_to_camelot
from dj_sorter import parse_camelot

logger = logging.getLogger("local_folder_service")

AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".mp4", ".wav", ".aiff", ".aif", ".ogg"}


def parse_filename_metadata(filename: str) -> Tuple[str, str]:
    """
    Extracts artist and title from filename (e.g., '01 - Artist - Track Title.mp3' -> ('Artist', 'Track Title')).
    """
    stem = Path(filename).stem
    # Remove leading track numbers e.g. "01 - ", "01. ", "01 ", "1 - "
    cleaned = re.sub(r"^\d+[\s\.\-_]+", "", stem).strip()
    
    if " - " in cleaned:
        parts = cleaned.split(" - ", 1)
        artist = parts[0].strip()
        title = parts[1].strip()
        return (artist or "Unknown Artist", title or stem)
    
    return ("Local Track", cleaned or stem)


def extract_audio_file_metadata(file_path: Path) -> SpotifyTrack:
    """
    Extracts metadata, BPM, harmonic key, duration, and embedded cover art from an audio file.
    """
    ext = file_path.suffix.lower()
    artist, title = parse_filename_metadata(file_path.name)
    album = file_path.parent.name
    bpm: Optional[float] = None
    musical_key: Optional[str] = None
    camelot_key: Optional[str] = None
    duration_ms = 0
    image_data_uri: Optional[str] = None

    try:
        if ext == ".mp3":
            from mutagen.mp3 import MP3
            from mutagen.id3 import ID3, APIC
            try:
                audio = MP3(str(file_path))
                duration_ms = int(audio.info.length * 1000) if audio.info else 0
            except Exception:
                audio = None

            try:
                tags = ID3(str(file_path))
                # Title, Artist, Album
                if "TIT2" in tags:
                    title = str(tags["TIT2"].text[0]).strip() or title
                if "TPE1" in tags:
                    artist = str(tags["TPE1"].text[0]).strip() or artist
                if "TALB" in tags:
                    album = str(tags["TALB"].text[0]).strip() or album

                # BPM (TBPM or TXXX:BPM)
                if "TBPM" in tags:
                    try:
                        bpm = float(str(tags["TBPM"].text[0]).strip())
                    except ValueError:
                        pass
                if not bpm:
                    for txxx in tags.getall("TXXX"):
                        if txxx.desc.upper() in ("BPM", "TBPM"):
                            try:
                                bpm = float(str(txxx.text[0]).strip())
                                break
                            except ValueError:
                                pass

                # Musical / Camelot Key (TKEY or TXXX:initialkey / TXXX:CAMELOT_KEY)
                if "TKEY" in tags:
                    raw_k = str(tags["TKEY"].text[0]).strip()
                    if parse_camelot(raw_k):
                        camelot_key = raw_k.upper()
                    else:
                        musical_key = raw_k

                for txxx in tags.getall("TXXX"):
                    desc_upper = txxx.desc.upper()
                    if desc_upper in ("INITIALKEY", "KEY"):
                        k_val = str(txxx.text[0]).strip()
                        if parse_camelot(k_val):
                            camelot_key = k_val.upper()
                        else:
                            musical_key = k_val
                    elif desc_upper in ("CAMELOT_KEY", "CAMELOT", "INITIAL_CAMELOT_KEY"):
                        camelot_key = str(txxx.text[0]).strip().upper()

                # Extract APIC Cover Artwork
                apic_frames = tags.getall("APIC")
                if apic_frames:
                    apic = apic_frames[0]
                    mime = apic.mime or "image/jpeg"
                    b64 = base64.b64encode(apic.data).decode("utf-8")
                    image_data_uri = f"data:{mime};base64,{b64}"

            except Exception as tag_err:
                logger.debug(f"ID3 tag reading notice for {file_path.name}: {tag_err}")

        elif ext == ".flac":
            from mutagen.flac import FLAC
            try:
                flac = FLAC(str(file_path))
                duration_ms = int(flac.info.length * 1000) if flac.info else 0
                title = flac.get("title", [title])[0]
                artist = flac.get("artist", [artist])[0]
                album = flac.get("album", [album])[0]
                if "bpm" in flac:
                    try:
                        bpm = float(flac["bpm"][0])
                    except ValueError:
                        pass
                if "initialkey" in flac or "key" in flac:
                    k_val = flac.get("initialkey", flac.get("key", [""]))[0].strip()
                    if parse_camelot(k_val):
                        camelot_key = k_val.upper()
                    else:
                        musical_key = k_val

                if flac.pictures:
                    pic = flac.pictures[0]
                    mime = pic.mime or "image/jpeg"
                    b64 = base64.b64encode(pic.data).decode("utf-8")
                    image_data_uri = f"data:{mime};base64,{b64}"
            except Exception as flac_err:
                logger.debug(f"FLAC tag notice: {flac_err}")

        elif ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4
            try:
                mp4 = MP4(str(file_path))
                duration_ms = int(mp4.info.length * 1000) if mp4.info else 0
                if "\xa9nam" in mp4:
                    title = mp4["\xa9nam"][0]
                if "\xa9ART" in mp4:
                    artist = mp4["\xa9ART"][0]
                if "\xa9alb" in mp4:
                    album = mp4["\xa9alb"][0]
                if "tmpo" in mp4:
                    bpm = float(mp4["tmpo"][0])
                if "covr" in mp4 and mp4["covr"]:
                    covr = mp4["covr"][0]
                    b64 = base64.b64encode(covr).decode("utf-8")
                    image_data_uri = f"data:image/jpeg;base64,{b64}"
            except Exception as mp4_err:
                logger.debug(f"MP4 tag notice: {mp4_err}")

    except Exception as e:
        logger.warning(f"Error parsing metadata for '{file_path.name}': {e}")

    # Calculate duration string
    dur_secs = max(0, duration_ms // 1000)
    dur_str = f"{dur_secs // 60}:{dur_secs % 60:02d}"

    track_id = f"local_{abs(hash(str(file_path)))}"

    track = SpotifyTrack(
        id=track_id,
        title=title,
        artist=artist,
        album=album,
        duration_ms=duration_ms,
        duration_str=dur_str,
        image_url=image_data_uri or "https://via.placeholder.com/80x80/222222/888888?text=Audio",
        bpm=round(bpm, 1) if bpm else None,
        musical_key=musical_key,
        camelot_key=camelot_key,
        spotify_url=f"file://{file_path.resolve()}"
    )

    from audio_analyzer import enrich_track_audio_features
    try:
        enrich_track_audio_features(track, local_path=file_path)
    except Exception as e:
        logger.debug(f"Audio features enrichment notice for '{file_path.name}': {e}")

    return track


def scan_folder_tracks(folder_path: str) -> Tuple[str, List[TrackState]]:
    """
    Scans directory for supported audio tracks, parses metadata, and returns a TrackState list.
    """
    resolved = Path(folder_path).expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise FileNotFoundError(f"Directory not found: '{folder_path}'")

    audio_files = []
    for root, _, files in os.walk(resolved):
        for f in sorted(files):
            p = Path(root) / f
            if p.suffix.lower() in AUDIO_EXTENSIONS and not p.name.startswith("."):
                audio_files.append(p)

    if not audio_files:
        raise ValueError(f"No supported audio files found in: '{resolved}'")

    tracks: List[TrackState] = []
    for p in audio_files:
        sp_track = extract_audio_file_metadata(p)
        state = TrackState(
            spotify_track=sp_track,
            status=TrackStatus.COMPLETED,
            downloaded_file_path=str(p)
        )
        tracks.append(state)

    folder_name = resolved.name or "Local DJ Folder"
    return (folder_name, tracks)


def rename_files_with_order(job: PlaylistJob) -> List[Dict[str, str]]:
    """
    Physically renames audio files with sequential numbered prefixes (01 - , 02 - , etc.)
    matching the sorted DJ sequence.
    """
    renamed = []
    total = len(job.tracks)
    pad = 2 if total < 100 else 3

    for idx, track_state in enumerate(job.tracks, start=1):
        if not track_state.downloaded_file_path:
            continue

        orig_path = Path(track_state.downloaded_file_path)
        if not orig_path.exists():
            continue

        # Strip any existing leading track numbering e.g. "01 - " or "1. "
        base_name = re.sub(r"^\d+[\s\.\-_]+", "", orig_path.name).strip()
        new_name = f"{idx:0{pad}d} - {base_name}"
        new_path = orig_path.parent / new_name

        if orig_path != new_path:
            try:
                orig_path.rename(new_path)
                track_state.downloaded_file_path = str(new_path)
                renamed.append({"old": orig_path.name, "new": new_name})
            except Exception as e:
                logger.error(f"Failed to rename '{orig_path.name}' to '{new_name}': {e}")

    return renamed


def export_m3u8(job: PlaylistJob, output_dir: Optional[Path] = None) -> Path:
    """
    Exports an extended UTF-8 .m3u8 playlist file containing all tracks in the current sorted order.
    """
    if not job.tracks:
        raise ValueError("Playlist has no tracks to export.")

    # Determine destination directory
    first_track_path = job.tracks[0].downloaded_file_path if job.tracks else None
    if output_dir:
        dest_dir = output_dir
    elif first_track_path and Path(first_track_path).exists():
        dest_dir = Path(first_track_path).parent
    else:
        dest_dir = settings.DOWNLOAD_DIR / job.playlist_name

    dest_dir.mkdir(parents=True, exist_ok=True)
    m3u8_path = dest_dir / f"{job.playlist_name} [DJ Mixed Set].m3u8"

    lines = ["#EXTM3U", f"#PLAYLIST:{job.playlist_name}"]
    for t in job.tracks:
        tr = t.spotify_track
        dur_secs = max(0, tr.duration_ms // 1000)
        file_p = t.downloaded_file_path or f"{tr.artist} - {tr.title}.mp3"
        filename_rel = Path(file_p).name
        
        info_parts = [f"{tr.artist} - {tr.title}"]
        if tr.bpm:
            info_parts.append(f"[{tr.bpm} BPM]")
        if tr.camelot_key:
            info_parts.append(f"[{tr.camelot_key}]")
        
        lines.append(f"#EXTINF:{dur_secs},{' '.join(info_parts)}")
        lines.append(filename_rel)

    with open(m3u8_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    logger.info(f"Exported DJ Playlist M3U8 to: '{m3u8_path}'")
    return m3u8_path
