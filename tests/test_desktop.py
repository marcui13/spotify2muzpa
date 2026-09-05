import pytest
from desktop import find_free_port, wait_for_server


def test_find_free_port():
    port = find_free_port(8000)
    assert isinstance(port, int)
    assert 1024 <= port <= 65535


def test_server_import_in_thread():
    import threading
    import asyncio

    error_occurred = []

    def run_import():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            from server import app, orchestrator
            assert app is not None
            assert orchestrator is not None
        except Exception as e:
            error_occurred.append(e)

    t = threading.Thread(target=run_import)
    t.start()
    t.join(timeout=3.0)

    assert len(error_occurred) == 0, f"Thread import raised: {error_occurred}"
