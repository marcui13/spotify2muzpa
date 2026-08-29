import pytest
from fastapi.testclient import TestClient
from server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Spotify to Muzpa" in response.text


def test_get_state_empty(client):
    response = client.get("/api/state")
    assert response.status_code == 200
    data = response.json()
    assert "active" in data
    assert "job" in data


def test_update_config(client):
    response = client.post("/api/config", json={"auto_mode": True, "similarity_threshold": 85.0})
    assert response.status_code == 200
    assert response.json() == {"status": "updated"}


def test_browser_list(client):
    response = client.get("/api/browser/list")
    assert response.status_code == 200
    data = response.json()
    assert "current" in data
    assert "browsers" in data


def test_muzpa_credentials_flow(client):
    # Test GET
    get_res = client.get("/api/muzpa/credentials")
    assert get_res.status_code == 200
    assert "configured" in get_res.json()

    # Test POST
    post_res = client.post("/api/muzpa/credentials", json={"email": "test@example.com", "password": "secretpassword", "auto_submit": False})
    assert post_res.status_code == 200
    assert post_res.json()["status"] == "saved"


def test_track_decision_endpoints(client):
    # Test confirm endpoint
    conf_res = client.post("/api/track/confirm", json={"track_id": "test_track_1", "candidate_id": "cand_1"})
    assert conf_res.status_code == 200
    assert conf_res.json()["status"] == "confirmed"

    # Test skip endpoint
    skip_res = client.post("/api/track/skip", json={"track_id": "test_track_1"})
    assert skip_res.status_code == 200
    assert skip_res.json()["status"] == "skipped"

    # Test search custom endpoint
    search_res = client.post("/api/track/search", json={"track_id": "test_track_1", "custom_query": "Artist - Custom Song"})
    assert search_res.status_code == 200
    assert search_res.json()["status"] == "searching"

    # Test decide endpoint
    decide_res = client.post("/api/track/decide", json={"track_id": "test_track_1", "action": "CONFIRM", "candidate_id": "cand_1"})
    assert decide_res.status_code == 200
    assert decide_res.json()["status"] == "decision_received"
