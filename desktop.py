import warnings
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")
warnings.filterwarnings("ignore", category=UserWarning)

import sys
import time
import socket
import logging
import threading
import uvicorn
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("desktop_app")


def find_free_port(preferred_port: int = 8000) -> int:
    """Finds an available local port that can be bound, prioritizing preferred_port."""
    for p in [preferred_port] + list(range(preferred_port + 1, preferred_port + 40)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", p))
                return p
        except OSError:
            continue

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


import os
os.environ["IS_DESKTOP_APP"] = "1"
os.environ["OPEN_DASHBOARD_TAB"] = "false"


def start_server_thread(host: str, port: int):
    """Starts Uvicorn FastAPI server in a dedicated background daemon thread."""
    import asyncio
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    except Exception as e:
        logger.debug(f"Event loop setup notice: {e}")

    from config import settings
    settings.IS_DESKTOP_APP = True
    settings.OPEN_DASHBOARD_TAB = False
    settings.HOST = host
    settings.PORT = port

    from server import app
    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="info",
        access_log=False
    )
    server = uvicorn.Server(config)
    server.run()


def wait_for_server(host: str, port: int, timeout: float = 10.0) -> bool:
    """Waits until the local server accepts TCP connections."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(0.2)
    return False


def main():
    """Main desktop application entrypoint."""
    host = "127.0.0.1"
    port = find_free_port(8000)
    app_url = f"http://{host}:{port}"

    logger.info(f"Starting Spotify to Muzpa Studio Desktop on {app_url}...")

    # Start FastAPI server in background thread
    server_thread = threading.Thread(
        target=start_server_thread,
        args=(host, port),
        daemon=True,
        name="FastAPIServerThread"
    )
    server_thread.start()

    if not wait_for_server(host, port, timeout=8.0):
        logger.error("Failed to start local background server in time.")
        sys.exit(1)

    logger.info("Background server ready. Launching desktop window...")

    try:
        import webview
        # Create native desktop window
        window = webview.create_window(
            title="Spotify to Muzpa Studio",
            url=app_url,
            width=1280,
            height=850,
            min_size=(1050, 700),
            background_color="#121212",
            text_select=True,
            confirm_close=False
        )
        webview.start(debug=False)
    except ImportError:
        logger.warning("pywebview is not installed. Falling back to default system browser.")
        import webbrowser
        webbrowser.open(app_url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Error initializing desktop GUI window: {e}")
        import webbrowser
        webbrowser.open(app_url)


if __name__ == "__main__":
    main()
