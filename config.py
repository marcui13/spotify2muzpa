import warnings
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")
warnings.filterwarnings("ignore", category=UserWarning)

import os
import sys
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_base_dir() -> Path:
    """Returns the base directory where static resources and templates are bundled."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def get_default_user_dir() -> Path:
    """Returns a safe, writable directory for application state and browser profiles."""
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support" / "Spotify2MuzpaStudio"
        elif sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            base = Path(appdata) / "Spotify2MuzpaStudio" if appdata else Path.home() / ".spotify2muzpa"
        else:
            base = Path.home() / ".config" / "spotify2muzpa"
        return base
    return Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Spotify API Credentials
    SPOTIFY_CLIENT_ID: str = Field(default="", description="Spotify Developer Client ID")
    SPOTIFY_CLIENT_SECRET: str = Field(default="", description="Spotify Developer Client Secret")

    # Muzpa Credentials (Optional - for auto-login attempt)
    MUZPA_EMAIL: Optional[str] = Field(default=None, description="Muzpa Account Email")
    MUZPA_PASSWORD: Optional[str] = Field(default=None, description="Muzpa Account Password")
    MUZPA_BASE_URL: str = Field(default="https://srv.muzpa.com", description="Base URL of Muzpa SPA")

    # Operational Paths
    BASE_DIR: Path = Field(default_factory=get_base_dir)
    # Default output directory is ~/Downloads/<Playlist Name>
    DOWNLOAD_DIR: Path = Field(default_factory=lambda: Path.home() / "Downloads")
    BROWSER_PROFILE_DIR: Path = Field(default_factory=lambda: get_default_user_dir() / "user_data_profile")
    STATE_DIR: Path = Field(default_factory=lambda: get_default_user_dir() / "state")

    # Browser Selection: 'chrome', 'brave', 'edge', 'chromium'
    BROWSER_NAME: str = Field(default="chrome", description="Browser to launch: 'chrome', 'brave', 'edge', or 'chromium'")

    # Scraping & Matching Configuration
    AUTO_MODE: bool = Field(default=False, description="Automatically download highest fuzzy match if above threshold")
    SIMILARITY_THRESHOLD: float = Field(default=75.0, description="Minimum score (0-100) to consider a valid auto-match")
    HEADLESS: bool = Field(default=False, description="Run Chromium in headless mode (set False for manual login)")
    DOWNLOAD_TIMEOUT_SECONDS: int = Field(default=120, description="Timeout in seconds for single track download")
    PAGE_LOAD_TIMEOUT_MS: int = Field(default=30000, description="Page navigation timeout in ms")
    MAX_RETRIES: int = Field(default=3, description="Max retries for network actions")
    MAX_CONCURRENT_DOWNLOADS: int = Field(default=3, description="Concurrent background download workers")
    RATE_LIMIT_DELAY_SECONDS: float = Field(default=1.0, description="Delay between search operations")

    # Web Dashboard Server Configuration
    HOST: str = Field(default="127.0.0.1", description="Server Host binding")
    PORT: int = Field(default=8000, description="Server Port")
    OPEN_DASHBOARD_TAB: bool = Field(default=False, description="Open Web Dashboard tab in crawler browser window")
    AUTO_LAUNCH_BROWSER: bool = Field(default=True, description="Automatically launch crawler browser on server startup")
    IS_DESKTOP_APP: bool = Field(default=False, description="Whether running inside native desktop window")

    # Access Control & Remote Kill-Switch
    ENABLE_ACCESS_CONTROL: bool = Field(default=True, description="Enable remote activation and kill-switch verification")
    APP_VERSION: str = Field(default="2.0.0", description="Current application version")
    REMOTE_CONFIG_URL: str = Field(
        default="https://raw.githubusercontent.com/marcui13/spotify2muzpa/main/access_control.json",
        description="Remote URL for kill-switch and allowed activation keys"
    )

    def ensure_directories(self) -> None:
        """Ensure that required operational directories exist on disk, with fallback for read-only systems."""
        for attr in ["DOWNLOAD_DIR", "BROWSER_PROFILE_DIR", "STATE_DIR"]:
            p: Path = getattr(self, attr)
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception:
                fallback = Path.home() / ".spotify2muzpa" / p.name
                try:
                    fallback.mkdir(parents=True, exist_ok=True)
                    setattr(self, attr, fallback)
                except Exception:
                    pass


# Global settings instance
settings = Settings()
settings.ensure_directories()
