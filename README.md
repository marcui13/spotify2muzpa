# Spotify to Muzpa Playlist Downloader

A personal tool that takes a Spotify playlist, searches for each track on
[Muzpa](https://muzpa.com), and lets you review, confirm, and download
matches — with searches automated and downloads queued in the background,
while you stay in control of every match.

> Built for personal use (finding DJ set tracks). Automating searches and
> downloads on a third-party site can interact with its Terms of Service —
> review Muzpa's ToS before relying on this for regular use, and treat this
> as a personal productivity tool rather than something to run unattended
> at scale.

---

## What it does

1. **Reads a Spotify playlist** directly from its URL (via the Spotify Web
   API), no manual export needed.
2. **Searches Muzpa automatically** for each track, using a Chrome window
   controlled by Playwright that's logged into your Muzpa account.
3. **Shows you the matches** in a local web UI, with the closest match to
   the Spotify track highlighted (using fuzzy string matching).
4. **You confirm or skip** each track. Nothing downloads without your
   explicit click.
5. **Downloads run in a background queue** (a few in parallel), so
   confirming a track doesn't block you from reviewing the next one.
6. **Files are saved** to `<output-dir>/<playlist name>/Artist - Track.mp3`.
7. **Click any track** in the list at any time to jump straight to
   searching it — in order, out of order, or to re-search one you already
   handled.

---

## Architecture

```
┌─────────────────┐        ┌───────────────────────────────┐
│  spotify_client  │──────▶│           app.py                │
│  (Spotify API)   │        │                                 │
└─────────────────┘        │  ┌───────────────────────────┐  │
                            │  │  Flask (main thread)       │  │
                            │  │  - serves the web UI       │  │
                            │  │  - /api/state, /start,      │  │
                            │  │    /decide, /search-track  │  │
                            │  └──────────────┬─────────────┘  │
                            │                 │ shared state    │
                            │                 │ (dict + locks)  │
                            │  ┌──────────────▼─────────────┐  │
                            │  │  worker_loop (bg thread)    │  │
                            │  │  - owns the Playwright       │  │
                            │  │    browser session          │  │
                            │  │  - searches Muzpa per track  │  │
                            │  │  - waits for your decision   │  │
                            │  └──────────────┬─────────────┘  │
                            │                 │ enqueues        │
                            │  ┌──────────────▼─────────────┐  │
                            │  │  download_worker × N        │  │
                            │  │  (bg threads, plain HTTP     │  │
                            │  │  via requests + session      │  │
                            │  │  cookies — never touch       │  │
                            │  │  Playwright)                 │  │
                            │  └───────────────────────────┘  │
                            └───────────────────────────────┘
```

**Why downloads don't use Playwright directly:** Playwright's sync API is
not thread-safe — only the thread that created the browser session is
allowed to call it. Calling it from other threads raises `Cannot switch to
a different thread`. So `app.py` captures the session cookies **once**
after login, and hands them to plain `requests`-based worker threads that
never touch Playwright again. This is also what makes the download queue
non-blocking: confirming a track just enqueues a job and moves on.

**Why searches still use Playwright:** Muzpa's search results are rendered
client-side (it's an AngularJS single-page app), so a plain HTTP request
wouldn't return the same HTML a logged-in browser sees. Playwright renders
the page and lets us read the real DOM.

---

## Setup

### 1. Install dependencies

```bash
python3 -m pip install flask playwright rapidfuzz requests spotipy --break-system-packages
python3 -m playwright install chromium
```

### 2. Create a Spotify app (free, one-time)

1. Go to <https://developer.spotify.com/dashboard> and log in.
2. **Create app** → any name/description.
3. Redirect URI: `http://127.0.0.1:8888/callback`
4. Save, then copy the **Client ID** and **Client Secret**.

### 3. Set environment variables

```bash
export SPOTIFY_CLIENT_ID="your_client_id"
export SPOTIFY_CLIENT_SECRET="your_client_secret"

# Optional — enables automatic Muzpa login attempts (see below)
export MUZPA_EMAIL="you@example.com"
export MUZPA_PASSWORD="your_password"
```

Never hardcode these in a file or paste them in chat/commits. If a secret
is ever exposed, rotate it (Spotify: regenerate the Client Secret in the
dashboard; Muzpa: change your password).

---

## Usage

### Single command (recommended)

```bash
python3 app.py --playlist-url "https://open.spotify.com/playlist/XXXXXXXXXXXX"
```

Then open <http://localhost:5000>.

### Legacy: from a CSV

If you'd rather generate a CSV first (e.g., to review the track list
offline before running the full tool):

```bash
python3 spotify_to_muzpa.py "https://open.spotify.com/playlist/XXXXXXXXXXXX"
python3 app.py --csv "output/my_playlist.csv" --playlist-name "my_playlist"
```

### First run: logging in to Muzpa

A Chrome window controlled by the script opens automatically, pointed at
Muzpa.

- If `MUZPA_EMAIL` / `MUZPA_PASSWORD` are set, the script makes a
  **best-effort automatic login attempt** using common form selectors.
  This wasn't verified against Muzpa's real login form, so it may not
  work — if the window still shows a login form after a couple of
  seconds, just **log in by hand once**.
- Either way, once you're logged in, the session is saved in
  `./browser_profile` and reused on future runs — you won't need to log
  in again unless that folder is deleted or the session expires.

### Using the app

- Click **Start**. The tool searches the first pending track and shows
  matches on the right, best match highlighted.
- Click **Download** on the match you want, or **Skip** to move on.
  Confirming doesn't wait for the file to finish downloading — you're
  immediately taken to the next track while the download runs in the
  background (watch the status badges update live).
- Click **any track** in the left-hand list to jump straight to searching
  it, at any time — including tracks that are already downloaded or
  skipped, if you want to re-check or replace them.
- Errors (no results found, failed downloads) show up as toast
  notifications in the bottom-right corner.

Files are saved to `~/Muzpa Downloads/<playlist name>/Artist - Track.mp3`
by default (change with `--output-dir`).

---

## Known limitations

- **Muzpa's markup is hardcoded.** The search-result and download-button
  selectors (`ms-release-track`, `a.ms-release-dwnldbtn`, etc.) were
  captured from a real page inspection at one point in time. If Muzpa
  changes its frontend, `extract_candidates()` in `app.py` will need
  updated selectors.
- **The login form selectors are guesses.** They weren't taken from a real
  inspection of Muzpa's login page. Manual login always works as a
  fallback.
- **No persistence between runs yet.** If you close the app mid-playlist,
  re-running with the same playlist starts the review from scratch (though
  already-downloaded files won't be re-downloaded unless you click them
  again). See Roadmap below.
- **Single Muzpa account, single machine.** This was built for personal
  use, not designed for multiple concurrent users.

---

## Architecture review / potential improvements

A few things worth considering if this keeps growing:

- **Persist state to disk** (e.g., a JSON file per playlist) so you can
  close the app mid-playlist and resume later without losing progress or
  re-reviewing already-decided tracks.
- **Retry logic for failed downloads** — right now a failed download just
  sits at `error`; clicking the track again re-searches it, but a
  dedicated "Retry download" action (re-using the same candidate href
  without a new search) would be faster.
- **Rate limiting / pacing** between searches to be gentler on Muzpa and
  reduce the chance of triggering anti-bot measures — right now searches
  fire as fast as you click.
- **Config file** instead of only env vars + CLI flags, for people who
  don't want to export variables every session (with the same
  no-hardcoded-secrets caution).
- **Structured logging** instead of `print()` statements, to make issues
  easier to diagnose from the terminal output.
- **Automated tests** for the pure-logic pieces (filename sanitization,
  fuzzy-match scoring, playlist parsing) — the Playwright/Flask glue is
  harder to test but the logic around it isn't.
- **Packaging** as a single installable CLI (e.g., a `pyproject.toml` +
  entry point) instead of "clone the folder and run `app.py`", if this is
  going to be used regularly.
- **Multi-user support**, if this ever becomes something to share: each
  user would need their own Spotify app credentials and their own Muzpa
  session/profile directory, plus a clear look at Muzpa's Terms of Service
  for automated access before enabling that.

---

## Project structure

```
spotify2muzpa/
├── app.py                  # Main tool: Flask UI + Playwright + download queue
├── spotify_client.py       # Shared Spotify API helpers
├── spotify_to_muzpa.py     # Legacy standalone CSV/HTML export tool
├── templates/
│   └── index.html          # Web UI (single page, polls /api/state)
├── browser_profile/        # Playwright's persistent Chrome profile (git-ignore this)
└── README.md
```

---

Agustin Marquardt © 2026 · Spotify2Muzpa
