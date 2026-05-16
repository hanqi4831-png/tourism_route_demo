"""Web launcher entrypoint for the tourism route recommendation system."""

from __future__ import annotations

import threading
import time
import webbrowser
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}/"
SERVER_READY_TIMEOUT_SECONDS = 30.0
SERVER_READY_POLL_INTERVAL_SECONDS = 0.25


def _server_is_ready(url: str) -> bool:
    try:
        with urlopen(url, timeout=1.0) as response:
            return 200 <= getattr(response, "status", 200) < 500
    except (OSError, URLError):
        return False


def _wait_for_server_ready(
    url: str,
    *,
    timeout_seconds: float = SERVER_READY_TIMEOUT_SECONDS,
    poll_interval_seconds: float = SERVER_READY_POLL_INTERVAL_SECONDS,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _server_is_ready(url):
            return True
        time.sleep(poll_interval_seconds)
    return False


def _open_browser_when_ready(url: str) -> None:
    if not _wait_for_server_ready(url):
        print(f"Web service is running, but the browser was not opened automatically. Visit: {url}")
        return

    try:
        opened = webbrowser.open(url)
    except Exception as exc:
        print(f"Failed to open the browser automatically: {exc}. Visit: {url}")
        return

    if not opened:
        print(f"Could not open the default browser automatically. Visit: {url}")


def _start_browser_thread(url: str) -> threading.Thread:
    browser_thread = threading.Thread(
        target=_open_browser_when_ready,
        args=(url,),
        daemon=True,
        name="tourism-route-demo-browser-launcher",
    )
    browser_thread.start()
    return browser_thread


def run() -> None:
    print(f"Starting Tourism Route Demo Web UI at {URL}")
    _start_browser_thread(URL)
    uvicorn.run("web_api:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    run()
