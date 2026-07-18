"""
Spotify to Muzpa Playlist Downloader
-------------------------------------
Takes a Spotify playlist and helps you find + download each track from
Muzpa, with a human reviewing and confirming every match.

For each track, the tool:
  1. Searches Muzpa automatically (using a Chrome window controlled by
     Playwright, logged into your Muzpa session).
  2. Shows you the matches it found on a local web page, with the best
     match highlighted.
  3. You confirm which one to download (or skip the track).
  4. The download is QUEUED and runs in the background (several workers
     in parallel), so you can keep reviewing the next track without
     waiting for the previous download to finish.
  5. You can also click any track in the playlist at any time to jump
     straight to searching it (out of order, or to re-search one you
     already handled).

Single-command usage (fetches the playlist directly from Spotify):
    python3 app.py --playlist-url "https://open.spotify.com/playlist/XXXX"

Legacy usage (from a CSV produced by spotify_to_muzpa.py):
    python3 app.py --csv "output/my_playlist.csv" --playlist-name "my_playlist"

Requirements:
    pip install flask playwright rapidfuzz requests spotipy --break-system-packages
    playwright install chromium

Environment variables:
    SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET   -> required for --playlist-url
    MUZPA_EMAIL / MUZPA_PASSWORD                -> optional, for automatic
                                                    Muzpa login (see below)

First run:
    A Chrome window controlled by this script will open, pointing at
    Muzpa. If MUZPA_EMAIL/MUZPA_PASSWORD are set, the script will try to
    log in automatically using common form selectors. This is best-effort:
    Muzpa's real login form wasn't inspected, so if the automatic attempt
    doesn't work, just log in by hand in that same window ONCE — the
    session is saved in ./browser_profile and reused on future runs.
"""

import argparse
import csv
import os
import queue
import re
import threading
import time
import urllib.parse
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template, request
from playwright.sync_api import sync_playwright
from rapidfuzz import fuzz

import spotify_client

MUZPA_BASE_URL = "https://srv.muzpa.com"
MUZPA_SEARCH_URL = MUZPA_BASE_URL + "/#/search?text="
PROFILE_DIR = "./browser_profile"
DOWNLOAD_WORKERS = 3  # how many downloads run in parallel

app = Flask(__name__)

# ---------------------------------------------------------------------
# SHARED STATE (between the Flask thread and the Playwright thread)
# ---------------------------------------------------------------------
state_lock = threading.Lock()
state = {
    "status": "idle",  # idle | running | searching | awaiting_confirmation | done
    "tracks": [],
    "current_index": None,
    "candidates": [],
    "message": "",
    "playlist_name": "",
}

decision_queue = queue.Queue()
command_queue = queue.Queue()
download_queue = queue.Queue()
jump_queue = queue.Queue()  # manual "search this track now" requests from the UI

cookies_lock = threading.Lock()
session_cookies: dict = {}


# ---------------------------------------------------------------------
# TRACK LOADING
# ---------------------------------------------------------------------
def new_track(track: str, artist: str) -> dict:
    return {
        "track": track,
        "artist": artist,
        "status": "pending",  # pending | queued | downloading | downloaded | skipped | error
        "saved_as": None,
        "error_message": None,
    }


def load_tracks_from_csv(csv_path: str) -> list[dict]:
    tracks = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tracks.append(new_track(row["Track Name"].strip(), row["Artist Name"].strip()))
    return tracks


def load_tracks_from_spotify(playlist_url: str) -> tuple[str, list[dict]]:
    playlist_name, raw_tracks = spotify_client.load_playlist(playlist_url)
    tracks = [new_track(t["track"], t["artist"]) for t in raw_tracks]
    return playlist_name, tracks


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    return name.strip()


# ---------------------------------------------------------------------
# MUZPA: SEARCH, LOGIN, DOWNLOAD
# ---------------------------------------------------------------------
def extract_candidates(page, target_artist: str = "", target_track: str = "") -> list[dict]:
    """Extracts search results from the current Muzpa page, and flags the
    candidate that best matches the Spotify track (best match)."""
    candidates = []
    try:
        page.wait_for_selector("ms-release-track", timeout=8000)
    except Exception:
        return candidates  # no results

    elements = page.query_selector_all("ms-release-track")
    for el in elements:
        name_el = el.query_selector("ms-release-audio-name-text")
        name_text = name_el.inner_text().strip() if name_el else ""

        info_divs = el.query_selector_all("ms-release-audio-info div")
        info_text = " · ".join(d.inner_text().strip() for d in info_divs if d.inner_text().strip())

        category_el = el.query_selector("ms-release-audio-category")
        category = category_el.inner_text().strip() if category_el else ""

        dwnld_el = el.query_selector("a.ms-release-dwnldbtn")
        href = dwnld_el.get_attribute("href") if dwnld_el else None

        if href:
            candidates.append(
                {
                    "name": name_text,
                    "info": info_text,
                    "category": category,
                    "href": href,
                    "score": 0,
                    "best": False,
                }
            )

    if candidates:
        target = f"{target_artist} {target_track}".lower()
        for c in candidates:
            c["score"] = fuzz.token_sort_ratio(target, c["name"].lower())
        candidates.sort(key=lambda c: c["score"], reverse=True)
        candidates[0]["best"] = True

    return candidates


def try_auto_login(page, email: str, password: str) -> bool:
    """Best-effort automatic login using common form field selectors.

    Muzpa's real login form wasn't inspected when this was written, so
    this tries a handful of typical patterns and gives up gracefully if
    none match — manual login in the same browser window always remains
    available as a fallback.
    """
    if not email or not password:
        return False

    email_selectors = [
        'input[type="email"]',
        'input[name="email"]',
        'input[name="username"]',
        "input#email",
        "input#username",
    ]
    password_selectors = [
        'input[type="password"]',
        'input[name="password"]',
        "input#password",
    ]
    submit_selectors = [
        'button[type="submit"]',
        'button:has-text("Log in")',
        'button:has-text("Login")',
        'button:has-text("Sign in")',
        'button:has-text("Iniciar sesión")',
        'button:has-text("Entrar")',
    ]

    try:
        email_field = next((page.query_selector(sel) for sel in email_selectors if page.query_selector(sel)), None)
        password_field = next(
            (page.query_selector(sel) for sel in password_selectors if page.query_selector(sel)), None
        )
        if not email_field or not password_field:
            return False

        email_field.fill(email)
        password_field.fill(password)

        clicked = False
        for sel in submit_selectors:
            btn = page.query_selector(sel)
            if btn:
                btn.click()
                clicked = True
                break
        if not clicked:
            password_field.press("Enter")

        page.wait_for_timeout(2000)  # give the SPA a moment to process the login
        return True
    except Exception as e:
        print(f"[warn] automatic Muzpa login attempt failed: {e}")
        return False


def get_cookie_header(context) -> dict:
    """Extracts cookies from the Playwright session to use with requests."""
    cookies = context.cookies()
    return {c["name"]: c["value"] for c in cookies}


def download_worker():
    """Runs in its own thread: pulls tasks off the queue and downloads them
    with requests, without blocking the search/review loop.
    IMPORTANT: never call Playwright methods here — Playwright's sync API
    is not thread-safe and will raise 'Cannot switch to a different
    thread' if used from another thread."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": MUZPA_BASE_URL + "/",
        }
    )

    while True:
        task = download_queue.get()
        if task is None:
            break

        idx = task["idx"]
        href = task["href"]
        dest_path: Path = task["dest_path"]

        with cookies_lock:
            cookies = dict(session_cookies)

        with state_lock:
            state["tracks"][idx]["status"] = "downloading"

        url = href if href.startswith("http") else MUZPA_BASE_URL + href

        try:
            session.cookies.update(cookies)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with session.get(url, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(dest_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

            with state_lock:
                state["tracks"][idx]["status"] = "downloaded"
                state["tracks"][idx]["saved_as"] = str(dest_path)
        except Exception as e:
            print(f"[error] download failed for {dest_path.name}: {e}")
            with state_lock:
                state["tracks"][idx]["status"] = "error"
                state["tracks"][idx]["error_message"] = str(e)


# ---------------------------------------------------------------------
# MAIN REVIEW LOOP
# ---------------------------------------------------------------------
def get_next_track_index(tracks: list[dict]):
    """Priority order: a manual click from the UI always wins; otherwise,
    the next pending track in playlist order."""
    try:
        return jump_queue.get_nowait()
    except queue.Empty:
        pass
    for i, t in enumerate(tracks):
        if t["status"] == "pending":
            return i
    return None


def process_track(page, tracks: list[dict], out_base: Path, idx: int):
    t = tracks[idx]

    with state_lock:
        state["current_index"] = idx
        state["status"] = "searching"
        state["candidates"] = []
        tracks[idx]["error_message"] = None

    query = f'{t["track"]} {t["artist"]}'
    url = MUZPA_SEARCH_URL + urllib.parse.quote(query)
    page.goto(url)
    candidates = extract_candidates(page, target_artist=t["artist"], target_track=t["track"])

    with state_lock:
        state["candidates"] = candidates
        state["status"] = "awaiting_confirmation"
        if not candidates:
            tracks[idx]["error_message"] = "No results found on Muzpa for this track."

    decision = decision_queue.get()  # {"action": "download" | "skip", "href": ...}

    if decision["action"] == "skip":
        with state_lock:
            tracks[idx]["status"] = "skipped"
        return

    if decision["action"] == "download":
        href = decision["href"]
        filename = sanitize_filename(f'{t["artist"]} - {t["track"]}.mp3')
        dest_path = out_base / filename

        with state_lock:
            tracks[idx]["status"] = "queued"

        download_queue.put({"idx": idx, "href": href, "dest_path": dest_path})


def worker_loop(
    playlist_url: str,
    csv_path: str,
    playlist_name_override: str,
    output_dir: str,
    muzpa_email: str,
    muzpa_password: str,
):
    if playlist_url:
        with state_lock:
            state["message"] = "Fetching playlist from Spotify..."
        playlist_name, tracks = load_tracks_from_spotify(playlist_url)
    else:
        tracks = load_tracks_from_csv(csv_path)
        playlist_name = playlist_name_override or Path(csv_path).stem

    with state_lock:
        state["tracks"] = tracks
        state["playlist_name"] = playlist_name

    out_base = Path(output_dir).expanduser() / sanitize_filename(playlist_name)

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            accept_downloads=True,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(MUZPA_BASE_URL)

        if muzpa_email and muzpa_password:
            with state_lock:
                state["message"] = "Attempting automatic Muzpa login..."
            logged_in = try_auto_login(page, muzpa_email, muzpa_password)
            if logged_in:
                with state_lock:
                    state["message"] = (
                        "Attempted automatic login. If the Chrome window still shows "
                        "a login form, log in manually there once, then come back and "
                        "click Start."
                    )
            else:
                with state_lock:
                    state["message"] = (
                        "Could not auto-detect Muzpa's login form. Log in manually in "
                        "the Chrome window that opened, then come back and click Start."
                    )
        else:
            with state_lock:
                state["message"] = (
                    "Log in to Muzpa in the Chrome window that opened (if you aren't "
                    "already), then come back here and click Start."
                )

        # Wait for the "start" command from the web UI
        while True:
            cmd = command_queue.get()
            if cmd == "start":
                break

        # Capture cookies ONCE, at a quiet moment (right after confirming
        # login, before any searching begins). Calling context.cookies()
        # repeatedly in between heavy page activity can trigger a
        # Playwright sync-API bug ("Cannot switch to a different thread"),
        # so we avoid repeating this call per track.
        with cookies_lock:
            session_cookies.update(get_cookie_header(context))

        # Start the background download workers. They never touch
        # Playwright — they use the session_cookies captured above.
        for _ in range(DOWNLOAD_WORKERS):
            threading.Thread(target=download_worker, daemon=True).start()

        with state_lock:
            state["status"] = "running"

        while True:
            idx = get_next_track_index(tracks)
            if idx is None:
                with state_lock:
                    state["status"] = "done"
                    state["current_index"] = None
                    state["candidates"] = []
                idx = jump_queue.get()  # block until the user clicks a track

            process_track(page, tracks, out_base, idx)


# ---------------------------------------------------------------------
# FLASK ROUTES
# ---------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    with state_lock:
        return jsonify(state)


@app.route("/api/start", methods=["POST"])
def api_start():
    command_queue.put("start")
    return jsonify({"ok": True})


@app.route("/api/decide", methods=["POST"])
def api_decide():
    data = request.get_json()
    decision_queue.put(data)
    return jsonify({"ok": True})


@app.route("/api/search-track", methods=["POST"])
def api_search_track():
    data = request.get_json()
    idx = data.get("idx")
    with state_lock:
        valid = isinstance(idx, int) and 0 <= idx < len(state["tracks"])
    if not valid:
        return jsonify({"ok": False, "error": "invalid track index"}), 400
    jump_queue.put(idx)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Spotify to Muzpa Playlist Downloader")
    parser.add_argument(
        "--playlist-url",
        help="Spotify playlist URL. Fetches the track list directly (recommended).",
    )
    parser.add_argument(
        "--csv",
        help="Legacy: CSV produced by spotify_to_muzpa.py, used instead of --playlist-url.",
    )
    parser.add_argument(
        "--playlist-name",
        help="Override the playlist name used for the output folder (mainly for --csv).",
    )
    parser.add_argument(
        "--output-dir",
        default="~/Muzpa Downloads",
        help="Base folder where the playlist subfolder is created.",
    )
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument(
        "--muzpa-email",
        default=os.environ.get("MUZPA_EMAIL", ""),
        help="Optional. Defaults to the MUZPA_EMAIL environment variable.",
    )
    parser.add_argument(
        "--muzpa-password",
        default=os.environ.get("MUZPA_PASSWORD", ""),
        help="Optional. Defaults to the MUZPA_PASSWORD environment variable. "
        "Prefer the environment variable over this flag to avoid leaving "
        "your password in shell history.",
    )
    args = parser.parse_args()

    if not args.playlist_url and not args.csv:
        parser.error("Provide either --playlist-url or --csv.")

    t = threading.Thread(
        target=worker_loop,
        args=(
            args.playlist_url,
            args.csv,
            args.playlist_name,
            args.output_dir,
            args.muzpa_email,
            args.muzpa_password,
        ),
        daemon=True,
    )
    t.start()

    app.run(port=args.port, debug=False)


if __name__ == "__main__":
    main()
