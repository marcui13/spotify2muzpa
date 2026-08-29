"""
Unified CLI & Server Entrypoint for Spotify to Muzpa Downloader.

Features:
  - Interactive Web Browser Selection (Chrome, Brave, Edge, Chromium).
  - Non-blocking Background Download Queue.
  - Saves MP3s with ID3 metadata directly to ~/Downloads/<Playlist Name>.
"""

import sys
import argparse
import asyncio
import logging
from pathlib import Path

import uvicorn
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

from config import settings
from models import PlaylistJob, TrackState, TrackStatus
from spotify_service import SpotifyService
from muzpa_crawler import MuzpaCrawlerEngine, detect_available_browsers
from downloader import MuzpaDownloader, StateManager, DownloadQueueManager

console = Console()


def prompt_browser_selection() -> str:
    """Interactively prompts the user to select their preferred browser."""
    available = detect_available_browsers()
    
    console.print("\n[bold cyan]Select Browser to Launch:[/bold cyan]")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", width=4, justify="center")
    table.add_column("Browser Name", width=32)
    table.add_column("Status", width=16)

    keys = list(available.keys())
    default_choice = "1"

    for idx, key in enumerate(keys, 1):
        info = available[key]
        status_str = "[bold green]Installed ✓[/bold green]" if info["installed"] else "[dim]Not found[/dim]"
        if info.get("recommended"):
            status_str += " [cyan](Recommended)[/cyan]"
            default_choice = str(idx)
        table.add_row(str(idx), info["name"], status_str)

    console.print(table)

    choice = Prompt.ask(
        "[bold yellow]Choose browser number[/bold yellow]",
        choices=[str(i) for i in range(1, len(keys) + 1)],
        default=default_choice
    )

    selected_key = keys[int(choice) - 1]
    console.print(f"[bold green]Selected: {available[selected_key]['name']}[/bold green]\n")
    return selected_key


def run_server(host: str, port: int, browser_name: str):
    """Starts the FastAPI Web Studio server with the chosen browser."""
    settings.BROWSER_NAME = browser_name
    console.print(f"[bold green]Starting Spotify to Muzpa Web Studio at http://{host}:{port}[/bold green]")
    console.print(f"[bold cyan]Selected Browser:[/bold cyan] [white]{browser_name}[/white]")
    console.print("[dim]Press Ctrl+C to stop the server.[/dim]")
    uvicorn.run("server:app", host=host, port=port, log_level="info")


async def run_cli_pipeline(playlist_url: str, auto_mode: bool, threshold: float, headless: bool, browser_name: str):
    """Executes the extraction, search, and non-blocking download queue via CLI."""
    settings.HEADLESS = headless
    settings.AUTO_MODE = auto_mode
    settings.SIMILARITY_THRESHOLD = threshold
    settings.BROWSER_NAME = browser_name

    console.print("[bold cyan]════════════════════════════════════════════════════════════[/bold cyan]")
    console.print("[bold green]          Spotify to Muzpa CLI Automation Engine            [/bold green]")
    console.print(f"[dim]Downloads destination: {settings.DOWNLOAD_DIR}/<Playlist Name>/[/dim]")
    console.print("[bold cyan]════════════════════════════════════════════════════════════[/bold cyan]\n")

    spotify = SpotifyService()
    crawler = MuzpaCrawlerEngine(browser_name=browser_name)
    download_queue = DownloadQueueManager(crawler)

    # 1. Fetch Spotify Playlist
    try:
        playlist_id = spotify.extract_playlist_id(playlist_url)
        console.print(f"[bold]1. Fetching Spotify playlist...[/bold] (ID: [yellow]{playlist_id}[/yellow])")
        name, img, tracks = spotify.fetch_playlist(playlist_url)
    except Exception as e:
        console.print(f"[bold red]Error loading Spotify playlist:[/bold red] {e}")
        return

    console.print(f"Loaded: [bold white]{name}[/bold white] ([cyan]{len(tracks)} tracks[/cyan])\n")

    # 2. Check for saved state
    job = StateManager.load_job(playlist_id)
    if not job:
        job = PlaylistJob(
            playlist_id=playlist_id,
            playlist_name=name,
            playlist_url=playlist_url,
            playlist_image=img,
            tracks=[TrackState(spotify_track=t) for t in tracks],
            auto_mode=auto_mode,
            similarity_threshold=threshold
        )
    else:
        console.print(f"[yellow]Resuming previous session with {len(job.tracks)} tracks.[/yellow]")

    # 3. Initialize Browser & Download Queue
    console.print(f"[bold]2. Launching {browser_name.title()} session...[/bold]")
    await crawler.initialize(browser_name=browser_name, open_dashboard_tab=False)
    download_queue.start()

    try:
        for idx, track_state in enumerate(job.tracks):
            track = track_state.spotify_track
            console.print(f"\n[bold magenta]Track [{idx+1}/{len(job.tracks)}]:[/bold magenta] [bold white]{track.artist} - {track.title}[/bold white] ({track.duration_str})")

            if track_state.status in [TrackStatus.COMPLETED, TrackStatus.DOWNLOADING]:
                console.print(f"  [green]✓ Status: {track_state.status.value}[/green]")
                continue

            # Search Muzpa
            console.print(f"  [cyan]🔍 Searching Muzpa...[/cyan]")
            candidates = await crawler.search_track(track)
            track_state.candidates = candidates

            if not candidates:
                console.print("  [red]✗ No candidates found on Muzpa.[/red]")
                track_state.status = TrackStatus.NOT_FOUND
                StateManager.save_job(job)
                continue

            top_candidate = candidates[0]

            # Display candidate table
            table = Table(title="Search Candidates", show_header=True, header_style="bold cyan")
            table.add_column("#", width=3)
            table.add_column("Score", width=6)
            table.add_column("Title", style="dim")
            table.add_column("Artist")
            table.add_column("Dur", width=6)
            table.add_column("Bitrate", width=8)

            for c_idx, c in enumerate(candidates[:5]):
                score_style = "green" if c.score >= 80 else ("yellow" if c.score >= 65 else "red")
                table.add_row(
                    str(c_idx + 1),
                    f"[{score_style}]{c.score}%[/{score_style}]",
                    c.title,
                    c.artist,
                    c.duration,
                    c.bitrate or "-"
                )

            console.print(table)

            # Decision
            chosen_candidate = None
            if auto_mode and top_candidate.score >= threshold:
                console.print(f"  [bold green]⚡ Auto-enqueuing top candidate ({top_candidate.score}% >= {threshold}%)[/bold green]")
                chosen_candidate = top_candidate
            else:
                if auto_mode:
                    console.print(f"  [yellow]Top match ({top_candidate.score}%) below threshold ({threshold}%). Confirmation needed.[/yellow]")
                
                prompt = console.input("  [bold yellow]Select candidate number (1-5), 's' to skip, or enter custom query:[/bold yellow] ").strip()
                if prompt.lower() == 's':
                    console.print("  [dim]Skipped track.[/dim]")
                    track_state.status = TrackStatus.SKIPPED
                    StateManager.save_job(job)
                    continue
                elif prompt.isdigit() and 1 <= int(prompt) <= len(candidates):
                    chosen_candidate = candidates[int(prompt) - 1]
                else:
                    custom_candidates = await crawler.search_track(track, custom_query=prompt)
                    if custom_candidates:
                        chosen_candidate = custom_candidates[0]
                    else:
                        console.print("  [red]No results for custom query.[/red]")
                        continue

            if chosen_candidate:
                console.print(f"  [bold cyan] Enqueued '{chosen_candidate.title}' for background download! Advancing...[/bold cyan]")
                download_queue.enqueue_download(job, track_state, chosen_candidate)

            StateManager.save_job(job)
            await asyncio.sleep(settings.RATE_LIMIT_DELAY_SECONDS)

        console.print("\n[bold yellow]All tracks reviewed. Waiting for background download queue to finish...[/bold yellow]")
        await download_queue.queue.join()

        console.print("\n[bold green]════════════════════════════════════════════════════════════[/bold green]")
        console.print(f"[bold green]   All downloads saved to: {settings.DOWNLOAD_DIR}/{job.playlist_name}/[/bold green]")
        console.print("[bold green]════════════════════════════════════════════════════════════[/bold green]")

    finally:
        download_queue.stop()
        await crawler.close()


def main():
    parser = argparse.ArgumentParser(description="Spotify to Muzpa Downloader Studio")
    parser.add_argument("--server", action="store_true", help="Launch web dashboard server")
    parser.add_argument("--playlist-url", type=str, help="Spotify playlist URL or URI")
    parser.add_argument("--auto", action="store_true", help="Enable 100% automatic download mode")
    parser.add_argument("--threshold", type=float, default=75.0, help="Similarity threshold for auto mode (0-100)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--browser", type=str, default=None, help="Browser to launch: 'chrome', 'brave', 'edge', 'chromium'")
    parser.add_argument("--host", type=str, default=settings.HOST, help="Web server host")
    parser.add_argument("--port", type=int, default=settings.PORT, help="Web server port")

    args = parser.parse_args()

    # Browser selection
    chosen_browser = args.browser
    if not chosen_browser:
        # Prompt interactively if run from terminal
        if sys.stdin.isatty():
            chosen_browser = prompt_browser_selection()
        else:
            chosen_browser = settings.BROWSER_NAME

    if args.server or not args.playlist_url:
        run_server(args.host, args.port, chosen_browser)
    else:
        asyncio.run(run_cli_pipeline(args.playlist_url, args.auto, args.threshold, args.headless, chosen_browser))


if __name__ == "__main__":
    main()
