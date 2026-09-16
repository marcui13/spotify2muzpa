import warnings
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")
warnings.filterwarnings("ignore", category=UserWarning)

import os
import re
import json
import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import settings
from models import (
    TrackStatus,
    SpotifyTrack,
    MuzpaCandidate,
    TrackState,
    PlaylistJob,
    DecisionRequest,
    ConfigUpdateRequest,
    DJSetTrackItem,
    DJSetJob,
    DJSetAnalyzeRequest,
    DJSetToPlaylistRequest,
)
from spotify_service import SpotifyService
from dj_set_service import DJSetService
from muzpa_crawler import MuzpaCrawlerEngine, detect_available_browsers
from downloader import MuzpaDownloader, StateManager, DownloadQueueManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("server")


# Broadcast log handler
class BroadcastLogHandler(logging.Handler):
    def __init__(self, manager: "ConnectionManager"):
        super().__init__()
        self.manager = manager
        self.log_history: List[Dict[str, str]] = []

    def emit(self, record):
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name
        }
        self.log_history.append(log_entry)
        if len(self.log_history) > 200:
            self.log_history.pop(0)

        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                asyncio.create_task(self.manager.broadcast({"type": "log", "data": log_entry}))
        except RuntimeError:
            pass


class ConnectionManager:
    """Manages active WebSocket connections for live UI streaming."""
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


manager = ConnectionManager()
log_handler = BroadcastLogHandler(manager)
logging.getLogger().addHandler(log_handler)


class DownloadOrchestrator:
    """Coordinates Playwright crawling, non-blocking download queues, and user confirmation."""
    def __init__(self):
        self.crawler = MuzpaCrawlerEngine(settings.BROWSER_NAME)
        self.download_queue = DownloadQueueManager(self.crawler, on_update_callback=self._on_download_update)
        self.current_job: Optional[PlaylistJob] = None
        self.is_paused: bool = False
        self.decision_events: Dict[str, asyncio.Event] = {}
        self.user_decisions: Dict[str, Dict[str, Any]] = {}
        self._worker_task: Optional[asyncio.Task] = None
        self._lock: Optional[asyncio.Lock] = None

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _on_download_update(self, event_data: Dict[str, Any]):
        """Broadcasts download progress/completion and saves state."""
        await manager.broadcast(event_data)
        if self.current_job:
            await manager.broadcast({"type": "state_updated", "data": self.current_job.model_dump()})

    async def initialize(self, browser_name: Optional[str] = None, open_dashboard_tab: bool = True):
        self.download_queue.start()
        await self.crawler.initialize(browser_name=browser_name, open_dashboard_tab=open_dashboard_tab)

    async def start_job(self, job: PlaylistJob):
        async with self.lock:
            self.current_job = job
            self.is_paused = False
            for ev in list(self.decision_events.values()):
                ev.set()
            self.decision_events.clear()
            self.user_decisions.clear()
            StateManager.save_job(job)

            if self._worker_task and not self._worker_task.done():
                self._worker_task.cancel()

            self._worker_task = asyncio.create_task(self._run_orchestrator_loop())
            await manager.broadcast({"type": "job_started", "data": job.model_dump()})

    async def pause(self):
        self.is_paused = True
        if self.current_job:
            self.current_job.is_running = False
            StateManager.save_job(self.current_job)
        await manager.broadcast({"type": "job_paused"})

    async def resume(self):
        self.is_paused = False
        if self.current_job:
            self.current_job.is_running = True
            StateManager.save_job(self.current_job)
            if not self._worker_task or self._worker_task.done():
                self._worker_task = asyncio.create_task(self._run_orchestrator_loop())
        await manager.broadcast({"type": "job_resumed"})

    def provide_decision(self, track_id: str, action: str, candidate_id: Optional[str] = None, custom_query: Optional[str] = None):
        act = (action or "skip").lower()
        self.user_decisions[track_id] = {
            "action": act,
            "candidate_id": candidate_id,
            "custom_query": custom_query
        }
        if track_id in self.decision_events:
            self.decision_events[track_id].set()

    async def _run_orchestrator_loop(self):
        """Main loop that iterates through tracks for search and confirmation."""
        if not self.current_job:
            return

        self.current_job.is_running = True
        logger.info(f"Starting playlist processing loop: '{self.current_job.playlist_name}'")

        try:
            await self.crawler.initialize()
            self.download_queue.start()

            while self.current_job.current_track_index < len(self.current_job.tracks):
                if self.is_paused:
                    logger.info("Processing loop paused by user.")
                    break

                idx = self.current_job.current_track_index
                track_state = self.current_job.tracks[idx]

                # Skip tracks that are already completed or downloaded
                if track_state.status in [TrackStatus.COMPLETED, TrackStatus.DOWNLOADING]:
                    self.current_job.current_track_index += 1
                    continue

                if track_state.status in [TrackStatus.SKIPPED]:
                    self.current_job.current_track_index += 1
                    continue

                await self._process_single_track(track_state)
                
                # Advance to next track
                self.current_job.current_track_index += 1
                StateManager.save_job(self.current_job)
                await manager.broadcast({
                    "type": "state_updated",
                    "data": self.current_job.model_dump(),
                    "queue_summary": self.download_queue.get_status_summary(self.current_job)
                })

                await asyncio.sleep(settings.RATE_LIMIT_DELAY_SECONDS)

            logger.info("Playlist review queue completed.")
        except asyncio.CancelledError:
            logger.info("Orchestrator worker loop cancelled.")
        except Exception as e:
            logger.error(f"Unexpected error in orchestrator loop: {e}", exc_info=True)
        finally:
            if self.current_job:
                self.current_job.is_running = False
                StateManager.save_job(self.current_job)
                await manager.broadcast({
                    "type": "job_finished",
                    "data": self.current_job.model_dump(),
                    "queue_summary": self.download_queue.get_status_summary(self.current_job)
                })

    async def _process_single_track(self, track_state: TrackState):
        """Searches and resolves a single track, enqueuing downloads asynchronously."""
        track = track_state.spotify_track
        track_id = track.id

        logger.info(f"Processing track [{self.current_job.current_track_index + 1}/{len(self.current_job.tracks)}]: {track.artist} - {track.title}")
        track_state.status = TrackStatus.SEARCHING
        # Broadcast immediately so UI spotlights this track and shows searching spinner
        await manager.broadcast({
            "type": "state_updated",
            "data": self.current_job.model_dump(),
            "queue_summary": self.download_queue.get_status_summary(self.current_job)
        })

        custom_query = None

        while True:
            # 1. Search Muzpa
            try:
                candidates = await self.crawler.search_track(track, custom_query=custom_query)
                track_state.candidates = candidates
            except Exception as e:
                logger.error(f"Error during search for '{track.title}': {e}")
                track_state.status = TrackStatus.ERROR
                track_state.error_message = f"Search failed: {e}"
                return

            if not candidates:
                logger.warning(f"No candidates found for '{track.title}'")
                track_state.status = TrackStatus.NOT_FOUND
                track_state.error_message = "No matching tracks found on Muzpa"
                if self.current_job.auto_mode:
                    return

            top_candidate = candidates[0] if candidates else None
            auto_threshold = self.current_job.similarity_threshold or settings.SIMILARITY_THRESHOLD

            # Check if auto download criteria met
            is_auto_eligible = (
                self.current_job.auto_mode
                and top_candidate is not None
                and top_candidate.score >= auto_threshold
            )

            if is_auto_eligible:
                logger.info(f"Auto-mode: Enqueuing top match '{top_candidate.title}' (Score {top_candidate.score}% >= {auto_threshold}%).")
                self.download_queue.enqueue_download(self.current_job, track_state, top_candidate)
                # Immediately advance to next track!
                return

            # Otherwise, wait for user confirmation
            track_state.status = TrackStatus.WAITING_CONFIRMATION
            StateManager.save_job(self.current_job)
            await manager.broadcast({"type": "waiting_decision", "track_id": track_id, "data": track_state.model_dump()})

            event = asyncio.Event()
            self.decision_events[track_id] = event

            # Wait until user submits decision
            await event.wait()
            self.decision_events.pop(track_id, None)

            decision = self.user_decisions.pop(track_id, {"action": "skip"})
            action = decision.get("action")

            if action == "skip":
                logger.info(f"User skipped track '{track.title}'")
                track_state.status = TrackStatus.SKIPPED
                return
            elif action == "custom_search":
                custom_query = decision.get("custom_query")
                logger.info(f"User requested custom re-search for '{track.title}': '{custom_query}'")
                track_state.status = TrackStatus.SEARCHING
                continue
            elif action == "confirm":
                cand_id = decision.get("candidate_id")
                chosen_candidate = next((c for c in track_state.candidates if c.id == cand_id), top_candidate)
                if chosen_candidate:
                    # Non-blocking enqueue!
                    self.download_queue.enqueue_download(self.current_job, track_state, chosen_candidate)
                else:
                    track_state.status = TrackStatus.ERROR
                    track_state.error_message = "No valid candidate chosen"
                # Immediately advance to next track without waiting for file download!
                return
            elif action == "retry":
                track_state.status = TrackStatus.SEARCHING
                continue


orchestrator = DownloadOrchestrator()
spotify_service = SpotifyService()
dj_set_service = DJSetService(spotify_service)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    logger.info("Initializing Spotify to Muzpa Backend Service...")
    
    async def auto_open_browser():
        await asyncio.sleep(1.0)
        if not settings.HEADLESS and settings.AUTO_LAUNCH_BROWSER:
            try:
                open_tab = settings.OPEN_DASHBOARD_TAB and not settings.IS_DESKTOP_APP
                logger.info(f"Initializing crawler browser (open_dashboard_tab={open_tab})...")
                await orchestrator.initialize(browser_name=settings.BROWSER_NAME, open_dashboard_tab=open_tab)
            except Exception as e:
                logger.warning(f"Browser auto-open background notice: {e}")

    asyncio.create_task(auto_open_browser())
    yield
    logger.info("Shutting down services and browser context...")
    orchestrator.download_queue.stop()
    await orchestrator.crawler.close()


app = FastAPI(
    title="Spotify to Muzpa Downloader Studio",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        if orchestrator.current_job:
            await websocket.send_json({"type": "initial_state", "data": orchestrator.current_job.model_dump()})
        await websocket.send_json({"type": "log_history", "data": log_handler.log_history})
        
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/api/browser/list")
async def get_browser_list():
    """Returns detected web browsers on the system."""
    browsers = detect_available_browsers()
    return {"current": settings.BROWSER_NAME, "browsers": browsers}


@app.get("/api/muzpa/credentials")
async def get_muzpa_credentials():
    """Returns whether Muzpa credentials are configured."""
    return {
        "configured": bool(settings.MUZPA_EMAIL and settings.MUZPA_PASSWORD),
        "email": settings.MUZPA_EMAIL or ""
    }


@app.post("/api/muzpa/credentials")
async def save_muzpa_credentials(payload: Dict[str, Any]):
    """Saves Muzpa username and password in settings and .env."""
    email = payload.get("email", "").strip()
    password = payload.get("password", "").strip()
    auto_submit = payload.get("auto_submit", False)

    if not email or not password:
        raise HTTPException(status_code=400, detail="Both email/username and password are required.")

    settings.MUZPA_EMAIL = email
    settings.MUZPA_PASSWORD = password

    # Update .env file
    env_file = settings.BASE_DIR / ".env"
    if env_file.exists():
        content = env_file.read_text(encoding="utf-8")
        if "MUZPA_EMAIL=" in content:
            content = re.sub(r'MUZPA_EMAIL=.*', f'MUZPA_EMAIL="{email}"', content)
        else:
            content += f'\nMUZPA_EMAIL="{email}"'

        if "MUZPA_PASSWORD=" in content:
            content = re.sub(r'MUZPA_PASSWORD=.*', f'MUZPA_PASSWORD="{password}"', content)
        else:
            content += f'\nMUZPA_PASSWORD="{password}"'
        env_file.write_text(content, encoding="utf-8")

    # Trigger immediate auto-fill on active page
    try:
        await orchestrator.crawler.autofill_login_form(email=email, password=password, submit=auto_submit)
    except Exception as e:
        logger.debug(f"Auto-fill on credential save notice: {e}")

    return {"status": "saved", "email": email}


@app.post("/api/muzpa/autofill")
async def trigger_muzpa_autofill(payload: Dict[str, Any] = None):
    """Triggers auto-fill on Muzpa tab and brings it to front."""
    payload = payload or {}
    submit = payload.get("submit", False)
    focus = payload.get("focus", True)

    success = await orchestrator.crawler.autofill_login_form(submit=submit)
    if focus:
        await orchestrator.crawler.bring_muzpa_to_front()

    return {"status": "success" if success else "form_not_found"}


@app.post("/api/playlist/load")
async def load_playlist(payload: Dict[str, Any]):
    """Loads tracks from Spotify URL, initializes or restores job (or forces fresh reload if force_fresh=True)."""
    url = payload.get("playlist_url")
    if not url:
        raise HTTPException(status_code=400, detail="Missing 'playlist_url' in request.")

    auto_mode = payload.get("auto_mode", settings.AUTO_MODE)
    threshold = payload.get("similarity_threshold", settings.SIMILARITY_THRESHOLD)
    force_fresh = payload.get("force_fresh", False)

    try:
        playlist_id = spotify_service.extract_playlist_id(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    existing_job = None if force_fresh else StateManager.load_job(playlist_id)
    if existing_job:
        logger.info(f"Loaded existing session for playlist: '{existing_job.playlist_name}'")
        job = existing_job
        job.auto_mode = auto_mode
        job.similarity_threshold = threshold
    else:
        logger.info(f"Fetching fresh playlist from Spotify API: {url} (force_fresh={force_fresh})...")
        try:
            name, img, tracks = spotify_service.fetch_playlist(url)
            track_states = [TrackState(spotify_track=t) for t in tracks]
            job = PlaylistJob(
                playlist_id=playlist_id,
                playlist_name=name,
                playlist_url=url,
                playlist_image=img,
                tracks=track_states,
                auto_mode=auto_mode,
                similarity_threshold=threshold
            )
        except Exception as e:
            logger.error(f"Failed to fetch Spotify playlist: {e}")
            raise HTTPException(status_code=500, detail=f"Spotify extraction failed: {e}")

    await orchestrator.start_job(job)
    return {"status": "success", "job": job.model_dump(), "reloaded_fresh": force_fresh}


@app.get("/api/state")
async def get_state():
    """Returns current active job state and download queue info."""
    if orchestrator.current_job:
        return {
            "active": True,
            "job": orchestrator.current_job.model_dump(),
            "stats": orchestrator.current_job.stats,
            "queue_summary": orchestrator.download_queue.get_status_summary(orchestrator.current_job)
        }
    return {"active": False, "job": None}


@app.post("/api/playlist/reset")
async def reset_playlist(payload: Dict[str, Any] = None):
    """Resets playlist tracks back to PENDING and restarts the review loop."""
    scope = (payload or {}).get("scope", "all")
    if not orchestrator.current_job:
        raise HTTPException(status_code=400, detail="No active playlist job to reset.")

    logger.info(f"Resetting playlist job (scope: '{scope}')...")

    if scope == "all":
        for t in orchestrator.current_job.tracks:
            t.status = TrackStatus.PENDING
            t.candidates = []
            t.selected_candidate = None
            t.error_message = None
            t.downloaded_file_path = None
        orchestrator.current_job.current_track_index = 0
    elif scope == "failed":
        for t in orchestrator.current_job.tracks:
            if t.status in [TrackStatus.ERROR, TrackStatus.NOT_FOUND, TrackStatus.SKIPPED]:
                t.status = TrackStatus.PENDING
                t.error_message = None
                t.candidates = []
    elif scope == "downloads":
        for t in orchestrator.current_job.tracks:
            if t.status in [TrackStatus.COMPLETED, TrackStatus.DOWNLOADING]:
                t.status = TrackStatus.PENDING
                t.downloaded_file_path = None

    StateManager.save_job(orchestrator.current_job)
    await manager.broadcast({"type": "state_updated", "data": orchestrator.current_job.model_dump()})

    # Restart orchestrator loop
    if orchestrator._worker_task and not orchestrator._worker_task.done():
        orchestrator._worker_task.cancel()
    orchestrator._worker_task = asyncio.create_task(orchestrator._run_orchestrator_loop())

    return {"status": "reset", "scope": scope}


@app.post("/api/playlist/sort")
async def sort_playlist_dj(payload: Dict[str, Any] = None):
    """Reorders active playlist tracks using Intelligent DJ Harmonic Sorting."""
    payload = payload or {}
    mode = payload.get("mode", "harmonic_flow")
    start_track_id = payload.get("start_track_id")

    if not orchestrator.current_job:
        raise HTTPException(status_code=400, detail="No active playlist job to sort.")

    from dj_sorter import optimize_dj_sequence, analyze_set_flow
    from audio_analyzer import enrich_track_audio_features

    # 1. Ensure all tracks have BPM and Camelot Key before sorting
    for t_state in orchestrator.current_job.tracks:
        tr = t_state.spotify_track
        if not tr.bpm or not tr.camelot_key:
            local_p = None
            if tr.spotify_url and tr.spotify_url.startswith("file://"):
                local_p = Path(tr.spotify_url.replace("file://", ""))
            try:
                enrich_track_audio_features(tr, local_path=local_p)
            except Exception as e:
                logger.debug(f"Feature enrichment notice for '{tr.title}': {e}")

    # 2. Reorder tracks
    sorted_tracks = optimize_dj_sequence(
        tracks=orchestrator.current_job.tracks,
        start_track_id=start_track_id,
        mode=mode
    )

    orchestrator.current_job.tracks = sorted_tracks
    orchestrator.current_job.current_track_index = 0

    StateManager.save_job(orchestrator.current_job)
    analysis = analyze_set_flow(orchestrator.current_job.tracks)

    await manager.broadcast({
        "type": "state_updated",
        "data": orchestrator.current_job.model_dump(),
        "queue_summary": orchestrator.download_queue.get_status_summary(orchestrator.current_job)
    })

    return {
        "status": "sorted",
        "mode": mode,
        "analysis": analysis,
        "job": orchestrator.current_job.model_dump()
    }


@app.post("/api/playlist/enrich-features")
async def enrich_playlist_features():
    """Analyzes and enriches BPM and harmonic keys for all tracks in the active playlist / folder."""
    if not orchestrator.current_job:
        raise HTTPException(status_code=400, detail="No active playlist or folder loaded.")

    from audio_analyzer import enrich_track_audio_features
    updated_count = 0
    for t_state in orchestrator.current_job.tracks:
        tr = t_state.spotify_track
        local_p = None
        if tr.spotify_url and tr.spotify_url.startswith("file://"):
            local_p = Path(tr.spotify_url.replace("file://", ""))
        try:
            changed = enrich_track_audio_features(tr, local_path=local_p)
            if changed:
                updated_count += 1
        except Exception as e:
            logger.debug(f"Enrichment notice for '{tr.title}': {e}")

    StateManager.save_job(orchestrator.current_job)
    await manager.broadcast({
        "type": "state_updated",
        "data": orchestrator.current_job.model_dump(),
        "queue_summary": orchestrator.download_queue.get_status_summary(orchestrator.current_job)
    })

    return {
        "status": "success",
        "updated_count": updated_count,
        "total_tracks": len(orchestrator.current_job.tracks),
        "job": orchestrator.current_job.model_dump()
    }


@app.get("/api/playlist/analysis")
async def get_playlist_dj_analysis():
    """Returns harmonic flow analysis and transition metrics for current playlist."""
    if not orchestrator.current_job:
        raise HTTPException(status_code=400, detail="No active playlist job.")

    from dj_sorter import analyze_set_flow
    analysis = analyze_set_flow(orchestrator.current_job.tracks)
    return analysis


@app.post("/api/folder/load")
async def load_local_folder(payload: Dict[str, Any]):
    """Loads audio tracks from a local directory for DJ inspection and sorting."""
    folder_path = payload.get("folder_path")
    if not folder_path:
        raise HTTPException(status_code=400, detail="Missing 'folder_path' parameter.")

    from local_folder_service import scan_folder_tracks
    try:
        folder_name, tracks = scan_folder_tracks(folder_path)
    except Exception as e:
        logger.error(f"Error scanning local folder: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    playlist_id = f"folder_{abs(hash(folder_path))}"
    job = PlaylistJob(
        playlist_id=playlist_id,
        playlist_name=folder_name,
        playlist_url=str(Path(folder_path).expanduser().resolve()),
        tracks=tracks,
        auto_mode=False
    )

    # In local folder mode, do not auto-run the crawler loop since files are already present
    orchestrator.current_job = job
    StateManager.save_job(job)

    await manager.broadcast({
        "type": "state_updated",
        "data": job.model_dump(),
        "queue_summary": orchestrator.download_queue.get_status_summary(job)
    })

    return {"status": "success", "job": job.model_dump(), "folder_name": folder_name}


@app.post("/api/folder/rename-order")
async def rename_folder_order():
    """Physically renames audio files with sequential numbers (01 -, 02 -) based on current sorted order."""
    if not orchestrator.current_job:
        raise HTTPException(status_code=400, detail="No active playlist or folder loaded.")

    from local_folder_service import rename_files_with_order
    renamed = rename_files_with_order(orchestrator.current_job)
    StateManager.save_job(orchestrator.current_job)

    await manager.broadcast({
        "type": "state_updated",
        "data": orchestrator.current_job.model_dump(),
        "queue_summary": orchestrator.download_queue.get_status_summary(orchestrator.current_job)
    })

    return {"status": "renamed", "renamed_count": len(renamed), "files": renamed}


@app.post("/api/folder/export-m3u")
async def export_folder_m3u():
    """Exports an .m3u8 playlist file into the audio folder matching the current DJ sequence."""
    if not orchestrator.current_job:
        raise HTTPException(status_code=400, detail="No active playlist or folder loaded.")

    from local_folder_service import export_m3u8
    try:
        path = export_m3u8(orchestrator.current_job)
        return {"status": "exported", "m3u8_path": str(path), "filename": path.name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export M3U8: {e}")


@app.post("/api/track/reset")
async def reset_single_track(payload: Dict[str, Any]):
    """Resets a single track and immediately begins searching it."""
    track_id = payload.get("track_id")
    if not orchestrator.current_job:
        raise HTTPException(status_code=400, detail="No active playlist job.")

    idx = next((i for i, t in enumerate(orchestrator.current_job.tracks) if t.spotify_track.id == track_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Track not found in current playlist.")

    t = orchestrator.current_job.tracks[idx]
    t.status = TrackStatus.PENDING
    t.candidates = []
    t.selected_candidate = None
    t.error_message = None
    t.downloaded_file_path = None
    orchestrator.current_job.current_track_index = idx

    StateManager.save_job(orchestrator.current_job)
    await manager.broadcast({"type": "state_updated", "data": orchestrator.current_job.model_dump()})

    if orchestrator._worker_task and not orchestrator._worker_task.done():
        orchestrator._worker_task.cancel()
    orchestrator._worker_task = asyncio.create_task(orchestrator._run_orchestrator_loop())

    return {"status": "track_reset", "track_id": track_id}


@app.post("/api/track/decide")
async def decide_track(decision: DecisionRequest):
    """Submits user decision for a track."""
    orchestrator.provide_decision(
        track_id=decision.track_id,
        action=decision.action,
        candidate_id=decision.candidate_id,
        custom_query=decision.custom_query
    )
    return {"status": "decision_received", "track_id": decision.track_id}


@app.post("/api/track/confirm")
async def confirm_track(payload: Dict[str, Any]):
    """Confirms candidate selection for a track and enqueues background download."""
    track_id = payload.get("track_id")
    candidate_id = payload.get("candidate_id")
    if not track_id:
        raise HTTPException(status_code=400, detail="Missing 'track_id'")
    orchestrator.provide_decision(
        track_id=track_id,
        action="confirm",
        candidate_id=candidate_id
    )
    return {"status": "confirmed", "track_id": track_id, "candidate_id": candidate_id}


@app.post("/api/track/skip")
async def skip_track(payload: Dict[str, Any]):
    """Skips the active track and moves to the next."""
    track_id = payload.get("track_id")
    if not track_id:
        raise HTTPException(status_code=400, detail="Missing 'track_id'")
    orchestrator.provide_decision(
        track_id=track_id,
        action="skip"
    )
    return {"status": "skipped", "track_id": track_id}


@app.post("/api/track/search")
async def search_custom_track(payload: Dict[str, Any]):
    """Triggers custom re-search for the active track."""
    track_id = payload.get("track_id")
    custom_query = payload.get("custom_query")
    if not track_id:
        raise HTTPException(status_code=400, detail="Missing 'track_id'")
    orchestrator.provide_decision(
        track_id=track_id,
        action="custom_search",
        custom_query=custom_query
    )
    return {"status": "searching", "track_id": track_id, "query": custom_query}


@app.post("/api/track/jump")
@app.post("/api/orchestrator/jump")
async def jump_to_track(payload: Dict[str, Any]):
    """Allows user to jump immediately to searching a specific track."""
    track_id = payload.get("track_id")
    if not orchestrator.current_job:
        raise HTTPException(status_code=400, detail="No active playlist job.")

    target_idx = next((i for i, t in enumerate(orchestrator.current_job.tracks) if t.spotify_track.id == track_id), None)
    if target_idx is None:
        raise HTTPException(status_code=404, detail="Track not found in current job.")

    # Unblock any waiting decision event
    for ev in list(orchestrator.decision_events.values()):
        ev.set()
    orchestrator.decision_events.clear()

    if orchestrator.current_job.tracks[target_idx].status != TrackStatus.COMPLETED:
        orchestrator.current_job.tracks[target_idx].status = TrackStatus.PENDING
    orchestrator.current_job.current_track_index = target_idx
    
    if orchestrator._worker_task and not orchestrator._worker_task.done():
        orchestrator._worker_task.cancel()
    
    orchestrator._worker_task = asyncio.create_task(orchestrator._run_orchestrator_loop())
    
    # Broadcast state immediately
    await manager.broadcast({
        "type": "state_updated",
        "data": orchestrator.current_job.model_dump(),
        "queue_summary": orchestrator.download_queue.get_status_summary(orchestrator.current_job)
    })
    return {"status": "jumped", "track_index": target_idx, "track_id": track_id}


@app.post("/api/browser/focus")
async def focus_browser_tab(payload: Dict[str, Any]):
    """Focuses Muzpa or Dashboard tab in the Chromium browser window."""
    target = payload.get("target", "muzpa")
    if target == "muzpa":
        await orchestrator.crawler.bring_muzpa_to_front()
    else:
        await orchestrator.crawler.bring_dashboard_to_front()
    return {"status": "focused", "target": target}


@app.post("/api/orchestrator/pause")
async def pause_orchestrator():
    await orchestrator.pause()
    return {"status": "paused"}


@app.post("/api/orchestrator/resume")
async def resume_orchestrator():
    await orchestrator.resume()
    return {"status": "resumed"}


@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest):
    if orchestrator.current_job:
        if req.auto_mode is not None:
            orchestrator.current_job.auto_mode = req.auto_mode
        if req.similarity_threshold is not None:
            orchestrator.current_job.similarity_threshold = req.similarity_threshold
        StateManager.save_job(orchestrator.current_job)
        await manager.broadcast({"type": "config_updated", "data": orchestrator.current_job.model_dump()})
    return {"status": "updated"}


# -------------------------------------------------------------
# DJ Set Tracklist Identifier Endpoints
# -------------------------------------------------------------

@app.post("/api/djset/analyze")
async def analyze_dj_set(payload: DJSetAnalyzeRequest):
    """Starts asynchronous DJ set analysis for a YouTube/SoundCloud URL or local set."""
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Missing 'url' in request.")

    yt_or_sc = bool(re.search(r"(youtube\.com|youtu\.be|soundcloud\.com)", url, re.IGNORECASE))
    if not yt_or_sc and not os.path.exists(url):
        raise HTTPException(status_code=400, detail="URL must be a valid YouTube, SoundCloud link or local audio file.")

    async def _progress_callback(info: Dict[str, Any]):
        await manager.broadcast({"type": "djset_progress", "data": info})

    # Run analysis in background task
    async def _run_analysis():
        try:
            job = await dj_set_service.analyze_dj_set(
                url=url,
                sample_interval=payload.sample_interval,
                snippet_duration=payload.snippet_duration,
                force_acoustic=payload.force_acoustic,
                on_progress_callback=lambda p: asyncio.create_task(_progress_callback(p))
            )
            await manager.broadcast({
                "type": "djset_complete",
                "data": job.model_dump()
            })
        except Exception as ex:
            logger.error(f"Background DJ set analysis error: {ex}")
            await manager.broadcast({
                "type": "djset_error",
                "data": {"error": str(ex)}
            })

    temp_id = f"djset_{uuid.uuid4().hex[:10]}"
    initial_job = DJSetJob(job_id=temp_id, source_url=url, status="extracting_info")
    dj_set_service.active_jobs[temp_id] = initial_job

    asyncio.create_task(_run_analysis())
    return {"status": "started", "job_id": temp_id, "job": initial_job.model_dump()}


@app.get("/api/djset/status/{job_id}")
async def get_dj_set_status(job_id: str):
    """Returns the current status and detected tracks of a DJ set analysis job."""
    job = dj_set_service.active_jobs.get(job_id)
    if not job:
        for j in dj_set_service.active_jobs.values():
            if j.job_id == job_id or j.source_url == job_id:
                job = j
                break
    if not job:
        if dj_set_service.active_jobs:
            job = list(dj_set_service.active_jobs.values())[-1]
        else:
            raise HTTPException(status_code=404, detail="DJ Set job not found.")
    return {"status": "success", "job": job.model_dump()}


@app.post("/api/djset/cancel/{job_id}")
async def cancel_dj_set(job_id: str):
    """Cancels an ongoing DJ set analysis job."""
    cancelled = dj_set_service.cancel_job(job_id)
    return {"status": "success", "cancelled": cancelled}


@app.post("/api/djset/to-playlist")
async def dj_set_to_playlist(payload: DJSetToPlaylistRequest):
    """Converts analyzed DJ set tracklist into an active PlaylistJob and begins Muzpa crawling."""
    try:
        target_id = payload.job_id
        if target_id not in dj_set_service.active_jobs and dj_set_service.active_jobs:
            target_id = list(dj_set_service.active_jobs.keys())[-1]

        playlist_job = dj_set_service.convert_to_playlist_job(
            job_id=target_id,
            playlist_name=payload.playlist_name,
            selected_indices=payload.selected_indices,
            auto_mode=payload.auto_mode,
            similarity_threshold=payload.similarity_threshold
        )
    except Exception as e:
        logger.error(f"Failed to convert DJ Set to playlist: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    await orchestrator.start_job(playlist_job)
    return {"status": "success", "job": playlist_job.model_dump()}


@app.post("/api/djset/export-spotify")
async def export_dj_set_to_spotify(payload: Dict[str, Any]):
    """Prepares tracks for Spotify playlist export or returns track URIs."""
    job_id = payload.get("job_id")
    target_id = job_id if job_id in dj_set_service.active_jobs else (list(dj_set_service.active_jobs.keys())[-1] if dj_set_service.active_jobs else None)
    if not target_id:
        raise HTTPException(status_code=404, detail="No DJ set job found.")

    job = dj_set_service.active_jobs[target_id]
    matched_ids = [f"spotify:track:{t.spotify_id}" for t in job.tracks if t.spotify_id]

    return {
        "status": "success",
        "matched_tracks": len(matched_ids),
        "total_tracks": len(job.tracks),
        "track_uris": matched_ids,
        "playlist_name": job.title
    }


# Mount static frontend
static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def serve_index():
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return HTMLResponse("<h1>Spotify to Muzpa Studio Dashboard</h1><p>index.html not found.</p>")


if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8000, log_level="info")
