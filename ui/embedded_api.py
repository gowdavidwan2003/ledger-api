"""Hosting mode for Streamlit Community Cloud, which runs only the Streamlit
process. The FastAPI app is started inside it on a background thread, and the UI
still talks to it over HTTP on loopback, exactly as it would to a separate service.
Locally you run the API yourself and this module isn't used."""

import sys
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent


def start(port: int) -> str:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import uvicorn

    from app.main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True, name="ledger-api").start()

    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{url}/health", timeout=2).ok:
                return url
        except requests.ConnectionError:
            pass
        time.sleep(0.3)
    raise RuntimeError("embedded API did not become healthy within 30s")
