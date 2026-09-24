"""
Build Automation Script for Spotify to Muzpa Studio Desktop.
Packages the Python + FastAPI + Playwright application into a standalone native desktop app (.app / .dmg on macOS or .exe on Windows).
"""

import os
import sys
import shutil
import platform
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist"
BUILD_DIR = BASE_DIR / "build"
APP_NAME = "Spotify2MuzpaStudio"


def run_command(cmd: list[str], description: str):
    """Runs a shell command and logs output."""
    print(f"\n🚀 {description}...")
    print(f"Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        print(f"❌ Error during: {description} (Exit code {result.returncode})")
        sys.exit(result.returncode)
    print(f"✓ {description} completed successfully.")


def clean_previous_builds():
    """Removes previous build artifacts."""
    print("\n🧹 Cleaning previous build artifacts...")
    for p in [BUILD_DIR, DIST_DIR]:
        if p.exists():
            shutil.rmtree(p)
            print(f"Removed {p}")


def build_pyinstaller():
    """Runs PyInstaller to compile the desktop bundle."""
    os_type = platform.system().lower()
    
    # Path separators
    sep = ";" if os_type == "windows" else ":"

    # Data files to bundle
    static_data = f"{BASE_DIR / 'static'}{sep}static"
    env_data = f"{BASE_DIR / '.env.example'}{sep}."
    access_data = f"{BASE_DIR / 'access_control.json'}{sep}."
    
    cache_dir = BASE_DIR / ".pyinstaller_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["PYINSTALLER_CONFIG_DIR"] = str(cache_dir)

    pyinstaller_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onedir",
        "--windowed",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--add-data", static_data,
        "--add-data", env_data,
        "--add-data", access_data,
        "--hidden-import", "access_service",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "mutagen.easyid3",
        "--hidden-import", "mutagen.mp3",
        "--hidden-import", "rapidfuzz",
        "--hidden-import", "playwright",
        "--hidden-import", "spotipy",
        "--hidden-import", "webview",
        "--hidden-import", "certifi",
        "--hidden-import", "pydantic_settings",
        "--collect-all", "yt_dlp",
        "--collect-all", "shazamio",
        "--collect-all", "shazamio_core",
        "--collect-all", "static_ffmpeg",
        str(BASE_DIR / "desktop.py")
    ]

    run_command(pyinstaller_cmd, "Compiling desktop binary with PyInstaller")


def build_macos_dmg():
    """Creates a macOS .dmg disk image installer if on macOS."""
    if platform.system().lower() != "darwin":
        return

    app_path = DIST_DIR / f"{APP_NAME}.app"
    dmg_path = DIST_DIR / f"{APP_NAME}-macOS.dmg"

    if not app_path.exists():
        print(f"⚠️ App bundle not found at {app_path}, skipping DMG creation.")
        return

    print("\n📦 Generating macOS DMG Installer Image...")
    if dmg_path.exists():
        dmg_path.unlink()

    dmg_cmd = [
        "hdiutil", "create",
        "-volname", APP_NAME,
        "-srcfolder", str(app_path),
        "-ov",
        "-format", "UDZO",
        str(dmg_path)
    ]
    try:
        subprocess.run(dmg_cmd, check=True)
        print(f"🎉 Created DMG Installer at: {dmg_path}")
    except Exception as e:
        print(f"⚠️ Could not create DMG via hdiutil: {e}")


def build_windows_zip():
    """Creates a Windows .zip distribution archive if on Windows."""
    if platform.system().lower() != "windows":
        return

    app_dir = DIST_DIR / APP_NAME
    zip_base = DIST_DIR / f"{APP_NAME}-Windows"

    if not app_dir.exists():
        print(f"⚠️ Windows build directory not found at {app_dir}, skipping ZIP creation.")
        return

    print("\n📦 Packaging Windows ZIP distribution...")
    try:
        zip_file = shutil.make_archive(str(zip_base), "zip", root_dir=DIST_DIR, base_dir=APP_NAME)
        print(f"🎉 Created Windows ZIP at: {zip_file}")
    except Exception as e:
        print(f"⚠️ Could not create ZIP: {e}")


def main():
    print(f"=" * 60)
    print(f"   Building {APP_NAME} Desktop Package ({platform.system()})")
    print(f"=" * 60)

    clean_previous_builds()
    build_pyinstaller()

    if platform.system().lower() == "darwin":
        build_macos_dmg()
    elif platform.system().lower() == "windows":
        build_windows_zip()

    print("\n" + "=" * 60)
    print(f"🎉 Build Complete! Artifacts located in:")
    print(f"   📂 {DIST_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
