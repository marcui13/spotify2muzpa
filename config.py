import warnings
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")
warnings.filterwarnings("ignore", category=UserWarning)

from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    BASE_DIR: Path = Field(default_factory=lambda: Path(__file__).resolve().parent)
    # Default output directory is ~/Downloads/<Playlist Name>
    DOWNLOAD_DIR: Path = Field(default_factory=lambda: Path.home() / "Downloads")
    BROWSER_PROFILE_DIR: Path = Field(default_factory=lambda: Path(__file__).resolve().parent / "user_data_profile")
    STATE_DIR: Path = Field(default_factory=lambda: Path(__file__).resolve().parent / "state")

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

    def ensure_directories(self) -> None:
        """Ensure that required operational directories exist on disk."""
        self.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self.STATE_DIR.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
settings.ensure_directories()
