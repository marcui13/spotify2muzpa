# AGENTS.md — Agent & Developer Guide for Spotify2Muzpa Studio

Welcome to **Spotify2Muzpa Studio**. This document establishes guidelines, architecture contracts, execution runbooks, and quality standards for AI coding agents and human engineers contributing to this repository.

---

## 🧭 1. Project Overview & Architecture

**Spotify2Muzpa Studio** is a modular, high-performance Python application that bridges Spotify playlists with web audio platforms (such as Muzpa). It extracts playlist metadata from Spotify, executes intelligent fuzzy searches on Muzpa via Chromium automation, downloads matching tracks asynchronously in the background, enriches MP3s with official ID3v2 metadata and DJ attributes (BPM & Camelot Harmonic Key), and presents a reactive web dashboard / native desktop GUI.

```
┌─────────────────────────┐
│     Spotify Service     │ ── (Official Spotipy API + Resilient Embed Parser)
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  Download Orchestrator  │ ── (Fuzzy Matching Engine via RapidFuzz)
└─────┬─────────────┬─────┘
      │             │
      ▼             ▼
┌─────────────┐  ┌─────────────────────────┐
│  Playwright │  │  Download Queue Manager │ ── (Asynchronous Worker Pool)
│   Crawler   │  └───────────┬─────────────┘
└─────────────┘              │
                             ▼
                 ┌─────────────────────────┐
                 │  Audio & ID3 Tagger     │ ── (Mutagen + Camelot Key Analyzer)
                 └───────────┬─────────────┘
                             │
                             ▼
                 ┌─────────────────────────┐
                 │ ~/Downloads/<Playlist>/ │
                 └─────────────────────────┘
```

### Core Architecture Pillars:
1. **Local-First & Privacy Preserving:** No user credentials, playlist URLs, or search queries leave the user's local machine.
2. **Native Download Capture (Solving HTTP 400):** Download flows use Playwright's native `page.expect_download()` and authenticated browser contexts to guarantee valid session cookies, AngularJS tokens, and request headers.
3. **Non-blocking Asynchronous Pipeline:** Confirming or auto-matching a track enqueues it to `DownloadQueueManager` and immediately advances the search loop without stalling for file I/O.
4. **DJ & Harmonic Analysis:** Calculates BPM and Camelot Wheel key signatures (`8A`, `11B`), writing them to standard ID3 frames (`TBPM`, `TKEY`, `TXXX`) recognized by Rekordbox, Serato DJ, Traktor, and Pioneer CDJs.

---

## 📁 2. Repository Structure & Module Responsibilities

```
spotify2muzpa/
├── config.py             # Centralized settings (Pydantic BaseSettings & .env loader)
├── models.py             # Strongly typed Pydantic models (SpotifyTrack, MuzpaCandidate, TrackState, PlaylistJob)
├── spotify_service.py    # Spotify extraction client with official API + Next.js embed fallback parser
├── dj_set_service.py     # Hybrid YouTube/SoundCloud DJ set tracklist parser & acoustic Shazam analyzer
├── muzpa_crawler.py      # Playwright browser automation, multi-tab manager, AngularJS reactive auto-fill
├── audio_analyzer.py     # BPM & Camelot Wheel harmonic key analyzer (pitch/mode translation)
├── downloader.py         # Asynchronous download queue workers, Mutagen ID3 tagging, state persistence
├── server.py             # FastAPI backend with REST endpoints, WebSocket streaming, and static files
├── run.py                # Unified interactive CLI entrypoint with browser selector
├── desktop.py            # Native desktop GUI wrapper using PyWebView (WebKit/Cocoa & WebView2)
├── build_desktop.py      # Automated cross-platform packaging script (PyInstaller & macOS DMG generator)
├── static/
│   └── index.html        # Reactive Spotify-styled dashboard (Tailwind CSS, glassmorphism, FontAwesome)
├── tests/
│   ├── test_audio_analyzer.py # Tests for Camelot Wheel mapping and DJ attributes
│   ├── test_dj_set_service.py # Tests for timestamp parsing, chapters, deduplication and 429 retry
│   ├── test_downloader.py     # Tests for filename sanitization and state persistence
│   ├── test_fuzzy.py          # Tests for RapidFuzz similarity scoring and penalties
│   ├── test_server.py         # Tests for FastAPI endpoints and state schemas
│   └── test_spotify.py        # Tests for Spotify URL/URI parsing and duration formatters
├── requirements.txt      # Production and development dependencies
├── README.md             # Public documentation, setup instructions, and library catalog
├── TERMS_AND_PRIVACY.md  # Legal terms of service, privacy policy, and disclaimers
└── AGENTS.md             # Instructions and standards for AI coding agents
```

---

## ⚙️ 3. Configuration & Environment Variables

All configuration is centralized in `config.py` using `pydantic-settings`. Configure via `.env` or system environment variables:

| Variable | Type | Default | Description |
| :--- | :---: | :---: | :--- |
| `SPOTIFY_CLIENT_ID` | `str` | `""` | Official Spotify Developer App Client ID |
| `SPOTIFY_CLIENT_SECRET` | `str` | `""` | Official Spotify Developer App Client Secret |
| `MUZPA_EMAIL` | `str` | `""` | Muzpa username / email for automatic form filling |
| `MUZPA_PASSWORD` | `str` | `""` | Muzpa password for automatic form filling |
| `SIMILARITY_THRESHOLD` | `float` | `75.0` | Minimum fuzzy match score required for auto-download |
| `AUTO_MODE` | `bool` | `False` | When True, auto-selects and downloads matches >= threshold |
| `DOWNLOAD_DIR` | `Path` | `~/Downloads` | Base destination directory for playlist folders |
| `BROWSER_NAME` | `str` | `"chrome"` | Target browser engine (`chrome`, `brave`, `edge`, `chromium`) |
| `HEADLESS` | `bool` | `False` | Run browser in headless mode |
| `MAX_CONCURRENT_DOWNLOADS` | `int` | `2` | Number of parallel background download workers |

---

## 🚀 4. Execution & Development Runbooks

### Setup Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### Launch Web Studio Dashboard
```bash
# Starts FastAPI server on http://localhost:8000
python server.py
# Or with interactive browser selection:
python run.py --server
```

### Run CLI Pipeline (Headless or Supervised)
```bash
python run.py --playlist "https://open.spotify.com/playlist/YOUR_PLAYLIST_ID" --auto --threshold 75
```

### Run Native Desktop App
```bash
python desktop.py
```

### Package Standalone Application (.app / .dmg / .exe)
```bash
python build_desktop.py
```

---

## 🧪 5. Testing & Quality Gates

Always run the full test suite before committing or merging any changes:

```bash
PYTHONPATH=. .venv/bin/pytest -v tests
```

### Code Standards for Agents:
1. **Type Annotations:** Maintain strict type annotations across all function signatures and Pydantic models.
2. **AngularJS Reactivity:** When automating DOM inputs in Muzpa, dispatch native `input` and `change` events (`dispatchEvent(new Event('input', { bubbles: true }))`) to notify the AngularJS scope.
3. **Safe Filenames:** Always run paths through `sanitize_filename()` before writing to disk to prevent path traversal or filesystem errors.
4. **Non-blocking Event Loop:** Never perform synchronous I/O or long-running HTTP blocking calls in FastAPI route handlers; use asynchronous equivalents (`aiofiles`, `asyncio.Queue`, `async with httpx.AsyncClient`).
5. **ID3 Tag Integrity:** Preserve existing ID3 frames when writing tags; always handle `HeaderNotFoundError` by initializing ID3 tags safely.
6. **Acoustic Audio Slicing Format:** `shazamio_core.Recognizer` strictly requires 16kHz mono 16-bit PCM WAV (`-c:a pcm_s16le -ar 16000 -ac 1`). Never pass MP3 slices to the native Rust signature recognizer as sample extraction will yield 0 samples.
7. **Acoustic Rate Limiting & Pacing:** Use adaptive stepping (jump forward 180s upon track match), client UA rotation, and exponential backoff (`4s * 2^attempt`) on `HTTP 429` to maintain reliable API quotas with Shazam.

---

## 🔒 6. Security & Privacy Rules

- **Zero Telemetry:** Never add tracking scripts, external analytics, or remote API pings.
- **Credential Hygiene:** Never commit `.env` or hardcode credentials in code. Use `.env.example` for templates.
- **User Data Isolation:** Browser sessions stored in `user_data_profile/` must remain in `.gitignore`.
