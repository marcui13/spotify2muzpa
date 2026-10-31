#!/usr/bin/env python3
"""
Filter & Sub-Playlist Generator CLI.
Extracts tracks from a Spotify playlist, filters them by query / artist / BPM / Key,
and creates a new Spotify playlist or exports track URIs.

Usage:
  python filter_playlist.py --url "https://open.spotify.com/playlist/..." --query "guyj" --create
  python filter_playlist.py --prompt "quiero hacer una playlist con todos los tracks de guyj que hay acá https://open.spotify.com/playlist/..."
"""

import sys
import argparse
import subprocess
from pathlib import Path
from typing import List, Optional

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm

from config import settings
from models import SpotifyTrack
from spotify_service import SpotifyService
from playlist_filter_service import parse_filter_prompt, filter_tracks

console = Console()


def copy_to_clipboard(text: str) -> bool:
    """Copies text to macOS / system clipboard."""
    try:
        if sys.platform == "darwin":
            process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            process.communicate(text.encode("utf-8"))
            return process.returncode == 0
        return False
    except Exception:
        return False


def display_tracks_table(tracks: List[SpotifyTrack], title: str = "Filtered Tracks") -> None:
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("#", width=4, justify="center")
    table.add_column("Title", style="white", min_width=20)
    table.add_column("Artist", style="green", min_width=18)
    table.add_column("BPM", justify="right", width=6)
    table.add_column("Key", justify="center", width=6)
    table.add_column("Duration", justify="right", width=8)

    for idx, t in enumerate(tracks, 1):
        table.add_row(
            str(idx),
            t.title,
            t.artist,
            str(t.bpm) if t.bpm else "-",
            t.camelot_key or "-",
            t.duration_str
        )

    console.print(table)


def run_filter_cli():
    parser = argparse.ArgumentParser(description="Filter tracks from a Spotify playlist and create a new sub-playlist.")
    parser.add_argument("--url", "-u", type=str, help="Spotify playlist, album, or track URL")
    parser.add_argument("--query", "-q", type=str, default=None, help="Search query or artist name (e.g. 'guyj', 'Guy J')")
    parser.add_argument("--prompt", "-p", type=str, help="Natural language prompt containing URL and filter instruction")
    parser.add_argument("--filter-by", type=str, default="all", choices=["all", "artist", "title", "key", "bpm"], help="Field to filter by")
    parser.add_argument("--min-bpm", type=int, default=None, help="Minimum BPM constraint")
    parser.add_argument("--max-bpm", type=int, default=None, help="Maximum BPM constraint")
    parser.add_argument("--key", type=str, default=None, help="Camelot Key constraint (e.g. 8A, 11B)")
    parser.add_argument("--name", "-n", type=str, default=None, help="Name for the new playlist")
    parser.add_argument("--create", "-c", action="store_true", help="Automatically create playlist in Spotify")
    parser.add_argument("--export-m3u", type=str, default=None, help="Path to export an .m3u8 playlist file")
    parser.add_argument("--copy-uris", action="store_true", help="Copy track URIs to clipboard")

    args = parser.parse_args()

    # Determine input prompt or URL
    raw_input = args.prompt or args.url
    query = args.query

    if not raw_input:
        console.print("[bold cyan]════════════════════════════════════════════════════════════[/bold cyan]")
        console.print("[bold green]       Spotify Playlist Filter & Sub-Playlist Generator     [/bold green]")
        console.print("[bold cyan]════════════════════════════════════════════════════════════[/bold cyan]\n")
        raw_input = Prompt.ask("[bold yellow]Enter Spotify playlist URL or prompt[/bold yellow]")

    extracted_url, extracted_q = parse_filter_prompt(raw_input)
    target_url = extracted_url or raw_input
    if extracted_q and query is None:
        query = extracted_q

    if query is None:
        if sys.stdin.isatty():
            query = Prompt.ask("[bold yellow]Filter query / artist name (leave empty for all tracks)[/bold yellow]", default="")
        else:
            query = ""

    console.print(f"\n[dim]Target URL:[/dim] [white]{target_url}[/white]")
    console.print(f"[dim]Filter Query:[/dim] [cyan]{query or 'All tracks'}[/cyan]\n")

    spotify = SpotifyService()

    console.print("[bold]1. Fetching playlist tracks from Spotify...[/bold]")
    try:
        pl_name, pl_img, all_tracks = spotify.fetch_playlist(target_url)
    except Exception as e:
        console.print(f"[bold red]Failed to load playlist:[/bold red] {e}")
        return

    console.print(f"Loaded: [bold white]{pl_name}[/bold white] ([cyan]{len(all_tracks)} total tracks[/cyan])")

    # Filter tracks
    filtered = filter_tracks(
        tracks=all_tracks,
        query=query,
        filter_by=args.filter_by,
        min_bpm=args.min_bpm,
        max_bpm=args.max_bpm,
        camelot_key=args.key
    )

    console.print(f"[bold green]Matched {len(filtered)} of {len(all_tracks)} tracks[/bold green] matching '{query}'\n")

    if not filtered:
        console.print("[yellow]No matching tracks found for this filter criteria.[/yellow]")
        return

    display_tracks_table(filtered, title=f"Matched Tracks for '{query}' ({len(filtered)} tracks)")

    # Suggested playlist name
    suggested_name = args.name or (f"{query.title()} — Selection from {pl_name}" if query else f"Selection from {pl_name}")

    track_uris = [f"spotify:track:{t.id}" for t in filtered if t.id and not t.id.startswith("track_")]

    # Copy URIs if requested
    if args.copy_uris or copy_to_clipboard("\n".join(track_uris)):
        console.print("[dim]✓ Copied track URIs to clipboard (ready to Cmd+V in Spotify)[/dim]")

    # Export M3U8 if requested
    if args.export_m3u:
        out_p = Path(args.export_m3u).expanduser().resolve()
        lines = ["#EXTM3U", f"#PLAYLIST:{suggested_name}"]
        for t in filtered:
            lines.append(f"#EXTINF:{t.duration_ms//1000},{t.artist} - {t.title}")
            lines.append(t.spotify_url or f"spotify:track:{t.id}")
        out_p.write_text("\n".join(lines), encoding="utf-8")
        console.print(f"[bold green]✓ Exported M3U8 playlist to:[/bold green] {out_p}")

    # Create playlist on Spotify
    should_create = args.create
    if not should_create and not args.copy_uris and not args.export_m3u:
        should_create = Confirm.ask(f"[bold yellow]Create new Spotify playlist '{suggested_name}'?[/bold yellow]", default=True)

    if should_create:
        if spotify.is_user_authenticated():
            console.print(f"[bold]Creating playlist '[white]{suggested_name}[/white]' in your Spotify account...[/bold]")
            res = spotify.create_user_playlist(
                name=suggested_name,
                description=f"Filtered selection for '{query}' from {pl_name} via Spotify2Muzpa Studio",
                track_ids_or_uris=track_uris
            )
            if res:
                console.print(f"\n[bold green]✓ Playlist created successfully![/bold green]")
                console.print(f"URL: [cyan]{res['playlist_url']}[/cyan]")
                console.print(f"URI: [white]{res['playlist_uri']}[/white]")
                console.print(f"Tracks added: [bold white]{res['tracks_added']}[/bold white]")
            else:
                console.print("[bold red]Failed to create playlist on Spotify account.[/bold red]")
        else:
            auth_url = spotify.get_user_auth_url()
            console.print("\n[yellow]Notice: Spotify account is not currently linked via OAuth.[/yellow]")
            if auth_url:
                console.print(f"To link your account, open this authorization link in your browser:\n[cyan]{auth_url}[/cyan]\n")
            console.print("Alternatively, all track URIs are copied to your clipboard. Simply open Spotify and press [bold white]Cmd+V[/bold white] into any new playlist!")


if __name__ == "__main__":
    run_filter_cli()
