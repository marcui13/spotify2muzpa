"""
Downloader Module & Non-blocking Asynchronous Queue Manager.
Handles robust file downloading via Playwright context, ID3 metadata tagging,
safe filename sanitization, saving to ~/Downloads/<Playlist Name>, and concurrent background queues.
"""

import os
import re
import json
import asyncio
import logging
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable, Awaitable
from datetime import datetime
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3, HeaderNotFoundError

from config import settings
from models import SpotifyTrack, MuzpaCandidate, TrackState, PlaylistJob, TrackStatus
from muzpa_crawler import MuzpaCrawlerEngine

logger = logging.getLogger("downloader")


def sanitize_filename(filename: str) -> str:
    """Sanitizes strings for safe cross-platform file and folder naming."""
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)
    clean = re.sub(r'_+', '_', clean)
    clean = re.sub(r'\s+', ' ', clean)
    clean = clean.strip('. ')
    if len(clean) > 200:
        clean = clean[:200].rstrip('. ')
    return clean or "untitled"


def tag_mp3_metadata(file_path: Path, track: SpotifyTrack) -> bool:
    """Tags downloaded MP3 file with Spotify metadata and DJ attributes (BPM, Key) using Mutagen."""
    try:
        if not file_path.exists() or file_path.stat().st_size == 0:
            return False

        try:
            audio = EasyID3(str(file_path))
        except HeaderNotFoundError:
            audio = MP3(str(file_path))
            audio.add_tags()
            audio = EasyID3(str(file_path))

        audio["title"] = track.title
        audio["artist"] = track.artist
        audio["album"] = track.album

        if track.bpm:
            audio["bpm"] = str(track.bpm)

        audio.save()

        # Add advanced DJ frames (TBPM, TKEY, TXXX, COMM, APIC) using Mutagen ID3
        try:
            from mutagen.id3 import ID3, TBPM, TKEY, TXXX, COMM, APIC
            id3 = ID3(str(file_path))
            if track.bpm:
                id3.add(TBPM(encoding=3, text=str(track.bpm)))
                id3.add(TXXX(encoding=3, desc="BPM", text=str(track.bpm)))
            
            key_sig = track.camelot_key or track.musical_key
            if key_sig:
                id3.add(TKEY(encoding=3, text=key_sig))
                id3.add(TXXX(encoding=3, desc="initialkey", text=track.musical_key or key_sig))
                id3.add(TXXX(encoding=3, desc="CAMELOT_KEY", text=track.camelot_key or key_sig))

            comment_parts = []
            if track.bpm:
                comment_parts.append(f"BPM: {track.bpm}")
            if track.camelot_key:
                comment_parts.append(f"Key: {track.camelot_key}")
            if track.musical_key:
                comment_parts.append(f"({track.musical_key})")

            if comment_parts:
                id3.add(COMM(encoding=3, lang="eng", desc="DJ_INFO", text=" | ".join(comment_parts)))

            # Fetch and embed high-res cover art from Spotify image_url
            if track.image_url and str(track.image_url).startswith("http"):
                try:
                    import requests
                    img_resp = requests.get(track.image_url, timeout=10)
                    if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                        mime = img_resp.headers.get("Content-Type", "image/jpeg")
                        mime = "image/png" if "png" in mime else "image/jpeg"
                        
                        id3.delall("APIC")
                        id3.add(APIC(
                            encoding=3,
                            mime=mime,
                            type=3,  # 3 = Front Cover
                            desc="Cover",
                            data=img_resp.content
                        ))
                        logger.debug(f"Embedded cover art ({len(img_resp.content)} bytes) into '{file_path.name}'")
                except Exception as img_err:
                    logger.debug(f"Could not download cover art for '{track.title}': {img_err}")

            id3.save(v2_version=3)
        except Exception as ex:
            logger.debug(f"Advanced ID3 frame writing notice: {ex}")

        logger.debug(f"Tagged metadata for '{file_path.name}' (BPM: {track.bpm}, Key: {track.camelot_key})")
        return True
    except Exception as e:
        logger.warning(f"Could not write ID3 tags to '{file_path.name}': {e}")
        return False


class StateManager:
    """Persists playlist jobs and track states to JSON files in the state directory."""

    @staticmethod
    def get_state_path(playlist_id: str) -> Path:
        return settings.STATE_DIR / f"job_{playlist_id}.json"

    @classmethod
    def save_job(cls, job: PlaylistJob) -> None:
        try:
            path = cls.get_state_path(job.playlist_id)
            with open(path, "w", encoding="utf-8") as f:
                f.write(job.model_dump_json(indent=2))
        except Exception as e:
            logger.error(f"Error saving job state for {job.playlist_id}: {e}")

    @classmethod
    def load_job(cls, playlist_id: str) -> Optional[PlaylistJob]:
        try:
            path = cls.get_state_path(playlist_id)
            if not path.exists():
                return None
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return PlaylistJob.model_validate(data)
        except Exception as e:
            logger.warning(f"Could not load previous state for {playlist_id}: {e}")
            return None


class MuzpaDownloader:
    """Executes single track downloads using Playwright's authenticated context."""

    def __init__(self, crawler: MuzpaCrawlerEngine):
        self.crawler = crawler

    async def download_candidate(
        self,
        playlist_name: str,
        track: SpotifyTrack,
        candidate: MuzpaCandidate
    ) -> Path:
        """
        Downloads a candidate track directly into ~/Downloads/<Playlist Name>/Artist - Track.mp3
        using authenticated Playwright requests or page download capture.
        """
        safe_playlist_dir_name = sanitize_filename(playlist_name)
        target_dir = settings.DOWNLOAD_DIR / safe_playlist_dir_name
        target_dir.mkdir(parents=True, exist_ok=True)

        target_file_name = f"{sanitize_filename(track.artist)} - {sanitize_filename(track.title)}.mp3"
        target_path = target_dir / target_file_name

        if target_path.exists() and target_path.stat().st_size > 100_000:
            logger.info(f"File already exists: '{target_path.name}'")
            return target_path

        temp_target_path = target_dir / f"{target_file_name}.part"
        logger.info(f"Downloading '{track.artist} - {track.title}' to '{target_path}'...")

        download_captured = False

        # Strategy A: Direct href streaming via context.request
        if candidate.direct_href and (candidate.direct_href.startswith("http") or candidate.direct_href.startswith("/")):
            try:
                full_url = candidate.direct_href
                if full_url.startswith("/"):
                    full_url = f"{settings.MUZPA_BASE_URL}{full_url}"

                logger.info(f"Streaming background download from: {full_url}")
                response = await self.crawler.context.request.get(full_url, timeout=settings.DOWNLOAD_TIMEOUT_SECONDS * 1000)
                if response.ok:
                    body = await response.body()
                    if len(body) > 50_000:
                        with open(temp_target_path, "wb") as f:
                            f.write(body)
                        download_captured = True
            except Exception as e:
                logger.debug(f"Direct stream notice: {e}")

        # Strategy B: Use background page in the same context
        if not download_captured:
            bg_page = None
            try:
                bg_page = await self.crawler.context.new_page()
                cand_idx = 0
                if candidate.id.startswith("cand_"):
                    try:
                        cand_idx = int(candidate.id.split("_")[1])
                    except ValueError:
                        cand_idx = 0

                query = track.clean_search_query
                encoded_query = urllib.parse.quote(query)
                search_url = f"{settings.MUZPA_BASE_URL}/#/search?text={encoded_query}"
                await bg_page.goto(search_url, wait_until="domcontentloaded", timeout=settings.PAGE_LOAD_TIMEOUT_MS)
                await asyncio.sleep(1.2)

                buttons = await bg_page.query_selector_all(
                    "a.ms-release-dwnldbtn, button.download, a[href*='download'], .dwnldbtn"
                )

                target_btn = buttons[cand_idx] if buttons and cand_idx < len(buttons) else (buttons[0] if buttons else None)

                if target_btn:
                    async with bg_page.expect_download(timeout=settings.DOWNLOAD_TIMEOUT_SECONDS * 1000) as dl_info:
                        await target_btn.click()
                    dl = await dl_info.value
                    await dl.save_as(str(temp_target_path))
                    download_captured = True
            except Exception as ex:
                logger.error(f"Background download capture error: {ex}")
            finally:
                if bg_page:
                    try:
                        await bg_page.close()
                    except Exception:
                        pass

        if not download_captured or not temp_target_path.exists() or temp_target_path.stat().st_size < 10_000:
            if temp_target_path.exists():
                try:
                    temp_target_path.unlink()
                except Exception:
                    pass
            raise RuntimeError(f"Could not complete download for '{track.title}'")

        # Move to final .mp3
        if target_path.exists():
            target_path.unlink()
        temp_target_path.rename(target_path)

        # Apply ID3 tags
        tag_mp3_metadata(target_path, track)

        logger.info(f"Download finished: '{target_path.name}' ({round(target_path.stat().st_size / (1024*1024), 2)} MB)")
        return target_path


class DownloadQueueManager:
    """
    Manages non-blocking concurrent background downloads.
    When a track is confirmed, it is queued and executed in background workers,
    allowing the search/review loop to continue immediately without pausing.
    """

    def __init__(self, crawler: MuzpaCrawlerEngine, on_update_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None):
        self.downloader = MuzpaDownloader(crawler)
        self._queue: Optional[asyncio.Queue] = None
        self.on_update = on_update_callback
        self.workers: list[asyncio.Task] = []
        self._running = False
        self.active_downloads: Dict[str, Dict[str, Any]] = {}
        self.completed_downloads: List[Dict[str, Any]] = []

    @property
    def queue(self) -> asyncio.Queue:
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if self._queue is None:
            self._queue = asyncio.Queue()
        elif current_loop is not None and hasattr(self._queue, "_loop") and self._queue._loop != current_loop:
            old_items = []
            while not self._queue.empty():
                try:
                    old_items.append(self._queue.get_nowait())
                except (asyncio.QueueEmpty, RuntimeError):
                    break
            self._queue = asyncio.Queue()
            for item in old_items:
                self._queue.put_nowait(item)

        return self._queue

    def start(self, num_workers: int = settings.MAX_CONCURRENT_DOWNLOADS):
        """Starts background download workers."""
        if self._running:
            return
        # Touch queue on active running loop
        _ = self.queue
        self._running = True
        for i in range(num_workers):
            task = asyncio.create_task(self._worker_loop(i + 1))
            self.workers.append(task)
        logger.info(f"DownloadQueueManager started with {num_workers} background workers.")

    def stop(self):
        """Stops background download workers."""
        self._running = False
        for task in self.workers:
            task.cancel()
        self.workers.clear()
        logger.info("DownloadQueueManager stopped.")

    def enqueue_download(self, job: PlaylistJob, track_state: TrackState, candidate: MuzpaCandidate):
        """Enqueues a confirmed track for non-blocking download."""
        track_state.selected_candidate = candidate
        track_state.status = TrackStatus.DOWNLOADING
        StateManager.save_job(job)

        track = track_state.spotify_track
        self.active_downloads[track.id] = {
            "track_id": track.id,
            "title": track.title,
            "artist": track.artist,
            "candidate_title": candidate.title,
            "status": "Queued",
            "started_at": datetime.now().strftime("%H:%M:%S")
        }

        self.queue.put_nowait((job, track_state, candidate))
        logger.info(f"Enqueued '{track.title}' to download queue (Queue size: {self.queue.qsize()}).")

    def get_status_summary(self, job: Optional[PlaylistJob] = None) -> Dict[str, Any]:
        completed = list(self.completed_downloads)
        
        # If job is available, ensure all completed tracks from job are in the list
        if job:
            existing_ids = {c["track_id"] for c in completed}
            for t in job.tracks:
                if t.status == TrackStatus.COMPLETED and t.spotify_track.id not in existing_ids:
                    fn = Path(t.downloaded_file_path).name if t.downloaded_file_path else f"{t.spotify_track.artist} - {t.spotify_track.title}.mp3"
                    completed.append({
                        "track_id": t.spotify_track.id,
                        "title": t.spotify_track.title,
                        "artist": t.spotify_track.artist,
                        "filename": fn,
                        "file_path": t.downloaded_file_path or "",
                        "bpm": t.spotify_track.bpm,
                        "musical_key": t.spotify_track.musical_key,
                        "camelot_key": t.spotify_track.camelot_key,
                        "completed_at": "Saved"
                    })

        return {
            "queue_size": self.queue.qsize(),
            "active_count": len(self.active_downloads),
            "active_list": list(self.active_downloads.values()),
            "completed_list": completed
        }

    async def _worker_loop(self, worker_id: int):
        while self._running:
            try:
                job, track_state, candidate = await self.queue.get()
            except asyncio.CancelledError:
                break
            except Exception as ex:
                logger.error(f"[Worker #{worker_id}] Error in worker queue retrieve: {ex}")
                await asyncio.sleep(0.5)
                continue

            try:
                track = track_state.spotify_track

                if track.id in self.active_downloads:
                    self.active_downloads[track.id]["status"] = "Downloading..."

                logger.info(f"[Worker #{worker_id}] Starting download: '{track.artist} - {track.title}'")

                if self.on_update:
                    await self.on_update({
                        "type": "download_started",
                        "track_id": track.id,
                        "candidate": candidate.model_dump(),
                        "queue_summary": self.get_status_summary(job)
                    })

                success = False
                file_path = None
                for attempt in range(1, settings.MAX_RETRIES + 1):
                    try:
                        file_path = await self.downloader.download_candidate(
                            playlist_name=job.playlist_name,
                            track=track,
                            candidate=candidate
                        )
                        track_state.downloaded_file_path = str(file_path)
                        track_state.status = TrackStatus.COMPLETED
                        track_state.error_message = None
                        success = True
                        break
                    except Exception as e:
                        logger.warning(f"[Worker #{worker_id}] Attempt {attempt}/{settings.MAX_RETRIES} failed for '{track.title}': {e}")
                        if attempt < settings.MAX_RETRIES:
                            await asyncio.sleep(2.0 * attempt)
                        else:
                            track_state.status = TrackStatus.ERROR
                            track_state.error_message = str(e)

                # Remove from active
                self.active_downloads.pop(track.id, None)

                if success and file_path:
                    self.completed_downloads.append({
                        "track_id": track.id,
                        "title": track.title,
                        "artist": track.artist,
                        "filename": file_path.name,
                        "file_path": str(file_path),
                        "bpm": track.bpm,
                        "musical_key": track.musical_key,
                        "camelot_key": track.camelot_key,
                        "completed_at": datetime.now().strftime("%H:%M:%S")
                    })

                StateManager.save_job(job)

                if self.on_update:
                    if success:
                        await self.on_update({
                            "type": "download_success",
                            "track_id": track.id,
                            "file": track_state.downloaded_file_path,
                            "queue_summary": self.get_status_summary(job)
                        })
                    else:
                        await self.on_update({
                            "type": "download_failed",
                            "track_id": track.id,
                            "error": track_state.error_message,
                            "queue_summary": self.get_status_summary(job)
                        })

                self.queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as ex:
                logger.error(f"[Worker #{worker_id}] Error in download worker execution: {ex}", exc_info=True)
                await asyncio.sleep(0.5)
