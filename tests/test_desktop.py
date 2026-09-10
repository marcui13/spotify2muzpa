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
    assert len(error_occurred) == 0, f"Thread import raised: {error_occurred}"


def test_find_free_port_busy_fallback():
    import socket
    base_port = 9990
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", base_port))
        s.listen(1)
        # find_free_port should gracefully find another port (e.g. 9991)
        port = find_free_port(base_port)
        assert port != base_port
        assert port > base_port

