"""
Tests for Access Control, Remote Kill-Switch, and Beta Activation Service.
"""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from access_service import AccessManager, AccessStatus
from config import settings


@pytest.fixture
def temp_license_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_ACCESS_CONTROL", True)
    license_file = tmp_path / "test_license.json"
    manager = AccessManager(license_file=license_file)
    # Mock remote config to use predictable values
    manager.fetch_remote_config = AsyncMock(return_value={
        "app_enabled": True,
        "min_version": "1.0.0",
        "status_message": "Spotify2Muzpa Test Beta",
        "blocked_message": "Mantenimiento",
        "allowed_keys": ["BETA-TEST-123", "BETA-VIP-999"]
    })
    return manager, license_file


@pytest.mark.asyncio
async def test_activation_required_when_no_license(temp_license_env):
    manager, license_file = temp_license_env
    status = await manager.check_access()
    assert status["is_authorized"] is False
    assert status["status"] == AccessStatus.ACTIVATION_REQUIRED


@pytest.mark.asyncio
async def test_successful_activation(temp_license_env):
    manager, license_file = temp_license_env
    success, msg = await manager.activate_key("beta-test-123")
    assert success is True
    assert license_file.exists()

    status = await manager.check_access()
    assert status["is_authorized"] is True
    assert status["status"] == AccessStatus.AUTHORIZED
    assert status["activated_key"] == "BETA-TEST-123"


@pytest.mark.asyncio
async def test_invalid_key_activation_rejected(temp_license_env):
    manager, license_file = temp_license_env
    success, msg = await manager.activate_key("INVALID-CODE-000")
    assert success is False
    assert not license_file.exists()


@pytest.mark.asyncio
async def test_kill_switch_blocks_access(temp_license_env):
    manager, license_file = temp_license_env
    # First activate valid key
    await manager.activate_key("BETA-TEST-123")
    assert (await manager.check_access())["is_authorized"] is True

    # Now simulate kill-switch activated on remote server
    manager.fetch_remote_config = AsyncMock(return_value={
        "app_enabled": False,
        "min_version": "1.0.0",
        "blocked_message": "Plataforma temporalmente pausada por mantenimiento.",
        "allowed_keys": ["BETA-TEST-123"]
    })

    status = await manager.check_access(force_refresh=True)
    assert status["is_authorized"] is False
    assert status["status"] == AccessStatus.BLOCKED
    assert "pausada" in status["message"]


@pytest.mark.asyncio
async def test_min_version_enforcement(temp_license_env):
    manager, license_file = temp_license_env
    await manager.activate_key("BETA-TEST-123")

    # Simulate required version 99.0.0
    manager.fetch_remote_config = AsyncMock(return_value={
        "app_enabled": True,
        "min_version": "99.0.0",
        "blocked_message": "Mantenimiento",
        "allowed_keys": ["BETA-TEST-123"]
    })

    status = await manager.check_access(force_refresh=True)
    assert status["is_authorized"] is False
    assert status["status"] == AccessStatus.UPDATE_REQUIRED
    assert "actualizar" in status["message"]


@pytest.mark.asyncio
async def test_deactivation(temp_license_env):
    manager, license_file = temp_license_env
    await manager.activate_key("BETA-TEST-123")
    assert license_file.exists()

    manager.deactivate_key()
    assert not license_file.exists()
    status = await manager.check_access()
    assert status["is_authorized"] is False
    assert status["status"] == AccessStatus.ACTIVATION_REQUIRED


def test_server_access_endpoints(client, monkeypatch, tmp_path):
    from access_service import access_manager

    monkeypatch.setattr(settings, "ENABLE_ACCESS_CONTROL", True)

    # Point access_manager to temporary test license file
    test_lic = tmp_path / "srv_lic.json"
    monkeypatch.setattr(access_manager, "license_file", test_lic)
    monkeypatch.setattr(access_manager, "fetch_remote_config", AsyncMock(return_value={
        "app_enabled": True,
        "min_version": "1.0.0",
        "status_message": "Beta Test",
        "blocked_message": "Blocked",
        "allowed_keys": ["BETA-SERVER-TEST"]
    }))

    # 1. Check status initial (unactivated)
    res = client.get("/api/access/status")
    assert res.status_code == 200
    assert res.json()["is_authorized"] is False

    # 2. Try to load playlist while unactivated -> 403 Forbidden
    pl_res = client.post("/api/playlist/load", json={"playlist_url": "https://open.spotify.com/playlist/test"})
    assert pl_res.status_code == 403

    # 3. Activate with wrong key -> 400
    act_bad = client.post("/api/access/activate", json={"key": "WRONG-KEY"})
    assert act_bad.status_code == 400

    # 4. Activate with valid key -> 200
    act_good = client.post("/api/access/activate", json={"key": "BETA-SERVER-TEST"})
    assert act_good.status_code == 200
    assert act_good.json()["access"]["is_authorized"] is True

    # 5. Check status now authorized -> 200
    res_auth = client.get("/api/access/status")
    assert res_auth.status_code == 200
    assert res_auth.json()["is_authorized"] is True
    assert res_auth.json()["activated_key"] == "BETA-SERVER-TEST"

    # 6. Deactivate key
    deact = client.post("/api/access/deactivate")
    assert deact.status_code == 200
    assert deact.json()["access"]["is_authorized"] is False
