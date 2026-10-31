#!/usr/bin/env python3
"""
Tracklist Extractor CLI for Spotify2Muzpa Studio.
Extracts tracks from images (via macOS Apple Vision OCR) or copied text lists,
prints formatted tracklists, and optionally launches Muzpa downloads.

Usage:
  python extract_tracklist.py --image "screenshot.png"
  python extract_tracklist.py --image "screenshot.png" --download --auto
  python extract_tracklist.py --text "tracklist.txt"
  python extract_tracklist.py --clipboard
"""

import sys
import argparse
import asyncio
import subprocess
from pathlib import Path
from typing import List, Optional

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm

from config import settings
from models import ExtractedTrackItem
from tracklist_extractor_service import (
    extract_text_from_image,
    parse_tracklist_lines,
    create_playlist_job_from_extracted
)
from muzpa_crawler import detect_available_browsers
from run import run_cli_pipeline, prompt_browser_selection

console = Console()


def read_text_from_clipboard() -> Optional[str]:
    """Reads text from system clipboard using pbpaste on macOS."""
    try:
        if sys.platform == "darwin":
            out = subprocess.check_output(["pbpaste"], text=True)
            return out if out and out.strip() else None
    except Exception:
        pass
    return None


def display_extracted_tracks_table(tracks: List[ExtractedTrackItem], title: str = "Extracted Tracklist") -> None:
    table = Table(title=title, show_header=True, header_style="bold magenta")
    table.add_column("#", width=4, justify="center")
    table.add_column("Artist", style="green", min_width=20)
    table.add_column("Title", style="white", min_width=25)
    table.add_column("Muzpa Search Query", style="dim cyan", min_width=30)

    for t in tracks:
        q = f"{t.artist} - {t.title}"
        table.add_row(
            str(t.index),
            t.artist,
            t.title,
            q
        )

    console.print(table)


def run_extractor_cli():
    parser = argparse.ArgumentParser(description="Extract tracks from Image or Copied List for Muzpa")
    parser.add_argument("--image", "-i", type=str, help="Path to tracklist image file (PNG, JPG, WEBP, etc.)")
    parser.add_argument("--text", "-t", type=str, help="Path to tracklist text file")
    parser.add_argument("--pasted", "-p", type=str, help="Directly passed multiline tracklist string")
    parser.add_argument("--clipboard", "-c", action="store_true", help="Read tracklist from clipboard")
    parser.add_argument("--name", "-n", type=str, default="Extracted Tracklist", help="Name for playlist/folder")
    parser.add_argument("--download", "-d", action="store_true", help="Directly queue to Muzpa download engine")
    parser.add_argument("--auto", "-a", action="store_true", help="Enable 100% automatic download mode")
    parser.add_argument("--threshold", type=float, default=75.0, help="Fuzzy match threshold (0-100)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--browser", type=str, default=None, help="Target browser engine")

    args = parser.parse_args()

    console.print("\n[bold magenta]════════════════════════════════════════════════════════════[/bold magenta]")
    console.print("[bold white]    Spotify2Muzpa — Image & Tracklist Text Extractor       [/bold white]")
    console.print("[bold magenta]════════════════════════════════════════════════════════════[/bold magenta]\n")

    raw_text = ""

    if args.image:
        img_path = Path(args.image).expanduser().resolve()
        if not img_path.is_file():
            console.print(f"[bold red]Error: Image file not found at '{img_path}'[/bold red]")
            sys.exit(1)
        console.print(f"[cyan]Performing Apple Vision OCR on image:[/cyan] {img_path.name}...")
        try:
            raw_text = extract_text_from_image(image_path=str(img_path))
        except Exception as e:
            console.print(f"[bold red]OCR extraction failed:[/bold red] {e}")
            sys.exit(1)
    elif args.text:
        txt_path = Path(args.text).expanduser().resolve()
        if not txt_path.is_file():
            console.print(f"[bold red]Error: Text file not found at '{txt_path}'[/bold red]")
            sys.exit(1)
        raw_text = txt_path.read_text(encoding="utf-8")
    elif args.pasted:
        raw_text = args.pasted
    elif args.clipboard:
        clip = read_text_from_clipboard()
        if not clip:
            console.print("[bold red]Clipboard is empty or does not contain text.[/bold red]")
            sys.exit(1)
        raw_text = clip
    else:
        # Interactive prompt if no arguments passed
        console.print("[yellow]No source specified. Enter image path, text file path, or paste text below.[/yellow]")
        choice = Prompt.ask("Choose input type", choices=["image", "file", "clipboard", "paste"], default="image")
        if choice == "image":
            p = Prompt.ask("Enter path to image file")
            raw_text = extract_text_from_image(image_path=str(Path(p).expanduser().resolve()))
        elif choice == "file":
            p = Prompt.ask("Enter path to text file")
            raw_text = Path(p).expanduser().resolve().read_text(encoding="utf-8")
        elif choice == "clipboard":
            clip = read_text_from_clipboard()
            if not clip:
                console.print("[bold red]Clipboard is empty.[/bold red]")
                sys.exit(1)
            raw_text = clip
        else:
            console.print("Paste your tracklist below (press Enter twice or Ctrl+D when finished):")
            lines = []
            try:
                while True:
                    line = input()
                    if not line and lines and not lines[-1]:
                        break
                    lines.append(line)
            except EOFError:
                pass
            raw_text = "\n".join(lines)

    tracks = parse_tracklist_lines(raw_text)
    if not tracks:
        console.print("[bold red]No tracks could be recognized from the provided input.[/bold red]")
        sys.exit(1)

    display_extracted_tracks_table(tracks, title=f"Extracted Tracks ({len(tracks)} found)")

    # Option to download
    should_download = args.download
    if not should_download and sys.stdin.isatty():
        should_download = Confirm.ask("\n[bold green]Queue these tracks for Muzpa download?[/bold green]", default=True)

    if should_download:
        chosen_browser = args.browser
        if not chosen_browser:
            if sys.stdin.isatty():
                chosen_browser = prompt_browser_selection()
            else:
                chosen_browser = settings.BROWSER_NAME

        job = create_playlist_job_from_extracted(
            tracks=tracks,
            playlist_name=args.name,
            auto_mode=args.auto,
            similarity_threshold=args.threshold
        )

        from downloader import StateManager, DownloadQueueManager
        from muzpa_crawler import MuzpaCrawlerEngine
        from downloader import MuzpaDownloader

        async def _run_download():
            settings.HEADLESS = args.headless
            settings.AUTO_MODE = args.auto
            settings.SIMILARITY_THRESHOLD = args.threshold
            settings.BROWSER_NAME = chosen_browser

            queue = DownloadQueueManager(max_concurrent=settings.MAX_CONCURRENT_DOWNLOADS)
            crawler = MuzpaCrawlerEngine(headless=args.headless, browser_name=chosen_browser)
            downloader = MuzpaDownloader(crawler=crawler, queue_manager=queue)
            await crawler.start()
            console.print(f"[bold green]Starting Muzpa crawler for job: '{job.playlist_name}'...[/bold green]")
            await downloader.process_playlist(job)
            await crawler.close()

        asyncio.run(_run_download())


if __name__ == "__main__":
    run_extractor_cli()
