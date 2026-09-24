"""
Access Control & Remote Kill-Switch Service.
Manages remote authorization, kill-switch status, and beta invitation key activation.
"""

import os
import json
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime
import httpx

from config import settings

logger = logging.getLogger("access_service")


class AccessStatus:
    AUTHORIZED = "AUTHORIZED"
    BLOCKED = "BLOCKED"
    ACTIVATION_REQUIRED = "ACTIVATION_REQUIRED"
    INVALID_KEY = "INVALID_KEY"
    UPDATE_REQUIRED = "UPDATE_REQUIRED"


class AccessManager:
    """Coordinates remote kill-switch verification and local key licensing."""

    def __init__(self, license_file: Optional[Path] = None, remote_url: Optional[str] = None):
        self.license_file = license_file or (settings.STATE_DIR / "license.json")
        self.remote_url = remote_url or settings.REMOTE_CONFIG_URL
        self.local_fallback_file = settings.BASE_DIR / "access_control.json"

        self._cached_config: Optional[Dict[str, Any]] = None
        self._cache_timestamp: float = 0.0
        self.cache_ttl_seconds: float = 600.0  # 10 minutes cache

    def _read_local_license(self) -> Optional[Dict[str, Any]]:
        """Reads local license file if it exists."""
        if not self.license_file.exists():
            return None
        try:
            with open(self.license_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read local license file: {e}")
            return None

    def _save_local_license(self, license_key: str) -> bool:
        """Saves activated license key to disk."""
        try:
            self.license_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "license_key": license_key.strip().upper(),
                "activated_at": datetime.now().isoformat(),
                "last_validated": datetime.now().isoformat(),
                "app_version": settings.APP_VERSION
            }
            with open(self.license_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save local license: {e}")
            return False

    def deactivate_key(self) -> bool:
        """Deactivates and removes current local license."""
        try:
            if self.license_file.exists():
                self.license_file.unlink()
            return True
        except Exception as e:
            logger.error(f"Failed to delete license file: {e}")
            return False

    async def fetch_remote_config(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Fetches remote JSON configuration with fallback to local cache or template.
        """
        now = time.time()
        if not force_refresh and self._cached_config and (now - self._cache_timestamp < self.cache_ttl_seconds):
            return self._cached_config

        # 1. Attempt network fetch
        if self.remote_url:
            try:
                async with httpx.AsyncClient(timeout=3.5, follow_redirects=True) as client:
                    resp = await client.get(self.remote_url)
                    if resp.status_code == 200:
                        config = resp.json()
                        self._cached_config = config
                        self._cache_timestamp = now
                        logger.info("Successfully fetched remote access configuration.")
                        return config
                    else:
                        logger.warning(f"Remote access config returned status {resp.status_code}.")
            except Exception as e:
                logger.warning(f"Network error fetching remote access config: {e}")

        # 2. Memory cache fallback
        if self._cached_config:
            return self._cached_config

        # 3. Local template fallback
        if self.local_fallback_file.exists():
            try:
                with open(self.local_fallback_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self._cached_config = config
                    self._cache_timestamp = now
                    logger.info("Loaded access configuration from local fallback file.")
                    return config
            except Exception as e:
                logger.error(f"Failed to read local fallback config: {e}")

        # 4. Default permissive safe fallback
        return {
            "app_enabled": True,
            "min_version": "1.0.0",
            "status_message": "Spotify2Muzpa Studio",
            "blocked_message": "La plataforma está temporalmente en mantenimiento.",
            "allowed_keys": ["*"]
        }

    @staticmethod
    def _is_version_allowed(current_ver: str, min_required_ver: str) -> bool:
        """Compares semver strings (e.g. 2.0.0 vs 1.0.0)."""
        def _parse(v: str) -> List[int]:
            parts = []
            for p in v.split("."):
                try:
                    parts.append(int(p))
                except ValueError:
                    parts.append(0)
            return parts

        c = _parse(current_ver)
        m = _parse(min_required_ver)
        # Pad to equal length
        length = max(len(c), len(m))
        c += [0] * (length - len(c))
        m += [0] * (length - len(m))
        return c >= m

    async def check_access(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Evaluates full access status including kill-switch, version, and license key.
        """
        if not settings.ENABLE_ACCESS_CONTROL:
            return {
                "is_authorized": True,
                "status": AccessStatus.AUTHORIZED,
                "app_enabled": True,
                "message": "Access control is disabled in configuration.",
                "activated_key": None,
                "app_version": settings.APP_VERSION,
                "min_version": "1.0.0"
            }

        config = await self.fetch_remote_config(force_refresh=force_refresh)
        app_enabled = bool(config.get("app_enabled", True))
        blocked_msg = config.get("blocked_message", "La plataforma se encuentra en pausa.")
        status_msg = config.get("status_message", "Spotify2Muzpa Studio")
        min_ver = str(config.get("min_version", "1.0.0"))
        allowed_keys = [str(k).strip().upper() for k in config.get("allowed_keys", [])]

        # 1. Global Kill-Switch Check
        if not app_enabled:
            return {
                "is_authorized": False,
                "status": AccessStatus.BLOCKED,
                "app_enabled": False,
                "message": blocked_msg,
                "activated_key": None,
                "app_version": settings.APP_VERSION,
                "min_version": min_ver
            }

        # 2. Minimum Version Check
        if not self._is_version_allowed(settings.APP_VERSION, min_ver):
            return {
                "is_authorized": False,
                "status": AccessStatus.UPDATE_REQUIRED,
                "app_enabled": True,
                "message": f"Se requiere actualizar la aplicación (versión mínima: {min_ver}, tu versión: {settings.APP_VERSION}).",
                "activated_key": None,
                "app_version": settings.APP_VERSION,
                "min_version": min_ver
            }

        # 3. License Key Check
        local_data = self._read_local_license()
        if not local_data or not local_data.get("license_key"):
            return {
                "is_authorized": False,
                "status": AccessStatus.ACTIVATION_REQUIRED,
                "app_enabled": True,
                "message": "Se requiere un código de activación de la beta privada.",
                "activated_key": None,
                "app_version": settings.APP_VERSION,
                "min_version": min_ver
            }

        active_key = str(local_data.get("license_key")).strip().upper()
        # Wildcard allows any key
        is_key_valid = ("*" in allowed_keys) or (active_key in allowed_keys)

        if not is_key_valid:
            return {
                "is_authorized": False,
                "status": AccessStatus.INVALID_KEY,
                "app_enabled": True,
                "message": "El código de activación ingresado ya no es válido o fue revocado.",
                "activated_key": active_key,
                "app_version": settings.APP_VERSION,
                "min_version": min_ver
            }

        return {
            "is_authorized": True,
            "status": AccessStatus.AUTHORIZED,
            "app_enabled": True,
            "message": status_msg,
            "activated_key": active_key,
            "app_version": settings.APP_VERSION,
            "min_version": min_ver
        }

    async def activate_key(self, raw_key: str) -> Tuple[bool, str]:
        """
        Validates raw key against remote allowed list and saves if valid.
        """
        key = (raw_key or "").strip().upper()
        if not key:
            return False, "Por favor ingresa un código de activación."

        config = await self.fetch_remote_config(force_refresh=True)
        if not config.get("app_enabled", True):
            return False, config.get("blocked_message", "La plataforma se encuentra en pausa.")

        allowed_keys = [str(k).strip().upper() for k in config.get("allowed_keys", [])]
        is_valid = ("*" in allowed_keys) or (key in allowed_keys)

        if not is_valid:
            return False, "El código de activación ingresado no es válido o no existe en la lista de permitidos."

        saved = self._save_local_license(key)
        if not saved:
            return False, "Error guardando la licencia local en disco."

        return True, "¡Acceso activado correctamente! Bienvenido a Spotify2Muzpa Studio."


# Global Access Manager instance
access_manager = AccessManager()
