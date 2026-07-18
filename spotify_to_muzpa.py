"""
spotify_to_muzpa.py (legacy / optional)
----------------------------------------
Standalone tool: reads a Spotify playlist and generates a CSV + HTML
file with direct Muzpa search links, for manual browsing.

This is kept for reference and for offline use, but it's no longer
required for the main workflow — app.py can now fetch a playlist
directly with --playlist-url and handle search + download in one step.

Usage:
    python3 spotify_to_muzpa.py "<spotify_playlist_url>"

Requirements:
    pip install spotipy --break-system-packages
"""

import csv
import os
import sys
import urllib.parse

import spotify_client

OUTPUT_DIR = "output"
MUZPA_SEARCH_BASE = "https://srv.muzpa.com/#/search?text="


def build_muzpa_search_url(track: str, artist: str) -> str:
    query = f"{track} {artist}"
    return MUZPA_SEARCH_BASE + urllib.parse.quote(query)


def write_csv(tracks: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Track Name", "Artist Name"])
        for t in tracks:
            writer.writerow([t["track"], t["artist"]])


def write_html(tracks: list[dict], path: str, playlist_name: str) -> None:
    rows = []
    for i, t in enumerate(tracks, 1):
        url = build_muzpa_search_url(t["track"], t["artist"])
        rows.append(
            f"""
            <tr>
              <td>{i}</td>
              <td>{t['track']}</td>
              <td>{t['artist']}</td>
              <td><a href="{url}" target="_blank">Search on Muzpa →</a></td>
              <td><input type="checkbox"></td>
            </tr>"""
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Muzpa search links - {playlist_name}</title>
<style>
  body {{ font-family: sans-serif; margin: 2rem; background: #111; color: #eee; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 8px 12px; border-bottom: 1px solid #333; text-align: left; }}
  th {{ background: #222; }}
  a {{ color: #1db954; text-decoration: none; font-weight: bold; }}
  a:hover {{ text-decoration: underline; }}
  tr:hover {{ background: #1a1a1a; }}
</style>
</head>
<body>
  <h1>{playlist_name}</h1>
  <p>{len(tracks)} tracks. Click each link to open the Muzpa search, download manually, and check it off.</p>
  <table>
    <thead>
      <tr><th>#</th><th>Track</th><th>Artist</th><th>Link</th><th>Done</th></tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 spotify_to_muzpa.py <spotify_playlist_url>")

    playlist_url = sys.argv[1]
    playlist_name, tracks = spotify_client.load_playlist(playlist_url)

    print(f"Reading playlist: {playlist_name}")
    print(f"Found {len(tracks)} tracks.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    import re

    safe_name = re.sub(r"[^\w\-. ]", "_", playlist_name)

    csv_path = os.path.join(OUTPUT_DIR, f"{safe_name}.csv")
    html_path = os.path.join(OUTPUT_DIR, f"{safe_name}.html")

    write_csv(tracks, csv_path)
    write_html(tracks, html_path, playlist_name)

    print(f"CSV written to: {csv_path}")
    print(f"HTML written to: {html_path}")
    print("\nTip: app.py --playlist-url now does search + download in one step,")
    print("so this tool is mainly useful for a quick manual reference list.")


if __name__ == "__main__":
    main()
