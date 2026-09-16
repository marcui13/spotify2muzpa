"""
DJ Set Tracklist Identification Service.
Extracts and timestamps full tracklists from YouTube / SoundCloud DJ sets or local audio,
using a hybrid approach:
  1. Fast text heuristics (YouTube video chapters, description timestamps, pinned comments).
  2. Acoustic fingerprinting (yt-dlp audio extraction, ffmpeg slicing, Shazam recognition, deduplication).
  3. Spotify enrichment (BPM, Camelot Key, album cover, Spotify URL).
  4. Conversion to Spotify2Muzpa PlaylistJob for automated downloading.
"""

import os
import re
import time
import uuid
import shutil
import asyncio
import logging
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Callable
import httpx
from rapidfuzz import fuzz

try:
    from shazamio_core import Recognizer
except ImportError:
    Recognizer = None

from models import DJSetTrackItem, DJSetJob, SpotifyTrack, TrackState, PlaylistJob
from spotify_service import SpotifyService

logger = logging.getLogger("dj_set_service")


# Common words that indicate a non-track chapter or description line
IGNORE_PATTERNS = [
    r"^intro$",
    r"^outro$",
    r"^welcome",
    r"^subscribe",
    r"^like\s*(&|\+)?\s*subscribe",
    r"^thanks\s+for\s+watching",
    r"^tracklist",
    r"^setlist",
    r"^full\s+tracklist",
    r"^interview",
    r"^q&a",
    r"^commercial",
    r"^ad$",
]


class ShazamRecognitionClient:
    """Direct, lightweight Shazam acoustic recognition client using shazamio_core and httpx."""

    def __init__(self, language: str = "en-US", country: str = "US"):
        self.language = language
        self.country = country
        self.recognizer = Recognizer() if Recognizer else None

    async def recognize_slice(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Recognizes a sliced audio snippet via Shazam acoustic fingerprinting."""
        if not self.recognizer:
            logger.warning("shazamio_core is not installed, cannot perform acoustic recognition.")
            return None

        if not os.path.exists(file_path) or os.path.getsize(file_path) < 1000:
            return None

        try:
            sig = await self.recognizer.recognize_path(file_path)
            if not sig or not hasattr(sig, "signature") or not sig.signature:
                return None

            uuid1 = str(uuid.uuid4()).upper()
            uuid2 = str(uuid.uuid4()).upper()
            url = f"https://amp.shazam.com/discovery/v5/{self.language}/{self.country}/iphone/-/tag/{uuid1}/{uuid2}"

            payload = {
                "timezone": "UTC",
                "signature": {
                    "uri": sig.signature.uri,
                    "samplems": sig.signature.samples
                },
                "timestamp": int(sig.timestamp or time.time() * 1000),
                "context": {},
                "geolocation": {}
            }

            headers = {
                "User-Agent": "Shazam/3673 CFNetwork/1408.0.4 Darwin/22.5.0",
                "Content-Type": "application/json"
            }

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    track = data.get("track")
                    if track and track.get("title"):
                        return track
        except Exception as e:
            logger.debug(f"Shazam slice recognition failed for {file_path}: {e}")
        return None


class DJSetService:
    """Orchestrates metadata heuristic parsing, acoustic fingerprinting, and Spotify enrichment."""

    def __init__(self, spotify_service: Optional[SpotifyService] = None):
        self.spotify_service = spotify_service or SpotifyService()
        self.shazam_client = ShazamRecognitionClient()
        self.active_jobs: Dict[str, DJSetJob] = {}
        self._cancelled_jobs: set = set()

    @staticmethod
    def seconds_to_timestamp(seconds: int) -> str:
        """Converts integer seconds to HH:MM:SS or MM:SS."""
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    @staticmethod
    def timestamp_to_seconds(ts: str) -> int:
        """Converts HH:MM:SS or MM:SS to integer seconds."""
        parts = [int(p) for p in ts.strip().split(":") if p.isdigit()]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 1:
            return parts[0]
        return 0

    @classmethod
    def is_ignored_title(cls, text: str) -> bool:
        """Checks if a title line looks like intro/outro/ad rather than a music track."""
        clean = text.strip().lower()
        # Remove leading timestamp if present (e.g. "00:00 Intro")
        clean = re.sub(r"^[\[\(]?\d{1,2}:\d{2}(?::\d{2})?[\]\)]?\s*[-–—:]?\s*", "", clean).strip()
        return any(re.search(pat, clean, re.IGNORECASE) for pat in IGNORE_PATTERNS)

    @classmethod
    def parse_tracklist_text(cls, text: str) -> List[Tuple[int, str, str]]:
        """
        Parses text (e.g. video description or pinned comment) for timestamped tracklines.
        Returns a list of tuples: (seconds, artist, title).
        """
        results: List[Tuple[int, str, str]] = []
        if not text:
            return results

        lines = text.splitlines()

        # Regex Patterns:
        # Pattern 1: [01:23:45] Artist - Title  OR  12:34 Artist - Title  OR  01:23:45 - Artist - Title
        p1 = re.compile(
            r"(?:^|\s)[\[\(]?(?:(?P<h>\d{1,2}):)?(?P<m>\d{1,2}):(?P<s>\d{2})[\]\)]?\s*[-–—:]?\s*(?P<artist>[^–—\n\r-]+?)\s*[-–—:]\s*(?P<title>[^\n\r\[\]\(\)]+)"
        )

        # Pattern 2: Artist - Title (12:34)  OR  Artist - Title [01:23:45]
        p2 = re.compile(
            r"^(?P<artist>[^–—\n\r-]+?)\s*[-–—:]\s*(?P<title>[^\[\(\n\r]+?)\s*[\[\(](?:(?P<h>\d{1,2}):)?(?P<m>\d{1,2}):(?P<s>\d{2})[\]\)]"
        )

        # Pattern 3: 12:34 Track Title (without clear artist delimiter, e.g. Single Artist Set)
        p3 = re.compile(
            r"(?:^|\s)[\[\(]?(?:(?P<h>\d{1,2}):)?(?P<m>\d{1,2}):(?P<s>\d{2})[\]\)]?\s*[-–—:]?\s*(?P<title>[^\n\r]+)"
        )

        for line in lines:
            line_str = line.strip()
            if not line_str or len(line_str) < 5:
                continue

            # Check Pattern 1
            m1 = p1.search(line_str)
            if m1:
                h = int(m1.group("h") or 0)
                m = int(m1.group("m"))
                s = int(m1.group("s"))
                sec = h * 3600 + m * 60 + s
                artist = m1.group("artist").strip().strip('"\'')
                title = m1.group("title").strip().strip('"\'')
                if not cls.is_ignored_title(artist) and not cls.is_ignored_title(title):
                    results.append((sec, artist, title))
                    continue

            # Check Pattern 2
            m2 = p2.search(line_str)
            if m2:
                h = int(m2.group("h") or 0)
                m = int(m2.group("m"))
                s = int(m2.group("s"))
                sec = h * 3600 + m * 60 + s
                artist = m2.group("artist").strip().strip('"\'')
                title = m2.group("title").strip().strip('"\'')
                if not cls.is_ignored_title(artist) and not cls.is_ignored_title(title):
                    results.append((sec, artist, title))
                    continue

            # Check Pattern 3 (fallback)
            m3 = p3.search(line_str)
            if m3:
                h = int(m3.group("h") or 0)
                m = int(m3.group("m"))
                s = int(m3.group("s"))
                sec = h * 3600 + m * 60 + s
                raw_title = m3.group("title").strip().strip('"\'')
                if not cls.is_ignored_title(raw_title) and " - " in raw_title:
                    parts = raw_title.split(" - ", 1)
                    results.append((sec, parts[0].strip(), parts[1].strip()))
                elif not cls.is_ignored_title(raw_title) and len(raw_title) > 3:
                    results.append((sec, "Unknown Artist", raw_title))

        # Sort chronologically and deduplicate exact timestamp collisions
        results.sort(key=lambda x: x[0])
        unique_results: List[Tuple[int, str, str]] = []
        for sec, artist, title in results:
            if not unique_results or abs(unique_results[-1][0] - sec) > 5:
                unique_results.append((sec, artist, title))

        return unique_results

    @classmethod
    def parse_chapters(cls, chapters: List[Dict[str, Any]]) -> List[Tuple[int, str, str]]:
        """Parses YouTube chapters into (seconds, artist, title)."""
        results: List[Tuple[int, str, str]] = []
        for ch in chapters:
            start_sec = int(ch.get("start_time", 0))
            raw_title = ch.get("title", "").strip()
            if cls.is_ignored_title(raw_title):
                continue

            # Split on standard artist/title separators
            delims = [" - ", " – ", " — "]
            found = False
            for d in delims:
                if d in raw_title:
                    parts = raw_title.split(d, 1)
                    results.append((start_sec, parts[0].strip(), parts[1].strip()))
                    found = True
                    break
            if not found:
                results.append((start_sec, "Unknown Artist", raw_title))

        results.sort(key=lambda x: x[0])
        return results

    async def extract_info(self, url: str) -> Dict[str, Any]:
        """Extracts video metadata, description, chapters, and comments using yt-dlp."""
        import yt_dlp

        ydl_opts = {
            "skip_download": True,
            "extract_flat": False,
            "no_warnings": True,
            "quiet": True,
            "get_comments": True,
            "extractor_args": {
                "youtube": {"max_comments": ["20", "all", "10"]}
            }
        }

        loop = asyncio.get_running_loop()

        def _run_extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        try:
            info = await loop.run_in_executor(None, _run_extract)
            return info or {}
        except Exception as e:
            logger.error(f"yt-dlp extract_info failed for {url}: {e}")
            raise RuntimeError(f"Failed to extract info from URL: {e}")

    @classmethod
    def deduplicate_tracks(
        cls,
        raw_items: List[Tuple[int, str, str]],
        threshold: float = 80.0
    ) -> List[DJSetTrackItem]:
        """
        Deduplicates tracks detected at contiguous intervals.
        Merges adjacent identical tracks into a single item with start and end timestamps.
        """
        if not raw_items:
            return []

        # Sort chronologically
        raw_items = sorted(raw_items, key=lambda x: x[0])
        deduped: List[DJSetTrackItem] = []

        for idx, (sec, artist, title) in enumerate(raw_items):
            start_ts = cls.seconds_to_timestamp(sec)
            
            if not deduped:
                deduped.append(DJSetTrackItem(
                    id=f"track_{len(deduped)+1}",
                    timestamp=start_ts,
                    artist=artist,
                    title=title,
                    confidence="heuristic" if "Unknown" not in artist else "partial"
                ))
                continue

            last = deduped[-1]
            last_sec = cls.timestamp_to_seconds(last.timestamp)

            # Check if this item is the same song as the last item
            clean_last_title = re.sub(r"[\(\[][^\)\]]*(?:mix|edit|version|feat|ft)[^\)\]]*[\)\]]", "", last.title, flags=re.IGNORECASE).strip()
            clean_curr_title = re.sub(r"[\(\[][^\)\]]*(?:mix|edit|version|feat|ft)[^\)\]]*[\)\]]", "", title, flags=re.IGNORECASE).strip()

            artist_sim = fuzz.token_set_ratio(last.artist.lower(), artist.lower())
            title_sim = fuzz.token_set_ratio(clean_last_title.lower(), clean_curr_title.lower())
            combo_sim = fuzz.token_set_ratio(
                f"{last.artist} {clean_last_title}".lower(),
                f"{artist} {clean_curr_title}".lower()
            )

            is_match = (title_sim >= threshold and artist_sim >= 60.0) or (combo_sim >= threshold)

            # If it's a match and occurred within reasonable song duration (e.g. within 12 minutes)
            if is_match and (sec - last_sec) < 720:
                last.end_timestamp = start_ts
                # If the new item has a cleaner artist name, upgrade it
                if last.artist == "Unknown Artist" and artist != "Unknown Artist":
                    last.artist = artist
                if len(title) > len(last.title):
                    last.title = title
            else:
                # Close previous track end timestamp if not closed
                if not last.end_timestamp:
                    last.end_timestamp = start_ts

                deduped.append(DJSetTrackItem(
                    id=f"track_{len(deduped)+1}",
                    timestamp=start_ts,
                    artist=artist,
                    title=title,
                    confidence="acoustic" if "Unknown" not in artist else "partial"
                ))

        return deduped

    async def scan_acoustic_slices(
        self,
        audio_file_path: str,
        total_duration_sec: int,
        sample_interval: int = 90,
        snippet_duration: int = 12,
        on_progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        job_id: Optional[str] = None
    ) -> List[Tuple[int, str, str]]:
        """
        Slices audio file at regular intervals, recognizes snippets via Shazam,
        and returns list of detected (seconds, artist, title).
        """
        ffmpeg_bin = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
        if not os.path.exists(ffmpeg_bin):
            logger.warning("ffmpeg not found, skipping acoustic analysis.")
            return []

        detected: List[Tuple[int, str, str]] = []
        sample_points = list(range(15, max(total_duration_sec - snippet_duration, 16), sample_interval))
        total_points = len(sample_points)

        with tempfile.TemporaryDirectory(prefix="djset_slices_") as tmp_dir:
            for idx, start_sec in enumerate(sample_points):
                if job_id and job_id in self._cancelled_jobs:
                    logger.info(f"Job {job_id} cancelled during acoustic scan.")
                    break

                slice_path = os.path.join(tmp_dir, f"slice_{start_sec}.mp3")

                # Fast ffmpeg slice
                cmd = [
                    ffmpeg_bin,
                    "-y",
                    "-ss", str(start_sec),
                    "-t", str(snippet_duration),
                    "-i", audio_file_path,
                    "-ac", "1",
                    "-ar", "16000",
                    "-b:a", "64k",
                    "-loglevel", "error",
                    slice_path
                ]

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await proc.wait()

                # Recognize slice
                track = await self.shazam_client.recognize_slice(slice_path)
                if track:
                    title = track.get("title", "").strip()
                    artist = track.get("subtitle", "").strip()
                    if title and artist:
                        detected.append((start_sec, artist, title))
                        logger.info(f"[{self.seconds_to_timestamp(start_sec)}] Recognized: {artist} - {title}")

                # Progress update
                percent = int((idx + 1) / max(total_points, 1) * 100)
                if on_progress_callback:
                    on_progress_callback({
                        "current": idx + 1,
                        "total": total_points,
                        "percent": percent,
                        "eta": f"~{int((total_points - idx - 1) * 2.5)}s left",
                        "detected_count": len(detected)
                    })

                # Polite pause to avoid rate limiting
                await asyncio.sleep(0.4)

        return detected

    async def enrich_tracks_with_spotify(self, tracks: List[DJSetTrackItem]) -> None:
        """Enriches identified DJSetTrackItems with Spotify metadata, artwork, BPM, and Camelot Key."""
        if not tracks:
            return

        from audio_analyzer import enrich_track_audio_features

        for item in tracks:
            query = f"{item.artist} - {item.title}".strip()
            # Clean remix brackets that may disrupt exact queries
            clean_q = re.sub(r"\(Original Mix\)", "", query, flags=re.IGNORECASE).strip()

            try:
                # 1. Search Spotify API if client initialized
                if self.spotify_service._sp:
                    results = self.spotify_service._sp.search(q=clean_q, type="track", limit=1)
                    items = results.get("tracks", {}).get("items", [])
                    if items:
                        t = items[0]
                        item.spotify_id = t.get("id")
                        item.spotify_url = t.get("external_urls", {}).get("spotify")
                        images = t.get("album", {}).get("images", [])
                        item.image_url = images[0].get("url") if images else None
                        item.duration_ms = t.get("duration_ms", 0)
                        item.duration_str = self.spotify_service.format_duration(item.duration_ms)

                # 2. Enrich BPM & Key
                dummy_spotify_track = SpotifyTrack(
                    id=item.spotify_id or f"temp_{item.id}",
                    title=item.title,
                    artist=item.artist,
                    duration_ms=item.duration_ms,
                    duration_str=item.duration_str,
                    spotify_url=item.spotify_url or ""
                )
                enrich_track_audio_features(dummy_spotify_track, allow_network=True)
                item.bpm = dummy_spotify_track.bpm
                item.musical_key = dummy_spotify_track.musical_key
                item.camelot_key = dummy_spotify_track.camelot_key
            except Exception as e:
                logger.debug(f"Spotify enrichment notice for '{query}': {e}")

    async def analyze_dj_set(
        self,
        url: str,
        sample_interval: int = 90,
        snippet_duration: int = 12,
        force_acoustic: bool = False,
        on_progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> DJSetJob:
        """
        Main entrypoint: analyzes DJ set from URL, parses heuristics or runs acoustic scan,
        enriches with Spotify, and returns a completed DJSetJob.
        """
        job_id = f"djset_{uuid.uuid4().hex[:10]}"
        job = DJSetJob(
            job_id=job_id,
            source_url=url,
            status="extracting_info"
        )
        self.active_jobs[job_id] = job

        def _update_progress(info_dict: Dict[str, Any]):
            job.progress = info_dict
            if on_progress_callback:
                on_progress_callback(info_dict)

        try:
            _update_progress({"status_text": "Extracting set metadata & chapters...", "percent": 5})
            info = await self.extract_info(url)

            job.title = info.get("title", "DJ Set")
            job.uploader = info.get("uploader") or info.get("channel", "Unknown Artist")
            job.duration_seconds = int(info.get("duration", 0))
            job.duration_str = self.seconds_to_timestamp(job.duration_seconds)
            job.thumbnail = info.get("thumbnail")

            raw_tracks: List[Tuple[int, str, str]] = []

            # 1. Try Chapters heuristic if not forcing acoustic
            if not force_acoustic and info.get("chapters"):
                chapters = info.get("chapters", [])
                logger.info(f"Found {len(chapters)} YouTube chapters in '{job.title}'.")
                raw_tracks = self.parse_chapters(chapters)

            # 2. Try Description heuristic if not enough tracks found yet
            if not force_acoustic and len(raw_tracks) < 3 and info.get("description"):
                desc_tracks = self.parse_tracklist_text(info.get("description", ""))
                if len(desc_tracks) >= 3:
                    logger.info(f"Found {len(desc_tracks)} tracks in video description.")
                    raw_tracks = desc_tracks

            # 3. Try Comments heuristic if still not enough tracks
            if not force_acoustic and len(raw_tracks) < 3 and info.get("comments"):
                for comment in info.get("comments", []):
                    c_text = comment.get("text", "")
                    comment_tracks = self.parse_tracklist_text(c_text)
                    if len(comment_tracks) >= 4:
                        logger.info(f"Found {len(comment_tracks)} tracks in pinned comment.")
                        raw_tracks = comment_tracks
                        break

            # 4. If heuristics succeeded, deduplicate & finalize
            if len(raw_tracks) >= 3 and not force_acoustic:
                logger.info(f"Successfully identified {len(raw_tracks)} tracks via metadata heuristics.")
                _update_progress({"status_text": "Enriching tracks with Spotify & DJ features...", "percent": 75})
                job.tracks = self.deduplicate_tracks(raw_tracks)
                await self.enrich_tracks_with_spotify(job.tracks)
                job.status = "complete"
                _update_progress({"status_text": "Analysis complete!", "percent": 100})
                return job

            # 5. Acoustic Scanning Fallback (when no tracklist exists in description/chapters)
            logger.info(f"Heuristics yielded only {len(raw_tracks)} tracks. Initiating acoustic fingerprinting...")
            job.status = "downloading_audio"
            _update_progress({"status_text": "Downloading audio stream for acoustic recognition...", "percent": 15})

            with tempfile.TemporaryDirectory(prefix="djset_audio_") as tmp_dir:
                audio_file = os.path.join(tmp_dir, "set_audio.mp3")

                import yt_dlp
                ydl_download_opts = {
                    "format": "ba[abr<=64]/ba/b",
                    "outtmpl": os.path.join(tmp_dir, "raw_audio.%(ext)s"),
                    "quiet": True,
                    "no_warnings": True,
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "64",
                    }]
                }

                loop = asyncio.get_running_loop()
                def _download_audio():
                    with yt_dlp.YoutubeDL(ydl_download_opts) as ydl:
                        ydl.download([url])

                await loop.run_in_executor(None, _download_audio)

                # Locate the converted mp3 file
                files = list(Path(tmp_dir).glob("*.mp3"))
                if not files:
                    # Check any audio file
                    files = list(Path(tmp_dir).glob("*.*"))
                
                if not files:
                    raise RuntimeError("Failed to download audio stream for analysis.")

                downloaded_file = str(files[0])
                job.status = "analyzing"
                _update_progress({"status_text": "Scanning acoustic slices with Shazam...", "percent": 25})

                acoustic_tracks = await self.scan_acoustic_slices(
                    audio_file_path=downloaded_file,
                    total_duration_sec=job.duration_seconds or 3600,
                    sample_interval=sample_interval,
                    snippet_duration=snippet_duration,
                    on_progress_callback=lambda p: _update_progress({
                        "status_text": f"Analyzing slice {p['current']}/{p['total']} ({p.get('detected_count', 0)} tracks found)...",
                        "percent": 25 + int(p["percent"] * 0.5)
                    }),
                    job_id=job_id
                )

                all_raw = raw_tracks + acoustic_tracks
                job.tracks = self.deduplicate_tracks(all_raw)

                _update_progress({"status_text": "Enriching tracks with Spotify & DJ features...", "percent": 85})
                await self.enrich_tracks_with_spotify(job.tracks)

                job.status = "complete"
                _update_progress({"status_text": "Analysis complete!", "percent": 100})
                return job

        except Exception as e:
            logger.error(f"DJ Set analysis failed for {url}: {e}", exc_info=True)
            job.status = "error"
            job.error_message = str(e)
            _update_progress({"status_text": f"Error: {e}", "percent": 0})
            return job

    def convert_to_playlist_job(
        self,
        job_id: str,
        playlist_name: Optional[str] = None,
        selected_indices: Optional[List[int]] = None,
        auto_mode: bool = False,
        similarity_threshold: float = 75.0
    ) -> PlaylistJob:
        """Converts completed DJSetJob into an active PlaylistJob for Muzpa downloader."""
        job = self.active_jobs.get(job_id)
        if not job:
            raise ValueError(f"DJ Set job '{job_id}' not found.")

        tracks_to_convert = job.tracks
        if selected_indices is not None:
            tracks_to_convert = [t for i, t in enumerate(job.tracks) if i in selected_indices]

        track_states: List[TrackState] = []
        for idx, item in enumerate(tracks_to_convert):
            spotify_track = SpotifyTrack(
                id=item.spotify_id or f"djset_{idx+1}_{job_id[:6]}",
                title=item.title,
                artist=item.artist,
                album=job.title,
                duration_ms=item.duration_ms,
                duration_str=item.duration_str,
                spotify_url=item.spotify_url or "",
                image_url=item.image_url or job.thumbnail,
                bpm=item.bpm,
                musical_key=item.musical_key,
                camelot_key=item.camelot_key
            )
            track_states.append(TrackState(spotify_track=spotify_track))

        p_name = playlist_name or f"DJ Set — {job.title}"
        return PlaylistJob(
            playlist_id=f"djset_{job_id}",
            playlist_name=p_name,
            playlist_url=job.source_url,
            playlist_image=job.thumbnail,
            tracks=track_states,
            auto_mode=auto_mode,
            similarity_threshold=similarity_threshold
        )

    def cancel_job(self, job_id: str) -> bool:
        """Cancels an ongoing DJ set analysis job."""
        if job_id in self.active_jobs:
            self._cancelled_jobs.add(job_id)
            self.active_jobs[job_id].status = "cancelled"
            return True
        return False
