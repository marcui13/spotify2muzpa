import pytest
from config import settings

# In tests, disable automatic browser launching to prevent headless hanging
settings.AUTO_LAUNCH_BROWSER = False
settings.HEADLESS = True

from fastapi.testclient import TestClient
from server import app


@pytest.fixture
def client():
    return TestClient(app)
