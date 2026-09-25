import pytest
from config import settings

# In tests, disable automatic browser launching to prevent headless hanging
settings.AUTO_LAUNCH_BROWSER = False
settings.HEADLESS = True
settings.ENABLE_ACCESS_CONTROL = False

from fastapi.testclient import TestClient
from server import app, orchestrator


@pytest.fixture(autouse=True)
def disable_real_crawler_and_loop(monkeypatch):
    """Prevents tests from launching real Playwright Chromium or running crawler loops in background."""
    async def noop_async(*args, **kwargs):
        return None

    monkeypatch.setattr(orchestrator, "_run_orchestrator_loop", noop_async)
    monkeypatch.setattr(orchestrator.crawler, "initialize", noop_async)
    monkeypatch.setattr(orchestrator.crawler, "close", noop_async)
    monkeypatch.setattr(orchestrator.crawler, "bring_muzpa_to_front", noop_async)
    monkeypatch.setattr(orchestrator.crawler, "bring_dashboard_to_front", noop_async)
    monkeypatch.setattr(orchestrator.crawler, "autofill_login_form", noop_async)
    yield
    if orchestrator._worker_task and not orchestrator._worker_task.done():
        orchestrator._worker_task.cancel()
    orchestrator.current_job = None


@pytest.fixture
def client():
    return TestClient(app)
