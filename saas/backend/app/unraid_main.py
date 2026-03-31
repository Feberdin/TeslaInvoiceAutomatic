"""
Purpose: Run the demo MVP in a single container for simple Unraid App installations.
Input/Output: Starts the background worker in a thread and exposes the FastAPI web app on port 8000.
Invariants: The same SQLite file and data directory are shared by API, worker, logs and generated PDFs.
Debug: If the Unraid app container runs but does not sync, inspect this module together with worker logs.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
from pathlib import Path

import uvicorn

from app.config import get_settings
from app.logging_config import configure_logging
from app.worker import run_worker_loop


settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


def main() -> None:
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    stop_event = threading.Event()
    worker_thread = threading.Thread(
        target=run_worker_loop,
        kwargs={"stop_event": stop_event},
        name="invoice-worker",
        daemon=True,
    )
    worker_thread.start()
    logger.info("Unraid single-container mode started. demo_mode=%s", settings.demo_mode)

    def _handle_shutdown(signum: int, _frame: object) -> None:
        logger.info("Received signal %s. Stopping worker and web server.", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    try:
        uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
    finally:
        stop_event.set()
        worker_thread.join(timeout=5)


if __name__ == "__main__":
    main()
